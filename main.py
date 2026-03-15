import os
import re
import json
import logging
import unicodedata
import time as _time
import asyncio
from datetime import datetime, timedelta
import secrets

from flask import Flask, request, render_template, redirect, url_for, session, Response, flash, get_flashed_messages, jsonify

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ChatMemberHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

import books_api
import trivia
import recommendations
import db
from app.bootstrap import serve
from app.config import (
    ADMIN_SECRET as CFG_ADMIN_SECRET,
    ADMIN_TELEGRAM_IDS as CFG_ADMIN_TELEGRAM_IDS,
    ALLOWED_CHAT_ID as CFG_ALLOWED_CHAT_ID,
    BOT_TOKEN as CFG_BOT_TOKEN,
    FLASK_SECRET_KEY as CFG_FLASK_SECRET_KEY,
    GROUP_INVITE_LINK as CFG_GROUP_INVITE_LINK,
    TELEGRAM_CHAT_ID as CFG_TELEGRAM_CHAT_ID,
    WEBHOOK_URL as CFG_WEBHOOK_URL,
    WEBHOOK_SECRET_TOKEN as CFG_WEBHOOK_SECRET_TOKEN,
    create_scheduler,
)
from app.formatting import bold, code, esc, italic
from app.messages import DEFAULT_MESSAGES as SHARED_DEFAULT_MESSAGES, get_text as shared_get_text
from app.services.bot_context import (
    build_help_text,
    build_private_keyboard,
    build_welcome_text,
    get_contextual_commands,
)
from app.services.admin_audit import (
    audit_admin,
    flush_pending_admin_audit,
    get_admin_actor,
    get_request_ip,
    prepare_admin_audit,
    remember_admin_identity,
)
from app.services.input_limits import InputValidationError, normalize_bug_description
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
from app.telegram.registry import register_handlers
from app.web.admin.routes import register_admin_routes
from app.web.admin.messaging import (
    add_scheduled_message,
    delete_scoped_admin_message,
    delete_scheduled_message,
    preview_admin_message,
    render_admin_messages,
    render_scheduler,
    render_sent_messages,
    reset_admin_message,
    save_scoped_admin_message,
    send_custom_message,
    update_admin_message,
)
from app.web.admin.ai import (
    ask_admin_ai,
    render_ai_questions,
    render_ai_quote,
    send_ai_questions,
    send_ai_quote,
)
from app.web.admin.catalog import (
    add_meeting_date_option,
    add_waitlist_entry,
    close_meeting_date,
    create_meeting as create_meeting_page,
    delete_db_row,
    delete_meeting as delete_meeting_page,
    delete_waitlist_entry,
    edit_book as edit_book_page,
    export_books,
    render_admin_db,
    render_attendance,
    render_close_voting,
    render_gallery,
    render_history,
    render_meeting_detail,
    render_meetings,
    render_ranking,
    render_themes,
    render_waitlist,
    save_gallery_notes,
    suggest_waitlist_to_group,
    execute_sql_query,
    truncate_db_table,
    update_db_row,
    update_meeting as update_meeting_page,
)
from app.web.admin.demo import (
    clear_demo_data,
    render_demo_page,
    run_demo_step as run_admin_demo_step,
    seed_demo_data,
)
from app.web.admin.operations import (
    assign_book_to_meeting,
    send_dm_reminders,
    send_manual_meeting_info,
    send_manual_meeting_reminder,
    send_manual_reading_reminder,
    send_pin_all,
)
from app.web.admin.monitoring import render_admin_audit, render_admin_bugs, render_admin_logs, update_admin_bug
from app.web.admin.insights import (
    get_security_alerts,
    render_admin_bot_context,
    render_admin_search,
    render_admin_simulator,
    update_admin_bot_context,
)
from app.web.admin.polls import (
    close_dates_poll,
    close_poll,
    close_theme_poll,
    create_book_poll,
    create_dates_poll,
    create_theme_poll,
    pick_book_winner,
)
from app.web.admin.site import (
    activate_cycle,
    advance_to_books,
    close_cycle,
    handle_public_settings,
    pick_theme_winner,
    rename_cycle,
    render_admin_cycle,
    render_admin_help,
    render_admin_poster,
    render_public_page,
    set_cycle_theme,
    unlock_proposals,
)
from app.web.admin.wizard import wizard_announce_date, wizard_lock_and_poll, wizard_new_cycle

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# --------------------------------------------------
# DEFAULT MESSAGES — textos editables desde el admin
# --------------------------------------------------

DEFAULT_MESSAGES = dict(SHARED_DEFAULT_MESSAGES)


def get_text(key, **kwargs):
    """Compatibilidad temporal mientras se vacia main.py."""
    return shared_get_text(key, **kwargs)

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

scheduler = create_scheduler()

BOT_TOKEN         = CFG_BOT_TOKEN
WEBHOOK_URL       = CFG_WEBHOOK_URL
PORT              = int(os.environ.get("PORT", "10000"))
ADMIN_SECRET      = CFG_ADMIN_SECRET
FLASK_SECRET_KEY  = CFG_FLASK_SECRET_KEY
if not FLASK_SECRET_KEY:
    raise RuntimeError("FLASK_SECRET_KEY no disponible tras cargar configuracion")
TELEGRAM_CHAT_ID  = CFG_TELEGRAM_CHAT_ID
WEBHOOK_SECRET_TOKEN = CFG_WEBHOOK_SECRET_TOKEN
# Si se define, el bot SOLO responde a comandos de ese chat/grupo
ALLOWED_CHAT_ID   = CFG_ALLOWED_CHAT_ID
# Soporta múltiples admins separados por coma: "123456,789012"
ADMIN_TELEGRAM_IDS = CFG_ADMIN_TELEGRAM_IDS
GROUP_INVITE_LINK = CFG_GROUP_INVITE_LINK

if not BOT_TOKEN:
    raise RuntimeError("Falta BOT_TOKEN")
if not WEBHOOK_URL:
    raise RuntimeError("Falta WEBHOOK_URL")

_admin_login_attempts: dict = {}  # {remote_addr: [timestamps]}

def _check_cooldown(user_id: int, command: str, seconds: int = 20) -> bool:
    """Devuelve True si puede ejecutar (no está en cooldown). Actualiza el timestamp."""
    return access_control.check_cooldown(user_id, command, seconds)

async def _is_group_member(user_id: int) -> bool:
    """Verifica si el usuario es miembro del grupo autorizado."""
    return await access_control.is_group_member(user_id)

async def _allowed(update) -> bool:
    """Devuelve True si el update debe procesarse.
    - Chats de grupo: solo el grupo autorizado
    - Chats privados: solo si el usuario es miembro del grupo
    """
    return await access_control.allowed(update)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --------------------------------------------------
# APP INIT
# --------------------------------------------------

db.init_db()

observability = ObservabilityTracker()
admin_search_limiter = SlidingWindowRateLimiter()
ai_quota_limiter = SlidingWindowRateLimiter()
ai_response_cache = TTLCache()

telegram_app = Application.builder().token(BOT_TOKEN).updater(None).build()
access_control = TelegramAccessControl(
    allowed_chat_id=ALLOWED_CHAT_ID,
    admin_ids=ADMIN_TELEGRAM_IDS,
    get_bot=lambda: telegram_app.bot,
)
messaging_service = TelegramMessagingService(
    get_bot=lambda: telegram_app.bot,
    chat_id=TELEGRAM_CHAT_ID,
    logger=logger if "logger" in globals() else logging.getLogger(__name__),
)
book_handlers = BookHandlers(
    allowed=_allowed,
    check_cooldown=_check_cooldown,
    logger=logger if "logger" in globals() else logging.getLogger(__name__),
    formatting={"bold": bold, "code": code, "esc": esc, "italic": italic},
)
extra_handlers = ExtraHandlers(
    allowed=_allowed,
    check_cooldown=_check_cooldown,
    logger=logger if "logger" in globals() else logging.getLogger(__name__),
    formatting={"bold": bold, "esc": esc, "italic": italic},
    admin_ids=ADMIN_TELEGRAM_IDS,
    quota_limiter=ai_quota_limiter,
    response_cache=ai_response_cache,
)
meeting_handlers = MeetingHandlers(
    allowed=_allowed,
    check_cooldown=_check_cooldown,
    logger=logger if "logger" in globals() else logging.getLogger(__name__),
    formatting={"bold": bold, "italic": italic, "esc": esc},
)
theme_handlers = ThemeHandlers(
    allowed=_allowed,
    check_cooldown=_check_cooldown,
    logger=logger if "logger" in globals() else logging.getLogger(__name__),
    formatting={"bold": bold, "code": code, "esc": esc},
)
callback_handler_service = CallbackHandler(
    logger=logger if "logger" in globals() else logging.getLogger(__name__)
)
runtime_jobs = RuntimeJobs(
    db=db,
    scheduler=scheduler,
    telegram_app=telegram_app,
    logger=logger,
    webhook_url=WEBHOOK_URL,
    admin_ids=ADMIN_TELEGRAM_IDS,
    get_contextual_commands=get_contextual_commands,
    observability=observability,
)
poll_answer_handler = PollAnswerHandler(db=db, logger=logger, observability=observability)

flask_app = Flask(__name__)
flask_app.secret_key = FLASK_SECRET_KEY
flask_app.config.update(
    SESSION_COOKIE_NAME="club_admin_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=str(WEBHOOK_URL).startswith("https://"),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

# --------------------------------------------------
# MARKDOWN V2 HELPERS
# --------------------------------------------------


# --------------------------------------------------
# JINJA FILTER — datetime-local format
# --------------------------------------------------

@flask_app.template_filter('dt_local')
def dt_local_filter(value):
    """Convierte datetime a formato YYYY-MM-DDTHH:MM para input datetime-local."""
    if not value:
        return ''
    return str(value).replace(' ', 'T')[:16]

# --------------------------------------------------
# AUTH HELPERS
# --------------------------------------------------

def is_admin_logged():
    return session.get("admin_logged") is True

def require_admin():
    if not is_admin_logged():
        return redirect(url_for("admin_login"))
    return None

def _is_login_rate_limited(remote_addr: str, *, max_attempts: int = 8, window_seconds: int = 900):
    now = _time.time()
    attempts = [ts for ts in _admin_login_attempts.get(remote_addr, []) if now - ts < window_seconds]
    _admin_login_attempts[remote_addr] = attempts
    return len(attempts) >= max_attempts


def _register_login_failure(remote_addr: str):
    now = _time.time()
    attempts = [ts for ts in _admin_login_attempts.get(remote_addr, []) if now - ts < 900]
    attempts.append(now)
    _admin_login_attempts[remote_addr] = attempts
    return len(attempts)


def _clear_login_failures(remote_addr: str):
    _admin_login_attempts.pop(remote_addr, None)


def get_csrf_token():
    """Genera (o devuelve) el token CSRF de la sesión actual."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]

flask_app.jinja_env.globals["csrf_token"] = get_csrf_token

@flask_app.before_request
def csrf_protect():
    """Valida el token CSRF en todos los POST administrativos y legacy."""
    request.environ["_request_started_at"] = _time.monotonic()
    if request.method != "POST":
        return
    if request.path in ("/admin/login", "/webhook"):
        return
    if not is_admin_logged():
        return  # require_admin() ya maneja accesos sin sesión
    token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not token or token != session.get("csrf_token"):
        logger.warning("CSRF inválido en %s desde %s", request.path, request.remote_addr)
        from flask import abort
        abort(403)


@flask_app.after_request
def admin_audit_after_request(response):
    started_at = request.environ.get("_request_started_at")
    if started_at is not None:
        observability.record_request(
            request.method,
            request.path,
            response.status_code,
            int((_time.monotonic() - started_at) * 1000),
        )
    return flush_pending_admin_audit(response)

# --------------------------------------------------
# ASYNC BRIDGE — run coroutines from sync Flask routes
# --------------------------------------------------

_bot_loop = None  # set in main() before serving

def _run_async(coro):
    """Run an async coroutine from a sync Flask route (thread-safe)."""
    if _bot_loop is None:
        raise RuntimeError("Bot event loop not initialized")
    return asyncio.run_coroutine_threadsafe(coro, _bot_loop).result()


webhook_handler = WebhookHandler(
    db=db,
    telegram_app=telegram_app,
    logger=logger,
    run_async=_run_async,
    secret_token=WEBHOOK_SECRET_TOKEN,
    observability=observability,
)

# --------------------------------------------------
# BOT / GROUP HELPERS
# --------------------------------------------------

def _allowed_chat(update):
    """Si ALLOWED_CHAT_ID está configurado, solo acepta ese chat."""
    if not ALLOWED_CHAT_ID:
        return True
    return str(update.effective_chat.id) == str(ALLOWED_CHAT_ID)

def is_admin_user(update):
    """Devuelve True si el remitente está en la lista de admins."""
    if not ADMIN_TELEGRAM_IDS:
        return False
    return str(update.effective_user.id) in ADMIN_TELEGRAM_IDS

async def send_to_group(text, parse_mode=None, reply_markup=None, message_type="custom"):
    return await messaging_service.send_to_group(
        text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        message_type=message_type,
    )

async def send_and_pin(text, parse_mode=None, reply_markup=None):
    """Envía un mensaje al grupo y lo fija. Devuelve (sent, pinned)."""
    return await messaging_service.send_and_pin(
        text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )

async def unpin_group_message():
    """Desfija el mensaje actual del grupo."""
    await messaging_service.unpin_group_message()

# --------------------------------------------------
# WINNER ANNOUNCEMENT
# --------------------------------------------------

async def announce_winner(book, cycle_key=None):
    """Envía ficha completa del libro ganador al grupo."""
    if not TELEGRAM_CHAT_ID:
        return
    from html import escape as hesc
    cycle_key = cycle_key or book.get("cycle_key") or db.get_current_cycle_key()
    votes = book.get("votes", 0)
    author_line = f"✍️ <i>{hesc(book['author'])}</i>\n" if book.get("author") else ""
    lines = [
        get_text(
            "winner_announcement_message",
            audience="group",
            phase="reading",
            cycle_key=cycle_key,
            book_title=book["title"],
            author_line=author_line,
            votes=votes,
        )
    ]
    if book.get("pages"):
        lines.append(f"📄 {book['pages']} páginas")
    if book.get("language_code"):
        lines.append(f"🌐 {str(book['language_code']).upper()}")
    lines.append(f"\n🗳️ Ganó con <b>{votes} voto{'s' if votes != 1 else ''}</b>")
    if book.get("description"):
        desc = hesc(book["description"])
        if len(desc) > 600:
            desc = desc[:597] + "…"
        lines.append(f"\n📖 <i>Sinopsis</i>\n{desc}")
    lines.append("\n¡A leer se ha dicho! 🚀 Usa /asistir para apuntarte a la reunión.")
    text = "\n".join(lines)

    next_meeting = db.get_latest_scheduled_meeting(cycle_key=cycle_key)
    logger.info(
        "Anuncio ganador: libro=%s ciclo=%s meeting_id=%s",
        book.get("title"),
        cycle_key,
        next_meeting["id"] if next_meeting else None,
    )
    if next_meeting:
        keyboard = [[
            InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{next_meeting['id']}"),
            InlineKeyboardButton("❌ No asistir", callback_data=f"noattend:{next_meeting['id']}"),
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
    else:
        reply_markup = None

    try:
        if book.get("cover"):
            await telegram_app.bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID,
                photo=book["cover"],
                caption=text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            return
    except Exception:
        pass
    await send_to_group(text, parse_mode="HTML", reply_markup=reply_markup, message_type="winner_announcement")

# --------------------------------------------------
# TELEGRAM COMMANDS
# --------------------------------------------------

async def start(update, context):
    if not await _allowed(update):
        if update.effective_chat.type == "private":
            await update.message.reply_text(
                "⛔ Este bot es solo para miembros del club de lectura.\n\n"
                "Si eres miembro del grupo, asegúrate de estar unido a él en Telegram "
                "y vuelve a intentarlo.",
                parse_mode=None
            )
        return

    if update.effective_chat.type == "private":
        # Registrar al usuario como miembro conocido
        try:
            db.save_member(
                update.effective_user.id,
                update.effective_user.first_name,
                update.effective_user.username
            )
        except Exception:
            pass
        is_admin = is_admin_user(update)
        user = update.effective_user.first_name or update.effective_user.username or "miembro"
        text, commands = build_welcome_text(user, is_admin=is_admin)
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton(item) for item in row] for row in build_private_keyboard(commands)] + [[KeyboardButton("❓ /ayuda")]],
            resize_keyboard=True,
            input_field_placeholder="Elige una opción o escribe un comando…"
        )
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
        return

    raw = get_text("welcome_message", audience="group", cycle_key=db.get_current_cycle_key())
    await update.message.reply_text(raw, parse_mode="HTML")


async def ayuda_cmd(update, context):
    if not await _allowed(update): return
    raw = build_help_text(
        is_admin=is_admin_user(update),
        cycle_key=db.get_current_cycle_key(),
        audience="private" if update.effective_chat.type == "private" else "group",
    )
    await update.message.reply_text(raw, parse_mode="HTML")


async def proponer(update, context):
    return await book_handlers.proponer(update, context)


async def propuestas(update, context):
    return await book_handlers.propuestas(update, context)


async def votar(update, context):
    return await book_handlers.votar(update, context)


async def resultados(update, context):
    return await book_handlers.resultados(update, context)


async def reunion(update, context):
    return await meeting_handlers.reunion(update, context)


async def asistir(update, context):
    return await meeting_handlers.asistir(update, context)


async def noasistir(update, context):
    return await meeting_handlers.noasistir(update, context)


async def asistencia(update, context):
    return await meeting_handlers.asistencia(update, context)


async def tema(update, context):
    return await theme_handlers.tema(update, context)


async def temas(update, context):
    return await theme_handlers.temas(update, context)


async def votar_tema(update, context):
    return await theme_handlers.votar_tema(update, context)


async def trivia_cmd(update, context):
    return await extra_handlers.trivia_cmd(update, context)


async def recomendar(update, context):
    return await extra_handlers.recomendar(update, context)


# --------------------------------------------------
# INLINE KEYBOARD CALLBACK HANDLER
# --------------------------------------------------

async def button_handler(update, context):
    if not await _allowed(update):
        await update.callback_query.answer("⛔ No tienes permiso para usar esta función.", show_alert=True)
        return
    return await callback_handler_service.handle(update, context)


# --------------------------------------------------
# NEW USER COMMANDS
# --------------------------------------------------

async def libro_cmd(update, context):
    if not await _allowed(update): return
    try:
        winner = db.get_winner_book()
        if not winner:
            await update.message.reply_text("📭 No hay libro del ciclo todavía\\.", parse_mode="MarkdownV2")
            return
        lines = [f"📗 {bold('Libro del ciclo')}\n"]
        lines.append(f"{bold(winner['title'])}")
        if winner.get("author"):
            lines.append(f"✍️ {italic(winner['author'])}")
        if winner.get("pages"):
            lines.append(f"📄 {esc(str(winner['pages']))} páginas")
        if winner.get("description"):
            desc = winner["description"]
            if len(desc) > 400:
                desc = desc[:397] + "…"
            lines.append(f"\n📖 _{esc(desc)}_")
        lines.append(f"\n🗳️ {bold(str(winner.get('votes',0)))} voto{'s' if winner.get('votes',0)!=1 else ''}")
        caption = "\n".join(lines)
        if winner.get("cover"):
            try:
                await update.message.reply_photo(photo=winner["cover"], caption=caption, parse_mode="MarkdownV2")
                return
            except Exception:
                pass
        await update.message.reply_text(caption, parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /libro")
        await update.message.reply_text("⚠️ Error obteniendo el libro\\.", parse_mode="MarkdownV2")


async def acta_cmd(update, context):
    if not await _allowed(update): return
    try:
        meetings = db.get_meetings(limit=20)
        meeting = next((m for m in meetings if m.get("status") == "closed" and m.get("summary")), None)
        if not meeting:
            await update.message.reply_text("📭 No hay acta disponible todavía\\.", parse_mode="MarkdownV2")
            return
        lines = [f"📋 {bold('Acta de la reunión')}\n"]
        lines.append(f"📅 {bold(meeting['name'])}")
        if meeting.get("final_date"):
            lines.append(f"🗓️ {esc(str(meeting['final_date'])[:10])}")
        lines.append(f"\n{esc(meeting['summary'])}")
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /acta")
        await update.message.reply_text("⚠️ Error obteniendo el acta\\.", parse_mode="MarkdownV2")



async def progreso_cmd(update, context):
    if not await _allowed(update): return
    if not context.args:
        await update.message.reply_text(
            f"📖 Usa {code('/progreso páginas')}\n_Ej: /progreso 120_",
            parse_mode="MarkdownV2"
        )
        return
    try:
        pages = int(context.args[0])
        winner = db.get_winner_book()
        if not winner:
            await update.message.reply_text("📭 No hay libro del ciclo activo\\.", parse_mode="MarkdownV2")
            return
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        db.log_reading_progress(user, winner["id"], pages, update.effective_user.id)
        total = winner.get("pages")
        pct = int(pages / total * 100) if total and total > 0 else None
        bar = ""
        if pct is not None:
            filled = int(pct / 10)
            bar = "█" * filled + "░" * (10 - filled) + f" {pct}%"
        lines = [f"📖 {bold('Progreso registrado')}"]
        lines.append(f"_{esc(winner['title'])}_")
        lines.append(f"Página {bold(str(pages))}" + (f" de {bold(str(total))}" if total else ""))
        if bar:
            lines.append(f"\n{esc(bar)}")
        lines.append(f"\n_¡Sigue así\\! 💪_")
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")
    except ValueError:
        await update.message.reply_text("❌ El número de páginas debe ser un entero\\.", parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /progreso")
        await update.message.reply_text("⚠️ Error registrando progreso\\.", parse_mode="MarkdownV2")


async def estadisticas_cmd(update, context):
    if not await _allowed(update): return
    try:
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        s = db.get_user_stats(user, update.effective_user.id)
        lines = [f"📊 Tus estadísticas — {user}\n"]
        lines.append(f"📚 Propuestas: {s['proposals_total']} en total, {s['proposals_cycle']} este ciclo")
        lines.append(f"🗳️ Votos emitidos: {s['book_votes']} libros, {s['theme_votes']} temáticas")
        lines.append(f"📅 Reuniones asistidas: {s['meetings']}")
        if s.get("last_progress"):
            p = s["last_progress"]
            total_str = f" de {p['total']}" if p.get("total") else ""
            lines.append(f"📖 Último progreso: {p['pages_read']} págs{total_str} — {p['title']}")
        await update.message.reply_text("\n".join(lines), parse_mode=None)
    except Exception:
        logger.exception("Error en /estadisticas")
        await update.message.reply_text("⚠️ Error obteniendo estadísticas.", parse_mode=None)


# --------------------------------------------------
# ADMIN BOT COMMANDS (solo ADMIN_TELEGRAM_ID)
# --------------------------------------------------

async def admin_ayuda_cmd(update, context):
    if not is_admin_user(update): return
    text = (
        "🔐 Comandos de administrador\n\n"
        "🔄 Ciclos\n"
        "  /ciclo — Ver ciclo activo\n"
        "  /nuevo_ciclo [nombre] — Crear nuevo ciclo\n"
        "  /cerrar_ciclo — Cerrar ciclo actual\n\n"
        "📣 Mensajes\n"
        "  /anuncio <texto> — Enviar mensaje al grupo\n"
        "  /anunciar_ganador — Anunciar libro ganador\n\n"
        "🗳️ Encuestas\n"
        "  /encuesta_libros — Lanzar encuesta de libros\n"
        "  /encuesta_temas — Lanzar encuesta de temáticas\n\n"
        "🔔 Recordatorios\n"
        "  /enviar_recordatorio — Recordatorio de reunión\n"
        "  /enviar_lectura — Recordatorio de lectura\n\n"
        "📌 Fijar mensajes\n"
        "  /fijar — Fija el recordatorio de reunión\n"
        "  /desfijar — Desfija el mensaje actual"
    )
    await update.message.reply_text(text, parse_mode=None)


async def ciclo_cmd(update, context):
    if not is_admin_user(update): return
    logger.info("/ciclo: solicitado por admin user_id=%d", update.effective_user.id)
    cycle = db.get_current_cycle_key()
    books = db.get_book_proposals()
    themes = db.get_themes()
    winner = db.get_winner_book()
    lines = [
        f"🔄 {bold('Ciclo activo')}: {code(cycle)}\n",
        f"📚 Propuestas de libros: {bold(str(len(books)))}",
        f"🏷️ Temáticas: {bold(str(len(themes)))}",
    ]
    if winner:
        lines.append(f"🏆 Libro líder: _{esc(winner['title'])}_")
    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


async def nuevo_ciclo_cmd(update, context):
    if not is_admin_user(update): return
    logger.info("/nuevo_ciclo: admin user_id=%d args=%r", update.effective_user.id, context.args)
    from app.web.admin.site import _suggested_cycle_name as _sug
    name = " ".join(context.args).strip() if context.args else None
    if not name:
        name = _sug()
    db.add_active_cycle(name)
    db.unlock_cycle_proposals(name)
    db.set_cycle_theme(name, "")
    from app.web.admin.polls import _set_phase
    _set_phase("setup")
    db.log_event("admin", f"Ciclo «{name}» activado vía bot", category="cycle", actor="admin")
    await update.message.reply_text(
        f"✅ {bold('Nuevo ciclo creado')}: {code(name)}\n"
        f"_A partir de ahora las propuestas y temáticas se guardan en este ciclo\\._\n\n"
        f"_Añade temáticas con /tema y lanza /encuesta\\_temas cuando estés listo\\._",
        parse_mode="MarkdownV2"
    )
    # Announce in group
    try:
        from html import escape as _hesc
        msg = (
            f"🔄 <b>¡Nuevo ciclo: {_hesc(name)}!</b>\n\n"
            f"Comienza un nuevo ciclo de lectura. "
            f"Primero vamos a <b>elegir la temática</b> que guiará las propuestas.\n\n"
            f"📊 Pronto se abrirá la encuesta de temáticas. ¡Estad atentos!"
        )
        await send_to_group(msg, parse_mode="HTML", message_type="new_cycle")
    except Exception:
        logger.exception("Error enviando mensaje de nuevo ciclo al grupo desde bot")


async def cerrar_ciclo_cmd(update, context):
    if not is_admin_user(update): return
    cycle = db.get_current_cycle_key()
    logger.info("/cerrar_ciclo: admin user_id=%d ciclo=%s", update.effective_user.id, cycle)
    db.close_cycle(cycle)
    await update.message.reply_text(
        f"🔒 {bold('Ciclo cerrado')}: {code(cycle)}\n"
        f"_Todas las propuestas y temáticas han sido desactivadas\\._\n"
        f"_Usa /nuevo\\_ciclo para empezar uno nuevo\\._",
        parse_mode="MarkdownV2"
    )


async def anuncio_cmd(update, context):
    if not is_admin_user(update): return
    text = " ".join(context.args).strip() if context.args else ""
    logger.info("/anuncio: admin user_id=%d (%d chars)", update.effective_user.id, len(text))
    if not text:
        await update.message.reply_text("❌ Usa: /anuncio <texto del mensaje>", parse_mode=None)
        return
    ok = await send_to_group(text, parse_mode=None)
    if ok:
        await update.message.reply_text("✅ Mensaje enviado al grupo\\.", parse_mode="MarkdownV2")
    else:
        await update.message.reply_text("❌ Error enviando el mensaje\\.", parse_mode="MarkdownV2")


async def anunciar_ganador_cmd(update, context):
    if not is_admin_user(update): return
    logger.info("/anunciar_ganador: admin user_id=%d", update.effective_user.id)
    tied = db.get_tied_books()
    if len(tied) > 1:
        tie_msg = (
            f"⚖️ ¡Hay empate en la votación!\n\n"
            f"Los siguientes libros han quedado empatados con {tied[0]['votes']} votos:\n"
        )
        for b in tied:
            tie_msg += f"  📖 {b['title']}" + (f" — {b['author']}" if b.get('author') else "") + "\n"
        tie_msg += "\n🔁 Lanzando encuesta de desempate..."
        await send_to_group(tie_msg, parse_mode=None, message_type="tie_notification")
        options = []
        for b in tied[:10]:
            label = b["title"]
            if b.get("author"):
                label = f"{b['title']} — {b['author']}"
            options.append(label[:100])
        if TELEGRAM_CHAT_ID:
            tie_poll = await telegram_app.bot.send_poll(
                chat_id=TELEGRAM_CHAT_ID,
                question=f"⚖️ Desempate — ¿Cuál de estos {len(tied)} libros leemos?",
                options=options,
                is_anonymous=False,
                allows_multiple_answers=False,
            )
            cycle = db.get_current_cycle_key()
            db.save_poll(chat_id=tie_poll.chat_id, message_id=tie_poll.message_id,
                         poll_id=tie_poll.poll.id, poll_type="books", cycle_key=cycle)
            db.set_poll_option_mapping(tie_poll.poll.id, "books", [b["proposal_id"] for b in tied[:10]])
        await update.message.reply_text(f"⚖️ Empate detectado. Encuesta de desempate lanzada.", parse_mode=None)
        return
    winner = db.get_winner_book()
    if not winner:
        await update.message.reply_text("📭 No hay libro ganador todavía\\.", parse_mode="MarkdownV2")
        return
    await announce_winner(winner, cycle_key=db.get_current_cycle_key())
    await update.message.reply_text("✅ Anuncio enviado al grupo\\.", parse_mode="MarkdownV2")


async def enviar_recordatorio_cmd(update, context):
    if not is_admin_user(update): return
    logger.info("/enviar_recordatorio: admin user_id=%d", update.effective_user.id)
    await send_meeting_reminder()
    await update.message.reply_text("✅ Recordatorio de reunión enviado\\.", parse_mode="MarkdownV2")


async def enviar_lectura_cmd(update, context):
    if not is_admin_user(update): return
    logger.info("/enviar_lectura: admin user_id=%d", update.effective_user.id)
    await send_reading_reminder()
    await update.message.reply_text("✅ Recordatorio de lectura enviado\\.", parse_mode="MarkdownV2")


async def encuesta_libros_cmd(update, context):
    """Admin: lanza encuesta de libros desde el chat."""
    if not is_admin_user(update): return
    try:
        cycle = db.get_current_cycle_key()
        books = db.get_book_proposals(cycle)
        if len(books) < 2:
            await update.message.reply_text("❌ Necesitas al menos 2 propuestas.", parse_mode=None)
            return
        if not TELEGRAM_CHAT_ID:
            await update.message.reply_text("❌ TELEGRAM_CHAT_ID no configurado.", parse_mode=None)
            return
        db.lock_cycle_proposals(cycle)
        options = []
        for b in books[:10]:
            label = b["title"]
            if b.get("author"):
                label = f"{b['title']} — {b['author']}"
            options.append(label[:100])
        msg = await telegram_app.bot.send_poll(
            chat_id=TELEGRAM_CHAT_ID,
            question="📚 ¿Qué libro leemos este mes?",
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        db.save_poll(chat_id=msg.chat_id, message_id=msg.message_id,
                     poll_id=msg.poll.id, poll_type="books", cycle_key=cycle)
        db.set_poll_option_mapping(msg.poll.id, "books", [b["proposal_id"] for b in books[:10]])
        from app.web.admin.polls import _set_phase
        _set_phase("book_voting")
        logger.info("/encuesta_libros: encuesta lanzada poll_id=%s ciclo=%s opciones=%d", msg.poll.id, cycle, len(options))
        await update.message.reply_text("✅ Encuesta de libros lanzada.", parse_mode=None)
    except Exception:
        logger.exception("Error en /encuesta_libros")
        await update.message.reply_text("⚠️ Error lanzando la encuesta.", parse_mode=None)


async def encuesta_temas_cmd(update, context):
    """Admin: lanza encuesta de temáticas desde el chat."""
    if not is_admin_user(update): return
    try:
        cycle = db.get_current_cycle_key()
        themes = db.get_themes(cycle)
        if len(themes) < 2:
            await update.message.reply_text("❌ Necesitas al menos 2 temáticas.", parse_mode=None)
            return
        if not TELEGRAM_CHAT_ID:
            await update.message.reply_text("❌ TELEGRAM_CHAT_ID no configurado.", parse_mode=None)
            return
        options = [t["name"][:100] for t in themes[:10]]
        msg = await telegram_app.bot.send_poll(
            chat_id=TELEGRAM_CHAT_ID,
            question="🏷️ ¿Qué temática elegimos para el próximo ciclo?",
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        db.save_poll(chat_id=msg.chat_id, message_id=msg.message_id,
                     poll_id=msg.poll.id, poll_type="themes", cycle_key=cycle)
        db.set_poll_option_mapping(msg.poll.id, "themes", [t["id"] for t in themes[:10]])
        from app.web.admin.polls import _set_phase
        _set_phase("theme_voting")
        logger.info("/encuesta_temas: encuesta lanzada poll_id=%s ciclo=%s opciones=%d", msg.poll.id, cycle, len(options))
        await update.message.reply_text("✅ Encuesta de temáticas lanzada.", parse_mode=None)
    except Exception:
        logger.exception("Error en /encuesta_temas")
        await update.message.reply_text("⚠️ Error lanzando la encuesta.", parse_mode=None)


# --------------------------------------------------
# SCHEDULED REMINDERS
# --------------------------------------------------

async def send_meeting_reminder():
    """Recordatorio semanal con días restantes y ritmo de páginas. Incluye todas las reuniones activas."""
    if db.get_config("reminder_weekly_enabled", "1") == "0":
        logger.debug("Recordatorio semanal deshabilitado, saltando")
        return
    all_meetings = db.get_meetings(limit=10)
    now = datetime.utcnow()
    upcoming = []
    for m in all_meetings:
        if m.get("status") == "closed":
            continue
        upcoming.append(m)
    if not upcoming:
        logger.debug("Recordatorio semanal: no hay reuniones activas")
        return
    logger.info("Recordatorio semanal: enviando para %d reunión(es)", len(upcoming))

    if len(upcoming) == 1:
        # Modo reunión única (comportamiento original)
        meeting = upcoming[0]
        asistentes = db.get_attendance(meeting["id"])
        book = None
        if meeting.get("book_id"):
            book = db.get_book_by_id(meeting["book_id"])
        if not book:
            book = db.get_winner_book()

        days_left = None
        if meeting.get("final_date"):
            try:
                final_dt = meeting["final_date"]
                if isinstance(final_dt, str):
                    final_dt = datetime.fromisoformat(final_dt)
                days_left = (final_dt - now).days
            except Exception:
                pass

        from html import escape as hesc
        fecha_str = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
        names = "\n".join(f"  ✅ {hesc(a)}" for a in asistentes) if asistentes else "Nadie apuntado todavía"
        parts = [
            get_text(
                "meeting_reminder_message",
                audience="group",
                phase="reading",
                cycle_key=meeting.get("cycle_key"),
                meeting_name=meeting["name"],
                meeting_date=fecha_str,
                location_line=f"📍 <b>{hesc(meeting['location'])}</b>\n" if meeting.get("location") else "",
                attendee_count=len(asistentes),
                book_title=(book or {}).get("title", "Sin libro"),
            )
        ]

        if meeting.get("notes"):
            parts.append(f"📝 <i>{hesc(meeting['notes'])}</i>")

        if days_left is not None:
            if days_left > 0:
                parts.append(f"⏳ Faltan <b>{days_left} día{'s' if days_left != 1 else ''}</b> para la reunión")
            elif days_left == 0:
                parts.append("🔔 <b>¡La reunión es HOY!</b>")
            else:
                parts.append(f"🔒 La reunión ya pasó hace {abs(days_left)} días")

        if book and book.get("title"):
            book_section = f"\n📗 <b>{hesc(book['title'])}</b>"
            if book.get("author"):
                book_section += f"\n✍️ <i>{hesc(book['author'])}</i>"

            pages = book.get("pages")
            if pages and days_left and days_left > 0:
                total_days = 30
                elapsed    = max(0, total_days - days_left)
                pages_now  = int(pages * elapsed / total_days)
                daily_pace = max(1, int(pages / total_days))
                book_section += (
                    f"\n\n📊 <b>Ritmo de lectura</b>\n"
                    f"Para estar al día: <b>{pages_now} de {pages} págs</b>\n"
                    f"<i>Unas {daily_pace} páginas al día — ¡tú puedes!</i>"
                )
            progress_list = db.get_reading_progress(book["id"])
            if progress_list and pages:
                book_section += "\n\n📖 <b>Progreso del grupo</b>"
                for p in progress_list[:5]:
                    pct = int(p["pages_read"] / pages * 100) if pages > 0 else 0
                    book_section += f"\n  • {hesc(p['user_name'])}: {p['pages_read']} págs ({pct}%)"
            parts.append(book_section)

        parts.append(f"\n👥 <b>Apuntados ({len(asistentes)})</b>:\n{names}")
        parts.append("¿Aún no te has apuntado? Usa /asistir 📖")

        keyboard = [
            [
                InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{meeting['id']}"),
                InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
            ]
        ]
        if meeting.get("book_id"):
            keyboard.append([InlineKeyboardButton("📗 Ver libro", callback_data=f"bookinfo:{meeting['book_id']}")])

        await send_to_group("\n".join(parts), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        # Modo multi-reunión: mensaje combinado con todas las reuniones activas
        from html import escape as hesc
        parts = ["📌 <b>Reuniones activas del club</b>"]
        keyboard = []
        for idx, meeting in enumerate(upcoming[:5], 1):
            asistentes = db.get_attendance(meeting["id"])
            fecha_str = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
            location_line = f"\n📍 {hesc(meeting['location'])}" if meeting.get("location") else ""
            parts.append(
                f"\n<b>{idx}. {hesc(meeting['name'])}</b>\n"
                f"🗓 <b>{hesc(fecha_str)}</b>"
                f"{location_line}\n"
                f"👥 {len(asistentes)} confirmado{'s' if len(asistentes) != 1 else ''}"
            )
            short_name = meeting['name'][:20]
            keyboard.append([
                InlineKeyboardButton(f"✅ {short_name}", callback_data=f"attend:{meeting['id']}"),
                InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
            ])

        parts.append("\nUsa /asistir para apuntarte a una reunión concreta 📖")
        await send_to_group("\n".join(parts), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def send_reading_reminder():
    """Recordatorio de lectura cada 2 días."""
    if db.get_config("reminder_reading_enabled", "1") == "0":
        logger.debug("Recordatorio de lectura deshabilitado, saltando")
        return
    meeting = db.get_latest_scheduled_meeting()
    # Usar el libro de la reunión, no el ganador del ciclo
    book = None
    if meeting and meeting.get("book_id"):
        book = db.get_book_by_id(meeting["book_id"])
    if not book:
        book = db.get_winner_book()
    if not book:
        logger.debug("Recordatorio de lectura: sin libro activo, saltando")
        return
    logger.info("Recordatorio de lectura: enviando para «%s»", book["title"])
    days_left = None
    if meeting and meeting.get("final_date"):
        try:
            final_dt = meeting["final_date"]
            if isinstance(final_dt, str):
                final_dt = datetime.fromisoformat(final_dt)
            days_left = max(0, (final_dt - datetime.utcnow()).days)
        except Exception:
            days_left = None
    from html import escape as hesc
    fecha = str(meeting["final_date"])[:16] if meeting and meeting.get("final_date") else "Sin fecha"
    reunion_name = meeting["name"] if meeting else "Sin reunión"
    author_line = f"✍️ <i>{hesc(book['author'])}</i>\n" if book.get("author") else ""
    parts = [
        get_text(
            "reading_reminder_message",
            audience="group",
            phase="reading",
            cycle_key=meeting.get("cycle_key") if meeting else db.get_current_cycle_key(),
            book_title=book["title"],
            author_line=author_line,
            meeting_name=reunion_name,
            meeting_date=fecha,
            days_left=days_left if days_left is not None else "?",
            pages=book.get("pages") or 0,
            daily_pages=max(1, int((book.get("pages") or 1) / 30)),
        )
    ]
    pages = book.get("pages")
    if pages and days_left is not None and days_left > 0:
        total_days = 30
        elapsed = max(0, total_days - days_left)
        pages_now = min(pages, int(pages * elapsed / total_days))
        daily_pace = max(1, int(pages / total_days))
        parts.append(f"\n📊 <b>Para ir al día:</b> {pages_now} de {pages} páginas.")
        parts.append(f"⏱️ <i>Unas {daily_pace} páginas al día.</i>")
    parts.append("\n✨ ¡A leer se ha dicho!")
    text = "\n".join(parts)
    keyboard = []
    if meeting:
        keyboard.append([
            InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{meeting['id']}"),
            InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
        ])
    await send_to_group(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)


# --------------------------------------------------
# DAY-BEFORE REMINDER
# --------------------------------------------------

async def send_day_before_reminder():
    """Recordatorio cuando la reunión es mañana o hoy."""
    if db.get_config("reminder_daybefore_enabled", "1") == "0":
        logger.debug("Recordatorio día-antes deshabilitado, saltando")
        return
    meeting = db.get_latest_scheduled_meeting()
    if not meeting or not meeting.get("final_date"):
        return
    final_dt = meeting["final_date"]
    if isinstance(final_dt, str):
        final_dt = datetime.fromisoformat(final_dt)
    days_left = (final_dt - datetime.utcnow()).days
    if days_left not in (0, 1):
        logger.debug("Recordatorio día-antes: reunión en %d días, no aplica", days_left)
        return
    logger.info("Recordatorio día-antes: días_restantes=%d reunión=%s", days_left, meeting["name"])
    from html import escape as hesc
    winner = db.get_winner_book()
    asistentes = db.get_attendance(meeting["id"])
    if days_left == 1:
        header = "🔔 <b>¡La reunión es MAÑANA!</b>"
    else:
        header = "🚨 <b>¡La reunión es HOY!</b>"
    parts = [
        f"{header}\n\n<b>{hesc(meeting['name'])}</b>\n🗓 <b>{hesc(str(final_dt)[:16])}</b>",
    ]
    if meeting.get("location"):
        parts.append(f"📍 <b>{hesc(meeting['location'])}</b>")
    if winner:
        parts.append(f"📗 <b>{hesc(winner['title'])}</b>")
    names = "\n".join(f"  ✅ {hesc(a)}" for a in asistentes) if asistentes else "Nadie apuntado aún"
    parts.append(f"\n👥 <b>Apuntados ({len(asistentes)})</b>:\n{names}")
    parts.append("¿Aún no te has apuntado? Usa /asistir 📚")
    keyboard = [
        [
            InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{meeting['id']}"),
            InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
        ]
    ]
    await send_to_group("\n".join(parts), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def send_scheduled_messages():
    """Envía mensajes programados pendientes."""
    try:
        pending = db.get_pending_scheduled_messages()
        for msg in pending:
            await send_to_group(msg["text"], parse_mode="HTML", message_type="scheduled")
            db.mark_scheduled_message_sent(msg["id"])
            logger.info("Mensaje programado #%s enviado", msg["id"])
    except Exception:
        logger.exception("Error en send_scheduled_messages")


async def _auto_close_cycle():
    """Cierra automáticamente el ciclo al final del día de la reunión."""
    try:
        phase = db.get_config("cycle_phase") or "setup"
        if phase in ("closed", "setup"):
            return
        meeting = db.get_latest_scheduled_meeting()
        if not meeting or not meeting.get("final_date"):
            return
        final_dt = meeting["final_date"]
        if isinstance(final_dt, str):
            final_dt = datetime.fromisoformat(final_dt)
        if hasattr(final_dt, 'tzinfo') and final_dt.tzinfo is None:
            final_dt = final_dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
        today = datetime.now(tz=final_dt.tzinfo).date() if final_dt.tzinfo else datetime.utcnow().date()
        if final_dt.date() != today:
            return
        # It's meeting day — close the cycle
        cycle = db.get_current_cycle_key()
        cycle_theme = db.get_cycle_theme(cycle) or None
        db.close_cycle(cycle)
        db.set_config("cycle_phase", "closed")
        try:
            db.auto_add_runners_up_to_waitlist(cycle_key=cycle, cycle_theme=cycle_theme)
        except Exception:
            pass
        from html import escape as hesc
        farewell = (
            f"🎉 <b>¡Hasta aquí el ciclo {hesc(cycle)}!</b>\n\n"
            f"Ha sido un placer leer juntos. 📚\n"
            f"Gracias a todos los que habéis participado.\n\n"
            f"Pronto abriremos el siguiente ciclo. ¡Hasta entonces! 👋"
        )
        await send_to_group(farewell, parse_mode="HTML", message_type="cycle_closed")
        db.log_event("scheduler", f"Ciclo «{cycle}» cerrado automáticamente al terminar el día de reunión", category="cycle", actor="scheduler")
        logger.info("Ciclo «%s» cerrado automáticamente por el scheduler", cycle)
    except Exception:
        logger.exception("Error en _auto_close_cycle")


# --------------------------------------------------
# BOT ADDED TO NEW CHAT
# --------------------------------------------------

async def handle_my_chat_member(update, context):
    """Se activa cuando el bot entra o sale de un grupo."""
    result = update.my_chat_member
    if not result:
        return
    new_status = result.new_chat_member.status
    chat = result.chat
    if new_status not in ("member", "administrator"):
        return

    if ALLOWED_CHAT_ID and str(chat.id) != str(ALLOWED_CHAT_ID):
        # Chat no autorizado — avisar y no hacer nada más
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    "👋 Hola! Soy el bot del *Club de Lectura*\\.\n\n"
                    "⚠️ Estoy configurado para operar en un grupo específico\\. "
                    "Mis comandos de gestión solo funcionarán allí\\.\n\n"
                    "_Para activarme aquí, configura la variable `ALLOWED_CHAT_ID` "
                    f"con el ID de este chat: `{chat.id}`_"
                ),
                parse_mode="MarkdownV2"
            )
        except Exception:
            logger.exception("Error enviando aviso a chat no autorizado")
    else:
        # Chat autorizado o sin restricción — bienvenida
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    f"📚 {bold('¡Hola!')} Soy el bot del Club de Lectura\\.\n\n"
                    f"Usa /start para ver todos los comandos disponibles\\. 🚀"
                ),
                parse_mode="MarkdownV2"
            )
        except Exception:
            logger.exception("Error enviando bienvenida al grupo")


async def fijar_cmd(update, context):
    """Admin: fija el recordatorio de reunión."""
    if not is_admin_user(update): return
    meeting = db.get_latest_scheduled_meeting()
    if not meeting:
        await update.message.reply_text("📭 No hay reunión activa.", parse_mode=None)
        return
    asistentes = db.get_attendance(meeting["id"])
    fecha = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
    lines = [
        f"📌 REUNIÓN — {meeting['name']}\n",
        f"📆 {fecha}",
    ]
    if meeting.get("location"):
        lines.append(f"📍 {meeting['location']}")
    winner = db.get_winner_book()
    if winner:
        lines.append(f"📗 {winner['title']}")
    lines.append(f"👥 Apuntados: {len(asistentes)}")
    lines.append("\nUsa /asistir para apuntarte · /noasistir para quitarte")
    keyboard = [[
        InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{meeting['id']}"),
        InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
    ]]
    sent, pinned = await send_and_pin("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
    if not sent:
        await update.message.reply_text("❌ Error enviando el mensaje.", parse_mode=None)
    elif pinned:
        await update.message.reply_text("📌 Mensaje enviado y fijado en el grupo.", parse_mode=None)
    else:
        await update.message.reply_text(
            "✅ Mensaje enviado al grupo, pero no se ha podido fijar.\n"
            "⚠️ Para fijar mensajes el bot debe ser administrador del grupo con permiso de «Fijar mensajes».",
            parse_mode=None
        )


async def desfijar_cmd(update, context):
    """Admin: desfija el mensaje actual."""
    if not is_admin_user(update): return
    await unpin_group_message()
    await update.message.reply_text("📌 Mensaje desfijado.", parse_mode=None)


async def preguntas_cmd(update, context):
    return await extra_handlers.preguntas_cmd(update, context)


async def lista_espera_cmd(update, context):
    if not await _allowed(update): return
    try:
        theme = " ".join(context.args).strip() if context.args else None
        books = db.get_waitlist(theme=theme)
        if not books:
            msg = "📭 No hay libros en la lista de espera" + (f" para la temática «{theme}»" if theme else "") + "."
            await update.message.reply_text(msg, parse_mode=None)
            return
        lines = ["📚 Lista de espera — libros pendientes\n"]
        if theme:
            lines[0] = f"📚 Lista de espera — temática: {theme}\n"
        current_theme = None
        for b in books[:15]:
            if b.get('cycle_theme') != current_theme:
                current_theme = b.get('cycle_theme')
                if current_theme:
                    lines.append(f"\n🏷️ {current_theme}")
            author_str = f" — {b['author']}" if b.get('author') else ""
            pos_str = f" (#{b['position_at_time']})" if b.get('position_at_time') else ""
            lines.append(f"  📖 {b['title']}{author_str}{pos_str}")
        lines.append("\nUsa /lista_espera [temática] para filtrar por temática.")
        await update.message.reply_text("\n".join(lines), parse_mode=None)
    except Exception:
        logger.exception("Error en /lista_espera")
        await update.message.reply_text("⚠️ Error obteniendo la lista de espera.", parse_mode=None)


async def proponer_fecha_cmd(update, context):
    if not await _allowed(update): return
    if not _check_cooldown(update.effective_user.id, "proponer_fecha", 30):
        await update.message.reply_text("⏳ Espera unos segundos.", parse_mode=None)
        return
    try:
        args = " ".join(context.args).strip()
        if not args:
            await update.message.reply_text(
                "📅 Uso: /proponer_fecha DD/MM HH:MM\nEjemplo: /proponer_fecha 15/04 19:30",
                parse_mode=None
            )
            return
        m = re.match(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?:\s+(\d{1,2}):(\d{2}))?', args)
        if not m:
            await update.message.reply_text("❌ Formato inválido. Usa: /proponer_fecha DD/MM HH:MM", parse_mode=None)
            return
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else datetime.now().year
        if year < 100: year += 2000
        hour = int(m.group(4)) if m.group(4) else 19
        minute = int(m.group(5)) if m.group(5) else 0
        try:
            proposed_dt = datetime(year, month, day, hour, minute)
        except ValueError:
            await update.message.reply_text("❌ Fecha inválida.", parse_mode=None)
            return
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text("📭 No hay reunión activa para proponer una fecha.", parse_mode=None)
            return
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        result = db.propose_meeting_date(meeting['id'], proposed_dt, user)
        if result:
            fecha_str = proposed_dt.strftime("%d/%m/%Y a las %H:%M")
            await update.message.reply_text(
                f"📅 ¡Fecha propuesta!\n\n"
                f"📌 Reunión: {meeting['name']}\n"
                f"📆 Fecha propuesta: {fecha_str}\n"
                f"👤 Por: {user}\n\n"
                f"El admin cerrará la fecha definitiva pronto.",
                parse_mode=None
            )
        else:
            await update.message.reply_text(
                f"ℹ️ Esa fecha ya estaba propuesta para {meeting['name']}.",
                parse_mode=None
            )
    except Exception:
        logger.exception("Error en /proponer_fecha")
        await update.message.reply_text("⚠️ Error al proponer la fecha.", parse_mode=None)


async def cita_cmd(update, context):
    return await extra_handlers.cita_cmd(update, context)


async def bug_cmd(update, context):
    """Permite a los usuarios reportar un bug o problema."""
    if not await _allowed(update): return
    if not _check_cooldown(update.effective_user.id, "bug", 60):
        await update.message.reply_text("⏳ Espera un momento antes de enviar otro reporte.", parse_mode=None)
        return
    description = " ".join(context.args).strip() if context.args else ""
    if not description:
        context.user_data["pending_bug"] = True
        context.user_data["pending_bug_started_at"] = _time.time()
        await update.message.reply_text(
            "Cuentame brevemente el problema y lo guardo como reporte.\n\n"
            "Ejemplo: El comando /votar no responde o la encuesta no se cierra.",
            parse_mode=None
        )
        return
    user = update.effective_user
    username = user.username or user.first_name or str(user.id)
    try:
        description = normalize_bug_description(description)
        report_id = db.create_bug_report(user.id, username, description)
        db.log_event("bot", f"Bug reportado por {username}: {description[:80]}", category="bug", actor=username)
        await update.message.reply_text(
            f"✅ Reporte #{report_id} recibido. ¡Gracias por avisar!\n"
            f"El equipo lo revisará pronto.",
            parse_mode=None
        )
        # Notificar al admin por DM si está configurado
        for admin_id in ADMIN_TELEGRAM_IDS:
            try:
                await telegram_app.bot.send_message(
                    chat_id=admin_id,
                    text=f"🐛 Nuevo bug #{report_id}\n👤 {username}\n\n{description}",
                    parse_mode=None
                )
            except Exception:
                pass
    except InputValidationError as exc:
        await update.message.reply_text(str(exc), parse_mode=None)
    except Exception:
        logger.exception("Error en /bug")
        await update.message.reply_text("⚠️ Error enviando el reporte.", parse_mode=None)


def _bot_actor_label(update):
    user = getattr(update, "effective_user", None)
    if not user:
        return "desconocido"
    return user.username or user.first_name or str(user.id)


def _clear_pending_flow(context, actor, command_name):
    user_data = getattr(context, "user_data", None)
    if user_data is None:
        return []
    pending_map = {
        "pending_proponer": "proponer",
        "pending_tema": "tema",
        "pending_bug": "bug",
    }
    cleared = []
    now = _time.time()
    for pending_key, flow_name in pending_map.items():
        if not user_data.get(pending_key):
            continue
        started_at = user_data.pop(f"{pending_key}_started_at", None)
        user_data.pop(pending_key, None)
        duration_ms = int((now - started_at) * 1000) if started_at else None
        db.log_event(
            "bot",
            f"Flujo {flow_name} abandonado por /{command_name}",
            category="flow",
            actor=actor,
            extra={
                "flow": flow_name,
                "abandoned_by": command_name,
                "duration_ms": duration_ms,
            },
        )
        cleared.append(flow_name)
    return cleared


def _trace_bot_handler(name, handler, *, category="command", clear_pending=True):
    async def _wrapped(update, context):
        actor = _bot_actor_label(update)
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        if user:
            try:
                db.save_member(
                    user.id,
                    user.first_name,
                    user.username,
                )
            except Exception:
                pass
        if clear_pending:
            _clear_pending_flow(context, actor, name)
        started_at = _time.monotonic()
        ok = False
        try:
            result = await handler(update, context)
            ok = True
            return result
        finally:
            duration_ms = int((_time.monotonic() - started_at) * 1000)
            observability.record_handler(name, duration_ms=duration_ms, ok=ok, actor=actor)
            db.log_event(
                "bot",
                f"Handler {name} ejecutado",
                category=category,
                actor=actor,
                extra={
                    "handler": name,
                    "chat_id": getattr(chat, "id", None),
                    "chat_type": getattr(chat, "type", None),
                    "duration_ms": duration_ms,
                    "ok": ok,
                },
            )

    return _wrapped


async def private_text_handler(update, context):
    """Responde a mensajes de texto libre en chats privados guiando al usuario."""
    if update.effective_chat.type != "private":
        return
    if not await _allowed(update):
        await update.message.reply_text(
            "⛔ Este bot es solo para miembros del club de lectura.",
            parse_mode=None
        )
        return

    text = (update.message.text or "").strip()
    text_lower = text.lower()
    u = update.effective_user
    actor = _bot_actor_label(update)
    logger.debug("private_text: user=%s id=%d text=%r", u.first_name or u.username, u.id, text[:80])

    # Handle pending /proponer state
    if context.user_data.get("pending_proponer"):
        started_at = context.user_data.pop("pending_proponer_started_at", None)
        context.user_data.pop("pending_proponer", None)
        if text:
            logger.info("private_text: pending_proponer resuelto con «%s» por user_id=%d", text, u.id)
            db.log_event(
                "bot",
                "Flujo proponer completado por texto libre",
                category="flow",
                actor=actor,
                extra={"duration_ms": int((_time.time() - started_at) * 1000) if started_at else None},
            )
            # Reuse proponer logic with the text as title
            context.args = text.split()
            await book_handlers.proponer(update, context)
        else:
            await update.message.reply_text("Escribe el título del libro para proponerlo.", parse_mode=None)
        return

    # Handle pending /tema state
    if context.user_data.get("pending_tema"):
        started_at = context.user_data.pop("pending_tema_started_at", None)
        context.user_data.pop("pending_tema", None)
        if text:
            logger.info("private_text: pending_tema resuelto con «%s» por user_id=%d", text, u.id)
            db.log_event(
                "bot",
                "Flujo tema completado por texto libre",
                category="flow",
                actor=actor,
                extra={"duration_ms": int((_time.time() - started_at) * 1000) if started_at else None},
            )
            context.args = [text]
            await theme_handlers.tema(update, context)
        else:
            await update.message.reply_text("Escribe el nombre de la temática para proponerla.", parse_mode=None)
        return

    if context.user_data.get("pending_bug"):
        started_at = context.user_data.pop("pending_bug_started_at", None)
        context.user_data.pop("pending_bug", None)
        if text:
            try:
                text = normalize_bug_description(text)
                report_id = db.create_bug_report(
                    user_id=u.id,
                    username=u.username or u.first_name or str(u.id),
                    description=text,
                )
                db.log_event(
                    "bot",
                    f"Bug report #{report_id} enviado por texto libre",
                    category="bug",
                    actor=actor,
                    extra={"duration_ms": int((_time.time() - started_at) * 1000) if started_at else None},
                )
                await update.message.reply_text(
                    f"Gracias. He guardado tu reporte como #{report_id}.",
                    parse_mode=None,
                )
            except InputValidationError as exc:
                await update.message.reply_text(str(exc), parse_mode=None)
            except Exception:
                logger.exception("Error completando flujo /bug por texto libre")
                await update.message.reply_text("No pude guardar el reporte ahora mismo.", parse_mode=None)
        else:
            await update.message.reply_text("Cuéntame brevemente qué ha fallado.", parse_mode=None)
        return

    # Saludos
    if any(w in text_lower for w in ("hola", "hi", "hello", "buenas", "hey", "ola")):
        await start(update, context)
        return

    if any(fragment in text_lower for fragment in ("voy a la reunion", "voy a la reunión", "me apunto", "ire a la reunion", "ire a la reunión")):
        context.args = []
        await meeting_handlers.asistir(update, context)
        return

    if any(fragment in text_lower for fragment in ("cuando es la proxima", "cuando es la próxima", "proxima reunion", "próxima reunion", "proxima reunión", "próxima reunión")):
        context.args = []
        await meeting_handlers.reunion(update, context)
        return

    if any(fragment in text_lower for fragment in ("que se lee", "qué se lee", "libro actual", "que estamos leyendo", "qué estamos leyendo")):
        context.args = []
        await libro_cmd(update, context)
        return

    if any(fragment in text_lower for fragment in ("quiero proponer", "que propongo", "qué propongo", "proponer un libro", "propongo un libro")):
        context.args = []
        await book_handlers.proponer(update, context)
        return

    if any(fragment in text_lower for fragment in ("quiero proponer tema", "proponer tematica", "proponer temática", "tema para el club")):
        context.args = []
        await theme_handlers.tema(update, context)
        return

    # Guía genérica
    await update.message.reply_text(
        "Puedo ayudarte tambien si me escribes en lenguaje natural.\n\n"
        "Prueba por ejemplo:\n"
        "- voy a la reunion\n"
        "- que se lee ahora\n"
        "- quiero proponer un libro\n"
        "- cuando es la proxima\n\n"
        "Si prefieres comandos, usa /ayuda para ver el menu contextual.",
        parse_mode=None
    )


async def handle_poll_answer(update, context):
    return await poll_answer_handler(update, context)


# --------------------------------------------------
# REGISTER HANDLERS
# --------------------------------------------------

register_handlers(telegram_app, {
    "start": _trace_bot_handler("start", start),
    "proponer": _trace_bot_handler("proponer", proponer),
    "propuestas": _trace_bot_handler("propuestas", propuestas),
    "votar": _trace_bot_handler("votar", votar),
    "resultados": _trace_bot_handler("resultados", resultados),
    "reunion": _trace_bot_handler("reunion", reunion),
    "asistir": _trace_bot_handler("asistir", asistir),
    "noasistir": _trace_bot_handler("noasistir", noasistir),
    "asistencia": _trace_bot_handler("asistencia", asistencia),
    "tema": _trace_bot_handler("tema", tema),
    "temas": _trace_bot_handler("temas", temas),
    "votar_tema": _trace_bot_handler("votar_tema", votar_tema),
    "trivia_cmd": _trace_bot_handler("trivia", trivia_cmd),
    "recomendar": _trace_bot_handler("recomendar", recomendar),
    "libro_cmd": _trace_bot_handler("libro", libro_cmd),
    "acta_cmd": _trace_bot_handler("acta", acta_cmd),
    "progreso_cmd": _trace_bot_handler("progreso", progreso_cmd),
    "estadisticas_cmd": _trace_bot_handler("estadisticas", estadisticas_cmd),
    "admin_ayuda_cmd": _trace_bot_handler("admin_ayuda", admin_ayuda_cmd),
    "ciclo_cmd": _trace_bot_handler("ciclo", ciclo_cmd),
    "nuevo_ciclo_cmd": _trace_bot_handler("nuevo_ciclo", nuevo_ciclo_cmd),
    "cerrar_ciclo_cmd": _trace_bot_handler("cerrar_ciclo", cerrar_ciclo_cmd),
    "anuncio_cmd": _trace_bot_handler("anuncio", anuncio_cmd),
    "anunciar_ganador_cmd": _trace_bot_handler("anunciar_ganador", anunciar_ganador_cmd),
    "enviar_recordatorio_cmd": _trace_bot_handler("enviar_recordatorio", enviar_recordatorio_cmd),
    "enviar_lectura_cmd": _trace_bot_handler("enviar_lectura", enviar_lectura_cmd),
    "ayuda_cmd": _trace_bot_handler("ayuda", ayuda_cmd),
    "encuesta_libros_cmd": _trace_bot_handler("encuesta_libros", encuesta_libros_cmd),
    "encuesta_temas_cmd": _trace_bot_handler("encuesta_temas", encuesta_temas_cmd),
    "fijar_cmd": _trace_bot_handler("fijar", fijar_cmd),
    "desfijar_cmd": _trace_bot_handler("desfijar", desfijar_cmd),
    "preguntas_cmd": _trace_bot_handler("preguntas", preguntas_cmd),
    "cita_cmd": _trace_bot_handler("cita", cita_cmd),
    "lista_espera_cmd": _trace_bot_handler("lista_espera", lista_espera_cmd),
    "proponer_fecha_cmd": _trace_bot_handler("proponer_fecha", proponer_fecha_cmd),
    "bug_cmd": _trace_bot_handler("bug", bug_cmd),
    "handle_my_chat_member": handle_my_chat_member,
    "button_handler": _trace_bot_handler("button_handler", button_handler, category="callback", clear_pending=False),
    "handle_poll_answer": _trace_bot_handler("handle_poll_answer", handle_poll_answer, category="poll", clear_pending=False),
    "private_text_handler": _trace_bot_handler("private_text_handler", private_text_handler, category="message", clear_pending=False),
})

# --------------------------------------------------
# FLASK — AUTH
# --------------------------------------------------

@flask_app.get("/")
def home():
    return redirect(url_for("public_page"), 301)


@flask_app.get("/robots.txt")
def robots_txt():
    canonical = db.get_config("public_canonical_url", "").strip()
    sitemap_url = f"{canonical}/sitemap.xml" if canonical else ""
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /webhook",
    ]
    if sitemap_url:
        lines.append(f"Sitemap: {sitemap_url}")
    return Response("\n".join(lines), mimetype="text/plain")


@flask_app.get("/sitemap.xml")
@flask_app.get("/publico/sitemap.xml")
def sitemap_xml():
    canonical = db.get_config("public_canonical_url", "").strip()
    if not canonical:
        canonical = WEBHOOK_URL.rstrip("/")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f'<url><loc>{canonical}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>'
        f'<url><loc>{canonical}/publico</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>'
        "</urlset>"
    )
    return Response(xml, mimetype="application/xml")

@flask_app.get("/google8715cced54138a71.html")
@flask_app.get("/publico/google8715cced54138a71.html")
def google_site_verification():
    return Response("google-site-verification: google8715cced54138a71.html", mimetype="text/html")


@flask_app.get("/favicon.ico")
def favicon():
    return Response(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">📚</text></svg>""",
        mimetype="image/svg+xml",
    )

@flask_app.get("/health")
def health():
    return {"status": "running"}, 200

@flask_app.get("/admin/login")
def admin_login():
    if is_admin_logged():
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_login.html", display_name=session.get("admin_display_name", ""))

@flask_app.post("/admin/login")
def admin_login_post():
    remote_addr = get_request_ip()
    display_name = request.form.get("display_name", "").strip()
    if _is_login_rate_limited(remote_addr):
        logger.warning("Login admin bloqueado por rate limit desde %s", remote_addr)
        audit_admin(
            "admin_login",
            actor=display_name or f"admin@{remote_addr}",
            target_type="session",
            target_id=remote_addr,
            status="blocked",
            result="rate_limited",
            extra={"display_name": display_name or None},
        )
        return render_template("admin_login.html", error="Demasiados intentos. Espera unos minutos.", display_name=display_name), 429
    secret = request.form.get("secret", "").strip()
    if not ADMIN_SECRET:
        return "ADMIN_SECRET no configurado", 500
    if secret != ADMIN_SECRET:
        attempts = _register_login_failure(remote_addr)
        logger.warning("Login admin fallido desde %s (intento %d)", remote_addr, attempts)
        audit_admin(
            "admin_login",
            actor=display_name or f"admin@{remote_addr}",
            target_type="session",
            target_id=remote_addr,
            status="error",
            result="invalid_secret",
            extra={"attempt": attempts, "display_name": display_name or None},
        )
        return render_template("admin_login.html", error="Secreto incorrecto", display_name=display_name), 403
    _clear_login_failures(remote_addr)
    session.clear()
    actor = remember_admin_identity(display_name)
    session["admin_logged"] = True
    session["csrf_token"] = secrets.token_hex(16)
    session.permanent = True
    audit_admin(
        "admin_login",
        actor=actor,
        target_type="session",
        target_id=remote_addr,
        status="ok",
        result="login_ok",
        extra={"display_name": display_name or None},
    )
    db.log_event("admin", "Inicio de sesión en el panel", category="auth", actor="admin")
    logger.info("Login admin correcto desde %s", remote_addr)
    return redirect(url_for("admin_dashboard"))

@flask_app.post("/admin/logout")
def admin_logout():
    actor = get_admin_actor()
    remote_addr = get_request_ip()
    db.log_event("admin", "Cierre de sesión del panel", category="auth", actor="admin")
    audit_admin(
        "admin_logout",
        actor=actor,
        target_type="session",
        target_id=remote_addr,
        status="ok",
        result="logout_ok",
    )
    session.clear()
    return redirect(url_for("admin_login"))

register_admin_routes(
    flask_app,
    require_admin=require_admin,
    run_async=_run_async,
    send_to_group=send_to_group,
    send_and_pin=send_and_pin,
    send_meeting_reminder=send_meeting_reminder,
    send_reading_reminder=send_reading_reminder,
    announce_winner=announce_winner,
    logger=logger,
    telegram_app=telegram_app,
    telegram_chat_id=TELEGRAM_CHAT_ID,
    default_messages=DEFAULT_MESSAGES,
    group_invite_link=GROUP_INVITE_LINK,
    reload_custom_reminders=lambda: _reload_custom_reminders(),
    utcnow=lambda: datetime.utcnow(),
    get_request_ip=get_request_ip,
    admin_search_limiter=admin_search_limiter,
    poll_formatting={"bold": bold, "italic": italic, "esc": esc},
    observability=observability,
)


# --------------------------------------------------
# WEBHOOK
# --------------------------------------------------

@flask_app.post("/webhook")
def webhook():
    return webhook_handler.handle_request(request)

# --------------------------------------------------
# STARTUP / SHUTDOWN
# --------------------------------------------------

def _make_custom_reminder_job(message_text):
    """Compatibilidad temporal mientras la carga de jobs vive en RuntimeJobs."""
    return runtime_jobs.make_custom_reminder_job(message_text, send_to_group)


def _reload_custom_reminders():
    runtime_jobs.reload_custom_reminders(send_to_group)


async def _keep_alive_ping():
    await runtime_jobs.keep_alive_ping()


async def refresh_bot_command_menu():
    return await runtime_jobs.refresh_bot_command_menu()


async def _register_runtime_bot_commands():
    await runtime_jobs.register_runtime_bot_commands()


async def main():
    global _bot_loop
    _bot_loop = asyncio.get_event_loop()
    await serve(
        flask_app,
        telegram_app,
        scheduler,
        (
            runtime_jobs.instrument("send_meeting_reminder", send_meeting_reminder),
            runtime_jobs.instrument("send_reading_reminder", send_reading_reminder),
            runtime_jobs.instrument("send_day_before_reminder", send_day_before_reminder),
            runtime_jobs.instrument("send_scheduled_messages", send_scheduled_messages),
            runtime_jobs.instrument("keep_alive_ping", _keep_alive_ping),
            [
                {
                    "id": "refresh_command_menu",
                    "func": runtime_jobs.instrument("refresh_bot_command_menu", refresh_bot_command_menu),
                    "trigger": "interval",
                    "kwargs": {"minutes": 15},
                },
                {
                    "id": "auto_close_cycle",
                    "func": runtime_jobs.instrument("auto_close_cycle", _auto_close_cycle),
                    "trigger": "cron",
                    "kwargs": {"hour": 23, "minute": 30},
                },
            ],
        ),
        register_commands=_register_runtime_bot_commands,
        post_scheduler_start=_reload_custom_reminders,
    )


if __name__ == "__main__":
    asyncio.run(main())
