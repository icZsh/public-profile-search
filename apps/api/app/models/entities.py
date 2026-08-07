from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class EligibilityVerification(Base):
    __tablename__ = "eligibility_verification"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    identifier_hmac: Mapped[str] = mapped_column(String(64), index=True)
    provider_id: Mapped[str] = mapped_column(String(80))
    canonicalization_version: Mapped[str] = mapped_column(String(32))
    canonical_url_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_subject_hmac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_method: Mapped[str] = mapped_column(String(64))
    challenge_token_hmac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    challenge_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    control_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    review_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    eligibility_state: Mapped[str] = mapped_column(String(48))
    purpose: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(32))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SearchJob(Base):
    __tablename__ = "search_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    retry_of_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    normalized_identifier_hmac: Mapped[str] = mapped_column(String(64), index=True)
    canonical_input_url_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_provider_id: Mapped[str] = mapped_column(String(80))
    canonicalization_version: Mapped[str] = mapped_column(String(32))
    eligibility_verification_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("eligibility_verification.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    job_kind: Mapped[str] = mapped_column(String(40), default="fast_brief")
    seed_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    seed_platform: Mapped[str | None] = mapped_column(String(80), nullable=True)
    seed_identifier_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    seed_identifier: Mapped[str | None] = mapped_column(String(160), nullable=True)
    normalized_seed: Mapped[str | None] = mapped_column(String(240), nullable=True)
    search_mode: Mapped[str | None] = mapped_column(String(24), nullable=True)
    catalog_profile: Mapped[str | None] = mapped_column(String(40), nullable=True)
    catalog_snapshot_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("maigret_catalog_snapshot.id", ondelete="RESTRICT"),
        nullable=True,
    )
    exploration_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    purpose: Mapped[str] = mapped_column(String(64))
    fixture_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    active_attempt_id: Mapped[str] = mapped_column(String(36))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collection_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fallback_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completion_policy_id: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(32))
    locale: Mapped[str] = mapped_column(String(16), default="en")
    acceptance_epoch: Mapped[int] = mapped_column(Integer, default=1)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobAttempt(Base):
    __tablename__ = "job_attempt"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("search_job.id", ondelete="CASCADE"), unique=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40))
    collection_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_analysis_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_report_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)


class ProviderRun(Base):
    __tablename__ = "provider_run"
    __table_args__ = (
        UniqueConstraint("attempt_id", "logical_run_id", name="uq_provider_logical_run"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("search_job.id", ondelete="CASCADE"), index=True
    )
    attempt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("job_attempt.id", ondelete="CASCADE")
    )
    logical_run_id: Mapped[str] = mapped_column(String(80))
    provider_id: Mapped[str] = mapped_column(String(80))
    parent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    query_config: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    required_for_finalization: Mapped[bool] = mapped_column(Boolean, default=True)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acceptance_epoch: Mapped[int] = mapped_column(Integer, default=1)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProviderAttempt(Base):
    __tablename__ = "provider_attempt"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("provider_run.id", ondelete="CASCADE"), index=True
    )
    generation: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(48))
    completion_disposition: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class GroundedSynthesisResult(Base):
    __tablename__ = "grounded_synthesis_result"

    provider_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("provider_run.id", ondelete="CASCADE"),
        primary_key=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("search_job.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(64))
    input_checksum: Mapped[str] = mapped_column(String(64))
    output: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    usage: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MaigretCatalogSnapshot(Base):
    __tablename__ = "maigret_catalog_snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    package_version: Mapped[str] = mapped_column(String(32))
    upstream_revision: Mapped[str] = mapped_column(String(64))
    database_checksum: Mapped[str] = mapped_column(String(64), index=True)
    manifest_checksum: Mapped[str] = mapped_column(String(64), unique=True)
    catalog_site_count: Mapped[int] = mapped_column(Integer)
    selection_policy: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MaigretScanRun(Base):
    __tablename__ = "maigret_scan_run"

    provider_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("provider_run.id", ondelete="CASCADE"),
        primary_key=True,
    )
    catalog_snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("maigret_catalog_snapshot.id", ondelete="RESTRICT"),
        index=True,
    )
    product_identifier_type: Mapped[str] = mapped_column(String(40))
    maigret_identifier_type: Mapped[str] = mapped_column(String(40))
    identifier_value: Mapped[str] = mapped_column(String(160))
    site_names: Mapped[list[str]] = mapped_column(JSON)
    selected_site_manifest_checksum: Mapped[str] = mapped_column(String(64))
    scan_profile: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), index=True)
    selected_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    found_count: Mapped[int] = mapped_column(Integer, default=0)
    not_found_count: Mapped[int] = mapped_column(Integer, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, default=0)
    illegal_count: Mapped[int] = mapped_column(Integer, default=0)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    max_connections: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class MaigretSiteCheck(Base):
    __tablename__ = "maigret_site_check"
    __table_args__ = (
        UniqueConstraint(
            "provider_run_id",
            "site_key",
            name="uq_maigret_scan_site",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("search_job.id", ondelete="CASCADE"), index=True
    )
    provider_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("provider_run.id", ondelete="CASCADE"), index=True
    )
    site_key: Mapped[str] = mapped_column(String(160))
    site_name: Mapped[str] = mapped_column(String(160))
    source_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    queried_identifier: Mapped[str] = mapped_column(String(160))
    queried_identifier_type: Mapped[str] = mapped_column(String(40))
    url_main: Mapped[str | None] = mapped_column(String(500), nullable=True)
    url_user: Mapped[str | None] = mapped_column(String(500), nullable=True)
    url_probe: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_status: Mapped[str] = mapped_column(String(32))
    normalized_status: Mapped[str] = mapped_column(String(40), index=True)
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_similar: Mapped[bool] = mapped_column(Boolean, default=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON)
    extracted_data: Mapped[dict[str, object]] = mapped_column(JSON)
    extracted_usernames: Mapped[dict[str, str]] = mapped_column(JSON)
    extracted_links: Mapped[list[str]] = mapped_column(JSON)
    result_checksum: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccountNode(Base):
    __tablename__ = "account_node"
    __table_args__ = (UniqueConstraint("job_id", "canonical_url", name="uq_job_account_url"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("search_job.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(160))
    canonical_handle: Mapped[str] = mapped_column(String(160))
    canonical_url: Mapped[str] = mapped_column(String(500))
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    identity_confidence_tier: Mapped[str] = mapped_column(String(32))
    selection_state: Mapped[str] = mapped_column(String(32), default="undecided")
    is_similar: Mapped[bool] = mapped_column(Boolean, default=False)
    profile_data: Mapped[dict[str, object]] = mapped_column(JSON)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DiscoveryEdge(Base):
    __tablename__ = "discovery_edge"
    __table_args__ = (
        UniqueConstraint(
            "provider_run_id",
            "site_check_id",
            "child_account_node_id",
            name="uq_discovery_probe_edge",
        ),
        UniqueConstraint(
            "provider_run_id",
            "source_observation_id",
            "child_account_node_id",
            name="uq_discovery_observation_edge",
        ),
        CheckConstraint(
            """
            (
                site_check_id IS NOT NULL
                AND source_observation_id IS NULL
            )
            OR
            (
                site_check_id IS NULL
                AND source_observation_id IS NOT NULL
            )
            """,
            name="ck_discovery_edge_exactly_one_lineage",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("search_job.id", ondelete="CASCADE"), index=True
    )
    provider_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("provider_run.id", ondelete="CASCADE")
    )
    site_check_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("maigret_site_check.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_observation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "source_observation.id",
            name="fk_discovery_edge_source_observation_id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    child_account_node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("account_node.id", ondelete="CASCADE"), index=True
    )
    parent_seed: Mapped[str] = mapped_column(String(240))
    discovery_method: Mapped[str] = mapped_column(String(64))
    discovery_engine: Mapped[str] = mapped_column(String(40), default="maigret")
    depth: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DiscoveredIdentifier(Base):
    __tablename__ = "discovered_identifier"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "parent_site_check_id",
            "identifier_type",
            "normalized_value",
            name="uq_discovered_identifier_lineage",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("search_job.id", ondelete="CASCADE"), index=True
    )
    parent_site_check_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("maigret_site_check.id", ondelete="CASCADE")
    )
    identifier_type: Mapped[str] = mapped_column(String(80))
    identifier_value: Mapped[str] = mapped_column(String(300))
    normalized_value: Mapped[str] = mapped_column(String(300))
    source_kind: Mapped[str] = mapped_column(String(40))
    scheduled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_user_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("search_job.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobEvent(Base):
    __tablename__ = "job_event"
    __table_args__ = (UniqueConstraint("job_id", "sequence", name="uq_job_event_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("search_job.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(160))
    terminal: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxMessage(Base):
    __tablename__ = "outbox_message"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic: Mapped[str] = mapped_column(String(80))
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class SourceDocument(Base):
    __tablename__ = "source_document"
    __table_args__ = (
        UniqueConstraint("canonical_url", "content_hash", name="uq_document_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    canonical_url: Mapped[str] = mapped_column(String(400))
    publisher: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(240))
    mime_type: Mapped[str] = mapped_column(String(80))
    content_hash: Mapped[str] = mapped_column(String(64))
    lineage_key: Mapped[str] = mapped_column(String(160))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderRunSourceUse(Base):
    __tablename__ = "provider_run_source_use"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("provider_run.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_document.id", ondelete="CASCADE")
    )
    disposition: Mapped[str] = mapped_column(String(40), default="accepted")
    policy_version: Mapped[str] = mapped_column(String(32))


class SourceObservation(Base):
    __tablename__ = "source_observation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("search_job.id", ondelete="CASCADE"), index=True
    )
    source_use_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("provider_run_source_use.id", ondelete="CASCADE")
    )
    source_type: Mapped[str] = mapped_column(String(80))
    trust_class: Mapped[str] = mapped_column(String(80))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    excerpt: Mapped[str] = mapped_column(Text)
    span_locator: Mapped[dict[str, object]] = mapped_column(JSON)
    extracted_fields: Mapped[dict[str, object]] = mapped_column(JSON)
    extraction_version: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CollectionSnapshot(Base):
    __tablename__ = "collection_snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("search_job.id", ondelete="CASCADE"), unique=True
    )
    attempt_id: Mapped[str] = mapped_column(String(36))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observation_ids: Mapped[list[str]] = mapped_column(JSON)
    provider_manifest: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(32))
    checksum: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AnalysisRevision(Base):
    __tablename__ = "analysis_revision"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("search_job.id", ondelete="CASCADE"), unique=True
    )
    collection_snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("collection_snapshot.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(40))
    rules_version: Mapped[str] = mapped_column(String(40))
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Claim(Base):
    __tablename__ = "claim"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("search_job.id", ondelete="CASCADE"), index=True
    )
    analysis_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_revision.id", ondelete="CASCADE")
    )
    predicate: Mapped[str] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(120))
    value: Mapped[str] = mapped_column(String(400))
    confidence: Mapped[str] = mapped_column(String(32))
    displayable: Mapped[bool] = mapped_column(Boolean, default=True)
    policy_reason: Mapped[str] = mapped_column(String(160))


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (UniqueConstraint("claim_id", "observation_id", name="uq_claim_observation"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("claim.id", ondelete="CASCADE"), index=True
    )
    observation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_observation.id", ondelete="CASCADE")
    )
    relation: Mapped[str] = mapped_column(String(32), default="supports")
    independence_group: Mapped[str] = mapped_column(String(160))
    rationale: Mapped[str] = mapped_column(String(240))


class ReportRevision(Base):
    __tablename__ = "report_revision"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("search_job.id", ondelete="CASCADE"), unique=True
    )
    analysis_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_revision.id", ondelete="CASCADE")
    )
    report_type: Mapped[str] = mapped_column(String(40), default="fast_brief")
    locale: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(40))
    content: Mapped[dict[str, object]] = mapped_column(JSON)
    template_version: Mapped[str] = mapped_column(String(40))
    policy_version: Mapped[str] = mapped_column(String(32))
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReportAccessState(Base):
    __tablename__ = "report_access_state"

    report_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_revision.id", ondelete="CASCADE"), primary_key=True
    )
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    state: Mapped[str] = mapped_column(String(48), default="active")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SubjectSuppressionRecord(Base):
    __tablename__ = "subject_suppression_record"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    identifier_hmac: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobDeletionTombstone(Base):
    __tablename__ = "job_deletion_tombstone"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    write_fence: Mapped[int] = mapped_column(Integer)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index("ix_outbox_undispatched", OutboxMessage.dispatched_at, OutboxMessage.created_at)
