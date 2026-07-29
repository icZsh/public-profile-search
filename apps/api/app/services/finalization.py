from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.core.crypto import stable_payload_hash
from apps.api.app.models.entities import (
    AnalysisRevision,
    Claim,
    ClaimEvidence,
    CollectionSnapshot,
    JobAttempt,
    JobDeletionTombstone,
    ProviderRun,
    ProviderRunSourceUse,
    ReportAccessState,
    ReportRevision,
    SearchJob,
    SourceDocument,
    SourceObservation,
    new_id,
)
from apps.api.app.policy.completeness import completeness_outcome
from apps.api.app.policy.eligibility import get_valid_eligibility
from apps.api.app.policy.suppression import is_suppressed
from apps.api.app.services.events import add_event
from workers.correlator.explicit_link import correlate_explicit_link
from workers.summarizer.deterministic import render_fast_brief

PROVIDER_TERMINAL_STATES = {
    "success",
    "no_result",
    "timeout",
    "rate_limited",
    "captcha_blocked",
    "auth_required",
    "invalid_response",
    "provider_error",
    "skipped_budget",
    "skipped_circuit_open",
    "closed_at_finalization",
    "cancelled",
}


def finalize_if_complete(
    session_factory: sessionmaker[Session],
    *,
    settings,
    clock,
    job_id: str,
    force_cutoff: bool = False,
) -> bool:
    with session_factory() as session, session.begin():
        if session.get(JobDeletionTombstone, job_id):
            return False
        job = session.scalar(select(SearchJob).where(SearchJob.id == job_id).with_for_update())
        if not job or job.status in {
            "ready",
            "ready_partial",
            "insufficient_evidence",
            "policy_blocked",
            "failed",
            "cancelled",
        }:
            return False
        attempt = session.get(JobAttempt, job.active_attempt_id)
        if not attempt or attempt.current_report_revision_id:
            return False

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
            job.input_provider_id == "github_public_profile_v1"
            and not settings.github_provider_enabled
        )
        if (
            verification is None
            or is_suppressed(session, job.normalized_identifier_hmac)
            or provider_disabled
        ):
            job.status = "policy_blocked"
            job.acceptance_epoch += 1
            job.row_version += 1
            attempt.status = "policy_blocked"
            attempt.finished_at = now
            attempt.terminal_reason = "eligibility_or_suppression"
            add_event(
                session,
                job_id=job_id,
                event_type="result_unavailable",
                message="The result is unavailable.",
                created_at=now,
                terminal=True,
            )
            return True

        runs = session.scalars(
            select(ProviderRun)
            .where(ProviderRun.job_id == job_id)
            .order_by(ProviderRun.logical_run_id)
            .with_for_update()
        ).all()
        cutoff_at = job.collection_cutoff_at
        if cutoff_at.tzinfo is None:
            cutoff_at = cutoff_at.replace(tzinfo=UTC)
        cutoff_reached = force_cutoff or now >= cutoff_at
        if cutoff_reached:
            for run in runs:
                if run.status not in PROVIDER_TERMINAL_STATES:
                    run.status = "closed_at_finalization"
                    run.lease_expires_at = None
        elif any(
            run.required_for_finalization and run.status not in PROVIDER_TERMINAL_STATES
            for run in runs
        ):
            return False

        job.status = "finalizing"
        job.row_version += 1
        attempt.status = "finalizing"
        add_event(
            session,
            job_id=job_id,
            event_type="finalization_started",
            message="The accepted public evidence is being finalized.",
            created_at=now,
        )
        job.acceptance_epoch += 1

        if (
            get_valid_eligibility(
                session,
                verification_id=job.eligibility_verification_id,
                user_id=job.user_id,
                identifier_hmac=job.normalized_identifier_hmac,
                now=now,
                policy_version=job.policy_version,
                provider_id=job.input_provider_id,
            )
            is None
            or is_suppressed(session, job.normalized_identifier_hmac)
            or (
                job.input_provider_id == "github_public_profile_v1"
                and not settings.github_provider_enabled
            )
        ):
            job.status = "policy_blocked"
            attempt.status = "policy_blocked"
            attempt.finished_at = now
            attempt.terminal_reason = "suppressed"
            add_event(
                session,
                job_id=job_id,
                event_type="result_unavailable",
                message="The result is unavailable.",
                created_at=now,
                terminal=True,
            )
            return True

        observation_rows = session.execute(
            select(SourceObservation, SourceDocument)
            .join(
                ProviderRunSourceUse,
                ProviderRunSourceUse.id == SourceObservation.source_use_id,
            )
            .join(SourceDocument, SourceDocument.id == ProviderRunSourceUse.document_id)
            .where(SourceObservation.job_id == job_id)
            .order_by(SourceObservation.id)
        ).all()
        observations = [
            {
                "id": observation.id,
                "source_type": observation.source_type,
                "extracted_fields": observation.extracted_fields,
                "lineage_key": document.lineage_key,
                "canonical_url": document.canonical_url,
            }
            for observation, document in observation_rows
        ]
        observation_ids = [str(item["id"]) for item in observations]
        provider_manifest = [
            {
                "provider_run_id": run.id,
                "provider_id": run.provider_id,
                "status": run.status,
                "result_count": run.result_count,
            }
            for run in runs
        ]
        snapshot_id = new_id()
        snapshot_checksum = stable_payload_hash(
            {"observations": observation_ids, "providers": provider_manifest}
        )
        snapshot = CollectionSnapshot(
            id=snapshot_id,
            job_id=job_id,
            attempt_id=attempt.id,
            cutoff_at=now,
            observation_ids=observation_ids,
            provider_manifest=provider_manifest,
            policy_version=settings.policy_version,
            checksum=snapshot_checksum,
            expires_at=job.expires_at,
        )
        session.add(snapshot)
        session.flush()

        claim_specs = correlate_explicit_link(observations)
        analysis_id = new_id()
        analysis = AnalysisRevision(
            id=analysis_id,
            job_id=job_id,
            collection_snapshot_id=snapshot_id,
            status="complete",
            rules_version="explicit-link-v2",
            checksum=stable_payload_hash(
                {
                    "snapshot": snapshot_checksum,
                    "claims": [
                        {"predicate": spec.predicate, "value": spec.value} for spec in claim_specs
                    ],
                }
            ),
            created_at=now,
            expires_at=job.expires_at,
        )
        session.add(analysis)
        session.flush()

        rendered_claims: list[dict[str, object]] = []
        for spec in claim_specs:
            claim = Claim(
                id=new_id(),
                job_id=job_id,
                analysis_revision_id=analysis_id,
                predicate=spec.predicate,
                label=spec.label,
                value=spec.value,
                confidence=spec.confidence,
                displayable=True,
                policy_reason="versioned display predicate allowlist",
            )
            session.add(claim)
            for observation_id, independence_group in spec.evidence:
                if observation_id not in observation_ids:
                    raise ValueError("Claim evidence cannot cross the frozen collection snapshot")
                session.add(
                    ClaimEvidence(
                        claim_id=claim.id,
                        observation_id=observation_id,
                        relation="supports",
                        independence_group=independence_group,
                        rationale="Deterministic explicit-link rule",
                    )
                )
            rendered_claims.append(
                {
                    "claim_id": claim.id,
                    "predicate": claim.predicate,
                    "label": claim.label,
                    "value": claim.value,
                    "confidence": claim.confidence,
                    "evidence_ids": [observation_id for observation_id, _ in spec.evidence],
                }
            )

        outcome = completeness_outcome({spec.predicate for spec in claim_specs})
        report_id = new_id()
        content = render_fast_brief(
            job_id=job_id,
            claims=rendered_claims,
            generated_at=now,
            provider_id=job.input_provider_id,
        )
        report = ReportRevision(
            id=report_id,
            job_id=job_id,
            analysis_revision_id=analysis_id,
            report_type="fast_brief",
            locale=job.locale,
            status="ready",
            content=content,
            template_version="deterministic-fast-brief-v1",
            policy_version=settings.policy_version,
            checksum=stable_payload_hash(content),
            created_at=now,
            expires_at=job.expires_at,
        )
        session.add(report)
        session.flush()
        session.add(
            ReportAccessState(
                report_id=report_id,
                job_id=job_id,
                state="active",
                updated_at=now,
            )
        )
        attempt.collection_snapshot_id = snapshot_id
        attempt.current_analysis_revision_id = analysis_id
        attempt.current_report_revision_id = report_id
        attempt.finished_at = now
        attempt.status = outcome
        attempt.terminal_reason = outcome
        job.status = outcome
        job.row_version += 1
        add_event(
            session,
            job_id=job_id,
            event_type="brief_ready" if outcome != "insufficient_evidence" else outcome,
            message=(
                "The deterministic public-profile brief is ready."
                if outcome != "insufficient_evidence"
                else "The accepted evidence was insufficient for a useful brief."
            ),
            created_at=now,
            terminal=True,
        )
        return True
