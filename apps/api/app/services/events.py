from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.models.entities import JobEvent


def add_event(
    session: Session,
    *,
    job_id: str,
    event_type: str,
    message: str,
    created_at,
    terminal: bool = False,
) -> JobEvent:
    current = session.scalar(
        select(func.coalesce(func.max(JobEvent.sequence), 0)).where(JobEvent.job_id == job_id)
    )
    pending = max(
        (
            event.sequence
            for event in session.new
            if isinstance(event, JobEvent) and event.job_id == job_id
        ),
        default=0,
    )
    event = JobEvent(
        job_id=job_id,
        sequence=max(int(current or 0), pending) + 1,
        event_type=event_type,
        message=message,
        terminal=terminal,
        created_at=created_at,
    )
    session.add(event)
    return event
