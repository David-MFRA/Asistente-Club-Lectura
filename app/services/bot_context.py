from __future__ import annotations

import re
import unicodedata
from html import escape as hesc

import db


# Este modulo concentra lo que el bot "sabe" sobre el momento actual del club:
# comandos prioritarios, ayudas visibles y preguntas frecuentes que respondemos
# directamente en privado para que el usuario no tenga que memorizar comandos.
COMMANDS = {
    "proponer": {"label": "/proponer", "emoji": "📚", "desc": "Proponer un libro", "group": "Participar"},
    "propuestas": {
        "label": "/propuestas",
        "emoji": "🗳️",
        "desc": "Ver propuestas y el ranking actual",
        "group": "Participar",
    },
    "resultados": {"label": "/resultados", "emoji": "🏆", "desc": "Ver el ranking actual", "group": "Consultar"},
    "tema": {"label": "/tema", "emoji": "🏷️", "desc": "Proponer una temática", "group": "Participar"},
    "temas": {
        "label": "/temas",
        "emoji": "🎨",
        "desc": "Ver temáticas y seguir la encuesta activa",
        "group": "Participar",
    },
    "reunion": {
        "label": "/reunion",
        "emoji": "🗓️",
        "desc": "Ver la próxima reunión o buscar una",
        "group": "Consultar",
    },
    "asistir": {"label": "/asistir", "emoji": "🙋", "desc": "Apuntarte a la reunión", "group": "Participar"},
    "noasistir": {"label": "/noasistir", "emoji": "❌", "desc": "Quitarte de la reunión", "group": "Participar"},
    "asistencia": {"label": "/asistencia", "emoji": "👥", "desc": "Ver asistentes confirmados", "group": "Consultar"},
    "proponer_fecha": {
        "label": "/proponer_fecha",
        "emoji": "🗓️",
        "desc": "Proponer fecha para la reunión",
        "group": "Participar",
    },
    "libro": {"label": "/libro", "emoji": "📖", "desc": "Ver el libro del ciclo", "group": "Consultar"},
    "acta": {"label": "/acta", "emoji": "📝", "desc": "Ver el acta de la última reunión", "group": "Consultar"},
    "progreso": {"label": "/progreso", "emoji": "📈", "desc": "Registrar páginas leídas", "group": "Tu actividad"},
    "estadisticas": {
        "label": "/estadisticas",
        "emoji": "📊",
        "desc": "Ver tu actividad en el club",
        "group": "Tu actividad",
    },
    "recomendar": {
        "label": "/recomendar",
        "emoji": "💡",
        "desc": "Pedir recomendaciones por temática",
        "group": "Extras",
    },
    "lista_espera": {"label": "/lista_espera", "emoji": "⏳", "desc": "Ver libros en espera", "group": "Consultar"},
    "trivia": {"label": "/trivia", "emoji": "🎲", "desc": "Sacar una pregunta para debatir", "group": "Extras"},
    "bug": {"label": "/bug", "emoji": "🐛", "desc": "Reportar un problema al admin", "group": "Ayuda"},
    "admin_ayuda": {"label": "/admin_ayuda", "emoji": "🔐", "desc": "Ver acciones de administración", "group": "Admin"},
}

PRIVATE_SHORTCUT_LABELS = {
    "proponer": "Proponer libro",
    "propuestas": "Ver propuestas",
    "resultados": "Ver ranking",
    "tema": "Proponer tema",
    "temas": "Ver temas",
    "reunion": "Ver reunión",
    "asistir": "Voy a la reunión",
    "noasistir": "No voy",
    "asistencia": "Ver asistentes",
    "proponer_fecha": "Proponer fecha",
    "libro": "Ver libro",
    "acta": "Última acta",
    "progreso": "Registrar progreso",
    "estadisticas": "Mis estadísticas",
    "recomendar": "Recomendarme un libro",
    "lista_espera": "Lista de espera",
    "trivia": "Pregunta para debatir",
    "bug": "Reportar problema",
    "admin_ayuda": "Ayuda admin",
}

GROUP_ORDER = ["Ahora mismo", "Participar", "Consultar", "Tu actividad", "Extras", "Ayuda", "Admin"]

HELP_EXAMPLES = {
    "proponer": "/proponer Dune",
    "propuestas": "/propuestas",
    "tema": "/tema distopias",
    "temas": "/temas",
    "reunion": "/reunion abril",
    "asistir": "/asistir",
    "asistencia": "/asistencia",
    "proponer_fecha": "/proponer_fecha 18/04 19:30",
    "libro": "/libro",
    "acta": "/acta",
    "progreso": "/progreso 120",
    "estadisticas": "/estadisticas",
    "recomendar": "/recomendar",
    "lista_espera": "/lista_espera",
    "trivia": "/trivia",
    "bug": "/bug No encuentro la encuesta fijada del grupo",
}

HELP_QUESTION_HINTS = (
    "como funciona el bot",
    "donde se vota",
    "como proponer un libro",
    "como me apunto",
    "que hago ahora",
    "como reporto un problema",
)


def _normalize_user_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", str(text or "").strip().lower())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = re.sub(r"[^a-z0-9/ ]+", " ", normalized)
    return " ".join(normalized.split())


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
        return ["temas", "tema", "recomendar", "bug"]
    if context["open_book_polls"]:
        return ["propuestas", "resultados", "reunion", "bug"]
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


def _meeting_date_text(meeting):
    if not meeting or not meeting.get("final_date"):
        return "sin fecha cerrada"
    return str(meeting["final_date"])[:16]


def _top_examples(commands, limit=5):
    examples = []
    for command in commands:
        example = HELP_EXAMPLES.get(command["id"])
        if example and example not in examples:
            examples.append(example)
        if len(examples) >= limit:
            break
    return examples


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


def get_private_shortcut_label(command_id: str) -> str:
    return PRIVATE_SHORTCUT_LABELS.get(command_id, COMMANDS.get(command_id, {}).get("desc", command_id))


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
        lines.append(f"🗓️ Proxima reunion: <b>{hesc(meeting['name'])}</b> ({hesc(_meeting_date_text(meeting))})")
    else:
        lines.append("🗓️ Aun no hay reunion cerrada.")
    lines.append("\n👉 Lo mas util ahora:")
    for command in commands[:5]:
        shortcut = get_private_shortcut_label(command["id"])
        lines.append(f"{command['emoji']} <b>{hesc(shortcut)}</b> - {hesc(command['desc'])}")
    lines.append("\nLas votaciones se hacen en las encuestas fijadas del grupo.")
    lines.append("Abajo veras botones rapidos y tambien puedes preguntarme cosas como:")
    for hint in HELP_QUESTION_HINTS[:3]:
        lines.append(f"• <code>{hesc(hint)}</code>")
    if settings.get("context_note"):
        lines.append(f"\n💬 {hesc(settings['context_note'])}")
    if is_admin:
        lines.append("\n🔐 Tambien tienes /admin_ayuda para acciones de gestion.")
    lines.append("\nUsa /ayuda para ver el menu contextual completo.")
    return "\n".join(lines), commands


def build_help_text(is_admin=False, cycle_key=None, audience="private"):
    context = get_cycle_context(cycle_key)
    commands = get_contextual_commands(audience, cycle_key, is_admin=is_admin)
    settings = context["settings"]
    sections = {group: [] for group in GROUP_ORDER}
    highlighted_ids = {item["id"] for item in commands[:5]}
    dashboard_state = context["dashboard_state"]

    sections["Ahora mismo"].append(f"Ciclo <b>{hesc(context['cycle'])}</b>: {hesc(dashboard_state['step_label'])}.")
    sections["Ahora mismo"].append(hesc(dashboard_state["step_desc"]))

    winner = context["winner"]
    if winner:
        author = f" - {hesc(winner['author'])}" if winner.get("author") else ""
        sections["Ahora mismo"].append(f"Libro activo: <b>{hesc(winner['title'])}</b>{author}.")

    meeting = context["meeting"]
    if meeting:
        sections["Ahora mismo"].append(
            f"Proxima reunion: <b>{hesc(meeting['name'])}</b> ({hesc(_meeting_date_text(meeting))})."
        )
    elif context["open_dates_poll"]:
        sections["Ahora mismo"].append("Hay una votacion de fechas abierta para cerrar la reunion.")

    for command in commands:
        marker = "-> " if command["id"] in highlighted_ids else ""
        sections.setdefault(command["group"], []).append(
            f"{marker}<b>{command['label']}</b> - {hesc(command['desc'])}"
        )

    sections["Ayuda"].append("Las votaciones del club se hacen en las encuestas nativas fijadas en el grupo.")
    if audience == "private":
        sections["Ayuda"].append("En privado veras botones rapidos y puedes escribirme preguntas en lenguaje natural.")
    else:
        sections["Ayuda"].append("En el grupo conviene usar comandos cortos para no llenar el chat.")
    sections["Ayuda"].append("Preguntas que entiendo bien:")
    sections["Ayuda"].extend(f"<code>{hesc(item)}</code>" for item in HELP_QUESTION_HINTS)

    examples = _top_examples(commands)
    if examples:
        sections["Ayuda"].append("Ejemplos rapidos:")
        sections["Ayuda"].extend(f"<code>{hesc(example)}</code>" for example in examples)

    if settings.get("help_note"):
        sections["Ayuda"].append(hesc(settings["help_note"]))

    if is_admin:
        sections["Admin"].append("Para encuestas, mensajes y revision operativa grande suele ser mejor usar el panel web.")

    lines = ["📚 <b>Menu contextual del club</b>"]
    for group in GROUP_ORDER:
        items = [item for item in sections.get(group, []) if item]
        if not items:
            continue
        lines.append(f"\n<b>{group}</b>")
        lines.extend(items)
    return "\n".join(lines)


def build_private_keyboard(commands):
    labels = [get_private_shortcut_label(item["id"]) for item in commands[:6]]
    rows = []
    for index in range(0, len(labels), 2):
        rows.append(labels[index:index + 2])
    return rows


def resolve_private_shortcut(text: str) -> str | None:
    normalized = _normalize_user_text(text)
    if normalized == "ayuda":
        return "ayuda"
    for command_id, label in PRIVATE_SHORTCUT_LABELS.items():
        if normalized == _normalize_user_text(label):
            return command_id
    return None


def resolve_private_intent(text: str) -> str | None:
    normalized = _normalize_user_text(text)
    if not normalized:
        return None

    direct_intents = {
        "ayuda": "ayuda",
        "menu": "ayuda",
        "proponer": "proponer",
        "propuestas": "propuestas",
        "tema": "tema",
        "temas": "temas",
        "reunion": "reunion",
        "libro": "libro",
        "asistencia": "asistencia",
        "bug": "bug",
    }
    if normalized in direct_intents:
        return direct_intents[normalized]

    if normalized in {"hola", "buenas", "hello", "hi", "hey", "ola"}:
        return "start"
    if any(fragment in normalized for fragment in ("me apunto", "voy a la reunion", "voy a la reunion del club", "asistire", "voy")):
        return "asistir"
    if any(fragment in normalized for fragment in ("no voy", "me quito", "me desapunto", "no puedo ir")):
        return "noasistir"
    if any(fragment in normalized for fragment in ("proxima reunion", "cuando es la reunion", "cuando es la proxima", "reunion")):
        return "reunion"
    if any(fragment in normalized for fragment in ("que se lee", "que libro", "libro actual", "que estamos leyendo")):
        return "libro"
    if any(fragment in normalized for fragment in ("proponer tema", "tematica", "tema para el club", "quiero proponer tema")):
        return "tema"
    if any(fragment in normalized for fragment in ("quiero proponer un libro", "proponer libro", "quiero proponer", "proponer")):
        return "proponer"
    if any(fragment in normalized for fragment in ("ver asistentes", "quien va", "quienes van", "asistencia")):
        return "asistencia"
    if any(fragment in normalized for fragment in ("ayuda", "menu", "que hago")):
        return "ayuda"
    if any(fragment in normalized for fragment in ("problema", "reportar", "reporto", "bug")):
        return "bug"
    return None


def _build_next_steps(context):
    commands = get_contextual_commands("private", context["cycle"], is_admin=False)
    lines = ["<b>Lo mas util ahora</b>"]
    for command in commands[:3]:
        lines.append(f"• <b>{hesc(get_private_shortcut_label(command['id']))}</b>: {hesc(command['desc'])}")
    if context["open_book_polls"] or context["open_theme_poll"] or context["open_dates_poll"]:
        lines.append("Las votaciones activas estan fijadas en el grupo.")
    return "\n".join(lines)


def answer_help_question(text: str, cycle_key=None) -> str | None:
    normalized = _normalize_user_text(text)
    if not normalized:
        return None

    context = get_cycle_context(cycle_key)
    meeting = context["meeting"]
    winner = context["winner"]

    if any(fragment in normalized for fragment in ("como funciona", "que puedes hacer", "para que sirves")):
        lines = [
            "<b>Como funciona el bot</b>",
            "1. En el grupo se lanzan encuestas nativas para votar tematicas, libros o fechas.",
            "2. En privado puedes proponer libros, consultar la reunion y reportar problemas sin llenar el grupo.",
            "3. Cuando haya reunion, puedes confirmar con /asistir o desde los botones del recordatorio.",
        ]
        if winner:
            lines.append(f"Ahora mismo el libro activo es <b>{hesc(winner['title'])}</b>.")
        return "\n".join(lines)

    if any(fragment in normalized for fragment in ("como voto", "donde se vota", "como se vota", "encuesta")):
        if context["open_book_polls"]:
            return (
                "<b>Votacion de libros</b>\n"
                "La votacion se hace en la encuesta fijada del grupo. Usa /propuestas para ver el ranking "
                "y abre el mensaje fijado para votar."
            )
        if context["open_theme_poll"]:
            return (
                "<b>Votacion de tematicas</b>\n"
                "La votacion se hace en la encuesta fijada del grupo. Usa /temas para ver opciones y el estado actual."
            )
        if context["open_dates_poll"]:
            return (
                "<b>Votacion de fechas</b>\n"
                "La fecha tambien se cierra con una encuesta fijada del grupo. Usa /reunion para ver como va."
            )
        return (
            "<b>Ahora mismo no hay una votacion abierta</b>\n"
            "Cuando el admin lance una encuesta aparecera fijada en el grupo y yo te la recordare en /ayuda."
        )

    if any(fragment in normalized for fragment in ("como propongo", "proponer libro", "quiero proponer")):
        return (
            "<b>Como proponer un libro</b>\n"
            "Pulsa el boton <b>Proponer libro</b> o usa /proponer. Te pedire el titulo, te enseñare la ficha y podras confirmarla."
        )

    if any(fragment in normalized for fragment in ("como propongo tema", "proponer tema", "tematica")):
        return (
            "<b>Como proponer una tematica</b>\n"
            "Pulsa <b>Proponer tema</b> o usa /tema. Te pedire el nombre y podras confirmarlo antes de enviarlo."
        )

    if any(fragment in normalized for fragment in ("como me apunto", "como asistir", "me apunto")):
        if meeting:
            return (
                f"<b>Como confirmar asistencia</b>\n"
                f"La proxima reunion es <b>{hesc(meeting['name'])}</b>. Usa /asistir, /noasistir o los botones del recordatorio."
            )
        return (
            "<b>Aun no hay reunion cerrada</b>\n"
            "Cuando se confirme una fecha podras usar /asistir o los botones del mensaje de reunion."
        )

    if any(fragment in normalized for fragment in ("como me uno", "como entrar", "como unirme", "quiero unirme")):
        return (
            "<b>Como unirte</b>\n"
            "Si ya estas en el club, abre el bot en privado y usa /start. Si aun no estas dentro, pide el enlace de invitacion a un miembro o al admin."
        )

    if any(fragment in normalized for fragment in ("que hago ahora", "que toca ahora", "por donde empiezo")):
        return _build_next_steps(context)

    if any(fragment in normalized for fragment in ("teclado", "botones", "menu rapido", "atajos")):
        return (
            "<b>Como usar los botones</b>\n"
            "En privado veras un teclado con atajos como <b>Proponer libro</b> o <b>Ver reunion</b>. "
            "Para confirmar pasos delicados uso botones dentro del mensaje: <b>Confirmar</b>, <b>Volver</b> y <b>Cancelar</b>."
        )

    if any(fragment in normalized for fragment in ("reportar problema", "reporto un problema", "como reporto", "bug")):
        return (
            "<b>Como reportar un problema</b>\n"
            "Pulsa <b>Reportar problema</b> o usa /bug. Te pedire una descripcion, el area afectada y una confirmacion antes de enviarlo."
        )

    if any(fragment in normalized for fragment in ("que se lee", "que libro actual", "libro actual")) and winner:
        author = f" de {hesc(winner['author'])}" if winner.get("author") else ""
        return f"<b>Libro actual</b>\nAhora mismo estais leyendo <b>{hesc(winner['title'])}</b>{author}."

    if any(fragment in normalized for fragment in ("ayuda", "menu")):
        return build_help_text(is_admin=False, cycle_key=cycle_key, audience="private")

    return None


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
            return "Ahora mismo se esta votando la tematica. Usa /temas para seguir la encuesta y despues se abriran las propuestas de libros."
        if context["open_book_polls"]:
            return "Las propuestas ya estan cerradas porque la encuesta de libros esta abierta. Usa /propuestas para seguir el ranking."
    if command_name in {"tema", "temas"} and context["winner"]:
        return "La tematica de este ciclo ya esta resuelta. Ahora tiene mas sentido usar /proponer, /propuestas o /reunion."
    if command_name in {"propuestas", "resultados"} and context["open_theme_poll"]:
        return "Antes de los libros, ahora mismo toca cerrar la tematica del ciclo. Usa /temas para seguir la encuesta activa."
    if command_name == "proponer_fecha" and not context["winner"]:
        return "Primero hace falta tener libro ganador. Mientras tanto, lo util es participar en /temas o /propuestas."
    return None
