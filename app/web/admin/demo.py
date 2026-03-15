from __future__ import annotations

from flask import flash, jsonify, redirect, render_template, url_for

from app.services.demo_fixtures import DEMO_CYCLE, apply_demo_step, get_seed_bundle


def render_demo_page(require_admin, db):
    auth = require_admin()
    if auth:
        return auth
    demo_active = db.get_config("demo_mode") == "true"
    return render_template("admin_demo.html", demo_active=demo_active)


def seed_demo_data(require_admin, db, utcnow, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        bundle = get_seed_bundle(utcnow)
        cycle_key = db.get_current_cycle_key()
        for book in bundle["books"]:
            try:
                db.insert_book(book, proposed_by="demo", cycle_key=cycle_key)
            except Exception:
                pass
        for theme_name in bundle["themes"]:
            try:
                db.create_theme(theme_name, created_by="demo", cycle_key=cycle_key)
            except Exception:
                pass
        try:
            db.create_meeting(
                name=bundle["meeting"]["name"],
                final_date=bundle["meeting"]["final_date"],
                created_by="demo",
            )
        except Exception:
            pass
        db.set_config("demo_mode", "true")
        flash("Datos de demo creados", "success")
    except Exception:
        logger.exception("Error preparando demo")
        flash("Error al preparar demo", "danger")
    return redirect(url_for("admin_dashboard") + "?tour=1")


def clear_demo_data(require_admin, db, logger):
    auth = require_admin()
    if auth:
        return auth
    try:
        cycle_key = db.get_current_cycle_key()
        with db.get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM book_proposals WHERE cycle_key = %s AND proposed_by = 'demo'", (cycle_key,))
            cur.execute("DELETE FROM themes WHERE cycle_key = %s AND created_by = 'demo'", (cycle_key,))
            cur.execute("DELETE FROM meetings WHERE cycle_key = %s AND created_by = 'demo'", (cycle_key,))
        db.set_config("demo_mode", "false")
        flash("Datos de demo eliminados", "success")
    except Exception:
        logger.exception("Error limpiando datos demo")
        flash("Error al limpiar datos", "danger")
    return redirect(url_for("admin_dashboard"))


def run_demo_step(require_admin, db, utcnow, logger, step_number: int):
    auth = require_admin()
    if auth:
        return jsonify({"ok": False, "message": "No autorizado"}), 401
    try:
        message = _run_demo_step(db, utcnow, step_number)
        total = 10
        return jsonify(
            {
                "ok": True,
                "step": step_number,
                "total": total,
                "message": message,
                "done": step_number >= total - 1,
            }
        )
    except Exception as exc:
        logger.exception("Demo step %d error", step_number)
        return jsonify(
            {
                "ok": False,
                "step": step_number,
                "message": f"Error: {exc}",
                "done": True,
            }
        )


def _demo_cleanup(db):
    with db.get_cursor(commit=True) as cur:
        cur.execute(
            """DELETE FROM book_votes WHERE proposal_id IN
               (SELECT id FROM book_proposals WHERE cycle_key = %s)""",
            (DEMO_CYCLE,),
        )
        cur.execute("DELETE FROM book_proposals WHERE cycle_key = %s", (DEMO_CYCLE,))
        cur.execute("DELETE FROM themes WHERE cycle_key = %s", (DEMO_CYCLE,))
        cur.execute("DELETE FROM meetings WHERE cycle_key = %s", (DEMO_CYCLE,))


def _run_demo_step(db, utcnow, step_number: int) -> str:
    return apply_demo_step(db, utcnow, step_number)
