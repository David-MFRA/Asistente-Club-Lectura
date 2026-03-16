from __future__ import annotations

import secrets
import time as _time
from datetime import timedelta

from flask import abort, redirect, render_template, request, session, url_for

import db
from app.services.admin_audit import (
    audit_admin,
    flush_pending_admin_audit,
    get_admin_actor,
    get_request_ip,
    remember_admin_identity,
)


def install_admin_panel(
    flask_app,
    *,
    admin_secret,
    webhook_url,
    observability,
    run_async,
    send_to_group,
    send_and_pin,
    send_meeting_reminder,
    send_reading_reminder,
    announce_winner,
    logger,
    telegram_app,
    telegram_chat_id,
    default_messages,
    group_invite_link,
    reload_custom_reminders,
    utcnow,
    admin_search_limiter,
    poll_formatting,
    webhook_handler,
):
    """
    Registra el panel admin compartido.

    Este modulo es la fuente de verdad del login web, CSRF, auditoria y rutas
    administrativas. `main.py` solo deberia delegar aqui para evitar divergencias.
    """
    from app.web.admin.routes import register_admin_routes

    flask_app.config.update(
        SESSION_COOKIE_NAME="club_admin_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=str(webhook_url).startswith("https://"),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )

    @flask_app.template_filter("dt_local")
    def dt_local_filter(value):
        if not value:
            return ""
        return str(value).replace(" ", "T")[:16]

    def is_admin_logged():
        return session.get("admin_logged") is True

    def require_admin():
        if not is_admin_logged():
            return redirect(url_for("admin_login"))
        return None

    # El bloqueo por IP vive en DB para que sobreviva reinicios y funcione igual
    # si el despliegue usa varios procesos o workers.
    def is_admin_ip_blocked(remote_addr: str):
        return db.is_admin_ip_blocked(remote_addr)

    def register_login_failure(remote_addr: str):
        return db.register_admin_login_failure(remote_addr, block_after=3)

    def clear_login_failures(remote_addr: str):
        return db.clear_admin_login_failures(remote_addr)

    def get_csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)
        return session["csrf_token"]

    flask_app.jinja_env.globals["csrf_token"] = get_csrf_token

    @flask_app.before_request
    def csrf_protect():
        request.environ["_request_started_at"] = _time.monotonic()
        if request.method != "POST":
            return
        if request.path in ("/admin/login", "/webhook"):
            return
        if not is_admin_logged():
            return
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not token or token != session.get("csrf_token"):
            logger.warning("CSRF invalido en %s desde %s", request.path, request.remote_addr)
            abort(403)

    @flask_app.after_request
    def admin_audit_after_request(response):
        started_at = request.environ.get("_request_started_at")
        if started_at is not None and observability is not None:
            observability.record_request(
                request.method,
                request.path,
                response.status_code,
                int((_time.monotonic() - started_at) * 1000),
            )
        if request.path.startswith("/admin"):
            # Las pantallas del panel no deben indexarse aunque alguien enlace
            # una URL privada desde fuera del sitio.
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return flush_pending_admin_audit(response)

    @flask_app.get("/admin/login")
    def admin_login():
        if is_admin_logged():
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", display_name=session.get("admin_display_name", ""))

    @flask_app.post("/admin/login")
    def admin_login_post():
        remote_addr = get_request_ip()
        display_name = request.form.get("display_name", "").strip()
        if is_admin_ip_blocked(remote_addr):
            logger.warning("Login admin bloqueado para IP ya bloqueada %s", remote_addr)
            audit_admin(
                "admin_login",
                actor=display_name or f"admin@{remote_addr}",
                target_type="session",
                target_id=remote_addr,
                status="blocked",
                result="ip_blocked",
                extra={"display_name": display_name or None},
            )
            return render_template(
                "admin_login.html",
                error="Esta IP esta bloqueada tras 3 intentos fallidos.",
                display_name=display_name,
            ), 423
        secret = request.form.get("secret", "").strip()
        if not admin_secret:
            return "ADMIN_SECRET no configurado", 500
        if secret != admin_secret:
            failure_state = register_login_failure(remote_addr)
            attempts = int(failure_state.get("failed_attempts") or 0)
            if failure_state.get("is_blocked"):
                logger.warning("Login admin bloqueado tras %d intentos desde %s", attempts, remote_addr)
                audit_admin(
                    "admin_login",
                    actor=display_name or f"admin@{remote_addr}",
                    target_type="session",
                    target_id=remote_addr,
                    status="blocked",
                    result="blocked_after_invalid_secret",
                    extra={"attempt": attempts, "display_name": display_name or None},
                )
                if failure_state.get("just_blocked"):
                    db.log_event(
                        "admin",
                        f"IP bloqueada tras intentos fallidos: {remote_addr}",
                        category="auth",
                        actor="security",
                        extra={"ip": remote_addr, "attempts": attempts},
                    )
                return render_template(
                    "admin_login.html",
                    error="Esta IP ha sido bloqueada al alcanzar 3 intentos fallidos.",
                    display_name=display_name,
                ), 423
            logger.warning("Login admin fallido desde %s (intento %d de 3)", remote_addr, attempts)
            audit_admin(
                "admin_login",
                actor=display_name or f"admin@{remote_addr}",
                target_type="session",
                target_id=remote_addr,
                status="error",
                result="invalid_secret",
                extra={"attempt": attempts, "display_name": display_name or None},
            )
            return render_template(
                "admin_login.html",
                error=f"Secreto incorrecto. Intento {attempts} de 3.",
                display_name=display_name,
            ), 403
        clear_login_failures(remote_addr)
        session.clear()
        actor = remember_admin_identity(display_name)
        session["admin_logged"] = True
        session["csrf_token"] = secrets.token_hex(16)
        session.permanent = True
        audit_admin(
            "admin_login",
            actor=actor,
            target_type="session",
            target_id=remote_addr,
            status="ok",
            result="login_ok",
            extra={"display_name": display_name or None},
        )
        db.log_event("admin", "Inicio de sesion en el panel", category="auth", actor="admin")
        logger.info("Login admin correcto desde %s", remote_addr)
        return redirect(url_for("admin_dashboard"))

    @flask_app.post("/admin/logout")
    def admin_logout():
        actor = get_admin_actor()
        remote_addr = get_request_ip()
        db.log_event("admin", "Cierre de sesion del panel", category="auth", actor="admin")
        audit_admin(
            "admin_logout",
            actor=actor,
            target_type="session",
            target_id=remote_addr,
            status="ok",
            result="logout_ok",
        )
        session.clear()
        return redirect(url_for("admin_login"))

    register_admin_routes(
        flask_app,
        require_admin=require_admin,
        run_async=run_async,
        send_to_group=send_to_group,
        send_and_pin=send_and_pin,
        send_meeting_reminder=send_meeting_reminder,
        send_reading_reminder=send_reading_reminder,
        announce_winner=announce_winner,
        logger=logger,
        telegram_app=telegram_app,
        telegram_chat_id=telegram_chat_id,
        default_messages=default_messages,
        group_invite_link=group_invite_link,
        reload_custom_reminders=reload_custom_reminders,
        utcnow=utcnow,
        get_request_ip=get_request_ip,
        admin_search_limiter=admin_search_limiter,
        poll_formatting=poll_formatting,
        observability=observability,
    )

    @flask_app.post("/webhook")
    def webhook():
        return webhook_handler.handle_request(request)

    flask_app.extensions["admin_panel"] = {
        "require_admin": require_admin,
        "is_admin_logged": is_admin_logged,
        "get_csrf_token": get_csrf_token,
    }
    return require_admin
