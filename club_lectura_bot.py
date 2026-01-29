"""
Bot de Telegram para Club de Lectura
Funcionalidades: sugerencias de libros, votaciones, recordatorios, discusiones, estadísticas
"""

import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PollAnswerHandler,
    ContextTypes,
    filters
)
import json
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Archivo para persistencia de datos
DATA_FILE = 'club_data.json'

class ClubLecturaBot:
    def __init__(self):
        self.data = self.cargar_datos()
    
    def cargar_datos(self):
        """Carga los datos desde archivo JSON"""
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            'libros_sugeridos': [],
            'libro_actual': None,
            'libros_leidos': [],
            'proxima_reunion': None,
            'miembros': {},
            'discusiones': [],
            'votaciones_activas': {},
            'citas': []
        }
    
    def guardar_datos(self):
        """Guarda los datos en archivo JSON"""
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

# Instancia global del bot
bot_data = ClubLecturaBot()

# ==================== COMANDOS BÁSICOS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mensaje de bienvenida"""
    user = update.effective_user
    
    # Registrar miembro si no existe
    user_id = str(user.id)
    if user_id not in bot_data.data['miembros']:
        bot_data.data['miembros'][user_id] = {
            'nombre': user.first_name,
            'libros_leidos': 0,
            'participaciones': 0,
            'fecha_union': datetime.now().isoformat()
        }
        bot_data.guardar_datos()
    
    mensaje = f"""
📚 ¡Bienvenido al Club de Lectura, {user.first_name}!

**Comandos disponibles:**

📖 **Gestión de Libros:**
/sugerir - Sugerir un libro para leer
/votacion - Ver votación actual
/libro_actual - Ver información del libro actual
/historial - Ver libros leídos

📅 **Reuniones:**
/proxima_reunion - Ver próxima reunión
/confirmar - Confirmar asistencia
/programar_reunion - Programar nueva reunión (admin)

💬 **Discusión:**
/pregunta - Agregar pregunta para discutir
/preguntas - Ver preguntas pendientes
/cita - Compartir una cita del libro
/citas - Ver citas compartidas

📊 **Estadísticas:**
/mis_stats - Ver tus estadísticas
/ranking - Ver ranking del club

⚙️ **Admin:**
/iniciar_votacion - Crear votación de libros
/finalizar_votacion - Cerrar votación
/seleccionar_libro - Marcar libro como actual
/terminar_libro - Marcar libro como terminado

ℹ️ /ayuda - Ver esta ayuda
"""
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar ayuda detallada"""
    await start(update, context)

# ==================== SUGERENCIAS DE LIBROS ====================

async def sugerir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sugerir un libro para el club"""
    if not context.args:
        await update.message.reply_text(
            "📚 Para sugerir un libro, usa:\n"
            "/sugerir [Título] - [Autor]\n\n"
            "Ejemplo: /sugerir Cien años de soledad - Gabriel García Márquez"
        )
        return
    
    sugerencia = ' '.join(context.args)
    user = update.effective_user
    
    libro = {
        'titulo_autor': sugerencia,
        'sugerido_por': user.first_name,
        'user_id': user.id,
        'fecha': datetime.now().isoformat(),
        'votos': 0
    }
    
    bot_data.data['libros_sugeridos'].append(libro)
    bot_data.guardar_datos()
    
    await update.message.reply_text(
        f"✅ ¡Libro sugerido!\n\n"
        f"📖 {sugerencia}\n"
        f"👤 Sugerido por: {user.first_name}\n\n"
        f"Total de sugerencias: {len(bot_data.data['libros_sugeridos'])}"
    )

# ==================== VOTACIONES ====================

async def iniciar_votacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Iniciar votación para elegir próximo libro"""
    if not bot_data.data['libros_sugeridos']:
        await update.message.reply_text("❌ No hay libros sugeridos para votar.")
        return
    
    # Crear botones para cada libro
    keyboard = []
    for idx, libro in enumerate(bot_data.data['libros_sugeridos']):
        keyboard.append([
            InlineKeyboardButton(
                f"📚 {libro['titulo_autor'][:50]}",
                callback_data=f"vote_{idx}"
            )
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    mensaje = "🗳️ **VOTACIÓN ABIERTA**\n\n"
    mensaje += "Elige el próximo libro del club:\n\n"
    
    for idx, libro in enumerate(bot_data.data['libros_sugeridos'], 1):
        mensaje += f"{idx}. {libro['titulo_autor']}\n"
        mensaje += f"   Sugerido por: {libro['sugerido_por']}\n"
        mensaje += f"   Votos: {libro.get('votos', 0)}\n\n"
    
    await update.message.reply_text(mensaje, reply_markup=reply_markup, parse_mode='Markdown')

async def votar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar votos en la votación"""
    query = update.callback_query
    await query.answer()
    
    # Extraer índice del libro
    idx = int(query.data.split('_')[1])
    user = query.from_user
    
    # Incrementar voto
    if idx < len(bot_data.data['libros_sugeridos']):
        bot_data.data['libros_sugeridos'][idx]['votos'] = \
            bot_data.data['libros_sugeridos'][idx].get('votos', 0) + 1
        bot_data.guardar_datos()
        
        libro = bot_data.data['libros_sugeridos'][idx]
        await query.edit_message_text(
            f"✅ ¡Voto registrado!\n\n"
            f"📚 {libro['titulo_autor']}\n"
            f"Votos totales: {libro['votos']}"
        )

async def votacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ver estado actual de la votación"""
    if not bot_data.data['libros_sugeridos']:
        await update.message.reply_text("📚 No hay libros sugeridos actualmente.")
        return
    
    # Ordenar por votos
    libros_ordenados = sorted(
        bot_data.data['libros_sugeridos'],
        key=lambda x: x.get('votos', 0),
        reverse=True
    )
    
    mensaje = "🗳️ **Estado de la Votación**\n\n"
    for idx, libro in enumerate(libros_ordenados, 1):
        votos = libro.get('votos', 0)
        barra = '█' * votos + '░' * (10 - min(votos, 10))
        mensaje += f"{idx}. {libro['titulo_autor']}\n"
        mensaje += f"   👤 {libro['sugerido_por']}\n"
        mensaje += f"   🗳️ {barra} {votos} votos\n\n"
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def finalizar_votacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalizar votación y anunciar ganador"""
    if not bot_data.data['libros_sugeridos']:
        await update.message.reply_text("❌ No hay votación activa.")
        return
    
    # Encontrar libro con más votos
    ganador = max(bot_data.data['libros_sugeridos'], key=lambda x: x.get('votos', 0))
    
    mensaje = f"🏆 **VOTACIÓN FINALIZADA**\n\n"
    mensaje += f"El libro ganador es:\n\n"
    mensaje += f"📚 **{ganador['titulo_autor']}**\n"
    mensaje += f"👤 Sugerido por: {ganador['sugerido_por']}\n"
    mensaje += f"🗳️ Votos: {ganador.get('votos', 0)}\n\n"
    mensaje += f"Usa /seleccionar_libro para marcarlo como libro actual."
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

# ==================== GESTIÓN DE LIBRO ACTUAL ====================

async def seleccionar_libro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Seleccionar el libro actual del club"""
    if not bot_data.data['libros_sugeridos']:
        await update.message.reply_text("❌ No hay libros sugeridos.")
        return
    
    # Tomar el libro con más votos
    ganador = max(bot_data.data['libros_sugeridos'], key=lambda x: x.get('votos', 0))
    
    bot_data.data['libro_actual'] = {
        **ganador,
        'fecha_inicio': datetime.now().isoformat(),
        'paginas_totales': None,
        'progreso': {}
    }
    
    # Limpiar sugerencias
    bot_data.data['libros_sugeridos'] = []
    bot_data.guardar_datos()
    
    await update.message.reply_text(
        f"📖 **Nuevo libro del club:**\n\n"
        f"📚 {ganador['titulo_autor']}\n"
        f"👤 Sugerido por: {ganador['sugerido_por']}\n\n"
        f"¡Feliz lectura a todos! 📚✨"
    )

async def libro_actual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar información del libro actual"""
    if not bot_data.data['libro_actual']:
        await update.message.reply_text("📚 No hay un libro actual seleccionado.")
        return
    
    libro = bot_data.data['libro_actual']
    fecha_inicio = datetime.fromisoformat(libro['fecha_inicio'])
    dias_leyendo = (datetime.now() - fecha_inicio).days
    
    mensaje = f"📖 **Libro Actual del Club**\n\n"
    mensaje += f"📚 {libro['titulo_autor']}\n"
    mensaje += f"👤 Sugerido por: {libro['sugerido_por']}\n"
    mensaje += f"📅 Inicio: {fecha_inicio.strftime('%d/%m/%Y')}\n"
    mensaje += f"⏳ Días leyendo: {dias_leyendo}\n"
    
    if bot_data.data['proxima_reunion']:
        reunion = datetime.fromisoformat(bot_data.data['proxima_reunion'])
        mensaje += f"\n📅 Próxima reunión: {reunion.strftime('%d/%m/%Y a las %H:%M')}\n"
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def terminar_libro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Marcar libro actual como terminado"""
    if not bot_data.data['libro_actual']:
        await update.message.reply_text("❌ No hay libro actual.")
        return
    
    libro = bot_data.data['libro_actual']
    libro['fecha_fin'] = datetime.now().isoformat()
    
    # Mover a historial
    bot_data.data['libros_leidos'].append(libro)
    bot_data.data['libro_actual'] = None
    
    # Actualizar estadísticas de miembros
    for user_id in bot_data.data['miembros']:
        bot_data.data['miembros'][user_id]['libros_leidos'] += 1
    
    bot_data.guardar_datos()
    
    await update.message.reply_text(
        f"✅ **Libro terminado y añadido al historial**\n\n"
        f"📚 {libro['titulo_autor']}\n\n"
        f"¡Felicitaciones a todos! 🎉\n"
        f"Total de libros leídos: {len(bot_data.data['libros_leidos'])}"
    )

async def historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostrar historial de libros leídos"""
    if not bot_data.data['libros_leidos']:
        await update.message.reply_text("📚 Aún no habéis terminado ningún libro juntos.")
        return
    
    mensaje = "📚 **Historial del Club de Lectura**\n\n"
    
    for idx, libro in enumerate(reversed(bot_data.data['libros_leidos']), 1):
        fecha_fin = datetime.fromisoformat(libro['fecha_fin'])
        mensaje += f"{idx}. {libro['titulo_autor']}\n"
        mensaje += f"   📅 {fecha_fin.strftime('%B %Y')}\n"
        mensaje += f"   👤 {libro['sugerido_por']}\n\n"
    
    mensaje += f"Total: {len(bot_data.data['libros_leidos'])} libros leídos 🎉"
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

# ==================== REUNIONES ====================

async def programar_reunion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Programar próxima reunión"""
    if len(context.args) < 2:
        await update.message.reply_text(
            "📅 Para programar una reunión, usa:\n"
            "/programar_reunion [DD/MM/YYYY] [HH:MM]\n\n"
            "Ejemplo: /programar_reunion 15/02/2026 19:00"
        )
        return
    
    try:
        fecha_str = context.args[0]
        hora_str = context.args[1]
        
        fecha_reunion = datetime.strptime(f"{fecha_str} {hora_str}", "%d/%m/%Y %H:%M")
        bot_data.data['proxima_reunion'] = fecha_reunion.isoformat()
        bot_data.data['confirmaciones'] = []
        bot_data.guardar_datos()
        
        await update.message.reply_text(
            f"✅ **Reunión programada**\n\n"
            f"📅 {fecha_reunion.strftime('%d de %B de %Y')}\n"
            f"🕐 {fecha_reunion.strftime('%H:%M')}\n\n"
            f"Usa /confirmar para confirmar tu asistencia."
        )
        
    except ValueError:
        await update.message.reply_text("❌ Formato de fecha incorrecto. Usa DD/MM/YYYY HH:MM")

async def proxima_reunion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ver información de la próxima reunión"""
    if not bot_data.data.get('proxima_reunion'):
        await update.message.reply_text("📅 No hay reunión programada actualmente.")
        return
    
    reunion = datetime.fromisoformat(bot_data.data['proxima_reunion'])
    dias_faltantes = (reunion - datetime.now()).days
    
    mensaje = f"📅 **Próxima Reunión**\n\n"
    mensaje += f"🗓️ {reunion.strftime('%d de %B de %Y')}\n"
    mensaje += f"🕐 {reunion.strftime('%H:%M')}\n"
    mensaje += f"⏳ Faltan {dias_faltantes} días\n\n"
    
    confirmaciones = bot_data.data.get('confirmaciones', [])
    if confirmaciones:
        mensaje += f"✅ Confirmados ({len(confirmaciones)}):\n"
        for conf in confirmaciones:
            mensaje += f"   • {conf}\n"
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def confirmar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirmar asistencia a la reunión"""
    if not bot_data.data.get('proxima_reunion'):
        await update.message.reply_text("❌ No hay reunión programada.")
        return
    
    user = update.effective_user
    if 'confirmaciones' not in bot_data.data:
        bot_data.data['confirmaciones'] = []
    
    if user.first_name not in bot_data.data['confirmaciones']:
        bot_data.data['confirmaciones'].append(user.first_name)
        bot_data.guardar_datos()
        
        await update.message.reply_text(
            f"✅ ¡Asistencia confirmada, {user.first_name}!\n"
            f"Total confirmados: {len(bot_data.data['confirmaciones'])}"
        )
    else:
        await update.message.reply_text("Ya habías confirmado tu asistencia. 😊")

# ==================== DISCUSIÓN ====================

async def pregunta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Agregar pregunta para discutir"""
    if not context.args:
        await update.message.reply_text(
            "💬 Para agregar una pregunta, usa:\n"
            "/pregunta [tu pregunta]\n\n"
            "Ejemplo: /pregunta ¿Qué opinan del final?"
        )
        return
    
    pregunta_texto = ' '.join(context.args)
    user = update.effective_user
    
    pregunta_obj = {
        'pregunta': pregunta_texto,
        'autor': user.first_name,
        'fecha': datetime.now().isoformat(),
        'respondida': False
    }
    
    bot_data.data['discusiones'].append(pregunta_obj)
    bot_data.guardar_datos()
    
    await update.message.reply_text(
        f"✅ Pregunta añadida:\n\n"
        f"💭 {pregunta_texto}\n"
        f"👤 Por: {user.first_name}"
    )

async def preguntas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ver preguntas pendientes"""
    preguntas_pendientes = [p for p in bot_data.data['discusiones'] if not p['respondida']]
    
    if not preguntas_pendientes:
        await update.message.reply_text("💬 No hay preguntas pendientes.")
        return
    
    mensaje = "💭 **Preguntas para Discutir**\n\n"
    
    for idx, p in enumerate(preguntas_pendientes, 1):
        mensaje += f"{idx}. {p['pregunta']}\n"
        mensaje += f"   👤 {p['autor']}\n\n"
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def cita(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compartir una cita del libro"""
    if not context.args:
        await update.message.reply_text(
            "📝 Para compartir una cita, usa:\n"
            "/cita [texto de la cita]\n\n"
            "Ejemplo: /cita Muchos años después, frente al pelotón de fusilamiento..."
        )
        return
    
    cita_texto = ' '.join(context.args)
    user = update.effective_user
    
    cita_obj = {
        'cita': cita_texto,
        'compartida_por': user.first_name,
        'fecha': datetime.now().isoformat()
    }
    
    bot_data.data['citas'].append(cita_obj)
    bot_data.guardar_datos()
    
    await update.message.reply_text(
        f"📖 **Cita compartida**\n\n"
        f'"{cita_texto}"\n\n'
        f"— Compartida por {user.first_name}"
    )

async def citas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ver citas compartidas"""
    if not bot_data.data['citas']:
        await update.message.reply_text("📝 No hay citas compartidas aún.")
        return
    
    # Mostrar últimas 5 citas
    ultimas_citas = bot_data.data['citas'][-5:]
    
    mensaje = "📚 **Citas Compartidas**\n\n"
    
    for cita in reversed(ultimas_citas):
        mensaje += f'"{cita["cita"]}"\n'
        mensaje += f"— {cita['compartida_por']}\n\n"
    
    mensaje += f"Total de citas: {len(bot_data.data['citas'])}"
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

# ==================== ESTADÍSTICAS ====================

async def mis_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ver estadísticas personales"""
    user = update.effective_user
    user_id = str(user.id)
    
    if user_id not in bot_data.data['miembros']:
        await update.message.reply_text("❌ No estás registrado en el club.")
        return
    
    stats = bot_data.data['miembros'][user_id]
    fecha_union = datetime.fromisoformat(stats['fecha_union'])
    dias_miembro = (datetime.now() - fecha_union).days
    
    mensaje = f"📊 **Tus Estadísticas**\n\n"
    mensaje += f"👤 {user.first_name}\n"
    mensaje += f"📅 Miembro desde: {fecha_union.strftime('%d/%m/%Y')}\n"
    mensaje += f"⏳ Días en el club: {dias_miembro}\n"
    mensaje += f"📚 Libros leídos: {stats['libros_leidos']}\n"
    mensaje += f"💬 Participaciones: {stats.get('participaciones', 0)}\n"
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ver ranking del club"""
    if not bot_data.data['miembros']:
        await update.message.reply_text("📊 No hay miembros registrados.")
        return
    
    # Ordenar por libros leídos
    miembros_ordenados = sorted(
        bot_data.data['miembros'].items(),
        key=lambda x: x[1]['libros_leidos'],
        reverse=True
    )
    
    mensaje = "🏆 **Ranking del Club**\n\n"
    
    emojis = ['🥇', '🥈', '🥉']
    for idx, (user_id, stats) in enumerate(miembros_ordenados[:10], 1):
        emoji = emojis[idx-1] if idx <= 3 else f"{idx}."
        mensaje += f"{emoji} {stats['nombre']}\n"
        mensaje += f"   📚 {stats['libros_leidos']} libros\n\n"
    
    await update.message.reply_text(mensaje, parse_mode='Markdown')

# ==================== FUNCIÓN PRINCIPAL ====================

def main():
    """Iniciar el bot"""
    # Obtener token desde variable de entorno
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not TOKEN:
        print("❌ ERROR: No se encontró el token de Telegram")
        print("Por favor configura la variable de entorno TELEGRAM_BOT_TOKEN")
        print("En Render: Settings > Environment > Add Environment Variable")
        return
    
    # Crear aplicación
    application = Application.builder().token(TOKEN).build()
    
    # Comandos básicos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ayuda", ayuda))
    
    # Sugerencias y votaciones
    application.add_handler(CommandHandler("sugerir", sugerir))
    application.add_handler(CommandHandler("iniciar_votacion", iniciar_votacion))
    application.add_handler(CommandHandler("votacion", votacion))
    application.add_handler(CommandHandler("finalizar_votacion", finalizar_votacion))
    application.add_handler(CallbackQueryHandler(votar_callback, pattern='^vote_'))
    
    # Gestión de libros
    application.add_handler(CommandHandler("seleccionar_libro", seleccionar_libro))
    application.add_handler(CommandHandler("libro_actual", libro_actual))
    application.add_handler(CommandHandler("terminar_libro", terminar_libro))
    application.add_handler(CommandHandler("historial", historial))
    
    # Reuniones
    application.add_handler(CommandHandler("programar_reunion", programar_reunion))
    application.add_handler(CommandHandler("proxima_reunion", proxima_reunion))
    application.add_handler(CommandHandler("confirmar", confirmar))
    
    # Discusión
    application.add_handler(CommandHandler("pregunta", pregunta))
    application.add_handler(CommandHandler("preguntas", preguntas))
    application.add_handler(CommandHandler("cita", cita))
    application.add_handler(CommandHandler("citas", citas))
    
    # Estadísticas
    application.add_handler(CommandHandler("mis_stats", mis_stats))
    application.add_handler(CommandHandler("ranking", ranking))
    
    # Iniciar bot
    print("🤖 Bot iniciado correctamente!")
    print("📚 Club de Lectura Bot funcionando...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()