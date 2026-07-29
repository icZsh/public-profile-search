import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.core.crypto import (
    UnsafePrototypeUrl,
    canonicalize_profile_url,
    decrypt_value,
    encrypt_value,
    hmac_matches,
    keyed_hmac,
)
from apps.api.app.core.errors import ApiError
from apps.api.app.models.entities import EligibilityVerification, new_id
from apps.api.app.policy.suppression import (
    is_suppressed,
    lock_identifier_scope,
)
from workers.providers.github_public import (
    GitHubProfileError,
    fetch_github_public_profile,
)

CHALLENGE_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])(tracebrief-[A-Za-z0-9_-]{32})(?![A-Za-z0-9_-])")
PENDING_STATES = {"verification_pending", "control_verified_review_pending"}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _is_expired(verification: EligibilityVerification, now: datetime) -> bool:
    if verification.eligibility_state == "verification_pending":
        expiry = _as_utc(verification.challenge_expires_at)
    elif verification.eligibility_state == "control_verified_review_pending":
        expiry = _as_utc(verification.review_expires_at)
    else:
        expiry = _as_utc(verification.expires_at)
    return bool(expiry and expiry <= now)


def _public_status(verification: EligibilityVerification, now: datetime) -> str:
    if _is_expired(verification, now):
        return "expired"
    return {
        "verification_pending": "pending_control",
        "control_verified_review_pending": "review_pending",
        "eligible_verified_self": "eligible",
    }.get(verification.eligibility_state, "unavailable")


def verification_response(
    verification: EligibilityVerification,
    *,
    settings,
    now: datetime,
    challenge_value: str | None = None,
    message: str | None = None,
) -> dict[str, object]:
    status = _public_status(verification, now)
    canonical_url = decrypt_value(
        verification.canonical_url_ciphertext,
        settings.profile_url_encryption_key,
    )
    response: dict[str, object] = {
        "verification_id": verification.id,
        "status": status,
        "purpose": verification.purpose,
        "provider_id": verification.provider_id,
        "canonical_profile_url": canonical_url,
        "policy_version": verification.policy_version,
        "challenge_value": challenge_value,
        "challenge_expires_at": verification.challenge_expires_at,
        "review_expires_at": verification.review_expires_at,
        "eligibility_reference_id": (verification.id if status == "eligible" else None),
        "eligibility_expires_at": (verification.expires_at if status == "eligible" else None),
        "attempts_remaining": max(
            0, settings.eligibility_max_attempts - verification.attempt_count
        ),
        "message": message,
    }
    return response


def create_verification(
    session: Session,
    *,
    settings,
    clock,
    user_id: str,
    profile_url: str,
) -> tuple[EligibilityVerification, str]:
    if not settings.github_provider_enabled:
        raise ApiError(
            503,
            "provider_disabled",
            "The GitHub evaluation provider is temporarily unavailable.",
        )
    try:
        target = canonicalize_profile_url(
            profile_url,
            fixture_url=settings.fixture_url,
            allow_fixture=False,
        )
    except UnsafePrototypeUrl as exc:
        raise ApiError(
            422,
            "unsupported_provider",
            "Enter a direct public GitHub profile URL.",
        ) from exc

    now = clock.now()
    identifier_hmac = keyed_hmac(target.canonical_url, settings.prototype_hmac_key)
    lock_identifier_scope(session, identifier_hmac)
    if is_suppressed(session, identifier_hmac):
        raise ApiError(404, "result_unavailable", "The result is unavailable.")

    existing = session.scalars(
        select(EligibilityVerification)
        .where(
            EligibilityVerification.user_id == user_id,
            EligibilityVerification.identifier_hmac == identifier_hmac,
            EligibilityVerification.eligibility_state.in_(PENDING_STATES),
            EligibilityVerification.revoked_at.is_(None),
        )
        .with_for_update()
    ).all()
    for prior in existing:
        prior.eligibility_state = "superseded"
        prior.revoked_at = now
        prior.challenge_token_hmac = None

    challenge = f"tracebrief-{secrets.token_urlsafe(24)}"
    challenge_expiry = now + timedelta(minutes=settings.eligibility_challenge_ttl_minutes)
    verification = EligibilityVerification(
        id=new_id(),
        user_id=user_id,
        identifier_hmac=identifier_hmac,
        provider_id=target.provider_id,
        canonicalization_version=target.canonicalization_version,
        canonical_url_ciphertext=encrypt_value(
            target.canonical_url,
            settings.profile_url_encryption_key,
        ),
        provider_subject_hmac=None,
        eligibility_state="verification_pending",
        purpose="self_audit",
        policy_version=settings.policy_version,
        verification_method="github_bio_challenge_v1",
        challenge_token_hmac=keyed_hmac(
            f"eligibility-challenge-v1:{challenge}",
            settings.prototype_hmac_key,
        ),
        challenge_expires_at=challenge_expiry,
        review_expires_at=None,
        attempt_count=0,
        last_checked_at=None,
        created_at=now,
        control_verified_at=None,
        reviewed_at=None,
        reviewer_id=None,
        review_code=None,
        verified_at=None,
        expires_at=challenge_expiry,
        revoked_at=None,
    )
    session.add(verification)
    session.flush()
    return verification, challenge


def owner_verification(
    session: Session,
    *,
    verification_id: str,
    user_id: str,
    for_update: bool = False,
) -> EligibilityVerification:
    statement = select(EligibilityVerification).where(
        EligibilityVerification.id == verification_id,
        EligibilityVerification.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    verification = session.scalar(statement)
    if not verification:
        raise ApiError(
            404,
            "verification_not_found",
            "The verification was not found.",
        )
    return verification


def _locked_owner_verification(
    session: Session,
    *,
    verification_id: str,
    user_id: str,
) -> EligibilityVerification:
    preview = owner_verification(
        session,
        verification_id=verification_id,
        user_id=user_id,
    )
    lock_identifier_scope(session, preview.identifier_hmac)
    return owner_verification(
        session,
        verification_id=verification_id,
        user_id=user_id,
        for_update=True,
    )


def complete_control_verification(
    session_factory: sessionmaker[Session],
    *,
    settings,
    clock,
    safe_fetch_gateway,
    verification_id: str,
    user_id: str,
) -> dict[str, object]:
    now = clock.now()
    pending_error: ApiError | None = None
    snapshot: dict[str, object] | None = None
    with session_factory() as session, session.begin():
        verification = _locked_owner_verification(
            session,
            verification_id=verification_id,
            user_id=user_id,
        )
        status = _public_status(verification, now)
        if status == "review_pending" or status == "eligible":
            return verification_response(verification, settings=settings, now=now)
        if status != "pending_control":
            pending_error = ApiError(
                410,
                "verification_expired",
                "This verification is no longer available.",
            )
        elif is_suppressed(session, verification.identifier_hmac):
            verification.eligibility_state = "suppressed"
            verification.revoked_at = now
            verification.challenge_token_hmac = None
            pending_error = ApiError(
                404,
                "result_unavailable",
                "The result is unavailable.",
            )
        elif verification.attempt_count >= settings.eligibility_max_attempts:
            verification.eligibility_state = "verification_failed"
            verification.revoked_at = now
            verification.challenge_token_hmac = None
            pending_error = ApiError(
                410,
                "verification_unavailable",
                "This verification is no longer available.",
            )
        else:
            last_checked = _as_utc(verification.last_checked_at)
            if last_checked:
                retry_at = last_checked + timedelta(
                    seconds=settings.eligibility_check_cooldown_seconds
                )
                if retry_at > now:
                    retry_after = max(1, int((retry_at - now).total_seconds()))
                    pending_error = ApiError(
                        429,
                        "verification_cooldown",
                        "Wait briefly before checking the profile again.",
                        headers={"Retry-After": str(retry_after)},
                    )
            if pending_error is None:
                verification.attempt_count += 1
                verification.last_checked_at = now
                snapshot = {
                    "generation": verification.attempt_count,
                    "canonical_url_ciphertext": verification.canonical_url_ciphertext,
                    "challenge_token_hmac": verification.challenge_token_hmac,
                }

    if pending_error:
        raise pending_error
    if not snapshot:
        raise ApiError(409, "verification_unavailable", "The verification is unavailable.")

    canonical_url = decrypt_value(
        str(snapshot["canonical_url_ciphertext"]),
        settings.profile_url_encryption_key,
    )
    try:
        profile = fetch_github_public_profile(safe_fetch_gateway, canonical_url)
    except GitHubProfileError as exc:
        if exc.status == "rate_limited":
            raise ApiError(
                429,
                "provider_rate_limited",
                "GitHub is rate limiting profile checks. Try again later.",
                headers={"Retry-After": "60"},
            ) from exc
        if exc.status == "no_result":
            raise ApiError(
                404,
                "verification_unavailable",
                "The public profile could not be verified.",
            ) from exc
        raise ApiError(
            503,
            "service_unavailable",
            "The public profile could not be checked safely.",
        ) from exc

    now = clock.now()
    with session_factory() as session, session.begin():
        verification = _locked_owner_verification(
            session,
            verification_id=verification_id,
            user_id=user_id,
        )
        if verification.eligibility_state != "verification_pending":
            return verification_response(verification, settings=settings, now=now)
        if verification.attempt_count != snapshot["generation"]:
            return verification_response(
                verification,
                settings=settings,
                now=now,
                message="A newer profile check is already in progress.",
            )
        if _is_expired(verification, now):
            verification.eligibility_state = "expired"
            verification.revoked_at = now
            verification.challenge_token_hmac = None
            return verification_response(verification, settings=settings, now=now)
        if is_suppressed(session, verification.identifier_hmac):
            verification.eligibility_state = "suppressed"
            verification.revoked_at = now
            verification.challenge_token_hmac = None
            return verification_response(verification, settings=settings, now=now)

        expected_hmac = str(snapshot["challenge_token_hmac"] or "")
        found = any(
            hmac_matches(
                keyed_hmac(
                    f"eligibility-challenge-v1:{candidate}",
                    settings.prototype_hmac_key,
                ),
                expected_hmac,
            )
            for candidate in CHALLENGE_PATTERN.findall(profile.bio)
        )
        if found:
            verification.eligibility_state = "control_verified_review_pending"
            verification.provider_subject_hmac = keyed_hmac(
                f"github-account-v1:{profile.account_id}",
                settings.prototype_hmac_key,
            )
            verification.control_verified_at = now
            verification.review_expires_at = now + timedelta(
                hours=settings.eligibility_review_ttl_hours
            )
            verification.expires_at = verification.review_expires_at
            verification.challenge_token_hmac = None
            return verification_response(
                verification,
                settings=settings,
                now=now,
                message=(
                    "Profile control is confirmed. An authorized local operator "
                    "must still approve eligibility."
                ),
            )

        if verification.attempt_count >= settings.eligibility_max_attempts:
            verification.eligibility_state = "verification_failed"
            verification.revoked_at = now
            verification.challenge_token_hmac = None
            verification.expires_at = now
            return verification_response(
                verification,
                settings=settings,
                now=now,
                message="The challenge could not be confirmed.",
            )
        return verification_response(
            verification,
            settings=settings,
            now=now,
            message="The challenge was not found in the public GitHub bio yet.",
        )


def admin_verification_summary(
    session: Session,
    *,
    settings,
    verification_id: str,
) -> dict[str, object]:
    verification = session.get(EligibilityVerification, verification_id)
    if not verification:
        raise ApiError(
            404,
            "verification_not_found",
            "The verification was not found.",
        )
    return {
        "verification_id": verification.id,
        "canonical_profile_url": decrypt_value(
            verification.canonical_url_ciphertext,
            settings.profile_url_encryption_key,
        ),
        "provider_id": verification.provider_id,
        "purpose": verification.purpose,
        "internal_state": verification.eligibility_state,
        "control_verified_at": verification.control_verified_at,
        "review_expires_at": verification.review_expires_at,
        "policy_version": verification.policy_version,
    }


def decide_verification(
    session: Session,
    *,
    settings,
    clock,
    verification_id: str,
    decision: str,
    review_code: str,
    reviewer_id: str,
) -> dict[str, object]:
    preview = session.get(EligibilityVerification, verification_id)
    if not preview:
        raise ApiError(
            404,
            "verification_not_found",
            "The verification was not found.",
        )
    lock_identifier_scope(session, preview.identifier_hmac)
    verification = session.scalar(
        select(EligibilityVerification)
        .where(EligibilityVerification.id == verification_id)
        .with_for_update()
    )
    if not verification:
        raise ApiError(
            404,
            "verification_not_found",
            "The verification was not found.",
        )
    now = clock.now()
    if verification.eligibility_state == "eligible_verified_self" and decision == "approve":
        return verification_response(verification, settings=settings, now=now)
    if (
        verification.eligibility_state != "control_verified_review_pending"
        or _is_expired(verification, now)
        or verification.provider_subject_hmac is None
    ):
        raise ApiError(
            409,
            "verification_unavailable",
            "This verification is not ready for an eligibility decision.",
        )
    if is_suppressed(session, verification.identifier_hmac):
        verification.eligibility_state = "suppressed"
        verification.revoked_at = now
        verification.challenge_token_hmac = None
        return verification_response(
            verification,
            settings=settings,
            now=now,
            message="The verification is unavailable.",
        )

    expected_code = (
        "adult_public_professional_context_confirmed"
        if decision == "approve"
        else "unable_to_confirm_scope"
    )
    if review_code != expected_code:
        raise ApiError(422, "invalid_request", "The review decision is invalid.")

    verification.reviewed_at = now
    verification.reviewer_id = reviewer_id
    verification.review_code = review_code
    if decision == "approve":
        verification.eligibility_state = "eligible_verified_self"
        verification.verified_at = now
        verification.expires_at = now + timedelta(hours=settings.eligibility_approval_ttl_hours)
        verification.revoked_at = None
        return verification_response(
            verification,
            settings=settings,
            now=now,
            message="Eligibility was approved for this local self-audit.",
        )

    verification.eligibility_state = "ineligible"
    verification.revoked_at = now
    verification.expires_at = now
    return verification_response(
        verification,
        settings=settings,
        now=now,
        message="The verification is unavailable.",
    )
