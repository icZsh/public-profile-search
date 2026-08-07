from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.models.entities import (
    MaigretScanRun,
    ProviderAttempt,
    ProviderRun,
    SearchJob,
)
from apps.api.app.services.anchor_selection import (
    MIN_PROFESSIONAL_SEARCH_SECONDS,
    anchor_selection_is_open,
)
from apps.api.app.services.finalization import finalize_if_complete
from apps.api.app.services.grounded_synthesis_scheduling import (
    GROUNDED_SYNTHESIS_PROVIDER_IDS,
)
from apps.api.app.services.maigret_runs import (
    PROVIDER_TERMINAL_STATES as MAIGRET_PROVIDER_TERMINAL_STATES,
)
from apps.api.app.services.maigret_runs import finalize_discovery_if_complete


def _finalize_expired_discovery_job(
    session_factory: sessionmaker[Session],
    *,
    job_id: str,
    now,
    settings,
) -> bool:
    with session_factory() as session, session.begin():
        job = session.scalar(select(SearchJob).where(SearchJob.id == job_id).with_for_update())
        if not job or job.job_kind != "footprint_discovery":
            return False
        runs = session.scalars(
            select(ProviderRun).where(ProviderRun.job_id == job_id).with_for_update()
        ).all()
        for run in runs:
            if run.status in MAIGRET_PROVIDER_TERMINAL_STATES:
                continue
            if run.provider_id in GROUNDED_SYNTHESIS_PROVIDER_IDS:
                continue
            was_running = run.status == "running"
            run.status = "closed_at_cutoff"
            run.lease_expires_at = None
            scan = session.get(MaigretScanRun, run.id)
            if scan:
                scan.status = "closed_at_cutoff"
                scan.finished_at = now
                scan.error_code = "maigret_deadline_exceeded"
            if was_running:
                attempt = session.scalar(
                    select(ProviderAttempt).where(
                        ProviderAttempt.provider_run_id == run.id,
                        ProviderAttempt.generation == run.lease_generation,
                    )
                )
                if attempt:
                    attempt.status = "closed_at_cutoff"
                    attempt.finished_at = now
                    attempt.completion_disposition = "late_payload_discarded"
                    attempt.error_code = "deadline_exceeded"
        return finalize_discovery_if_complete(
            session,
            job=job,
            now=now,
            settings=settings,
        )


def _advance_expired_anchor_job(
    session_factory: sessionmaker[Session],
    *,
    job_id: str,
    now,
    settings,
) -> bool:
    with session_factory() as session, session.begin():
        job = session.scalar(select(SearchJob).where(SearchJob.id == job_id).with_for_update())
        if (
            not job
            or job.job_kind != "footprint_discovery"
            or job.exploration_status != "awaiting_anchor"
            or anchor_selection_is_open(job=job, now=now)
        ):
            return False
        finalize_discovery_if_complete(
            session,
            job=job,
            now=now,
            settings=settings,
        )
        return job.exploration_status != "awaiting_anchor"


def finalize_expired_jobs(session_factory: sessionmaker[Session], *, settings, clock) -> int:
    now = clock.now()
    with session_factory() as session:
        anchor_job_ids = session.scalars(
            select(SearchJob.id).where(
                SearchJob.job_kind == "footprint_discovery",
                SearchJob.exploration_status == "awaiting_anchor",
                SearchJob.deadline_at
                <= now + timedelta(seconds=MIN_PROFESSIONAL_SEARCH_SECONDS),
                SearchJob.collection_cutoff_at > now,
                SearchJob.status.in_(["queued", "running", "finalizing", "discovering"]),
            )
        ).all()
        jobs = session.execute(
            select(SearchJob.id, SearchJob.job_kind).where(
                SearchJob.collection_cutoff_at <= now,
                SearchJob.status.in_(["queued", "running", "finalizing", "discovering"]),
            )
        ).all()
    finalized = sum(
        int(
            _advance_expired_anchor_job(
                session_factory,
                job_id=job_id,
                now=now,
                settings=settings,
            )
        )
        for job_id in anchor_job_ids
    )
    for job_id, job_kind in jobs:
        if job_kind == "footprint_discovery":
            finalized += int(
                _finalize_expired_discovery_job(
                    session_factory,
                    job_id=job_id,
                    now=now,
                    settings=settings,
                )
            )
        else:
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
