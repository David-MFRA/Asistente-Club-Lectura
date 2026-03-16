from flask import flash, redirect, render_template, request, url_for

import db
from app.services.admin_audit import prepare_admin_audit


def render_admin_logs(require_admin):
    """Vista de logs operativos generales del sistema."""
    auth = require_admin()
    if auth:
        return auth
    event_type = request.args.get("type", "")
    category = request.args.get("category", "")
    events = db.get_events(
        limit=300,
        event_type=event_type or None,
        category=category or None,
    )
    return render_template(
        "admin_logs.html",
        events=events,
        event_type=event_type,
        category=category,
    )


def render_public_access_logs(require_admin):
    """Vista dedicada al trafico de la pagina publica."""
    auth = require_admin()
    if auth:
        return auth
    ip_filter = request.args.get("ip", "").strip()
    rows = db.get_public_page_access_logs(limit=300, ip=ip_filter or None)
    unique_ips = len({row.get("ip") for row in rows if row.get("ip")})
    return render_template(
        "admin_public_access.html",
        rows=rows,
        ip_filter=ip_filter,
        total_rows=len(rows),
        unique_ips=unique_ips,
    )


def render_admin_security(require_admin):
    """Panel de seguridad ligera para revisar y desbloquear IPs vetadas del admin."""
    auth = require_admin()
    if auth:
        return auth
    rows = db.get_blocked_admin_ips(limit=200)
    return render_template(
        "admin_security.html",
        rows=rows,
    )


def unblock_admin_ip(require_admin):
    """Revierte un bloqueo persistente para que la IP vuelva a empezar desde cero."""
    auth = require_admin()
    if auth:
        return auth
    ip = request.form.get("ip", "").strip()
    if not ip:
        flash("IP invalida", "danger")
        return redirect(url_for("admin_security"))
    before = db.get_admin_ip_state(ip)
    released = db.unblock_admin_ip(ip)
    if not released:
        flash(f"La IP {ip} no estaba bloqueada.", "warning")
        return redirect(url_for("admin_security"))
    prepare_admin_audit(
        action="admin_ip_unblock",
        target_type="ip",
        target_id=ip,
        before=before,
        after={"ip": ip, "blocked_at": None, "failed_attempts": 0},
    )
    db.log_event("admin", f"IP desbloqueada: {ip}", category="auth", actor="security")
    flash(f"IP {ip} desbloqueada", "success")
    return redirect(url_for("admin_security"))


def render_admin_audit(require_admin):
    auth = require_admin()
    if auth:
        return auth
    action = request.args.get("action", "")
    status = request.args.get("status", "")
    rows = db.get_admin_audit_logs(
        limit=300,
        action=action or None,
        status=status or None,
    )
    return render_template(
        "admin_audit.html",
        rows=rows,
        action=action,
        status=status,
    )


def render_admin_bugs(require_admin):
    auth = require_admin()
    if auth:
        return auth
    status_filter = request.args.get("status", "")
    reports = db.get_bug_reports(status=status_filter or None)
    all_reports = db.get_bug_reports()
    counts = {
        "open": sum(1 for report in all_reports if report["status"] == "open"),
        "resolved": sum(1 for report in all_reports if report["status"] == "resolved"),
        "wontfix": sum(1 for report in all_reports if report["status"] == "wontfix"),
    }
    return render_template(
        "admin_bugs.html",
        reports=reports,
        status_filter=status_filter,
        counts=counts,
    )


def update_admin_bug(require_admin, report_id):
    auth = require_admin()
    if auth:
        return auth
    status = request.form.get("status", "open")
    admin_notes = request.form.get("admin_notes", "").strip() or None
    before = next((row for row in db.get_bug_reports() if row["id"] == report_id), None)
    db.update_bug_report(report_id, status, admin_notes)
    after = next((row for row in db.get_bug_reports() if row["id"] == report_id), None)
    prepare_admin_audit(
        action="bug_update",
        target_type="bug_report",
        target_id=report_id,
        before=before,
        after=after,
        extra={"status": status},
    )
    db.log_event("admin", f"Bug #{report_id} actualizado a '{status}'", category="bug", actor="admin")
    flash(f"Reporte #{report_id} actualizado", "success")
    return redirect(url_for("admin_bugs"))
