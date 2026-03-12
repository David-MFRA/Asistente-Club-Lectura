import os
import logging
from http import HTTPStatus

from flask import Flask, request, render_template, redirect, url_for, session, Response
from asgiref.wsgi import WsgiToAsgi
import uvicorn

from telegram import Update
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

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", "10000"))

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "cambia-esto-en-render")

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
# HELPERS
# --------------------------------------------------

def is_admin_logged() -> bool:
    return session.get("admin_logged") is True


def require_admin():
    if not is_admin_logged():
        return redirect(url_for("admin_login"))
    return None


# --------------------------------------------------
# TELEGRAM COMMANDS
# --------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "BOT CLUB LECTURA\n\n"
        "/proponer <libro>\n"
        "/propuestas\n"
        "/votar <id>\n"
        "/resultados\n"
        "/tema <nombre>\n"
        "/temas\n"
        "/votar_tema <id>\n"
        "/reunion\n"
        "/asistir\n"
        "/noasistir\n"
        "/asistencia\n"
        "/trivia\n"
        "/recomendar"
    )


async def proponer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = " ".join(context.args).strip()

    if not title:
        await update.message.reply_text("Usa /proponer titulo")
        return

    try:
        book = books_api.google_books(title)

        if not book:
            await update.message.reply_text("Libro no encontrado")
            return

        user = update.effective_user.first_name or update.effective_user.username or "telegram"
        db.insert_book(book, user)

        await update.message.reply_text(f"Libro añadido: {book['title']}")

    except Exception:
        logger.exception("Error en /proponer")
        await update.message.reply_text("Error añadiendo el libro")


async def propuestas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        books = db.get_book_proposals()
        if not books:
            await update.message.reply_text("No hay propuestas activas.")
            return

        text = "📚 Propuestas actuales\n\n"
        for b in books:
            text += f"{b['proposal_id']}. {b['title']} — {b['votes']} votos\n"

        await update.message.reply_text(text)

    except Exception:
        logger.exception("Error en /propuestas")
        await update.message.reply_text("Error obteniendo propuestas")


async def votar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usa /votar <id_propuesta>")
        return

    try:
        proposal_id = int(context.args[0])
        user = update.effective_user.first_name or update.effective_user.username or "telegram"

        ok = db.vote_book(proposal_id, user)

        if ok:
            await update.message.reply_text("Voto registrado")
        else:
            await update.message.reply_text("Ya habías votado esa propuesta")

    except Exception:
        logger.exception("Error en /votar")
        await update.message.reply_text("Error registrando voto")


async def resultados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        books = db.get_cycle_results()
        if not books:
            await update.message.reply_text("No hay resultados.")
            return

        text = "🏆 Resultados del ciclo\n\n"
        for b in books:
            text += f"{b['title']} — {b['votes']} votos\n"

        await update.message.reply_text(text)

    except Exception:
        logger.exception("Error en /resultados")
        await update.message.reply_text("Error obteniendo resultados")


async def reunion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text("No hay reunión creada.")
            return

        asistentes = db.get_attendance(meeting["id"])
        text = (
            f"📅 {meeting['name']}\n"
            f"Fecha: {meeting.get('final_date') or 'Sin cerrar'}\n"
            f"Asistentes: {len(asistentes)}\n"
        )
        if asistentes:
            text += "\n" + "\n".join(f"- {a}" for a in asistentes)

        await update.message.reply_text(text)

    except Exception:
        logger.exception("Error en /reunion")
        await update.message.reply_text("Error obteniendo reunión")


async def asistir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text("No hay reunión activa.")
            return

        user = update.effective_user.first_name or update.effective_user.username or "telegram"
        db.add_attendance(meeting["id"], user)

        asistentes = db.get_attendance(meeting["id"])
        text = (
            f"Te has apuntado a {meeting['name']}.\n"
            f"Participantes ({len(asistentes)}):\n" +
            "\n".join(f"- {a}" for a in asistentes)
        )
        await update.message.reply_text(text)

    except Exception:
        logger.exception("Error en /asistir")
        await update.message.reply_text("Error al apuntarte")


async def noasistir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text("No hay reunión activa.")
            return

        user = update.effective_user.first_name or update.effective_user.username or "telegram"
        db.remove_attendance(meeting["id"], user)

        asistentes = db.get_attendance(meeting["id"])
        text = (
            f"Te has quitado de {meeting['name']}.\n"
            f"Participantes ({len(asistentes)}):\n" +
            ("\n".join(f"- {a}" for a in asistentes) if asistentes else "Nadie")
        )
        await update.message.reply_text(text)

    except Exception:
        logger.exception("Error en /noasistir")
        await update.message.reply_text("Error al quitarte")


async def asistencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        meeting = db.get_latest_scheduled_meeting()
        if not meeting:
            await update.message.reply_text("No hay reunión activa.")
            return

        asistentes = db.get_attendance(meeting["id"])
        text = f"👥 Asistencia de {meeting['name']}\n\n"
        if asistentes:
            text += "\n".join(f"- {a}" for a in asistentes)
        else:
            text += "Nadie apuntado"

        await update.message.reply_text(text)

    except Exception:
        logger.exception("Error en /asistencia")
        await update.message.reply_text("Error obteniendo asistencia")


async def tema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("Usa /tema <nombre>")
        return

    try:
        user = update.effective_user.first_name or update.effective_user.username or "telegram"
        row = db.create_theme(name, created_by=user)
        if row:
            await update.message.reply_text(f"Temática creada: {name}")
        else:
            await update.message.reply_text("Esa temática ya existe en este ciclo")

    except Exception:
        logger.exception("Error en /tema")
        await update.message.reply_text("Error creando temática")


async def temas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rows = db.get_themes()
        if not rows:
            await update.message.reply_text("No hay temáticas.")
            return

        text = "🧭 Temáticas del ciclo\n\n"
        for t in rows:
            text += f"{t['id']}. {t['name']} — {t['votes']} votos\n"

        await update.message.reply_text(text)

    except Exception:
        logger.exception("Error en /temas")
        await update.message.reply_text("Error obteniendo temáticas")


async def votar_tema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usa /votar_tema <id>")
        return

    try:
        theme_id = int(context.args[0])
        user = update.effective_user.first_name or update.effective_user.username or "telegram"
        ok = db.vote_theme(theme_id, user)

        if ok:
            await update.message.reply_text("Voto de temática registrado")
        else:
            await update.message.reply_text("Ya habías votado esa temática")

    except Exception:
        logger.exception("Error en /votar_tema")
        await update.message.reply_text("Error registrando voto de temática")


async def trivia_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text(trivia.generate())
    except Exception:
        logger.exception("Error en /trivia")
        await update.message.reply_text("Error generando trivia")


async def recomendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rec = recommendations.recommend("fiction")

        if not rec:
            await update.message.reply_text("No hay recomendaciones")
            return

        text = "Recomendaciones:\n\n" + "\n".join(
            f"- {r['title']} ({r['author']})" for r in rec
        )

        await update.message.reply_text(text)

    except Exception:
        logger.exception("Error en /recomendar")
        await update.message.reply_text("Error obteniendo recomendaciones")


# --------------------------------------------------
# REMINDERS
# --------------------------------------------------

async def send_meeting_reminder():
    meeting = db.get_latest_scheduled_meeting()
    if not meeting or not meeting.get("final_date"):
        return

    attendees = db.get_attendance(meeting["id"])
    if not attendees:
        return

    text = (
        f"⏰ Recordatorio de reunión\n\n"
        f"{meeting['name']}\n"
        f"Fecha: {meeting['final_date']}\n"
        f"Participantes apuntados: {len(attendees)}\n\n"
        f"Lista:\n" + "\n".join(f"- {a}" for a in attendees)
    )
    logger.info(text)


async def send_reading_reminder():
    meeting = db.get_latest_scheduled_meeting()
    if not meeting:
        return

    attendees = db.get_attendance(meeting["id"])
    winner = db.get_winner_book()
    db.close_cycle_proposals()
    if not attendees or not winner:
        return

    text = (
        f"📖 Recordatorio de lectura\n\n"
        f"Libro del ciclo: {winner['title']}\n"
        f"Reunión: {meeting['name']}\n"
        f"Fecha: {meeting.get('final_date') or 'Sin cerrar'}\n"
        f"Asistentes: {len(attendees)}"
    )
    logger.info(text)


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

    books = db.get_books()
    meetings = db.get_meetings(limit=5)
    themes = db.get_themes()
    ranking = db.get_book_ranking()

    return render_template(
        "admin.html",
        books=books,
        meetings=meetings,
        themes=themes,
        ranking=ranking
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

    attendees = db.get_attendance(meeting_id)
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

    name = request.form.get("name", "").strip()
    final_date = request.form.get("final_date", "").strip() or None
    summary = request.form.get("summary", "").strip() or None
    status = request.form.get("status", "").strip() or None

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

    name = request.form.get("meeting_name", "").strip()
    meeting_date = request.form.get("meeting_date", "").strip()

    if not name or not meeting_date:
        return "Faltan datos", 400

    try:
        db.create_meeting(
            name=name,
            final_date=meeting_date,
            created_by="admin"
        )
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
        return (
            f"No hay asistentes todavía para "
            f"{latest_meeting['name']}"
        )

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
        data = request.get_json(force=True)
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

    scheduler.add_job(
        send_meeting_reminder,
        "interval",
        hours=12,
        id="meeting_reminder",
        replace_existing=True
    )
    scheduler.add_job(
        send_reading_reminder,
        "interval",
        days=2,
        id="reading_reminder",
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
    server = uvicorn.Server(
        uvicorn.Config(
            asgi_app,
            host="0.0.0.0",
            port=PORT,
            log_level="info"
        )
    )

    try:
        await server.serve()
    finally:
        await shutdown()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())