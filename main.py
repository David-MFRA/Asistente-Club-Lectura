import os
import re
import json
import logging
import unicodedata
import time as _time
import asyncio
from datetime import datetime, timedelta
from http import HTTPStatus
import secrets

from flask import Flask, request, render_template, redirect, url_for, session, Response, flash, get_flashed_messages, jsonify
from asgiref.wsgi import WsgiToAsgi
import uvicorn

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeChat, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ChatMemberHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import books_api
import trivia
import recommendations
import db
import ai_features
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
from app.services.meeting_lookup import find_meeting_by_text
from app.telegram.access import TelegramAccessControl
from app.telegram.callbacks import CallbackHandler
from app.telegram.commands.books import BookHandlers
from app.telegram.commands.extras import ExtraHandlers
from app.telegram.commands.meetings import MeetingHandlers
from app.telegram.commands.themes import ThemeHandlers
from app.telegram.messaging import TelegramMessagingService
from app.telegram.registry import register_handlers
from app.web.admin.messaging import (
    add_scheduled_message,
    delete_scheduled_message,
    preview_admin_message,
    render_admin_messages,
    render_scheduler,
    render_sent_messages,
    reset_admin_message,
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
from app.web.admin.monitoring import render_admin_bugs, render_admin_logs, update_admin_bug
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
    import hashlib as _hashlib
    _bot_token = os.getenv("BOT_TOKEN", "")
    FLASK_SECRET_KEY = _hashlib.sha256(f"flask-{_bot_token}-secret".encode()).hexdigest()
    import logging as _log
    _log.getLogger(__name__).warning(
        "FLASK_SECRET_KEY no configurada — derivando de BOT_TOKEN. "
        "Define la variable de entorno para mayor seguridad."
    )
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

# Anti-spam: cooldown por usuario y comando
_cooldowns: dict = {}  # {(user_id, command): last_used_timestamp}
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

# --------------------------------------------------
# ASYNC BRIDGE — run coroutines from sync Flask routes
# --------------------------------------------------

_bot_loop = None  # set in main() before serving

def _run_async(coro):
    """Run an async coroutine from a sync Flask route (thread-safe)."""
    if _bot_loop is None:
        raise RuntimeError("Bot event loop not initialized")
    return asyncio.run_coroutine_threadsafe(coro, _bot_loop).result()

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
    lines = ["🏆 <b>¡Tenemos libro del mes!</b>"]
    lines.append(f"\n📗 <b>{hesc(book['title'])}</b>")
    if book.get("author"):
        lines.append(f"✍️ <i>{hesc(book['author'])}</i>")
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
        user = update.effective_user.first_name or update.effective_user.username or "miembro"
        current_cycle = db.get_current_cycle_key()
        winner = db.get_winner_book(current_cycle)
        meeting = db.get_latest_scheduled_meeting(cycle_key=current_cycle)

        libro_line = f"📗 Libro actual: {winner['title']}" + (f" — {winner['author']}" if winner and winner.get('author') else "") if winner else "📗 Aún no hay libro elegido este ciclo"
        reunion_line = ""
        if meeting:
            fecha = str(meeting["final_date"])[:10] if meeting.get("final_date") else "sin fecha"
            reunion_line = f"\n📅 Próxima reunión: {meeting['name']} ({fecha})"

        is_admin = is_admin_user(update)
        quick_lines = [
            "📖 /proponer título — Proponer un libro",
            "🗳️ /propuestas — Ver y votar propuestas",
            "📅 /reunion — Info de la próxima reunión",
            "✅ /asistir · ❌ /noasistir — Gestionar asistencia",
            "🏷️ /temas — Ver y votar temáticas",
            "📊 /progreso · /estadisticas — Tu actividad",
            "💡 /recomendar — Recomendaciones de libros",
            "🐛 /bug — Reportar un problema",
        ]
        if is_admin:
            quick_lines.append("🔐 /admin_ayuda — Comandos de administración")

        text = (
            f"📚 ¡Hola, {user}! Bienvenid@ al bot del Club de Lectura.\n\n"
            f"{libro_line}{reunion_line}\n\n"
            f"Aquí puedes usar todos los comandos del club de forma privada "
            f"sin molestar al grupo. Pulsa cualquier botón del menú o escribe "
            f"un comando directamente.\n\n"
            + "\n".join(quick_lines)
            + "\n\n"
            f"Usa /ayuda para la lista completa."
        )
        keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("📚 /propuestas"), KeyboardButton("📅 /reunion")],
                [KeyboardButton("✅ /asistir"),    KeyboardButton("🏷️ /temas")],
                [KeyboardButton("📗 /libro"),      KeyboardButton("💡 /recomendar")],
                [KeyboardButton("❓ /ayuda")],
            ],
            resize_keyboard=True,
            input_field_placeholder="Elige una opción o escribe un comando…"
        )
        await update.message.reply_text(text, parse_mode=None, reply_markup=keyboard)
        return

    raw = get_text("welcome_message")
    await update.message.reply_text(raw, parse_mode="HTML")


async def ayuda_cmd(update, context):
    if not await _allowed(update): return
    raw = get_text("help_message")
    await update.message.reply_text(raw, parse_mode="HTML")


async def proponer(update, context):
    return await book_handlers.proponer(update, context)


async def propuestas(update, context):
    return await book_handlers.propuestas(update, context)
    if not await _allowed(update): return
    try:
        books = db.get_book_proposals()
        if not books:
            await update.message.reply_text(
                "📭 No hay propuestas todavía\\. Usa /proponer para añadir la primera\\.",
                parse_mode="MarkdownV2"
            )
            return
        lines = [f"📚 {bold('Propuestas del ciclo')}\n"]
        for b in books:
            pos = b.get("cycle_position", b["proposal_id"])
            author_str = f" — _{esc(b['author'])}_" if b.get("author") else ""
            stars = "⭐" * min(b["votes"], 5) if b["votes"] > 0 else "·"
            lines.append(
                f"{bold(str(pos))}\\. {esc(b['title'])}{author_str}\n"
                f"   {stars} {bold(str(b['votes']))} voto{'s' if b['votes'] != 1 else ''}"
            )
        lines.append(f"\n_Pulsa un botón para votar directamente:_")
        keyboard = []
        for b in books[:10]:
            pos = b.get("cycle_position", b["proposal_id"])
            label = f"🗳️ {pos}. {b['title'][:28]}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"vb:{b['proposal_id']}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2", reply_markup=reply_markup)
    except Exception:
        logger.exception("Error en /propuestas")
        await update.message.reply_text("⚠️ Error obteniendo propuestas\\.", parse_mode="MarkdownV2")


async def votar(update, context):
    return await book_handlers.votar(update, context)
    if not await _allowed(update): return
    if not _check_cooldown(update.effective_user.id, "votar", 10):
        await update.message.reply_text("⏳ Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
        return
    if not context.args:
        await update.message.reply_text(
            f"🗳️ Usa {code('/votar número')} — el número es la posición en /propuestas\\.", parse_mode="MarkdownV2"
        )
        return
    try:
        num = int(context.args[0])
        # Resolver posición de ciclo → proposal_id real
        books = db.get_book_proposals()
        proposal = next((b for b in books if b.get("cycle_position") == num), None)
        if not proposal:
            # Fallback: intentar como proposal_id directo (backward compat)
            proposal = db.get_proposal_by_id(num)
        if not proposal:
            await update.message.reply_text(
                f"❌ No existe la propuesta \\#{bold(str(num))}\\. Usa /propuestas para ver la lista\\.",
                parse_mode="MarkdownV2"
            )
            return
        proposal_id = proposal["proposal_id"]
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        ok = db.vote_book(proposal_id, user)
        if ok:
            proposal = db.get_proposal_by_id(proposal_id)
            book_name = proposal["title"] if proposal else f"propuesta #{proposal_id}"
            await update.message.reply_text(
                f"✅ {bold('Voto registrado')} para _{esc(book_name)}_\\.\nUsa /propuestas para ver el ranking\\.",
                parse_mode="MarkdownV2"
            )
        else:
            await update.message.reply_text("⚠️ Ya habías votado esa propuesta\\.", parse_mode="MarkdownV2")
    except ValueError:
        await update.message.reply_text("❌ El ID debe ser un número\\.", parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /votar")
        await update.message.reply_text("⚠️ Error registrando el voto\\.", parse_mode="MarkdownV2")


async def resultados(update, context):
    return await book_handlers.resultados(update, context)
    if not await _allowed(update): return
    try:
        books = db.get_cycle_results()
        if not books:
            await update.message.reply_text("📭 No hay resultados todavía\\.", parse_mode="MarkdownV2")
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = [f"🏆 {bold('Resultados del ciclo')}\n"]
        for i, b in enumerate(books):
            medal = medals[i] if i < 3 else f"{i+1}\\."
            author_str = f"\n   _{esc(b['author'])}_" if b.get("author") else ""
            lines.append(
                f"{medal} {bold(b['title'])}{author_str}\n"
                f"   {bold(str(b['votes']))} voto{'s' if b['votes'] != 1 else ''}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /resultados")
        await update.message.reply_text("⚠️ Error obteniendo resultados\\.", parse_mode="MarkdownV2")


def _normalize(text: str) -> str:
    """Normaliza texto: minúsculas, sin acentos, sin puntuación."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text

def _find_meeting_by_text(query: str):
    """Busca la reunión más relevante por nombre o fecha."""
    meetings = db.get_meetings(limit=20)
    query_norm = _normalize(query)
    best = None
    best_score = 0
    for m in meetings:
        if m.get("status") == "closed":
            continue
        name_norm = _normalize(m.get("name", ""))
        if name_norm == query_norm:
            score = 100
        elif query_norm in name_norm:
            score = 80
        else:
            words = query_norm.split()
            matched = sum(1 for w in words if w in name_norm)
            score = int(matched / max(len(words), 1) * 60)
        if m.get("final_date"):
            date_str = _normalize(str(m["final_date"]))
            month_names = {"enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06",
                           "julio":"07","agosto":"08","septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12"}
            for month_es, month_num in month_names.items():
                if month_es in query_norm and f"-{month_num}-" in date_str:
                    score += 30
        if score > best_score:
            best_score = score
            best = m
    return best if best_score >= 30 else None


async def reunion(update, context):
    return await meeting_handlers.reunion(update, context)
    if not await _allowed(update): return
    try:
        if context.args:
            query = " ".join(context.args)
            meeting = find_meeting_by_text(query)
            if not meeting:
                await update.message.reply_text(f"❌ No encontré ninguna reunión con «{query}».\nUsa /reunion sin argumentos para ver la próxima.", parse_mode=None)
                return
        else:
            meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text("📭 No hay reunión programada todavía.", parse_mode=None)
            return
        asistentes = db.get_attendance(meeting["id"])
        fecha = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
        estado_map = {"draft": "⏳ Borrador", "scheduled": "✅ Confirmada", "closed": "🔒 Cerrada"}
        estado = estado_map.get(meeting.get("status", ""), meeting.get("status", ""))
        lines = [
            f"📅 {meeting['name']}\n",
            f"📆 Fecha: {fecha}",
            f"📊 Estado: {estado}",
        ]
        if meeting.get("location"):
            lines.append(f"📍 Lugar: {meeting['location']}")
        if meeting.get("notes"):
            lines.append(f"📝 {meeting['notes']}")
        if meeting.get("book_title"):
            lines.append(f"📗 Libro: {meeting['book_title']}")
        lines.append(f"👥 Apuntados: {len(asistentes)}")
        if asistentes:
            lines.append("  " + ",  ".join(f"• {a}" for a in asistentes))
        lines.append("\nUsa /asistir o /noasistir para gestionar tu asistencia.")
        keyboard = [
            [
                InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{meeting['id']}"),
                InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
            ]
        ]
        if meeting.get("book_id"):
            keyboard.append([InlineKeyboardButton("📗 Ver libro", callback_data=f"bookinfo:{meeting['book_id']}")])
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=None,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception:
        logger.exception("Error en /reunion")
        await update.message.reply_text("⚠️ Error obteniendo la reunión.", parse_mode=None)


async def asistir(update, context):
    return await meeting_handlers.asistir(update, context)
    if not await _allowed(update): return
    if not _check_cooldown(update.effective_user.id, "asistir", 10):
        await update.message.reply_text("⏳ Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
        return
    try:
        meetings = db.get_upcoming_meetings()
        if not meetings:
            await update.message.reply_text("📭 No hay reunión activa.", parse_mode=None)
            return
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        if len(meetings) == 1:
            meeting = meetings[0]
            db.add_attendance(meeting["id"], user)
            db.log_event("bot", f"{user} se apuntó a «{meeting['name']}»", category="meeting", actor=user)
            asistentes = db.get_attendance(meeting["id"])
            names = "\n".join(f"  ✅ {a}" for a in asistentes)
            await update.message.reply_text(
                f"🎉 {user} se apuntó a {meeting['name']}\n\n"
                f"👥 Apuntados ({len(asistentes)}):\n{names}",
                parse_mode=None
            )
        else:
            keyboard = []
            for m in meetings[:5]:
                date_str = str(m["final_date"])[:16] if m.get("final_date") else "Sin fecha"
                label = f"📅 {m['name']} · {date_str}"
                keyboard.append([InlineKeyboardButton(label, callback_data=f"attend:{m['id']}")])
            await update.message.reply_text(
                "📅 ¿A qué reunión te apuntas? Elige una:",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception:
        logger.exception("Error en /asistir")
        await update.message.reply_text("⚠️ Error al apuntarte.", parse_mode=None)


async def noasistir(update, context):
    return await meeting_handlers.noasistir(update, context)
    if not await _allowed(update): return
    if not _check_cooldown(update.effective_user.id, "noasistir", 10):
        await update.message.reply_text("⏳ Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
        return
    try:
        meetings = db.get_upcoming_meetings()
        if not meetings:
            await update.message.reply_text("📭 No hay reunión activa.", parse_mode=None)
            return
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        if len(meetings) == 1:
            meeting = meetings[0]
            db.remove_attendance(meeting["id"], user)
            asistentes = db.get_attendance(meeting["id"])
            names = ("\n".join(f"  • {a}" for a in asistentes)) if asistentes else "Nadie de momento"
            await update.message.reply_text(
                f"👋 {user} se ha quitado de {meeting['name']}\n\n"
                f"👥 Quedan ({len(asistentes)}):\n{names}",
                parse_mode=None
            )
        else:
            keyboard = []
            for m in meetings[:5]:
                date_str = str(m["final_date"])[:16] if m.get("final_date") else "Sin fecha"
                label = f"📅 {m['name']} · {date_str}"
                keyboard.append([InlineKeyboardButton(label, callback_data=f"noattend:{m['id']}")])
            await update.message.reply_text(
                "📅 ¿De qué reunión te quitas? Elige una:",
                parse_mode=None,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception:
        logger.exception("Error en /noasistir")
        await update.message.reply_text("⚠️ Error al quitarte.", parse_mode=None)


async def asistencia(update, context):
    return await meeting_handlers.asistencia(update, context)
    if not await _allowed(update): return
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text("📭 No hay reunión activa\\.", parse_mode="MarkdownV2")
            return
        asistentes = db.get_attendance(meeting["id"])
        names = ("\n".join(f"  ✅ {esc(a)}" for a in asistentes)) if asistentes else "_Nadie apuntado todavía_"
        await update.message.reply_text(
            f"👥 {bold('Asistencia')} — {italic(meeting['name'])}\n\n{names}",
            parse_mode="MarkdownV2"
        )
    except Exception:
        logger.exception("Error en /asistencia")
        await update.message.reply_text("⚠️ Error obteniendo asistencia\\.", parse_mode="MarkdownV2")


async def tema(update, context):
    return await theme_handlers.tema(update, context)
    if not await _allowed(update): return
    if not _check_cooldown(update.effective_user.id, "tema", 30):
        await update.message.reply_text("⏳ Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
        return
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text(
            f"🏷️ Usa {code('/tema nombre de la temática')}", parse_mode="MarkdownV2"
        )
        return
    try:
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        row = db.create_theme(name, created_by=user)
        if row:
            prev = db.get_theme_previous_cycles(name)
            warning = ""
            if prev:
                cycles_str = ", ".join(p["cycle_key"] for p in prev[:3])
                warning = f"\n\n⚠️ Esta temática ya se usó en: {cycles_str}"
            await update.message.reply_text(
                f"🏷️ Temática propuesta: {name}\n"
                f"Propuesta por {user}.{warning}\n"
                f"Usa /temas para votar.",
                parse_mode=None
            )
        else:
            await update.message.reply_text(
                f"⚠️ La temática _{esc(name)}_ ya existe en este ciclo\\.", parse_mode="MarkdownV2"
            )
    except Exception:
        logger.exception("Error en /tema")
        await update.message.reply_text("⚠️ Error creando temática\\.", parse_mode="MarkdownV2")


async def temas(update, context):
    return await theme_handlers.temas(update, context)
    if not await _allowed(update): return
    try:
        rows = db.get_themes()
        if not rows:
            await update.message.reply_text(
                "📭 No hay temáticas\\. Usa /tema para añadir la primera\\.", parse_mode="MarkdownV2"
            )
            return
        lines = [f"🧭 {bold('Temáticas del ciclo')}\n"]
        for t in rows:
            bar = "█" * min(t["votes"], 8) if t["votes"] > 0 else "░"
            lines.append(
                f"{bold(str(t['id']))}\\. {esc(t['name'])}\n"
                f"   {bar} {bold(str(t['votes']))} voto{'s' if t['votes'] != 1 else ''}"
            )
        lines.append(f"\n_Pulsa un botón para votar:_")
        keyboard = []
        for t in rows[:10]:
            label = f"🗳️ {t['name'][:30]}"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"vt:{t['id']}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2", reply_markup=reply_markup)
    except Exception:
        logger.exception("Error en /temas")
        await update.message.reply_text("⚠️ Error obteniendo temáticas\\.", parse_mode="MarkdownV2")


async def votar_tema(update, context):
    return await theme_handlers.votar_tema(update, context)
    if not await _allowed(update): return
    if not _check_cooldown(update.effective_user.id, "votar_tema", 10):
        await update.message.reply_text("⏳ Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
        return
    if not context.args:
        await update.message.reply_text(
            f"🗳️ Usa {code('/votar_tema id')} — consulta IDs con /temas\\.", parse_mode="MarkdownV2"
        )
        return
    try:
        theme_id = int(context.args[0])
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        ok = db.vote_theme(theme_id, user)
        if ok:
            await update.message.reply_text(
                f"✅ {bold('Voto de temática registrado')}\\! Usa /temas para ver el ranking\\.",
                parse_mode="MarkdownV2"
            )
        else:
            await update.message.reply_text("⚠️ Ya habías votado esa temática\\.", parse_mode="MarkdownV2")
    except ValueError:
        await update.message.reply_text("❌ El ID debe ser un número\\.", parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /votar_tema")
        await update.message.reply_text("⚠️ Error registrando voto\\.", parse_mode="MarkdownV2")


async def trivia_cmd(update, context):
    return await extra_handlers.trivia_cmd(update, context)
    if not await _allowed(update): return
    if not _check_cooldown(update.effective_user.id, "trivia", 15):
        await update.message.reply_text("⏳ Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
        return
    try:
        question = trivia.generate()
        await update.message.reply_text(esc(question), parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /trivia")
        await update.message.reply_text("⚠️ Error generando trivia\\.", parse_mode="MarkdownV2")


async def recomendar(update, context):
    return await extra_handlers.recomendar(update, context)
    if not await _allowed(update): return
    if not _check_cooldown(update.effective_user.id, "recomendar", 60):
        await update.message.reply_text("⏳ Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
        return
    try:
        top_theme = db.get_top_theme()
        theme_name = top_theme["name"] if top_theme else "novela"
        wait = await update.message.reply_text(
            f"🔍 Buscando libros de _{esc(theme_name)}_\\.\\.\\.", parse_mode="MarkdownV2"
        )
        rec = recommendations.recommend(theme_name)
        await wait.delete()
        if not rec:
            await update.message.reply_text(
                "📭 No encontré recomendaciones\\.", parse_mode="MarkdownV2"
            )
            return
        lines = [f"💡 {bold('Recomendaciones')} — tema {italic(theme_name)}\n"]
        for i, r in enumerate(rec, 1):
            author_str = f"\n   _{esc(r['author'])}_" if r.get("author") else ""
            lines.append(f"{bold(str(i))}\\. {esc(r['title'])}{author_str}")
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /recomendar")
        await update.message.reply_text("⚠️ Error obteniendo recomendaciones\\.", parse_mode="MarkdownV2")


# --------------------------------------------------
# INLINE KEYBOARD CALLBACK HANDLER
# --------------------------------------------------

async def button_handler(update, context):
    if not await _allowed(update):
        await update.callback_query.answer("⛔ No tienes permiso para usar esta función.", show_alert=True)
        return
    return await callback_handler_service.handle(update, context)
    data = query.data
    user = query.from_user.first_name or query.from_user.username or "alguien"
    try:
        if data.startswith("vb:"):
            proposal_id = int(data.split(":")[1])
            ok = db.vote_book(proposal_id, user)
            proposal = db.get_proposal_by_id(proposal_id)
            book_name = proposal["title"] if proposal else f"propuesta #{proposal_id}"
            if ok:
                await query.answer(f"✅ Voto registrado para «{book_name}»", show_alert=True)
            else:
                await query.answer(f"⚠️ Ya habías votado «{book_name}»", show_alert=True)

        elif data.startswith("vt:"):
            theme_id = int(data.split(":")[1])
            ok = db.vote_theme(theme_id, user)
            if ok:
                await query.answer("✅ Voto de temática registrado", show_alert=True)
            else:
                await query.answer("⚠️ Ya habías votado esa temática", show_alert=True)

        elif data.startswith("attend:"):
            meeting_id = int(data.split(":")[1])
            ok = db.add_attendance(meeting_id, user)
            meeting = db.get_meeting(meeting_id)
            meeting_name = meeting["name"] if meeting else f"reunión #{meeting_id}"
            if ok:
                asistentes = db.get_attendance(meeting_id)
                await query.answer(f"✅ Apuntado a «{meeting_name}»")
                names = ", ".join(asistentes) if asistentes else "nadie"
                await query.edit_message_text(
                    f"✅ {user} apuntado a {meeting_name}\n\n"
                    f"👥 Apuntados ({len(asistentes)}): {names}\n\n"
                    f"Usa /noasistir para quitarte.",
                    parse_mode=None
                )
            else:
                await query.answer(f"Ya estás apuntado a «{meeting_name}»", show_alert=True)

        elif data.startswith("noattend:"):
            meeting_id = int(data.split(":")[1])
            db.remove_attendance(meeting_id, user)
            meeting = db.get_meeting(meeting_id)
            meeting_name = meeting["name"] if meeting else f"reunión #{meeting_id}"
            asistentes = db.get_attendance(meeting_id)
            await query.answer(f"Te has quitado de «{meeting_name}»")
            names = ", ".join(asistentes) if asistentes else "nadie"
            await query.edit_message_text(
                f"👋 {user} se ha quitado de {meeting_name}\n\n"
                f"👥 Quedan ({len(asistentes)}): {names}",
                parse_mode=None
            )

        elif data.startswith("bookinfo:"):
            book_id_str = data.split(":")[1]
            if book_id_str and book_id_str != "0":
                book = db.get_book_by_id(int(book_id_str))
                if book:
                    lines = [f"📗 {book['title']}"]
                    if book.get("author"):
                        lines.append(f"✍️ {book['author']}")
                    if book.get("pages"):
                        lines.append(f"📄 {book['pages']} páginas")
                    if book.get("description"):
                        desc = book["description"]
                        if len(desc) > 400:
                            desc = desc[:397] + "…"
                        lines.append(f"\n📖 {desc}")
                    await query.answer()
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text="\n".join(lines),
                        parse_mode=None
                    )
                else:
                    await query.answer("No se encontró el libro", show_alert=True)
            else:
                await query.answer("No hay libro asignado a esta reunión", show_alert=True)

    except Exception:
        logger.exception("Error en button_handler")
        await query.answer("⚠️ Error procesando la acción", show_alert=True)


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
        db.log_reading_progress(user, winner["id"], pages)
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
        s = db.get_user_stats(user)
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
    db.set_config("active_theme", "")
    db.set_config(f"active_theme:{name}", "")
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
            db.set_config(f"poll_options_{tie_poll.poll.id}", json.dumps([b["proposal_id"] for b in tied[:10]]))
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
        db.set_config(f"poll_options_{msg.poll.id}", json.dumps([b["proposal_id"] for b in books[:10]]))
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
        db.set_config(f"poll_options_{msg.poll.id}", json.dumps([t["id"] for t in themes[:10]]))
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

        parts = [f"📅 <b>Recordatorio semanal del club</b>\n\n<b>{hesc(meeting['name'])}</b>\n🗓 <b>{hesc(fecha_str)}</b>"]

        if meeting.get("location"):
            parts.append(f"📍 {hesc(meeting['location'])}")
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
    author_line = f"\n✍️ <i>{hesc(book['author'])}</i>" if book.get("author") else ""
    parts = [
        f"📖 <b>Recordatorio de lectura</b>\n\nToca avanzar un poco más en la lectura.\n",
        f"📚 <b>{hesc(book['title'])}</b>{author_line}",
        f"\n📅 Reunión: <b>{hesc(reunion_name)}</b>",
        f"🗓 Fecha: <b>{hesc(fecha)}</b>",
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
        cycle_theme = db.get_config("active_theme") or None
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
    """Genera preguntas de debate para el libro actual."""
    if not await _allowed(update): return
    if not _check_cooldown(update.effective_user.id, "preguntas", 60):
        await update.message.reply_text("⏳ Espera un momento antes de generar más preguntas.", parse_mode=None)
        return
    try:
        winner = db.get_winner_book()
        if not winner:
            await update.message.reply_text("📭 No hay libro del ciclo activo.", parse_mode=None)
            return
        wait = await update.message.reply_text("🤔 Generando preguntas de debate...", parse_mode=None)
        questions = ai_features.generate_discussion_questions(
            winner["title"], winner.get("author", ""), winner.get("description", "")
        )
        await wait.delete()
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        db.log_event("bot", f"/preguntas solicitado para «{winner['title']}»", category="ai", actor=user)
        await update.message.reply_text(
            f"💬 Preguntas de debate — {winner['title']}\n\n{questions}",
            parse_mode=None
        )
    except Exception:
        logger.exception("Error en /preguntas")
        await update.message.reply_text("⚠️ Error generando preguntas.", parse_mode=None)


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
    """Genera una cita literaria relacionada con el libro actual."""
    if not await _allowed(update): return
    if not _check_cooldown(update.effective_user.id, "cita", 30):
        await update.message.reply_text("⏳ Espera un momento.", parse_mode=None)
        return
    try:
        winner = db.get_winner_book()
        if not winner:
            await update.message.reply_text("📭 No hay libro del ciclo activo.", parse_mode=None)
            return
        wait = await update.message.reply_text("✨ Buscando cita...", parse_mode=None)
        quote = ai_features.generate_book_quote(winner["title"], winner.get("author", ""))
        await wait.delete()
        await update.message.reply_text(
            f"✨ {quote}\n\n— Sobre «{winner['title']}»",
            parse_mode=None
        )
    except Exception:
        logger.exception("Error en /cita")
        await update.message.reply_text("⚠️ Error generando cita.", parse_mode=None)


async def bug_cmd(update, context):
    """Permite a los usuarios reportar un bug o problema."""
    if not await _allowed(update): return
    if not _check_cooldown(update.effective_user.id, "bug", 60):
        await update.message.reply_text("⏳ Espera un momento antes de enviar otro reporte.", parse_mode=None)
        return
    description = " ".join(context.args).strip() if context.args else ""
    if not description:
        await update.message.reply_text(
            "🐛 Usa /bug seguido de la descripción del problema.\n"
            "Ejemplo: /bug El comando /votar no responde",
            parse_mode=None
        )
        return
    user = update.effective_user
    username = user.username or user.first_name or str(user.id)
    try:
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
    except Exception:
        logger.exception("Error en /bug")
        await update.message.reply_text("⚠️ Error enviando el reporte.", parse_mode=None)


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
    logger.debug("private_text: user=%s id=%d text=%r", u.first_name or u.username, u.id, text[:80])

    # Handle pending /proponer state
    if context.user_data.get("pending_proponer"):
        context.user_data.pop("pending_proponer", None)
        if text:
            logger.info("private_text: pending_proponer resuelto con «%s» por user_id=%d", text, u.id)
            # Reuse proponer logic with the text as title
            context.args = text.split()
            await book_handlers.proponer(update, context)
        else:
            await update.message.reply_text("Escribe el título del libro para proponerlo.", parse_mode=None)
        return

    # Handle pending /tema state
    if context.user_data.get("pending_tema"):
        context.user_data.pop("pending_tema", None)
        if text:
            logger.info("private_text: pending_tema resuelto con «%s» por user_id=%d", text, u.id)
            context.args = [text]
            await theme_handlers.tema(update, context)
        else:
            await update.message.reply_text("Escribe el nombre de la temática para proponerla.", parse_mode=None)
        return

    # Saludos
    if any(w in text_lower for w in ("hola", "hi", "hello", "buenas", "hey", "ola")):
        await start(update, context)
        return

    # Guía genérica
    await update.message.reply_text(
        "👋 Usa los comandos del menú para interactuar con el club.\n\n"
        "Pulsa el icono / en el teclado para ver todos los comandos, "
        "o escribe /ayuda para la lista completa.\n\n"
        "Algunos comandos rápidos:\n"
        "📚 /propuestas — ver y votar libros\n"
        "📅 /reunion — próxima reunión\n"
        "✅ /asistir — apuntarte",
        parse_mode=None
    )


async def handle_poll_answer(update, context):
    """Recibe votos en tiempo real de encuestas de Telegram (non-anonymous polls)."""
    answer = update.poll_answer
    if not answer:
        return
    poll_id = answer.poll_id
    user_id = str(answer.user.id)
    user_name = answer.user.first_name or answer.user.username or user_id
    new_option_ids = list(answer.option_ids)  # list of selected option indices
    logger.info("poll_answer: poll_id=%s user=%s(%s) opciones=%s", poll_id, user_name, user_id, new_option_ids)

    # Find poll in our DB
    poll = db.get_poll_by_telegram_id(poll_id)
    if not poll or poll.get("is_closed"):
        logger.debug("poll_answer: encuesta no encontrada o cerrada poll_id=%s", poll_id)
        return

    poll_type = poll.get("poll_type")
    if poll_type not in ("books", "themes"):
        logger.debug("poll_answer: tipo de encuesta ignorado poll_type=%s", poll_type)
        return

    # Get option→entity_id mapping
    options_json = db.get_config(f"poll_options_{poll_id}")
    if not options_json:
        logger.warning("poll_answer: sin mapeo de opciones para poll_id=%s", poll_id)
        return
    try:
        options = json.loads(options_json)  # list of proposal_id or theme_id
    except Exception:
        logger.exception("poll_answer: error parseando opciones poll_id=%s", poll_id)
        return

    # Get previous selection for this user (to remove old votes)
    prev_key = f"poll_uv_{poll_id}_{user_id}"
    try:
        prev_option_ids = json.loads(db.get_config(prev_key, "[]") or "[]")
    except Exception:
        prev_option_ids = []

    # Remove previous votes
    for old_idx in prev_option_ids:
        if old_idx < len(options):
            entity_id = options[old_idx]
            try:
                if poll_type == "books":
                    db.remove_book_vote(entity_id, user_id)
                else:
                    db.remove_theme_vote(entity_id, user_id)
            except Exception:
                pass

    # Add new votes
    for new_idx in new_option_ids:
        if new_idx < len(options):
            entity_id = options[new_idx]
            try:
                if poll_type == "books":
                    db.vote_book(entity_id, user_id)
                else:
                    db.vote_theme(entity_id, user_id)
            except Exception:
                logger.exception("poll_answer: error registrando voto entity_id=%s", entity_id)

    # Persist new selection
    db.set_config(prev_key, json.dumps(new_option_ids))
    logger.debug("poll_answer: procesado OK poll_id=%s user=%s", poll_id, user_name)


# --------------------------------------------------
# REGISTER HANDLERS
# --------------------------------------------------

register_handlers(telegram_app, {
    "start": start,
    "proponer": proponer,
    "propuestas": propuestas,
    "votar": votar,
    "resultados": resultados,
    "reunion": reunion,
    "asistir": asistir,
    "noasistir": noasistir,
    "asistencia": asistencia,
    "tema": tema,
    "temas": temas,
    "votar_tema": votar_tema,
    "trivia_cmd": trivia_cmd,
    "recomendar": recomendar,
    "libro_cmd": libro_cmd,
    "acta_cmd": acta_cmd,
    "progreso_cmd": progreso_cmd,
    "estadisticas_cmd": estadisticas_cmd,
    "admin_ayuda_cmd": admin_ayuda_cmd,
    "ciclo_cmd": ciclo_cmd,
    "nuevo_ciclo_cmd": nuevo_ciclo_cmd,
    "cerrar_ciclo_cmd": cerrar_ciclo_cmd,
    "anuncio_cmd": anuncio_cmd,
    "anunciar_ganador_cmd": anunciar_ganador_cmd,
    "enviar_recordatorio_cmd": enviar_recordatorio_cmd,
    "enviar_lectura_cmd": enviar_lectura_cmd,
    "ayuda_cmd": ayuda_cmd,
    "encuesta_libros_cmd": encuesta_libros_cmd,
    "encuesta_temas_cmd": encuesta_temas_cmd,
    "fijar_cmd": fijar_cmd,
    "desfijar_cmd": desfijar_cmd,
    "preguntas_cmd": preguntas_cmd,
    "cita_cmd": cita_cmd,
    "lista_espera_cmd": lista_espera_cmd,
    "proponer_fecha_cmd": proponer_fecha_cmd,
    "bug_cmd": bug_cmd,
    "handle_my_chat_member": handle_my_chat_member,
    "button_handler": button_handler,
    "handle_poll_answer": handle_poll_answer,
    "private_text_handler": private_text_handler,
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
    return render_template("admin_login.html")

@flask_app.post("/admin/login")
def admin_login_post():
    remote_addr = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if _is_login_rate_limited(remote_addr):
        logger.warning("Login admin bloqueado por rate limit desde %s", remote_addr)
        return render_template("admin_login.html", error="Demasiados intentos. Espera unos minutos."), 429
    secret = request.form.get("secret", "").strip()
    if not ADMIN_SECRET:
        return "ADMIN_SECRET no configurado", 500
    if secret != ADMIN_SECRET:
        attempts = _register_login_failure(remote_addr)
        logger.warning("Login admin fallido desde %s (intento %d)", remote_addr, attempts)
        return render_template("admin_login.html", error="Secreto incorrecto"), 403
    _clear_login_failures(remote_addr)
    session.clear()
    session["admin_logged"] = True
    session["csrf_token"] = secrets.token_hex(16)
    session.permanent = True
    db.log_event("admin", "Inicio de sesión en el panel", category="auth", actor="admin")
    logger.info("Login admin correcto desde %s", remote_addr)
    return redirect(url_for("admin_dashboard"))

@flask_app.post("/admin/logout")
def admin_logout():
    db.log_event("admin", "Cierre de sesión del panel", category="auth", actor="admin")
    session.clear()
    return redirect(url_for("admin_login"))

# --------------------------------------------------
# FLASK — DASHBOARD
# --------------------------------------------------

@flask_app.get("/admin")
def admin_dashboard():
    auth = require_admin()
    if auth: return auth
    current_cycle    = db.get_current_cycle_key()
    books            = db.get_books(current_cycle)
    meetings         = db.get_meetings(limit=5, cycle_key=current_cycle)
    themes           = db.get_themes(current_cycle)
    ranking          = db.get_book_ranking()
    open_poll_books  = db.get_open_polls(poll_type="books", cycle_key=current_cycle)
    open_poll_themes = db.get_open_poll(poll_type="themes", cycle_key=current_cycle)
    cycle_states     = db.get_active_cycle_states()
    tied_books       = db.get_tied_books(current_cycle)
    active_cycles    = db.get_active_cycle_keys()
    return render_template(
        "admin.html",
        books=books, meetings=meetings, themes=themes, ranking=ranking,
        open_poll_books=open_poll_books, open_poll_themes=open_poll_themes,
        cycle_states=cycle_states, cycle_state=cycle_states[0] if cycle_states else None,
        tied_books=tied_books, tied_count=len(tied_books),
        current_cycle=current_cycle, active_cycles=active_cycles,
    )

# --------------------------------------------------
# FLASK — LIBROS (admin)
# --------------------------------------------------

@flask_app.post("/admin/book/add")
def admin_book_add():
    auth = require_admin()
    if auth: return auth
    title = request.form.get("title", "").strip()
    next_url = request.form.get("_next", url_for("admin_dashboard"))
    cycle_key = request.form.get("cycle", "").strip() or None
    if not title:
        flash("El título es obligatorio", "danger")
        return redirect(next_url)
    try:
        book = books_api.google_books(title)
        if not book:
            book = {
                "title":  title,
                "author": request.form.get("author", "").strip() or None,
            }
        db.insert_book(book, proposed_by="admin", cycle_key=cycle_key)
        effective_cycle = cycle_key or db.get_current_cycle_key()
        flash(f"Libro «{book['title']}» añadido al ciclo «{effective_cycle}»", "success")
    except Exception:
        logger.exception("Error añadiendo libro desde admin")
        flash("Error añadiendo el libro", "danger")
    return redirect(next_url)

@flask_app.post("/admin/book/<int:proposal_id>/delete")
def admin_book_delete(proposal_id):
    auth = require_admin()
    if auth: return auth
    next_url = request.form.get("_next", url_for("admin_dashboard"))
    try:
        db.remove_book_proposal(proposal_id)
        flash("Propuesta eliminada", "success")
    except Exception:
        flash("Error eliminando la propuesta", "danger")
    return redirect(next_url)

# --------------------------------------------------
# FLASK — ENCUESTA LIBROS
# --------------------------------------------------

@flask_app.post("/admin/encuesta/libros/crear")
def admin_crear_encuesta_libros():
    return _run_async(create_book_poll(require_admin, telegram_app, TELEGRAM_CHAT_ID, logger))

@flask_app.post("/admin/encuesta/<int:poll_db_id>/cerrar")
def admin_cerrar_encuesta(poll_db_id):
    return _run_async(close_poll(require_admin, poll_db_id, telegram_app, TELEGRAM_CHAT_ID, send_to_group, announce_winner, logger))

# --------------------------------------------------
# FLASK — ENCUESTA TEMÁTICAS
# --------------------------------------------------

@flask_app.post("/admin/encuesta/temas/crear")
def admin_crear_encuesta_temas():
    return _run_async(create_theme_poll(require_admin, telegram_app, TELEGRAM_CHAT_ID, logger))

# --------------------------------------------------
# FLASK — ENCUESTA FECHAS
# --------------------------------------------------

@flask_app.post("/admin/encuesta/fechas/<int:meeting_id>/crear")
def admin_crear_encuesta_fechas(meeting_id):
    return _run_async(create_dates_poll(require_admin, meeting_id, telegram_app, TELEGRAM_CHAT_ID, logger))


@flask_app.post("/admin/encuesta/fechas/<int:meeting_id>/<int:poll_db_id>/cerrar")
def admin_cerrar_encuesta_fechas(meeting_id, poll_db_id):
    return _run_async(
        close_dates_poll(
            require_admin,
            meeting_id,
            poll_db_id,
            telegram_app,
            send_to_group,
            {"bold": bold, "italic": italic, "esc": esc},
            logger,
        )
    )
# --------------------------------------------------

@flask_app.route("/meetings", methods=["GET", "POST"])
def meetings_admin():
    return render_meetings(require_admin)

@flask_app.get("/themes")
def themes_admin():
    return render_themes(require_admin)

@flask_app.get("/ranking")
def ranking_admin():
    return render_ranking(require_admin)

@flask_app.get("/meeting/<int:meeting_id>")
def meeting_detail_admin(meeting_id):
    return render_meeting_detail(require_admin, meeting_id)

@flask_app.post("/meeting/<int:meeting_id>/edit")
def meeting_edit_admin(meeting_id):
    return update_meeting_page(require_admin, meeting_id)

@flask_app.post("/meeting/<int:meeting_id>/delete")
def meeting_delete_admin(meeting_id):
    return delete_meeting_page(require_admin, meeting_id)

@flask_app.post("/meeting/<int:meeting_id>/date-option")
def meeting_add_date_option_admin(meeting_id):
    return add_meeting_date_option(require_admin, meeting_id)

@flask_app.post("/meeting/<int:meeting_id>/close-date")
def meeting_close_date_admin(meeting_id):
    return close_meeting_date(require_admin, meeting_id)

@flask_app.post("/create_meeting")
def create_meeting():
    return create_meeting_page(require_admin, logger)

# --------------------------------------------------
# FLASK — UTILIDADES
# --------------------------------------------------

@flask_app.get("/export")
def export():
    return export_books(require_admin)
    auth = require_admin()
    if auth: return auth
    rows = db.get_books()
    text = "id,title,author,votes\n"
    for r in rows:
        text += f'{r["id"]},"{r["title"]}","{r.get("author","") or ""}",{r["votes"]}\n'
    return Response(text, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=club_lectura_books.csv"})

@flask_app.get("/close_voting")
def close_voting():
    return render_close_voting(require_admin)

@flask_app.get("/attendance")
def attendance():
    return render_attendance(require_admin)

# --------------------------------------------------
# FLASK — TEMÁTICAS (admin CRUD)
# --------------------------------------------------

@flask_app.post("/admin/theme/add")
def admin_theme_add():
    auth = require_admin()
    if auth: return auth
    name = request.form.get("name", "").strip()
    next_url = request.form.get("_next", url_for("themes_admin"))
    if not name:
        flash("El nombre de la temática es obligatorio", "danger")
        return redirect(next_url)
    try:
        db.create_theme(name, created_by="admin")
        flash(f"Temática «{name}» añadida", "success")
    except Exception:
        flash("Error añadiendo la temática", "danger")
    return redirect(next_url)

@flask_app.post("/admin/theme/<int:theme_id>/edit")
def admin_theme_edit(theme_id):
    auth = require_admin()
    if auth: return auth
    name = request.form.get("name", "").strip()
    next_url = request.form.get("_next", url_for("themes_admin"))
    if not name:
        flash("El nombre no puede estar vacío", "danger")
        return redirect(next_url)
    try:
        db.update_theme(theme_id, name)
        flash("Temática actualizada", "success")
    except Exception:
        flash("Error actualizando la temática", "danger")
    return redirect(next_url)

@flask_app.post("/admin/theme/<int:theme_id>/delete")
def admin_theme_delete(theme_id):
    auth = require_admin()
    if auth: return auth
    next_url = request.form.get("_next", url_for("themes_admin"))
    try:
        db.delete_theme(theme_id)
        flash("Temática eliminada", "success")
    except Exception:
        flash("Error eliminando la temática", "danger")
    return redirect(next_url)

# --------------------------------------------------
# FLASK — RECORDATORIOS MANUALES
# --------------------------------------------------

@flask_app.post("/admin/send/meeting-reminder")
def admin_send_meeting_reminder():
    return _run_async(send_manual_meeting_reminder(require_admin, send_meeting_reminder, logger))

@flask_app.post("/admin/send/reading-reminder")
def admin_send_reading_reminder():
    return _run_async(send_manual_reading_reminder(require_admin, send_reading_reminder, logger))

@flask_app.post("/admin/send/meeting-info")
def admin_send_meeting_info():
    return _run_async(send_manual_meeting_info(require_admin, send_to_group, logger))

@flask_app.post("/admin/send/pin-all")
def admin_send_pin_all():
    return _run_async(send_pin_all(require_admin, send_and_pin, logger))

@flask_app.post("/admin/send/dm-reminders/<int:meeting_id>")
def admin_send_dm_reminders(meeting_id):
    return _run_async(send_dm_reminders(require_admin, meeting_id, telegram_app, logger))
@flask_app.get("/admin/historico")
def admin_historico():
    return render_history(require_admin)

# --------------------------------------------------
# FLASK — GALERÍA
# --------------------------------------------------

@flask_app.get("/admin/galeria")
def admin_galeria():
    return render_gallery(require_admin)

@flask_app.post("/admin/galeria/<int:meeting_id>/notes")
def admin_galeria_notes(meeting_id):
    return save_gallery_notes(require_admin, meeting_id)

# --------------------------------------------------
# FLASK — PÁGINA PÚBLICA
# --------------------------------------------------

@flask_app.get("/publico")
def public_page():
    return render_public_page(GROUP_INVITE_LINK)

@flask_app.route("/admin/public-settings", methods=["GET", "POST"])
def admin_public_settings():
    return handle_public_settings(require_admin, GROUP_INVITE_LINK)

# --------------------------------------------------
# FLASK — VISOR DE BASE DE DATOS
# --------------------------------------------------

@flask_app.get("/admin/db")
def admin_db():
    return render_admin_db(require_admin, logger)

@flask_app.post("/admin/db/<table>/delete")
def admin_db_delete_row(table):
    return delete_db_row(require_admin, logger, table)

@flask_app.post("/admin/db/<table>/update")
def admin_db_update_row(table):
    return update_db_row(require_admin, logger, table)

@flask_app.post("/admin/db/<table>/truncate")
def admin_db_truncate(table):
    return truncate_db_table(require_admin, logger, table)

# --------------------------------------------------
# FLASK — BOOK EDIT (admin)
# --------------------------------------------------

@flask_app.post("/admin/book/<int:book_id>/edit")
def admin_book_edit(book_id):
    return edit_book_page(require_admin, logger, book_id)

# --------------------------------------------------
# FLASK — SEND CUSTOM MESSAGE (admin)
# --------------------------------------------------

@flask_app.post("/admin/send/custom")
def admin_send_custom():
    return _run_async(send_custom_message(require_admin, logger, send_to_group))

# --------------------------------------------------
# FLASK — MESSAGE TEMPLATES (admin)
# --------------------------------------------------

@flask_app.get("/admin/messages")
def admin_messages():
    return render_admin_messages(require_admin, DEFAULT_MESSAGES)

@flask_app.post("/admin/messages/<key>/edit")
def admin_message_edit(key):
    return update_admin_message(require_admin, DEFAULT_MESSAGES, key)

@flask_app.post("/admin/messages/<key>/reset")
def admin_message_reset(key):
    return reset_admin_message(require_admin, key)

@flask_app.post("/admin/messages/preview")
def admin_message_preview():
    auth = require_admin()
    if auth:
        return auth
    from flask import jsonify
    template = request.form.get("template", "")
    example_vars = {
        "user_name": "María García",
        "book_title": "El nombre del viento",
        "author": "Patrick Rothfuss",
        "meeting_name": "Reunión de Abril",
        "meeting_date": "2026-04-15 19:00",
        "location": "Casa de Ana",
        "attendee_count": "7",
        "count": "7",
        "names": "María, Carlos, Ana",
        "location_line": "📍 Casa de Ana\n",
        "author_line": "✍️ Patrick Rothfuss\n",
    }
    try:
        rendered = template.format(**example_vars)
    except (KeyError, ValueError):
        rendered = template
    return jsonify({"rendered": rendered})

# --------------------------------------------------
# FLASK — SENT MESSAGES HISTORY
# --------------------------------------------------

@flask_app.get("/admin/sent-messages")
def admin_sent_messages():
    return render_sent_messages(require_admin)

# --------------------------------------------------
# FLASK — MESSAGE SCHEDULER
# --------------------------------------------------

@flask_app.get("/admin/scheduler")
def admin_scheduler():
    return render_scheduler(require_admin)

@flask_app.post("/admin/scheduler/add")
def admin_scheduler_add():
    return add_scheduled_message(require_admin, logger)

@flask_app.post("/admin/scheduler/<int:msg_id>/delete")
def admin_scheduler_delete(msg_id):
    return delete_scheduled_message(require_admin, logger, msg_id)

@flask_app.post("/admin/scheduler/custom/add")
def admin_custom_reminder_add():
    import uuid
    auth = require_admin()
    if auth:
        return auth
    title = request.form.get("title", "").strip()
    message = request.form.get("message", "").strip()
    schedule_type = request.form.get("schedule_type", "interval")
    if not title or not message:
        flash("Título y mensaje son obligatorios", "danger")
        return redirect(url_for("admin_scheduler"))
    try:
        reminders = json.loads(db.get_config("custom_reminders", "[]") or "[]")
    except Exception:
        reminders = []
    new_id = str(uuid.uuid4())[:8]
    reminder = {"id": new_id, "title": title, "message": message, "schedule_type": schedule_type, "enabled": True}
    if schedule_type == "cron":
        reminder["day_of_week"] = request.form.get("day_of_week", "")
        try:
            reminder["hour"] = int(request.form.get("hour", 10))
            reminder["minute"] = int(request.form.get("minute", 0))
        except ValueError:
            reminder["hour"] = 10
            reminder["minute"] = 0
    else:
        try:
            reminder["hours"] = max(1, int(request.form.get("hours", 24)))
        except ValueError:
            reminder["hours"] = 24
    reminders.append(reminder)
    db.set_config("custom_reminders", json.dumps(reminders))
    _reload_custom_reminders()
    flash(f"Recordatorio «{title}» añadido", "success")
    return redirect(url_for("admin_scheduler"))


@flask_app.post("/admin/scheduler/custom/<reminder_id>/delete")
def admin_custom_reminder_delete(reminder_id):
    auth = require_admin()
    if auth:
        return auth
    try:
        reminders = json.loads(db.get_config("custom_reminders", "[]") or "[]")
    except Exception:
        reminders = []
    reminders = [r for r in reminders if r.get("id") != reminder_id]
    db.set_config("custom_reminders", json.dumps(reminders))
    _reload_custom_reminders()
    flash("Recordatorio eliminado", "success")
    return redirect(url_for("admin_scheduler"))


@flask_app.post("/admin/scheduler/custom/<reminder_id>/toggle")
def admin_custom_reminder_toggle(reminder_id):
    auth = require_admin()
    if auth:
        return auth
    try:
        reminders = json.loads(db.get_config("custom_reminders", "[]") or "[]")
    except Exception:
        reminders = []
    for r in reminders:
        if r.get("id") == reminder_id:
            r["enabled"] = not r.get("enabled", True)
            break
    db.set_config("custom_reminders", json.dumps(reminders))
    _reload_custom_reminders()
    flash("Recordatorio actualizado", "success")
    return redirect(url_for("admin_scheduler"))


@flask_app.post("/admin/scheduler/reminder/toggle")
def admin_reminder_toggle():
    auth = require_admin()
    if auth:
        return auth
    from flask import request, redirect, url_for, flash
    key = request.form.get("key", "")
    # key must be one of the known reminder keys
    allowed_keys = {
        "reminder_weekly_enabled", "reminder_reading_enabled",
        "reminder_daybefore_enabled", "reminder_keepalive_enabled"
    }
    if key not in allowed_keys:
        flash("Clave inválida", "danger")
        return redirect(url_for("admin_scheduler"))
    current = db.get_config(key, "1")
    new_val = "0" if current == "1" else "1"
    db.set_config(key, new_val)
    state = "activado" if new_val == "1" else "desactivado"
    flash(f"Recordatorio {state}", "success")
    return redirect(url_for("admin_scheduler"))

# --------------------------------------------------
# FLASK — AI FEATURES
# --------------------------------------------------

@flask_app.get("/admin/ai/questions")
def admin_ai_questions():
    return render_ai_questions(require_admin, logger)

@flask_app.post("/admin/ai/questions/send")
def admin_ai_questions_send():
    return _run_async(send_ai_questions(require_admin, logger, send_to_group))

@flask_app.get("/admin/ai/quote")
def admin_ai_quote():
    return render_ai_quote(require_admin, logger)

@flask_app.post("/admin/ai/quote/send")
def admin_ai_quote_send():
    return _run_async(send_ai_quote(require_admin, logger, send_to_group))

# --------------------------------------------------
# FLASK — AI ASSISTANT (contextual)
# --------------------------------------------------

@flask_app.post("/admin/ai/ask")
def admin_ai_ask():
    return _run_async(ask_admin_ai(require_admin, _utcnow, logger))

# --------------------------------------------------
# FLASK — POSTER DESIGNER
# --------------------------------------------------

@flask_app.get("/admin/poster")
def admin_poster():
    return render_admin_poster(require_admin)

# --------------------------------------------------
# FLASK — ADMIN HELP
# --------------------------------------------------

@flask_app.get("/admin/help")
def admin_help():
    return render_admin_help(require_admin)

# --------------------------------------------------
# FLASK — CYCLE MANAGEMENT (admin)
# --------------------------------------------------

@flask_app.get("/admin/ciclo")
def admin_ciclo():
    return render_admin_cycle(require_admin)

@flask_app.get("/admin/ciclo/easy")
def admin_ciclo_easy():
    auth = require_admin()
    if auth: return auth
    active_keys = db.get_active_cycle_keys()
    cycle = db.get_cycle_state(active_keys[0]) if active_keys else None
    return render_template("admin_ciclo_easy.html", cycle=cycle)

@flask_app.post("/admin/ciclo/nuevo")
def admin_ciclo_nuevo():
    return _run_async(activate_cycle(require_admin, send_to_group, logger, telegram_app, TELEGRAM_CHAT_ID))

@flask_app.post("/admin/ciclo/cerrar")
def admin_ciclo_cerrar():
    return close_cycle(require_admin, logger)

@flask_app.post("/admin/ciclo/tema")
def admin_ciclo_tema():
    return set_cycle_theme(require_admin)

@flask_app.post("/admin/ciclo/desbloquear")
def admin_ciclo_desbloquear():
    return unlock_proposals(require_admin)

@flask_app.post("/admin/ciclo/advance-books")
def admin_ciclo_advance_books():
    return _run_async(advance_to_books(require_admin, send_to_group, logger))

@flask_app.post("/admin/ciclo/pick-theme/<int:theme_id>")
def admin_ciclo_pick_theme(theme_id):
    return _run_async(pick_theme_winner(require_admin, theme_id, send_to_group, logger))

@flask_app.post("/admin/ciclo/pick-book/<int:proposal_id>")
def admin_ciclo_pick_book(proposal_id):
    return _run_async(pick_book_winner(require_admin, proposal_id, announce_winner, logger))

@flask_app.post("/admin/ciclo/<cycle_key>/rename")
def admin_ciclo_rename(cycle_key):
    return rename_cycle(require_admin)


@flask_app.post("/admin/ciclo/meeting/<int:meeting_id>/set-date")
def admin_ciclo_meeting_set_date(meeting_id):
    auth = require_admin()
    if auth:
        return auth
    final_date = request.form.get("final_date", "").strip()
    if not final_date:
        flash("Fecha inválida", "danger")
        return redirect(url_for("admin_ciclo"))
    try:
        db.set_meeting_final_date(meeting_id, final_date)
        flash("Fecha de reunión actualizada", "success")
    except Exception:
        logger.exception("Error actualizando fecha de reunión %s", meeting_id)
        flash("Error actualizando la fecha", "danger")
    return redirect(url_for("admin_ciclo"))

@flask_app.post("/admin/encuesta/temas/<int:poll_db_id>/cerrar")
def admin_cerrar_encuesta_temas(poll_db_id):
    return _run_async(close_theme_poll(require_admin, poll_db_id, telegram_app, TELEGRAM_CHAT_ID, send_to_group, logger))


@flask_app.post("/admin/wizard/new-cycle")
def admin_wizard_new_cycle():
    return _run_async(wizard_new_cycle(require_admin, send_to_group, _utcnow, logger))


@flask_app.post("/admin/wizard/lock-and-poll")
def admin_wizard_lock_and_poll():
    return _run_async(wizard_lock_and_poll(require_admin, telegram_app, TELEGRAM_CHAT_ID, logger))


@flask_app.post("/admin/wizard/announce-date")
def admin_wizard_announce_date():
    return _run_async(wizard_announce_date(require_admin, send_to_group, logger))

# --------------------------------------------------
# FLASK — ASSIGN BOOK TO MEETING (admin)
# --------------------------------------------------

@flask_app.post("/meeting/<int:meeting_id>/set-book")
def meeting_set_book(meeting_id):
    return assign_book_to_meeting(require_admin, meeting_id)

# --------------------------------------------------
# FLASK — BOOK WAITLIST
# --------------------------------------------------

@flask_app.get("/admin/waitlist")
def admin_waitlist():
    return render_waitlist(require_admin)

@flask_app.post("/admin/waitlist/add")
def admin_waitlist_add():
    return add_waitlist_entry(require_admin)

@flask_app.post("/admin/waitlist/<int:wl_id>/delete")
def admin_waitlist_delete(wl_id):
    return delete_waitlist_entry(require_admin, wl_id)

@flask_app.post("/admin/waitlist/suggest")
def admin_waitlist_suggest():
    return _run_async(suggest_waitlist_to_group(require_admin, send_to_group))

# --------------------------------------------------
# FLASK — DEMO / TOUR
# --------------------------------------------------

def _utcnow():
    from datetime import timezone as _tz
    return datetime.now(_tz.utc).replace(tzinfo=None)

@flask_app.get("/admin/demo")
def admin_demo():
    return render_demo_page(require_admin, db)

@flask_app.post("/admin/demo/seed")
def admin_demo_seed():
    return seed_demo_data(require_admin, db, _utcnow, logger)

@flask_app.post("/admin/demo/clear")
def admin_demo_clear():
    return clear_demo_data(require_admin, db, logger)

@flask_app.get("/admin/logs")
def admin_logs():
    return render_admin_logs(require_admin)


# --------------------------------------------------
# FLASK — BUG REPORTS
# --------------------------------------------------

@flask_app.get("/admin/bugs")
def admin_bugs():
    return render_admin_bugs(require_admin)

@flask_app.post("/admin/bugs/<int:report_id>/update")
def admin_bug_update(report_id):
    return update_admin_bug(require_admin, report_id)


# --------------------------------------------------
# WEBHOOK
# --------------------------------------------------

async def _enqueue_webhook_update(data):
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.update_queue.put(update)


@flask_app.post("/webhook")
def webhook():
    try:
        secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not WEBHOOK_SECRET_TOKEN or secret_token != WEBHOOK_SECRET_TOKEN:
            logger.warning("Webhook rechazado por token invalido desde %s", request.remote_addr)
            return Response(status=HTTPStatus.FORBIDDEN)
        data = request.get_json(force=True)
        _run_async(_enqueue_webhook_update(data))
        return Response(status=HTTPStatus.OK)
    except Exception:
        logger.exception("Error procesando webhook")
        return Response(status=HTTPStatus.INTERNAL_SERVER_ERROR)

# --------------------------------------------------
# STARTUP / SHUTDOWN
# --------------------------------------------------

def _make_custom_reminder_job(message_text):
    """Crea una función async que envía el mensaje de recordatorio al grupo."""
    async def _job():
        await send_to_group(message_text, parse_mode="HTML", message_type="custom_reminder")
    return _job


def _reload_custom_reminders():
    """Carga/recarga todos los recordatorios personalizados desde la BD al scheduler."""
    # Eliminar jobs custom existentes
    for job in scheduler.get_jobs():
        if job.id.startswith("custom_reminder_"):
            try:
                scheduler.remove_job(job.id)
            except Exception:
                pass
    # Cargar desde BD
    try:
        reminders = json.loads(db.get_config("custom_reminders", "[]") or "[]")
    except Exception:
        reminders = []
    for r in reminders:
        if not r.get("enabled", True):
            continue
        job_id = f"custom_reminder_{r['id']}"
        message = r.get("message", "")
        if not message:
            continue
        stype = r.get("schedule_type", "interval")
        try:
            if stype == "cron":
                kwargs = {"hour": r.get("hour", 10), "minute": r.get("minute", 0)}
                dow = r.get("day_of_week", "")
                if dow:
                    kwargs["day_of_week"] = dow
                scheduler.add_job(
                    _make_custom_reminder_job(message), "cron",
                    id=job_id, timezone="Europe/Madrid", replace_existing=True, **kwargs
                )
            else:
                scheduler.add_job(
                    _make_custom_reminder_job(message), "interval",
                    hours=max(1, r.get("hours", 24)),
                    id=job_id, replace_existing=True
                )
        except Exception:
            logger.exception("Error cargando recordatorio personalizado %s", r.get("id"))


async def _keep_alive_ping():
    """Hace ping a /health para mantener el servicio activo en Render."""
    if db.get_config("reminder_keepalive_enabled", "1") == "0":
        return
    import urllib.request
    url = f"{WEBHOOK_URL}/health"
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, urllib.request.urlopen, url)
        logger.info("Keep-alive ping OK → %s", url)
    except Exception:
        logger.warning("Keep-alive ping falló → %s", url)


async def startup():
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.bot.set_webhook(
        url=f"{WEBHOOK_URL}/webhook",
        secret_token=WEBHOOK_SECRET_TOKEN,
    )

    # Registrar comandos del bot en Telegram
    user_commands = [
        BotCommand("start", "👋 Bienvenida y menú de comandos"),
        BotCommand("ayuda", "❓ Ver todos los comandos disponibles"),
        BotCommand("proponer", "📚 Proponer un libro para el ciclo"),
        BotCommand("propuestas", "📋 Ver propuestas y votar"),
        BotCommand("votar", "🗳️ Votar una propuesta por número"),
        BotCommand("resultados", "🏆 Ver ranking de votos"),
        BotCommand("libro", "📖 Ver el libro del ciclo actual"),
        BotCommand("tema", "🎭 Proponer una temática"),
        BotCommand("temas", "🎨 Ver temáticas y votar"),
        BotCommand("reunion", "📅 Info de la próxima reunión"),
        BotCommand("asistir", "✅ Apuntarse a la reunión"),
        BotCommand("noasistir", "❌ Quitarse de la reunión"),
        BotCommand("asistencia", "👥 Ver lista de asistentes"),
        BotCommand("acta", "📝 Acta de la última reunión"),
        BotCommand("progreso", "📈 Mi progreso de lectura"),
        BotCommand("estadisticas", "📊 Estadísticas del club"),
        BotCommand("recomendar", "💡 Recomendaciones según temática"),
        BotCommand("lista_espera", "⏳ Libros en lista de espera"),
        BotCommand("bug", "🐛 Reportar un problema o bug"),
    ]
    try:
        await telegram_app.bot.set_my_commands(user_commands, scope=BotCommandScopeAllGroupChats())
        await telegram_app.bot.set_my_commands(user_commands, scope=BotCommandScopeAllPrivateChats())
        logger.info("Comandos del bot registrados en Telegram")
    except Exception:
        logger.warning("No se pudieron registrar los comandos del bot")

    # Comandos extra para admins (con scope por chat individual)
    admin_extra = [
        BotCommand("preguntas", "🤖 Generar preguntas de debate con IA"),
        BotCommand("cita", "✨ Generar cita literaria del libro actual"),
        BotCommand("admin_ayuda", "🛠️ Ayuda de administrador"),
        BotCommand("ciclo", "🔄 Ver ciclo activo"),
        BotCommand("nuevo_ciclo", "🆕 Crear nuevo ciclo"),
        BotCommand("cerrar_ciclo", "🔒 Cerrar ciclo actual"),
        BotCommand("anuncio", "📢 Enviar mensaje al grupo"),
        BotCommand("anunciar_ganador", "🎉 Anunciar libro ganador"),
        BotCommand("encuesta_libros", "📊 Lanzar encuesta de libros"),
        BotCommand("encuesta_temas", "📊 Lanzar encuesta de temáticas"),
        BotCommand("enviar_recordatorio", "🔔 Enviar recordatorio de reunión"),
        BotCommand("enviar_lectura", "📖 Enviar recordatorio de lectura"),
        BotCommand("fijar", "📌 Fijar mensaje en el grupo"),
        BotCommand("desfijar", "📍 Desfijar mensaje actual"),
    ]
    for _admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await telegram_app.bot.set_my_commands(
                user_commands + admin_extra,
                scope=BotCommandScopeChat(chat_id=int(_admin_id))
            )
        except Exception:
            logger.warning("No se pudieron registrar comandos admin para %s", _admin_id)

    # Recordatorio semanal — lunes 10:00
    scheduler.add_job(
        send_meeting_reminder, "cron",
        day_of_week="mon", hour=10, minute=0,
        id="weekly_reminder", replace_existing=True
    )
    # Recordatorio de lectura — cada 2 días
    scheduler.add_job(
        send_reading_reminder, "interval",
        days=2, id="reading_reminder", replace_existing=True
    )
    # Recordatorio día antes — todos los días a las 10:00
    scheduler.add_job(
        send_day_before_reminder, "cron",
        hour=10, minute=0,
        id="day_before_reminder", replace_existing=True
    )
    # Mensajes programados — cada 5 minutos
    scheduler.add_job(
        send_scheduled_messages, "interval",
        minutes=5, id="scheduled_messages", replace_existing=True
    )
    # Keep-alive ping — cada 10 minutos
    scheduler.add_job(
        _keep_alive_ping, "interval",
        minutes=10, id="keep_alive", replace_existing=True
    )
    # Auto-cierre de ciclo — diario a las 23:30
    scheduler.add_job(
        _auto_close_cycle, "cron",
        hour=23, minute=30,
        id="auto_close_cycle", replace_existing=True
    )
    scheduler.start()
    _reload_custom_reminders()


async def main():
    global _bot_loop
    _bot_loop = asyncio.get_event_loop()
    await serve(
        flask_app,
        telegram_app,
        scheduler,
        (
            send_meeting_reminder,
            send_reading_reminder,
            send_day_before_reminder,
            send_scheduled_messages,
        ),
    )


if __name__ == "__main__":
    asyncio.run(main())
