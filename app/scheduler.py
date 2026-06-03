"""Background scheduler for automatic email processing.

Polls the mailbox every settings.email_poll_seconds and runs the AI email
pipeline. Each run uses its own DB session. Safe to run with a single worker;
for multiple workers, run the scheduler in one dedicated process.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger

log = get_logger("scheduler")
_scheduler: BackgroundScheduler | None = None


def _poll_email_job():
    from app.ai.email_processor import process_unread
    db = SessionLocal()
    try:
        result = process_unread(db, max_results=10)
        if result:
            log.info("scheduled_email_run", processed=len(result))
    except Exception as e:  # pragma: no cover
        log.warning("scheduled_email_failed", error=str(e))
    finally:
        db.close()


def start_scheduler():
    global _scheduler
    if not settings.scheduler_enabled:
        log.info("scheduler_disabled")
        return
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(_poll_email_job, "interval",
                       seconds=settings.email_poll_seconds,
                       id="poll_email", max_instances=1, coalesce=True)
    _scheduler.start()
    log.info("scheduler_started", every_seconds=settings.email_poll_seconds)


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("scheduler_stopped")
