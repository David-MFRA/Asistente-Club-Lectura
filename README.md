# 📚 Bot Club de Lectura

Bot de Telegram para gestionar un club de lectura. Permite proponer y votar libros, organizar reuniones, gestionar asistencia, lanzar encuestas y enviar recordatorios automáticos. Incluye un panel de administración web.

## Funcionalidades

### Bot de Telegram
- Proponer libros (búsqueda automática en Google Books) y votar
- Proponer temáticas y votar
- Ver la próxima reunión, apuntarse o quitarse con botones inline
- Buscar reuniones por nombre o mes (`/reunion abril`)
- Recordatorios automáticos semanales con ritmo de lectura
- Preguntas de debate y citas literarias con IA (Groq)
- Estadísticas personales de cada miembro
- Soporte para múltiples reuniones y encuestas simultáneas

### Panel de administración web (`/admin`)
- Gestión completa de libros, temáticas y reuniones
- Lanzar y cerrar encuestas de Telegram
- Enviar y programar mensajes al grupo
- Editar todos los textos del bot desde el panel
- Historial de mensajes enviados
- Visor y editor de la base de datos
- Histórico de ciclos anteriores
- Generar contenido con IA y enviarlo al grupo
- Fijar mensajes importantes en el grupo

### Flujo guiado del ciclo (dashboard)

El dashboard incluye un wizard que guía al administrador paso a paso:

1. **Iniciar ciclo** → anuncia el nuevo ciclo en el grupo y habilita propuestas
2. **Recoger propuestas** → los miembros usan `/proponer`, admin puede añadir desde el panel
3. **Lanzar encuesta** → cierra propuestas y envía encuesta nativa de Telegram
4. **Cerrar encuesta** → anuncia el ganador automáticamente
5. **Fijar fecha** → directamente o via encuesta de fechas en Telegram
6. **Anunciar fecha** → envía mensaje al grupo con botones de asistencia

---

## Stack técnico

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.10+ |
| Web framework | Flask + ASGI (asgiref + uvicorn) |
| Bot Telegram | python-telegram-bot 20.x (webhook) |
| Base de datos | PostgreSQL (Supabase como backend gestionado) |
| Scheduler | APScheduler (AsyncIOScheduler) |
| Templates | Jinja2 |
| IA (opcional) | Groq API — llama3-8b-8192 |
| Libros | Google Books API |

---

## Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `BOT_TOKEN` | ✅ | Token del bot de Telegram (obtenido de @BotFather) |
| `WEBHOOK_URL` | ✅ | URL pública del servidor, ej. `https://miapp.onrender.com` |
| `DATABASE_URL` | ✅ | Connection string PostgreSQL de Supabase |
| `ADMIN_SECRET` | ✅ | Contraseña para acceder al panel `/admin` |
| `FLASK_SECRET_KEY` | ✅ | Clave secreta para sesiones Flask (string aleatorio largo) |
| `TELEGRAM_CHAT_ID` | ✅ | ID del grupo de Telegram donde opera el bot |
| `ADMIN_TELEGRAM_ID` | ✅ | ID(s) de Telegram de los admins, separados por coma |
| `ALLOWED_CHAT_ID` | ❌ | Si se define, el bot solo responde en ese chat |
| `GROQ_API_KEY` | ❌ | API key de Groq para funciones de IA (gratis en console.groq.com) |
| `PORT` | ❌ | Puerto del servidor (por defecto `10000`) |

---

## Comandos del bot

### Comandos de usuario

| Comando | Descripción |
|---|---|
| `/start` | Mensaje de bienvenida |
| `/ayuda` | Lista de todos los comandos |
| `/proponer <título>` | Proponer un libro (busca en Google Books) |
| `/propuestas` | Ver propuestas del ciclo con botones para votar |
| `/votar <N>` | Votar la propuesta número N |
| `/resultados` | Ranking de votos del ciclo actual |
| `/libro` | Ver el libro ganador del ciclo |
| `/tema <nombre>` | Proponer una temática |
| `/temas` | Ver temáticas con botones para votar |
| `/reunion [texto]` | Ver la próxima reunión (o buscar por nombre/mes) |
| `/asistir` | Apuntarse a la reunión |
| `/noasistir` | Quitarse de la reunión |
| `/asistencia` | Ver lista de asistentes |
| `/acta` | Resumen de la última reunión cerrada |
| `/progreso <páginas>` | Registrar páginas leídas |
| `/estadisticas` | Tus estadísticas en el club |
| `/trivia` | Pregunta aleatoria para el debate |
| `/preguntas` | Generar preguntas de debate con IA |
| `/cita` | Cita del libro (Goodreads o IA) |
| `/recomendar` | Recomendaciones según la temática activa |

### Comandos de administrador

| Comando | Descripción |
|---|---|
| `/admin_ayuda` | Lista de comandos de admin |
| `/ciclo` | Ver el ciclo activo |
| `/nuevo_ciclo [nombre]` | Crear nuevo ciclo |
| `/cerrar_ciclo` | Cerrar el ciclo actual |
| `/anuncio <texto>` | Enviar mensaje libre al grupo |
| `/anunciar_ganador` | Anunciar el libro ganador |
| `/encuesta_libros` | Lanzar encuesta de libros |
| `/encuesta_temas` | Lanzar encuesta de temáticas |
| `/enviar_recordatorio` | Enviar recordatorio de reunión ahora |
| `/enviar_lectura` | Enviar recordatorio de lectura ahora |
| `/fijar` | Fijar recordatorio de reunión en el grupo |
| `/desfijar` | Desfijar el mensaje actual |

---

## Estructura del proyecto

```
bot/
├── main.py              # App Flask + handlers Telegram + schedulers
├── db.py                # Capa de base de datos (PostgreSQL)
├── ai_features.py       # Groq API + scraping Goodreads (citas y preguntas)
├── books_api.py         # Google Books API
├── recommendations.py   # Recomendaciones por temática
├── trivia.py            # Preguntas de debate predefinidas
├── stats.py             # Generación de gráficas (matplotlib)
├── scheduler.py         # (legacy, schedulers en main.py)
├── requirements.txt     # Dependencias Python
└── templates/
    ├── admin.html            # Dashboard principal
    ├── admin_messages.html   # Editor de mensajes del bot
    ├── admin_help.html       # Ayuda interna del admin
    ├── admin_sent_messages.html  # Historial de mensajes
    ├── admin_scheduler.html  # Programador de mensajes
    ├── admin_historico.html  # Histórico de ciclos
    ├── admin_db.html         # Visor de base de datos
    ├── admin_ciclo.html      # Gestión de ciclos
    ├── admin_login.html      # Login del admin
    ├── meetings.html         # Lista de reuniones
    ├── meeting_detail.html   # Detalle de reunión
    ├── themes.html           # Gestión de temáticas
    ├── attendance.html       # Asistencia
    └── ranking.html          # Ranking de libros
```

---

## Esquema de base de datos

| Tabla | Descripción |
|---|---|
| `books` | Catálogo de libros |
| `book_proposals` | Propuestas por ciclo |
| `book_votes` | Votos a propuestas |
| `themes` | Temáticas propuestas |
| `theme_votes` | Votos a temáticas |
| `meetings` | Reuniones (con location, notes) |
| `meeting_date_options` | Opciones de fecha para votación |
| `meeting_date_votes` | Votos de fecha |
| `meeting_attendance` | Asistencia a reuniones |
| `telegram_polls` | Encuestas de Telegram activas |
| `app_config` | Configuración del sistema (clave/valor) |
| `reading_progress` | Progreso de lectura por usuario |
| `message_templates` | Textos del bot personalizados |
| `sent_messages` | Historial de mensajes enviados al grupo |
| `scheduled_messages` | Mensajes programados para envío futuro |

---

## Recordatorios automáticos

| Cuándo | Qué envía |
|---|---|
| Lunes a las 10:00 | Recordatorio semanal: reunión, libro, ritmo de lectura, progreso del grupo |
| Cada 2 días | Recordatorio de lectura con botones para apuntarse |
| Diariamente a las 10:00 | Si la reunión es hoy o mañana, aviso urgente |
| Cada 5 minutos | Comprueba y envía mensajes programados pendientes |

---

## Instalación local

```bash
# Clonar el repositorio
git clone <repo-url>
cd bot

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tus valores

# Arrancar
python main.py
```

> Para desarrollo local el webhook no funcionará desde localhost. Usa [ngrok](https://ngrok.com) para exponer el servidor: `ngrok http 10000` y pon la URL de ngrok como `WEBHOOK_URL`.
