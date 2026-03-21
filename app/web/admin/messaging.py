import logging

from flask import flash, jsonify, redirect, render_template, request, url_for

import db
from app.services.admin_audit import prepare_admin_audit

logger = logging.getLogger(__name__)

PHASE_OPTIONS = [
    ("setup", "Inicio"),
    ("theme_voting", "Votacion de tematica"),
    ("books", "Propuestas de libros"),
    ("book_voting", "Votacion de libros"),
    ("date_voting", "Votacion de fecha"),
    ("reading", "Lectura"),
    ("closed", "Cerrado"),
]


def _build_template_rows(default_messages):
    templates_db = db.get_all_message_templates()
    templates_db_dict = {template["key"]: template for template in templates_db}
    rows = []
    for key, default_value in default_messages.items():
        custom = templates_db_dict.get(key)
        rows.append(
            {
                "key": key,
                "value": custom["value"] if custom else default_value,
                "updated_at": custom["updated_at"] if custom else None,
                "is_custom": bool(custom),
                "default_value": default_value,
            }
        )
    return rows


def render_admin_messages(require_admin, default_messages):
    auth = require_admin()
    if auth:
        return auth
    return render_template(
        "admin_messages.html",
        templates=_build_template_rows(default_messages),
        scoped_templates=db.get_scoped_message_templates(),
        base_keys=sorted(default_messages.keys()),
        active_cycles=db.get_active_cycle_keys() or [db.get_current_cycle_key()],
        phase_options=PHASE_OPTIONS,
    )


def update_admin_message(require_admin, default_messages, key):
    auth = require_admin()
    if auth:
        return auth
    if key not in default_messages:
        return "Clave no válida", 400
    value = request.form.get("value", "").strip()
    before = next((row for row in db.get_all_message_templates() if row["key"] == key), None)
    if value:
        logger.info("Admin: mensaje editado clave=%s (%d chars)", key, len(value))
        db.set_message_template(key, value)
        after = next((row for row in db.get_all_message_templates() if row["key"] == key), None)
        prepare_admin_audit(
            action="message_template_update",
            target_type="message_template",
            target_id=key,
            before=before,
            after=after,
            extra={"scope": "base"},
        )
        flash("Mensaje actualizado", "success")
    return redirect(url_for("admin_messages"))


def reset_admin_message(require_admin, key):
    auth = require_admin()
    if auth:
        return auth
    before = next((row for row in db.get_all_message_templates() if row["key"] == key), None)
    logger.info("Admin: mensaje restablecido a default clave=%s", key)
    db.delete_message_template(key)
    prepare_admin_audit(
        action="message_template_reset",
        target_type="message_template",
        target_id=key,
        before=before,
        after={"key": key, "value": None},
        extra={"scope": "base"},
    )
    flash("Mensaje restablecido al valor por defecto", "success")
    return redirect(url_for("admin_messages"))


def save_scoped_admin_message(require_admin, default_messages):
    auth = require_admin()
    if auth:
        return auth

    base_key = request.form.get("base_key", "").strip()
    audience = request.form.get("audience", "").strip() or None
    phase = request.form.get("phase", "").strip() or None
    cycle_key = request.form.get("cycle_key", "").strip() or None
    value = request.form.get("value", "").strip()

    if base_key not in default_messages:
        flash("Base del mensaje no válida", "danger")
        return redirect(url_for("admin_messages"))
    if not (audience or phase or cycle_key):
        flash("Debes definir al menos un alcance: audiencia, fase o ciclo.", "danger")
        return redirect(url_for("admin_messages"))
    if not value:
        flash("El texto no puede estar vacío", "danger")
        return redirect(url_for("admin_messages"))

    scoped_key = db.build_scoped_message_key(
        base_key,
        audience=audience,
        phase=phase,
        cycle_key=cycle_key,
    )
    before = next((row for row in db.get_scoped_message_templates() if row["key"] == scoped_key), None)
    db.set_message_template(scoped_key, value)
    after = next((row for row in db.get_scoped_message_templates() if row["key"] == scoped_key), None)
    prepare_admin_audit(
        action="message_template_scoped_save",
        target_type="message_template",
        target_id=scoped_key,
        before=before,
        after=after,
        extra={
            "base_key": base_key,
            "audience": audience,
            "phase": phase,
            "cycle_key": cycle_key,
        },
    )
    flash("Plantilla contextual guardada", "success")
    return redirect(url_for("admin_messages"))


def delete_scoped_admin_message(require_admin):
    auth = require_admin()
    if auth:
        return auth
    scoped_key = request.form.get("scoped_key", "").strip()
    if not scoped_key:
        flash("Falta la clave contextual", "danger")
        return redirect(url_for("admin_messages"))
    before = next((row for row in db.get_scoped_message_templates() if row["key"] == scoped_key), None)
    db.delete_message_template(scoped_key)
    prepare_admin_audit(
        action="message_template_scoped_delete",
        target_type="message_template",
        target_id=scoped_key,
        before=before,
        after={"key": scoped_key, "value": None},
        extra={"scope": "scoped"},
    )
    flash("Plantilla contextual eliminada", "success")
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
        "theme_name": "Fantasia",
        "cycle_name": "Lectura de Abril 2026",
        "votes": "8",
        "days_left": "6",
        "pages": "280",
        "daily_pages": "35",
        "theme_line": "Tematica: Fantasia\n",
        "books_list": "1. Libro A\n2. Libro B",
        "themes_list": "1. Fantasia\n2. Misterio",
        "question": "Que personaje te ha sorprendido mas?",
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
            "title": "Recordatorio semanal de reunion",
            "desc": "Se envia cada lunes a las 10:00. Incluye dias restantes, libro actual y ritmo de lectura.",
            "schedule": "Lunes 10:00",
            "enabled": db.get_config("reminder_weekly_enabled", "1") == "1",
        },
        {
            "key": "reminder_reading_enabled",
            "title": "Recordatorio de lectura",
            "desc": "Se envia cada 2 dias. Recuerda el libro del ciclo y la fecha de reunion.",
            "schedule": "Cada 2 dias",
            "enabled": db.get_config("reminder_reading_enabled", "1") == "1",
        },
        {
            "key": "reminder_daybefore_enabled",
            "title": "Aviso dia antes / mismo dia",
            "desc": "Se envia cada dia a las 10:00 pero solo actua si la reunion es hoy o manana.",
            "schedule": "Diario 10:00",
            "enabled": db.get_config("reminder_daybefore_enabled", "1") == "1",
        },
        {
            "key": "reminder_keepalive_enabled",
            "title": "Keep-alive ping",
            "desc": "Hace ping a /health cada 10 minutos para mantener el servicio activo.",
            "schedule": "Cada 10 minutos",
            "enabled": db.get_config("reminder_keepalive_enabled", "1") == "1",
        },
    ]
    return render_template(
        "admin_scheduler.html",
        scheduled=scheduled,
        reminders=reminders,
        custom_reminders=db.get_custom_reminders(),
    )


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
        prepare_admin_audit(
            action="scheduled_message_add",
            target_type="scheduled_message",
            target_id=send_at,
            after={"text": text, "send_at": send_at},
        )
        flash("Mensaje programado correctamente", "success")
    except Exception:
        logger.exception("Error programando mensaje")
        flash("Error programando el mensaje", "danger")
    return redirect(url_for("admin_scheduler"))


def delete_scheduled_message(require_admin, logger, msg_id):
    auth = require_admin()
    if auth:
        return auth
    before = next((row for row in db.get_all_scheduled_messages() if row["id"] == msg_id), None)
    try:
        db.delete_scheduled_message(msg_id)
        prepare_admin_audit(
            action="scheduled_message_delete",
            target_type="scheduled_message",
            target_id=msg_id,
            before=before,
            after={"deleted": True},
        )
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
        flash("El mensaje no puede estar vacío", "danger")
        return redirect(url_for("admin_dashboard"))
    try:
        ok = await send_to_group(text, parse_mode=None)
        prepare_admin_audit(
            action="send_custom_message",
            target_type="telegram_group",
            target_id="main",
            after={"length": len(text), "ok": bool(ok)},
        )
        if ok:
            flash("Mensaje enviado al grupo", "success")
        else:
            flash("Error enviando el mensaje", "danger")
    except Exception:
        logger.exception("Error enviando mensaje custom")
        flash("Error enviando el mensaje", "danger")
    return redirect(url_for("admin_dashboard"))
