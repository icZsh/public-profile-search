from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.crypto import encrypt_value, keyed_hmac
from apps.api.app.models.entities import EligibilityVerification


def ensure_prototype_seed(session: Session, settings, now) -> None:
    verification_id = str(settings.fixture_eligibility_reference_id)
    existing = session.scalar(
        select(EligibilityVerification).where(EligibilityVerification.id == verification_id)
    )
    if existing:
        existing.provider_id = "fixture_primary_v1"
        existing.canonicalization_version = "profile-url-v1"
        existing.verification_method = "synthetic_seed"
        existing.attempt_count = existing.attempt_count or 0
        existing.created_at = existing.created_at or existing.verified_at or now
        if not existing.canonical_url_ciphertext:
            existing.canonical_url_ciphertext = encrypt_value(
                settings.fixture_url,
                settings.profile_url_encryption_key,
            )
        return
    session.add(
        EligibilityVerification(
            id=verification_id,
            user_id=str(settings.prototype_user_id),
            identifier_hmac=keyed_hmac(settings.fixture_url, settings.prototype_hmac_key),
            provider_id="fixture_primary_v1",
            canonicalization_version="profile-url-v1",
            canonical_url_ciphertext=encrypt_value(
                settings.fixture_url,
                settings.profile_url_encryption_key,
            ),
            provider_subject_hmac=None,
            verification_method="synthetic_seed",
            challenge_token_hmac=None,
            challenge_expires_at=None,
            review_expires_at=None,
            attempt_count=0,
            last_checked_at=None,
            created_at=now,
            control_verified_at=now,
            reviewed_at=now,
            reviewer_id="synthetic-seed",
            review_code="synthetic_fixture",
            eligibility_state="eligible_verified_self",
            purpose="self_audit",
            policy_version=settings.policy_version,
            verified_at=now,
            expires_at=now + timedelta(days=365),
            revoked_at=None,
        )
    )
