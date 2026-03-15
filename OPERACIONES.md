# Operaciones del club

Guia corta y accionable para operar el bot y el panel sin tener que pensar demasiado donde esta cada cosa.

## Rutas utiles

- `/admin`: dashboard general
- `/admin/ciclo/easy`: vista rapida para el paso actual
- `/admin/ciclo`: vista detallada del ciclo
- `/admin/messages`: mensajes del bot
- `/admin/scheduler`: mensajes programados y recordatorios
- `/admin/logs`: logs operativos
- `/admin/audit`: auditoria del panel
- `/admin/bugs`: incidencias reportadas desde Telegram
- `/admin/bot-context`: highlights y previews de `/start` y `/ayuda`

## Checklist: abrir un ciclo nuevo

1. Entrar en `/admin/ciclo` o `/admin/ciclo/easy`.
2. Crear el ciclo con nombre claro.
3. Anadir al menos 2 tematicas iniciales.
4. Confirmar que se lanza o se puede lanzar la encuesta de tematicas.
5. Revisar en el grupo que el anuncio y la encuesta han salido bien.

## Checklist: cerrar votacion de tematicas

1. Confirmar que la encuesta correcta sigue abierta.
2. Cerrar la encuesta desde el panel.
3. Revisar tema ganador.
4. Abrir fase de propuestas de libros.
5. Si hace falta, comunicar al grupo que ya pueden usar `/proponer`.

## Checklist: lanzar votacion de libros

1. Revisar duplicados o propuestas flojas.
2. Confirmar que hay minimo 2 propuestas.
3. Lanzar encuesta desde el panel.
4. Si hay muchas opciones, comprobar cuantas partes se han creado.
5. No anunciar ganador hasta cerrar todas las partes.

## Checklist: cerrar votacion de libros

1. Cerrar una a una todas las partes abiertas.
2. Revisar si hay empate.
3. Confirmar libro ganador.
4. Pasar a gestion de fecha de reunion.
5. Dejar preparado el anuncio de reunion y asistencia.

## Checklist: fijar fecha de reunion

1. Crear o editar la reunion del ciclo.
2. Elegir entre fecha manual o encuesta de fechas.
3. Cerrar la fecha final.
4. Comunicarla al grupo.
5. Abrir o revisar asistencia.

## Checklist: ciclo en lectura

1. Revisar asistentes y fecha cerrada.
2. Programar o enviar recordatorios.
3. Revisar progreso si el grupo usa `/progreso`.
4. Preparar preguntas o cita si procede.
5. Revisar bugs, logs y mensajes pendientes.

## Checklist: dia de reunion

1. Confirmar lugar y hora.
2. Enviar ultimo recordatorio si hace falta.
3. Revisar asistentes apuntados.
4. Tener a mano acta, cita o preguntas.
5. Despues de la reunion, guardar resumen o acta.

## Checklist: cerrar ciclo

1. Confirmar que no quedan encuestas abiertas.
2. Revisar historico y lista de espera.
3. Cerrar el ciclo desde el panel.
4. Comprobar que el siguiente ciclo queda listo o claramente pendiente.
5. Si hubo incidencias, dejarlas anotadas en bugs o auditoria.

## Incidencias rapidas

### El bot no responde

1. Mirar `/admin/logs`.
2. Comprobar `GET /health`.
3. Revisar webhook y variables de entorno.
4. Confirmar que el bot sigue en el grupo y con permisos.

### No salen recordatorios

1. Revisar `/admin/scheduler`.
2. Confirmar `TELEGRAM_CHAT_ID`.
3. Revisar logs y estado del servicio.
4. Ver si el servicio estaba dormido o sin conectividad.

### La ayuda del bot no refleja el momento del ciclo

1. Revisar ciclo activo y encuestas abiertas.
2. Ir a `/admin/bot-context`.
3. Ver previews de `/start` y `/ayuda`.
4. Ajustar highlights, ocultos o notas.
