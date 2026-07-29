from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.models.entities import OutboxMessage, ProviderAttempt, ProviderRun, new_id


def reclaim_expired_leases(session_factory: sessionmaker[Session], *, now) -> int:
    reclaimed = 0
    with session_factory() as session, session.begin():
        runs = session.scalars(
            select(ProviderRun)
            .where(
                ProviderRun.status == "running",
                ProviderRun.lease_expires_at.is_not(None),
                ProviderRun.lease_expires_at < now,
            )
            .with_for_update(skip_locked=True)
        ).all()
        for run in runs:
            attempt = session.scalar(
                select(ProviderAttempt).where(
                    ProviderAttempt.provider_run_id == run.id,
                    ProviderAttempt.generation == run.lease_generation,
                )
            )
            if attempt:
                attempt.status = "abandoned_lease_expired"
                attempt.finished_at = now
                attempt.completion_disposition = "late_payload_discarded"
            run.status = "retry_scheduled"
            run.lease_expires_at = None
            session.add(
                OutboxMessage(
                    id=new_id(),
                    topic="provider_run",
                    dedupe_key=(f"provider-run:{run.id}:generation:{run.lease_generation + 1}"),
                    payload={"provider_run_id": run.id},
                    created_at=now,
                    dispatched_at=None,
                    attempts=0,
                )
            )
            reclaimed += 1
    return reclaimed
