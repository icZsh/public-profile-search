from celery import Celery

from apps.api.app.core.clock import Clock
from apps.api.app.core.config import get_settings
from apps.api.app.core.db import build_engine, build_session_factory
from apps.api.app.services.grounded_synthesis_runs import (
    process_grounded_synthesis_run,
)
from apps.api.app.services.maigret_runs import process_maigret_scan_run
from apps.api.app.services.professional_search_runs import (
    process_professional_search_run,
)
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
    # Redis reverses Celery's numeric priority scale: 0 is highest, 9 lowest.
    task_default_priority=9,
    task_queue_max_priority=9,
    broker_transport_options={
        "priority_steps": list(range(10)),
        "sep": ":",
        "queue_order_strategy": "priority",
    },
    task_routes={
        "prototype.process_provider_run": {"queue": "fast_http"},
        "prototype.process_maigret_scan_run": {"queue": "maigret_scan"},
        "prototype.process_professional_search_run": {"queue": "professional_search"},
        "prototype.process_grounded_synthesis_run": {"queue": "grounded_synthesis"},
    },
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


@celery_app.task(name="prototype.process_maigret_scan_run")
def process_maigret_scan_run_task(provider_run_id: str) -> None:
    process_maigret_scan_run(
        session_factory,
        settings=settings,
        clock=Clock(),
        provider_run_id=provider_run_id,
    )


@celery_app.task(name="prototype.process_professional_search_run")
def process_professional_search_run_task(provider_run_id: str) -> None:
    process_professional_search_run(
        session_factory,
        settings=settings,
        clock=Clock(),
        provider_run_id=provider_run_id,
    )


@celery_app.task(
    name="prototype.process_grounded_synthesis_run",
    acks_late=True,
    acks_on_failure_or_timeout=False,
    reject_on_worker_lost=True,
)
def process_grounded_synthesis_run_task(provider_run_id: str) -> None:
    process_grounded_synthesis_run(
        session_factory,
        settings=settings,
        clock=Clock(),
        provider_run_id=provider_run_id,
    )
