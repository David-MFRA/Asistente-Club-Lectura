# Guia de despliegue

Guia practica para desplegar el bot en produccion con Render y PostgreSQL gestionado, normalmente Supabase.

## 1. Prepara los servicios externos

### Telegram

1. Crea el bot con `@BotFather`.
2. Guarda `BOT_TOKEN`.
3. Mete el bot en el grupo.
4. Dale permisos de admin si quieres fijar mensajes.

### Base de datos

1. Crea una base PostgreSQL.
2. Copia la URI completa a `DATABASE_URL`.
3. Verifica que el servidor acepta conexiones externas desde Render.

Supabase funciona bien y no necesita SQL manual para el arranque inicial. La app crea tablas e indices al iniciar.

## 2. Variables de entorno

Necesitas al menos estas:

| Variable | Uso |
|---|---|
| `BOT_TOKEN` | Token del bot |
| `WEBHOOK_URL` | URL publica base del servicio |
| `DATABASE_URL` | Conexion PostgreSQL |
| `ADMIN_SECRET` | Clave de acceso al panel |
| `FLASK_SECRET_KEY` | Clave de sesion Flask |
| `WEBHOOK_SECRET_TOKEN` | Token para validar el webhook |
| `TELEGRAM_CHAT_ID` | ID del grupo |
| `ADMIN_TELEGRAM_ID` | IDs de admins separados por coma |

Opcionales:

| Variable | Uso |
|---|---|
| `ALLOWED_CHAT_ID` | Restringe el bot a un chat concreto |
| `GROUP_INVITE_LINK` | Enlace de invitacion para la pagina publica |
| `GROQ_API_KEY` | Habilita IA para preguntas y citas |
| `PORT` | Puerto HTTP, por defecto `10000` |

Puedes partir de `.env.example`.

## 3. Crear el servicio en Render

Configura un Web Service con:

- Runtime: Python 3
- Build Command: `pip install -r requirements.txt`
- Start Command: `python main.py`

Despues carga las variables de entorno reales.

## 4. Valores importantes

- `WEBHOOK_URL` debe ser la URL base publica, sin ruta final.
- `WEBHOOK_SECRET_TOKEN` debe ser un valor aleatorio propio, no una copia de `BOT_TOKEN`.
- `TELEGRAM_CHAT_ID` suele ser negativo en grupos y supergrupos.
- Si usas `ALLOWED_CHAT_ID`, mantenlo alineado con `TELEGRAM_CHAT_ID`.

## 5. Primer arranque

En el primer arranque la app:

1. Abre el pool de conexiones a PostgreSQL.
2. Ejecuta `init_db()` y crea tablas e indices si faltan.
3. Registra el webhook de Telegram en `/webhook`.
4. Arranca el scheduler de recordatorios.
5. Expone Flask en el puerto configurado.

## 6. Verificaciones despues del deploy

Comprueba esto:

- `GET /health` responde `200`.
- `GET /admin` carga el login.
- `GET /` carga la pagina publica.
- El bot responde a `/start`.
- Los logs muestran el webhook registrado.

## 7. Solucion de problemas

### El bot no responde

- Revisa `WEBHOOK_URL`.
- Revisa `WEBHOOK_SECRET_TOKEN`.
- Verifica que el bot sigue en el grupo.
- Mira logs de Render y comprueba `/health`.

### El panel entra pero algunas acciones fallan

- Revisa `DATABASE_URL`.
- Revisa si la base esta pausada o sin conexiones disponibles.
- Comprueba que el servicio arranco sin errores de import o de tabla.

### El grupo migra a supergrupo

- Revisa los logs y `app_config`.
- Actualiza `TELEGRAM_CHAT_ID` y `ALLOWED_CHAT_ID` con el valor definitivo.

### Los recordatorios no salen

- Verifica `TELEGRAM_CHAT_ID`.
- Asegurate de que el bot puede escribir en el grupo.
- Revisa que el servicio no este dormido en un plan gratuito.

## 8. Actualizaciones

Cada despliegue nuevo vuelve a ejecutar el arranque y las migraciones ligeras embebidas en `init_db()`. Aun asi, conviene vigilar cambios grandes en `db.py` porque hoy el proyecto no usa migraciones versionadas separadas.

## 9. URLs utiles

- `/health`: healthcheck
- `/admin`: panel
- `/admin/help`: ayuda operativa
- `/admin/ciclo`: ciclo detallado
- `/admin/ciclo/easy`: vista rapida
- `/webhook`: endpoint de Telegram
