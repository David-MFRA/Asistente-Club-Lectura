"""Helpers para guias operativas del panel y previews del bot."""


def _link(label, url, kind="soft"):
    return {"label": label, "url": url, "kind": kind}


def build_dashboard_focus(cycle_state, *, active_cycles=None, alert_count=0):
    if not cycle_state:
        return {
            "eyebrow": "Ahora mismo",
            "title": "No hay ciclo activo",
            "summary": "Crea un ciclo para abrir la primera votacion y empezar a operar el club.",
            "checklist": [
                "Crea el ciclo base desde la vista detallada.",
                "Anade al menos dos tematicas iniciales.",
                "Usa la vista rapida para seguir el siguiente paso.",
            ],
            "links": [
                _link("Abrir ciclo detallado", "/admin/ciclo", "primary"),
                _link("Leer guia operativa", "/admin/help"),
            ],
            "meta": [],
        }

    step = cycle_state.get("step")
    step_label = cycle_state.get("step_label") or "Operacion en curso"
    step_desc = cycle_state.get("step_desc") or "Revisa el estado actual del ciclo."
    step_url = cycle_state.get("step_url") or ""
    step_label_lower = step_label.lower()

    if step == "new_cycle":
        checklist = [
            "Define el nombre del ciclo y las tematicas de salida.",
            "Deja lista la primera encuesta de tematicas.",
            "Comprueba que el grupo recibio el anuncio inicial.",
        ]
    elif step == "collecting_proposals" and "tematic" in step_label_lower:
        checklist = [
            "Revisa que haya al menos dos tematicas viables.",
            "Lanza la encuesta de tematicas cuando el listado ya este limpio.",
            "Ten preparada la siguiente fase: abrir propuestas de libros.",
        ]
    elif step == "collecting_proposals":
        checklist = [
            "Revisa duplicados o propuestas flojas antes de votar.",
            "Espera a tener al menos dos propuestas publicables.",
            "Cuando cierres propuestas, lanza la encuesta de libros.",
        ]
    elif step == "poll_open" and "tematic" in step_label_lower:
        checklist = [
            "Deja que la encuesta gane traccion en Telegram.",
            "Cierra la votacion cuando haya participacion suficiente.",
            "Confirma la tematica ganadora y abre propuestas de libros.",
        ]
    elif step == "poll_open":
        checklist = [
            "Comprueba que todas las partes de la encuesta sigan abiertas.",
            "Cierra la votacion cuando el resultado sea estable.",
            "Despues revisa ganador, fecha y mensaje al grupo.",
        ]
    elif step == "dates_poll_open":
        checklist = [
            "Espera a que el grupo vote las opciones de fecha.",
            "Cierra la encuesta cuando haya una opcion clara.",
            "Publica la fecha final y abre asistencia.",
        ]
    elif step == "awaiting_date":
        checklist = [
            "Crea o revisa la reunion del ciclo.",
            "Decide si fijar fecha manualmente o abrir encuesta.",
            "No dejes la asistencia para despues de comunicar la fecha.",
        ]
    elif step == "meeting_scheduled":
        checklist = [
            "Anuncia la fecha al grupo si aun no se ha hecho.",
            "Revisa asistentes y programa recordatorios.",
            "Deja preparados mensajes de lectura o debate.",
        ]
    else:
        checklist = [
            "Revisa el estado del ciclo en la vista detallada.",
            "Comprueba logs, mensajes y reuniones relacionadas.",
            "Usa la guia operativa si vas a tocar una fase manualmente.",
        ]

    links = []
    if step_url and not str(step_url).startswith("#"):
        links.append(_link(cycle_state.get("step_action") or "Siguiente accion", step_url, "primary"))
    links.extend(
        [
            _link("Vista rapida del ciclo", "/admin/ciclo/easy"),
            _link("Ciclo detallado", "/admin/ciclo"),
            _link("Guia operativa", "/admin/help"),
        ]
    )
    if alert_count:
        links.append(_link("Revisar logs y alertas", "/admin/logs"))

    meta = []
    if active_cycles:
        meta.append(f"{len(active_cycles)} ciclo(s) activo(s)")
    if alert_count:
        meta.append(f"{alert_count} alerta(s) por revisar")
    if cycle_state.get("winner"):
        meta.append(f"Libro activo: {cycle_state['winner']['title']}")

    return {
        "eyebrow": "Ahora mismo",
        "title": step_label,
        "summary": step_desc,
        "checklist": checklist,
        "links": links,
        "meta": meta,
    }


def build_cycle_easy_guidance(cycle):
    if not cycle:
        return {
            "title": "Sin ciclo activo",
            "summary": "Crea un ciclo y vuelve a esta vista para operar por fases.",
            "checklist": [
                "Abre la vista detallada del ciclo.",
                "Crea el ciclo base con nombre y tematicas.",
                "Vuelve aqui para seguir el paso recomendado.",
            ],
            "links": [
                _link("Abrir ciclo detallado", "/admin/ciclo", "primary"),
                _link("Leer ayuda", "/admin/help"),
            ],
        }

    phase = cycle.get("phase")
    if phase == "setup":
        title = "Preparar el ciclo"
        summary = "Antes de abrir la participacion, deja el ciclo y las tematicas iniciales bien definidos."
        checklist = [
            "Confirma nombre y tematicas de salida.",
            "Verifica que el grupo recibira la primera encuesta.",
            "Usa la vista detallada si necesitas tocar datos base.",
        ]
    elif phase == "theme_voting":
        title = "Cerrar tematica"
        summary = "Ahora mismo toca vigilar la encuesta de tematicas y preparar la apertura de propuestas."
        checklist = [
            "Comprueba que la encuesta correcta sigue abierta.",
            "Cierra cuando haya suficiente participacion.",
            "Al resolverla, abre propuestas de libros.",
        ]
    elif phase == "books":
        title = "Curar propuestas"
        summary = "Esta fase suele atascarse si entran pocas propuestas o hay duplicados."
        checklist = [
            "Anade propuestas manuales si el grupo se queda corto.",
            "Limpia duplicados antes de abrir votacion.",
            "No lances la encuesta con menos de dos opciones viables.",
        ]
    elif phase == "book_voting":
        title = "Resolver el libro ganador"
        summary = "La prioridad es cerrar todas las partes abiertas y dejar ganador claro."
        checklist = [
            "Cierra cada parte de la encuesta una a una.",
            "Comprueba si hay empate o ganador directo.",
            "Despues pasa a fecha de reunion sin dejar huecos.",
        ]
    elif phase == "date_voting":
        title = "Cerrar la fecha de reunion"
        summary = "Ya hay libro. Falta cerrar fecha y comunicarla con claridad."
        checklist = [
            "Revisa o crea la reunion del ciclo.",
            "Decide si fijar fecha a mano o votar.",
            "Anuncia la fecha final y abre asistencia.",
        ]
    elif phase == "reading":
        title = "Acompanhar la lectura"
        summary = "Con el ciclo en marcha, lo importante es mantener ritmo y preparacion de la reunion."
        checklist = [
            "Envia recordatorios cuando toque.",
            "Revisa asistentes y progreso general.",
            "Prepara preguntas, cita o materiales de reunion.",
        ]
    else:
        title = "Revisar fase"
        summary = "La fase actual necesita validacion manual."
        checklist = [
            "Comprueba el estado en la vista detallada.",
            "Mira logs y mensajes si algo no encaja.",
            "Usa la guia operativa para la siguiente decision.",
        ]

    links = [
        _link("Abrir ciclo detallado", "/admin/ciclo"),
        _link("Mensajes", "/admin/messages"),
        _link("Guia operativa", "/admin/help"),
    ]
    if cycle.get("meeting"):
        links.insert(1, _link("Abrir reunion", f"/meeting/{cycle['meeting']['id']}"))

    return {
        "title": title,
        "summary": summary,
        "checklist": checklist,
        "links": links,
    }


def build_bot_context_previews(cycle_key):
    from app.services.bot_context import (
        build_help_text,
        build_welcome_text,
        get_contextual_commands,
        get_cycle_context,
    )

    context = get_cycle_context(cycle_key)
    member_welcome, member_start_commands = build_welcome_text("Marta", is_admin=False, cycle_key=cycle_key)
    admin_welcome, admin_start_commands = build_welcome_text("Marta Admin", is_admin=True, cycle_key=cycle_key)
    member_help = build_help_text(is_admin=False, cycle_key=cycle_key, audience="private")
    group_help = build_help_text(is_admin=False, cycle_key=cycle_key, audience="group")
    admin_help = build_help_text(is_admin=True, cycle_key=cycle_key, audience="private")

    snapshot = {
        "cycle": context["cycle"],
        "step_label": context["dashboard_state"]["step_label"],
        "winner": (context["winner"] or {}).get("title"),
        "meeting": (context["meeting"] or {}).get("name"),
    }

    cards = [
        {
            "title": "Miembro /start",
            "description": "Mensaje de bienvenida y accesos rapidos en privado.",
            "text": member_welcome,
            "commands": [item["label"] for item in member_start_commands[:5]],
        },
        {
            "title": "Miembro /ayuda privado",
            "description": "Ayuda contextual principal para una persona normal del club.",
            "text": member_help,
            "commands": [item["label"] for item in get_contextual_commands("private", cycle_key, is_admin=False)[:6]],
        },
        {
            "title": "Miembro /ayuda grupo",
            "description": "Resumen que se ve en grupo, pensado para no saturar el chat.",
            "text": group_help,
            "commands": [item["label"] for item in get_contextual_commands("group", cycle_key, is_admin=False)[:6]],
        },
        {
            "title": "Admin /start y /ayuda",
            "description": "Vista privada con comandos de gestion disponibles para admins.",
            "text": admin_welcome + "\n\n---\n\n" + admin_help,
            "commands": [item["label"] for item in admin_start_commands[:6]],
        },
    ]

    return {"snapshot": snapshot, "cards": cards}
