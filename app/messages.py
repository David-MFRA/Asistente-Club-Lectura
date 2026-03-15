"""Textos por defecto y helper para templates editables."""

import db

DEFAULT_MESSAGES = {
    "welcome_message": (
        "📚 <b>Bienvenido al Club de Lectura</b>\n\n"
        "Desde aqui puedes proponer libros, votar, seguir reuniones y registrar tu progreso.\n\n"
        "Si me escribes por privado veras un menu contextual con botones.\n"
        "Usa /ayuda para ver los comandos disponibles."
    ),
    "help_message": (
        "📚 <b>Club de Lectura</b> - Ayuda rapida\n\n"
        "En privado, /ayuda muestra un menu contextual que cambia segun la fase del ciclo.\n\n"
        "📖 <b>Libros</b>\n"
        "  /proponer titulo - Proponer un libro\n"
        "  /propuestas - Ver propuestas y votar\n"
        "  /votar N - Votar la propuesta numero N\n"
        "  /resultados - Ver el ranking actual\n"
        "  /libro - Ver el libro del ciclo\n\n"
        "🏷️ <b>Tematicas</b>\n"
        "  /tema nombre - Proponer una tematica\n"
        "  /temas - Ver y votar tematicas\n"
        "  /votar_tema ID - Votar una tematica por ID\n\n"
        "📅 <b>Reunion</b>\n"
        "  /reunion [texto] - Ver la proxima reunion o buscar una\n"
        "  /asistir - Apuntarte a la reunion\n"
        "  /noasistir - Quitarte de la reunion\n"
        "  /asistencia - Ver asistentes\n"
        "  /acta - Ver el acta de la ultima reunion\n"
        "  /proponer_fecha DD/MM HH:MM - Proponer fecha\n\n"
        "📊 <b>Tu actividad</b>\n"
        "  /progreso paginas - Registrar tu avance\n"
        "  /estadisticas - Ver tus datos del club\n\n"
        "✨ <b>Extras</b>\n"
        "  /trivia - Pregunta para debatir\n"
        "  /recomendar - Recomendaciones por tematica\n"
        "  /lista_espera - Libros en espera\n"
        "  /bug descripcion - Reportar un problema\n\n"
        "🔐 Si eres admin, usa /admin_ayuda. Los comandos /preguntas y /cita son solo para administradores."
    ),
    "next_meeting_message": (
        "📅 *{meeting_name}*\n\n"
        "📆 Fecha: {meeting_date}\n"
        "{location_line}"
        "👥 Apuntados: {attendee_count}"
    ),
    "proposal_confirmation_message": (
        "✅ *Libro propuesto* por {user_name}\n\n"
        "📗 {book_title}\n"
        "{author_line}"
        "_Usa /propuestas para votar._"
    ),
    "attendance_join_message": "🎉 *{user_name}* se apunto a *{meeting_name}*\n\n👥 Apuntados ({count}): {names}",
    "attendance_leave_message": "👋 *{user_name}* se ha quitado de *{meeting_name}*\n\n👥 Quedan ({count}): {names}",
    "attendance_prompt_message": "📅 A que reunion te apuntas? Elige una:",
    "theme_chosen_message": (
        "🏷️ <b>Tematica elegida: {theme_name}</b>\n\n"
        "Es hora de proponer libros para este ciclo.\n\n"
        "📝 Propon con el comando /proponer\n"
        "💡 Cuantas mas propuestas tengamos, mejor sera la votacion."
    ),
    "new_cycle_message": (
        "🔄 <b>Nuevo ciclo: {cycle_name}</b>\n\n"
        "Comienza un nuevo ciclo de lectura. "
        "Primero vamos a <b>elegir la tematica</b> que guiara las propuestas."
    ),
    "winner_announcement_message": (
        "🏆 <b>Ya tenemos libro del mes</b>\n\n"
        "📗 <b>{book_title}</b>\n"
        "{author_line}"
        "🗳️ Gano con <b>{votes} votos</b>\n\n"
        "Usa /asistir para apuntarte a la reunion."
    ),
    "books_open_message": (
        "📚 <b>Hora de proponer libros</b>\n\n"
        "{theme_line}"
        "Propon tus lecturas favoritas para este ciclo:\n"
        "/proponer titulo del libro\n\n"
        "💡 Tienes hasta que el admin cierre las propuestas."
    ),
    "reading_reminder_message": (
        "📖 <b>Recordatorio de lectura</b>\n\n"
        "📗 Libro actual: <b>{book_title}</b>\n"
        "{author_line}"
        "📅 Proxima reunion: <b>{meeting_name}</b> ({meeting_date})\n"
        "📊 Te quedan <b>{days_left} dias</b> para leer <b>{pages} paginas</b>.\n"
        "Con <b>{daily_pages} paginas al dia</b> llegas a tiempo."
    ),
    "meeting_reminder_message": (
        "📅 <b>Recordatorio de reunion</b>\n\n"
        "📗 <b>{meeting_name}</b>\n"
        "🗓 Fecha: <b>{meeting_date}</b>\n"
        "{location_line}"
        "👥 Apuntados: <b>{attendee_count}</b>\n"
        "📖 Libro: <b>{book_title}</b>\n\n"
        "✅ /asistir · ❌ /noasistir"
    ),
    "trivia_message": (
        "🎲 <b>Pregunta del club</b>\n\n"
        "{question}\n\n"
        "<i>Responde en el grupo para debatir juntos.</i>"
    ),
    "theme_tie_message": (
        "⚖️ <b>Empate en la votacion de tematica</b>\n\n"
        "Estas tematicas han quedado empatadas:\n"
        "{themes_list}\n\n"
        "🔁 El admin decidira el siguiente paso."
    ),
    "book_tie_message": (
        "⚖️ <b>Empate en la votacion de libros</b>\n\n"
        "Estos libros han quedado empatados con <b>{votes} votos</b>:\n"
        "{books_list}\n\n"
        "🔁 El admin decidira el siguiente paso."
    ),
    "poll_books_question": "📚 Que libro leemos este ciclo?",
    "poll_themes_question": "🏷️ Que tematica elegimos para este ciclo?",
    "poll_dates_question": "📅 Cuando nos reunimos? · {meeting_name}",
}


def get_text(key, **kwargs):
    """Obtiene texto del template (BD o default) y aplica placeholders."""
    phase = kwargs.pop("phase", None)
    audience = kwargs.pop("audience", None)
    cycle_key = kwargs.pop("cycle_key", None)
    template, _resolved_key = db.get_message_template_scoped(
        key,
        phase=phase,
        audience=audience,
        cycle_key=cycle_key,
    )
    if template is None:
        template = DEFAULT_MESSAGES.get(key, "")
    if kwargs:
        try:
            template = template.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return template
