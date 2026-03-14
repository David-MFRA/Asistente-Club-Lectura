from flask import flash, redirect, url_for

import db


async def create_book_poll(require_admin, telegram_app, telegram_chat_id, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        books = db.get_book_proposals()
        if len(books) < 2:
            return "Necesitas al menos 2 propuestas para crear una encuesta", 400
        if not telegram_chat_id:
            return "TELEGRAM_CHAT_ID no configurado en variables de entorno", 500

        options = []
        for book in books[:10]:
            label = book["title"]
            if book.get("author"):
                label = f"{book['title']} - {book['author']}"
            options.append(label[:100])

        msg = await telegram_app.bot.send_poll(
            chat_id=telegram_chat_id,
            question="¿Que libro leemos este mes?",
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        db.save_poll(chat_id=msg.chat_id, message_id=msg.message_id, poll_id=msg.poll.id, poll_type="books")
    except Exception:
        logger.exception("Error creando encuesta libros")
        return "Error creando encuesta", 500
    return redirect(url_for("admin_dashboard"))


async def close_poll(require_admin, poll_db_id, telegram_app, telegram_chat_id, send_to_group, announce_winner, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        poll = db.get_poll_by_id(poll_db_id)
        if not poll:
            return "Encuesta no encontrada", 404
        await telegram_app.bot.stop_poll(chat_id=poll["chat_id"], message_id=poll["message_id"])
        db.close_poll(poll_db_id)
        if poll.get("poll_type") == "books" and telegram_chat_id:
            tied = db.get_tied_books()
            if len(tied) > 1:
                tie_msg = (
                    f"Hay empate en la votacion.\n\n"
                    f"Los siguientes libros han quedado empatados con {tied[0]['votes']} votos:\n"
                )
                for book in tied:
                    tie_msg += f"  {book['title']}" + (f" - {book['author']}" if book.get("author") else "") + "\n"
                tie_msg += "\nLanzando encuesta de desempate..."
                await send_to_group(tie_msg, parse_mode=None, message_type="tie_notification")

                options = []
                for book in tied[:10]:
                    label = book["title"]
                    if book.get("author"):
                        label = f"{book['title']} - {book['author']}"
                    options.append(label[:100])

                tie_poll = await telegram_app.bot.send_poll(
                    chat_id=telegram_chat_id,
                    question=f"Desempate - ¿Cual de estos {len(tied)} libros leemos?",
                    options=options,
                    is_anonymous=False,
                    allows_multiple_answers=False,
                )
                db.save_poll(chat_id=tie_poll.chat_id, message_id=tie_poll.message_id, poll_id=tie_poll.poll.id, poll_type="books")
                flash(f"Empate detectado. Se ha lanzado una encuesta de desempate con {len(tied)} libros.", "warning")
                return redirect(url_for("admin_dashboard"))
            winner = db.get_winner_book()
            if winner:
                await announce_winner(winner)
                next_meeting = db.get_latest_scheduled_meeting()
                if next_meeting and not next_meeting.get("book_id"):
                    db.update_meeting(meeting_id=next_meeting["id"], book_id=winner["id"])
    except Exception:
        logger.exception("Error cerrando encuesta")
        return "Error cerrando encuesta", 500
    return redirect(url_for("admin_dashboard"))


async def create_theme_poll(require_admin, telegram_app, telegram_chat_id, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        themes = db.get_themes()
        if len(themes) < 2:
            return "Necesitas al menos 2 tematicas para crear una encuesta", 400
        if not telegram_chat_id:
            return "TELEGRAM_CHAT_ID no configurado", 500
        options = [theme["name"][:100] for theme in themes[:10]]
        msg = await telegram_app.bot.send_poll(
            chat_id=telegram_chat_id,
            question="¿Que tematica elegimos para el proximo ciclo?",
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        db.save_poll(chat_id=msg.chat_id, message_id=msg.message_id, poll_id=msg.poll.id, poll_type="themes")
    except Exception:
        logger.exception("Error creando encuesta temas")
        return "Error creando encuesta", 500
    return redirect(url_for("admin_dashboard"))


async def create_dates_poll(require_admin, meeting_id, telegram_app, telegram_chat_id, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        meeting = db.get_meeting(meeting_id)
        if not meeting:
            return "Reunion no encontrada", 404
        date_options = db.get_meeting_date_options(meeting_id)
        if len(date_options) < 2:
            return "Añade al menos 2 opciones de fecha primero", 400
        if not telegram_chat_id:
            return "TELEGRAM_CHAT_ID no configurado", 500
        poll_options = [str(option["option_date"])[:20] for option in date_options[:10]]
        msg = await telegram_app.bot.send_poll(
            chat_id=telegram_chat_id,
            question=f"¿Cuando nos reunimos? - {meeting['name']}",
            options=poll_options,
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        db.save_poll(chat_id=msg.chat_id, message_id=msg.message_id, poll_id=msg.poll.id, poll_type="dates", meeting_id=meeting_id)
    except Exception:
        logger.exception("Error creando encuesta fechas")
        return "Error creando encuesta fechas", 500
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))


async def close_dates_poll(require_admin, meeting_id, poll_db_id, telegram_app, send_to_group, formatting, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        poll = db.get_poll_by_id(poll_db_id)
        if not poll:
            return "Encuesta no encontrada", 404
        tg_poll = await telegram_app.bot.stop_poll(chat_id=poll["chat_id"], message_id=poll["message_id"])
        db.close_poll(poll_db_id)
        if tg_poll.options:
            winner_text = max(tg_poll.options, key=lambda option: option.voter_count).text
            date_opts = db.get_meeting_date_options(meeting_id)
            for option in date_opts:
                opt_str = str(option["option_date"])
                if winner_text[:16] in opt_str[:20] or opt_str[:16] in winner_text[:20]:
                    db.set_meeting_final_date(meeting_id, option["option_date"])
                    meeting_name = db.get_meeting(meeting_id)["name"]
                    await send_to_group(
                        f"{formatting['bold']('¡Fecha de reunion decidida!')}\n\n"
                        f"La reunion {formatting['italic'](meeting_name)} sera el "
                        f"{formatting['bold'](formatting['esc'](opt_str))}\\.\n\n"
                        f"_Usa /asistir para apuntarte\\._",
                    )
                    break
    except Exception:
        logger.exception("Error cerrando encuesta fechas")
        return "Error cerrando encuesta fechas", 500
    return redirect(url_for("meeting_detail_admin", meeting_id=meeting_id))
