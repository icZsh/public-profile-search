from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.crypto import UnsafePrototypeUrl, canonicalize_profile_url, keyed_hmac
from apps.api.app.core.errors import ApiError
from apps.api.app.models.entities import (
    EligibilityVerification,
    JobAttempt,
    ReportAccessState,
    SearchJob,
    SubjectSuppressionRecord,
)
from apps.api.app.policy.suppression import lock_identifier_scope


def suppress_profile(session: Session, *, settings, profile_url: str, now) -> None:
    try:
        target = canonicalize_profile_url(profile_url, fixture_url=settings.fixture_url)
    except UnsafePrototypeUrl as exc:
        raise ApiError(
            422,
            "unsupported_provider",
            "Enter an allowlisted direct public profile URL.",
        ) from exc
    identifier_hmac = keyed_hmac(target.canonical_url, settings.prototype_hmac_key)
    lock_identifier_scope(session, identifier_hmac)
    record = session.scalar(
        select(SubjectSuppressionRecord).where(
            SubjectSuppressionRecord.identifier_hmac == identifier_hmac
        )
    )
    if not record:
        session.add(
            SubjectSuppressionRecord(
                identifier_hmac=identifier_hmac,
                status="active",
                created_at=now,
                expires_at=None,
            )
        )
    else:
        record.status = "active"

    verifications = session.scalars(
        select(EligibilityVerification)
        .where(
            EligibilityVerification.identifier_hmac == identifier_hmac,
            EligibilityVerification.revoked_at.is_(None),
        )
        .with_for_update()
    ).all()
    for verification in verifications:
        verification.eligibility_state = "suppressed"
        verification.revoked_at = now
        verification.challenge_token_hmac = None

    jobs = session.scalars(
        select(SearchJob)
        .where(SearchJob.normalized_identifier_hmac == identifier_hmac)
        .with_for_update()
    ).all()
    for job in jobs:
        job.acceptance_epoch += 1
        if job.status not in {"ready", "ready_partial", "insufficient_evidence", "failed"}:
            job.status = "policy_blocked"
        attempt = session.get(JobAttempt, job.active_attempt_id)
        if attempt and attempt.current_report_revision_id:
            access = session.get(ReportAccessState, attempt.current_report_revision_id)
            if access:
                access.state = "revoked_suppression"
                access.updated_at = now


suppress_fixture = suppress_profile
