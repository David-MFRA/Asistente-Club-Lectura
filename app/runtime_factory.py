from __future__ import annotations

import logging
from dataclasses import dataclass

from telegram.ext import Application

import db
from app.config import create_scheduler
from app.formatting import bold, code, esc, italic
from app.services.bot_context import get_contextual_commands
from app.services.observability import ObservabilityTracker
from app.services.runtime_limits import SlidingWindowRateLimiter, TTLCache
from app.runtime.jobs import RuntimeJobs
from app.telegram.access import TelegramAccessControl
from app.telegram.callbacks import CallbackHandler
from app.telegram.commands.books import BookHandlers
from app.telegram.commands.extras import ExtraHandlers
from app.telegram.commands.meetings import MeetingHandlers
from app.telegram.commands.themes import ThemeHandlers
from app.telegram.messaging import TelegramMessagingService
from app.telegram.polling import PollAnswerHandler, WebhookHandler


@dataclass
class RuntimeServices:
    scheduler: object
    observability: ObservabilityTracker
    admin_search_limiter: SlidingWindowRateLimiter
    ai_quota_limiter: SlidingWindowRateLimiter
    ai_response_cache: TTLCache
    telegram_app: Application
    access_control: TelegramAccessControl
    messaging_service: TelegramMessagingService
    book_handlers: BookHandlers
    extra_handlers: ExtraHandlers
    meeting_handlers: MeetingHandlers
    theme_handlers: ThemeHandlers
    callback_handler: CallbackHandler
    runtime_jobs: RuntimeJobs
    poll_answer_handler: PollAnswerHandler


def build_runtime_services(
    *,
    bot_token: str,
    allowed_chat_id,
    admin_ids,
    telegram_chat_id,
    webhook_url: str,
    allowed,
    check_cooldown,
    logger: logging.Logger,
) -> RuntimeServices:
    scheduler = create_scheduler()
    observability = ObservabilityTracker()
    admin_search_limiter = SlidingWindowRateLimiter()
    ai_quota_limiter = SlidingWindowRateLimiter()
    ai_response_cache = TTLCache()

    telegram_app = Application.builder().token(bot_token).updater(None).build()
    access_control = TelegramAccessControl(
        allowed_chat_id=allowed_chat_id,
        admin_ids=admin_ids,
        get_bot=lambda: telegram_app.bot,
    )
    messaging_service = TelegramMessagingService(
        get_bot=lambda: telegram_app.bot,
        chat_id=telegram_chat_id,
        logger=logger,
    )
    book_handlers = BookHandlers(
        allowed=allowed,
        check_cooldown=check_cooldown,
        logger=logger,
        formatting={"bold": bold, "code": code, "esc": esc, "italic": italic},
    )
    extra_handlers = ExtraHandlers(
        allowed=allowed,
        check_cooldown=check_cooldown,
        logger=logger,
        formatting={"bold": bold, "esc": esc, "italic": italic},
        admin_ids=admin_ids,
        quota_limiter=ai_quota_limiter,
        response_cache=ai_response_cache,
    )
    meeting_handlers = MeetingHandlers(
        allowed=allowed,
        check_cooldown=check_cooldown,
        logger=logger,
        formatting={"bold": bold, "italic": italic, "esc": esc},
    )
    theme_handlers = ThemeHandlers(
        allowed=allowed,
        check_cooldown=check_cooldown,
        logger=logger,
        formatting={"bold": bold, "code": code, "esc": esc},
    )
    callback_handler = CallbackHandler(logger=logger)
    runtime_jobs = RuntimeJobs(
        db=db,
        scheduler=scheduler,
        telegram_app=telegram_app,
        logger=logger,
        webhook_url=webhook_url,
        admin_ids=admin_ids,
        get_contextual_commands=get_contextual_commands,
        observability=observability,
    )
    poll_answer_handler = PollAnswerHandler(db=db, logger=logger, observability=observability)
    return RuntimeServices(
        scheduler=scheduler,
        observability=observability,
        admin_search_limiter=admin_search_limiter,
        ai_quota_limiter=ai_quota_limiter,
        ai_response_cache=ai_response_cache,
        telegram_app=telegram_app,
        access_control=access_control,
        messaging_service=messaging_service,
        book_handlers=book_handlers,
        extra_handlers=extra_handlers,
        meeting_handlers=meeting_handlers,
        theme_handlers=theme_handlers,
        callback_handler=callback_handler,
        runtime_jobs=runtime_jobs,
        poll_answer_handler=poll_answer_handler,
    )


def build_webhook_handler(*, telegram_app, logger, run_async, secret_token, observability):
    return WebhookHandler(
        db=db,
        telegram_app=telegram_app,
        logger=logger,
        run_async=run_async,
        secret_token=secret_token,
        observability=observability,
    )
