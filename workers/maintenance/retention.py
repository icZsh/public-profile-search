from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.models.entities import (
    JobDeletionTombstone,
    ProviderRunSourceUse,
    SourceDocument,
)


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
