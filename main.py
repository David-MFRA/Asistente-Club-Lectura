import os
import re
import json
import logging
import unicodedata
import time as _time
from datetime import datetime
from http import HTTPStatus

from flask import Flask, request, render_template, redirect, url_for, session, Response, flash, get_flashed_messages, jsonify
from asgiref.wsgi import WsgiToAsgi
import uvicorn

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ChatMemberHandler, CallbackQueryHandler, ContextTypes

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import books_api
import trivia
import recommendations
import db
import ai_features

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# --------------------------------------------------
# DEFAULT MESSAGES — textos editables desde el admin
# --------------------------------------------------

DEFAULT_MESSAGES = {
    "welcome_message": (
        "📚 *¡Bienvenid@ al Club de Lectura!*\n\n"
        "Propón libros, vota, apúntate a reuniones y mucho más.\n\n"
        "Usa /ayuda para ver todos los comandos disponibles. 🚀"
    ),
    "help_message": (
        "📚 *Club de Lectura* — Comandos\n\n"
        "📖 *Libros*\n"
        "  /proponer título — Propone un libro\n"
        "  /propuestas — Lista con botones para votar\n"
        "  /votar N — Vota la propuesta número N\n"
        "  /resultados — Ranking de votos\n"
        "  /libro — Libro del ciclo actual\n\n"
        "🏷️ *Temáticas*\n"
        "  /tema nombre — Propone una temática\n"
        "  /temas — Lista con botones para votar\n\n"
        "📅 *Reunión*\n"
        "  /reunion — Info de la próxima reunión\n"
        "  /asistir — Apuntarse a la reunión\n"
        "  /noasistir — Quitarse de la reunión\n"
        "  /asistencia — Ver asistentes\n"
        "  /acta — Resumen de la última reunión\n\n"
        "📊 *Tu actividad*\n"
        "  /progreso páginas — Registra tu lectura\n"
        "  /estadisticas — Tus estadísticas del club\n\n"
        "🎲 *Extras*\n"
        "  /trivia — Pregunta para el debate\n"
        "  /preguntas — Preguntas de debate con IA\n"
        "  /cita — Cita literaria del libro actual\n"
        "  /recomendar — Libros del tema activo\n"
        "  /lista_espera — Libros en lista de espera\n"
        "  /proponer_fecha DD/MM HH:MM — Proponer fecha de reunión"
    ),
    "next_meeting_message": (
        "📅 *{meeting_name}*\n\n"
        "📆 Fecha: {meeting_date}\n"
        "{location_line}"
        "👥 Apuntados: {attendee_count}"
    ),
    "proposal_confirmation_message": (
        "✅ *¡Libro propuesto!* por {user_name}\n\n"
        "📗 {book_title}\n"
        "{author_line}"
        "_Usa /propuestas para votar._"
    ),
    "attendance_join_message": "🎉 *{user_name}* se apuntó a *{meeting_name}*\n\n👥 Apuntados ({count}): {names}",
    "attendance_leave_message": "👋 *{user_name}* se ha quitado de *{meeting_name}*\n\n👥 Quedan ({count}): {names}",
    "attendance_prompt_message": "📅 ¿A qué reunión te apuntas? Elige una:",
}


def get_text(key, **kwargs):
    """Obtiene texto del template (BD o default) y aplica placeholders."""
    template = db.get_message_template(key)
    if template is None:
        template = DEFAULT_MESSAGES.get(key, "")
    if kwargs:
        try:
            template = template.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return template

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

scheduler = AsyncIOScheduler(timezone="Europe/Madrid")

BOT_TOKEN         = os.getenv("BOT_TOKEN")
WEBHOOK_URL       = os.getenv("WEBHOOK_URL")
PORT              = int(os.environ.get("PORT", "10000"))
ADMIN_SECRET      = os.getenv("ADMIN_SECRET", "")
FLASK_SECRET_KEY  = os.getenv("FLASK_SECRET_KEY", "cambia-esto-en-render")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID")
# Si se define, el bot SOLO responde a comandos de ese chat/grupo
ALLOWED_CHAT_ID   = os.getenv("ALLOWED_CHAT_ID")
# Soporta múltiples admins separados por coma: "123456,789012"
ADMIN_TELEGRAM_IDS = {
    x.strip() for x in os.getenv("ADMIN_TELEGRAM_ID", "").split(",") if x.strip()
}

if not BOT_TOKEN:
    raise RuntimeError("Falta BOT_TOKEN")
if not WEBHOOK_URL:
    raise RuntimeError("Falta WEBHOOK_URL")

# Anti-spam: cooldown por usuario y comando
_cooldowns: dict = {}  # {(user_id, command): last_used_timestamp}

def _check_cooldown(user_id: int, command: str, seconds: int = 20) -> bool:
    """Devuelve True si puede ejecutar (no está en cooldown). Actualiza el timestamp."""
    key = (user_id, command)
    now = _time.monotonic()
    last = _cooldowns.get(key, 0)
    if now - last < seconds:
        return False
    _cooldowns[key] = now
    return True

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

flask_app = Flask(__name__)
flask_app.secret_key = FLASK_SECRET_KEY

# --------------------------------------------------
# MARKDOWN V2 HELPERS
# --------------------------------------------------

def esc(text):
    if not text:
        return ""
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\\-])', r'\\\1', str(text))

def bold(text):   return f"*{esc(text)}*"
def italic(text): return f"_{esc(text)}_"
def code(text):   return f"`{esc(text)}`"

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

async def send_to_group(text, parse_mode="MarkdownV2", reply_markup=None, message_type="custom"):
    if not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_CHAT_ID no configurado")
        return False
    try:
        msg = await telegram_app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
        try:
            db.log_sent_message(message_type, TELEGRAM_CHAT_ID, text, msg.message_id)
        except Exception:
            pass
        return True
    except Exception:
        logger.exception("Error enviando al grupo")
        return False

async def send_and_pin(text, parse_mode=None, reply_markup=None):
    """Envía un mensaje al grupo y lo fija. Guarda el message_id en app_config (soporte multi-pin con coma)."""
    if not TELEGRAM_CHAT_ID:
        return False
    try:
        msg = await telegram_app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
        try:
            await telegram_app.bot.pin_chat_message(
                chat_id=TELEGRAM_CHAT_ID,
                message_id=msg.message_id,
                disable_notification=True
            )
            # Acumular IDs de mensajes fijados (coma-separado) y también guardar el último
            existing = db.get_config("pinned_message_ids") or ""
            ids = [x for x in existing.split(",") if x.strip()]
            ids.append(str(msg.message_id))
            db.set_config("pinned_message_ids", ",".join(ids))
            db.set_config("pinned_message_id", str(msg.message_id))
        except Exception:
            logger.warning("No se pudo fijar el mensaje (¿el bot es admin?)")
        return True
    except Exception:
        logger.exception("Error en send_and_pin")
        return False

async def unpin_group_message():
    """Desfija el mensaje actual del grupo."""
    pinned_id = db.get_config("pinned_message_id")
    if pinned_id and TELEGRAM_CHAT_ID:
        try:
            await telegram_app.bot.unpin_chat_message(
                chat_id=TELEGRAM_CHAT_ID,
                message_id=int(pinned_id)
            )
            db.set_config("pinned_message_id", "")
        except Exception:
            logger.warning("No se pudo desfijar el mensaje")

# --------------------------------------------------
# WINNER ANNOUNCEMENT
# --------------------------------------------------

async def announce_winner(book):
    """Envía ficha completa del libro ganador al grupo."""
    if not TELEGRAM_CHAT_ID:
        return
    votes = book.get("votes", 0)
    lines = ["🏆 ¡Tenemos libro del mes!\n"]
    lines.append(f"📗 {book['title']}")
    if book.get("author"):
        lines.append(f"✍️ {book['author']}")
    if book.get("pages"):
        lines.append(f"📄 {book['pages']} páginas")
    if book.get("language_code"):
        lines.append(f"🌐 Idioma: {str(book['language_code']).upper()}")
    lines.append(f"\n🗳️ Ganó con {votes} voto{'s' if votes != 1 else ''}")
    if book.get("description"):
        desc = book["description"]
        if len(desc) > 600:
            desc = desc[:597] + "…"
        lines.append(f"\n📖 Sinopsis\n{desc}")
    lines.append("\n¡A leer se ha dicho! 🚀 Usa /asistir para apuntarte a la reunión.")
    text = "\n".join(lines)

    keyboard = [[InlineKeyboardButton("✅ Asistir", callback_data="attend:next"),
                 InlineKeyboardButton("❌ No asistir", callback_data="noattend:next")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if book.get("cover"):
            await telegram_app.bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID,
                photo=book["cover"],
                caption=text,
                parse_mode=None,
                reply_markup=reply_markup
            )
            return
    except Exception:
        pass
    await send_to_group(text, reply_markup=reply_markup)

# --------------------------------------------------
# TELEGRAM COMMANDS
# --------------------------------------------------

async def start(update, context):
    if not _allowed_chat(update): return
    raw = get_text("welcome_message")
    await update.message.reply_text(raw, parse_mode=None)


async def ayuda_cmd(update, context):
    if not _allowed_chat(update): return
    raw = get_text("help_message")
    await update.message.reply_text(raw, parse_mode=None)


async def proponer(update, context):
    if not _allowed_chat(update): return
    if not _check_cooldown(update.effective_user.id, "proponer", 30):
        await update.message.reply_text("⏳ Espera unos segundos antes de volver a usar este comando.", parse_mode=None)
        return
    if db.get_config("proposals_locked_for") == db.get_current_cycle_key():
        await update.message.reply_text(
            "❌ Las propuestas para este ciclo están cerradas. ¡Espera al siguiente ciclo!",
            parse_mode=None
        )
        return
    title = " ".join(context.args).strip()
    if not title:
        await update.message.reply_text(
            f"📖 Usa {code('/proponer título del libro')}", parse_mode="MarkdownV2"
        )
        return
    try:
        wait_msg = await update.message.reply_text(
            f"🔍 Buscando _{esc(title)}_\\.\\.\\.", parse_mode="MarkdownV2"
        )
        book = books_api.google_books(title)
        if not book:
            await wait_msg.delete()
            await update.message.reply_text(
                "❌ No encontré ese libro\\. Prueba con un título más completo\\.",
                parse_mode="MarkdownV2"
            )
            return
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        db.insert_book(book, user)
        await wait_msg.delete()

        lines = [f"✅ {bold('¡Libro propuesto!')} por {italic(user)}\n"]
        lines.append(f"📗 {bold(book['title'])}")
        if book.get("author"):
            lines.append(f"✍️ {italic(book['author'])}")
        if book.get("pages"):
            lines.append(f"📄 {esc(str(book['pages']))} páginas")
        if book.get("description"):
            desc = book["description"]
            if len(desc) > 300:
                desc = desc[:297] + "…"
            lines.append(f"\n💬 _{esc(desc)}_")
        lines.append(f"\n_Usa /propuestas y /votar para votar\\._")
        caption = "\n".join(lines)

        if book.get("cover"):
            await update.message.reply_photo(photo=book["cover"], caption=caption, parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(caption, parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /proponer")
        await update.message.reply_text("⚠️ Error añadiendo el libro\\.", parse_mode="MarkdownV2")


async def propuestas(update, context):
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
    try:
        if context.args:
            query = " ".join(context.args)
            meeting = _find_meeting_by_text(query)
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
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    query = update.callback_query
    await query.answer()
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
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    name = " ".join(context.args).strip() if context.args else None
    if not name:
        from datetime import timezone as _tz
        name = datetime.now(_tz.utc).strftime("%Y-%m")
    db.set_config("active_cycle_key", name)
    await update.message.reply_text(
        f"✅ {bold('Nuevo ciclo creado')}: {code(name)}\n"
        f"_A partir de ahora las propuestas y temáticas se guardan en este ciclo\\._",
        parse_mode="MarkdownV2"
    )


async def cerrar_ciclo_cmd(update, context):
    if not is_admin_user(update): return
    cycle = db.get_current_cycle_key()
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
            db.save_poll(chat_id=tie_poll.chat_id, message_id=tie_poll.message_id,
                         poll_id=tie_poll.poll.id, poll_type="books")
        await update.message.reply_text(f"⚖️ Empate detectado. Encuesta de desempate lanzada.", parse_mode=None)
        return
    winner = db.get_winner_book()
    if not winner:
        await update.message.reply_text("📭 No hay libro ganador todavía\\.", parse_mode="MarkdownV2")
        return
    await announce_winner(winner)
    await update.message.reply_text("✅ Anuncio enviado al grupo\\.", parse_mode="MarkdownV2")


async def enviar_recordatorio_cmd(update, context):
    if not is_admin_user(update): return
    await send_meeting_reminder()
    await update.message.reply_text("✅ Recordatorio de reunión enviado\\.", parse_mode="MarkdownV2")


async def enviar_lectura_cmd(update, context):
    if not is_admin_user(update): return
    await send_reading_reminder()
    await update.message.reply_text("✅ Recordatorio de lectura enviado\\.", parse_mode="MarkdownV2")


async def encuesta_libros_cmd(update, context):
    """Admin: lanza encuesta de libros desde el chat."""
    if not is_admin_user(update): return
    try:
        books = db.get_book_proposals()
        if len(books) < 2:
            await update.message.reply_text("❌ Necesitas al menos 2 propuestas.", parse_mode=None)
            return
        if not TELEGRAM_CHAT_ID:
            await update.message.reply_text("❌ TELEGRAM_CHAT_ID no configurado.", parse_mode=None)
            return
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
                     poll_id=msg.poll.id, poll_type="books")
        await update.message.reply_text("✅ Encuesta de libros lanzada.", parse_mode=None)
    except Exception:
        logger.exception("Error en /encuesta_libros")
        await update.message.reply_text("⚠️ Error lanzando la encuesta.", parse_mode=None)


async def encuesta_temas_cmd(update, context):
    """Admin: lanza encuesta de temáticas desde el chat."""
    if not is_admin_user(update): return
    try:
        themes = db.get_themes()
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
                     poll_id=msg.poll.id, poll_type="themes")
        await update.message.reply_text("✅ Encuesta de temáticas lanzada.", parse_mode=None)
    except Exception:
        logger.exception("Error en /encuesta_temas")
        await update.message.reply_text("⚠️ Error lanzando la encuesta.", parse_mode=None)


# --------------------------------------------------
# SCHEDULED REMINDERS
# --------------------------------------------------

async def send_meeting_reminder():
    """Recordatorio semanal con días restantes y ritmo de páginas. Incluye todas las reuniones activas."""
    all_meetings = db.get_meetings(limit=10)
    now = datetime.utcnow()
    upcoming = []
    for m in all_meetings:
        if m.get("status") == "closed":
            continue
        upcoming.append(m)
    if not upcoming:
        return

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

        fecha_str = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
        names = "\n".join(f"  • {a}" for a in asistentes) if asistentes else "Nadie apuntado todavía"

        lines = [f"📅 Recordatorio semanal del club\n"]
        lines.append(f"Reunión: {meeting['name']}")
        lines.append(f"📆 Fecha: {fecha_str}")

        if meeting.get("location"):
            lines.append(f"📍 Lugar: {meeting['location']}")
        if meeting.get("notes"):
            lines.append(f"📝 {meeting['notes']}")

        if days_left is not None:
            if days_left > 0:
                lines.append(f"⏳ Faltan {days_left} día{'s' if days_left != 1 else ''} para la reunión")
            elif days_left == 0:
                lines.append(f"🔔 ¡La reunión es HOY!")
            else:
                lines.append(f"🔒 La reunión ya pasó hace {abs(days_left)} días")

        if book and book.get("title"):
            lines.append(f"\n📗 Libro: {book['title']}")
            if book.get("author"):
                lines.append(f"   ✍️ {book['author']}")

            pages = book.get("pages")
            if pages and days_left and days_left > 0:
                total_days = 30
                elapsed    = max(0, total_days - days_left)
                pages_now  = int(pages * elapsed / total_days)
                daily_pace = max(1, int(pages / total_days))
                lines.append(
                    f"\n📊 Ritmo de lectura\n"
                    f"  Para estar al día deberías llevar unas {pages_now} páginas de {pages} en total ✨\n"
                    f"  (Son unos {daily_pace} páginas al día, ¡tú puedes!)"
                )
            progress_list = db.get_reading_progress(book["id"])
            if progress_list and pages:
                lines.append(f"\n📖 Progreso del grupo")
                for p in progress_list[:5]:
                    pct = int(p["pages_read"] / pages * 100) if pages > 0 else 0
                    lines.append(f"  • {p['user_name']}: {p['pages_read']} págs ({pct}%)")

        lines.append(f"\n👥 Apuntados ({len(asistentes)}):\n{names}")
        lines.append(f"\n¿Aún no te has apuntado? Usa /asistir 📖")

        keyboard = [
            [
                InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{meeting['id']}"),
                InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
            ]
        ]
        if meeting.get("book_id"):
            keyboard.append([InlineKeyboardButton("📗 Ver libro", callback_data=f"bookinfo:{meeting['book_id']}")])

        await send_to_group("\n".join(lines), parse_mode=None, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        # Modo multi-reunión: mensaje combinado con todas las reuniones activas
        lines = ["📌 REUNIONES ACTIVAS\n"]
        keyboard = []
        for idx, meeting in enumerate(upcoming[:5], 1):
            asistentes = db.get_attendance(meeting["id"])
            fecha_str = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
            lines.append(f"📅 Reunión {idx}: {meeting['name']}")
            lines.append(f"   📆 Fecha: {fecha_str}")
            if meeting.get("location"):
                lines.append(f"   📍 Lugar: {meeting['location']}")
            lines.append(f"   👥 Apuntados: {len(asistentes)}")
            if idx < len(upcoming[:5]):
                lines.append("")
            # Botones por reunión
            short_name = meeting['name'][:20]
            keyboard.append([
                InlineKeyboardButton(f"✅ {short_name}", callback_data=f"attend:{meeting['id']}"),
                InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
            ])

        lines.append(f"\nUsa /asistir para apuntarte a una reunión concreta 📖")
        await send_to_group("\n".join(lines), parse_mode=None, reply_markup=InlineKeyboardMarkup(keyboard))


async def send_reading_reminder():
    """Recordatorio de lectura cada 2 días."""
    meeting = db.get_latest_scheduled_meeting()
    # Usar el libro de la reunión, no el ganador del ciclo
    book = None
    if meeting and meeting.get("book_id"):
        book = db.get_book_by_id(meeting["book_id"])
    if not book:
        book = db.get_winner_book()
    if not book:
        return
    fecha = str(meeting["final_date"])[:16] if meeting and meeting.get("final_date") else "Sin fecha"
    reunion_name = meeting["name"] if meeting else "Sin reunión"
    author_line = f"\n✍️ {book['author']}" if book.get("author") else ""
    text = (
        f"📖 Recordatorio de lectura\n\n"
        f"El libro del ciclo es:\n"
        f"📗 {book['title']}{author_line}\n\n"
        f"📅 Reunión: {reunion_name}\n"
        f"📆 Fecha: {fecha}\n\n"
        f"¡A leer se ha dicho! 🚀"
    )
    keyboard = []
    if meeting:
        keyboard.append([
            InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{meeting['id']}"),
            InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
        ])
    await send_to_group(text, parse_mode=None, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)


# --------------------------------------------------
# DAY-BEFORE REMINDER
# --------------------------------------------------

async def send_day_before_reminder():
    """Recordatorio cuando la reunión es mañana o hoy."""
    meeting = db.get_latest_scheduled_meeting()
    if not meeting or not meeting.get("final_date"):
        return
    final_dt = meeting["final_date"]
    if isinstance(final_dt, str):
        final_dt = datetime.fromisoformat(final_dt)
    days_left = (final_dt - datetime.utcnow()).days
    if days_left not in (0, 1):
        return
    winner = db.get_winner_book()
    asistentes = db.get_attendance(meeting["id"])
    if days_left == 1:
        header = f"🔔 ¡La reunión es MAÑANA!"
    else:
        header = f"🚨 ¡La reunión es HOY!"
    lines = [
        header + "\n",
        f"📅 {meeting['name']}",
        f"🗓️ {str(final_dt)[:16]}",
    ]
    if meeting.get("location"):
        lines.append(f"📍 {meeting['location']}")
    if winner:
        lines.append(f"📗 Libro: {winner['title']}")
    names = "\n".join(f"  ✅ {a}" for a in asistentes) if asistentes else "Nadie apuntado"
    lines.append(f"\n👥 Apuntados ({len(asistentes)}):\n{names}")
    lines.append(f"\n¿Aún no te has apuntado? Usa /asistir 📚")
    keyboard = [
        [
            InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{meeting['id']}"),
            InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
        ]
    ]
    await send_to_group("\n".join(lines), parse_mode=None, reply_markup=InlineKeyboardMarkup(keyboard))


async def send_scheduled_messages():
    """Envía mensajes programados pendientes."""
    try:
        pending = db.get_pending_scheduled_messages()
        for msg in pending:
            await send_to_group(msg["text"], parse_mode=None, message_type="scheduled")
            db.mark_scheduled_message_sent(msg["id"])
            logger.info("Mensaje programado #%s enviado", msg["id"])
    except Exception:
        logger.exception("Error en send_scheduled_messages")


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
    ok = await send_and_pin("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
    if ok:
        await update.message.reply_text("📌 Mensaje fijado en el grupo.", parse_mode=None)
    else:
        await update.message.reply_text("❌ Error enviando el mensaje.", parse_mode=None)


async def desfijar_cmd(update, context):
    """Admin: desfija el mensaje actual."""
    if not is_admin_user(update): return
    await unpin_group_message()
    await update.message.reply_text("📌 Mensaje desfijado.", parse_mode=None)


async def preguntas_cmd(update, context):
    """Genera preguntas de debate para el libro actual."""
    if not _allowed_chat(update): return
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
        await update.message.reply_text(
            f"💬 Preguntas de debate — {winner['title']}\n\n{questions}",
            parse_mode=None
        )
    except Exception:
        logger.exception("Error en /preguntas")
        await update.message.reply_text("⚠️ Error generando preguntas.", parse_mode=None)


async def lista_espera_cmd(update, context):
    if not _allowed_chat(update): return
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
    if not _allowed_chat(update): return
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
    """Genera una cita literaria relacionada con el libro actual."""
    if not _allowed_chat(update): return
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


# --------------------------------------------------
# REGISTER HANDLERS
# --------------------------------------------------

telegram_app.add_handler(CommandHandler("start",      start))
telegram_app.add_handler(CommandHandler("proponer",   proponer))
telegram_app.add_handler(CommandHandler("propuestas", propuestas))
telegram_app.add_handler(CommandHandler("votar",      votar))
telegram_app.add_handler(CommandHandler("resultados", resultados))
telegram_app.add_handler(CommandHandler("reunion",    reunion))
telegram_app.add_handler(CommandHandler("asistir",    asistir))
telegram_app.add_handler(CommandHandler("noasistir",  noasistir))
telegram_app.add_handler(CommandHandler("asistencia", asistencia))
telegram_app.add_handler(CommandHandler("tema",       tema))
telegram_app.add_handler(CommandHandler("temas",      temas))
telegram_app.add_handler(CommandHandler("votar_tema", votar_tema))
telegram_app.add_handler(CommandHandler("trivia",     trivia_cmd))
telegram_app.add_handler(CommandHandler("recomendar", recomendar))
telegram_app.add_handler(CommandHandler("libro",            libro_cmd))
telegram_app.add_handler(CommandHandler("acta",             acta_cmd))
telegram_app.add_handler(CommandHandler("progreso",         progreso_cmd))
telegram_app.add_handler(CommandHandler("estadisticas",     estadisticas_cmd))
telegram_app.add_handler(CommandHandler("admin_ayuda",      admin_ayuda_cmd))
telegram_app.add_handler(CommandHandler("ciclo",            ciclo_cmd))
telegram_app.add_handler(CommandHandler("nuevo_ciclo",      nuevo_ciclo_cmd))
telegram_app.add_handler(CommandHandler("cerrar_ciclo",     cerrar_ciclo_cmd))
telegram_app.add_handler(CommandHandler("anuncio",          anuncio_cmd))
telegram_app.add_handler(CommandHandler("anunciar_ganador", anunciar_ganador_cmd))
telegram_app.add_handler(CommandHandler("enviar_recordatorio", enviar_recordatorio_cmd))
telegram_app.add_handler(CommandHandler("enviar_lectura",   enviar_lectura_cmd))
telegram_app.add_handler(CommandHandler("ayuda",            ayuda_cmd))
telegram_app.add_handler(CommandHandler("encuesta_libros",  encuesta_libros_cmd))
telegram_app.add_handler(CommandHandler("encuesta_temas",   encuesta_temas_cmd))
telegram_app.add_handler(CommandHandler("fijar",            fijar_cmd))
telegram_app.add_handler(CommandHandler("desfijar",         desfijar_cmd))
telegram_app.add_handler(CommandHandler("preguntas",        preguntas_cmd))
telegram_app.add_handler(CommandHandler("cita",             cita_cmd))
telegram_app.add_handler(CommandHandler("lista_espera",     lista_espera_cmd))
telegram_app.add_handler(CommandHandler("proponer_fecha",   proponer_fecha_cmd))
telegram_app.add_handler(ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
telegram_app.add_handler(CallbackQueryHandler(button_handler))

# --------------------------------------------------
# FLASK — AUTH
# --------------------------------------------------

@flask_app.get("/")
def home():
    return "ok", 200

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
    secret = request.form.get("secret", "").strip()
    if not ADMIN_SECRET:
        return "ADMIN_SECRET no configurado", 500
    if secret != ADMIN_SECRET:
        return render_template("admin_login.html", error="Secreto incorrecto"), 403
    session["admin_logged"] = True
    return redirect(url_for("admin_dashboard"))

@flask_app.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

# --------------------------------------------------
# FLASK — DASHBOARD
# --------------------------------------------------

@flask_app.get("/admin")
def admin_dashboard():
    auth = require_admin()
    if auth: return auth
    books            = db.get_books()
    meetings         = db.get_meetings(limit=5)
    themes           = db.get_themes()
    ranking          = db.get_book_ranking()
    open_poll_books  = db.get_open_poll(poll_type="books")
    open_poll_themes = db.get_open_poll(poll_type="themes")
    cycle_state      = db.get_cycle_dashboard_state()
    tied_books       = db.get_tied_books()
    return render_template(
        "admin.html",
        books=books, meetings=meetings, themes=themes, ranking=ranking,
        open_poll_books=open_poll_books, open_poll_themes=open_poll_themes,
        cycle_state=cycle_state, tied_books=tied_books,
        tied_count=len(tied_books),
    )

# --------------------------------------------------
# FLASK — LIBROS (admin)
# --------------------------------------------------

@flask_app.post("/admin/book/add")
def admin_book_add():
    auth = require_admin()
    if auth: return auth
    title = request.form.get("title", "").strip()
    if not title:
        return redirect(url_for("admin_dashboard"))
    try:
        book = books_api.google_books(title)
        if not book:
            book = {
                "title":  title,
                "author": request.form.get("author", "").strip() or None,
            }
        db.insert_book(book, proposed_by="admin")
    except Exception:
        logger.exception("Error añadiendo libro desde admin")
    return redirect(url_for("admin_dashboard"))

@flask_app.post("/admin/book/<int:proposal_id>/delete")
def admin_book_delete(proposal_id):
    auth = require_admin()
    if auth: return auth
    db.remove_book_proposal(proposal_id)
    return redirect(url_for("admin_dashboard"))

# --------------------------------------------------
# FLASK — ENCUESTA LIBROS
# --------------------------------------------------

@flask_app.post("/admin/encuesta/libros/crear")
async def admin_crear_encuesta_libros():
    auth = require_admin()
    if auth: return auth
    try:
        books = db.get_book_proposals()
        if len(books) < 2:
            return "Necesitas al menos 2 propuestas para crear una encuesta", 400
        if not TELEGRAM_CHAT_ID:
            return "TELEGRAM_CHAT_ID no configurado en variables de entorno", 500

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
                     poll_id=msg.poll.id, poll_type="books")
    except Exception:
        logger.exception("Error creando encuesta libros")
        return "Error creando encuesta", 500
    return redirect(url_for("admin_dashboard"))

@flask_app.post("/admin/encuesta/<int:poll_db_id>/cerrar")
async def admin_cerrar_encuesta(poll_db_id):
    auth = require_admin()
    if auth: return auth
    try:
        poll = db.get_poll_by_id(poll_db_id)
        if not poll:
            return "Encuesta no encontrada", 404
        await telegram_app.bot.stop_poll(chat_id=poll["chat_id"], message_id=poll["message_id"])
        db.close_poll(poll_db_id)
        # Anunciar ganador y auto-asignar a la reunión próxima
        if poll.get("poll_type") == "books" and TELEGRAM_CHAT_ID:
            tied = db.get_tied_books()
            if len(tied) > 1:
                # Send tie notification
                tie_msg = (
                    f"⚖️ ¡Hay empate en la votación!\n\n"
                    f"Los siguientes libros han quedado empatados con {tied[0]['votes']} votos:\n"
                )
                for b in tied:
                    tie_msg += f"  📖 {b['title']}" + (f" — {b['author']}" if b.get('author') else "") + "\n"
                tie_msg += "\n🔁 Lanzando encuesta de desempate..."
                await send_to_group(tie_msg, parse_mode=None, message_type="tie_notification")

                # Create tiebreaker poll
                options = []
                for b in tied[:10]:
                    label = b["title"]
                    if b.get("author"):
                        label = f"{b['title']} — {b['author']}"
                    options.append(label[:100])

                tie_poll = await telegram_app.bot.send_poll(
                    chat_id=TELEGRAM_CHAT_ID,
                    question=f"⚖️ Desempate — ¿Cuál de estos {len(tied)} libros leemos?",
                    options=options,
                    is_anonymous=False,
                    allows_multiple_answers=False,
                )
                db.save_poll(chat_id=tie_poll.chat_id, message_id=tie_poll.message_id,
                             poll_id=tie_poll.poll.id, poll_type="books")
                flash(f"¡Empate detectado! Se ha lanzado una encuesta de desempate con {len(tied)} libros.", "warning")
                return redirect(url_for("admin_dashboard"))
            else:
                winner = db.get_winner_book()
                if winner:
                    await announce_winner(winner)
                    # Asignar automáticamente el libro ganador a la próxima reunión
                    next_meeting = db.get_latest_scheduled_meeting()
                    if next_meeting and not next_meeting.get("book_id"):
                        db.update_meeting(meeting_id=next_meeting["id"], book_id=winner["id"])
                        logger.info("Libro ganador '%s' asignado automáticamente a '%s'",
                                    winner["title"], next_meeting["name"])
    except Exception:
        logger.exception("Error cerrando encuesta")
        return "Error cerrando encuesta", 500
    return redirect(url_for("admin_dashboard"))

# --------------------------------------------------
# FLASK — ENCUESTA TEMÁTICAS
# --------------------------------------------------

@flask_app.post("/admin/encuesta/temas/crear")
async def admin_crear_encuesta_temas():
    auth = require_admin()
    if auth: return auth
    try:
        themes = db.get_themes()
        if len(themes) < 2:
            return "Necesitas al menos 2 temáticas para crear una encuesta", 400
        if not TELEGRAM_CHAT_ID:
            return "TELEGRAM_CHAT_ID no configurado", 500

        options = [t["name"][:100] for t in themes[:10]]
        msg = await telegram_app.bot.send_poll(
            chat_id=TELEGRAM_CHAT_ID,
            question="🏷️ ¿Qué temática elegimos para el próximo ciclo?",
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        db.save_poll(chat_id=msg.chat_id, message_id=msg.message_id,
                     poll_id=msg.poll.id, poll_type="themes")
    except Exception:
        logger.exception("Error creando encuesta temas")
        return "Error creando encuesta", 500
    return redirect(url_for("admin_dashboard"))

# --------------------------------------------------
# FLASK — ENCUESTA FECHAS
# --------------------------------------------------

@flask_app.post("/admin/encuesta/fechas/<int:meeting_id>/crear")
async def admin_crear_encuesta_fechas(meeting_id):
    auth = require_admin()
    if auth: return auth
    try:
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            return "Reunión no encontrada", 404
        date_options = db.get_meeting_date_options(meeting_id)
        if len(date_options) < 2:
            return "Añade al menos 2 opciones de fecha primero", 400
        if not TELEGRAM_CHAT_ID:
            return "TELEGRAM_CHAT_ID no configurado", 500

        poll_options = [str(o["option_date"])[:20] for o in date_options[:10]]
        msg = await telegram_app.bot.send_poll(
            chat_id=TELEGRAM_CHAT_ID,
            question=f"📅 ¿Cuándo nos reunimos? — {meeting['name']}",
            options=poll_options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        db.save_poll(chat_id=msg.chat_id, message_id=msg.message_id,
                     poll_id=msg.poll.id, poll_type="dates", meeting_id=meeting_id)
    except Exception:
        logger.exception("Error creando encuesta fechas")
        return "Error creando encuesta fechas", 500
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))

@flask_app.post("/admin/encuesta/fechas/<int:meeting_id>/cerrar/<int:poll_db_id>")
async def admin_cerrar_encuesta_fechas(meeting_id, poll_db_id):
    auth = require_admin()
    if auth: return auth
    try:
        poll = db.get_poll_by_id(poll_db_id)
        if not poll:
            return "Encuesta no encontrada", 404

        tg_poll = await telegram_app.bot.stop_poll(
            chat_id=poll["chat_id"],
            message_id=poll["message_id"]
        )
        db.close_poll(poll_db_id)

        # Asignar fecha ganadora a la reunión
        if tg_poll.options:
            winner_text = max(tg_poll.options, key=lambda o: o.voter_count).text
            date_opts   = db.get_meeting_date_options(meeting_id)
            for opt in date_opts:
                opt_str = str(opt["option_date"])
                if winner_text[:16] in opt_str[:20] or opt_str[:16] in winner_text[:20]:
                    db.set_meeting_final_date(meeting_id, opt["option_date"])
                    meeting_name = db.get_meeting(meeting_id)["name"]
                    await send_to_group(
                        f"📅 {bold('¡Fecha de reunión decidida!')}\n\n"
                        f"La reunión {italic(meeting_name)} será el "
                        f"{bold(esc(opt_str))}\\.\n\n"
                        f"_Usa /asistir para apuntarte\\. ¡Os esperamos\\! 🎉_"
                    )
                    break
    except Exception:
        logger.exception("Error cerrando encuesta fechas")
        return "Error cerrando encuesta fechas", 500
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))

# --------------------------------------------------
# FLASK — REUNIONES
# --------------------------------------------------

@flask_app.route("/meetings", methods=["GET", "POST"])
def meetings_admin():
    auth = require_admin()
    if auth: return auth
    if request.method == "POST":
        name         = request.form.get("meeting_name", "").strip()
        meeting_date = request.form.get("meeting_date", "").strip() or None
        location     = request.form.get("location", "").strip() or None
        if not name:
            meetings_list = db.get_meetings()
            meetings_json = json.dumps([{'id': m['id'], 'name': m['name'], 'final_date': str(m['final_date'])[:10] if m.get('final_date') else None, 'status': m.get('status', 'draft')} for m in meetings_list])
            return render_template("meetings.html", meetings=meetings_list, meetings_json=meetings_json, error="Falta el nombre")
        try:
            m = db.create_meeting(name=name, final_date=meeting_date, created_by="admin")
            if location:
                db.update_meeting(meeting_id=m["id"], location=location)
        except Exception:
            logger.exception("Error creando reunión")
        return redirect(url_for("meetings_admin"))
    meetings_list = db.get_meetings()
    meetings_json = json.dumps([{
        'id': m['id'], 'name': m['name'],
        'final_date': str(m['final_date'])[:10] if m.get('final_date') else None,
        'status': m.get('status', 'draft')
    } for m in meetings_list])
    return render_template("meetings.html", meetings=meetings_list, meetings_json=meetings_json)

@flask_app.get("/themes")
def themes_admin():
    auth = require_admin()
    if auth: return auth
    themes = db.get_themes()
    return render_template("themes.html", themes=themes)

@flask_app.get("/ranking")
def ranking_admin():
    auth = require_admin()
    if auth: return auth
    ranking = db.get_book_ranking()
    return render_template("ranking.html", ranking=ranking)

@flask_app.get("/meeting/<int:meeting_id>")
def meeting_detail_admin(meeting_id):
    auth = require_admin()
    if auth: return auth
    meeting = db.get_meeting(meeting_id)
    if not meeting:
        return "Reunión no encontrada", 404
    attendees    = db.get_attendance(meeting_id)
    date_options = db.get_meeting_date_options(meeting_id)
    open_poll    = db.get_open_poll(poll_type="dates", meeting_id=meeting_id)
    return render_template(
        "meeting_detail.html",
        meeting=meeting,
        attendees=attendees,
        date_options=date_options,
        open_poll=open_poll,
    )

@flask_app.post("/meeting/<int:meeting_id>/edit")
def meeting_edit_admin(meeting_id):
    auth = require_admin()
    if auth: return auth
    name       = request.form.get("name", "").strip()
    final_date = request.form.get("final_date", "").strip() or None
    summary    = request.form.get("summary", "").strip() or None
    status     = request.form.get("status", "").strip() or None
    location   = request.form.get("location", "").strip() or None
    notes      = request.form.get("notes", "").strip() or None
    db.update_meeting(meeting_id=meeting_id, name=name or None, final_date=final_date,
                      summary=summary, status=status, location=location, notes=notes)
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))

@flask_app.post("/meeting/<int:meeting_id>/delete")
def meeting_delete_admin(meeting_id):
    auth = require_admin()
    if auth: return auth
    db.delete_meeting(meeting_id)
    return redirect(url_for("meetings_admin"))

@flask_app.post("/meeting/<int:meeting_id>/date-option")
def meeting_add_date_option_admin(meeting_id):
    auth = require_admin()
    if auth: return auth
    option_date = request.form.get("option_date", "").strip()
    if not option_date:
        return "Fecha obligatoria", 400
    db.add_meeting_date_option(meeting_id, option_date)
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))

@flask_app.post("/meeting/<int:meeting_id>/close-date")
def meeting_close_date_admin(meeting_id):
    auth = require_admin()
    if auth: return auth
    final_date = request.form.get("final_date", "").strip()
    if not final_date:
        return "Fecha obligatoria", 400
    db.set_meeting_final_date(meeting_id, final_date)
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))

@flask_app.post("/create_meeting")
def create_meeting():
    auth = require_admin()
    if auth: return auth
    name         = request.form.get("meeting_name", "").strip()
    meeting_date = request.form.get("meeting_date", "").strip() or None
    location     = request.form.get("location", "").strip() or None
    if not name:
        return "Falta el nombre", 400
    try:
        m = db.create_meeting(name=name, final_date=meeting_date, created_by="admin")
        if location:
            db.update_meeting(meeting_id=m["id"], location=location)
        return redirect(url_for("meetings_admin"))
    except Exception:
        logger.exception("Error creando reunión")
        return "Error creando reunión", 500

# --------------------------------------------------
# FLASK — UTILIDADES
# --------------------------------------------------

@flask_app.get("/export")
def export():
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
    auth = require_admin()
    if auth: return auth
    winner = db.get_winner_book()
    if not winner:
        return "No hay libros propuestos", 404
    return f"Libro ganador actual: {winner['title']} ({winner['votes']} votos)"

@flask_app.get("/attendance")
def attendance():
    auth = require_admin()
    if auth: return auth
    latest_meeting = db.get_latest_meeting()
    if not latest_meeting:
        return render_template("attendance.html", meeting=None, attendees=[])
    attendees = db.get_attendance(latest_meeting["id"])
    return render_template("attendance.html", meeting=latest_meeting, attendees=attendees)

# --------------------------------------------------
# FLASK — TEMÁTICAS (admin CRUD)
# --------------------------------------------------

@flask_app.post("/admin/theme/add")
def admin_theme_add():
    auth = require_admin()
    if auth: return auth
    name = request.form.get("name", "").strip()
    if name:
        db.create_theme(name, created_by="admin")
    return redirect(url_for("themes_admin"))

@flask_app.post("/admin/theme/<int:theme_id>/edit")
def admin_theme_edit(theme_id):
    auth = require_admin()
    if auth: return auth
    name = request.form.get("name", "").strip()
    if name:
        db.update_theme(theme_id, name)
    return redirect(url_for("themes_admin"))

@flask_app.post("/admin/theme/<int:theme_id>/delete")
def admin_theme_delete(theme_id):
    auth = require_admin()
    if auth: return auth
    db.delete_theme(theme_id)
    return redirect(url_for("themes_admin"))

# --------------------------------------------------
# FLASK — RECORDATORIOS MANUALES
# --------------------------------------------------

@flask_app.post("/admin/send/meeting-reminder")
async def admin_send_meeting_reminder():
    auth = require_admin()
    if auth: return auth
    try:
        await send_meeting_reminder()
    except Exception:
        logger.exception("Error enviando recordatorio de reunión manual")
    return redirect(url_for("admin_dashboard"))

@flask_app.post("/admin/send/reading-reminder")
async def admin_send_reading_reminder():
    auth = require_admin()
    if auth: return auth
    try:
        await send_reading_reminder()
    except Exception:
        logger.exception("Error enviando recordatorio de lectura manual")
    return redirect(url_for("admin_dashboard"))

@flask_app.post("/admin/send/meeting-info")
async def admin_send_meeting_info():
    auth = require_admin()
    if auth: return auth
    try:
        await send_meeting_reminder()
        flash("Información de reunión enviada al grupo", "success")
    except Exception:
        logger.exception("Error enviando info de reunión")
        flash("Error enviando la información", "danger")
    return redirect(url_for("admin_dashboard"))

@flask_app.post("/admin/send/pin-all")
async def admin_send_pin_all():
    """Envía y fija un mensaje combinado con todas las reuniones activas."""
    auth = require_admin()
    if auth: return auth
    try:
        all_meetings = db.get_meetings(limit=10)
        upcoming = [m for m in all_meetings if m.get("status") != "closed"]
        if not upcoming:
            flash("No hay reuniones activas para fijar", "danger")
            return redirect(url_for("admin_dashboard"))
        lines = ["📌 REUNIONES ACTIVAS\n"]
        keyboard = []
        for idx, meeting in enumerate(upcoming[:5], 1):
            asistentes = db.get_attendance(meeting["id"])
            fecha_str = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
            lines.append(f"📅 Reunión {idx}: {meeting['name']}")
            lines.append(f"   📆 Fecha: {fecha_str}")
            if meeting.get("location"):
                lines.append(f"   📍 Lugar: {meeting['location']}")
            lines.append(f"   👥 Apuntados: {len(asistentes)}")
            if idx < len(upcoming[:5]):
                lines.append("")
            short_name = meeting['name'][:20]
            keyboard.append([
                InlineKeyboardButton(f"✅ {short_name}", callback_data=f"attend:{meeting['id']}"),
                InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
            ])
        lines.append("\nUsa /asistir para apuntarte a una reunión concreta 📖")
        await send_and_pin(
            "\n".join(lines),
            parse_mode=None,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        flash("Mensaje de reuniones fijado en el grupo", "success")
    except Exception:
        logger.exception("Error en pin-all")
        flash("Error fijando mensaje", "danger")
    return redirect(url_for("admin_dashboard"))

# --------------------------------------------------
# FLASK — HISTÓRICO DE CICLOS
# --------------------------------------------------

@flask_app.get("/admin/historico")
def admin_historico():
    auth = require_admin()
    if auth: return auth
    books_history  = db.get_all_books_history()
    themes_history = db.get_all_themes_history()
    polls_history  = db.get_all_polls_history()
    meetings_history = db.get_all_meetings_history()
    return render_template(
        "admin_historico.html",
        books_history=books_history,
        themes_history=themes_history,
        polls_history=polls_history,
        meetings_history=meetings_history,
    )

# --------------------------------------------------
# FLASK — VISOR DE BASE DE DATOS
# --------------------------------------------------

@flask_app.get("/admin/db")
def admin_db():
    auth = require_admin()
    if auth: return auth
    tables = db.get_table_names()
    table  = request.args.get("table", "books")
    if table not in tables:
        table = tables[0]
    try:
        cols, rows = db.get_table_rows(table)
    except Exception:
        logger.exception("Error cargando tabla")
        cols, rows = [], []
    return render_template("admin_db.html", tables=tables, table=table, cols=cols, rows=rows)

@flask_app.post("/admin/db/<table>/delete/<int:row_id>")
def admin_db_delete_row(table, row_id):
    auth = require_admin()
    if auth: return auth
    try:
        db.delete_table_row(table, row_id)
    except Exception:
        logger.exception("Error borrando fila en tabla %s", table)
    return redirect(url_for("admin_db", table=table))

@flask_app.post("/admin/db/<table>/truncate")
def admin_db_truncate(table):
    auth = require_admin()
    if auth: return auth
    try:
        db.truncate_table(table)
    except Exception:
        logger.exception("Error vaciando tabla %s", table)
    return redirect(url_for("admin_db", table=table))

# --------------------------------------------------
# FLASK — BOOK EDIT (admin)
# --------------------------------------------------

@flask_app.post("/admin/book/<int:book_id>/edit")
def admin_book_edit(book_id):
    auth = require_admin()
    if auth: return auth
    title       = request.form.get("title", "").strip() or None
    author      = request.form.get("author", "").strip() or None
    description = request.form.get("description", "").strip() or None
    pages       = request.form.get("pages", "").strip() or None
    cover       = request.form.get("cover", "").strip() or None
    try:
        db.update_book(book_id, title=title, author=author, description=description, pages=pages, cover=cover)
        flash("Libro actualizado correctamente", "success")
    except Exception:
        logger.exception("Error editando libro")
        flash("Error actualizando el libro", "danger")
    return redirect(url_for("admin_dashboard"))

# --------------------------------------------------
# FLASK — SEND CUSTOM MESSAGE (admin)
# --------------------------------------------------

@flask_app.post("/admin/send/custom")
async def admin_send_custom():
    auth = require_admin()
    if auth: return auth
    text = request.form.get("message", "").strip()
    if not text:
        flash("El mensaje no puede estar vacío", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        ok = await send_to_group(text, parse_mode=None)
        if ok:
            flash("Mensaje enviado al grupo", "success")
        else:
            flash("Error enviando el mensaje (¿TELEGRAM_CHAT_ID configurado?)", "danger")
    except Exception:
        logger.exception("Error enviando mensaje custom")
        flash("Error enviando el mensaje", "danger")
    return redirect(url_for("admin_dashboard"))

# --------------------------------------------------
# FLASK — MESSAGE TEMPLATES (admin)
# --------------------------------------------------

@flask_app.get("/admin/messages")
def admin_messages():
    auth = require_admin()
    if auth: return auth
    templates_db = db.get_all_message_templates()
    # Merge defaults with DB overrides
    templates_db_dict = {t["key"]: t for t in templates_db}
    templates = []
    for key, default_value in DEFAULT_MESSAGES.items():
        if key in templates_db_dict:
            templates.append({
                "key": key,
                "value": templates_db_dict[key]["value"],
                "updated_at": templates_db_dict[key]["updated_at"],
                "is_custom": True,
                "default_value": default_value,
            })
        else:
            templates.append({
                "key": key,
                "value": default_value,
                "updated_at": None,
                "is_custom": False,
                "default_value": default_value,
            })
    return render_template("admin_messages.html", templates=templates)

@flask_app.post("/admin/messages/<key>/edit")
def admin_message_edit(key):
    auth = require_admin()
    if auth: return auth
    if key not in DEFAULT_MESSAGES:
        return "Clave no válida", 400
    value = request.form.get("value", "").strip()
    if value:
        db.set_message_template(key, value)
        flash("Mensaje actualizado", "success")
    return redirect(url_for("admin_messages"))

@flask_app.post("/admin/messages/<key>/reset")
def admin_message_reset(key):
    auth = require_admin()
    if auth: return auth
    db.delete_message_template(key)
    flash("Mensaje restablecido al valor por defecto", "success")
    return redirect(url_for("admin_messages"))

@flask_app.post("/admin/messages/preview")
def admin_message_preview():
    auth = require_admin()
    if auth: return auth
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
    auth = require_admin()
    if auth: return auth
    messages = db.get_sent_messages(limit=50)
    return render_template("admin_sent_messages.html", messages=messages)

# --------------------------------------------------
# FLASK — MESSAGE SCHEDULER
# --------------------------------------------------

@flask_app.get("/admin/scheduler")
def admin_scheduler():
    auth = require_admin()
    if auth: return auth
    scheduled = db.get_all_scheduled_messages()
    return render_template("admin_scheduler.html", scheduled=scheduled)

@flask_app.post("/admin/scheduler/add")
def admin_scheduler_add():
    auth = require_admin()
    if auth: return auth
    text = request.form.get("text", "").strip()
    send_at = request.form.get("send_at", "").strip()
    if not text or not send_at:
        flash("Texto y fecha son obligatorios", "danger")
        return redirect(url_for("admin_scheduler"))
    try:
        db.schedule_message(text, send_at)
        flash("Mensaje programado correctamente", "success")
    except Exception:
        logger.exception("Error programando mensaje")
        flash("Error programando el mensaje", "danger")
    return redirect(url_for("admin_scheduler"))

@flask_app.post("/admin/scheduler/<int:msg_id>/delete")
def admin_scheduler_delete(msg_id):
    auth = require_admin()
    if auth: return auth
    db.delete_scheduled_message(msg_id)
    flash("Mensaje eliminado", "success")
    return redirect(url_for("admin_scheduler"))

# --------------------------------------------------
# FLASK — AI FEATURES
# --------------------------------------------------

@flask_app.get("/admin/ai/questions")
def admin_ai_questions():
    auth = require_admin()
    if auth: return auth
    winner = db.get_winner_book()
    if not winner:
        flash("No hay libro del ciclo activo", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        questions = ai_features.generate_discussion_questions(
            winner["title"], winner.get("author", ""), winner.get("description", "")
        )
        content = f"💬 Preguntas de debate — {winner['title']}\n\n{questions}"
        return render_template(
            "admin_ai_preview.html",
            content=content,
            winner=winner,
            content_type="questions",
            send_url="/admin/ai/questions/send",
            regen_url="/admin/ai/questions",
            title="Preguntas de debate",
        )
    except Exception:
        logger.exception("Error generando preguntas AI")
        flash("Error generando preguntas", "danger")
        return redirect(url_for("admin_dashboard"))

@flask_app.post("/admin/ai/questions/send")
async def admin_ai_questions_send():
    auth = require_admin()
    if auth: return auth
    content = request.form.get("content", "").strip()
    if not content:
        flash("Contenido vacío", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        await send_to_group(content, parse_mode=None, message_type="ai_questions")
        flash("Preguntas de debate enviadas al grupo", "success")
    except Exception:
        logger.exception("Error enviando preguntas AI")
        flash("Error enviando preguntas", "danger")
    return redirect(url_for("admin_dashboard"))

@flask_app.get("/admin/ai/quote")
def admin_ai_quote():
    auth = require_admin()
    if auth: return auth
    winner = db.get_winner_book()
    if not winner:
        flash("No hay libro del ciclo activo", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        quote = ai_features.generate_book_quote(winner["title"], winner.get("author", ""))
        content = f"✨ {quote}\n\n— Sobre «{winner['title']}»"
        return render_template(
            "admin_ai_preview.html",
            content=content,
            winner=winner,
            content_type="quote",
            send_url="/admin/ai/quote/send",
            regen_url="/admin/ai/quote",
            title="Cita literaria",
        )
    except Exception:
        logger.exception("Error generando cita AI")
        flash("Error generando cita", "danger")
        return redirect(url_for("admin_dashboard"))

@flask_app.post("/admin/ai/quote/send")
async def admin_ai_quote_send():
    auth = require_admin()
    if auth: return auth
    content = request.form.get("content", "").strip()
    if not content:
        flash("Contenido vacío", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        await send_to_group(content, parse_mode=None, message_type="ai_quote")
        flash("Cita enviada al grupo", "success")
    except Exception:
        logger.exception("Error enviando cita AI")
        flash("Error enviando cita", "danger")
    return redirect(url_for("admin_dashboard"))

# --------------------------------------------------
# FLASK — AI ASSISTANT (contextual)
# --------------------------------------------------

@flask_app.post("/admin/ai/ask")
async def admin_ai_ask():
    auth = require_admin()
    if auth: return jsonify({"error": "No autorizado"}), 401

    question = request.json.get("question", "").strip() if request.is_json else request.form.get("question", "").strip()
    if not question:
        return jsonify({"error": "Pregunta vacía"}), 400

    # Build context
    cycle_key = db.get_current_cycle_key()
    winner = db.get_winner_book()
    proposals = db.get_book_proposals(cycle_key)
    meeting = db.get_latest_scheduled_meeting()
    attendees = db.get_attendance(meeting["id"]) if meeting else []
    themes = db.get_themes(cycle_key)

    context_lines = [
        "Eres el asistente del Club de Lectura. Responde siempre en español.",
        f"Fecha actual: {_utcnow().strftime('%d/%m/%Y')}",
        f"Ciclo actual: {cycle_key}",
    ]
    if winner:
        context_lines.append(f"Libro del ciclo: «{winner['title']}»" + (f" de {winner['author']}" if winner.get('author') else "") + f" ({winner.get('votes', 0)} votos)")
        if winner.get('description'):
            context_lines.append(f"Sinopsis: {winner['description'][:200]}")
    if proposals:
        tops = proposals[:5]
        prop_str = ", ".join(f"«{b['title']}» ({b['votes']} votos)" for b in tops)
        context_lines.append(f"Propuestas actuales (top 5): {prop_str}")
    if meeting:
        fecha = str(meeting['final_date'])[:16] if meeting.get('final_date') else 'Sin fecha'
        context_lines.append(f"Próxima reunión: {meeting['name']} — {fecha}")
        if meeting.get('location'):
            context_lines.append(f"Lugar: {meeting['location']}")
        if attendees:
            context_lines.append(f"Asistentes ({len(attendees)}): {', '.join(attendees[:10])}")

    full_prompt = "\n".join(context_lines) + f"\n\nPregunta del administrador: {question}"

    try:
        answer = ai_features._groq_chat(full_prompt)
        if not answer:
            return jsonify({"error": "No hay respuesta de la IA (¿está configurado GROQ_API_KEY?)"}), 503
        return jsonify({"answer": answer})
    except Exception as e:
        logger.exception("Error en AI ask")
        return jsonify({"error": str(e)}), 500

# --------------------------------------------------
# FLASK — POSTER DESIGNER
# --------------------------------------------------

@flask_app.get("/admin/poster")
def admin_poster():
    auth = require_admin()
    if auth: return auth
    winner = db.get_winner_book()
    meeting = db.get_latest_scheduled_meeting()
    return render_template("admin_poster.html", winner=winner, meeting=meeting)

# --------------------------------------------------
# FLASK — ADMIN HELP
# --------------------------------------------------

@flask_app.get("/admin/help")
def admin_help():
    auth = require_admin()
    if auth: return auth
    return render_template("admin_help.html")

# --------------------------------------------------
# FLASK — CYCLE MANAGEMENT (admin)
# --------------------------------------------------

@flask_app.get("/admin/ciclo")
def admin_ciclo():
    auth = require_admin()
    if auth: return auth
    current_cycle = db.get_current_cycle_key()
    all_cycles    = db.get_all_cycle_keys()
    books         = db.get_book_proposals()
    themes        = db.get_themes()
    winner        = db.get_winner_book()
    return render_template(
        "admin_ciclo.html",
        current_cycle=current_cycle,
        all_cycles=all_cycles,
        books=books, themes=themes, winner=winner,
    )

@flask_app.post("/admin/ciclo/nuevo")
def admin_ciclo_nuevo():
    auth = require_admin()
    if auth: return auth
    name = request.form.get("cycle_name", "").strip()
    if not name:
        flash("El nombre del ciclo no puede estar vacío", "danger")
        return redirect(url_for("admin_ciclo"))
    db.set_config("active_cycle_key", name)
    db.set_config("proposals_locked_for", "")  # unlock proposals for new cycle
    flash(f"Ciclo «{name}» activado correctamente", "success")
    return redirect(url_for("admin_ciclo"))

@flask_app.post("/admin/ciclo/cerrar")
def admin_ciclo_cerrar():
    auth = require_admin()
    if auth: return auth
    cycle = db.get_current_cycle_key()
    cycle_theme = db.get_config("active_theme") or None
    db.close_cycle(cycle)
    try:
        db.auto_add_runners_up_to_waitlist(cycle_key=cycle, cycle_theme=cycle_theme)
    except Exception:
        logger.exception("Error añadiendo runners-up a la lista de espera")
    flash(f"Ciclo «{cycle}» cerrado. Propuestas y temáticas desactivadas.", "success")
    return redirect(url_for("admin_ciclo"))

# --------------------------------------------------
# FLASK — CYCLE WIZARD
# --------------------------------------------------

@flask_app.post("/admin/wizard/new-cycle")
async def admin_wizard_new_cycle():
    """Inicia un nuevo ciclo y envía mensaje al grupo pidiendo propuestas."""
    auth = require_admin()
    if auth: return auth
    from datetime import timezone as _tz
    cycle_name = datetime.now(_tz.utc).strftime("%Y-%m")
    db.set_config("active_cycle_key", cycle_name)
    db.set_config("proposals_locked_for", "")
    try:
        text = (
            f"📚 ¡Nuevo ciclo de lectura — {cycle_name}!\n\n"
            f"Ha llegado el momento de elegir nuestro próximo libro. 🎉\n\n"
            f"Sugiere tus propuestas con el comando:\n"
            f"👉 /proponer título del libro\n\n"
            f"¡Anímate a proponer y a votar! 🗳️"
        )
        await send_to_group(text, parse_mode=None, message_type="new_cycle")
        flash(f"Ciclo {cycle_name} iniciado. Mensaje enviado al grupo.", "success")
    except Exception:
        logger.exception("Error en wizard new-cycle")
        flash(f"Ciclo {cycle_name} creado pero no se pudo enviar el mensaje al grupo.", "warning")
    return redirect(url_for("admin_dashboard"))


@flask_app.post("/admin/wizard/lock-and-poll")
async def admin_wizard_lock_and_poll():
    """Cierra las propuestas y lanza la encuesta de libros."""
    auth = require_admin()
    if auth: return auth
    cycle = db.get_current_cycle_key()
    books = db.get_book_proposals(cycle)
    if len(books) < 2:
        flash("Necesitas al menos 2 propuestas para lanzar la encuesta.", "danger")
        return redirect(url_for("admin_dashboard"))
    if not TELEGRAM_CHAT_ID:
        flash("TELEGRAM_CHAT_ID no configurado.", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        # Bloquear propuestas
        db.set_config("proposals_locked_for", cycle)
        # Crear encuesta de libros
        options = []
        for b in books[:10]:
            label = b["title"]
            if b.get("author"):
                label = f"{b['title']} — {b['author']}"
            options.append(label[:100])
        msg = await telegram_app.bot.send_poll(
            chat_id=TELEGRAM_CHAT_ID,
            question="📚 ¿Qué libro leemos este ciclo?",
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        db.save_poll(chat_id=msg.chat_id, message_id=msg.message_id,
                     poll_id=msg.poll.id, poll_type="books")
        flash("Propuestas cerradas y encuesta de libros lanzada en Telegram.", "success")
    except Exception:
        logger.exception("Error en wizard lock-and-poll")
        flash("Error lanzando la encuesta.", "danger")
    return redirect(url_for("admin_dashboard"))


@flask_app.post("/admin/wizard/announce-date")
async def admin_wizard_announce_date():
    """Envía un mensaje al grupo anunciando la fecha de la reunión."""
    auth = require_admin()
    if auth: return auth
    meeting = db.get_latest_scheduled_meeting()
    if not meeting or not meeting.get("final_date"):
        flash("No hay reunión con fecha confirmada.", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        fecha = str(meeting["final_date"])[:16]
        winner = db.get_winner_book()
        book_line = f"\n📗 Libro: {winner['title']}" if winner else ""
        location_line = f"\n📍 Lugar: {meeting['location']}" if meeting.get("location") else ""
        text = (
            f"📅 ¡Ya tenemos fecha para la reunión!\n\n"
            f"📌 {meeting['name']}\n"
            f"🗓️ {fecha}{location_line}{book_line}\n\n"
            f"¡Apúntate con /asistir! 🙋"
        )
        keyboard = [[
            InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{meeting['id']}"),
            InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
        ]]
        await send_to_group(text, parse_mode=None,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            message_type="date_announcement")
        flash("Fecha de reunión anunciada en el grupo.", "success")
    except Exception:
        logger.exception("Error en wizard announce-date")
        flash("Error enviando el anuncio.", "danger")
    return redirect(url_for("admin_dashboard"))

# --------------------------------------------------
# FLASK — ASSIGN BOOK TO MEETING (admin)
# --------------------------------------------------

@flask_app.post("/meeting/<int:meeting_id>/set-book")
def meeting_set_book(meeting_id):
    auth = require_admin()
    if auth: return auth
    book_id = request.form.get("book_id", "").strip()
    db.update_meeting(meeting_id=meeting_id, book_id=int(book_id) if book_id else None)
    flash("Libro asignado a la reunión", "success")
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))

# --------------------------------------------------
# FLASK — BOOK WAITLIST
# --------------------------------------------------

@flask_app.get("/admin/waitlist")
def admin_waitlist():
    auth = require_admin()
    if auth: return auth
    theme_filter = request.args.get('theme', '')
    waitlist = db.get_waitlist(theme=theme_filter if theme_filter else None)
    themes = db.get_waitlist_themes()
    winner = db.get_winner_book()
    books = db.get_book_proposals()
    return render_template('admin_waitlist.html', waitlist=waitlist, themes=themes,
                           theme_filter=theme_filter, winner=winner, books=books)

@flask_app.post("/admin/waitlist/add")
def admin_waitlist_add():
    auth = require_admin()
    if auth: return auth
    book_id = request.form.get('book_id', type=int)
    cycle_theme = request.form.get('cycle_theme', '').strip() or None
    notes = request.form.get('notes', '').strip() or None
    if not book_id:
        flash("Falta el ID del libro", "danger")
        return redirect(url_for('admin_waitlist'))
    cycle_key = db.get_current_cycle_key()
    db.add_to_waitlist(book_id=book_id, cycle_key=cycle_key, cycle_theme=cycle_theme,
                       added_by='admin', notes=notes)
    flash("Libro añadido a la lista de espera", "success")
    return redirect(url_for('admin_waitlist'))

@flask_app.post("/admin/waitlist/<int:wl_id>/delete")
def admin_waitlist_delete(wl_id):
    auth = require_admin()
    if auth: return auth
    db.remove_from_waitlist(wl_id)
    flash("Eliminado de la lista de espera", "success")
    return redirect(url_for('admin_waitlist'))

@flask_app.post("/admin/waitlist/suggest")
async def admin_waitlist_suggest():
    auth = require_admin()
    if auth: return auth
    theme = request.form.get('theme', '').strip()
    books = db.get_waitlist(theme=theme if theme else None)
    if not books:
        flash("No hay libros en la lista de espera para esa temática", "warning")
        return redirect(url_for('admin_waitlist'))
    lines = ["📚 *Lista de espera — libros pendientes*\n"]
    if theme:
        lines[0] = f"📚 *Lista de espera — temática: {theme}*\n"
    for i, b in enumerate(books[:10], 1):
        lines.append(f"{i}. {b['title']}" + (f" — {b['author']}" if b.get('author') else ""))
        if b.get('votes_at_time'):
            lines[-1] += f" ({b['votes_at_time']} votos en su ciclo)"
    lines.append("\n_¿Alguno de estos te apetece releer o proponer?_")
    await send_to_group("\n".join(lines), parse_mode=None)
    flash("Sugerencias enviadas al grupo", "success")
    return redirect(url_for('admin_waitlist'))

# --------------------------------------------------
# FLASK — DEMO / TOUR
# --------------------------------------------------

def _utcnow():
    from datetime import timezone as _tz
    return datetime.now(_tz.utc).replace(tzinfo=None)

@flask_app.get("/admin/demo")
def admin_demo():
    auth = require_admin()
    if auth: return auth
    demo_active = db.get_config("demo_mode") == "true"
    return render_template("admin_demo.html", demo_active=demo_active)

@flask_app.post("/admin/demo/seed")
def admin_demo_seed():
    auth = require_admin()
    if auth: return auth
    try:
        from datetime import timedelta
        demo_books = [
            {"title": "El nombre del viento", "author": "Patrick Rothfuss", "pages": 662,
             "description": "La historia de Kvothe, un mago legendario que narra su propia vida.", "language_code": "es"},
            {"title": "Sapiens", "author": "Yuval Noah Harari", "pages": 496,
             "description": "Una breve historia de la humanidad desde el homo sapiens hasta la actualidad.", "language_code": "es"},
            {"title": "La sombra del viento", "author": "Carlos Ruiz Zafón", "pages": 544,
             "description": "Un misterioso libro hace que un joven se aventure en el laberinto de los libros perdidos de Barcelona.", "language_code": "es"},
        ]
        cycle_key = db.get_current_cycle_key()
        for b in demo_books:
            try:
                db.insert_book(b, proposed_by="demo", cycle_key=cycle_key)
            except Exception:
                pass
        try:
            db.create_theme("Fantasía épica", created_by="demo", cycle_key=cycle_key)
        except Exception:
            pass
        demo_date = (_utcnow() + timedelta(days=14)).replace(hour=19, minute=0, second=0, microsecond=0)
        try:
            db.create_meeting(name="Reunión de demostración", final_date=str(demo_date), created_by="demo")
        except Exception:
            pass
        db.set_config("demo_mode", "true")
        flash("✅ Datos de demo sembrados correctamente", "success")
    except Exception:
        logger.exception("Error sembrando datos demo")
        flash("Error al sembrar datos", "danger")
    return redirect(url_for("admin_dashboard") + "?tour=1")

@flask_app.post("/admin/demo/clear")
def admin_demo_clear():
    auth = require_admin()
    if auth: return auth
    try:
        cycle_key = db.get_current_cycle_key()
        with db.get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM book_proposals WHERE cycle_key = %s AND proposed_by = 'demo'", (cycle_key,))
            cur.execute("DELETE FROM themes WHERE cycle_key = %s AND created_by = 'demo'", (cycle_key,))
            cur.execute("DELETE FROM meetings WHERE cycle_key = %s AND created_by = 'demo'", (cycle_key,))
        db.set_config("demo_mode", "false")
        flash("🧹 Datos de demo eliminados", "success")
    except Exception:
        logger.exception("Error limpiando datos demo")
        flash("Error al limpiar datos", "danger")
    return redirect(url_for("admin_dashboard"))

# --------------------------------------------------
# WEBHOOK
# --------------------------------------------------

@flask_app.post("/webhook")
async def webhook():
    try:
        data   = request.get_json(force=True)
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.update_queue.put(update)
        return Response(status=HTTPStatus.OK)
    except Exception:
        logger.exception("Error procesando webhook")
        return Response(status=HTTPStatus.INTERNAL_SERVER_ERROR)

# --------------------------------------------------
# STARTUP / SHUTDOWN
# --------------------------------------------------

async def startup():
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")

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
    scheduler.start()


async def shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await telegram_app.stop()
    await telegram_app.shutdown()


async def main():
    await startup()
    asgi_app = WsgiToAsgi(flask_app)
    server   = uvicorn.Server(
        uvicorn.Config(asgi_app, host="0.0.0.0", port=PORT, log_level="info")
    )
    try:
        await server.serve()
    finally:
        await shutdown()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
