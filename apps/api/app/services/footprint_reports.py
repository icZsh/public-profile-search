from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.errors import ApiError
from apps.api.app.models.entities import (
    AnalysisRevision,
    CollectionSnapshot,
    JobAttempt,
    ProviderRunSourceUse,
    ReportAccessState,
    ReportRevision,
    SourceDocument,
    SourceObservation,
)
from apps.api.app.services.discovery_jobs import owner_footprint_job


def _active_footprint_report(
    session: Session,
    *,
    job_id: str,
    user_id: str,
    reads_enabled: bool,
    now,
) -> tuple[ReportRevision, CollectionSnapshot]:
    if not reads_enabled:
        raise ApiError(404, "result_unavailable", "The result is unavailable.")

    job = owner_footprint_job(session, job_id=job_id, user_id=user_id, now=now)
    attempt = session.get(JobAttempt, job.active_attempt_id)
    if not attempt or not attempt.current_report_revision_id:
        raise ApiError(409, "job_not_ready", "The footprint brief is not ready.")

    report = session.get(ReportRevision, attempt.current_report_revision_id)
    if (
        not report
        or report.job_id != job.id
        or report.report_type not in {"account_centric", "person_centric"}
        or report.status != "ready"
    ):
        raise ApiError(404, "result_unavailable", "The result is unavailable.")

    access = session.get(ReportAccessState, report.id)
    if not access or access.job_id != job.id or access.state != "active":
        raise ApiError(404, "result_unavailable", "The result is unavailable.")

    analysis = session.get(AnalysisRevision, report.analysis_revision_id)
    snapshot = (
        session.get(CollectionSnapshot, analysis.collection_snapshot_id)
        if analysis and analysis.job_id == job.id
        else None
    )
    if not snapshot or snapshot.job_id != job.id:
        raise ApiError(404, "result_unavailable", "The result is unavailable.")
    return report, snapshot


def get_footprint_brief(
    session: Session,
    *,
    job_id: str,
    user_id: str,
    reads_enabled: bool,
    now,
) -> dict[str, object]:
    report, _snapshot = _active_footprint_report(
        session,
        job_id=job_id,
        user_id=user_id,
        reads_enabled=reads_enabled,
        now=now,
    )
    content = report.content
    if (
        not isinstance(content, dict)
        or str(content.get("job_id")) != job_id
        or content.get("report_type") != report.report_type
    ):
        raise ApiError(404, "result_unavailable", "The result is unavailable.")
    return content


def get_footprint_evidence(
    session: Session,
    *,
    job_id: str,
    user_id: str,
    reads_enabled: bool,
    now,
) -> list[dict[str, object]]:
    _report, snapshot = _active_footprint_report(
        session,
        job_id=job_id,
        user_id=user_id,
        reads_enabled=reads_enabled,
        now=now,
    )
    observation_ids = {str(observation_id) for observation_id in snapshot.observation_ids}
    if not observation_ids:
        return []

    rows = session.execute(
        select(SourceObservation, SourceDocument)
        .join(
            ProviderRunSourceUse,
            ProviderRunSourceUse.id == SourceObservation.source_use_id,
        )
        .join(SourceDocument, SourceDocument.id == ProviderRunSourceUse.document_id)
        .where(
            SourceObservation.job_id == job_id,
            SourceObservation.id.in_(observation_ids),
        )
        .order_by(SourceObservation.retrieved_at, SourceObservation.id)
    ).all()
    return [
        {
            "evidence_id": observation.id,
            "source_type": observation.source_type,
            "trust_class": observation.trust_class,
            "publisher": document.publisher,
            "title": document.title,
            "url": document.canonical_url,
            "excerpt": observation.excerpt,
            "retrieved_at": observation.retrieved_at,
        }
        for observation, document in rows
    ]
