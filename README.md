# 📚 Bot de Telegram para Club de Lectura

Bot completo para gestionar un club de lectura en Telegram con múltiples funcionalidades.

## 🚀 Instalación

### 1. Requisitos previos
- Python 3.8 o superior
- Una cuenta de Telegram
- pip (gestor de paquetes de Python)

### 2. Instalar dependencias

```bash
pip install python-telegram-bot --break-system-packages
```

### 3. Crear tu bot en Telegram

1. Abre Telegram y busca a **@BotFather**
2. Envía el comando `/newbot`
3. Sigue las instrucciones:
   - Elige un nombre para tu bot (ej: "Club de Lectura Los Lectores")
   - Elige un username (debe terminar en 'bot', ej: "ClubLecturaBot")
4. BotFather te dará un **TOKEN** (guárdalo, lo necesitarás)

### 4. Configurar el bot

Abre el archivo `club_lectura_bot.py` y reemplaza esta línea:

```python
TOKEN = 'TU_TOKEN_AQUÍ'
```

Por tu token real:

```python
TOKEN = '1234567890:ABCdefGHIjklMNOpqrsTUVwxyz'
```

### 5. Ejecutar el bot

```bash
python club_lectura_bot.py
```

¡El bot ya está funcionando! Ve a Telegram y búscalo por su username.

---

## 📖 Funcionalidades

### 🔵 Gestión de Libros

**`/sugerir [Título] - [Autor]`**
- Cualquier miembro puede sugerir un libro
- Ejemplo: `/sugerir Cien años de soledad - Gabriel García Márquez`

**`/iniciar_votacion`** (Admin)
- Crea una votación con todos los libros sugeridos
- Los miembros pueden votar haciendo clic en botones

**`/votacion`**
- Ver el estado actual de la votación con barras de progreso

**`/finalizar_votacion`** (Admin)
- Cierra la votación y anuncia el ganador

**`/seleccionar_libro`** (Admin)
- Marca el libro ganador como libro actual del club

**`/libro_actual`**
- Muestra información del libro que están leyendo

**`/terminar_libro`** (Admin)
- Marca el libro como terminado y lo añade al historial

**`/historial`**
- Ver todos los libros que ha leído el club

### 📅 Reuniones

**`/programar_reunion [DD/MM/YYYY] [HH:MM]`** (Admin)
- Programa la próxima reunión
- Ejemplo: `/programar_reunion 15/02/2026 19:00`

**`/proxima_reunion`**
- Ver información de la próxima reunión y confirmaciones

**`/confirmar`**
- Confirmar tu asistencia a la reunión

### 💬 Discusión

**`/pregunta [tu pregunta]`**
- Agregar una pregunta para discutir en la reunión
- Ejemplo: `/pregunta ¿Qué opinan del personaje principal?`

**`/preguntas`**
- Ver todas las preguntas pendientes

**`/cita [texto]`**
- Compartir una cita que te gustó del libro
- Ejemplo: `/cita En un lugar de la Mancha...`

**`/citas`**
- Ver las últimas citas compartidas

### 📊 Estadísticas

**`/mis_stats`**
- Ver tus estadísticas personales (libros leídos, días en el club, etc.)

**`/ranking`**
- Ver el ranking de lectores más activos

### ℹ️ Ayuda

**`/start`** o **`/ayuda`**
- Ver lista completa de comandos

---

## 🎯 Flujo de trabajo típico

### 1️⃣ Inicio de ciclo
Los miembros sugieren libros:
```
/sugerir El principito - Antoine de Saint-Exupéry
/sugerir 1984 - George Orwell
/sugerir Rayuela - Julio Cortázar
```

### 2️⃣ Votación
El administrador inicia la votación:
```
/iniciar_votacion
```
Los miembros votan haciendo clic en los botones.

Ver progreso:
```
/votacion
```

### 3️⃣ Selección
Cerrar votación y anunciar ganador:
```
/finalizar_votacion
```

Marcar como libro actual:
```
/seleccionar_libro
```

### 4️⃣ Programar reunión
```
/programar_reunion 20/02/2026 20:00
```

Los miembros confirman:
```
/confirmar
```

### 5️⃣ Durante la lectura
Compartir citas:
```
/cita "Todo lo que necesitas está ya dentro de ti"
```

Agregar preguntas:
```
/pregunta ¿Por qué creen que el autor eligió ese final?
```

### 6️⃣ Antes de la reunión
Ver preguntas a discutir:
```
/preguntas
```

### 7️⃣ Finalizar
Después de la reunión:
```
/terminar_libro
```

---

## 💾 Persistencia de datos

El bot guarda automáticamente todos los datos en `club_data.json`:
- Libros sugeridos
- Libro actual
- Historial de libros leídos
- Reuniones programadas
- Miembros y sus estadísticas
- Preguntas y citas

**IMPORTANTE:** No borres este archivo o perderás todos los datos del club.

---

## 🔒 Seguridad y permisos

### Comandos de administrador
Algunos comandos están marcados como "Admin" en la documentación. Por ahora, cualquier miembro puede usarlos, pero puedes modificar el código para restringirlos.

Para agregar control de administradores, modifica el código:

```python
# Lista de IDs de administradores (obtén tu ID con /start)
ADMINS = [123456789, 987654321]

async def iniciar_votacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Solo los administradores pueden hacer esto.")
        return
    # ... resto del código
```

---

## 🎨 Personalización

### Cambiar emojis y mensajes
Puedes personalizar fácilmente los mensajes editando el archivo `club_lectura_bot.py`.

### Agregar nuevas funcionalidades
El código está bien estructurado para añadir nuevas funciones:

```python
async def mi_nuevo_comando(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¡Hola!")

# En main():
application.add_handler(CommandHandler("mi_comando", mi_nuevo_comando))
```

---

## 🐛 Solución de problemas

### El bot no responde
- Verifica que el token sea correcto
- Asegúrate de que el script esté ejecutándose
- Revisa que no haya errores en la consola

### Error al instalar python-telegram-bot
```bash
pip install python-telegram-bot --upgrade --break-system-packages
```

### Los datos se pierden
- No borres `club_data.json`
- Haz backups periódicos de este archivo

### El bot se detiene
- Usa un servicio como `systemd`, `supervisor` o ejecútalo en un servidor
- Para desarrollo, simplemente vuelve a ejecutar `python club_lectura_bot.py`

---

## 📱 Características especiales

### ✨ Botones interactivos
- Votación con botones clicables
- Fácil de usar incluso para principiantes

### 📊 Gamificación
- Sistema de ranking
- Estadísticas personales
- Motivación para participar más

### 💾 Sin bases de datos
- Usa archivos JSON simples
- Fácil de respaldar y migrar
- No requiere configuración compleja

### 🔄 Actualizaciones en tiempo real
- Todos los cambios se guardan inmediatamente
- Los miembros ven información actualizada

---

## 🚀 Próximas mejoras posibles

- [ ] Recordatorios automáticos de reuniones
- [ ] Integración con Goodreads
- [ ] Sistema de reseñas
- [ ] Exportar historial a PDF
- [ ] Encuestas de satisfacción
- [ ] Sugerencias de libros basadas en lecturas previas
- [ ] Generación automática de preguntas de discusión
- [ ] Calendario de lectura con metas

---

## 📧 Soporte

Si tienes problemas o sugerencias, puedes:
- Revisar la documentación de python-telegram-bot: https://docs.python-telegram-bot.org/
- Consultar ejemplos en GitHub

---

## 📄 Licencia

Este bot es de uso libre. Siéntete libre de modificarlo y adaptarlo a las necesidades de tu club.

---

¡Disfruta de tu club de lectura automatizado! 📚✨
# Asistente-Club-Lectura
