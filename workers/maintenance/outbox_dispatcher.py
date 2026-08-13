import argparse
import logging
import time
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.core.clock import Clock
from apps.api.app.core.config import get_settings
from apps.api.app.core.db import build_engine, build_session_factory
from apps.api.app.models.entities import OutboxMessage
from workers.maintenance.deadline_watchdog import finalize_expired_jobs
from workers.maintenance.reconciler import advance_discovery_jobs, reclaim_expired_leases
from workers.orchestrator.celery_app import celery_app

_LOGGER = logging.getLogger(__name__)
_MAINTENANCE_INTERVAL_SECONDS = 1.0


class TaskPublisher(Protocol):
    def send_provider_run(self, provider_run_id: str, task_id: str) -> None: ...

    def send_maigret_scan_run(self, provider_run_id: str, task_id: str) -> None: ...

    def send_professional_search_run(
        self,
        provider_run_id: str,
        task_id: str,
    ) -> None: ...

    def send_grounded_synthesis_run(
        self,
        provider_run_id: str,
        task_id: str,
    ) -> None: ...


class CeleryPublisher:
    def send_provider_run(self, provider_run_id: str, task_id: str) -> None:
        celery_app.send_task(
            "prototype.process_provider_run",
            args=[provider_run_id],
            task_id=task_id,
            queue="fast_http",
        )

    def send_maigret_scan_run(self, provider_run_id: str, task_id: str) -> None:
        celery_app.send_task(
            "prototype.process_maigret_scan_run",
            args=[provider_run_id],
            task_id=task_id,
            queue="maigret_scan",
        )

    def send_professional_search_run(
        self,
        provider_run_id: str,
        task_id: str,
    ) -> None:
        celery_app.send_task(
            "prototype.process_professional_search_run",
            args=[provider_run_id],
            task_id=task_id,
            queue="professional_search",
        )

    def send_grounded_synthesis_run(
        self,
        provider_run_id: str,
        task_id: str,
    ) -> None:
        celery_app.send_task(
            "prototype.process_grounded_synthesis_run",
            args=[provider_run_id],
            task_id=task_id,
            queue="grounded_synthesis",
        )


def dispatch_once(
    session_factory: sessionmaker[Session],
    publisher: TaskPublisher,
) -> bool:
    with session_factory() as session, session.begin():
        message = session.scalar(
            select(OutboxMessage)
            .where(OutboxMessage.dispatched_at.is_(None))
            .order_by(OutboxMessage.created_at, OutboxMessage.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if not message:
            return False
        message.attempts += 1
        payload = message.payload
        provider_run_id = payload.get("provider_run_id")
        if not provider_run_id:
            message.dispatched_at = datetime.now(UTC)
            return True
        if message.topic == "provider_run":
            publisher.send_provider_run(str(provider_run_id), message.dedupe_key)
        elif message.topic == "maigret_scan_run":
            publisher.send_maigret_scan_run(str(provider_run_id), message.dedupe_key)
        elif message.topic == "professional_search_run":
            publisher.send_professional_search_run(
                str(provider_run_id),
                message.dedupe_key,
            )
        elif message.topic == "grounded_synthesis_run":
            publisher.send_grounded_synthesis_run(
                str(provider_run_id),
                message.dedupe_key,
            )
        else:
            message.dispatched_at = datetime.now(UTC)
            return True
        message.dispatched_at = datetime.now(UTC)
        return True


def maintenance_once(
    session_factory: sessionmaker[Session],
    *,
    settings,
    clock,
) -> tuple[int, int, int]:
    """Reclaim lost work and close jobs whose bounded retrieval window expired."""

    reclaimed = reclaim_expired_leases(session_factory, now=clock.now())
    advanced = advance_discovery_jobs(
        session_factory,
        settings=settings,
        clock=clock,
    )
    finalized = finalize_expired_jobs(
        session_factory,
        settings=settings,
        clock=clock,
    )
    return reclaimed, advanced, finalized


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    factory = build_session_factory(build_engine(settings.database_url))
    publisher = CeleryPublisher()
    clock = Clock()
    next_maintenance_at = 0.0
    while True:
        monotonic_now = time.monotonic()
        if monotonic_now >= next_maintenance_at:
            try:
                maintenance_once(factory, settings=settings, clock=clock)
            except Exception:
                # Broker dispatch must stay alive across a transient maintenance
                # failure; the next interval retries the idempotent reconciliation.
                _LOGGER.exception("Background discovery maintenance failed")
            next_maintenance_at = monotonic_now + _MAINTENANCE_INTERVAL_SECONDS
        dispatched = dispatch_once(factory, publisher)
        if args.once:
            return
        if not dispatched:
            time.sleep(0.5)


if __name__ == "__main__":
    main()
