from flask import flash, redirect, render_template, request, url_for

import db
from app.services.admin_audit import prepare_admin_audit


def render_admin_logs(require_admin):
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
