# Arquitectura

Resumen tecnico del proyecto, pensado para tocar codigo sin perder tiempo reconstruyendo el mapa mental.

## Componentes principales

- `main.py`: punto de entrada. Arranca Flask, Telegram, scheduler y parte del glue legacy.
- `db.py`: acceso a PostgreSQL, inicializacion de tablas, indices y helpers de persistencia.
- `app/bootstrap.py`: arranque compartido de servidor web, webhook y scheduler.
- `app/runtime/jobs.py`: jobs periodicos y recarga de recordatorios personalizados.
- `app/services/`: servicios transversales.
- `app/telegram/`: acceso, callbacks, polling y handlers del bot.
- `app/web/admin/`: rutas y vistas del panel.

## Flujo de arranque

1. `main.py` carga configuracion desde `app/config.py`.
2. Se inicializa logging y se ejecuta `db.init_db()`.
3. Se crean instancias de Telegram, control de acceso, mensajeria, observabilidad y jobs.
4. Se registran handlers del bot.
5. Flask expone rutas publicas, admin y webhook.
6. `app/bootstrap.py` registra webhook, arranca scheduler y levanta Flask en thread dedicado.

## Flujo Telegram

### Mensajes y comandos

1. Telegram envia updates al webhook.
2. `app/telegram/polling.py` valida token y mete el update en la cola de PTB.
3. `app/telegram/registry.py` enruta a handlers de comandos, callbacks o poll answers.
4. Los handlers llaman a `db.py`, servicios o APIs externas.

### Encuestas

1. El panel o los comandos admin lanzan encuestas nativas de Telegram.
2. Se guardan en `telegram_polls` y se mapean opciones.
3. `PollAnswerHandler` procesa respuestas y persiste votos.
4. Al cerrar la encuesta, el panel resuelve ganador o siguiente paso.

## Flujo panel admin

1. Flask sirve rutas sync.
2. Las acciones que necesitan async usan `run_async` para ejecutarse sobre el loop del bot.
3. Las pantallas tiran de `db.py` y de servicios de apoyo como contexto del bot, auditoria y observabilidad.

## Servicios relevantes

- `app/services/bot_context.py`: decide comandos visibles, ayudas suaves y textos contextuales.
- `app/services/admin_guidance.py`: genera guias operativas del panel y previews del bot.
- `app/services/admin_audit.py`: prepara y persiste auditoria admin.
- `app/services/runtime_limits.py`: rate limiting y cache TTL en memoria.
- `app/services/observability.py`: metricas simples de requests, handlers y jobs.

## Persistencia

`db.py` concentra:

- esquema inicial
- indices
- backfills ligeros
- queries por dominio
- utilidades de admin como visor de tablas y SQL manual

Esto funciona, pero hoy no hay sistema de migraciones versionadas separado. Si el esquema sigue creciendo, ese sera uno de los siguientes puntos a extraer.

## Pantallas admin por area

- `routes.py`: registro de rutas Flask.
- `site.py`: ciclo, pagina publica y ayuda.
- `catalog.py`: libros, reuniones, historico, galeria y DB admin.
- `polls.py`: creacion y cierre de encuestas.
- `messaging.py`: mensajes editables, preview y scheduler.
- `insights.py`: buscador, simulador, contexto del bot y alertas.
- `monitoring.py`: logs, bugs y auditoria.

## Donde tocar cada cosa

### Ayuda del bot

- Logica: `app/services/bot_context.py`
- Textos por defecto editables: `app/messages.py`
- Preview admin: `app/web/admin/insights.py` y `templates/admin_bot_context.html`

### Dashboard y guia operativa

- Datos: `app/services/admin_guidance.py`
- Route wiring: `app/web/admin/routes.py`
- Templates: `templates/admin.html`, `templates/admin_ciclo_easy.html`, `templates/admin_help.html`

### Scheduler y recordatorios

- Jobs base: `app/bootstrap.py`
- Jobs runtime y recordatorios custom: `app/runtime/jobs.py`
- Pantalla admin: `app/web/admin/messaging.py` y `templates/admin_scheduler.html`

## Riesgos y tradeoffs actuales

- `main.py` sigue concentrando bastante wiring y codigo legacy.
- `db.py` mezcla esquema y consultas de negocio.
- Parte del rate limit y deduplicacion vive en memoria de proceso.
- Hay herramientas potentes en `/admin/db` que conviene usar con prudencia.

## Verificacion minima al tocar codigo

```powershell
python -m unittest discover -s tests
python -m py_compile main.py db.py app\messages.py app\services\bot_context.py app\services\admin_guidance.py
```
