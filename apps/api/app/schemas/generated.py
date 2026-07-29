"""Prototype models mirrored from contracts/openapi.yaml.

The contract generation command will own this file before the API is promoted beyond
the local prototype. Route code imports from this boundary and nowhere else.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class CreateSearchJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_url: str = Field(min_length=1, max_length=300)
    purpose: Literal["self_audit"]
    target_relationship: Literal["self"]
    eligibility_reference_id: UUID
    attestation_policy_version: str
    locale: Literal["en", "zh-CN"] = "en"


class SearchJobResponse(BaseModel):
    job_id: UUID
    status: str
    collection_cutoff_at: datetime
    fallback_at: datetime
    deadline_at: datetime
    events_url: str


class PrototypeConfigResponse(BaseModel):
    fixture_url: HttpUrl
    eligibility_reference_id: UUID
    purpose: Literal["self_audit"] = "self_audit"
    attestation_policy_version: str
    allowed_profile_hosts: list[str]
    github_provider_enabled: bool


class SuppressionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_url: str = Field(min_length=1, max_length=300)


class CreateEligibilityVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_url: str = Field(min_length=1, max_length=300)
    purpose: Literal["self_audit"]


class EligibilityVerificationResponse(BaseModel):
    verification_id: UUID
    status: Literal[
        "pending_control",
        "review_pending",
        "eligible",
        "expired",
        "unavailable",
    ]
    purpose: Literal["self_audit"]
    provider_id: str
    canonical_profile_url: HttpUrl
    policy_version: str
    challenge_value: str | None = None
    challenge_expires_at: datetime | None = None
    review_expires_at: datetime | None = None
    eligibility_reference_id: UUID | None = None
    eligibility_expires_at: datetime | None = None
    attempts_remaining: int = Field(ge=0)
    message: str | None = None


class EligibilityDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "deny"]
    review_code: Literal[
        "adult_public_professional_context_confirmed",
        "unable_to_confirm_scope",
    ]
    reviewer_id: str = Field(
        min_length=3,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )

    @model_validator(mode="after")
    def decision_matches_review_code(self) -> "EligibilityDecisionRequest":
        expected = (
            "adult_public_professional_context_confirmed"
            if self.decision == "approve"
            else "unable_to_confirm_scope"
        )
        if self.review_code != expected:
            raise ValueError("review_code does not match decision")
        return self


class AdminEligibilityVerificationResponse(BaseModel):
    verification_id: UUID
    canonical_profile_url: HttpUrl
    provider_id: str
    purpose: str
    internal_state: str
    control_verified_at: datetime | None = None
    review_expires_at: datetime | None = None
    policy_version: str


class ClaimResponse(BaseModel):
    claim_id: UUID
    predicate: str
    label: str
    value: str
    confidence: str
    evidence_ids: list[UUID]


class FastBriefResponse(BaseModel):
    job_id: UUID
    subject: str
    summary: str
    claims: list[ClaimResponse]
    limitations: list[str]
    generated_at: datetime


class EvidenceItemResponse(BaseModel):
    evidence_id: UUID
    source_type: str
    title: str
    url: HttpUrl
    excerpt: str
    retrieved_at: datetime


class EvidenceListResponse(BaseModel):
    items: list[EvidenceItemResponse]
