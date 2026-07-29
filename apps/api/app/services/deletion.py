from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.app.models.entities import (
    AnalysisRevision,
    Claim,
    ClaimEvidence,
    CollectionSnapshot,
    IdempotencyRecord,
    JobAttempt,
    JobDeletionTombstone,
    JobEvent,
    OutboxMessage,
    ProviderAttempt,
    ProviderRun,
    ProviderRunSourceUse,
    ReportAccessState,
    ReportRevision,
    SearchJob,
    SourceDocument,
    SourceObservation,
)
from apps.api.app.services.jobs import owner_job


def delete_job(session: Session, *, job_id: str, user_id: str, now) -> None:
    job = owner_job(session, job_id=job_id, user_id=user_id, for_update=True)
    job.acceptance_epoch += 1
    report_ids = session.scalars(
        select(ReportRevision.id).where(ReportRevision.job_id == job_id)
    ).all()
    claim_ids = session.scalars(select(Claim.id).where(Claim.job_id == job_id)).all()
    run_ids = session.scalars(select(ProviderRun.id).where(ProviderRun.job_id == job_id)).all()
    source_use_rows = (
        session.execute(
            select(ProviderRunSourceUse.id, ProviderRunSourceUse.document_id).where(
                ProviderRunSourceUse.provider_run_id.in_(run_ids)
            )
        ).all()
        if run_ids
        else []
    )
    source_use_ids = [row.id for row in source_use_rows]
    document_ids = list({row.document_id for row in source_use_rows})
    session.add(
        JobDeletionTombstone(
            job_id=job_id,
            write_fence=job.acceptance_epoch,
            deleted_at=now,
            expires_at=now + timedelta(days=7),
        )
    )
    if claim_ids:
        session.execute(delete(ClaimEvidence).where(ClaimEvidence.claim_id.in_(claim_ids)))
    session.execute(delete(Claim).where(Claim.job_id == job_id))
    if report_ids:
        session.execute(
            delete(ReportAccessState).where(ReportAccessState.report_id.in_(report_ids))
        )
    session.execute(delete(ReportRevision).where(ReportRevision.job_id == job_id))
    session.execute(delete(AnalysisRevision).where(AnalysisRevision.job_id == job_id))
    session.execute(delete(CollectionSnapshot).where(CollectionSnapshot.job_id == job_id))
    session.execute(delete(SourceObservation).where(SourceObservation.job_id == job_id))
    if source_use_ids:
        session.execute(
            delete(ProviderRunSourceUse).where(ProviderRunSourceUse.id.in_(source_use_ids))
        )
    if run_ids:
        session.execute(delete(ProviderAttempt).where(ProviderAttempt.provider_run_id.in_(run_ids)))
    session.execute(delete(ProviderRun).where(ProviderRun.job_id == job_id))
    session.execute(
        delete(OutboxMessage).where(
            OutboxMessage.payload["provider_run_id"].as_string().in_(run_ids)
        )
    )
    session.execute(delete(JobEvent).where(JobEvent.job_id == job_id))
    session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.job_id == job_id))
    session.execute(delete(JobAttempt).where(JobAttempt.job_id == job_id))
    session.execute(delete(SearchJob).where(SearchJob.id == job_id))
    if document_ids:
        still_referenced = (
            select(ProviderRunSourceUse.id)
            .where(ProviderRunSourceUse.document_id == SourceDocument.id)
            .exists()
        )
        session.execute(
            delete(SourceDocument).where(
                SourceDocument.id.in_(document_ids),
                ~still_referenced,
            )
        )
