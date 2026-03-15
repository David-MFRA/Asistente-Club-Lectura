from datetime import datetime
from http import HTTPStatus
from time import monotonic

from flask import Response
from telegram import Update


class PollAnswerHandler:
    def __init__(self, *, db, logger, observability=None):
        self.db = db
        self.logger = logger
        self.observability = observability

    async def __call__(self, update, context):
        started_at = monotonic()
        ok = True
        try:
            answer = update.poll_answer
            if not answer:
                return

            poll_id = answer.poll_id
            user_name = answer.user.first_name or answer.user.username or str(answer.user.id)
            new_option_ids = list(answer.option_ids)
            self.logger.info(
                "poll_answer: poll_id=%s user=%s(%s) opciones=%s",
                poll_id,
                user_name,
                answer.user.id,
                new_option_ids,
            )

            poll = self.db.get_poll_by_telegram_id(poll_id)
            if not poll or poll.get("is_closed"):
                self.db.log_event(
                    "bot",
                    f"Respuesta de encuesta ignorada para poll_id={poll_id}",
                    category="poll",
                    actor=user_name,
                    extra={"poll_id": poll_id, "reason": "missing_or_closed"},
                )
                return

            poll_type = poll.get("poll_type")
            if poll_type not in ("books", "themes"):
                return

            options = self.db.get_poll_option_mapping(poll_id)
            if not options:
                self.db.log_event(
                    "error",
                    f"Encuesta sin mapeo de opciones: {poll_id}",
                    category="poll",
                    actor=user_name,
                    extra={"poll_id": poll_id},
                )
                return

            previous_option_ids = self.db.get_poll_user_selection(poll_id, answer.user.id)
            for old_idx in previous_option_ids:
                if old_idx >= len(options):
                    continue
                entity_id = options[old_idx]
                try:
                    if poll_type == "books":
                        self.db.remove_book_vote(entity_id, user_name, answer.user.id)
                    else:
                        self.db.remove_theme_vote(entity_id, user_name, answer.user.id)
                except Exception:
                    pass

            for new_idx in new_option_ids:
                if new_idx >= len(options):
                    continue
                entity_id = options[new_idx]
                if poll_type == "books":
                    self.db.vote_book(entity_id, user_name, answer.user.id)
                else:
                    self.db.vote_theme(entity_id, user_name, answer.user.id)

            self.db.set_poll_user_selection(poll_id, answer.user.id, new_option_ids)
            self.db.log_event(
                "bot",
                f"Respuesta de encuesta procesada para poll_id={poll_id}",
                category="poll",
                actor=user_name,
                extra={
                    "poll_id": poll_id,
                    "poll_type": poll_type,
                    "new_option_ids": new_option_ids,
                    "previous_option_ids": previous_option_ids,
                },
            )
        except Exception:
            ok = False
            self.logger.exception("Error procesando poll_answer")
            raise
        finally:
            if self.observability is not None:
                self.observability.record_handler(
                    "poll_answer",
                    duration_ms=int((monotonic() - started_at) * 1000),
                    ok=ok,
                )


class WebhookHandler:
    def __init__(
        self,
        *,
        db,
        telegram_app,
        logger,
        run_async,
        secret_token,
        observability=None,
        recent_window_seconds=600,
    ):
        self.db = db
        self.telegram_app = telegram_app
        self.logger = logger
        self.run_async = run_async
        self.secret_token = secret_token
        self.observability = observability
        self.recent_window_seconds = recent_window_seconds
        self._recent_updates = {}

    async def enqueue_update(self, data):
        update_id = data.get("update_id")
        if update_id is not None:
            now = monotonic()
            expired = [key for key, ts in self._recent_updates.items() if now - ts > self.recent_window_seconds]
            for key in expired:
                self._recent_updates.pop(key, None)
            if update_id in self._recent_updates:
                self.logger.info("Webhook duplicado ignorado: update_id=%s", update_id)
                self.db.log_event(
                    "system",
                    f"Webhook duplicado ignorado: update_id={update_id}",
                    category="webhook",
                    actor="telegram",
                    extra={"update_id": update_id, "duplicate": True},
                )
                return
            self._recent_updates[update_id] = now

        update = Update.de_json(data, self.telegram_app.bot)
        await self.telegram_app.update_queue.put(update)

    def handle_request(self, flask_request):
        started_at = monotonic()
        status_code = HTTPStatus.OK
        try:
            secret_token = flask_request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not self.secret_token or secret_token != self.secret_token:
                status_code = HTTPStatus.FORBIDDEN
                self.logger.warning("Webhook rechazado por token invalido desde %s", flask_request.remote_addr)
                self.db.set_config("last_webhook_invalid_at", datetime.utcnow().isoformat())
                self.db.log_event(
                    "system",
                    "Webhook rechazado por token invalido",
                    category="webhook",
                    actor=flask_request.remote_addr or "unknown",
                )
                return Response(status=status_code)

            data = flask_request.get_json(force=True)
            self.db.set_config("last_webhook_received_at", datetime.utcnow().isoformat())
            self.run_async(self.enqueue_update(data))
            return Response(status=status_code)
        except Exception:
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            self.logger.exception("Error procesando webhook")
            self.db.log_event(
                "error",
                "Error procesando webhook",
                category="webhook",
                actor=flask_request.remote_addr or "unknown",
            )
            return Response(status=status_code)
        finally:
            if self.observability is not None:
                self.observability.record_handler(
                    "webhook",
                    duration_ms=int((monotonic() - started_at) * 1000),
                    ok=int(status_code) < 500,
                )
