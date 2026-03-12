import os
import re
import logging
from datetime import datetime
from http import HTTPStatus

from flask import Flask, request, render_template, redirect, url_for, session, Response, flash, get_flashed_messages
from asgiref.wsgi import WsgiToAsgi
import uvicorn

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ChatMemberHandler, CallbackQueryHandler, ContextTypes

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import books_api
import trivia
import recommendations
import db

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

async def send_to_group(text, parse_mode="MarkdownV2"):
    if not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_CHAT_ID no configurado")
        return False
    try:
        await telegram_app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=parse_mode
        )
        return True
    except Exception:
        logger.exception("Error enviando al grupo")
        return False

# --------------------------------------------------
# WINNER ANNOUNCEMENT
# --------------------------------------------------

async def announce_winner(book):
    """Envía ficha completa del libro ganador al grupo."""
    if not TELEGRAM_CHAT_ID:
        return
    lines = [f"🏆 {bold('¡Tenemos libro del mes!')}\\!\n"]
    lines.append(f"📗 {bold(book['title'])}")
    if book.get("author"):
        lines.append(f"✍️ {italic(book['author'])}")
    if book.get("pages"):
        lines.append(f"📄 {esc(str(book['pages']))} páginas")
    if book.get("language_code"):
        lines.append(f"🌐 Idioma original: {esc(str(book['language_code']).upper())}")
    lines.append(f"\n🗳️ Ganó con {bold(str(book.get('votes', 0)))} voto{'s' if book.get('votes', 0) != 1 else ''}")
    if book.get("description"):
        desc = book["description"]
        if len(desc) > 500:
            desc = desc[:497] + "…"
        lines.append(f"\n📖 {bold('Sinopsis')}\n_{esc(desc)}_")
    lines.append(f"\n_¡A leer se ha dicho\\! 🚀 Usa /asistir para apuntarte a la reunión\\._")
    text = "\n".join(lines)

    try:
        if book.get("cover"):
            await telegram_app.bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID,
                photo=book["cover"],
                caption=text,
                parse_mode="MarkdownV2"
            )
            return
    except Exception:
        pass
    await send_to_group(text)

# --------------------------------------------------
# TELEGRAM COMMANDS
# --------------------------------------------------

async def start(update, context):
    if not _allowed_chat(update): return
    text = (
        f"📚 {bold('Club de Lectura')} — Comandos disponibles\n\n"
        f"📖 {bold('Libros')}\n"
        f"  /proponer _título_ — Propone un libro\n"
        f"  /propuestas — Lista con botones para votar\n"
        f"  /votar _id_ — Vota una propuesta\n"
        f"  /resultados — Ranking de votos\n"
        f"  /libro — Libro del ciclo actual\n\n"
        f"🏷️ {bold('Temáticas')}\n"
        f"  /tema _nombre_ — Propone una temática\n"
        f"  /temas — Lista con botones para votar\n"
        f"  /votar\\_tema _id_ — Vota una temática\n\n"
        f"📅 {bold('Reunión')}\n"
        f"  /reunion — Info de la próxima reunión\n"
        f"  /asistir — Apuntarse a la reunión\n"
        f"  /noasistir — Quitarse de la reunión\n"
        f"  /asistencia — Ver asistentes\n"
        f"  /acta — Resumen de la última reunión\n\n"
        f"📊 {bold('Tu actividad')}\n"
        f"  /calificar _N_ _\\[reseña\\]_ — Valora el libro \\(1\\-5\\)\n"
        f"  /progreso _páginas_ — Registra tu lectura\n"
        f"  /estadisticas — Tus estadísticas del club\n\n"
        f"🎲 {bold('Extras')}\n"
        f"  /trivia — Pregunta para el debate\n"
        f"  /recomendar — Libros del tema activo"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def proponer(update, context):
    if not _allowed_chat(update): return
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


async def reunion(update, context):
    if not _allowed_chat(update): return
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text("📭 No hay reunión programada todavía\\.", parse_mode="MarkdownV2")
            return
        asistentes = db.get_attendance(meeting["id"])
        fecha = esc(str(meeting["final_date"])) if meeting.get("final_date") else "_Sin fecha cerrada_"
        estado_map = {"draft": "⏳ Borrador", "scheduled": "✅ Confirmada", "closed": "🔒 Cerrada"}
        estado = esc(estado_map.get(meeting.get("status", ""), meeting.get("status", "")))
        lines = [
            f"📅 {bold(meeting['name'])}\n",
            f"📆 *Fecha:* {fecha}",
            f"📊 *Estado:* {estado}",
            f"👥 *Asistentes:* {bold(str(len(asistentes)))}",
        ]
        if asistentes:
            lines.append("\n" + "  ".join(f"• {esc(a)}" for a in asistentes))
        lines.append(f"\n_Usa /asistir o /noasistir para gestionar tu asistencia\\._")
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /reunion")
        await update.message.reply_text("⚠️ Error obteniendo la reunión\\.", parse_mode="MarkdownV2")


async def asistir(update, context):
    if not _allowed_chat(update): return
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text("📭 No hay reunión activa\\.", parse_mode="MarkdownV2")
            return
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        db.add_attendance(meeting["id"], user)
        asistentes = db.get_attendance(meeting["id"])
        names = "\n".join(f"  ✅ {esc(a)}" for a in asistentes)
        await update.message.reply_text(
            f"🎉 {bold(esc(user))} se apuntó a {italic(meeting['name'])}\n\n"
            f"👥 {bold('Asistentes')} \\({bold(str(len(asistentes)))}\\):\n{names}",
            parse_mode="MarkdownV2"
        )
    except Exception:
        logger.exception("Error en /asistir")
        await update.message.reply_text("⚠️ Error al apuntarte\\.", parse_mode="MarkdownV2")


async def noasistir(update, context):
    if not _allowed_chat(update): return
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text("📭 No hay reunión activa\\.", parse_mode="MarkdownV2")
            return
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        db.remove_attendance(meeting["id"], user)
        asistentes = db.get_attendance(meeting["id"])
        names = ("\n".join(f"  • {esc(a)}" for a in asistentes)) if asistentes else "_Nadie de momento_"
        await update.message.reply_text(
            f"👋 {bold(esc(user))} se ha quitado de {italic(meeting['name'])}\n\n"
            f"👥 {bold('Quedan')} \\({bold(str(len(asistentes)))}\\):\n{names}",
            parse_mode="MarkdownV2"
        )
    except Exception:
        logger.exception("Error en /noasistir")
        await update.message.reply_text("⚠️ Error al quitarte\\.", parse_mode="MarkdownV2")


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
            await update.message.reply_text(
                f"🏷️ {bold('Temática propuesta')}: _{esc(name)}_\n"
                f"Propuesta por {italic(user)}\\.\n"
                f"_Usa /temas y /votar\\_tema para votar\\._",
                parse_mode="MarkdownV2"
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
    try:
        question = trivia.generate()
        await update.message.reply_text(esc(question), parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /trivia")
        await update.message.reply_text("⚠️ Error generando trivia\\.", parse_mode="MarkdownV2")


async def recomendar(update, context):
    if not _allowed_chat(update): return
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
    except Exception:
        logger.exception("Error en button_handler")
        await query.answer("⚠️ Error procesando el voto", show_alert=True)


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


async def calificar_cmd(update, context):
    if not _allowed_chat(update): return
    if not context.args:
        await update.message.reply_text(
            f"⭐ Usa {code('/calificar puntuación [reseña]')}\n"
            f"_Ej: /calificar 4 Muy buen libro_\n"
            f"_Puntuación del 1 al 5_",
            parse_mode="MarkdownV2"
        )
        return
    try:
        score = int(context.args[0])
        if not 1 <= score <= 5:
            await update.message.reply_text("❌ La puntuación debe ser entre 1 y 5\\.", parse_mode="MarkdownV2")
            return
        review = " ".join(context.args[1:]).strip() or None
        winner = db.get_winner_book()
        if not winner:
            await update.message.reply_text("📭 No hay libro del ciclo para valorar\\.", parse_mode="MarkdownV2")
            return
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        db.rate_book(winner["id"], user, score, review)
        stars = "⭐" * score
        lines = [f"{stars} {bold('Valoración registrada')}\\!"]
        lines.append(f"📗 {esc(winner['title'])}")
        lines.append(f"Puntuación: {bold(str(score))}/5")
        if review:
            lines.append(f"💬 _{esc(review)}_")
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")
    except ValueError:
        await update.message.reply_text("❌ El primer argumento debe ser un número del 1 al 5\\.", parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /calificar")
        await update.message.reply_text("⚠️ Error registrando valoración\\.", parse_mode="MarkdownV2")


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
        lines = [f"📊 {bold('Tus estadísticas')} — {italic(user)}\n"]
        lines.append(f"📚 Propuestas: {bold(str(s['proposals_total']))} en total, {bold(str(s['proposals_cycle']))} este ciclo")
        lines.append(f"🗳️ Votos emitidos: {bold(str(s['book_votes']))} libros, {bold(str(s['theme_votes']))} temáticas")
        lines.append(f"📅 Reuniones asistidas: {bold(str(s['meetings']))}")
        if s['ratings'] > 0:
            avg_str = str(s['avg_score']) if s['avg_score'] else '?'
            lines.append(f"⭐ Libros valorados: {bold(str(s['ratings']))} \\(media: {bold(avg_str)}/5\\)")
        else:
            lines.append(f"⭐ Aún no has valorado ningún libro")
        if s.get("last_progress"):
            p = s["last_progress"]
            total_str = f" de {bold(str(p['total']))}" if p.get("total") else ""
            lines.append(f"📖 Último progreso: {bold(str(p['pages_read']))} págs{total_str} \\— _{esc(p['title'])}_")
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")
    except Exception:
        logger.exception("Error en /estadisticas")
        await update.message.reply_text("⚠️ Error obteniendo estadísticas\\.", parse_mode="MarkdownV2")


# --------------------------------------------------
# ADMIN BOT COMMANDS (solo ADMIN_TELEGRAM_ID)
# --------------------------------------------------

async def admin_ayuda_cmd(update, context):
    if not is_admin_user(update): return
    text = (
        f"🔐 {bold('Comandos de administrador')}\n\n"
        f"🔄 {bold('Ciclos')}\n"
        f"  /ciclo — Ver ciclo activo\n"
        f"  /nuevo\\_ciclo \\[nombre\\] — Crear nuevo ciclo\n"
        f"  /cerrar\\_ciclo — Cerrar ciclo actual\n\n"
        f"📣 {bold('Mensajes')}\n"
        f"  /anuncio \\<texto\\> — Enviar mensaje al grupo\n"
        f"  /anunciar\\_ganador — Anunciar libro ganador\n\n"
        f"🔔 {bold('Recordatorios')}\n"
        f"  /enviar\\_recordatorio — Recordatorio de reunión\n"
        f"  /enviar\\_lectura — Recordatorio de lectura"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


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


# --------------------------------------------------
# SCHEDULED REMINDERS
# --------------------------------------------------

async def send_meeting_reminder():
    """Recordatorio semanal con días restantes y ritmo de páginas."""
    meeting = db.get_latest_scheduled_meeting()
    if not meeting:
        return
    asistentes = db.get_attendance(meeting["id"])
    winner = db.get_winner_book()
    now = datetime.utcnow()

    days_left = None
    if meeting.get("final_date"):
        try:
            final_dt = meeting["final_date"]
            if isinstance(final_dt, str):
                final_dt = datetime.fromisoformat(final_dt)
            days_left = (final_dt - now).days
        except Exception:
            pass

    fecha_str = esc(str(meeting["final_date"])) if meeting.get("final_date") else "_Sin fecha_"
    names = "\n".join(f"  • {esc(a)}" for a in asistentes) if asistentes else "_Nadie apuntado todavía_"

    lines = [f"📅 {bold('Recordatorio semanal del club')}\n"]
    lines.append(f"Reunión: {bold(meeting['name'])}")
    lines.append(f"📆 Fecha: {fecha_str}")

    if days_left is not None:
        if days_left > 0:
            lines.append(f"⏳ Faltan {bold(str(days_left))} día{'s' if days_left != 1 else ''} para la reunión")
        elif days_left == 0:
            lines.append(f"🔔 {bold('¡La reunión es HOY!')}")
        else:
            lines.append(f"🔒 La reunión ya pasó hace {bold(str(abs(days_left)))} días")

    if winner and winner.get("title"):
        lines.append(f"\n📗 Libro: {bold(winner['title'])}")
        if winner.get("author"):
            lines.append(f"   ✍️ {italic(winner['author'])}")

        pages = winner.get("pages")
        if pages and days_left and days_left > 0:
            total_days = 30
            elapsed    = max(0, total_days - days_left)
            pages_now  = int(pages * elapsed / total_days)
            daily_pace = max(1, int(pages / total_days))
            lines.append(
                f"\n📊 {bold('Ritmo de lectura')}\n"
                f"  Para estar al día deberías llevar unas "
                f"{bold(str(pages_now))} páginas de {bold(str(pages))} en total ✨\n"
                f"  _{esc(f'Son unos {daily_pace} páginas al día, ¡tú puedes!')}_"
            )
        # Progreso del grupo
        progress_list = db.get_reading_progress(winner["id"])
        if progress_list and pages:
            lines.append(f"\n📖 {bold('Progreso del grupo')}")
            for p in progress_list[:5]:
                pct = int(p["pages_read"] / pages * 100) if pages > 0 else 0
                bar = "█" * int(pct/10) + "░" * (10 - int(pct/10))
                lines.append(f"  • {esc(p['user_name'])}: {bold(str(p['pages_read']))} págs \\({pct}%\\)")

    lines.append(f"\n👥 Apuntados \\({bold(str(len(asistentes)))}\\):\n{names}")
    lines.append(f"\n_¿Aún no te has apuntado? Usa /asistir 📖_")

    await send_to_group("\n".join(lines))


async def send_reading_reminder():
    """Recordatorio de lectura cada 2 días."""
    winner  = db.get_winner_book()
    meeting = db.get_latest_scheduled_meeting()
    if not winner:
        return
    fecha  = esc(str(meeting["final_date"])) if meeting and meeting.get("final_date") else "_Sin fecha_"
    reunion_name = italic(meeting["name"]) if meeting else "_Sin reunión_"
    author = f"\n✍️ _{esc(winner['author'])}_" if winner.get("author") else ""
    text = (
        f"📖 {bold('Recordatorio de lectura')}\n\n"
        f"El libro del ciclo es:\n"
        f"📗 {bold(winner['title'])}{author}\n\n"
        f"📅 Reunión: {reunion_name}\n"
        f"📆 Fecha: {fecha}\n\n"
        f"_¡A leer se ha dicho\\! 🚀_"
    )
    await send_to_group(text)


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
        header = f"🔔 {bold('¡La reunión es MAÑANA!')}"
    else:
        header = f"🚨 {bold('¡La reunión es HOY!')}"
    lines = [
        header + "\n",
        f"📅 {bold(meeting['name'])}",
        f"🗓️ {esc(str(final_dt)[:16])}",
    ]
    if winner:
        lines.append(f"📗 Libro: {bold(winner['title'])}")
    names = "\n".join(f"  ✅ {esc(a)}" for a in asistentes) if asistentes else "_Nadie apuntado_"
    lines.append(f"\n👥 Apuntados \\({bold(str(len(asistentes)))}\\):\n{names}")
    lines.append(f"\n_¿Aún no te has apuntado? Usa /asistir 📚_")
    await send_to_group("\n".join(lines))


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
telegram_app.add_handler(CommandHandler("calificar",        calificar_cmd))
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
    return render_template(
        "admin.html",
        books=books, meetings=meetings, themes=themes, ranking=ranking,
        open_poll_books=open_poll_books, open_poll_themes=open_poll_themes,
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

@flask_app.get("/meetings")
def meetings_admin():
    auth = require_admin()
    if auth: return auth
    meetings = db.get_meetings()
    return render_template("meetings.html", meetings=meetings)

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
    db.update_meeting(meeting_id=meeting_id, name=name or None, final_date=final_date, summary=summary, status=status)
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
    if not name:
        return "Falta el nombre", 400
    try:
        db.create_meeting(name=name, final_date=meeting_date, created_by="admin")
        return redirect(url_for("admin_dashboard"))
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
    flash(f"Ciclo «{name}» activado correctamente", "success")
    return redirect(url_for("admin_ciclo"))

@flask_app.post("/admin/ciclo/cerrar")
def admin_ciclo_cerrar():
    auth = require_admin()
    if auth: return auth
    cycle = db.get_current_cycle_key()
    db.close_cycle(cycle)
    flash(f"Ciclo «{cycle}» cerrado. Propuestas y temáticas desactivadas.", "success")
    return redirect(url_for("admin_ciclo"))

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
