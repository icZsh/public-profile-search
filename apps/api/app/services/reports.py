from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.errors import ApiError
from apps.api.app.models.entities import (
    JobAttempt,
    ProviderRunSourceUse,
    ReportAccessState,
    ReportRevision,
    SourceDocument,
    SourceObservation,
)
from apps.api.app.policy.eligibility import get_valid_eligibility
from apps.api.app.policy.suppression import is_suppressed
from apps.api.app.services.jobs import owner_job


def _active_report(
    session: Session,
    *,
    job_id: str,
    user_id: str,
    reads_enabled: bool,
    settings,
    now,
):
    if not reads_enabled:
        raise ApiError(404, "result_unavailable", "The result is unavailable.")
    job = owner_job(session, job_id=job_id, user_id=user_id)
    attempt = session.get(JobAttempt, job.active_attempt_id)
    if not attempt or not attempt.current_report_revision_id:
        raise ApiError(409, "job_not_ready", "The brief is not ready.")
    report = session.get(ReportRevision, attempt.current_report_revision_id)
    access = session.get(ReportAccessState, attempt.current_report_revision_id)
    if not report or not access or access.state != "active":
        raise ApiError(404, "result_unavailable", "The result is unavailable.")
    if job.input_provider_id == "github_public_profile_v1" and not settings.github_provider_enabled:
        raise ApiError(404, "result_unavailable", "The result is unavailable.")
    if get_valid_eligibility(
        session,
        verification_id=job.eligibility_verification_id,
        user_id=job.user_id,
        identifier_hmac=job.normalized_identifier_hmac,
        now=now,
        policy_version=job.policy_version,
        provider_id=job.input_provider_id,
    ) is None or is_suppressed(session, job.normalized_identifier_hmac):
        raise ApiError(404, "result_unavailable", "The result is unavailable.")
    return job, report


def get_brief(
    session: Session,
    *,
    job_id: str,
    user_id: str,
    reads_enabled: bool,
    settings,
    now,
) -> dict[str, object]:
    _job, report = _active_report(
        session,
        job_id=job_id,
        user_id=user_id,
        reads_enabled=reads_enabled,
        settings=settings,
        now=now,
    )
    return report.content


def get_evidence(
    session: Session,
    *,
    job_id: str,
    user_id: str,
    reads_enabled: bool,
    settings,
    now,
) -> list[dict[str, object]]:
    _active_report(
        session,
        job_id=job_id,
        user_id=user_id,
        reads_enabled=reads_enabled,
        settings=settings,
        now=now,
    )
    rows = session.execute(
        select(SourceObservation, SourceDocument)
        .join(
            ProviderRunSourceUse,
            ProviderRunSourceUse.id == SourceObservation.source_use_id,
        )
        .join(SourceDocument, SourceDocument.id == ProviderRunSourceUse.document_id)
        .where(SourceObservation.job_id == job_id)
        .order_by(SourceObservation.retrieved_at, SourceObservation.id)
    ).all()
    return [
        {
            "evidence_id": observation.id,
            "source_type": observation.source_type,
            "title": document.title,
            "url": document.canonical_url,
            "excerpt": observation.excerpt,
            "retrieved_at": observation.retrieved_at,
        }
        for observation, document in rows
    ]
