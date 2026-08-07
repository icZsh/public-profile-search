from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.core.crypto import stable_payload_hash
from apps.api.app.models.entities import (
    GroundedSynthesisResult,
    MaigretScanRun,
    OutboxMessage,
    ProviderAttempt,
    ProviderRun,
    SearchJob,
    new_id,
)
from apps.api.app.services.grounded_synthesis_scheduling import (
    GROUNDED_SYNTHESIS_PROMPT_VERSION,
    GROUNDED_SYNTHESIS_PROVIDER_IDS,
)
from apps.api.app.services.maigret_runs import finalize_discovery_if_complete
from apps.api.app.services.professional_search_scheduling import (
    PROFESSIONAL_PROVIDER_IDS,
)

MAIGRET_PROVIDER_ID = "maigret_discovery_v1"


def _deadline_reached(deadline, now) -> bool:
    if deadline is None:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return deadline <= now


def reclaim_expired_leases(session_factory: sessionmaker[Session], *, now) -> int:
    with session_factory() as session:
        candidates = session.execute(
            select(ProviderRun.id, ProviderRun.job_id).where(
                ProviderRun.status == "running",
                ProviderRun.lease_expires_at.is_not(None),
                ProviderRun.lease_expires_at < now,
            )
        ).all()
    return sum(
        int(
            _reclaim_expired_lease(
                session_factory,
                run_id=run_id,
                job_id=job_id,
                now=now,
            )
        )
        for run_id, job_id in candidates
    )


def _reclaim_expired_lease(
    session_factory: sessionmaker[Session],
    *,
    run_id: str,
    job_id: str,
    now,
) -> bool:
    """Fence one expired run while locking its job before its provider row."""

    with session_factory() as session, session.begin():
        job = session.scalar(
            select(SearchJob).where(SearchJob.id == job_id).with_for_update()
        )
        run = session.scalar(
            select(ProviderRun).where(ProviderRun.id == run_id).with_for_update()
        )
        if (
            job is None
            or run is None
            or run.job_id != job.id
            or run.status != "running"
            or run.lease_expires_at is None
            or not _deadline_reached(run.lease_expires_at, now)
        ):
            return False

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
            attempt.error_code = "lease_expired"
        is_maigret = run.provider_id == MAIGRET_PROVIDER_ID
        is_professional = run.provider_id in PROFESSIONAL_PROVIDER_IDS
        is_synthesis = run.provider_id in GROUNDED_SYNTHESIS_PROVIDER_IDS
        query_config = dict(run.query_config or {})
        is_adaptive_professional = bool(
            is_professional and query_config.get("retrieval_mode") in {"adaptive", "deep"}
        )
        scan = session.get(MaigretScanRun, run.id) if is_maigret else None
        should_finalize = False
        if (is_maigret or is_professional or is_synthesis) and _deadline_reached(
            run.deadline_at,
            now,
        ):
            run.status = "closed_at_cutoff"
            run.lease_expires_at = None
            if scan:
                scan.status = "closed_at_cutoff"
                scan.finished_at = now
                scan.error_code = "maigret_deadline_exceeded"
            if is_synthesis:
                _persist_synthesis_fallback(
                    session,
                    run=run,
                    status="closed_at_cutoff",
                    error_code="grounded_synthesis_deadline_exceeded",
                    now=now,
                )
            should_finalize = True
        elif is_synthesis or is_adaptive_professional:
            run.status = "provider_error"
            run.lease_expires_at = None
            if is_synthesis:
                _persist_synthesis_fallback(
                    session,
                    run=run,
                    status="provider_error",
                    error_code="grounded_synthesis_lease_expired_ambiguous",
                    now=now,
                )
            should_finalize = True
        else:
            run.status = "retry_scheduled"
            run.lease_expires_at = None
            if scan:
                scan.status = "retry_scheduled"
                scan.error_code = "maigret_lease_expired"
            session.add(
                OutboxMessage(
                    id=new_id(),
                    topic=(
                        "maigret_scan_run"
                        if is_maigret
                        else "professional_search_run"
                        if is_professional
                        else "provider_run"
                    ),
                    dedupe_key=(
                        f"maigret-scan:{run.id}:generation:{run.lease_generation + 1}"
                        if is_maigret
                        else (
                            f"professional-search:{run.id}:generation:"
                            f"{run.lease_generation + 1}"
                        )
                        if is_professional
                        else f"provider-run:{run.id}:generation:{run.lease_generation + 1}"
                    ),
                    payload={"provider_run_id": run.id},
                    created_at=now,
                    dispatched_at=None,
                    attempts=0,
                )
            )

        if should_finalize and job.job_kind == "footprint_discovery":
            finalize_discovery_if_complete(session, job=job, now=now)
        return True


def _bounded_text(
    value: object,
    *,
    default: str,
    maximum: int,
) -> str:
    normalized = str(value).strip() if value is not None else ""
    return normalized[:maximum] or default


def _persist_synthesis_fallback(
    session: Session,
    *,
    run: ProviderRun,
    status: str,
    error_code: str,
    now,
) -> None:
    if session.get(GroundedSynthesisResult, run.id) is not None:
        return
    query_config = dict(run.query_config or {})
    model = _bounded_text(
        query_config.get("model"),
        default="gpt-5.6-sol",
        maximum=80,
    )
    prompt_version = _bounded_text(
        query_config.get("prompt_version"),
        default=GROUNDED_SYNTHESIS_PROMPT_VERSION,
        maximum=64,
    )
    session.add(
        GroundedSynthesisResult(
            provider_run_id=run.id,
            job_id=run.job_id,
            status=status,
            model=model,
            prompt_version=prompt_version,
            input_checksum=stable_payload_hash(
                {
                    "job_id": run.job_id,
                    "provider_run_id": run.id,
                    "fallback_reason": error_code,
                }
            ),
            output=None,
            usage=None,
            error_code=error_code,
            created_at=now,
            expires_at=run.expires_at,
        )
    )
