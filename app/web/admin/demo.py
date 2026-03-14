from __future__ import annotations

from datetime import timedelta

from flask import flash, jsonify, redirect, render_template, url_for


_DEMO_CYCLE = "__DEMO__"
_DEMO_BOOKS = [
    {
        "title": "El nombre del viento",
        "author": "Patrick Rothfuss",
        "pages": 662,
        "description": "La historia de Kvothe, un mago legendario.",
        "language_code": "es",
    },
    {
        "title": "Sapiens",
        "author": "Yuval Noah Harari",
        "pages": 496,
        "description": "Una breve historia de la humanidad.",
        "language_code": "es",
    },
    {
        "title": "La sombra del viento",
        "author": "Carlos Ruiz Zafon",
        "pages": 544,
        "description": "Un laberinto de libros perdidos en Barcelona.",
        "language_code": "es",
    },
    {
        "title": "El Hobbit",
        "author": "J.R.R. Tolkien",
        "pages": 310,
        "description": "La aventura de Bilbo Bolson.",
        "language_code": "es",
    },
]
_DEMO_VOTE_DIST = [5, 3, 2, 1]


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
        demo_books = [
            {
                "title": "El nombre del viento",
                "author": "Patrick Rothfuss",
                "pages": 662,
                "description": "La historia de Kvothe, un mago legendario que narra su propia vida.",
                "language_code": "es",
            },
            {
                "title": "Sapiens",
                "author": "Yuval Noah Harari",
                "pages": 496,
                "description": "Una breve historia de la humanidad desde el homo sapiens hasta la actualidad.",
                "language_code": "es",
            },
            {
                "title": "La sombra del viento",
                "author": "Carlos Ruiz Zafon",
                "pages": 544,
                "description": "Un misterioso libro hace que un joven se aventure en el laberinto de los libros perdidos de Barcelona.",
                "language_code": "es",
            },
        ]
        cycle_key = db.get_current_cycle_key()
        for book in demo_books:
            try:
                db.insert_book(book, proposed_by="demo", cycle_key=cycle_key)
            except Exception:
                pass
        try:
            db.create_theme("Fantasia epica", created_by="demo", cycle_key=cycle_key)
        except Exception:
            pass
        demo_date = (utcnow() + timedelta(days=14)).replace(hour=19, minute=0, second=0, microsecond=0)
        try:
            db.create_meeting(name="Reunion de demostracion", final_date=str(demo_date), created_by="demo")
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
            (_DEMO_CYCLE,),
        )
        cur.execute("DELETE FROM book_proposals WHERE cycle_key = %s", (_DEMO_CYCLE,))
        cur.execute("DELETE FROM themes WHERE cycle_key = %s", (_DEMO_CYCLE,))
        cur.execute("DELETE FROM meetings WHERE cycle_key = %s", (_DEMO_CYCLE,))


def _run_demo_step(db, utcnow, step_number: int) -> str:
    if step_number == 0:
        _demo_cleanup(db)
        return "Entorno limpio; ciclo __DEMO__ preparado"
    if step_number == 1:
        db.insert_book(_DEMO_BOOKS[0], proposed_by="__demo__", cycle_key=_DEMO_CYCLE)
        return f"Propuesta: {_DEMO_BOOKS[0]['title']} ({_DEMO_BOOKS[0]['author']})"
    if step_number == 2:
        db.insert_book(_DEMO_BOOKS[1], proposed_by="__demo__", cycle_key=_DEMO_CYCLE)
        return f"Propuesta: {_DEMO_BOOKS[1]['title']} ({_DEMO_BOOKS[1]['author']})"
    if step_number == 3:
        db.insert_book(_DEMO_BOOKS[2], proposed_by="__demo__", cycle_key=_DEMO_CYCLE)
        return f"Propuesta: {_DEMO_BOOKS[2]['title']} ({_DEMO_BOOKS[2]['author']})"
    if step_number == 4:
        db.insert_book(_DEMO_BOOKS[3], proposed_by="__demo__", cycle_key=_DEMO_CYCLE)
        return f"Propuesta: {_DEMO_BOOKS[3]['title']} ({_DEMO_BOOKS[3]['author']})"
    if step_number == 5:
        books = db.get_books(_DEMO_CYCLE)
        lines = []
        for index, book in enumerate(books[:4]):
            votes = _DEMO_VOTE_DIST[index] if index < len(_DEMO_VOTE_DIST) else 0
            for user_index in range(votes):
                db.vote_book(book["proposal_id"], f"__demo_user_{index}_{user_index}__")
            lines.append(f"{book['title'][:22]}: {'*' * votes} ({votes})")
        return "Votaciones simuladas: " + " | ".join(lines)
    if step_number == 6:
        db.create_theme("Fantasia epica", created_by="__demo__", cycle_key=_DEMO_CYCLE)
        db.create_theme("Ciencia ficcion", created_by="__demo__", cycle_key=_DEMO_CYCLE)
        return "Tematicas creadas: Fantasia epica, Ciencia ficcion"
    if step_number == 7:
        demo_date = (utcnow() + timedelta(days=12)).replace(hour=19, minute=0, second=0, microsecond=0)
        db.create_meeting(
            name="Reunion demo - Club de Lectura",
            final_date=str(demo_date),
            cycle_key=_DEMO_CYCLE,
            created_by="__demo__",
        )
        return f"Reunion demo creada para {str(demo_date)[:16]}"
    if step_number == 8:
        books = db.get_books(_DEMO_CYCLE)
        winner = books[0] if books else None
        if winner:
            return f"Ganador del ciclo demo: {winner['title']} con {winner['votes']} votos."
        return "Ciclo demo completado"
    if step_number == 9:
        _demo_cleanup(db)
        return "Datos de demo eliminados; entorno limpio"
    return "Demo completada"
