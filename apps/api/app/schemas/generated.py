"""Prototype models mirrored from contracts/openapi.yaml.

The contract generation command will own this file before the API is promoted beyond
the local prototype. Route code imports from this boundary and nowhere else.
"""

from datetime import datetime
from typing import Annotated, Literal
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
    trust_class: str
    publisher: str
    title: str
    url: HttpUrl
    excerpt: str
    retrieved_at: datetime


class EvidenceListResponse(BaseModel):
    items: list[EvidenceItemResponse]


FootprintConfidence = Literal["high", "medium_high", "medium", "low"]


class FootprintBriefAccountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID
    platform: str
    handle: str
    profile_url: HttpUrl
    display_name: str | None
    existence_status: Literal[
        "exact_verified",
        "indexed_profile",
        "claimed_unverified",
        "channel_limited",
        "excluded",
    ]
    identity_status: Literal[
        "confirmed",
        "likely",
        "unverified",
        "conflicting",
        "excluded",
    ]
    confidence: FootprintConfidence
    source_ids: list[UUID]
    reasons: list[str]


class FootprintBriefClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: UUID
    predicate: str
    label: str
    value: str
    confidence: FootprintConfidence
    source_ids: list[UUID]
    qualification: str | None


class FootprintIdentityReasonsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supporting: list[str]
    limiting: list[str]


class FootprintCitedTextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    source_ids: list[UUID]


class FootprintNarrativeSectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    body: str
    source_ids: list[UUID]
    highlights: list[FootprintCitedTextResponse] = Field(default_factory=list)


class FootprintDeepIdentityFactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    confidence: FootprintConfidence
    status: Literal[
        "observed",
        "self_described",
        "indexed",
        "likely",
        "independently_unverified",
        "unknown",
    ]
    qualification: str | None
    source_ids: list[UUID]


class FootprintDeepAccountInsightResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    rationale: str
    source_ids: list[UUID]
    public_facts: list[FootprintCitedTextResponse]
    association_reasons: list[FootprintCitedTextResponse]


class FootprintDeepCuratedClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    predicate: str
    label: str
    value: str
    confidence: Literal["high", "medium_high", "medium", "low"]
    status: Literal[
        "confirmed",
        "likely",
        "possible",
        "independently_unverified",
        "contradicted",
        "unknown",
    ]
    source_ids: list[UUID]
    contradicting_source_ids: list[UUID]
    qualification: str | None
    supporting_evidence: list[FootprintCitedTextResponse]
    limiting_evidence: list[FootprintCitedTextResponse]


class FootprintDeepExcludedCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID | None
    label: str
    disposition: Literal[
        "excluded",
        "unverified",
        "derivative",
        "no_exact_hit",
        "separate_cluster",
    ]
    reason: str
    source_ids: list[UUID]


class FootprintDeepChannelCoverageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str
    status: Literal[
        "confirmed",
        "likely",
        "candidate",
        "unverified",
        "no_exact_hit",
        "channel_limited",
        "excluded",
        "not_checked",
    ]
    detail: str
    source_ids: list[UUID]


class FootprintDeepProfileAnswerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None
    confidence: FootprintConfidence | None
    basis: Literal[
        "observed",
        "self_described",
        "indexed",
        "inferred",
        "mixed",
        "unknown",
    ]
    explanation: str
    source_ids: list[UUID]


class FootprintDeepProfileTraitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    confidence: FootprintConfidence
    basis: Literal[
        "observed",
        "self_described",
        "indexed",
        "inferred",
        "mixed",
    ]
    explanation: str
    source_ids: list[UUID]


class FootprintDeepProfileUnknownResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: Literal[
        "identity",
        "location",
        "occupation",
        "education",
        "interests",
        "likes",
        "dislikes",
        "projects",
        "other",
    ]
    explanation: str
    source_ids: list[UUID]


class FootprintDeepTimelineEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_type: Literal["work", "education"]
    title: str
    organization: str | None
    timeframe: str | None
    currentness: Literal["current", "recent", "historical", "unclear"]
    confidence: FootprintConfidence
    basis: Literal["observed", "self_described", "indexed", "inferred", "mixed"]
    explanation: str
    source_ids: list[UUID]


class FootprintDeepSubjectProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: FootprintDeepProfileAnswerResponse
    location: FootprintDeepProfileAnswerResponse
    occupation: FootprintDeepProfileAnswerResponse
    education: FootprintDeepProfileAnswerResponse
    interests: list[FootprintDeepProfileTraitResponse]
    likes: list[FootprintDeepProfileTraitResponse]
    dislikes: list[FootprintDeepProfileTraitResponse]
    unknowns: list[FootprintDeepProfileUnknownResponse]
    career_timeline: list[FootprintDeepTimelineEntryResponse] = Field(default_factory=list)


class FootprintDeepStoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["deep-story-v2", "deep-story-v3", "deep-story-v4"]
    overview: str
    overview_source_ids: list[UUID]
    conclusion: str
    conclusion_source_ids: list[UUID]
    overall_confidence: FootprintConfidence
    likely_public_identity: str | None
    broad_location: str | None
    major_boundary: str
    identity_facts: list[FootprintDeepIdentityFactResponse]
    account_insights: list[FootprintDeepAccountInsightResponse]
    curated_claims: list[FootprintDeepCuratedClaimResponse]
    excluded_candidates: list[FootprintDeepExcludedCandidateResponse]
    channel_coverage: list[FootprintDeepChannelCoverageResponse]
    next_verification_steps: list[FootprintCitedTextResponse]
    subject_profile: FootprintDeepSubjectProfileResponse | None = None


class FootprintSynthesisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["deterministic", "llm_grounded"]
    status: Literal["complete", "fallback"]
    provider: Literal["openai", "openrouter"] | None = None
    model: str | None
    prompt_version: str
    fallback_reason: str | None


class FootprintBriefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    report_type: Literal["account_centric", "person_centric"]
    subject: str
    summary: str
    overall_identity_status: Literal["confirmed", "likely", "unverified"]
    accounts: list[FootprintBriefAccountResponse]
    claims: list[FootprintBriefClaimResponse]
    identity_reasons: FootprintIdentityReasonsResponse
    narrative_sections: list[FootprintNarrativeSectionResponse] = Field(default_factory=list)
    deep_story: FootprintDeepStoryResponse | None = None
    synthesis: FootprintSynthesisResponse | None = None
    limitations: list[str]
    generated_at: datetime


FootprintPlatformValue = Literal[
    "github",
    "instagram",
    "linkedin",
    "reddit",
    "tiktok",
    "twitter",
    "x",
    "youtube",
    "other",
]


class PlatformIdentifierFootprintSeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["platform_identifier"]
    platform: FootprintPlatformValue
    identifier_type: Literal["handle"]
    identifier: str = Field(min_length=1, max_length=64)


class BareHandleFootprintSeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["bare_handle"]
    platform: None = None
    identifier_type: Literal["handle"]
    identifier: str = Field(min_length=1, max_length=64)


class ProfileUrlFootprintSeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["profile_url"]
    profile_url: str = Field(min_length=1, max_length=300)
    platform: FootprintPlatformValue | None = None
    identifier_type: Literal["handle"] = "handle"
    identifier: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def optional_assertions_cannot_be_null(self) -> "ProfileUrlFootprintSeedRequest":
        if "platform" in self.model_fields_set and self.platform is None:
            raise ValueError("platform must be omitted instead of null")
        if "identifier" in self.model_fields_set and self.identifier is None:
            raise ValueError("identifier must be omitted instead of null")
        return self


FootprintSeedRequest = Annotated[
    PlatformIdentifierFootprintSeedRequest
    | BareHandleFootprintSeedRequest
    | ProfileUrlFootprintSeedRequest,
    Field(discriminator="kind"),
]


class PlatformIdentifierFootprintSeedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["platform_identifier"]
    platform: FootprintPlatformValue
    identifier_type: Literal["handle"]
    identifier: str = Field(min_length=1, max_length=64)


class BareHandleFootprintSeedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["bare_handle"]
    platform: None
    identifier_type: Literal["handle"]
    identifier: str = Field(min_length=1, max_length=64)


class ProfileUrlFootprintSeedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["profile_url"]
    profile_url: HttpUrl = Field(max_length=300)
    platform: FootprintPlatformValue
    identifier_type: Literal["handle"]
    identifier: str = Field(min_length=1, max_length=64)


FootprintSeedResponse = Annotated[
    PlatformIdentifierFootprintSeedResponse
    | BareHandleFootprintSeedResponse
    | ProfileUrlFootprintSeedResponse,
    Field(discriminator="kind"),
]


class CreateFootprintJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: FootprintSeedRequest
    search_mode: Literal["quick", "deep"] = "quick"
    locale: Literal["en-US", "zh-CN"] = "en-US"


class FootprintCoverageResponse(BaseModel):
    selected: int = Field(ge=0)
    completed: int = Field(ge=0)
    claimed: int = Field(ge=0)
    available: int = Field(ge=0)
    unknown: int = Field(ge=0)
    illegal: int = Field(ge=0)


class FootprintCatalogResponse(BaseModel):
    engine: Literal["maigret"]
    package_version: str | None
    database_checksum: str | None
    profile: str | None


class FootprintDeepProgressResponse(BaseModel):
    current_phase: Literal[
        "queued",
        "account_scan",
        "awaiting_anchor",
        "professional_enrichment",
        "report_generation",
        "finalizing",
        "complete",
    ]
    phase_started_at: datetime
    finished_at: datetime | None


class FootprintJobResponse(BaseModel):
    job_id: UUID
    status: Literal[
        "queued",
        "discovering",
        "ready",
        "ready_partial",
        "no_candidates",
        "failed",
        "cancelled",
    ]
    exploration_status: Literal[
        "idle",
        "running",
        "awaiting_anchor",
        "completed",
        "cancelled",
    ]
    deep_progress: FootprintDeepProgressResponse | None
    seed: FootprintSeedResponse
    search_mode: Literal["quick", "deep"] | None
    coverage: FootprintCoverageResponse
    catalog: FootprintCatalogResponse
    events_url: str
    candidates_url: str
    accepted_at: datetime
    deadline_at: datetime


class SelectFootprintAnchorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID


class SelectedFootprintAnchorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: UUID
    platform: str
    handle: str
    profile_url: HttpUrl
    display_name: str | None
    selection_state: Literal["included"]


class SelectFootprintAnchorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: FootprintJobResponse
    selected_anchor: SelectedFootprintAnchorResponse


class CandidateEvidenceResponse(BaseModel):
    site_check_id: UUID
    site_name: str
    status: Literal["CLAIMED", "AVAILABLE", "UNKNOWN", "ILLEGAL"]
    discovery_method: Literal["username_catalog_probe", "similar_handle_result"]
    observed_at: datetime


class AccountCandidateResponse(BaseModel):
    candidate_id: UUID
    platform: str
    handle: str
    profile_url: HttpUrl
    display_name: str | None
    relationship: Literal["unresolved"]
    identity_tier: Literal["possible", "weak"]
    selection_state: Literal["undecided", "included", "excluded"]
    anchor_eligible: bool
    is_similar: bool
    profile_data: dict[str, object]
    discovered_at: datetime
    evidence: list[CandidateEvidenceResponse]


class CandidateListResponse(BaseModel):
    items: list[AccountCandidateResponse]
    extracted_identifier_count: int = Field(ge=0)
