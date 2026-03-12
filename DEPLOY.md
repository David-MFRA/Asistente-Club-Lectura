# 🚀 Guía de Despliegue — Render + Supabase

Guía paso a paso para desplegar el bot en producción usando **Supabase** como base de datos y **Render** como servidor.

---

## 1. Configurar Supabase

### 1.1 Crear proyecto

1. Ve a [supabase.com](https://supabase.com) e inicia sesión.
2. Crea un nuevo proyecto (elige una región cercana a Europa).
3. Anota la contraseña de la base de datos — la necesitarás después.

### 1.2 Obtener la connection string

1. En tu proyecto, ve a **Settings → Database**.
2. Baja hasta la sección **Connection string**.
3. Selecciona la pestaña **URI**.
4. Copia la cadena — tiene esta forma:
   ```
   postgresql://postgres:[PASSWORD]@db.xxxxxxxxxxxx.supabase.co:5432/postgres
   ```
5. Reemplaza `[PASSWORD]` con la contraseña que pusiste al crear el proyecto.

> ℹ️ El bot crea todas las tablas automáticamente al arrancar (`init_db()`). No necesitas ejecutar SQL manualmente.

### 1.3 Límites del plan gratuito de Supabase

| Recurso | Límite gratuito |
|---|---|
| Tamaño BD | 500 MB |
| Conexiones simultáneas | 60 |
| RAM | 500 MB |
| Transferencia | 5 GB/mes |
| Proyectos activos | 2 |
| Inactividad | El proyecto se pausa tras 1 semana sin uso |

> ⚠️ Si el proyecto se pausa, reactívalo desde el dashboard de Supabase antes de reiniciar el bot.

---

## 2. Configurar el bot de Telegram

### 2.1 Crear el bot

1. Abre Telegram y busca **@BotFather**.
2. Envía `/newbot` y sigue las instrucciones.
3. Copia el **token** que te da (formato: `1234567890:ABCdef...`).

### 2.2 Obtener el ID del grupo

1. Añade el bot al grupo de Telegram.
2. Envía cualquier mensaje en el grupo.
3. Visita esta URL en el navegador (sustituye el token):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
4. Busca `"chat":{"id":` en la respuesta — ese número negativo es el `TELEGRAM_CHAT_ID`.

### 2.3 Obtener tu ID de Telegram (para ser admin)

1. Busca **@userinfobot** en Telegram.
2. Envíale `/start` — te responderá con tu ID numérico.
3. Ese número es tu `ADMIN_TELEGRAM_ID`.

### 2.4 Hacer el bot administrador del grupo

Para que el bot pueda **fijar mensajes**, necesita ser administrador:

1. En el grupo, ve a **Información del grupo → Administradores → Añadir administrador**.
2. Busca tu bot y añádelo.
3. Activa el permiso **"Fijar mensajes"**.

---

## 3. Desplegar en Render

### 3.1 Crear el servicio

1. Ve a [render.com](https://render.com) e inicia sesión.
2. Crea un nuevo **Web Service**.
3. Conecta tu repositorio de GitHub/GitLab.
4. Configura:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
   - **Plan**: Free (o el que prefieras)

### 3.2 Configurar variables de entorno

En Render, ve a **Environment → Environment Variables** y añade:

| Variable | Valor |
|---|---|
| `BOT_TOKEN` | Token de @BotFather |
| `WEBHOOK_URL` | URL de tu servicio en Render, ej. `https://mi-bot.onrender.com` |
| `DATABASE_URL` | Connection string de Supabase (con contraseña) |
| `ADMIN_SECRET` | Contraseña que quieras para el panel admin (elige una segura) |
| `FLASK_SECRET_KEY` | String aleatorio largo, ej. genera con `python -c "import secrets; print(secrets.token_hex(32))"` |
| `TELEGRAM_CHAT_ID` | ID del grupo de Telegram (número negativo) |
| `ADMIN_TELEGRAM_ID` | Tu ID de Telegram (o varios separados por coma) |
| `GROQ_API_KEY` | *(Opcional)* API key de Groq para funciones de IA |

> ⚠️ Asegúrate de que `WEBHOOK_URL` NO tiene barra final y es exactamente la URL pública de Render.

### 3.3 Primer despliegue

1. Haz clic en **Deploy**. Render instalará las dependencias y arrancará el servidor.
2. Una vez desplegado, el bot registrará automáticamente el webhook con Telegram.
3. Accede al panel admin en `https://tu-app.onrender.com/admin`.

### 3.4 Limitaciones del plan gratuito de Render

| Recurso | Límite gratuito |
|---|---|
| RAM | 512 MB |
| CPU | Compartida |
| Horas de uso | 750 h/mes (suficiente para 1 servicio 24/7) |
| Inactividad | El servicio se duerme tras 15 min sin tráfico |

> ⚠️ En el plan gratuito el servicio se "duerme" si no recibe peticiones durante 15 minutos. El primer mensaje del bot después de ese período tardará ~30 segundos en responder (cold start). Considera el plan **Starter ($7/mes)** para evitarlo.

---

## 4. Obtener GROQ_API_KEY (opcional)

La IA (preguntas de debate, citas literarias) usa Groq, que tiene un plan gratuito generoso.

1. Ve a [console.groq.com](https://console.groq.com).
2. Crea una cuenta gratuita.
3. Ve a **API Keys → Create API Key**.
4. Copia la clave y añádela como `GROQ_API_KEY` en Render.

Sin esta variable el bot funciona igual, pero:
- `/cita` intentará obtener citas de Goodreads (scraping) y si falla usará un texto genérico
- `/preguntas` usará preguntas genéricas predefinidas en lugar de generadas por IA

---

## 5. Verificar el despliegue

Una vez desplegado, comprueba:

- [ ] El bot responde a `/start` en el grupo de Telegram
- [ ] El panel admin es accesible en `/admin`
- [ ] Las tablas se crearon en Supabase (comprueba en **Table Editor**)
- [ ] Los recordatorios automáticos aparecen en los logs de Render

### Ver logs en Render

En Render, ve a tu servicio → **Logs**. Deberías ver algo como:

```
INFO - Application started
INFO - Webhook set to https://tu-app.onrender.com/webhook
INFO - Scheduler started
```

---

## 6. Solución de problemas frecuentes

### El bot no responde a los mensajes

- Comprueba que `WEBHOOK_URL` es correcta y accesible desde internet.
- Verifica que el bot está en el grupo y tiene permisos para leer mensajes.
- Revisa los logs de Render para ver errores.
- Comprueba el webhook manualmente:
  ```
  https://api.telegram.org/bot<TOKEN>/getWebhookInfo
  ```

### Error de conexión a la base de datos

- Verifica que `DATABASE_URL` es correcta y tiene la contraseña incluida.
- Comprueba que el proyecto de Supabase no está pausado.
- En Supabase, ve a **Settings → Database → Connection pooling** y asegúrate de que está activado.

### El servicio se duerme (plan gratuito de Render)

- Normal en el plan gratuito. El primer mensaje tras la inactividad tarda ~30s.
- Para evitarlo: usa un servicio de ping como [UptimeRobot](https://uptimerobot.com) que haga una petición a `/health` cada 10 minutos.

### Los recordatorios no se envían

- Comprueba que `TELEGRAM_CHAT_ID` es el ID correcto del grupo.
- Verifica que el bot tiene permisos para enviar mensajes en el grupo.
- En el plan gratuito, si el servicio está dormido los recordatorios pueden perderse.

---

## 7. Actualizar el bot

Para actualizar el código en producción:

1. Haz push de los cambios a tu repositorio.
2. Render detecta el push automáticamente y redespliega.
3. Las migraciones de BD se ejecutan solas al arrancar (`init_db()` usa `CREATE TABLE IF NOT EXISTS` y `ALTER TABLE` condicionales).

---

## 8. Resumen de URLs importantes

| URL | Descripción |
|---|---|
| `https://tu-app.onrender.com/admin` | Panel de administración |
| `https://tu-app.onrender.com/health` | Health check |
| `https://tu-app.onrender.com/webhook` | Webhook de Telegram (POST) |
| `https://api.telegram.org/bot<TOKEN>/getWebhookInfo` | Estado del webhook |
