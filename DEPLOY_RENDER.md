# 🚀 Guía Completa: Desplegar Bot en Render

Esta guía te llevará paso a paso para hospedar tu bot de Telegram en Render **GRATIS** y que funcione 24/7.

---

## 📋 Tabla de Contenidos

1. [Requisitos previos](#requisitos-previos)
2. [Preparar el repositorio](#preparar-el-repositorio)
3. [Crear cuenta en Render](#crear-cuenta-en-render)
4. [Desplegar el bot](#desplegar-el-bot)
5. [Configurar variables de entorno](#configurar-variables-de-entorno)
6. [Verificar que funciona](#verificar-que-funciona)
7. [Solución de problemas](#solución-de-problemas)

---

## 1️⃣ Requisitos Previos

### ✅ Necesitas tener:

1. **Cuenta de GitHub** (gratis) - https://github.com
2. **Cuenta de Render** (gratis) - https://render.com
3. **Token de Telegram** (de @BotFather)

### 🤖 Obtener tu token de Telegram

Si aún no tienes tu bot:

1. Abre Telegram
2. Busca: **@BotFather**
3. Envía: `/newbot`
4. Sigue las instrucciones:
   - Nombre: `Club de Lectura`
   - Username: `TuClubLecturaBot` (debe terminar en 'bot')
5. **Copia el TOKEN** que te da (algo como: `7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsad`)
6. **Guárdalo** - lo necesitarás más tarde

---

## 2️⃣ Preparar el Repositorio

### Opción A: Usar GitHub Desktop (Más fácil)

1. **Descarga GitHub Desktop**: https://desktop.github.com/
2. **Instálalo** y inicia sesión con tu cuenta de GitHub
3. **Crea un nuevo repositorio:**
   - Clic en `File` > `New Repository`
   - Name: `club-lectura-bot`
   - Local Path: Elige dónde guardarlo
   - Clic en `Create Repository`

4. **Copia los archivos del bot:**
   - Abre la carpeta del repositorio (clic en `Show in Explorer/Finder`)
   - Copia TODOS los archivos del bot a esa carpeta:
     - `club_lectura_bot.py`
     - `requirements.txt`
     - `Procfile`
     - `runtime.txt`
     - `.gitignore`
     - `README.md`
     - (NO copies `.env` ni `club_data.json`)

5. **Publica en GitHub:**
   - En GitHub Desktop, verás los archivos en "Changes"
   - Escribe un mensaje: `Primer commit - Bot de club de lectura`
   - Clic en `Commit to main`
   - Clic en `Publish repository`
   - Desmarca "Keep this code private" (o déjalo privado si prefieres)
   - Clic en `Publish Repository`

### Opción B: Usar línea de comandos (Para usuarios avanzados)

```bash
# 1. Crear repositorio en GitHub.com primero
# Ve a github.com > New repository > nombre: club-lectura-bot

# 2. En tu computadora:
cd ruta/a/los/archivos/del/bot

# 3. Inicializar git
git init
git add .
git commit -m "Primer commit - Bot de club de lectura"

# 4. Conectar con GitHub (reemplaza TU_USUARIO)
git remote add origin https://github.com/TU_USUARIO/club-lectura-bot.git
git branch -M main
git push -u origin main
```

---

## 3️⃣ Crear Cuenta en Render

1. Ve a **https://render.com**
2. Clic en **"Get Started"** o **"Sign Up"**
3. **Regístrate con GitHub** (opción más fácil)
4. Autoriza a Render para acceder a tus repositorios

---

## 4️⃣ Desplegar el Bot

### Paso 1: Crear nuevo servicio

1. En el dashboard de Render, clic en **"New +"**
2. Selecciona **"Web Service"**

### Paso 2: Conectar repositorio

1. Busca tu repositorio: `club-lectura-bot`
2. Clic en **"Connect"**

### Paso 3: Configurar el servicio

Rellena los siguientes campos:

**Name:** `club-lectura-bot` (o el nombre que quieras)

**Region:** Selecciona la más cercana a ti:
- `Oregon (US West)` - Para América
- `Frankfurt (EU Central)` - Para Europa
- `Singapore (Southeast Asia)` - Para Asia

**Branch:** `main`

**Runtime:** `Python 3`

**Build Command:** (déjalo vacío o escribe `pip install -r requirements.txt`)

**Start Command:** `python club_lectura_bot.py`

**Instance Type:** **FREE** ⭐

### Paso 4: Scroll hasta el final

⚠️ **IMPORTANTE:** NO hagas clic en "Create Web Service" todavía.

Primero necesitamos configurar la variable de entorno.

---

## 5️⃣ Configurar Variables de Entorno

### Antes de crear el servicio:

1. Scroll hacia abajo hasta encontrar **"Environment Variables"**
2. Clic en **"Add Environment Variable"**
3. Configura lo siguiente:

**Key:** `TELEGRAM_BOT_TOKEN`

**Value:** (pega aquí tu token de Telegram)
```
7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsad
```

4. Ahora sí, clic en **"Create Web Service"**

---

## 6️⃣ Verificar que Funciona

### El proceso de despliegue:

1. Render comenzará a construir tu aplicación
2. Verás logs en tiempo real
3. Busca estos mensajes en los logs:

```
✅ Python 3 encontrado
📦 Instalando dependencias...
✅ Dependencias instaladas correctamente
🤖 Bot iniciado correctamente!
📚 Club de Lectura Bot funcionando...
```

### Probar el bot:

1. Abre Telegram
2. Busca tu bot por su username (ej: `@TuClubLecturaBot`)
3. Envía `/start`
4. Si responde, ¡**FUNCIONA**! 🎉

---

## 🎯 Resumen Visual

```
📁 Tu Computadora
    ↓
    [Archivos del bot]
    ↓
🐙 GitHub
    ↓
    [Repositorio: club-lectura-bot]
    ↓
☁️ Render
    ↓
    [Bot funcionando 24/7]
    ↓
📱 Telegram
    [Tu bot respondiendo]
```

---

## ⚙️ Configuración Adicional (Opcional pero Recomendado)

### Deshabilitar "Auto-Deploy"

Por defecto, cada vez que hagas cambios en GitHub, Render re-desplegará automáticamente. Si quieres control manual:

1. En Render, ve a tu servicio
2. Settings > Build & Deploy
3. Desmarca "Auto-Deploy"

### Configurar Health Check

Para que Render sepa que tu bot está funcionando:

1. Settings > Health & Alerts
2. Health Check Path: déjalo vacío (no es necesario para bots)

### Ver logs en tiempo real

Para ver lo que hace tu bot:

1. En tu servicio de Render
2. Clic en "Logs" en el menú lateral
3. Verás todos los mensajes en tiempo real

---

## 🔄 Actualizar el Bot

### Cuando quieras hacer cambios:

#### Opción A: GitHub Desktop

1. Haz cambios en los archivos locales
2. Abre GitHub Desktop
3. Verás los cambios en "Changes"
4. Escribe descripción del cambio
5. Clic en "Commit to main"
6. Clic en "Push origin"
7. Render re-desplegará automáticamente (si Auto-Deploy está activo)

#### Opción B: Línea de comandos

```bash
# 1. Haz tus cambios en los archivos

# 2. Guarda los cambios
git add .
git commit -m "Descripción de tus cambios"
git push

# 3. Render detectará los cambios y re-desplegará
```

### Re-desplegar manualmente en Render:

1. Ve a tu servicio en Render
2. Clic en "Manual Deploy"
3. Selecciona "Clear build cache & deploy"

---

## 🆓 Limitaciones del Plan Gratuito de Render

### ✅ Lo que tienes:

- **750 horas/mes** de servicio (más que suficiente)
- El bot funciona **24/7**
- **No necesitas tarjeta de crédito**
- Logs completos
- SSL/HTTPS automático

### ⚠️ Limitaciones:

1. **El servicio "duerme" después de 15 minutos de inactividad**
   - Solución: El bot se despierta automáticamente cuando alguien le envía un mensaje
   - Puede tardar 30-60 segundos en responder el primer mensaje después de "despertar"

2. **Los datos se pierden si re-despliegas**
   - `club_data.json` se borra con cada nuevo deploy
   - Solución más adelante: usar una base de datos persistente

---

## 🔧 Solución de Problemas

### Problema 1: "Build failed"

**Síntoma:** El deploy falla en Render

**Soluciones:**
1. Verifica que todos los archivos estén en GitHub:
   - `club_lectura_bot.py`
   - `requirements.txt`
   - `Procfile`
   - `runtime.txt`

2. Verifica el contenido de `requirements.txt`:
   ```
   python-telegram-bot==21.0.1
   python-dotenv==1.0.0
   ```

3. Verifica el contenido de `Procfile`:
   ```
   web: python club_lectura_bot.py
   ```

### Problema 2: El bot no responde

**Síntoma:** El deploy es exitoso pero el bot no responde en Telegram

**Soluciones:**
1. Verifica la variable de entorno:
   - Render > Settings > Environment
   - Debe estar `TELEGRAM_BOT_TOKEN` con tu token

2. Revisa los logs en Render:
   - ¿Dice "Bot iniciado correctamente"?
   - ¿Hay algún error?

3. Verifica el token:
   - Asegúrate de copiar el token completo
   - No debe tener espacios al principio o final

### Problema 3: "Application error" en Render

**Síntoma:** Render muestra error en los logs

**Soluciones:**
1. Lee el error específico en los logs
2. Errores comunes:
   - `Invalid token` → Token incorrecto
   - `Module not found` → Falta algo en `requirements.txt`
   - `Permission denied` → Problema con archivos

### Problema 4: Los datos se pierden

**Síntoma:** Después de re-desplegar, el historial desaparece

**Explicación:** En el plan gratuito, `club_data.json` se borra con cada deploy.

**Solución temporal:** Antes de re-desplegar, descarga `club_data.json` desde los logs o desde el código.

**Solución permanente:** Migrar a una base de datos (ver sección siguiente).

---

## 📊 Usar Base de Datos Persistente (Avanzado)

Para que los datos NO se pierdan entre deploys, puedes usar una base de datos.

### Opción recomendada: PostgreSQL en Render

Render ofrece PostgreSQL gratuito (90 días, luego expira pero puedes crear otro):

1. En Render: New > PostgreSQL
2. Nombre: `club-lectura-db`
3. Clic en "Create Database"
4. Copia la "Internal Database URL"
5. Añádela como variable de entorno en tu servicio

Luego necesitarías modificar el código para usar PostgreSQL en lugar de JSON, pero eso requiere conocimientos más avanzados.

---

## 🎉 ¡Felicidades!

Si llegaste hasta aquí, tu bot debería estar funcionando 24/7 en Render.

### Próximos pasos:

- ✅ Invita a tu grupo de Telegram
- ✅ Empieza a sugerir libros
- ✅ Programa tu primera reunión
- ✅ Disfruta de las lecturas con tus amigos

---

## 📞 Recursos Adicionales

- **Documentación de Render:** https://render.com/docs
- **Soporte de Render:** https://render.com/support
- **Python Telegram Bot:** https://docs.python-telegram-bot.org/
- **Comunidad de Render:** https://community.render.com/

---

## 🔐 Seguridad

### ✅ Buenas prácticas:

1. **NUNCA** subas el token a GitHub
2. Usa variables de entorno siempre
3. El archivo `.gitignore` previene subir datos sensibles
4. Puedes hacer el repositorio privado en GitHub (Settings > Danger Zone)

### 🔒 Verificar seguridad:

```bash
# Buscar en GitHub que no haya tokens expuestos
# Ve a: github.com/TU_USUARIO/club-lectura-bot
# Busca en el código - NO debe aparecer tu token real
```

---

**¿Problemas? ¿Preguntas?**

Revisa esta guía paso a paso o los logs de Render para identificar el error específico.

¡Buena lectura! 📚✨
