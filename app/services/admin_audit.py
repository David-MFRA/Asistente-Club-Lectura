import json

from flask import g, request, session

import db


def get_request_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    raw = forwarded or request.remote_addr or "unknown"
    return raw.split(",")[0].strip()


def get_admin_actor(default="admin"):
    alias = (session.get("admin_display_name") or "").strip()
    if alias:
        return alias
    actor = (session.get("admin_actor") or "").strip()
    if actor:
        return actor
    return default


def remember_admin_identity(display_name=None):
    display_name = (display_name or "").strip()
    ip = get_request_ip()
    if display_name:
        session["admin_display_name"] = display_name[:80]
        session["admin_actor"] = display_name[:80]
    else:
        session["admin_actor"] = f"admin@{ip}"
    session["admin_ip"] = ip
    return get_admin_actor()


def prepare_admin_audit(
    *,
    action=None,
    actor=None,
    target_type=None,
    target_id=None,
    status=None,
    result=None,
    before=None,
    after=None,
    extra=None,
):
    payload = dict(getattr(g, "admin_audit_payload", {}) or {})
    updates = {
        "action": action,
        "actor": actor,
        "target_type": target_type,
        "target_id": target_id,
        "status": status,
        "result": result,
        "before": before,
        "after": after,
        "extra": extra,
    }
    for key, value in updates.items():
        if value is None:
            continue
        if key == "extra":
            merged = dict(payload.get("extra") or {})
            merged.update(value)
            payload["extra"] = merged
        else:
            payload[key] = value
    g.admin_audit_payload = payload


def audit_admin(
    action,
    *,
    actor=None,
    target_type=None,
    target_id=None,
    status="ok",
    result=None,
    before=None,
    after=None,
    extra=None,
):
    db.log_admin_audit(
        action,
        actor=actor or get_admin_actor(),
        route=request.path,
        method=request.method,
        ip=get_request_ip(),
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        status=status,
        result=result,
        before=before,
        after=after,
        extra=extra,
    )
    g.admin_audit_logged = True


def flush_pending_admin_audit(response):
    if getattr(g, "admin_audit_logged", False):
        return response
    if request.path == "/webhook":
        return response
    if request.method != "POST":
        return response
    if not (request.path.startswith("/admin") or session.get("admin_logged") is True):
        return response

    payload = dict(getattr(g, "admin_audit_payload", {}) or {})
    action = payload.pop("action", None) or (request.endpoint or request.path)
    actor = payload.pop("actor", None) or get_admin_actor()
    status = payload.pop("status", None) or ("ok" if response.status_code < 400 else "error")
    result = payload.pop("result", None) or response.status
    before = payload.pop("before", None)
    after = payload.pop("after", None)
    target_type = payload.pop("target_type", None)
    target_id = payload.pop("target_id", None)
    extra = payload.pop("extra", None)
    if extra and not isinstance(extra, dict):
        extra = {"raw": json.dumps(extra, ensure_ascii=False)}

    db.log_admin_audit(
        action,
        actor=actor,
        route=request.path,
        method=request.method,
        ip=get_request_ip(),
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        status=status,
        result=result,
        before=before,
        after=after,
        extra=extra,
    )
    g.admin_audit_logged = True
    return response
