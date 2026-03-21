import uuid

from flask import flash, redirect, render_template, request, session, url_for
from urllib.parse import urlparse


def _safe_next(default_endpoint: str) -> str:
    """Devuelve el valor de _next solo si apunta a una ruta interna (mismo host).
    Previene open-redirect: un atacante no puede redirigir al admin a un dominio externo."""
    raw = request.form.get("_next", "")
    if raw:
        parsed = urlparse(raw)
        # Permitido: rutas relativas (sin scheme/netloc) o mismo host explícito
        if not parsed.scheme and not parsed.netloc:
            return raw
    return url_for(default_endpoint)

import books_api
import db
from app.services.admin_guidance import build_cycle_easy_guidance, build_dashboard_focus
from app.services.input_limits import (
    InputValidationError,
    normalize_admin_search_query,
    normalize_book_query,
    normalize_theme_name,
    truncate_search_query,
)
from app.web.admin.ai import (
    ask_admin_ai,
    render_ai_questions,
    render_ai_quote,
    render_manual_quote,
    send_ai_questions,
    send_ai_quote,
)
from app.web.admin.catalog import (
    add_meeting_date_option,
    add_waitlist_entry,
    close_meeting_date,
    create_meeting as create_meeting_page,
    delete_db_row,
    delete_meeting as delete_meeting_page,
    delete_waitlist_entry,
    edit_book as edit_book_page,
    execute_sql_query,
    export_books,
    render_admin_db,
    render_attendance,
    render_close_voting,
    render_gallery,
    render_history,
    render_meeting_detail,
    render_meetings,
    render_ranking,
    render_themes,
    render_waitlist,
    save_gallery_notes,
    suggest_waitlist_to_group,
    truncate_db_table,
    update_db_row,
    update_meeting as update_meeting_page,
)
from app.web.admin.demo import (
    clear_demo_data,
    render_demo_page,
    run_demo_step as run_admin_demo_step,
    seed_demo_data,
)
from app.web.admin.insights import (
    get_security_alerts,
    render_admin_bot_context,
    render_admin_search,
    render_admin_simulator,
    update_admin_bot_context,
)
from app.web.admin.messaging import (
    add_scheduled_message,
    delete_scoped_admin_message,
    delete_scheduled_message,
    preview_admin_message,
    render_admin_messages,
    render_scheduler,
    render_sent_messages,
    reset_admin_message,
    save_scoped_admin_message,
    send_custom_message,
    update_admin_message,
)
from app.web.admin.monitoring import (
    render_admin_audit,
    render_admin_bugs,
    render_admin_logs,
    render_admin_security,
    render_public_access_logs,
    unblock_admin_ip,
    update_admin_bug,
)
from app.web.admin.operations import (
    assign_book_to_meeting,
    send_dm_reminders,
    send_manual_meeting_info,
    send_manual_meeting_reminder,
    send_manual_reading_reminder,
    send_pin_all,
)
from app.web.admin.polls import (
    close_dates_poll,
    close_poll,
    close_theme_poll,
    create_book_poll,
    create_dates_poll,
    create_theme_poll,
    pick_book_winner,
)
from app.web.admin.site import (
    activate_cycle,
    advance_to_books,
    close_cycle as close_cycle_page,
    handle_public_settings,
    pick_theme_winner,
    rename_cycle as rename_cycle_page,
    render_admin_cycle,
    render_admin_help,
    render_admin_poster,
    render_public_page,
    set_cycle_theme as set_cycle_theme_page,
    unlock_proposals,
)
from app.web.admin.wizard import wizard_announce_date, wizard_lock_and_poll, wizard_new_cycle


def register_admin_routes(
    flask_app,
    *,
    require_admin,
    run_async,
    send_to_group,
    send_and_pin,
    send_meeting_reminder,
    send_reading_reminder,
    announce_winner,
    logger,
    telegram_app,
    telegram_chat_id,
    default_messages,
    group_invite_link,
    reload_custom_reminders,
    utcnow,
    get_request_ip,
    admin_search_limiter,
    poll_formatting,
    observability=None,
):
    @flask_app.get("/dashboard")
    def admin_dashboard():
        auth = require_admin()
        if auth:
            return auth
        current_cycle = db.get_current_cycle_key()
        books = db.get_books(current_cycle)
        meetings = db.get_meetings(limit=5, cycle_key=current_cycle)
        themes = db.get_themes(current_cycle)
        ranking = db.get_book_ranking()
        open_poll_books = db.get_open_polls(poll_type="books", cycle_key=current_cycle)
        open_poll_themes = db.get_open_poll(poll_type="themes", cycle_key=current_cycle)
        cycle_states = db.get_active_cycle_states()
        tied_books = db.get_tied_books(current_cycle)
        active_cycles = db.get_active_cycle_keys()
        operational_alerts = db.get_operational_alerts()
        security_alerts = get_security_alerts()
        runtime_metrics = observability.snapshot() if observability is not None else None
        recent_audit = db.get_admin_audit_logs(limit=5)
        cycle_state = cycle_states[0] if cycle_states else None
        dashboard_focus = build_dashboard_focus(
            cycle_state,
            active_cycles=active_cycles,
            alert_count=len(operational_alerts) + len(security_alerts),
        )
        return render_template(
            "admin.html",
            books=books,
            meetings=meetings,
            themes=themes,
            ranking=ranking,
            open_poll_books=open_poll_books,
            open_poll_themes=open_poll_themes,
            cycle_states=cycle_states,
            cycle_state=cycle_state,
            tied_books=tied_books,
            tied_count=len(tied_books),
            current_cycle=current_cycle,
            active_cycles=active_cycles,
            operational_alerts=operational_alerts,
            security_alerts=security_alerts,
            runtime_metrics=runtime_metrics,
            recent_audit=recent_audit,
            dashboard_focus=dashboard_focus,
        )

    @flask_app.get("/admin")
    def admin_dashboard_legacy():
        return redirect(url_for("admin_dashboard"), code=301)

    @flask_app.post("/admin/book/add")
    def admin_book_add():
        auth = require_admin()
        if auth:
            return auth
        next_url = _safe_next("admin_dashboard")
        cycle_key = request.form.get("cycle", "").strip() or None
        try:
            title = normalize_book_query(request.form.get("title", ""))
        except InputValidationError as exc:
            flash(str(exc), "danger")
            return redirect(next_url)
        try:
            book = books_api.google_books(title)
            if not book:
                book = {
                    "title": title,
                    "author": request.form.get("author", "").strip() or None,
                }
            db.insert_book(book, proposed_by="admin", cycle_key=cycle_key)
            effective_cycle = cycle_key or db.get_current_cycle_key()
            flash(f"Libro «{book['title']}» añadido al ciclo «{effective_cycle}»", "success")
        except Exception:
            logger.exception("Error añadiendo libro desde admin")
            flash("Error añadiendo el libro", "danger")
        return redirect(next_url)

    @flask_app.post("/admin/book/<int:proposal_id>/delete")
    def admin_book_delete(proposal_id):
        auth = require_admin()
        if auth:
            return auth
        next_url = _safe_next("admin_dashboard")
        try:
            db.remove_book_proposal(proposal_id)
            flash("Propuesta eliminada", "success")
        except Exception:
            flash("Error eliminando la propuesta", "danger")
        return redirect(next_url)

    @flask_app.post("/admin/encuesta/libros/crear")
    def admin_crear_encuesta_libros():
        return run_async(create_book_poll(require_admin, telegram_app, telegram_chat_id, logger))

    @flask_app.post("/admin/encuesta/<int:poll_db_id>/cerrar")
    def admin_cerrar_encuesta(poll_db_id):
        return run_async(close_poll(require_admin, poll_db_id, telegram_app, telegram_chat_id, send_to_group, announce_winner, logger))

    @flask_app.post("/admin/encuesta/temas/crear")
    def admin_crear_encuesta_temas():
        return run_async(create_theme_poll(require_admin, telegram_app, telegram_chat_id, logger))

    @flask_app.post("/admin/encuesta/fechas/<int:meeting_id>/crear")
    def admin_crear_encuesta_fechas(meeting_id):
        return run_async(create_dates_poll(require_admin, meeting_id, telegram_app, telegram_chat_id, logger))

    @flask_app.post("/admin/encuesta/fechas/<int:meeting_id>/<int:poll_db_id>/cerrar")
    def admin_cerrar_encuesta_fechas(meeting_id, poll_db_id):
        return run_async(
            close_dates_poll(require_admin, meeting_id, poll_db_id, telegram_app, send_to_group, poll_formatting, logger)
        )

    @flask_app.route("/meetings", methods=["GET", "POST"])
    def meetings_admin():
        return render_meetings(require_admin)

    @flask_app.get("/themes")
    def themes_admin():
        return render_themes(require_admin)

    @flask_app.get("/ranking")
    def ranking_admin():
        return render_ranking(require_admin)

    @flask_app.get("/meeting/<int:meeting_id>")
    def meeting_detail_admin(meeting_id):
        return render_meeting_detail(require_admin, meeting_id)

    @flask_app.post("/meeting/<int:meeting_id>/edit")
    def meeting_edit_admin(meeting_id):
        return update_meeting_page(require_admin, meeting_id)

    @flask_app.post("/meeting/<int:meeting_id>/delete")
    def meeting_delete_admin(meeting_id):
        return delete_meeting_page(require_admin, meeting_id)

    @flask_app.post("/meeting/<int:meeting_id>/date-option")
    def meeting_add_date_option_admin(meeting_id):
        return add_meeting_date_option(require_admin, meeting_id)

    @flask_app.post("/meeting/<int:meeting_id>/close-date")
    def meeting_close_date_admin(meeting_id):
        return close_meeting_date(require_admin, meeting_id)

    @flask_app.post("/create_meeting")
    def create_meeting():
        return create_meeting_page(require_admin, logger)

    @flask_app.get("/export")
    def export():
        return export_books(require_admin)

    @flask_app.get("/close_voting")
    def close_voting():
        return render_close_voting(require_admin)

    @flask_app.get("/attendance")
    def attendance():
        return render_attendance(require_admin)

    @flask_app.post("/admin/theme/add")
    def admin_theme_add():
        auth = require_admin()
        if auth:
            return auth
        next_url = _safe_next("themes_admin")
        try:
            name = normalize_theme_name(request.form.get("name", ""))
        except InputValidationError as exc:
            flash(str(exc), "danger")
            return redirect(next_url)
        try:
            db.create_theme(name, created_by="admin")
            flash(f"Temática «{name}» añadida", "success")
        except Exception:
            flash("Error añadiendo la temática", "danger")
        return redirect(next_url)

    @flask_app.post("/admin/theme/<int:theme_id>/edit")
    def admin_theme_edit(theme_id):
        auth = require_admin()
        if auth:
            return auth
        next_url = _safe_next("themes_admin")
        try:
            name = normalize_theme_name(request.form.get("name", ""))
        except InputValidationError as exc:
            flash(str(exc), "danger")
            return redirect(next_url)
        try:
            db.update_theme(theme_id, name)
            flash("Temática actualizada", "success")
        except Exception:
            flash("Error actualizando la temática", "danger")
        return redirect(next_url)

    @flask_app.post("/admin/theme/<int:theme_id>/delete")
    def admin_theme_delete(theme_id):
        auth = require_admin()
        if auth:
            return auth
        next_url = _safe_next("themes_admin")
        try:
            db.delete_theme(theme_id)
            flash("Temática eliminada", "success")
        except Exception:
            flash("Error eliminando la temática", "danger")
        return redirect(next_url)

    @flask_app.post("/admin/send/meeting-reminder")
    def admin_send_meeting_reminder():
        return run_async(send_manual_meeting_reminder(require_admin, send_meeting_reminder, logger))

    @flask_app.post("/admin/send/reading-reminder")
    def admin_send_reading_reminder():
        return run_async(send_manual_reading_reminder(require_admin, send_reading_reminder, logger))

    @flask_app.post("/admin/send/meeting-info")
    def admin_send_meeting_info():
        return run_async(send_manual_meeting_info(require_admin, send_to_group, logger))

    @flask_app.post("/admin/send/pin-all")
    def admin_send_pin_all():
        return run_async(send_pin_all(require_admin, send_and_pin, logger))

    @flask_app.post("/admin/send/dm-reminders/<int:meeting_id>")
    def admin_send_dm_reminders(meeting_id):
        return run_async(send_dm_reminders(require_admin, meeting_id, telegram_app, logger))

    @flask_app.get("/admin/historico")
    def admin_historico():
        return render_history(require_admin)

    @flask_app.get("/admin/galeria")
    def admin_galeria():
        return render_gallery(require_admin)

    @flask_app.post("/admin/galeria/<int:meeting_id>/notes")
    def admin_galeria_notes(meeting_id):
        return save_gallery_notes(require_admin, meeting_id)

    @flask_app.get("/")
    def public_root():
        return render_public_page(group_invite_link)

    @flask_app.get("/publico")
    def public_page():
        # La URL historica se mantiene como redireccion para consolidar SEO en la raiz.
        return redirect(url_for("public_root"), code=301)

    @flask_app.get("/publico/")
    def public_page_slash():
        return redirect(url_for("public_root"), code=301)

    @flask_app.route("/admin/public-settings", methods=["GET", "POST"])
    def admin_public_settings():
        return handle_public_settings(require_admin, group_invite_link)

    @flask_app.get("/admin/db")
    def admin_db():
        return render_admin_db(require_admin, logger)

    @flask_app.post("/admin/db/<table>/delete")
    def admin_db_delete_row(table):
        return delete_db_row(require_admin, logger, table)

    @flask_app.post("/admin/db/<table>/update")
    def admin_db_update_row(table):
        return update_db_row(require_admin, logger, table)

    @flask_app.post("/admin/db/<table>/truncate")
    def admin_db_truncate(table):
        return truncate_db_table(require_admin, logger, table)

    @flask_app.post("/admin/db/sql")
    def admin_db_sql():
        return execute_sql_query(require_admin, logger)

    @flask_app.post("/admin/book/<int:book_id>/edit")
    def admin_book_edit(book_id):
        return edit_book_page(require_admin, logger, book_id)

    @flask_app.post("/admin/send/custom")
    def admin_send_custom():
        return run_async(send_custom_message(require_admin, logger, send_to_group))

    @flask_app.get("/admin/messages")
    def admin_messages():
        return render_admin_messages(require_admin, default_messages)

    @flask_app.post("/admin/messages/<key>/edit")
    def admin_message_edit(key):
        return update_admin_message(require_admin, default_messages, key)

    @flask_app.post("/admin/messages/<key>/reset")
    def admin_message_reset(key):
        return reset_admin_message(require_admin, key)

    @flask_app.post("/admin/messages/scoped/save")
    def admin_message_scoped_save():
        return save_scoped_admin_message(require_admin, default_messages)

    @flask_app.post("/admin/messages/scoped/delete")
    def admin_message_scoped_delete():
        return delete_scoped_admin_message(require_admin)

    @flask_app.post("/admin/messages/preview")
    def admin_message_preview():
        return preview_admin_message(require_admin)

    @flask_app.get("/admin/sent-messages")
    def admin_sent_messages():
        return render_sent_messages(require_admin)

    @flask_app.get("/admin/scheduler")
    def admin_scheduler():
        return render_scheduler(require_admin)

    @flask_app.post("/admin/scheduler/add")
    def admin_scheduler_add():
        return add_scheduled_message(require_admin, logger)

    @flask_app.post("/admin/scheduler/<int:msg_id>/delete")
    def admin_scheduler_delete(msg_id):
        return delete_scheduled_message(require_admin, logger, msg_id)

    @flask_app.post("/admin/scheduler/custom/add")
    def admin_custom_reminder_add():
        auth = require_admin()
        if auth:
            return auth
        title = request.form.get("title", "").strip()
        message = request.form.get("message", "").strip()
        schedule_type = request.form.get("schedule_type", "interval")
        if not title or not message:
            flash("Título y mensaje son obligatorios", "danger")
            return redirect(url_for("admin_scheduler"))
        new_id = str(uuid.uuid4())[:8]
        kwargs = {
            "reminder_id": new_id,
            "title": title,
            "message": message,
            "schedule_type": schedule_type,
            "enabled": True,
        }
        if schedule_type == "cron":
            kwargs["day_of_week"] = request.form.get("day_of_week", "")
            try:
                kwargs["hour"] = int(request.form.get("hour", 10))
                kwargs["minute"] = int(request.form.get("minute", 0))
            except ValueError:
                kwargs["hour"] = 10
                kwargs["minute"] = 0
        else:
            try:
                kwargs["interval_hours"] = max(1, int(request.form.get("hours", 24)))
            except ValueError:
                kwargs["interval_hours"] = 24
        db.upsert_custom_reminder(**kwargs)
        reload_custom_reminders()
        flash(f"Recordatorio «{title}» añadido", "success")
        return redirect(url_for("admin_scheduler"))

    @flask_app.post("/admin/scheduler/custom/<reminder_id>/delete")
    def admin_custom_reminder_delete(reminder_id):
        auth = require_admin()
        if auth:
            return auth
        db.delete_custom_reminder(reminder_id)
        reload_custom_reminders()
        flash("Recordatorio eliminado", "success")
        return redirect(url_for("admin_scheduler"))

    @flask_app.post("/admin/scheduler/custom/<reminder_id>/toggle")
    def admin_custom_reminder_toggle(reminder_id):
        auth = require_admin()
        if auth:
            return auth
        db.toggle_custom_reminder(reminder_id)
        reload_custom_reminders()
        flash("Recordatorio actualizado", "success")
        return redirect(url_for("admin_scheduler"))

    @flask_app.post("/admin/scheduler/reminder/toggle")
    def admin_reminder_toggle():
        auth = require_admin()
        if auth:
            return auth
        key = request.form.get("key", "")
        allowed_keys = {
            "reminder_weekly_enabled",
            "reminder_reading_enabled",
            "reminder_daybefore_enabled",
            "reminder_keepalive_enabled",
        }
        if key not in allowed_keys:
            flash("Clave inválida", "danger")
            return redirect(url_for("admin_scheduler"))
        current = db.get_config(key, "1")
        new_val = "0" if current == "1" else "1"
        db.set_config(key, new_val)
        flash(f"Recordatorio {'activado' if new_val == '1' else 'desactivado'}", "success")
        return redirect(url_for("admin_scheduler"))

    @flask_app.get("/admin/ai/questions")
    def admin_ai_questions():
        return render_ai_questions(require_admin, logger)

    @flask_app.post("/admin/ai/questions/send")
    def admin_ai_questions_send():
        return run_async(send_ai_questions(require_admin, logger, send_to_group))

    @flask_app.get("/admin/ai/quote")
    def admin_ai_quote():
        return render_ai_quote(require_admin, logger)

    @flask_app.post("/admin/ai/quote/send")
    def admin_ai_quote_send():
        return run_async(send_ai_quote(require_admin, logger, send_to_group))

    @flask_app.route("/admin/ai/quote/manual", methods=["GET", "POST"])
    def admin_ai_quote_manual():
        return render_manual_quote(require_admin, logger)

    @flask_app.post("/admin/ai/ask")
    def admin_ai_ask():
        return run_async(ask_admin_ai(require_admin, utcnow, logger))

    @flask_app.get("/admin/poster")
    def admin_poster():
        return render_admin_poster(require_admin)

    @flask_app.get("/admin/help")
    def admin_help():
        return render_admin_help(require_admin)

    @flask_app.get("/admin/ciclo")
    def admin_ciclo():
        return render_admin_cycle(require_admin)

    @flask_app.get("/admin/ciclo/easy")
    def admin_ciclo_easy():
        auth = require_admin()
        if auth:
            return auth
        active_keys = db.get_active_cycle_keys()
        cycle = db.get_cycle_state(active_keys[0]) if active_keys else None
        return render_template(
            "admin_ciclo_easy.html",
            cycle=cycle,
            cycle_guidance=build_cycle_easy_guidance(cycle),
        )

    @flask_app.post("/admin/ciclo/nuevo")
    def admin_ciclo_nuevo():
        return run_async(activate_cycle(require_admin, send_to_group, logger, telegram_app, telegram_chat_id))

    @flask_app.post("/admin/ciclo/cerrar")
    def admin_ciclo_cerrar():
        return close_cycle_page(require_admin, logger)

    @flask_app.post("/admin/ciclo/tema")
    def admin_ciclo_tema():
        return set_cycle_theme_page(require_admin)

    @flask_app.post("/admin/ciclo/desbloquear")
    def admin_ciclo_desbloquear():
        return unlock_proposals(require_admin)

    @flask_app.post("/admin/ciclo/advance-books")
    def admin_ciclo_advance_books():
        return run_async(advance_to_books(require_admin, send_to_group, logger))

    @flask_app.post("/admin/ciclo/pick-theme/<int:theme_id>")
    def admin_ciclo_pick_theme(theme_id):
        return run_async(pick_theme_winner(require_admin, theme_id, send_to_group, logger))

    @flask_app.post("/admin/ciclo/pick-book/<int:proposal_id>")
    def admin_ciclo_pick_book(proposal_id):
        return run_async(pick_book_winner(require_admin, proposal_id, announce_winner, logger))

    @flask_app.post("/admin/ciclo/<cycle_key>/rename")
    def admin_ciclo_rename(cycle_key):
        return rename_cycle_page(require_admin)

    @flask_app.post("/admin/ciclo/meeting/<int:meeting_id>/set-date")
    def admin_ciclo_meeting_set_date(meeting_id):
        auth = require_admin()
        if auth:
            return auth
        final_date = request.form.get("final_date", "").strip()
        if not final_date:
            flash("Fecha inválida", "danger")
            return redirect(url_for("admin_ciclo"))
        try:
            db.set_meeting_final_date(meeting_id, final_date)
            flash("Fecha de reunión actualizada", "success")
        except Exception:
            logger.exception("Error actualizando fecha de reunión %s", meeting_id)
            flash("Error actualizando la fecha", "danger")
        return redirect(url_for("admin_ciclo"))

    @flask_app.post("/admin/encuesta/temas/<int:poll_db_id>/cerrar")
    def admin_cerrar_encuesta_temas(poll_db_id):
        return run_async(close_theme_poll(require_admin, poll_db_id, telegram_app, telegram_chat_id, send_to_group, logger))

    @flask_app.post("/admin/wizard/new-cycle")
    def admin_wizard_new_cycle():
        return run_async(wizard_new_cycle(require_admin, send_to_group, utcnow, logger))

    @flask_app.post("/admin/wizard/lock-and-poll")
    def admin_wizard_lock_and_poll():
        return run_async(wizard_lock_and_poll(require_admin, telegram_app, telegram_chat_id, logger))

    @flask_app.post("/admin/wizard/announce-date")
    def admin_wizard_announce_date():
        return run_async(wizard_announce_date(require_admin, send_to_group, logger))

    @flask_app.post("/meeting/<int:meeting_id>/set-book")
    def meeting_set_book(meeting_id):
        return assign_book_to_meeting(require_admin, meeting_id)

    @flask_app.get("/admin/waitlist")
    def admin_waitlist():
        return render_waitlist(require_admin)

    @flask_app.post("/admin/waitlist/add")
    def admin_waitlist_add():
        return add_waitlist_entry(require_admin)

    @flask_app.post("/admin/waitlist/<int:wl_id>/delete")
    def admin_waitlist_delete(wl_id):
        return delete_waitlist_entry(require_admin, wl_id)

    @flask_app.post("/admin/waitlist/suggest")
    def admin_waitlist_suggest():
        return run_async(suggest_waitlist_to_group(require_admin, send_to_group))

    @flask_app.get("/admin/demo")
    def admin_demo():
        return render_demo_page(require_admin, db)

    @flask_app.post("/admin/demo/seed")
    def admin_demo_seed():
        return seed_demo_data(require_admin, db, utcnow, logger)

    @flask_app.post("/admin/demo/clear")
    def admin_demo_clear():
        return clear_demo_data(require_admin, db, logger)

    @flask_app.post("/admin/demo/step/<int:step>")
    def admin_demo_step(step):
        return run_admin_demo_step(
            require_admin, db, utcnow, logger, step,
            run_async=run_async,
            send_to_group=send_to_group,
            send_and_pin=send_and_pin,
        )

    @flask_app.get("/admin/search")
    def admin_search():
        auth = require_admin()
        if auth:
            return auth
        raw_query = request.args.get("q", "")
        if not raw_query.strip():
            return render_admin_search(require_admin, query="")
        key = f"{session.get('admin_display_name') or 'admin'}:{get_request_ip()}"
        allowed, retry_after = admin_search_limiter.allow(key, limit=10, window_seconds=60)
        if not allowed:
            return render_admin_search(
                require_admin,
                query=truncate_search_query(raw_query),
                error_message=f"Demasiadas búsquedas seguidas. Espera {retry_after}s.",
                status_code=429,
            )
        try:
            query = normalize_admin_search_query(raw_query)
        except InputValidationError as exc:
            return render_admin_search(
                require_admin,
                query=truncate_search_query(raw_query),
                error_message=str(exc),
                status_code=400,
            )
        return render_admin_search(require_admin, query=query)

    @flask_app.get("/admin/simulator")
    def admin_simulator():
        return render_admin_simulator(require_admin)

    @flask_app.get("/admin/bot-context")
    def admin_bot_context():
        return render_admin_bot_context(require_admin)

    @flask_app.post("/admin/bot-context")
    def admin_bot_context_update():
        return update_admin_bot_context(require_admin)

    @flask_app.get("/admin/logs")
    def admin_logs():
        return render_admin_logs(require_admin)

    @flask_app.get("/admin/public-access")
    def admin_public_access():
        return render_public_access_logs(require_admin)

    @flask_app.get("/admin/security")
    def admin_security():
        return render_admin_security(require_admin)

    @flask_app.post("/admin/security/unblock")
    def admin_security_unblock():
        return unblock_admin_ip(require_admin)

    @flask_app.get("/admin/audit")
    def admin_audit():
        return render_admin_audit(require_admin)

    @flask_app.get("/admin/bugs")
    def admin_bugs():
        return render_admin_bugs(require_admin)

    @flask_app.post("/admin/bugs/<int:report_id>/update")
    def admin_bug_update(report_id):
        return update_admin_bug(require_admin, report_id)
