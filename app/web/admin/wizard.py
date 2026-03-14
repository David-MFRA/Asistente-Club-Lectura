from flask import flash, redirect, request, url_for
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import db


async def wizard_new_cycle(require_admin, send_to_group, utcnow, logger):
    auth = require_admin()
    if auth:
        return auth

    cycle_name = request.form.get("cycle_name", "").strip()
    if not cycle_name:
        cycle_name = utcnow().strftime("%Y-%m")
    cycle_name = cycle_name.upper()
    db.set_config("active_cycle_key", cycle_name)

    try:
        text = "\n".join(
            [
                f"📚 Nuevo ciclo de lectura: {cycle_name}",
                "",
                "✨ Arranca una nueva ronda del club.",
                "Es momento de proponer lecturas para elegir el siguiente libro.",
                "",
                "📝 Usa este comando en el chat:",
                "/proponer titulo del libro",
                "",
                "💡 Cuantas mas propuestas tengamos, mejor saldra la votacion.",
            ]
        )
        await send_to_group(text, parse_mode=None, message_type="new_cycle")
        flash(f"Ciclo {cycle_name} iniciado. Mensaje enviado al grupo.", "success")
    except Exception:
        logger.exception("Error en wizard new-cycle")
        flash(f"Ciclo {cycle_name} creado pero no se pudo enviar el mensaje al grupo.", "warning")
    return redirect(url_for("admin_dashboard"))


async def wizard_lock_and_poll(require_admin, telegram_app, telegram_chat_id, logger):
    auth = require_admin()
    if auth:
        return auth

    cycle = request.form.get("cycle") or db.get_current_cycle_key()
    books = db.get_book_proposals(cycle)
    if len(books) < 2:
        flash("Necesitas al menos 2 propuestas para lanzar la encuesta.", "danger")
        return redirect(url_for("admin_dashboard"))
    if not telegram_chat_id:
        flash("TELEGRAM_CHAT_ID no configurado.", "danger")
        return redirect(url_for("admin_dashboard"))

    try:
        locked_now = db.get_config("proposals_locked_for") or ""
        locked_set = {value.strip() for value in locked_now.split(",") if value.strip()}
        locked_set.add(cycle)
        db.set_config("proposals_locked_for", ",".join(sorted(locked_set)))

        options = []
        for book in books[:10]:
            label = book["title"]
            if book.get("author"):
                label = f"{book['title']} - {book['author']}"
            options.append(label[:100])

        msg = await telegram_app.bot.send_poll(
            chat_id=telegram_chat_id,
            question="📚 ¿Qué libro leemos en este ciclo?",
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        db.save_poll(
            chat_id=msg.chat_id,
            message_id=msg.message_id,
            poll_id=msg.poll.id,
            poll_type="books",
            cycle_key=cycle,
        )
        flash("Propuestas cerradas y encuesta de libros lanzada en Telegram.", "success")
    except Exception:
        logger.exception("Error en wizard lock-and-poll")
        flash("Error lanzando la encuesta.", "danger")
    return redirect(url_for("admin_dashboard"))


async def wizard_announce_date(require_admin, send_to_group, logger):
    auth = require_admin()
    if auth:
        return auth

    meeting = db.get_latest_scheduled_meeting()
    if not meeting or not meeting.get("final_date"):
        flash("No hay reunion con fecha confirmada.", "danger")
        return redirect(url_for("admin_dashboard"))

    try:
        date_text = str(meeting["final_date"])[:16]
        cycle = request.form.get("cycle") or db.get_current_cycle_key()
        winner = db.get_winner_book(cycle)
        book_line = f"\n📖 Libro: {winner['title']}" if winner else ""
        location_line = f"\n📍 Lugar: {meeting['location']}" if meeting.get("location") else ""
        text = "\n".join(
            [
                "📅 Ya tenemos fecha para la reunion",
                "",
                f"🫶 {meeting['name']}",
                f"🕒 {date_text}{location_line}{book_line}",
                "",
                "✅ Apuntate con /asistir",
                "❌ Si no puedes venir, usa /noasistir",
            ]
        )
        keyboard = [[
            InlineKeyboardButton("✅ Asistir", callback_data=f"attend:{meeting['id']}"),
            InlineKeyboardButton("❌ No voy", callback_data=f"noattend:{meeting['id']}"),
        ]]
        await send_to_group(
            text,
            parse_mode=None,
            reply_markup=InlineKeyboardMarkup(keyboard),
            message_type="date_announcement",
        )
        flash("Fecha de reunion anunciada en el grupo.", "success")
    except Exception:
        logger.exception("Error en wizard announce-date")
        flash("Error enviando el anuncio.", "danger")
    return redirect(url_for("admin_dashboard"))
