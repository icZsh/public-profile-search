from celery import Celery

from apps.api.app.core.clock import Clock
from apps.api.app.core.config import get_settings
from apps.api.app.core.db import build_engine, build_session_factory
from apps.api.app.services.provider_runs import process_provider_run

settings = get_settings()
engine = build_engine(settings.database_url)
session_factory = build_session_factory(engine)

celery_app = Celery("public_profile_search", broker=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_ignore_result=True,
    worker_prefetch_multiplier=1,
    task_default_queue="fast_http",
    broker_connection_retry_on_startup=True,
)


@celery_app.task(name="prototype.process_provider_run")
def process_provider_run_task(provider_run_id: str) -> None:
    process_provider_run(
        session_factory,
        settings=settings,
        clock=Clock(),
        provider_run_id=provider_run_id,
    )
