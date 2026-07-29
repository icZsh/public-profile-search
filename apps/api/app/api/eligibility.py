from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from apps.api.app.core.auth import (
    AuthContext,
    require_prototype_admin,
    require_prototype_auth,
)
from apps.api.app.core.db import get_session
from apps.api.app.policy.suppression import is_suppressed
from apps.api.app.schemas.generated import (
    AdminEligibilityVerificationResponse,
    CreateEligibilityVerificationRequest,
    EligibilityDecisionRequest,
    EligibilityVerificationResponse,
)
from apps.api.app.services.eligibility import (
    admin_verification_summary,
    complete_control_verification,
    create_verification,
    decide_verification,
    owner_verification,
    verification_response,
)

router = APIRouter(prefix="/v1")


@router.post(
    "/eligibility-verifications",
    response_model=EligibilityVerificationResponse,
    status_code=201,
)
def create_eligibility_verification(
    body: CreateEligibilityVerificationRequest,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    verification, challenge = create_verification(
        session,
        settings=request.app.state.settings,
        clock=request.app.state.clock,
        user_id=auth.user_id,
        profile_url=body.profile_url,
    )
    response = verification_response(
        verification,
        settings=request.app.state.settings,
        now=request.app.state.clock.now(),
        challenge_value=challenge,
        message=(
            "Temporarily place this challenge in the public GitHub bio, "
            "then verify profile control."
        ),
    )
    session.commit()
    return response


@router.get(
    "/eligibility-verifications/{verification_id}",
    response_model=EligibilityVerificationResponse,
)
def get_eligibility_verification(
    verification_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    verification = owner_verification(
        session,
        verification_id=str(verification_id),
        user_id=auth.user_id,
    )
    response = verification_response(
        verification,
        settings=request.app.state.settings,
        now=request.app.state.clock.now(),
    )
    if is_suppressed(session, verification.identifier_hmac):
        response.update(
            {
                "status": "unavailable",
                "eligibility_reference_id": None,
                "eligibility_expires_at": None,
                "message": "The verification is unavailable.",
            }
        )
    return response


@router.post(
    "/eligibility-verifications/{verification_id}/complete",
    response_model=EligibilityVerificationResponse,
)
def complete_eligibility_verification(
    verification_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
) -> dict[str, object]:
    return complete_control_verification(
        request.app.state.session_factory,
        settings=request.app.state.settings,
        clock=request.app.state.clock,
        safe_fetch_gateway=request.app.state.safe_fetch_factory(),
        verification_id=str(verification_id),
        user_id=auth.user_id,
    )


@router.get(
    "/prototype/eligibility-verifications/{verification_id}",
    response_model=AdminEligibilityVerificationResponse,
)
def get_admin_eligibility_verification(
    verification_id: UUID,
    request: Request,
    _admin: None = Depends(require_prototype_admin),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return admin_verification_summary(
        session,
        settings=request.app.state.settings,
        verification_id=str(verification_id),
    )


@router.post(
    "/prototype/eligibility-verifications/{verification_id}/decision",
    response_model=EligibilityVerificationResponse,
)
def decide_eligibility_verification(
    verification_id: UUID,
    body: EligibilityDecisionRequest,
    request: Request,
    _admin: None = Depends(require_prototype_admin),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    response = decide_verification(
        session,
        settings=request.app.state.settings,
        clock=request.app.state.clock,
        verification_id=str(verification_id),
        decision=body.decision,
        review_code=body.review_code,
        reviewer_id=body.reviewer_id,
    )
    session.commit()
    return response
