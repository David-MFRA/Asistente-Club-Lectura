from html import escape as hesc

import db


COMMANDS = {
    "proponer": {"label": "/proponer", "emoji": "📚", "desc": "Proponer un libro", "group": "Participar"},
    "propuestas": {"label": "/propuestas", "emoji": "🗳️", "desc": "Ver y votar libros", "group": "Participar"},
    "votar": {"label": "/votar", "emoji": "✅", "desc": "Votar una propuesta", "group": "Participar"},
    "resultados": {"label": "/resultados", "emoji": "🏆", "desc": "Ver ranking de votos", "group": "Consultar"},
    "tema": {"label": "/tema", "emoji": "🏷️", "desc": "Proponer tematica", "group": "Participar"},
    "temas": {"label": "/temas", "emoji": "🎨", "desc": "Ver y votar tematicas", "group": "Participar"},
    "votar_tema": {"label": "/votar_tema", "emoji": "🗳️", "desc": "Votar tematica", "group": "Participar"},
    "reunion": {"label": "/reunion", "emoji": "📅", "desc": "Ver proxima reunion", "group": "Consultar"},
    "asistir": {"label": "/asistir", "emoji": "🙋", "desc": "Apuntarte a la reunion", "group": "Participar"},
    "noasistir": {"label": "/noasistir", "emoji": "❌", "desc": "Quitarte de la reunion", "group": "Participar"},
    "asistencia": {"label": "/asistencia", "emoji": "👥", "desc": "Ver asistentes", "group": "Consultar"},
    "proponer_fecha": {"label": "/proponer_fecha", "emoji": "🗓️", "desc": "Proponer fecha", "group": "Participar"},
    "libro": {"label": "/libro", "emoji": "📖", "desc": "Ver libro actual", "group": "Consultar"},
    "acta": {"label": "/acta", "emoji": "📝", "desc": "Ver acta de reunion", "group": "Consultar"},
    "progreso": {"label": "/progreso", "emoji": "📈", "desc": "Registrar progreso", "group": "Tu actividad"},
    "estadisticas": {"label": "/estadisticas", "emoji": "📊", "desc": "Tus estadisticas", "group": "Tu actividad"},
    "recomendar": {"label": "/recomendar", "emoji": "💡", "desc": "Recibir recomendaciones", "group": "Extras"},
    "lista_espera": {"label": "/lista_espera", "emoji": "⏳", "desc": "Ver lista de espera", "group": "Consultar"},
    "trivia": {"label": "/trivia", "emoji": "🎲", "desc": "Pregunta para debatir", "group": "Extras"},
    "bug": {"label": "/bug", "emoji": "🐛", "desc": "Reportar un problema", "group": "Ayuda"},
    "admin_ayuda": {"label": "/admin_ayuda", "emoji": "🔐", "desc": "Comandos de admin", "group": "Admin"},
}

GROUP_ORDER = ["Ahora mismo", "Participar", "Consultar", "Tu actividad", "Extras", "Ayuda", "Admin"]


def get_cycle_context(cycle_key=None):
    cycle_key = cycle_key or db.get_current_cycle_key()
    meeting = db.get_latest_scheduled_meeting(cycle_key=cycle_key)
    open_theme_poll = db.get_open_poll("themes", cycle_key=cycle_key)
    open_book_polls = db.get_open_polls("books", cycle_key=cycle_key)
    open_dates_poll = None
    if meeting:
        open_dates_poll = db.get_open_poll("dates", cycle_key=cycle_key, meeting_id=meeting["id"])
    return {
        "cycle": cycle_key,
        "winner": db.get_winner_book(cycle_key),
        "meeting": meeting,
        "dashboard_state": db.get_cycle_dashboard_state(cycle=cycle_key),
        "open_theme_poll": open_theme_poll,
        "open_book_polls": open_book_polls,
        "open_dates_poll": open_dates_poll,
        "latest_meeting": db.get_latest_meeting(),
        "settings": db.get_cycle_bot_settings(cycle_key),
    }


def _base_priority(context):
    if context["open_theme_poll"]:
        return ["temas", "votar_tema", "tema", "recomendar", "bug"]
    if context["open_book_polls"]:
        return ["propuestas", "votar", "resultados", "reunion", "bug"]
    if context["open_dates_poll"]:
        return ["reunion", "proponer_fecha", "asistir", "asistencia", "bug"]
    if context["winner"] and context["meeting"] and context["meeting"].get("final_date"):
        return ["reunion", "asistir", "noasistir", "asistencia", "progreso", "bug"]
    if context["winner"]:
        return ["reunion", "proponer_fecha", "progreso", "libro", "bug"]
    themes = db.get_themes(context["cycle"])
    books = db.get_books(context["cycle"])
    if themes and not books:
        return ["tema", "temas", "proponer", "recomendar", "bug"]
    return ["proponer", "propuestas", "tema", "temas", "reunion", "bug"]


def _context_hidden(context):
    hidden = set()
    if not context["meeting"]:
        hidden.update({"asistir", "noasistir", "asistencia"})
    if not context["meeting"] and not context["winner"]:
        hidden.add("proponer_fecha")
    if not context["winner"]:
        hidden.update({"libro", "progreso"})
    if not context["latest_meeting"] or context["latest_meeting"].get("status") != "closed":
        hidden.add("acta")
    return hidden


def get_contextual_commands(audience="private", cycle_key=None, is_admin=False):
    context = get_cycle_context(cycle_key)
    settings = context["settings"]
    hidden = set(settings.get("hidden_commands") or [])
    hidden.update(_context_hidden(context))
    configured = settings.get("private_highlights" if audience == "private" else "group_highlights") or []
    priority = configured + _base_priority(context)
    seen = []
    for item in priority + list(COMMANDS.keys()):
        if item in COMMANDS and item not in hidden and item not in seen:
            seen.append(item)
    if not is_admin and "admin_ayuda" in seen:
        seen.remove("admin_ayuda")
    if is_admin and "admin_ayuda" not in seen:
        seen.append("admin_ayuda")
    return [dict(COMMANDS[item], id=item) for item in seen]


def build_welcome_text(user_name, is_admin=False, cycle_key=None):
    context = get_cycle_context(cycle_key)
    commands = get_contextual_commands("private", cycle_key, is_admin=is_admin)
    winner = context["winner"]
    meeting = context["meeting"]
    settings = context["settings"]
    lines = [f"📚 Hola, {hesc(user_name)}!"]
    if winner:
        author = f" - {hesc(winner['author'])}" if winner.get("author") else ""
        lines.append(f"\n📖 Ahora mismo estais leyendo <b>{hesc(winner['title'])}</b>{author}.")
    else:
        lines.append(f"\n📖 Todavia no hay libro cerrado para el ciclo <b>{hesc(context['cycle'])}</b>.")
    if meeting:
        date_text = str(meeting["final_date"])[:16] if meeting.get("final_date") else "sin fecha"
        lines.append(f"📅 Proxima reunion: <b>{hesc(meeting['name'])}</b> ({hesc(date_text)})")
    else:
        lines.append("📅 Aun no hay reunion cerrada.")
    lines.append("\n👉 Lo mas util ahora:")
    for command in commands[:5]:
        lines.append(f"{command['emoji']} <b>{command['label']}</b> - {hesc(command['desc'])}")
    if settings.get("context_note"):
        lines.append(f"\n💬 {hesc(settings['context_note'])}")
    if is_admin:
        lines.append("\n🔐 Tienes ademas /admin_ayuda para acciones de gestion.")
    lines.append("\nUsa /ayuda para ver el menu contextual completo.")
    return "\n".join(lines), commands


def build_help_text(is_admin=False, cycle_key=None, audience="private"):
    context = get_cycle_context(cycle_key)
    commands = get_contextual_commands(audience, cycle_key, is_admin=is_admin)
    settings = context["settings"]
    sections = {group: [] for group in GROUP_ORDER}
    highlighted_ids = {item["id"] for item in commands[:5]}
    sections["Ahora mismo"].append(f"Ciclo <b>{hesc(context['cycle'])}</b>: {hesc(context['dashboard_state']['step_label'])}.")
    sections["Ahora mismo"].append(hesc(context["dashboard_state"]["step_desc"]))
    for command in commands:
        marker = "⭐ " if command["id"] in highlighted_ids else ""
        sections.setdefault(command["group"], []).append(f"{marker}<b>{command['label']}</b> - {hesc(command['desc'])}")
    if settings.get("help_note"):
        sections["Ayuda"].append(hesc(settings["help_note"]))
    lines = ["📚 <b>Menu contextual del club</b>"]
    for group in GROUP_ORDER:
        items = [item for item in sections.get(group, []) if item]
        if not items:
            continue
        lines.append(f"\n<b>{group}</b>")
        lines.extend(items)
    return "\n".join(lines)


def build_private_keyboard(commands):
    labels = [f"{item['emoji']} {item['label']}" for item in commands[:6]]
    rows = []
    for index in range(0, len(labels), 2):
        rows.append(labels[index:index + 2])
    return rows


def get_soft_guidance(command_name, cycle_key=None):
    context = get_cycle_context(cycle_key)
    if not context["settings"].get("soft_mode_enabled", True):
        return None
    state = context["dashboard_state"]["step"]
    if command_name in {"asistir", "noasistir", "asistencia"} and not context["meeting"]:
        if context["open_dates_poll"]:
            return "Todavia no hay una reunion cerrada. Ahora mismo esta abierta la votacion de fechas; usa /reunion para ver el estado."
        if context["winner"]:
            return "Ya hay libro ganador, pero aun falta cerrar la fecha de la reunion. Usa /reunion para ver que falta."
        return "Todavia no hay reunion activa. Lo util ahora es seguir el ciclo con /propuestas o /temas."
    if command_name == "proponer" and state == "poll_open":
        if context["open_theme_poll"]:
            return "Ahora mismo se esta votando la tematica. Usa /temas para participar y despues se abriran las propuestas de libros."
        if context["open_book_polls"]:
            return "Las propuestas ya estan cerradas porque la encuesta de libros esta abierta. Usa /propuestas para seguir la votacion."
    if command_name in {"tema", "temas"} and context["winner"]:
        return "La tematica de este ciclo ya esta resuelta. Ahora tiene mas sentido usar /proponer, /propuestas o /reunion."
    if command_name in {"propuestas", "votar", "resultados"} and context["open_theme_poll"]:
        return "Antes de los libros, ahora mismo toca cerrar la tematica del ciclo. Usa /temas para votar."
    if command_name == "proponer_fecha" and not context["winner"]:
        return "Primero hace falta tener libro ganador. Mientras tanto, lo util es participar en /temas o /propuestas."
    return None
