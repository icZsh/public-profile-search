from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.core.crypto import (
    InvalidEncryptedValue,
    decrypt_value,
    hmac_matches,
    keyed_hmac,
    stable_payload_hash,
)
from apps.api.app.models.entities import (
    JobAttempt,
    JobDeletionTombstone,
    OutboxMessage,
    ProviderAttempt,
    ProviderRun,
    ProviderRunSourceUse,
    SearchJob,
    SourceDocument,
    SourceObservation,
    new_id,
)
from apps.api.app.policy.eligibility import get_valid_eligibility
from apps.api.app.policy.redaction import safe_text
from apps.api.app.policy.suppression import is_suppressed
from apps.api.app.services.events import add_event
from apps.api.app.services.finalization import finalize_if_complete
from workers.providers.base import ProviderResult
from workers.providers.registry import run_provider


def process_provider_run(
    session_factory: sessionmaker[Session],
    *,
    settings,
    clock,
    provider_run_id: str,
    safe_fetch_gateway=None,
) -> None:
    lease = _lease_run(
        session_factory,
        settings=settings,
        clock=clock,
        provider_run_id=provider_run_id,
    )
    if not lease:
        return
    (
        generation,
        acceptance_epoch,
        provider_id,
        job_id,
        attempt_id,
        canonical_url_ciphertext,
    ) = lease
    try:
        canonical_url = decrypt_value(
            canonical_url_ciphertext,
            settings.profile_url_encryption_key,
        )
        result = run_provider(
            provider_id,
            canonical_profile_url=canonical_url,
            settings=settings,
            safe_fetch_gateway=safe_fetch_gateway,
        )
    except (InvalidEncryptedValue, ValueError):
        result = ProviderResult(
            provider_id=provider_id,
            status="provider_error",
            documents=(),
            error_code="invalid_encrypted_target",
        )
    except Exception:
        result = ProviderResult(
            provider_id=provider_id,
            status="provider_error",
            documents=(),
            error_code="unexpected_provider_failure",
        )

    with session_factory() as session, session.begin():
        run = session.scalar(
            select(ProviderRun).where(ProviderRun.id == provider_run_id).with_for_update()
        )
        job = session.scalar(select(SearchJob).where(SearchJob.id == job_id).with_for_update())
        provider_attempt = session.scalar(
            select(ProviderAttempt).where(
                ProviderAttempt.provider_run_id == provider_run_id,
                ProviderAttempt.generation == generation,
            )
        )
        tombstone = session.get(JobDeletionTombstone, job_id)
        stale = bool(
            not run
            or not job
            or tombstone
            or run.status != "running"
            or run.lease_generation != generation
            or run.acceptance_epoch != acceptance_epoch
            or job.acceptance_epoch != acceptance_epoch
        )
        if stale:
            if provider_attempt:
                provider_attempt.finished_at = clock.now()
                provider_attempt.status = "completed_after_fence"
                provider_attempt.completion_disposition = "late_payload_discarded"
            return

        now = clock.now()
        verification = get_valid_eligibility(
            session,
            verification_id=job.eligibility_verification_id,
            user_id=job.user_id,
            identifier_hmac=job.normalized_identifier_hmac,
            now=now,
            policy_version=job.policy_version,
            provider_id=job.input_provider_id,
        )
        subject_mismatch = bool(
            result.status == "success"
            and provider_id == "github_public_profile_v1"
            and (
                not verification
                or not verification.provider_subject_hmac
                or not result.subject_identifier
                or not hmac_matches(
                    keyed_hmac(
                        result.subject_identifier,
                        settings.prototype_hmac_key,
                    ),
                    verification.provider_subject_hmac,
                )
            )
        )
        if (
            verification is None
            or is_suppressed(session, job.normalized_identifier_hmac)
            or subject_mismatch
            or (provider_id == "github_public_profile_v1" and not settings.github_provider_enabled)
        ):
            _block_job_for_policy(
                session,
                job=job,
                run=run,
                provider_attempt=provider_attempt,
                now=now,
            )
            return

        if result.status != "success":
            run.status = result.status
            run.lease_expires_at = None
            if provider_attempt:
                provider_attempt.finished_at = now
                provider_attempt.status = result.status
                provider_attempt.completion_disposition = "in_budget"
                provider_attempt.error_code = result.error_code
            add_event(
                session,
                job_id=job_id,
                event_type="source_completed",
                message="An approved source reached a terminal status.",
                created_at=now,
            )
        else:
            result_count = 0
            for document in result.documents:
                content_hash = stable_payload_hash(
                    {
                        "url": document.canonical_url,
                        "title": document.title,
                        "excerpt": document.excerpt,
                        "fields": document.extracted_fields,
                    }
                )
                source_document = session.scalar(
                    select(SourceDocument).where(
                        SourceDocument.canonical_url == document.canonical_url,
                        SourceDocument.content_hash == content_hash,
                    )
                )
                if not source_document:
                    source_document = SourceDocument(
                        canonical_url=document.canonical_url,
                        publisher=safe_text(document.publisher, max_length=160),
                        title=safe_text(document.title, max_length=240),
                        mime_type="application/json",
                        content_hash=content_hash,
                        lineage_key=document.lineage_key,
                        expires_at=job.expires_at,
                    )
                    session.add(source_document)
                    session.flush()
                elif (
                    source_document.expires_at is None
                    or source_document.expires_at < job.expires_at
                ):
                    source_document.expires_at = job.expires_at
                source_use = ProviderRunSourceUse(
                    provider_run_id=run.id,
                    document_id=source_document.id,
                    disposition="accepted",
                    policy_version=settings.policy_version,
                )
                session.add(source_use)
                session.flush()
                observation = SourceObservation(
                    job_id=job_id,
                    source_use_id=source_use.id,
                    source_type=document.source_type,
                    trust_class=document.trust_class,
                    retrieved_at=now,
                    excerpt=safe_text(document.excerpt),
                    span_locator=document.span_locator,
                    extracted_fields=document.extracted_fields,
                    extraction_version=(
                        "github-public-v1"
                        if provider_id == "github_public_profile_v1"
                        else "fixture-v1"
                    ),
                    expires_at=job.expires_at,
                )
                session.add(observation)
                result_count += 1

            run.status = "success"
            run.result_count = result_count
            run.lease_expires_at = None
            if provider_attempt:
                provider_attempt.finished_at = now
                provider_attempt.status = "success"
                provider_attempt.completion_disposition = "in_budget"
            if provider_id == "fixture_primary_v1":
                _plan_linked_run(
                    session,
                    job=job,
                    attempt_id=attempt_id,
                    settings=settings,
                    now=now,
                )
            add_event(
                session,
                job_id=job_id,
                event_type="source_completed",
                message="An approved public source completed.",
                created_at=now,
            )

    finalize_if_complete(
        session_factory,
        settings=settings,
        clock=clock,
        job_id=job_id,
    )


def _lease_run(
    session_factory: sessionmaker[Session],
    *,
    settings,
    clock,
    provider_run_id: str,
) -> tuple[int, int, str, str, str, str] | None:
    with session_factory() as session, session.begin():
        run = session.scalar(
            select(ProviderRun).where(ProviderRun.id == provider_run_id).with_for_update()
        )
        if not run or run.status not in {"pending", "retry_scheduled"}:
            return None
        if session.get(JobDeletionTombstone, run.job_id):
            return None
        job = session.scalar(select(SearchJob).where(SearchJob.id == run.job_id).with_for_update())
        if not job or job.status in {
            "ready",
            "ready_partial",
            "insufficient_evidence",
            "policy_blocked",
            "failed",
            "cancelled",
        }:
            run.status = "closed_at_finalization"
            return None
        now = clock.now()
        verification = get_valid_eligibility(
            session,
            verification_id=job.eligibility_verification_id,
            user_id=job.user_id,
            identifier_hmac=job.normalized_identifier_hmac,
            now=now,
            policy_version=job.policy_version,
            provider_id=job.input_provider_id,
        )
        provider_disabled = (
            run.provider_id == "github_public_profile_v1" and not settings.github_provider_enabled
        )
        if (
            verification is None
            or is_suppressed(session, job.normalized_identifier_hmac)
            or provider_disabled
        ):
            _block_job_for_policy(
                session,
                job=job,
                run=run,
                provider_attempt=None,
                now=now,
            )
            return None
        if not job.canonical_input_url_ciphertext:
            _block_job_for_policy(
                session,
                job=job,
                run=run,
                provider_attempt=None,
                now=now,
            )
            return None
        run.status = "running"
        run.lease_generation += 1
        run.lease_expires_at = now + timedelta(seconds=30)
        run.acceptance_epoch = job.acceptance_epoch
        generation = run.lease_generation
        session.add(
            ProviderAttempt(
                provider_run_id=run.id,
                generation=generation,
                started_at=now,
                finished_at=None,
                status="running",
                completion_disposition=None,
                error_code=None,
            )
        )
        attempt = session.get(JobAttempt, run.attempt_id)
        if job.status == "queued":
            job.status = "running"
            if attempt:
                attempt.status = "running"
            add_event(
                session,
                job_id=job.id,
                event_type="collection_started",
                message="Approved public evidence collection started.",
                created_at=now,
            )
        return (
            generation,
            job.acceptance_epoch,
            run.provider_id,
            job.id,
            run.attempt_id,
            job.canonical_input_url_ciphertext,
        )


def _block_job_for_policy(
    session: Session,
    *,
    job: SearchJob,
    run: ProviderRun,
    provider_attempt: ProviderAttempt | None,
    now,
) -> None:
    job.acceptance_epoch += 1
    job.status = "policy_blocked"
    job.row_version += 1
    run.status = "cancelled"
    run.lease_expires_at = None
    for other_run in session.scalars(
        select(ProviderRun)
        .where(ProviderRun.job_id == job.id, ProviderRun.id != run.id)
        .with_for_update()
    ).all():
        if other_run.status not in {"success", "no_result", "cancelled"}:
            other_run.status = "cancelled"
            other_run.lease_expires_at = None
    attempt = session.get(JobAttempt, job.active_attempt_id)
    if attempt:
        attempt.status = "policy_blocked"
        attempt.finished_at = now
        attempt.terminal_reason = "eligibility_or_suppression"
    if provider_attempt:
        provider_attempt.finished_at = now
        provider_attempt.status = "cancelled"
        provider_attempt.completion_disposition = "payload_discarded_policy"
        provider_attempt.error_code = "result_unavailable"
    add_event(
        session,
        job_id=job.id,
        event_type="result_unavailable",
        message="The result is unavailable.",
        created_at=now,
        terminal=True,
    )


def _plan_linked_run(session: Session, *, job, attempt_id: str, settings, now) -> None:
    existing = session.scalar(
        select(ProviderRun.id).where(
            ProviderRun.attempt_id == attempt_id,
            ProviderRun.logical_run_id == "wave2:fixture_linked_v1",
        )
    )
    if existing:
        return
    linked_run = ProviderRun(
        id=new_id(),
        job_id=job.id,
        attempt_id=attempt_id,
        logical_run_id="wave2:fixture_linked_v1",
        provider_id="fixture_linked_v1",
        status="pending",
        required_for_finalization=True,
        lease_generation=0,
        lease_expires_at=None,
        acceptance_epoch=job.acceptance_epoch,
        result_count=0,
        deadline_at=job.collection_cutoff_at,
        expires_at=job.expires_at,
    )
    session.add(linked_run)
    session.flush()
    session.add(
        OutboxMessage(
            topic="provider_run",
            dedupe_key=f"provider-run:{linked_run.id}:generation:1",
            payload={"provider_run_id": linked_run.id},
            created_at=now,
            dispatched_at=None,
            attempts=0,
        )
    )
