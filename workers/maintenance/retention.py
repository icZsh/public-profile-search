from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.models.entities import (
    JobDeletionTombstone,
    ProviderRunSourceUse,
    SearchJob,
    SourceDocument,
)
from apps.api.app.services.deletion import delete_locked_job


def remove_expired_search_jobs(
    session_factory: sessionmaker[Session],
    *,
    now,
    batch_size: int = 25,
) -> int:
    """Fence and physically delete one small, lock-safe batch of expired jobs."""

    limit = min(50, max(1, int(batch_size)))
    with session_factory() as session, session.begin():
        jobs = session.scalars(
            select(SearchJob)
            .where(
                SearchJob.job_kind == "footprint_discovery",
                SearchJob.expires_at <= now,
            )
            .order_by(SearchJob.expires_at, SearchJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            # This also advances the acceptance epoch and creates a tombstone,
            # so anomalously active work cannot write through the retention fence.
            delete_locked_job(session, job=job, now=now)
        return len(jobs)


def remove_expired_tombstones(session_factory: sessionmaker[Session], *, now) -> int:
    with session_factory() as session, session.begin():
        result = session.execute(
            delete(JobDeletionTombstone).where(JobDeletionTombstone.expires_at <= now)
        )
        return int(result.rowcount or 0)


def remove_expired_orphan_source_documents(session_factory: sessionmaker[Session], *, now) -> int:
    with session_factory() as session, session.begin():
        still_referenced = (
            select(ProviderRunSourceUse.id)
            .where(ProviderRunSourceUse.document_id == SourceDocument.id)
            .exists()
        )
        result = session.execute(
            delete(SourceDocument).where(
                SourceDocument.expires_at.is_not(None),
                SourceDocument.expires_at <= now,
                ~still_referenced,
            )
        )
        return int(result.rowcount or 0)
