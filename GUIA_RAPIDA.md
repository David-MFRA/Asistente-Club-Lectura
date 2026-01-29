# 🎯 GUÍA RÁPIDA DE USO

## 🚀 Inicio Rápido (5 minutos)

### Paso 1: Crear el bot
1. Abre Telegram
2. Busca: **@BotFather**
3. Envía: `/newbot`
4. Nombre: `Club Lectura Tus Amigos`
5. Username: `ClubLecturaTusAmigosBot`
6. **Copia el TOKEN que te da**

### Paso 2: Configurar
```bash
# Edita el archivo
nano club_lectura_bot.py

# Busca esta línea:
TOKEN = 'TU_TOKEN_AQUÍ'

# Reemplázala con tu token:
TOKEN = '7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsad'
```

### Paso 3: Ejecutar
```bash
python3 club_lectura_bot.py
```

### Paso 4: Probar
1. Busca tu bot en Telegram
2. Envía: `/start`
3. ¡Ya funciona! 🎉

---

## 💡 Ejemplos de Uso Real

### Ejemplo 1: Ciclo completo del club

**Semana 1 - Sugerencias**
```
Juan: /sugerir Cien años de soledad - Gabriel García Márquez
María: /sugerir 1984 - George Orwell  
Pedro: /sugerir El amor en los tiempos del cólera - García Márquez
Ana: /sugerir Rayuela - Julio Cortázar
```

**Semana 2 - Votación**
```
Admin: /iniciar_votacion

[El bot muestra botones para votar]

Juan: [Clic en "Cien años de soledad"]
María: [Clic en "1984"]
Pedro: [Clic en "Cien años de soledad"]
Ana: [Clic en "Rayuela"]

Admin: /votacion
Bot muestra:
🗳️ Estado de la Votación

1. Cien años de soledad
   👤 Juan
   🗳️ ██░░░░░░░░ 2 votos

2. 1984
   👤 María
   🗳️ █░░░░░░░░░ 1 voto

3. Rayuela
   👤 Ana
   🗳️ █░░░░░░░░░ 1 voto
```

**Semana 3 - Inicio del libro**
```
Admin: /finalizar_votacion
Bot: 🏆 El libro ganador es: Cien años de soledad

Admin: /seleccionar_libro
Bot: 📖 Nuevo libro del club: Cien años de soledad

Admin: /programar_reunion 20/02/2026 20:00
Bot: ✅ Reunión programada para el 20 de febrero a las 20:00

Juan: /confirmar
María: /confirmar
Pedro: /confirmar
```

**Durante la lectura**
```
María: /cita Muchos años después, frente al pelotón de fusilamiento...
Bot: 📖 Cita compartida: "Muchos años después..."

Pedro: /pregunta ¿Por qué Aureliano no pudo romper la maldición?
Bot: ✅ Pregunta añadida

Ana: /pregunta ¿Qué simboliza el hielo en la novela?
```

**Antes de la reunión**
```
Juan: /proxima_reunion
Bot: 
📅 Próxima Reunión
🗓️ 20 de febrero de 2026
🕐 20:00
⏳ Faltan 2 días

✅ Confirmados (3):
   • Juan
   • María
   • Pedro

Juan: /preguntas
Bot:
💭 Preguntas para Discutir

1. ¿Por qué Aureliano no pudo romper la maldición?
   👤 Pedro

2. ¿Qué simboliza el hielo en la novela?
   👤 Ana
```

**Después de terminar**
```
Admin: /terminar_libro
Bot: ✅ Libro terminado y añadido al historial
📚 Cien años de soledad
¡Felicitaciones a todos! 🎉
Total de libros leídos: 5
```

---

## 📊 Ejemplo: Ver estadísticas

```
Juan: /mis_stats

Bot:
📊 Tus Estadísticas

👤 Juan
📅 Miembro desde: 15/01/2026
⏳ Días en el club: 45
📚 Libros leídos: 5
💬 Participaciones: 12

----

María: /ranking

Bot:
🏆 Ranking del Club

🥇 María
   📚 6 libros

🥈 Juan
   📚 5 libros

🥉 Pedro
   📚 5 libros

4. Ana
   📚 4 libros
```

---

## 🎨 Ejemplo: Conversación natural

```
[Grupo de Telegram del club]

Ana: Acabo de terminar el capítulo 5, ¡qué emocionante!

Pedro: Yo voy por el 3 todavía 😅

Juan: /cita "La tierra tiene la forma de una naranja"

Bot: 📖 Cita compartida
"La tierra tiene la forma de una naranja"
— Compartida por Juan

María: Me encanta esa parte! /pregunta ¿Creen que el autor se inspiró en su propia vida?

Bot: ✅ Pregunta añadida

Ana: /proxima_reunion

Bot:
📅 Próxima Reunión
🗓️ 20 de febrero de 2026
🕐 20:00
⏳ Faltan 5 días

✅ Confirmados (3):
   • Juan
   • María
   • Pedro

Ana: Yo también voy! /confirmar

Bot: ✅ ¡Asistencia confirmada, Ana!
Total confirmados: 4
```

---

## 🔄 Comandos por rol

### 👥 TODOS LOS MIEMBROS pueden:
- `/start` - Unirse al club
- `/sugerir` - Sugerir libros
- `/votacion` - Ver votación
- Votar (mediante botones)
- `/libro_actual` - Ver libro actual
- `/historial` - Ver historial
- `/proxima_reunion` - Ver reunión
- `/confirmar` - Confirmar asistencia
- `/pregunta` - Agregar preguntas
- `/preguntas` - Ver preguntas
- `/cita` - Compartir citas
- `/citas` - Ver citas
- `/mis_stats` - Ver estadísticas propias
- `/ranking` - Ver ranking

### 👑 SOLO ADMINISTRADORES:
- `/iniciar_votacion` - Iniciar votación
- `/finalizar_votacion` - Cerrar votación
- `/seleccionar_libro` - Marcar libro actual
- `/terminar_libro` - Finalizar libro
- `/programar_reunion` - Programar reunión

**Nota:** Por defecto, todos pueden usar comandos admin. Para restringir, ver README.md sección "Seguridad y permisos".

---

## 🎁 Trucos y consejos

### 💡 Consejo 1: Citas rápidas
En lugar de escribir `/cita` cada vez, los miembros pueden copiar y pegar:
```
/cita [pegar texto aquí]
```

### 💡 Consejo 2: Preguntas desde móvil
Escribe la pregunta primero, luego agrega `/pregunta` al inicio:
```
/pregunta ¿Qué opinan del personaje principal en esta escena?
```

### 💡 Consejo 3: Ver progreso rápido
Para ver todo de un vistazo:
```
/libro_actual
/proxima_reunion
/preguntas
```

### 💡 Consejo 4: Motivar participación
Comparte el ranking periódicamente:
```
Administrador: ¡Felicitaciones a María por ser nuestra lectora más activa! 🎉
/ranking
```

### 💡 Consejo 5: Backup de datos
Guarda `club_data.json` regularmente:
```bash
cp club_data.json backup_$(date +%Y%m%d).json
```

---

## ❓ Preguntas frecuentes

**P: ¿El bot funciona 24/7?**
R: Solo mientras el script esté ejecutándose. Para 24/7, necesitas un servidor o VPS.

**P: ¿Puedo tener múltiples clubes?**
R: Sí, crea un bot diferente para cada club (con diferentes tokens).

**P: ¿Se pueden eliminar sugerencias?**
R: Actualmente no, pero puedes editar el archivo `club_data.json` manualmente.

**P: ¿Cuántos miembros soporta?**
R: Ilimitados. Telegram soporta hasta 200,000 miembros en un grupo.

**P: ¿Funciona en grupos de Telegram?**
R: Sí, agrega el bot a tu grupo y funcionará para todos.

**P: ¿Puedo cambiar el diseño de los mensajes?**
R: Sí, editando el código en `club_lectura_bot.py`.

---

## 🆘 Problemas comunes

### Problema: "Invalid token"
**Solución:** Verifica que copiaste el token completo de BotFather.

### Problema: El bot no responde
**Solución:** 
1. Verifica que el script esté ejecutándose
2. Mira si hay errores en la consola
3. Reinicia el bot

### Problema: Los datos desaparecen
**Solución:** 
- No borres `club_data.json`
- Haz backups regularmente

### Problema: Error al votar
**Solución:** 
- Asegúrate de haber ejecutado `/iniciar_votacion` primero
- Verifica que haya libros sugeridos

---

¡Disfruta de tu club de lectura! 📚✨
