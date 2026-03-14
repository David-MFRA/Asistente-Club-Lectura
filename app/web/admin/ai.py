from flask import flash, jsonify, redirect, render_template, request, url_for

import ai_features
import db


def render_ai_questions(require_admin, logger):
    auth = require_admin()
    if auth:
        return auth
    winner = db.get_winner_book()
    if not winner:
        flash("No hay libro del ciclo activo", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        questions = ai_features.generate_discussion_questions(
            winner["title"], winner.get("author", ""), winner.get("description", "")
        )
        content = f"Preguntas de debate - {winner['title']}\n\n{questions}"
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


async def send_ai_questions(require_admin, logger, send_to_group):
    auth = require_admin()
    if auth:
        return auth
    content = request.form.get("content", "").strip()
    if not content:
        flash("Contenido vacio", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        await send_to_group(content, parse_mode=None, message_type="ai_questions")
        db.log_event("admin", "Preguntas de debate IA enviadas al grupo", category="ai", actor="admin")
        flash("Preguntas de debate enviadas al grupo", "success")
    except Exception:
        logger.exception("Error enviando preguntas AI")
        flash("Error enviando preguntas", "danger")
    return redirect(url_for("admin_dashboard"))


def render_ai_quote(require_admin, logger):
    auth = require_admin()
    if auth:
        return auth
    winner = db.get_winner_book()
    if not winner:
        flash("No hay libro del ciclo activo", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        quote = ai_features.generate_book_quote(winner["title"], winner.get("author", ""))
        content = f"{quote}\n\nSobre «{winner['title']}»"
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


async def send_ai_quote(require_admin, logger, send_to_group):
    auth = require_admin()
    if auth:
        return auth
    content = request.form.get("content", "").strip()
    if not content:
        flash("Contenido vacio", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        await send_to_group(content, parse_mode=None, message_type="ai_quote")
        flash("Cita enviada al grupo", "success")
    except Exception:
        logger.exception("Error enviando cita AI")
        flash("Error enviando cita", "danger")
    return redirect(url_for("admin_dashboard"))


async def ask_admin_ai(require_admin, utcnow, logger):
    auth = require_admin()
    if auth:
        return jsonify({"error": "No autorizado"}), 401

    question = request.json.get("question", "").strip() if request.is_json else request.form.get("question", "").strip()
    if not question:
        return jsonify({"error": "Pregunta vacia"}), 400

    cycle_key = db.get_current_cycle_key()
    winner = db.get_winner_book()
    proposals = db.get_book_proposals(cycle_key)
    meeting = db.get_latest_scheduled_meeting()
    attendees = db.get_attendance(meeting["id"]) if meeting else []

    context_lines = [
        "Eres el asistente del Club de Lectura. Responde siempre en espanol.",
        f"Fecha actual: {utcnow().strftime('%d/%m/%Y')}",
        f"Ciclo actual: {cycle_key}",
    ]
    if winner:
        context_lines.append(
            f"Libro del ciclo: «{winner['title']}»"
            + (f" de {winner['author']}" if winner.get("author") else "")
            + f" ({winner.get('votes', 0)} votos)"
        )
        if winner.get("description"):
            context_lines.append(f"Sinopsis: {winner['description'][:200]}")
    if proposals:
        tops = proposals[:5]
        prop_str = ", ".join(f"«{book['title']}» ({book['votes']} votos)" for book in tops)
        context_lines.append(f"Propuestas actuales (top 5): {prop_str}")
    if meeting:
        date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "Sin fecha"
        context_lines.append(f"Proxima reunion: {meeting['name']} - {date_text}")
        if meeting.get("location"):
            context_lines.append(f"Lugar: {meeting['location']}")
        if attendees:
            context_lines.append(f"Asistentes ({len(attendees)}): {', '.join(attendees[:10])}")

    full_prompt = "\n".join(context_lines) + f"\n\nPregunta del administrador: {question}"

    try:
        answer = ai_features._groq_chat(full_prompt)
        if not answer:
            return jsonify({"error": "No hay respuesta de la IA (¿esta configurado GROQ_API_KEY?)"}), 503
        return jsonify({"answer": answer})
    except Exception as exc:
        logger.exception("Error en AI ask")
        return jsonify({"error": str(exc)}), 500
