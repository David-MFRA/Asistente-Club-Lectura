import os
from flask import Flask, request
from telegram import Update
from telegram.ext import *

import books_api
import trivia
import recommendations
import db

db.init_db()

TOKEN = os.getenv("BOT_TOKEN")

telegram_app = ApplicationBuilder().token(TOKEN).build()

flask_app = Flask(__name__)

# ---------------- BOT ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text("""
BOT CLUB LECTURA

/proponer libro
/trivia
/recomendar
""")

async def proponer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = " ".join(context.args)

    if not title:
        await update.message.reply_text("Usa /proponer titulo")
        return

    book = books_api.google_books(title)

    if not book:
        await update.message.reply_text("Libro no encontrado")
        return

    user = update.effective_user.first_name or "telegram"
    db.insert_book(book, user)

    await update.message.reply_text(f"Libro añadido: {book['title']}")

async def trivia_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(trivia.generate())

async def recomendar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    rec = recommendations.recommend("fiction")

    text = "Recomendaciones:\n"

    for r in rec:
        text += f"- {r}\n"

    await update.message.reply_text(text)

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("proponer", proponer))
telegram_app.add_handler(CommandHandler("trivia", trivia_cmd))
telegram_app.add_handler(CommandHandler("recomendar", recomendar))

# ---------------- HEALTH ----------------

@flask_app.route("/")
def home():
    return "ok"

@flask_app.route("/health")
def health():
    return {"status": "running"}

# ---------------- WEBHOOK ----------------

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(
        request.get_json(force=True),
        telegram_app.bot
    )
    import asyncio
    asyncio.run(telegram_app.process_update(update))
    return "ok"

# ---------------- ADMIN ----------------

@flask_app.route("/admin")
def admin():
    books = db.get_books()
    return render_template("admin.html", books=books)

@flask_app.route("/export")
def export():

    rows = db.get_books()

    text = "title,author,votes\n"

    for r in rows:
        text += f"{r['title']},{r['author']},{r['votes']}\n"

    return text

# ---------------- START ----------------

import asyncio

async def init():

    await telegram_app.initialize()
    await telegram_app.start()

asyncio.get_event_loop().run_until_complete(init())

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    flask_app.run(
        host="0.0.0.0",
        port=port
    )