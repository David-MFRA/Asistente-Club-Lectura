"""Textos por defecto y helper para templates editables."""

import db

DEFAULT_MESSAGES = {
    "welcome_message": (
        "📚 *¡Bienvenid@ al Club de Lectura!*\n\n"
        "Propón libros, vota, apúntate a reuniones y mucho más.\n\n"
        "Usa /ayuda para ver todos los comandos disponibles. 🚀"
    ),
    "help_message": (
        "📚 *Club de Lectura* - Comandos\n\n"
        "📖 *Libros*\n"
        "  /proponer título - Propone un libro\n"
        "  /propuestas - Lista con botones para votar\n"
        "  /votar N - Vota la propuesta número N\n"
        "  /resultados - Ranking de votos\n"
        "  /libro - Libro del ciclo actual\n\n"
        "🏷️ *Temáticas*\n"
        "  /tema nombre - Propone una temática\n"
        "  /temas - Lista con botones para votar\n\n"
        "📅 *Reunión*\n"
        "  /reunion - Info de la próxima reunión\n"
        "  /asistir - Apuntarse a la reunión\n"
        "  /noasistir - Quitarse de la reunión\n"
        "  /asistencia - Ver asistentes\n"
        "  /acta - Resumen de la última reunión\n\n"
        "📊 *Tu actividad*\n"
        "  /progreso páginas - Registra tu lectura\n"
        "  /estadisticas - Tus estadísticas del club\n\n"
        "🎲 *Extras*\n"
        "  /trivia - Pregunta para el debate\n"
        "  /preguntas - Preguntas de debate con IA\n"
        "  /cita - Cita literaria del libro actual\n"
        "  /recomendar - Libros del tema activo\n"
        "  /lista_espera - Libros en lista de espera\n"
        "  /proponer_fecha DD/MM HH:MM - Proponer fecha de reunión"
    ),
    "next_meeting_message": (
        "📅 *{meeting_name}*\n\n"
        "📆 Fecha: {meeting_date}\n"
        "{location_line}"
        "👥 Apuntados: {attendee_count}"
    ),
    "proposal_confirmation_message": (
        "✅ *¡Libro propuesto!* por {user_name}\n\n"
        "📗 {book_title}\n"
        "{author_line}"
        "_Usa /propuestas para votar._"
    ),
    "attendance_join_message": "🎉 *{user_name}* se apuntó a *{meeting_name}*\n\n👥 Apuntados ({count}): {names}",
    "attendance_leave_message": "👋 *{user_name}* se ha quitado de *{meeting_name}*\n\n👥 Quedan ({count}): {names}",
    "attendance_prompt_message": "📅 ¿A qué reunión te apuntas? Elige una:",
}


def get_text(key, **kwargs):
    """Obtiene texto del template (BD o default) y aplica placeholders."""
    template = db.get_message_template(key)
    if template is None:
        template = DEFAULT_MESSAGES.get(key, "")
    if kwargs:
        try:
            template = template.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return template
