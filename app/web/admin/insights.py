import os
from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, url_for

import db
from app.messages import get_text
from app.services.admin_audit import prepare_admin_audit
from app.services.bot_context import (
    COMMANDS,
    GROUP_ORDER,
    build_help_text,
    build_welcome_text,
    get_contextual_commands,
    get_cycle_context,
    get_soft_guidance,
)


PHASE_OPTIONS = [
    ("setup", "Inicio"),
    ("theme_voting", "Votacion de tematica"),
    ("books", "Propuestas de libros"),
    ("book_voting", "Votacion de libros"),
    ("date_voting", "Votacion de fecha"),
    ("reading", "Lectura"),
    ("closed", "Cerrado"),
]


def _split_csv(value):
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _parse_dt(raw_value):
    if not raw_value:
        return None
    text = str(raw_value).strip()
    for parser in (datetime.fromisoformat,):
        try:
            return parser(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            continue
    return None


def get_security_alerts():
    alerts = []

    if not os.getenv("FLASK_SECRET_KEY"):
        alerts.append(
            {
                "level": "warning",
                "title": "FLASK_SECRET_KEY no configurada",
                "message": "La sesion del panel usa una clave derivada o efimera. Define una clave propia en produccion.",
                "action_label": "Revisar despliegue",
                "action_url": "/admin/help",
            }
        )

    if not os.getenv("WEBHOOK_SECRET_TOKEN"):
        alerts.append(
            {
                "level": "warning",
                "title": "WEBHOOK_SECRET_TOKEN no configurado",
                "message": "El webhook funciona, pero con token derivado. Conviene fijar uno explicito en produccion.",
                "action_label": "Ver seguridad",
                "action_url": "/admin/help",
            }
        )

    if not os.getenv("ADMIN_SECRET"):
        alerts.append(
            {
                "level": "danger",
                "title": "ADMIN_SECRET ausente",
                "message": "El panel no deberia exponerse sin secreto de administracion configurado.",
                "action_label": "Bloqueante",
                "action_url": "/admin/help",
            }
        )

    last_webhook = _parse_dt(db.get_config("last_webhook_received_at"))
    if not last_webhook:
        alerts.append(
            {
                "level": "warning",
                "title": "Aun no hay trazas del webhook",
                "message": "No se ha registrado ninguna llamada valida al webhook desde que existe este control.",
                "action_label": "Ver logs",
                "action_url": "/admin/logs?type=system&category=webhook",
            }
        )
    else:
        age = datetime.utcnow() - last_webhook
        if age >= timedelta(hours=48):
            alerts.append(
                {
                    "level": "warning",
                    "title": "Webhook posiblemente inactivo",
                    "message": f"La ultima llamada valida al webhook fue hace {int(age.total_seconds() // 3600)}h.",
                    "action_label": "Revisar logs",
                    "action_url": "/admin/logs?type=system&category=webhook",
                }
            )

    return alerts


def render_admin_search(require_admin):
    auth = require_admin()
    if auth:
        return auth

    query = request.args.get("q", "").strip()
    results = db.search_admin(query) if query else None
    total = sum(len(items) for items in (results or {}).values()) if results else 0
    return render_template(
        "admin_search.html",
        query=query,
        results=results or {},
        total_results=total,
    )


def _sim_message_block(title, text, kind="message", meta=None):
    return {
        "title": title,
        "text": text.strip() if isinstance(text, str) else "",
        "kind": kind,
        "meta": meta or "",
    }


def render_admin_simulator(require_admin):
    auth = require_admin()
    if auth:
        return auth

    cycle_key = request.args.get("cycle", "").strip() or db.get_current_cycle_key()
    audience = request.args.get("audience", "private").strip() or "private"
    admin_mode = request.args.get("admin") == "1"

    context = get_cycle_context(cycle_key)
    meeting = context["meeting"]
    winner = context["winner"]
    dashboard_state = context["dashboard_state"]
    attendees = db.get_attendance(meeting["id"]) if meeting else []
    commands = get_contextual_commands(audience, cycle_key, is_admin=admin_mode)
    welcome_text, welcome_commands = build_welcome_text("Maria", is_admin=admin_mode, cycle_key=cycle_key)
    help_text = build_help_text(is_admin=admin_mode, cycle_key=cycle_key, audience=audience)
    phase = dashboard_state.get("step") or "setup"

    theme_options = [theme["name"] for theme in db.get_themes(cycle_key)[:10]]
    book_options = [book["title"] for book in db.get_books(cycle_key)[:10]]
    date_options = []
    if meeting:
        date_options = [str(item["option_date"])[:16] for item in db.get_meeting_date_options(meeting["id"])[:10]]

    author_line = ""
    if winner and winner.get("author"):
        author_line = f"{winner['author']}\n"
    location_line = ""
    if meeting and meeting.get("location"):
        location_line = f"{meeting['location']}\n"

    message_blocks = [
        _sim_message_block(
            "Privado /start",
            welcome_text,
            meta=f"{len(welcome_commands[:5])} accesos destacados",
        ),
        _sim_message_block(
            "Privado /ayuda",
            help_text,
            meta=f"Fase detectada: {dashboard_state.get('step_label', phase)}",
        ),
        _sim_message_block(
            "Grupo - info proxima reunion",
            get_text(
                "next_meeting_message",
                audience="group",
                phase=phase,
                cycle_key=cycle_key,
                meeting_name=meeting["name"] if meeting else "Sin reunion",
                meeting_date=str(meeting["final_date"])[:16] if meeting and meeting.get("final_date") else "Sin fecha",
                location_line=location_line,
                attendee_count=len(attendees),
            ),
        ),
        _sim_message_block(
            "Grupo - anuncio ganador",
            get_text(
                "winner_announcement_message",
                audience="group",
                phase="reading",
                cycle_key=cycle_key,
                book_title=winner["title"] if winner else "Sin libro",
                author_line=author_line,
                votes=winner.get("votes", 0) if winner else 0,
            ),
        ),
        _sim_message_block(
            "Grupo - recordatorio de reunion",
            get_text(
                "meeting_reminder_message",
                audience="group",
                phase="reading",
                cycle_key=cycle_key,
                meeting_name=meeting["name"] if meeting else "Sin reunion",
                meeting_date=str(meeting["final_date"])[:16] if meeting and meeting.get("final_date") else "Sin fecha",
                location_line=location_line,
                attendee_count=len(attendees),
                book_title=winner["title"] if winner else "Sin libro",
            ),
        ),
        _sim_message_block(
            "Grupo - recordatorio de lectura",
            get_text(
                "reading_reminder_message",
                audience="group",
                phase="reading",
                cycle_key=cycle_key,
                book_title=winner["title"] if winner else "Sin libro",
                author_line=author_line,
                meeting_name=meeting["name"] if meeting else "Sin reunion",
                meeting_date=str(meeting["final_date"])[:16] if meeting and meeting.get("final_date") else "Sin fecha",
                days_left=7,
                pages=winner.get("pages", 300) if winner else 300,
                daily_pages=25,
            ),
        ),
        _sim_message_block(
            "Encuesta - libros",
            get_text(
                "poll_books_question",
                audience="group",
                phase="book_voting",
                cycle_key=cycle_key,
            ),
            kind="poll",
            meta=", ".join(book_options[:5]) or "Sin opciones",
        ),
        _sim_message_block(
            "Encuesta - tematicas",
            get_text(
                "poll_themes_question",
                audience="group",
                phase="theme_voting",
                cycle_key=cycle_key,
            ),
            kind="poll",
            meta=", ".join(theme_options[:5]) or "Sin opciones",
        ),
        _sim_message_block(
            "Encuesta - fechas",
            get_text(
                "poll_dates_question",
                audience="group",
                phase="date_voting",
                cycle_key=cycle_key,
                meeting_name=meeting["name"] if meeting else "Proxima reunion",
            ),
            kind="poll",
            meta=", ".join(date_options[:5]) or "Sin opciones",
        ),
    ]

    guidance_samples = []
    for command_name in ("proponer", "propuestas", "tema", "asistir"):
        guidance = get_soft_guidance(command_name, cycle_key=cycle_key)
        if guidance:
            guidance_samples.append({"command": command_name, "guidance": guidance})

    return render_template(
        "admin_simulator.html",
        cycle_key=cycle_key,
        audience=audience,
        admin_mode=admin_mode,
        commands=commands,
        context=context,
        message_blocks=message_blocks,
        guidance_samples=guidance_samples,
        cycles=db.get_active_cycle_keys() or [db.get_current_cycle_key()],
        phase_options=PHASE_OPTIONS,
    )


def render_admin_bot_context(require_admin):
    auth = require_admin()
    if auth:
        return auth

    cycle_key = request.args.get("cycle", "").strip() or db.get_current_cycle_key()
    settings = db.get_cycle_bot_settings(cycle_key)
    grouped_commands = []
    for group_name in GROUP_ORDER:
        items = []
        for command_id, payload in COMMANDS.items():
            if payload["group"] == group_name:
                items.append({"id": command_id, **payload})
        if items:
            grouped_commands.append({"group": group_name, "items": items})

    return render_template(
        "admin_bot_context.html",
        cycle_key=cycle_key,
        cycles=db.get_active_cycle_keys() or [db.get_current_cycle_key()],
        settings=settings,
        grouped_commands=grouped_commands,
    )


def update_admin_bot_context(require_admin):
    auth = require_admin()
    if auth:
        return auth

    cycle_key = request.form.get("cycle", "").strip() or db.get_current_cycle_key()
    before = db.get_cycle_bot_settings(cycle_key)
    after = {
        "private_highlights": _split_csv(request.form.get("private_highlights")),
        "group_highlights": _split_csv(request.form.get("group_highlights")),
        "hidden_commands": _split_csv(request.form.get("hidden_commands")),
        "context_note": request.form.get("context_note", "").strip(),
        "help_note": request.form.get("help_note", "").strip(),
        "soft_mode_enabled": request.form.get("soft_mode_enabled") == "1",
    }
    db.set_cycle_bot_settings(cycle_key, after)
    prepare_admin_audit(
        action="bot_context_update",
        target_type="cycle",
        target_id=cycle_key,
        before=before,
        after=after,
        extra={"section": "bot_context"},
    )
    flash(f"Contexto del bot actualizado para {cycle_key}.", "success")
    return redirect(url_for("admin_bot_context", cycle=cycle_key))
