from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.entities import EligibilityVerification


def get_valid_eligibility(
    session: Session,
    *,
    verification_id: str,
    user_id: str,
    identifier_hmac: str,
    now: datetime,
    policy_version: str,
    provider_id: str | None = None,
) -> EligibilityVerification | None:
    statement = select(EligibilityVerification).where(
        EligibilityVerification.id == verification_id,
        EligibilityVerification.user_id == user_id,
        EligibilityVerification.identifier_hmac == identifier_hmac,
        EligibilityVerification.eligibility_state.in_(
            {"eligible_verified_self", "eligible_manual_public_allowlist"}
        ),
        EligibilityVerification.purpose == "self_audit",
        EligibilityVerification.policy_version == policy_version,
        EligibilityVerification.verified_at.is_not(None),
        EligibilityVerification.expires_at > now,
        EligibilityVerification.revoked_at.is_(None),
    )
    if provider_id is not None:
        statement = statement.where(EligibilityVerification.provider_id == provider_id)
    return session.scalar(statement)


def has_valid_eligibility(
    session: Session,
    *,
    verification_id: str,
    user_id: str,
    identifier_hmac: str,
    now: datetime,
    policy_version: str,
    provider_id: str | None = None,
) -> bool:
    verification = get_valid_eligibility(
        session,
        verification_id=verification_id,
        user_id=user_id,
        identifier_hmac=identifier_hmac,
        now=now,
        policy_version=policy_version,
        provider_id=provider_id,
    )
    return verification is not None
