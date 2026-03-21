from telegram.ext import CallbackQueryHandler, ChatMemberHandler, CommandHandler, MessageHandler, PollAnswerHandler, filters


def register_handlers(telegram_app, handlers):
    """Registra todos los handlers del bot desde un único punto.

    Las votaciones se hacen con encuestas nativas de Telegram, así que aquí
    exponemos solo acciones de consulta, propuestas y asistencia.
    """
    telegram_app.add_handler(CommandHandler("start", handlers["start"]))
    telegram_app.add_handler(CommandHandler("proponer", handlers["proponer"]))
    telegram_app.add_handler(CommandHandler("propuestas", handlers["propuestas"]))
    telegram_app.add_handler(CommandHandler("resultados", handlers["resultados"]))
    telegram_app.add_handler(CommandHandler("reunion", handlers["reunion"]))
    telegram_app.add_handler(CommandHandler("asistir", handlers["asistir"]))
    telegram_app.add_handler(CommandHandler("noasistir", handlers["noasistir"]))
    telegram_app.add_handler(CommandHandler("asistencia", handlers["asistencia"]))
    telegram_app.add_handler(CommandHandler("tema", handlers["tema"]))
    telegram_app.add_handler(CommandHandler("temas", handlers["temas"]))
    telegram_app.add_handler(CommandHandler("trivia", handlers["trivia_cmd"]))
    telegram_app.add_handler(CommandHandler("recomendar", handlers["recomendar"]))
    telegram_app.add_handler(CommandHandler("libro", handlers["libro_cmd"]))
    telegram_app.add_handler(CommandHandler("acta", handlers["acta_cmd"]))
    telegram_app.add_handler(CommandHandler("progreso", handlers["progreso_cmd"]))
    telegram_app.add_handler(CommandHandler("estadisticas", handlers["estadisticas_cmd"]))
    telegram_app.add_handler(CommandHandler("admin_ayuda", handlers["admin_ayuda_cmd"]))
    telegram_app.add_handler(CommandHandler("ciclo", handlers["ciclo_cmd"]))
    telegram_app.add_handler(CommandHandler("nuevo_ciclo", handlers["nuevo_ciclo_cmd"]))
    telegram_app.add_handler(CommandHandler("cerrar_ciclo", handlers["cerrar_ciclo_cmd"]))
    telegram_app.add_handler(CommandHandler("anuncio", handlers["anuncio_cmd"]))
    telegram_app.add_handler(CommandHandler("anunciar_ganador", handlers["anunciar_ganador_cmd"]))
    telegram_app.add_handler(CommandHandler("enviar_recordatorio", handlers["enviar_recordatorio_cmd"]))
    telegram_app.add_handler(CommandHandler("enviar_lectura", handlers["enviar_lectura_cmd"]))
    telegram_app.add_handler(CommandHandler("ayuda", handlers["ayuda_cmd"]))
    telegram_app.add_handler(CommandHandler("encuesta_libros", handlers["encuesta_libros_cmd"]))
    telegram_app.add_handler(CommandHandler("encuesta_temas", handlers["encuesta_temas_cmd"]))
    telegram_app.add_handler(CommandHandler("fijar", handlers["fijar_cmd"]))
    telegram_app.add_handler(CommandHandler("desfijar", handlers["desfijar_cmd"]))
    telegram_app.add_handler(CommandHandler("preguntas", handlers["preguntas_cmd"]))
    telegram_app.add_handler(CommandHandler("cita", handlers["cita_cmd"]))
    telegram_app.add_handler(CommandHandler("lista_espera", handlers["lista_espera_cmd"]))
    telegram_app.add_handler(CommandHandler("proponer_fecha", handlers["proponer_fecha_cmd"]))
    telegram_app.add_handler(CommandHandler("bug", handlers["bug_cmd"]))
    telegram_app.add_handler(
        ChatMemberHandler(
            handlers["handle_my_chat_member"],
            ChatMemberHandler.MY_CHAT_MEMBER,
        )
    )
    telegram_app.add_handler(CallbackQueryHandler(handlers["button_handler"]))
    telegram_app.add_handler(PollAnswerHandler(handlers["handle_poll_answer"]))
    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
            handlers["private_text_handler"],
        )
    )
