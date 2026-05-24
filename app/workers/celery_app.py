"""
Celery Background Task Worker
──────────────────────────────
Handles long-running operations off the request thread:
  - Large dataset processing
  - Scheduled AI insight generation
  - Schema creation in the database
  - Cleanup tasks
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "ai_backend",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,                    # Re-queue on worker crash
    worker_prefetch_multiplier=1,           # Fair task distribution
    task_routes={
        "app.workers.tasks.process_large_dataset": {"queue": "heavy"},
        "app.workers.tasks.generate_scheduled_insights": {"queue": "ai"},
        "app.workers.tasks.cleanup_old_logs": {"queue": "maintenance"},
    },
    beat_schedule={
        "cleanup-old-api-logs": {
            "task": "app.workers.tasks.cleanup_old_logs",
            "schedule": crontab(hour=2, minute=0),   # Daily at 2am UTC
        },
        "refresh-prompt-performance": {
            "task": "app.workers.tasks.refresh_prompt_scores",
            "schedule": crontab(hour="*/6"),          # Every 6 hours
        },
    },
)
