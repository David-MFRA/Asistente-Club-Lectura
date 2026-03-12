import os
import re
import logging
from http import HTTPStatus

from flask import Flask, request, render_template, redirect, url_for, session, Response
from asgiref.wsgi import WsgiToAsgi
import uvicorn

from telegram import Update, Poll
from telegram.ext import Application, CommandHandler, ContextTypes

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import books_api
import trivia
import recommendations
import db

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

scheduler = AsyncIOScheduler(timezone="Europe/Madrid")

BOT_TOKEN        = os.getenv("BOT_TOKEN")
WEBHOOK_URL      = os.getenv("WEBHOOK_URL")
PORT             = int(os.environ.get("PORT", "10000"))
ADMIN_SECRET     = os.getenv("ADMIN_SECRET", "")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "cambia-esto-en-render")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")   # ID del grupo/canal para mensajes automáticos

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

def esc(text: str) -> str:
    """Escapa texto para Telegram MarkdownV2."""
    if not text:
        return ""
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\\-])', r'\\\1', str(text))


def bold(text: str) -> str:
    return f"*{esc(text)}*"


def italic(text: str) -> str:
    return f"_{esc(text)}_"


def code(text: str) -> str:
    return f"`{esc(text)}`"


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def is_admin_logged() -> bool:
    return session.get("admin_logged") is True


def require_admin():
    if not is_admin_logged():
        return redirect(url_for("admin_login"))
    return None


async def send_to_group(text: str, parse_mode: str = "MarkdownV2") -> bool:
    """Envía un mensaje al chat/grupo configurado en TELEGRAM_CHAT_ID."""
    if not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_CHAT_ID no configurado — mensaje no enviado al grupo")
        return False
    try:
        await telegram_app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=parse_mode
        )
        return True
    except Exception:
        logger.exception("Error enviando mensaje al grupo")
        return False


# --------------------------------------------------
# TELEGRAM COMMANDS
# --------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"📚 {bold('Club de Lectura')} — Comandos disponibles\n\n"
        f"📖 {bold('Libros')}\n"
        f"  /proponer _título_ — Propone un libro\n"
        f"  /propuestas — Lista de propuestas del ciclo\n"
        f"  /votar _id_ — Vota una propuesta\n"
        f"  /resultados — Ranking de votos\n\n"
        f"🏷️ {bold('Temáticas')}\n"
        f"  /tema _nombre_ — Propone una temática\n"
        f"  /temas — Lista de temáticas\n"
        f"  /votar\\_tema _id_ — Vota una temática\n\n"
        f"📅 {bold('Reunión')}\n"
        f"  /reunion — Info de la próxima reunión\n"
        f"  /asistir — Apuntarse a la reunión\n"
        f"  /noasistir — Quitarse de la reunión\n"
        f"  /asistencia — Ver asistentes\n\n"
        f"🗳️ {bold('Encuesta')}\n"
        f"  /encuesta — Lanza encuesta nativa de Telegram\n\n"
        f"🎲 {bold('Extras')}\n"
        f"  /trivia — Pregunta para el debate\n"
        f"  /recomendar — Libros del tema activo"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def proponer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = " ".join(context.args).strip()

    if not title:
        await update.message.reply_text(
            f"📖 Usa {code('/proponer título del libro')}",
            parse_mode="MarkdownV2"
        )
        return

    try:
        # Mensaje de espera mientras buscamos
        wait_msg = await update.message.reply_text(
            f"🔍 Buscando _{esc(title)}_\\.\\.\\.",
            parse_mode="MarkdownV2"
        )

        book = books_api.google_books(title)

        if not book:
            await wait_msg.delete()
            await update.message.reply_text(
                f"❌ No encontré ese libro en Google Books\\.\n"
                f"Prueba con un título diferente o más completo\\.",
                parse_mode="MarkdownV2"
            )
            return

        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        db.insert_book(book, user)
        await wait_msg.delete()

        # Construir mensaje rico con los datos del libro
        lines = [f"✅ {bold('¡Libro propuesto!')} por {italic(user)}\n"]
        lines.append(f"📗 {bold(book['title'])}")

        if book.get("author"):
            lines.append(f"✍️ {italic(book['author'])}")

        if book.get("pages"):
            lines.append(f"📄 {esc(str(book['pages']))} páginas")

        if book.get("description"):
            # Truncar descripción a 300 chars
            desc = book["description"]
            if len(desc) > 300:
                desc = desc[:297] + "…"
            lines.append(f"\n💬 _{esc(desc)}_")

        lines.append(f"\n_Usa /propuestas para ver todas las propuestas y /votar para votar\\._")

        caption = "\n".join(lines)

        if book.get("cover"):
            await update.message.reply_photo(
                photo=book["cover"],
                caption=caption,
                parse_mode="MarkdownV2"
            )
        else:
            await update.message.reply_text(caption, parse_mode="MarkdownV2")

    except Exception:
        logger.exception("Error en /proponer")
        await update.message.reply_text(
            "⚠️ Hubo un error añadiendo el libro\\. Inténtalo de nuevo\\.",
            parse_mode="MarkdownV2"
        )


async def propuestas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        books = db.get_book_proposals()
        if not books:
            await update.message.reply_text(
                "📭 No hay propuestas en este ciclo todavía\\.\n"
                "Usa /proponer para añadir la primera\\.",
                parse_mode="MarkdownV2"
            )
            return

        lines = [f"📚 {bold('Propuestas del ciclo')}\n"]
        for b in books:
            author_str = f" — _{esc(b['author'])}_" if b.get("author") else ""
            stars = "⭐" * min(b["votes"], 5) if b["votes"] > 0 else "·"
            lines.append(
                f"{bold(str(b['proposal_id']))}\\. {esc(b['title'])}{author_str}\n"
                f"   {stars} {bold(str(b['votes']))} voto{'s' if b['votes'] != 1 else ''}"
            )

        lines.append(f"\n_Vota con /votar \\<id\\>_")
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")

    except Exception:
        logger.exception("Error en /propuestas")
        await update.message.reply_text(
            "⚠️ Error obteniendo propuestas\\.", parse_mode="MarkdownV2"
        )


async def votar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            f"🗳️ Usa {code('/votar id_propuesta')}\\.\n"
            f"Consulta los IDs con /propuestas\\.",
            parse_mode="MarkdownV2"
        )
        return

    try:
        proposal_id = int(context.args[0])
        user = update.effective_user.first_name or update.effective_user.username or "alguien"

        ok = db.vote_book(proposal_id, user)

        if ok:
            proposal = db.get_proposal_by_id(proposal_id)
            book_name = proposal["title"] if proposal else f"propuesta #{proposal_id}"
            await update.message.reply_text(
                f"✅ {bold('Voto registrado')}\n\n"
                f"Has votado por _{esc(book_name)}_\\.\n"
                f"Usa /propuestas para ver el ranking actualizado\\.",
                parse_mode="MarkdownV2"
            )
        else:
            await update.message.reply_text(
                f"⚠️ Ya habías votado esa propuesta\\.\n"
                f"Solo se permite un voto por propuesta\\.",
                parse_mode="MarkdownV2"
            )

    except ValueError:
        await update.message.reply_text(
            "❌ El ID debe ser un número\\. Usa /propuestas para verlos\\.",
            parse_mode="MarkdownV2"
        )
    except Exception:
        logger.exception("Error en /votar")
        await update.message.reply_text(
            "⚠️ Error registrando el voto\\.", parse_mode="MarkdownV2"
        )


async def resultados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        books = db.get_cycle_results()
        if not books:
            await update.message.reply_text(
                "📭 No hay resultados todavía\\.\nUsa /proponer para añadir libros\\.",
                parse_mode="MarkdownV2"
            )
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = [f"🏆 {bold('Resultados del ciclo')}\n"]

        for i, b in enumerate(books):
            medal = medals[i] if i < 3 else f"{i+1}\\."
            author_str = f"\n   _{italic(b['author'])}_" if b.get("author") else ""
            lines.append(
                f"{medal} {bold(b['title'])}{author_str}\n"
                f"   {bold(str(b['votes']))} voto{'s' if b['votes'] != 1 else ''}"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")

    except Exception:
        logger.exception("Error en /resultados")
        await update.message.reply_text(
            "⚠️ Error obteniendo resultados\\.", parse_mode="MarkdownV2"
        )


async def reunion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text(
                "📭 No hay reunión programada\\.\n"
                "El administrador creará una pronto\\.",
                parse_mode="MarkdownV2"
            )
            return

        asistentes = db.get_attendance(meeting["id"])
        fecha = esc(str(meeting["final_date"])) if meeting.get("final_date") else "_Sin fecha cerrada_"
        estado_map = {"draft": "⏳ Borrador", "scheduled": "✅ Confirmada", "closed": "🔒 Cerrada"}
        estado = estado_map.get(meeting.get("status", ""), esc(meeting.get("status", "")))

        lines = [
            f"📅 {bold(meeting['name'])}\n",
            f"📆 *Fecha:* {fecha}",
            f"📊 *Estado:* {esc(estado)}",
            f"👥 *Asistentes:* {bold(str(len(asistentes)))}",
        ]

        if asistentes:
            names = "  ".join(f"• {esc(a)}" for a in asistentes)
            lines.append(f"\n{names}")

        lines.append(f"\n_Usa /asistir o /noasistir para gestionar tu asistencia\\._")

        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")

    except Exception:
        logger.exception("Error en /reunion")
        await update.message.reply_text(
            "⚠️ Error obteniendo la reunión\\.", parse_mode="MarkdownV2"
        )


async def asistir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text(
                "📭 No hay reunión activa\\.", parse_mode="MarkdownV2"
            )
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


async def noasistir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text(
                "📭 No hay reunión activa\\.", parse_mode="MarkdownV2"
            )
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


async def asistencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text(
                "📭 No hay reunión activa\\.", parse_mode="MarkdownV2"
            )
            return

        asistentes = db.get_attendance(meeting["id"])
        if asistentes:
            names = "\n".join(f"  ✅ {esc(a)}" for a in asistentes)
        else:
            names = "_Nadie apuntado todavía_"

        await update.message.reply_text(
            f"👥 {bold('Asistencia')} — {italic(meeting['name'])}\n\n{names}",
            parse_mode="MarkdownV2"
        )

    except Exception:
        logger.exception("Error en /asistencia")
        await update.message.reply_text("⚠️ Error obteniendo asistencia\\.", parse_mode="MarkdownV2")


async def tema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text(
            f"🏷️ Usa {code('/tema nombre de la temática')}",
            parse_mode="MarkdownV2"
        )
        return

    try:
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        row = db.create_theme(name, created_by=user)
        if row:
            await update.message.reply_text(
                f"🏷️ {bold('Temática propuesta')}\n\n"
                f"_{esc(name)}_\n\n"
                f"Propuesta por {italic(user)}\\.\n"
                f"_Usa /temas para ver todas y /votar\\_tema para votar\\._",
                parse_mode="MarkdownV2"
            )
        else:
            await update.message.reply_text(
                f"⚠️ La temática _{esc(name)}_ ya existe en este ciclo\\.",
                parse_mode="MarkdownV2"
            )

    except Exception:
        logger.exception("Error en /tema")
        await update.message.reply_text("⚠️ Error creando temática\\.", parse_mode="MarkdownV2")


async def temas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rows = db.get_themes()
        if not rows:
            await update.message.reply_text(
                "📭 No hay temáticas propuestas\\.\nUsa /tema para añadir la primera\\.",
                parse_mode="MarkdownV2"
            )
            return

        lines = [f"🧭 {bold('Temáticas del ciclo')}\n"]
        for t in rows:
            bar = "█" * min(t["votes"], 8) if t["votes"] > 0 else "░"
            lines.append(
                f"{bold(str(t['id']))}\\. {esc(t['name'])}\n"
                f"   {bar} {bold(str(t['votes']))} voto{'s' if t['votes'] != 1 else ''}"
            )

        lines.append(f"\n_Vota con /votar\\_tema \\<id\\>_")
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")

    except Exception:
        logger.exception("Error en /temas")
        await update.message.reply_text("⚠️ Error obteniendo temáticas\\.", parse_mode="MarkdownV2")


async def votar_tema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            f"🗳️ Usa {code('/votar_tema id')}\\. Consulta IDs con /temas\\.",
            parse_mode="MarkdownV2"
        )
        return

    try:
        theme_id = int(context.args[0])
        user = update.effective_user.first_name or update.effective_user.username or "alguien"
        ok = db.vote_theme(theme_id, user)

        if ok:
            await update.message.reply_text(
                f"✅ {bold('Voto de temática registrado')}\n\n"
                f"Gracias {italic(user)}\\! Usa /temas para ver el ranking\\.",
                parse_mode="MarkdownV2"
            )
        else:
            await update.message.reply_text(
                "⚠️ Ya habías votado esa temática\\.", parse_mode="MarkdownV2"
            )

    except ValueError:
        await update.message.reply_text(
            "❌ El ID debe ser un número\\. Usa /temas para verlos\\.", parse_mode="MarkdownV2"
        )
    except Exception:
        logger.exception("Error en /votar_tema")
        await update.message.reply_text("⚠️ Error registrando voto\\.", parse_mode="MarkdownV2")


async def trivia_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        question = trivia.generate()
        # trivia.generate() ya devuelve texto con emoji, lo escapamos
        await update.message.reply_text(
            esc(question),
            parse_mode="MarkdownV2"
        )
    except Exception:
        logger.exception("Error en /trivia")
        await update.message.reply_text("⚠️ Error generando trivia\\.", parse_mode="MarkdownV2")


async def recomendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Usar el tema activo con más votos
        top_theme = db.get_top_theme()
        theme_name = top_theme["name"] if top_theme else "novela"

        wait = await update.message.reply_text(
            f"🔍 Buscando libros de _{esc(theme_name)}_\\.\\.\\.",
            parse_mode="MarkdownV2"
        )

        rec = recommendations.recommend(theme_name)
        await wait.delete()

        if not rec:
            await update.message.reply_text(
                "📭 No encontré recomendaciones\\. Inténtalo de nuevo\\.",
                parse_mode="MarkdownV2"
            )
            return

        lines = [
            f"💡 {bold('Recomendaciones')} — temática {italic(theme_name)}\n"
        ]
        for i, r in enumerate(rec, 1):
            author_str = f"\n   _{esc(r['author'])}_" if r.get("author") else ""
            lines.append(f"{bold(str(i))}\\. {esc(r['title'])}{author_str}")

        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")

    except Exception:
        logger.exception("Error en /recomendar")
        await update.message.reply_text("⚠️ Error obteniendo recomendaciones\\.", parse_mode="MarkdownV2")


async def encuesta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Crea una encuesta nativa de Telegram con las propuestas del ciclo."""
    try:
        books = db.get_book_proposals()

        if not books:
            await update.message.reply_text(
                "📭 No hay propuestas para crear una encuesta\\.\n"
                "Usa /proponer para añadir libros primero\\.",
                parse_mode="MarkdownV2"
            )
            return

        # Telegram permite máximo 10 opciones en un poll
        options = []
        for b in books[:10]:
            label = b["title"]
            if b.get("author"):
                label = f"{b['title']} — {b['author']}"
            # Máximo 100 chars por opción en Telegram
            options.append(label[:100])

        if len(options) < 2:
            await update.message.reply_text(
                "⚠️ Necesitas al menos 2 propuestas para crear una encuesta\\.",
                parse_mode="MarkdownV2"
            )
            return

        poll_msg = await update.message.reply_poll(
            question="📚 ¿Qué libro leemos este mes?",
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )

        # Guardar en DB para poder cerrarla desde el admin
        db.save_poll(
            chat_id=poll_msg.chat_id,
            message_id=poll_msg.message_id,
            poll_id=poll_msg.poll.id,
        )

        await update.message.reply_text(
            f"🗳️ {bold('¡Encuesta lanzada!')}\n\n"
            f"El admin puede cerrarla desde el panel de administración\\.",
            parse_mode="MarkdownV2"
        )

    except Exception:
        logger.exception("Error en /encuesta")
        await update.message.reply_text(
            "⚠️ Error creando la encuesta\\.", parse_mode="MarkdownV2"
        )


# --------------------------------------------------
# REMINDERS — envían mensajes reales al grupo
# --------------------------------------------------

async def send_meeting_reminder():
    meeting = db.get_latest_scheduled_meeting()
    if not meeting or not meeting.get("final_date"):
        return

    asistentes = db.get_attendance(meeting["id"])
    names = "\n".join(f"  ✅ {esc(a)}" for a in asistentes) if asistentes else "_Nadie apuntado todavía_"

    text = (
        f"⏰ {bold('Recordatorio de reunión')}\n\n"
        f"📅 {bold(meeting['name'])}\n"
        f"📆 *Fecha:* {esc(str(meeting['final_date']))}\n"
        f"👥 *Apuntados:* {bold(str(len(asistentes)))}\n\n"
        f"{names}\n\n"
        f"_Usa /asistir si aún no te has apuntado\\._"
    )

    await send_to_group(text)


async def send_reading_reminder():
    winner = db.get_winner_book()
    meeting = db.get_latest_scheduled_meeting()

    if not winner:
        return

    fecha = esc(str(meeting["final_date"])) if meeting and meeting.get("final_date") else "_Sin fecha cerrada_"
    reunion_name = italic(meeting["name"]) if meeting else "_Sin reunión_"

    author_str = f"\n✍️ _{esc(winner['author'])}_" if winner.get("author") else ""

    text = (
        f"📖 {bold('Recordatorio de lectura')}\n\n"
        f"El libro del ciclo es:\n"
        f"📗 {bold(winner['title'])}{author_str}\n\n"
        f"📅 Reunión: {reunion_name}\n"
        f"📆 Fecha: {fecha}\n\n"
        f"_¡A leer se ha dicho\\! 🚀_"
    )

    await send_to_group(text)


async def send_weekly_trivia():
    """Envía una pregunta de trivia al grupo cada semana."""
    question = trivia.generate()
    text = (
        f"🎲 {bold('Pregunta semanal del club')}\n\n"
        f"{esc(question)}"
    )
    await send_to_group(text)


# --------------------------------------------------
# REGISTER TELEGRAM HANDLERS
# --------------------------------------------------

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("proponer", proponer))
telegram_app.add_handler(CommandHandler("propuestas", propuestas))
telegram_app.add_handler(CommandHandler("votar", votar))
telegram_app.add_handler(CommandHandler("resultados", resultados))
telegram_app.add_handler(CommandHandler("reunion", reunion))
telegram_app.add_handler(CommandHandler("asistir", asistir))
telegram_app.add_handler(CommandHandler("noasistir", noasistir))
telegram_app.add_handler(CommandHandler("asistencia", asistencia))
telegram_app.add_handler(CommandHandler("tema", tema))
telegram_app.add_handler(CommandHandler("temas", temas))
telegram_app.add_handler(CommandHandler("votar_tema", votar_tema))
telegram_app.add_handler(CommandHandler("trivia", trivia_cmd))
telegram_app.add_handler(CommandHandler("recomendar", recomendar))
telegram_app.add_handler(CommandHandler("encuesta", encuesta))

# --------------------------------------------------
# FLASK ROUTES
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


@flask_app.get("/admin")
def admin_dashboard():
    auth = require_admin()
    if auth:
        return auth

    books     = db.get_books()
    meetings  = db.get_meetings(limit=5)
    themes    = db.get_themes()
    ranking   = db.get_book_ranking()
    open_poll = db.get_open_poll()

    return render_template(
        "admin.html",
        books=books,
        meetings=meetings,
        themes=themes,
        ranking=ranking,
        open_poll=open_poll,
    )


@flask_app.get("/meetings")
def meetings_admin():
    auth = require_admin()
    if auth:
        return auth

    meetings = db.get_meetings()
    return render_template("meetings.html", meetings=meetings)


@flask_app.get("/themes")
def themes_admin():
    auth = require_admin()
    if auth:
        return auth

    themes = db.get_themes()
    return render_template("themes.html", themes=themes)


@flask_app.get("/ranking")
def ranking_admin():
    auth = require_admin()
    if auth:
        return auth

    ranking = db.get_book_ranking()
    return render_template("ranking.html", ranking=ranking)


@flask_app.get("/meeting/<int:meeting_id>")
def meeting_detail_admin(meeting_id):
    auth = require_admin()
    if auth:
        return auth

    meeting = db.get_meeting(meeting_id)
    if not meeting:
        return "Reunión no encontrada", 404

    attendees    = db.get_attendance(meeting_id)
    date_options = db.get_meeting_date_options(meeting_id)

    return render_template(
        "meeting_detail.html",
        meeting=meeting,
        attendees=attendees,
        date_options=date_options
    )


@flask_app.post("/meeting/<int:meeting_id>/edit")
def meeting_edit_admin(meeting_id):
    auth = require_admin()
    if auth:
        return auth

    name       = request.form.get("name", "").strip()
    final_date = request.form.get("final_date", "").strip() or None
    summary    = request.form.get("summary", "").strip() or None
    status     = request.form.get("status", "").strip() or None

    db.update_meeting(
        meeting_id=meeting_id,
        name=name if name else None,
        final_date=final_date,
        summary=summary,
        status=status
    )

    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))


@flask_app.post("/meeting/<int:meeting_id>/delete")
def meeting_delete_admin(meeting_id):
    auth = require_admin()
    if auth:
        return auth

    db.delete_meeting(meeting_id)
    return redirect(url_for("meetings_admin"))


@flask_app.post("/meeting/<int:meeting_id>/date-option")
def meeting_add_date_option_admin(meeting_id):
    auth = require_admin()
    if auth:
        return auth

    option_date = request.form.get("option_date", "").strip()
    if not option_date:
        return "Fecha obligatoria", 400

    db.add_meeting_date_option(meeting_id, option_date)
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))


@flask_app.post("/meeting/<int:meeting_id>/close-date")
def meeting_close_date_admin(meeting_id):
    auth = require_admin()
    if auth:
        return auth

    final_date = request.form.get("final_date", "").strip()
    if not final_date:
        return "Fecha obligatoria", 400

    db.set_meeting_final_date(meeting_id, final_date)
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))


@flask_app.get("/export")
def export():
    auth = require_admin()
    if auth:
        return auth

    rows = db.get_books()

    text = "id,title,author,votes\n"
    for r in rows:
        text += f'{r["id"]},"{r["title"]}","{r["author"]}",{r["votes"]}\n'

    return Response(
        text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=club_lectura_books.csv"}
    )


@flask_app.post("/admin/cerrar_encuesta/<int:poll_db_id>")
async def cerrar_encuesta(poll_db_id):
    """Cierra una encuesta de Telegram desde el panel de admin."""
    auth = require_admin()
    if auth:
        return auth

    try:
        poll = db.get_poll_by_id(poll_db_id)
        if not poll:
            return "Encuesta no encontrada", 404

        await telegram_app.bot.stop_poll(
            chat_id=poll["chat_id"],
            message_id=poll["message_id"]
        )

        db.close_poll(poll_db_id)

        return redirect(url_for("admin_dashboard"))

    except Exception:
        logger.exception("Error cerrando encuesta")
        return "Error cerrando encuesta", 500


@flask_app.get("/close_voting")
def close_voting():
    auth = require_admin()
    if auth:
        return auth

    winner = db.get_winner_book()

    if not winner:
        return "No hay libros propuestos", 404

    return (
        f"Libro ganador actual: {winner['title']} "
        f"({winner['votes']} votos)"
    )


@flask_app.post("/create_meeting")
def create_meeting():
    auth = require_admin()
    if auth:
        return auth

    name         = request.form.get("meeting_name", "").strip()
    meeting_date = request.form.get("meeting_date", "").strip()

    if not name or not meeting_date:
        return "Faltan datos", 400

    try:
        db.create_meeting(name=name, final_date=meeting_date, created_by="admin")
        return redirect(url_for("admin_dashboard"))

    except Exception:
        logger.exception("Error creando reunión")
        return "Error creando reunión", 500


@flask_app.get("/attendance")
def attendance():
    auth = require_admin()
    if auth:
        return auth

    latest_meeting = db.get_latest_meeting()

    if not latest_meeting:
        return "No hay reuniones creadas", 404

    attendees = db.get_attendance(latest_meeting["id"])

    if not attendees:
        return f"No hay asistentes todavía para {latest_meeting['name']}"

    participants = "<br>".join(attendees)

    return (
        f"<h2>{latest_meeting['name']}</h2>"
        f"<p>Fecha: {latest_meeting.get('final_date') or 'Sin cerrar'}</p>"
        f"<p>Participantes:</p>"
        f"<div>{participants}</div>"
    )


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
# STARTUP
# --------------------------------------------------

async def startup():
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")

    # Recordatorio de reunión cada 12 horas
    scheduler.add_job(
        send_meeting_reminder,
        "interval",
        hours=12,
        id="meeting_reminder",
        replace_existing=True
    )

    # Recordatorio de lectura cada 2 días
    scheduler.add_job(
        send_reading_reminder,
        "interval",
        days=2,
        id="reading_reminder",
        replace_existing=True
    )

    # Trivia semanal — lunes a las 10:00
    scheduler.add_job(
        send_weekly_trivia,
        "cron",
        day_of_week="mon",
        hour=10,
        minute=0,
        id="weekly_trivia",
        replace_existing=True
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
