from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.clock import Clock
from apps.api.app.models.entities import (
    JobAttempt,
    MaigretScanRun,
    ProviderAttempt,
    ProviderRun,
    SearchJob,
)
from apps.api.app.services.discovery_jobs import owner_footprint_job
from apps.api.app.services.events import add_event

_TERMINAL_JOB_STATES = {
    "ready",
    "ready_partial",
    "no_candidates",
    "failed",
    "cancelled",
}
_TERMINAL_PROVIDER_RUN_STATES = {
    "success",
    "partial_success",
    "no_result",
    "timeout",
    "rate_limited",
    "captcha_blocked",
    "auth_required",
    "invalid_response",
    "provider_error",
    "skipped_budget",
    "skipped_circuit_open",
    "skipped_invalid_identifier",
    "skipped_configuration",
    "closed_at_finalization",
    "closed_at_cutoff",
    "cancelled",
}


def cancel_footprint_job(
    session: Session,
    *,
    job_id: str,
    user_id: str,
    clock: Clock,
) -> SearchJob:
    """Cancel unfinished footprint work while preserving results already accepted."""

    job = owner_footprint_job(
        session,
        job_id=job_id,
        user_id=user_id,
        for_update=True,
    )
    # Cancellation is convergent. A repeated request, or one that loses a race to
    # normal finalization, returns the durable terminal state without rewriting it.
    if job.status in _TERMINAL_JOB_STATES:
        return job

    # Take the timestamp only after cancellation owns the job lock. Sampling it
    # in the route can make cancellation appear to predate work committed while
    # this request was waiting for the lock.
    now = clock.now()
    job.acceptance_epoch += 1
    job.row_version += 1
    job.status = "cancelled"
    job.exploration_status = "cancelled"
    job.cancelled_at = now

    attempt = session.scalar(
        select(JobAttempt)
        .where(JobAttempt.id == job.active_attempt_id)
        .with_for_update()
    )
    if attempt is not None:
        attempt.status = "cancelled"
        attempt.finished_at = now
        attempt.terminal_reason = "user_cancelled"

    runs = session.scalars(
        select(ProviderRun)
        .where(ProviderRun.job_id == job.id)
        .order_by(ProviderRun.id)
        .with_for_update()
    ).all()
    run_ids = [run.id for run in runs]
    for run in runs:
        if run.status in _TERMINAL_PROVIDER_RUN_STATES:
            continue
        run.status = "cancelled"
        run.lease_expires_at = None

    if run_ids:
        scans = session.scalars(
            select(MaigretScanRun)
            .where(MaigretScanRun.provider_run_id.in_(run_ids))
            .with_for_update()
        ).all()
        for scan in scans:
            if scan.status in _TERMINAL_PROVIDER_RUN_STATES:
                continue
            scan.status = "cancelled"
            scan.finished_at = now
            scan.error_code = "job_cancelled"

        active_attempts = session.scalars(
            select(ProviderAttempt)
            .where(
                ProviderAttempt.provider_run_id.in_(run_ids),
                ProviderAttempt.finished_at.is_(None),
            )
            .with_for_update()
        ).all()
        for provider_attempt in active_attempts:
            provider_attempt.status = "cancelled"
            provider_attempt.finished_at = now
            provider_attempt.completion_disposition = "late_payload_discarded"
            provider_attempt.error_code = "job_cancelled"

        # Leave undispatched outbox messages in place. Their tasks no-op against
        # the durable job/run fence, while deleting them here could make Stop wait
        # behind a dispatcher that holds the row during a slow broker publish.

    add_event(
        session,
        job_id=job.id,
        event_type="job_cancelled",
        message="Discovery was cancelled by the user.",
        created_at=now,
        terminal=True,
    )
    return job
