from __future__ import annotations

from copy import deepcopy
from datetime import timedelta


DEMO_CYCLE = "__DEMO__"
DEMO_BOOKS = [
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
        "description": "Un misterioso libro lleva a un joven al cementerio de los libros olvidados.",
        "language_code": "es",
    },
    {
        "title": "El Hobbit",
        "author": "J.R.R. Tolkien",
        "pages": 310,
        "description": "La aventura de Bilbo Bolsón camino de Erebor.",
        "language_code": "es",
    },
]
DEMO_THEMES = ["Fantasía épica", "Ciencia ficción"]
DEMO_VOTE_DIST = [5, 3, 2, 1]

SIMULATOR_SCENARIOS = {
    "default": {
        "label": "Actual",
        "description": "Estado real del ciclo seleccionado.",
    },
    "tie": {
        "label": "Empate",
        "description": "Simula empate final de votos para validar mensajes y decisiones.",
    },
    "no_meeting": {
        "label": "Sin reunión",
        "description": "Libro elegido pero sin fecha cerrada todavía.",
    },
    "multipart_poll": {
        "label": "Encuesta multipart",
        "description": "Varias encuestas de libros abiertas para revisar copy y opciones.",
    },
    "locked_cycle": {
        "label": "Ciclo bloqueado",
        "description": "Propuestas cerradas y panel listo para lanzar o cerrar votación.",
    },
}


def get_demo_books():
    return [deepcopy(book) for book in DEMO_BOOKS]


def get_seed_bundle(utcnow):
    demo_date = (utcnow() + timedelta(days=14)).replace(hour=19, minute=0, second=0, microsecond=0)
    return {
        "books": get_demo_books()[:3],
        "themes": list(DEMO_THEMES),
        "meeting": {
            "name": "Reunión de demostración",
            "final_date": str(demo_date),
        },
    }


def _tg(run_async, coro):
    """Lanza un mensaje Telegram desde contexto síncrono. Silencioso si no hay loop."""
    if run_async is not None and coro is not None:
        try:
            run_async(coro)
        except Exception:
            pass


def apply_demo_step(db_module, utcnow, step_number: int,
                    run_async=None, send_to_group=None, send_and_pin=None) -> str:
    if step_number == 0:
        _demo_cleanup(db_module)
        _tg(run_async, send_to_group and send_to_group(
            "🎬 <b>Demo del club iniciada</b>\n\n"
            "Vamos a simular un ciclo completo: propuestas → votación → reunión → ganador.\n"
            "<i>(Esto es una demostración automática — los datos se borrarán al terminar)</i>",
            parse_mode="HTML",
        ))
        return "Entorno limpio — demo iniciada y anunciada en el grupo"

    if step_number in (1, 2, 3, 4):
        book = get_demo_books()[step_number - 1]
        db_module.insert_book(book, proposed_by="__demo__", cycle_key=DEMO_CYCLE)
        return f"📖 Propuesta añadida: {book['title']} ({book['author']})"

    if step_number == 5:
        books = db_module.get_books(DEMO_CYCLE)
        bar_lines = []
        for index, book in enumerate(books[:4]):
            votes = DEMO_VOTE_DIST[index] if index < len(DEMO_VOTE_DIST) else 0
            for user_index in range(votes):
                db_module.vote_book(book["proposal_id"], f"__demo_user_{index}_{user_index}__")
            filled = "█" * votes
            empty  = "░" * (5 - votes)
            bar_lines.append(f"{index + 1}. <b>{book['title'][:26]}</b>\n   {filled}{empty} {votes} voto{'s' if votes != 1 else ''}")
        poll_text = "🗳 <b>Resultados de la votación (demo)</b>\n\n" + "\n\n".join(bar_lines)
        _tg(run_async, send_to_group and send_to_group(poll_text, parse_mode="HTML"))
        return "Votaciones simuladas y resultados enviados al grupo"

    if step_number == 6:
        for theme_name in DEMO_THEMES:
            db_module.create_theme(theme_name, created_by="__demo__", cycle_key=DEMO_CYCLE)
        themes_text = (
            "💡 <b>Temáticas propuestas (demo)</b>\n\n"
            + "\n".join(f"🏷 {t}" for t in DEMO_THEMES)
            + "\n\n<i>Vota tu favorita en la encuesta del grupo</i>"
        )
        _tg(run_async, send_to_group and send_to_group(themes_text, parse_mode="HTML"))
        return "Temáticas creadas: " + ", ".join(DEMO_THEMES)

    if step_number == 7:
        demo_date = (utcnow() + timedelta(days=12)).replace(hour=19, minute=0, second=0, microsecond=0)
        db_module.create_meeting(
            name="Reunión demo - Club de Lectura",
            final_date=str(demo_date),
            cycle_key=DEMO_CYCLE,
            created_by="__demo__",
        )
        date_str = demo_date.strftime("%d/%m/%Y a las %H:%M")
        _tg(run_async, send_to_group and send_to_group(
            f"📅 <b>Reunión demo confirmada</b>\n\n🗓 {date_str}\n<i>Confirma asistencia con /asistir</i>",
            parse_mode="HTML",
        ))
        return f"Reunión demo creada para {str(demo_date)[:16]} y anunciada en el grupo"

    if step_number == 8:
        books = db_module.get_books(DEMO_CYCLE)
        winner = books[0] if books else None
        if winner:
            winner_text = (
                f"🏆 <b>¡Libro del mes elegido! (demo)</b>\n\n"
                f"📗 <b>{winner['title']}</b>\n"
                f"✍️ {winner.get('author', '')}\n\n"
                f"🗳 {winner.get('votes', 0)} votos — ¡nos vemos en la reunión!"
            )
            _tg(run_async, send_and_pin and send_and_pin(winner_text, parse_mode="HTML"))
            return f"🏆 Ganador: «{winner['title']}» con {winner.get('votes', 0)} votos — mensaje fijado en el grupo"
        return "Sin libros en el demo para proclamar ganador"

    if step_number == 9:
        _demo_cleanup(db_module)
        _tg(run_async, send_to_group and send_to_group(
            "🧹 <b>Demo finalizada</b>\n\nTodos los datos de prueba han sido eliminados. El grupo vuelve a su estado normal.",
            parse_mode="HTML",
        ))
        return "Datos de demo eliminados y grupo notificado"

    return "Demo completada"


def apply_simulator_scenario(db_module, cycle_key, context, scenario_key):
    scenario_key = scenario_key if scenario_key in SIMULATOR_SCENARIOS else "default"
    snapshot = {
        "scenario_key": scenario_key,
        "scenario": SIMULATOR_SCENARIOS[scenario_key],
        "context": deepcopy(context),
        "tied_books": [],
    }
    if scenario_key == "default":
        return snapshot

    winner = deepcopy(snapshot["context"].get("winner"))
    dashboard_state = dict(snapshot["context"].get("dashboard_state") or {})

    if scenario_key == "tie":
        top_books = list(db_module.get_books(cycle_key)[:2])
        if len(top_books) >= 2:
            top_books[0]["votes"] = max(top_books[0].get("votes", 0), 4)
            top_books[1]["votes"] = top_books[0]["votes"]
            snapshot["tied_books"] = top_books
        dashboard_state.update(
            {
                "step": "poll_open",
                "step_label": "Empate pendiente",
                "step_desc": "Hay que resolver un empate antes de anunciar ganador.",
            }
        )
        snapshot["context"]["open_book_polls"] = [{"id": 901, "poll_type": "books"}]
    elif scenario_key == "no_meeting":
        if winner is None:
            books = list(db_module.get_books(cycle_key))
            winner = books[0] if books else {"title": "Libro pendiente", "author": "Club"}
        snapshot["context"]["winner"] = winner
        snapshot["context"]["meeting"] = None
        snapshot["context"]["open_dates_poll"] = None
        dashboard_state.update(
            {
                "step": "awaiting_date",
                "step_label": "Libro listo, falta reunion",
                "step_desc": "Conviene cerrar fecha y comunicarla al grupo.",
            }
        )
    elif scenario_key == "multipart_poll":
        snapshot["context"]["open_book_polls"] = [
            {"id": 1101, "poll_type": "books"},
            {"id": 1102, "poll_type": "books"},
        ]
        dashboard_state.update(
            {
                "step": "poll_open",
                "step_label": "Encuestas abiertas",
                "step_desc": "Hay varias encuestas activas para validar texto, orden y cortes.",
            }
        )
    elif scenario_key == "locked_cycle":
        dashboard_state.update(
            {
                "step": "books",
                "step_label": "Propuestas bloqueadas",
                "step_desc": "El ciclo esta listo para lanzar votacion o revisar incidencias.",
                "proposals_locked": True,
            }
        )

    snapshot["context"]["dashboard_state"] = dashboard_state
    snapshot["context"]["winner"] = winner
    return snapshot


def _demo_cleanup(db_module):
    with db_module.get_cursor(commit=True) as cur:
        cur.execute(
            """DELETE FROM book_votes WHERE proposal_id IN
               (SELECT id FROM book_proposals WHERE cycle_key = %s)""",
            (DEMO_CYCLE,),
        )
        cur.execute("DELETE FROM book_proposals WHERE cycle_key = %s", (DEMO_CYCLE,))
        cur.execute("DELETE FROM themes WHERE cycle_key = %s", (DEMO_CYCLE,))
        cur.execute("DELETE FROM meetings WHERE cycle_key = %s", (DEMO_CYCLE,))
