from sqlalchemy import select, text
from sqlalchemy.orm import Session

from apps.api.app.models.entities import SubjectSuppressionRecord


def lock_identifier_scope(session: Session, identifier_hmac: str) -> None:
    """Serialize admission and suppression for one canonical identifier on PostgreSQL."""

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    lock_key = int(identifier_hmac[:16], 16)
    if lock_key >= 2**63:
        lock_key -= 2**64
    session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


def is_suppressed(session: Session, identifier_hmac: str) -> bool:
    return (
        session.scalar(
            select(SubjectSuppressionRecord.id).where(
                SubjectSuppressionRecord.identifier_hmac == identifier_hmac,
                SubjectSuppressionRecord.status == "active",
            )
        )
        is not None
    )
