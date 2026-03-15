# Bot Club de Lectura

Bot de Telegram para gestionar un club de lectura con panel web de administracion. Permite proponer y votar libros, lanzar encuestas nativas de Telegram, organizar reuniones, registrar asistencia y progreso de lectura, y operar el ciclo completo desde `/admin`.

## Que hace hoy

### Bot de Telegram
- Propone libros con busqueda en Google Books.
- Vota libros y tematicas desde comandos o encuestas de Telegram.
- Muestra el libro activo, la proxima reunion y el acta anterior.
- Permite confirmar asistencia y registrar progreso de lectura.
- Ofrece ayuda contextual en privado con accesos rapidos.
- Soporta extras como trivia, recomendaciones y reporte de bugs.

### Panel web
- Dashboard con estado del ciclo, alertas y accesos operativos.
- Vista guiada de ciclo en `/admin/ciclo/easy`.
- Gestion completa de libros, tematicas, reuniones y lista de espera.
- Lanzamiento y cierre de encuestas de libros, tematicas y fechas.
- Edicion de mensajes del bot y programacion de envios.
- Auditoria, logs, bugs, buscador administrativo y contexto del bot.
- Pagina publica del club en `/` y editor de su contenido.

## Arquitectura rapida

- `main.py`: arranque principal, glue code y algunas rutas y handlers legacy.
- `db.py`: capa de acceso a PostgreSQL, inicializacion de tablas e indices.
- `app/bootstrap.py`: arranque coordinado de Flask, Telegram y scheduler.
- `app/runtime/jobs.py`: jobs en background y recarga de recordatorios.
- `app/services/`: contexto del bot, auditoria, limites, observabilidad y helpers.
- `app/telegram/`: control de acceso, callbacks, polling y comandos por dominio.
- `app/web/admin/`: rutas y pantallas del panel.

## Requisitos

- Python 3.11 recomendado.
- PostgreSQL accesible desde `DATABASE_URL`.
- Un bot de Telegram creado con BotFather.
- Un webhook publico para produccion. En local puedes usar ngrok.

## Variables de entorno

Las variables importantes son estas:

| Variable | Obligatoria | Uso |
|---|---|---|
| `BOT_TOKEN` | Si | Token del bot de Telegram |
| `WEBHOOK_URL` | Si | URL publica base, por ejemplo `https://miapp.onrender.com` |
| `DATABASE_URL` | Si | Connection string PostgreSQL |
| `ADMIN_SECRET` | Si | Clave para entrar al panel web |
| `FLASK_SECRET_KEY` | Recomendado | Clave de sesion Flask |
| `WEBHOOK_SECRET_TOKEN` | Recomendado | Token secreto para validar el webhook |
| `TELEGRAM_CHAT_ID` | Si | ID del grupo donde opera el bot |
| `ALLOWED_CHAT_ID` | Opcional | Limita respuestas a un chat concreto |
| `ADMIN_TELEGRAM_ID` | Si | IDs de admins separados por coma |
| `GROUP_INVITE_LINK` | Opcional | Enlace publico al grupo o canal |
| `GROQ_API_KEY` | Opcional | Habilita funciones de IA |
| `PORT` | Opcional | Puerto HTTP, por defecto `10000` |

Hay un ejemplo listo en [`.env.example`](/C:/Users/david/OneDrive/Escritorio/bot/.env.example).

## Puesta en marcha local

### 1. Crear entorno e instalar dependencias

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Crear el archivo de entorno

```powershell
Copy-Item .env.example .env
```

Rellena los valores reales antes de arrancar.

### 3. Arrancar la app

```powershell
python main.py
```

La app expone:

- `GET /health`
- `POST /webhook`
- `GET /admin`
- `GET /admin/help`
- `GET /`
- `GET /publico`

### 4. Probar en local con Telegram

Telegram necesita una URL publica para el webhook. En local:

```powershell
ngrok http 10000
```

Despues usa la URL HTTPS de ngrok como `WEBHOOK_URL`.

## Comandos del bot

### Para miembros

- `/start`: bienvenida y accesos rapidos en privado.
- `/ayuda`: menu contextual segun la fase del ciclo.
- `/proponer <titulo>`: proponer un libro.
- `/propuestas`: ver propuestas y botones de voto.
- `/votar <N>`: votar la propuesta numero `N`.
- `/resultados`: ver el ranking actual.
- `/tema <nombre>`: proponer una tematica.
- `/temas`: ver y votar tematicas.
- `/votar_tema <ID>`: votar una tematica concreta.
- `/libro`: ver el libro del ciclo.
- `/reunion [texto]`: ver la proxima reunion o buscar una por nombre o mes.
- `/asistir` y `/noasistir`: gestionar asistencia.
- `/asistencia`: ver asistentes confirmados.
- `/acta`: ver el acta de la ultima reunion cerrada.
- `/proponer_fecha DD/MM HH:MM`: sugerir una fecha.
- `/progreso <paginas>`: registrar paginas leidas.
- `/estadisticas`: ver tu actividad en el club.
- `/trivia`: sacar una pregunta de debate.
- `/recomendar`: pedir recomendaciones por tematica.
- `/lista_espera`: ver libros en espera.
- `/bug <descripcion>`: reportar un problema.

### Solo para administracion

- `/admin_ayuda`: resumen de acciones admin.
- `/ciclo`: estado resumido del ciclo.
- `/nuevo_ciclo [nombre]`: crear un nuevo ciclo.
- `/cerrar_ciclo`: cerrar el ciclo activo.
- `/anuncio <texto>`: enviar un mensaje al grupo.
- `/anunciar_ganador`: publicar el libro ganador.
- `/encuesta_libros`: lanzar la encuesta de libros.
- `/encuesta_temas`: lanzar la encuesta de tematicas.
- `/enviar_recordatorio`: enviar recordatorio de reunion.
- `/enviar_lectura`: enviar recordatorio de lectura.
- `/preguntas`: generar preguntas de debate con IA.
- `/cita`: generar una cita del libro activo.
- `/fijar` y `/desfijar`: fijar o quitar el mensaje fijado del grupo.

## Flujo recomendado del ciclo

1. Crear ciclo desde `/admin/ciclo` o usar el wizard.
2. Votar tematica.
3. Abrir propuestas de libros.
4. Lanzar y cerrar encuesta de libros.
5. Crear reunion y cerrar fecha.
6. Anunciar la fecha y gestionar asistencia.
7. Seguir lectura, recordatorios y acta.
8. Cerrar ciclo y revisar lista de espera.

La vista mas comoda para operar dia a dia es la ruta `/admin/ciclo/easy`.

## Scheduler y jobs

Por defecto se programan estos jobs:

- Lunes 10:00: recordatorio semanal de reunion.
- Cada 2 dias: recordatorio de lectura.
- Diario 10:00: aviso especial si la reunion es hoy o manana.
- Cada 5 minutos: envio de mensajes programados.
- Cada 10 minutos: keep-alive HTTP.

Ademas puedes crear recordatorios personalizados desde `/admin/scheduler`.

## Estructura de proyecto

```text
bot/
|-- main.py
|-- db.py
|-- ai_features.py
|-- books_api.py
|-- recommendations.py
|-- trivia.py
|-- app/
|   |-- bootstrap.py
|   |-- config.py
|   |-- formatting.py
|   |-- messages.py
|   |-- runtime/
|   |-- services/
|   |-- telegram/
|   `-- web/admin/
|-- templates/
|-- static/
`-- tests/
```

## Calidad y verificacion

Tests actuales:

```powershell
python -m unittest discover -s tests
```

Si tocas codigo sensible, merece la pena ejecutar tambien una compilacion rapida:

```powershell
python -m py_compile main.py db.py app\messages.py app\services\bot_context.py
```

## Notas operativas

- El panel web usa Flask threaded y las acciones async pasan por un bridge interno para compartir event loop con Telegram.
- Si `WEBHOOK_SECRET_TOKEN` no esta definido, la app deriva uno desde `BOT_TOKEN`, pero es mejor configurarlo de forma explicita.
- Si `FLASK_SECRET_KEY` no esta definida, la app genera una clave derivada o efimera. Para produccion define una fija.
- Si Telegram migra el grupo a supergrupo, la app intenta detectar el nuevo `chat_id` y guardarlo para diagnostico.
- Hay herramientas potentes en `/admin/db`; conviene reservarlas para mantenimiento y diagnostico.

## Documentacion relacionada

- Despliegue: [DEPLOY.md](/C:/Users/david/OneDrive/Escritorio/bot/DEPLOY.md)
- Ayuda del panel: `/admin/help`
- Pendientes funcionales: `pendiente.txt`
