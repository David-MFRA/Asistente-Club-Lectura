import json
import logging

from flask import flash, jsonify, redirect, render_template, request, url_for

import db

logger = logging.getLogger(__name__)


def render_admin_messages(require_admin, default_messages):
    auth = require_admin()
    if auth:
        return auth
    templates_db = db.get_all_message_templates()
    templates_db_dict = {template["key"]: template for template in templates_db}
    templates = []
    for key, default_value in default_messages.items():
        if key in templates_db_dict:
            templates.append(
                {
                    "key": key,
                    "value": templates_db_dict[key]["value"],
                    "updated_at": templates_db_dict[key]["updated_at"],
                    "is_custom": True,
                    "default_value": default_value,
                }
            )
        else:
            templates.append(
                {
                    "key": key,
                    "value": default_value,
                    "updated_at": None,
                    "is_custom": False,
                    "default_value": default_value,
                }
            )
    return render_template("admin_messages.html", templates=templates)


def update_admin_message(require_admin, default_messages, key):
    auth = require_admin()
    if auth:
        return auth
    if key not in default_messages:
        return "Clave no valida", 400
    value = request.form.get("value", "").strip()
    if value:
        logger.info("Admin: mensaje editado clave=%s (%d chars)", key, len(value))
        db.set_message_template(key, value)
        flash("Mensaje actualizado", "success")
    return redirect(url_for("admin_messages"))


def reset_admin_message(require_admin, key):
    auth = require_admin()
    if auth:
        return auth
    logger.info("Admin: mensaje restablecido a default clave=%s", key)
    db.delete_message_template(key)
    flash("Mensaje restablecido al valor por defecto", "success")
    return redirect(url_for("admin_messages"))


def preview_admin_message(require_admin):
    auth = require_admin()
    if auth:
        return auth
    template = request.form.get("template", "")
    example_vars = {
        "user_name": "Maria Garcia",
        "book_title": "El nombre del viento",
        "author": "Patrick Rothfuss",
        "meeting_name": "Reunion de Abril",
        "meeting_date": "2026-04-15 19:00",
        "location": "Casa de Ana",
        "attendee_count": "7",
        "count": "7",
        "names": "Maria, Carlos, Ana",
        "location_line": "Casa de Ana\n",
        "author_line": "Patrick Rothfuss\n",
    }
    try:
        rendered = template.format(**example_vars)
    except (KeyError, ValueError):
        rendered = template
    return jsonify({"rendered": rendered})


def render_sent_messages(require_admin):
    auth = require_admin()
    if auth:
        return auth
    messages = db.get_sent_messages(limit=50)
    return render_template("admin_sent_messages.html", messages=messages)


def render_scheduler(require_admin):
    auth = require_admin()
    if auth:
        return auth
    scheduled = db.get_all_scheduled_messages()
    reminders = [
        {
            "key": "reminder_weekly_enabled",
            "title": "📅 Recordatorio semanal de reunión",
            "desc": "Se envía cada lunes a las 10:00. Incluye días restantes, libro actual y ritmo de lectura.",
            "schedule": "Lunes 10:00",
            "enabled": db.get_config("reminder_weekly_enabled", "1") == "1",
        },
        {
            "key": "reminder_reading_enabled",
            "title": "📖 Recordatorio de lectura",
            "desc": "Se envía cada 2 días. Recuerda el libro del ciclo y la fecha de reunión.",
            "schedule": "Cada 2 días",
            "enabled": db.get_config("reminder_reading_enabled", "1") == "1",
        },
        {
            "key": "reminder_daybefore_enabled",
            "title": "⏰ Aviso día antes/mismo día",
            "desc": "Se envía diariamente a las 10:00 pero solo actúa si la reunión es hoy o mañana.",
            "schedule": "Diario 10:00 (activo si reunión es hoy/mañana)",
            "enabled": db.get_config("reminder_daybefore_enabled", "1") == "1",
        },
        {
            "key": "reminder_keepalive_enabled",
            "title": "💓 Keep-alive ping",
            "desc": "Hace ping a /health cada 10 minutos para mantener el servicio activo en Render.",
            "schedule": "Cada 10 minutos",
            "enabled": db.get_config("reminder_keepalive_enabled", "1") == "1",
        },
    ]
    try:
        custom_reminders = json.loads(db.get_config("custom_reminders", "[]") or "[]")
    except Exception:
        custom_reminders = []
    return render_template("admin_scheduler.html", scheduled=scheduled, reminders=reminders, custom_reminders=custom_reminders)


def add_scheduled_message(require_admin, logger):
    auth = require_admin()
    if auth:
        return auth
    text = request.form.get("text", "").strip()
    send_at = request.form.get("send_at", "").strip()
    if not text or not send_at:
        flash("Texto y fecha son obligatorios", "danger")
        return redirect(url_for("admin_scheduler"))
    try:
        db.schedule_message(text, send_at)
        logger.info("Admin: mensaje programado para %s (%d chars)", send_at, len(text))
        flash("Mensaje programado correctamente", "success")
    except Exception:
        logger.exception("Error programando mensaje")
        flash("Error programando el mensaje", "danger")
    return redirect(url_for("admin_scheduler"))


def delete_scheduled_message(require_admin, logger, msg_id):
    auth = require_admin()
    if auth:
        return auth
    try:
        db.delete_scheduled_message(msg_id)
        flash("Mensaje eliminado", "success")
    except Exception:
        logger.exception("Error eliminando mensaje programado #%s", msg_id)
        flash("No se pudo eliminar el mensaje", "danger")
    return redirect(url_for("admin_scheduler"))


async def send_custom_message(require_admin, logger, send_to_group):
    auth = require_admin()
    if auth:
        return auth
    text = request.form.get("message", "").strip()
    logger.info("Admin: enviando mensaje custom al grupo (%d chars)", len(text))
    if not text:
        flash("El mensaje no puede estar vacio", "danger")
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
