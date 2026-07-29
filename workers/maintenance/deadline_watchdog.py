from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.models.entities import SearchJob
from apps.api.app.services.finalization import finalize_if_complete


def finalize_expired_jobs(session_factory: sessionmaker[Session], *, settings, clock) -> int:
    now = clock.now()
    with session_factory() as session:
        job_ids = session.scalars(
            select(SearchJob.id).where(
                SearchJob.collection_cutoff_at <= now,
                SearchJob.status.in_(["queued", "running", "finalizing"]),
            )
        ).all()
    finalized = 0
    for job_id in job_ids:
        finalized += int(
            finalize_if_complete(
                session_factory,
                settings=settings,
                clock=clock,
                job_id=job_id,
                force_cutoff=True,
            )
        )
    return finalized
