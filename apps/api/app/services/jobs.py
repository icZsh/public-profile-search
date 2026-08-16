from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.crypto import (
    UnsafePrototypeUrl,
    canonicalize_profile_url,
    encrypt_value,
    keyed_hmac,
    stable_payload_hash,
)
from apps.api.app.core.errors import ApiError
from apps.api.app.models.entities import (
    IdempotencyRecord,
    JobAttempt,
    OutboxMessage,
    ProviderRun,
    SearchJob,
    new_id,
)
from apps.api.app.policy.eligibility import has_valid_eligibility
from apps.api.app.policy.suppression import is_suppressed, lock_identifier_scope
from apps.api.app.services.events import add_event

TERMINAL_WIRE_STATUS = {
    "ready": "complete",
    "ready_partial": "partial",
    "insufficient_evidence": "insufficient_evidence",
    "policy_blocked": "result_unavailable",
    "failed": "service_error",
    "cancelled": "cancelled",
}


def wire_status(status: str) -> str:
    return TERMINAL_WIRE_STATUS.get(status, status)


def create_job(
    session: Session,
    *,
    settings,
    clock,
    user_id: str,
    idempotency_key: str,
    request_payload: dict[str, object],
) -> tuple[SearchJob, bool]:
    if not settings.prototype_jobs_enabled:
        raise ApiError(503, "prototype_disabled", "New prototype jobs are temporarily disabled.")
    if not 8 <= len(idempotency_key) <= 128:
        raise ApiError(422, "invalid_request", "The request could not be accepted.")

    raw_url = str(request_payload["profile_url"])
    try:
        target = canonicalize_profile_url(raw_url, fixture_url=settings.fixture_url)
    except UnsafePrototypeUrl as exc:
        raise ApiError(
            422,
            "unsupported_provider",
            "Enter a direct public GitHub profile URL.",
        ) from exc
    if target.provider_id == "github_public_profile_v1" and not settings.github_provider_enabled:
        raise ApiError(
            503,
            "provider_disabled",
            "The GitHub evaluation provider is temporarily unavailable.",
        )

    now = clock.now()
    identifier_hmac = keyed_hmac(target.canonical_url, settings.prototype_hmac_key)
    lock_identifier_scope(session, identifier_hmac)
    if is_suppressed(session, identifier_hmac):
        raise ApiError(404, "result_unavailable", "The result is unavailable.")
    if request_payload.get("attestation_policy_version") != settings.policy_version:
        raise ApiError(422, "invalid_request", "The request could not be accepted.")

    verification_id = str(request_payload["eligibility_reference_id"])
    if not has_valid_eligibility(
        session,
        verification_id=verification_id,
        user_id=user_id,
        identifier_hmac=identifier_hmac,
        now=now,
        policy_version=settings.policy_version,
        provider_id=target.provider_id,
    ):
        raise ApiError(
            404,
            "result_unavailable",
            "The result is unavailable.",
        )

    normalized_payload = {
        **request_payload,
        "profile_url": target.canonical_url,
    }
    payload_hash = stable_payload_hash(normalized_payload)
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if existing.payload_hash != payload_hash:
            raise ApiError(
                409,
                "idempotency_conflict",
                "This idempotency key was already used for a different request.",
            )
        job = session.get(SearchJob, existing.job_id)
        if not job:
            raise ApiError(409, "idempotency_conflict", "The prior job is no longer available.")
        return job, False

    job_id = new_id()
    attempt_id = new_id()
    provider_run_id = new_id()
    expires_at = now + timedelta(days=settings.retention_days)
    job = SearchJob(
        id=job_id,
        user_id=user_id,
        refresh_of_job_id=None,
        history_reuse_policy=None,
        normalized_identifier_hmac=identifier_hmac,
        canonical_input_url_ciphertext=encrypt_value(
            target.canonical_url,
            settings.profile_url_encryption_key,
        ),
        input_provider_id=target.provider_id,
        canonicalization_version=target.canonicalization_version,
        eligibility_verification_id=verification_id,
        purpose=str(request_payload["purpose"]),
        fixture_key=target.fixture_key,
        status="queued",
        active_attempt_id=attempt_id,
        accepted_at=now,
        collection_cutoff_at=now + timedelta(seconds=80),
        fallback_at=now + timedelta(seconds=110),
        deadline_at=now + timedelta(seconds=120),
        completion_policy_id=settings.completion_policy_id,
        policy_version=settings.policy_version,
        locale=str(request_payload["locale"]),
        acceptance_epoch=1,
        row_version=1,
        cancelled_at=None,
        expires_at=expires_at,
    )
    attempt = JobAttempt(
        id=attempt_id,
        job_id=job_id,
        attempt_no=1,
        status="queued",
        collection_snapshot_id=None,
        current_analysis_revision_id=None,
        current_report_revision_id=None,
        started_at=now,
        finished_at=None,
        terminal_reason=None,
    )
    provider_run = ProviderRun(
        id=provider_run_id,
        job_id=job_id,
        attempt_id=attempt_id,
        logical_run_id=f"wave1:{target.provider_id}",
        provider_id=target.provider_id,
        status="pending",
        required_for_finalization=True,
        lease_generation=0,
        lease_expires_at=None,
        acceptance_epoch=1,
        result_count=0,
        deadline_at=job.collection_cutoff_at,
        expires_at=expires_at,
    )
    session.add(job)
    session.flush()
    session.add(attempt)
    session.flush()
    session.add(provider_run)
    session.flush()
    session.add(
        IdempotencyRecord(
            user_id=user_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            job_id=job_id,
            created_at=now,
            expires_at=expires_at,
        )
    )
    session.add(
        OutboxMessage(
            topic="provider_run",
            dedupe_key=f"provider-run:{provider_run_id}:generation:1",
            payload={"provider_run_id": provider_run_id},
            created_at=now,
            dispatched_at=None,
            attempts=0,
        )
    )
    add_event(
        session,
        job_id=job_id,
        event_type="job_queued",
        message="The approved public-profile check is queued.",
        created_at=now,
    )
    return job, True


def owner_job(
    session: Session, *, job_id: str, user_id: str, for_update: bool = False
) -> SearchJob:
    statement = select(SearchJob).where(SearchJob.id == job_id, SearchJob.user_id == user_id)
    if for_update:
        statement = statement.with_for_update()
    job = session.scalar(statement)
    if not job:
        raise ApiError(404, "job_not_found", "The job was not found.")
    return job


def job_response(job: SearchJob) -> dict[str, object]:
    return {
        "job_id": job.id,
        "status": wire_status(job.status),
        "collection_cutoff_at": job.collection_cutoff_at,
        "fallback_at": job.fallback_at,
        "deadline_at": job.deadline_at,
        "events_url": f"/v1/search-jobs/{job.id}/events",
    }
