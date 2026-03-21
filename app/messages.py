"""Textos por defecto y helper para templates editables."""

import db


DEFAULT_MESSAGES = {
    "welcome_message": (
        "📚 <b>Bienvenido al Club de Lectura</b>\n\n"
        "Desde aquí puedes proponer libros, seguir reuniones y registrar tu progreso.\n"
        "Las votaciones se hacen en las encuestas fijadas del grupo.\n\n"
        "Si me escribes por privado verás un menú contextual con botones.\n"
        "Usa /ayuda para ver los comandos disponibles."
    ),
    "help_message": (
        "📚 <b>Club de Lectura</b> - Ayuda rápida\n\n"
        "En privado, /ayuda muestra un menú contextual que cambia según la fase del ciclo.\n\n"
        "📖 <b>Libros</b>\n"
        "  /proponer titulo - Proponer un libro\n"
        "  /propuestas - Ver propuestas y el ranking actual\n"
        "  /resultados - Ver el ranking actual\n"
        "  /libro - Ver el libro del ciclo\n\n"
        "🏷️ <b>Temáticas</b>\n"
        "  /tema nombre - Proponer una temática\n"
        "  /temas - Ver temáticas y seguir la encuesta fijada\n\n"
        "🗓️ <b>Reunión</b>\n"
        "  /reunion [texto] - Ver la próxima reunión o buscar una\n"
        "  /asistir - Apuntarte a la reunión\n"
        "  /noasistir - Quitarte de la reunión\n"
        "  /asistencia - Ver asistentes\n"
        "  /acta - Ver el acta de la última reunión\n"
        "  /proponer_fecha DD/MM HH:MM - Proponer fecha\n\n"
        "📊 <b>Tu actividad</b>\n"
        "  /progreso paginas - Registrar tu avance\n"
        "  /estadisticas - Ver tus datos del club\n\n"
        "✨ <b>Extras</b>\n"
        "  /trivia - Pregunta para debatir\n"
        "  /recomendar - Recomendaciones por temática\n"
        "  /lista_espera - Libros en espera\n"
        "  /bug descripcion - Reportar un problema\n\n"
        "🔐 Si eres admin, usa /admin_ayuda. Los comandos /preguntas y /cita son solo para administradores."
    ),
    "next_meeting_message": (
        "🗓️ *{meeting_name}*\n\n"
        "📆 Fecha: {meeting_date}\n"
        "{location_line}"
        "👥 Apuntados: {attendee_count}"
    ),
    "proposal_confirmation_message": (
        "✅ *Libro propuesto* por {user_name}\n\n"
        "📗 {book_title}\n"
        "{author_line}"
        "_Usa /propuestas para seguir el ranking y vota en la encuesta fijada._"
    ),
    "attendance_join_message": "🎉 *{user_name}* se apuntó a *{meeting_name}*\n\n👥 Apuntados ({count}): {names}",
    "attendance_leave_message": "👋 *{user_name}* se ha quitado de *{meeting_name}*\n\n👥 Quedan ({count}): {names}",
    "attendance_prompt_message": "🗓️ ¿A qué reunión te apuntas? Elige una:",
    "theme_chosen_message": (
        "🏷️ <b>Temática elegida: {theme_name}</b>\n\n"
        "Es hora de proponer libros para este ciclo.\n\n"
        "📝 Propón con el comando /proponer\n"
        "💡 Cuantas más propuestas tengamos, mejor saldrá la encuesta."
    ),
    "new_cycle_message": (
        "🔄 <b>Nuevo ciclo: {cycle_name}</b>\n\n"
        "Comienza un nuevo ciclo de lectura. "
        "Primero vamos a <b>elegir la temática</b> que guiará las propuestas."
    ),
    "winner_announcement_message": (
        "🏆 <b>Ya tenemos libro del mes</b>\n\n"
        "📗 <b>{book_title}</b>\n"
        "{author_line}"
        "🗳️ Ganó con <b>{votes} votos</b>\n\n"
        "Usa /asistir para apuntarte a la reunión."
    ),
    "books_open_message": (
        "📚 <b>Hora de proponer libros</b>\n\n"
        "{theme_line}"
        "Propón tus lecturas favoritas para este ciclo:\n"
        "/proponer titulo del libro\n\n"
        "💡 Tienes hasta que el admin cierre las propuestas."
    ),
    "reading_reminder_message": (
        "📖 <b>Recordatorio de lectura</b>\n\n"
        "📗 Libro actual: <b>{book_title}</b>\n"
        "{author_line}"
        "🗓️ Próxima reunión: <b>{meeting_name}</b> ({meeting_date})\n"
        "📊 Te quedan <b>{days_left} días</b> para leer <b>{pages} páginas</b>.\n"
        "Con <b>{daily_pages} páginas al día</b> llegas a tiempo."
    ),
    "meeting_reminder_message": (
        "🗓️ <b>Recordatorio de reunión</b>\n\n"
        "📗 <b>{meeting_name}</b>\n"
        "📍 Fecha: <b>{meeting_date}</b>\n"
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
        "⚖️ <b>Empate en la votación de temática</b>\n\n"
        "Estas temáticas han quedado empatadas:\n"
        "{themes_list}\n\n"
        "🔁 El admin decidirá el siguiente paso."
    ),
    "book_tie_message": (
        "⚖️ <b>Empate en la votación de libros</b>\n\n"
        "Estos libros han quedado empatados con <b>{votes} votos</b>:\n"
        "{books_list}\n\n"
        "🔁 El admin decidirá el siguiente paso."
    ),
    "poll_books_question": "📚 ¿Qué libro leemos este ciclo?",
    "poll_themes_question": "🏷️ ¿Qué temática elegimos para este ciclo?",
    "poll_dates_question": "🗓️ ¿Cuándo nos reunimos? · {meeting_name}",
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
