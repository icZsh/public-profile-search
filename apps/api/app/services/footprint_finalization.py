import html
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.crypto import stable_payload_hash
from apps.api.app.models.entities import (
    AccountNode,
    AnalysisRevision,
    Claim,
    ClaimEvidence,
    CollectionSnapshot,
    DiscoveryEdge,
    GroundedSynthesisResult,
    JobAttempt,
    MaigretScanRun,
    MaigretSiteCheck,
    ProviderRun,
    ProviderRunSourceUse,
    ReportAccessState,
    ReportRevision,
    SearchJob,
    SourceDocument,
    SourceObservation,
    new_id,
)
from apps.api.app.policy.redaction import safe_text
from apps.api.app.services.anchor_selection import (
    is_exact_handle_account,
    selected_anchor_from_nodes,
)
from apps.api.app.services.events import add_event
from apps.api.app.services.grounded_synthesis_scheduling import (
    GROUNDED_SYNTHESIS_PROVIDER_IDS,
)

_TERMINAL_JOB_STATES = {
    "ready",
    "ready_partial",
    "no_candidates",
    "failed",
    "cancelled",
}
_TERMINAL_RUN_STATES = {
    "success",
    "partial_success",
    "no_result",
    "timeout",
    "rate_limited",
    "captcha_blocked",
    "auth_required",
    "provider_error",
    "invalid_response",
    "skipped_configuration",
    "cancelled",
    "closed_at_cutoff",
}
_CONCLUSIVE_RUN_STATES = {"success", "no_result"}
_CHANNEL_LIMITED_STATES = {
    "rate_limited",
    "captcha_blocked",
    "auth_required",
    "timeout",
    "provider_error",
    "skipped_configuration",
    "cancelled",
}
_DISPLAY_NAME_FIELDS = ("display_name", "fullname", "full_name", "name")
_USERNAME_FIELDS = ("username", "handle", "login", "screen_name")
_BIO_FIELDS = {
    "about",
    "bio",
    "biography",
    "description",
    "profile_bio",
}
_DIRECT_LOCATION_FIELDS = ("location", "public_location")
_WEBSITE_FIELDS = ("website", "website_url", "external_url")
_BOOLEAN_FIELDS = ("is_private", "is_verified")
_COUNT_FIELD_ALIASES = {
    "follower_count": ("follower_count", "followers", "followers_count"),
    "following_count": ("following_count", "following", "followings_count"),
    "post_count": ("post_count", "posts", "posts_count"),
}
_COUNT_PATTERN = re.compile(r"\A[\d.,]+(?:[KMB])?\Z", flags=re.IGNORECASE)
_LOCATION_PATTERN = re.compile(
    r"(?:📍|\b(?:location|based\s+in)\s*[:：])\s*([^\n\r|;；•]{2,80})",
    flags=re.IGNORECASE,
)
_NAME_TOKEN_PATTERN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_PLATFORM_ALIASES = {
    "twitter": "x",
    "twittercom": "x",
    "xcom": "x",
    "youtubecom": "youtube",
}


@dataclass(frozen=True)
class _AccountAssessment:
    node: AccountNode
    existence_status: str
    identity_status: str
    confidence: str
    source_ids: tuple[str, ...]
    association_source_ids: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _ClaimSpec:
    predicate: str
    label: str
    value: str
    confidence: str
    source_ids: tuple[str, ...]
    qualification: str | None


@dataclass(frozen=True)
class _ProfessionalEvidence:
    observation: SourceObservation
    provider_id: str
    query_name: str | None
    query_location: str | None
    source_node_ids: tuple[str, ...]
    name_source_node_ids: tuple[str, ...]


@dataclass(frozen=True)
class _ProfessionalMatch:
    full_name: str
    source_node_ids: tuple[str, ...]
    name_source_node_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    confidence: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _PersonDecision:
    report_type: str
    overall_identity_status: str
    full_name: str | None
    supporting_source_ids: tuple[str, ...]
    reason: str | None


@dataclass(frozen=True)
class _SynthesisView:
    summary: str | None
    narrative_sections: tuple[dict[str, object], ...]
    deep_story: dict[str, object] | None
    supporting_reasons: tuple[str, ...]
    limiting_reasons: tuple[str, ...]
    metadata: dict[str, object]
    limitation: str | None


def finalize_footprint_if_complete(
    session: Session,
    *,
    job: SearchJob,
    now,
) -> bool:
    """Freeze bounded discovery evidence and render a source-linked footprint brief."""

    locked_job = session.scalar(select(SearchJob).where(SearchJob.id == job.id).with_for_update())
    if (
        not locked_job
        or locked_job.job_kind != "footprint_discovery"
        or locked_job.status in _TERMINAL_JOB_STATES
    ):
        return False
    job = locked_job
    attempt = session.scalar(
        select(JobAttempt).where(JobAttempt.id == job.active_attempt_id).with_for_update()
    )
    if not attempt or attempt.current_report_revision_id:
        return False

    runs = session.scalars(
        select(ProviderRun)
        .where(ProviderRun.job_id == job.id)
        .order_by(ProviderRun.logical_run_id)
        .with_for_update()
    ).all()
    if not runs or any(run.status not in _TERMINAL_RUN_STATES for run in runs):
        return False

    job.status = "finalizing"
    job.row_version += 1
    attempt.status = "finalizing"
    add_event(
        session,
        job_id=job.id,
        event_type="finalization_started",
        message="The bounded footprint evidence is being finalized.",
        created_at=now,
    )
    job.acceptance_epoch += 1
    # The application session intentionally disables autoflush. The last completed
    # scan can still have a pending DiscoveryEdge when it enters finalization.
    session.flush()

    checks = session.scalars(
        select(MaigretSiteCheck)
        .where(MaigretSiteCheck.job_id == job.id)
        .order_by(
            MaigretSiteCheck.site_name,
            MaigretSiteCheck.site_key,
            MaigretSiteCheck.id,
        )
    ).all()
    nodes = session.scalars(
        select(AccountNode)
        .where(AccountNode.job_id == job.id)
        .order_by(AccountNode.platform, AccountNode.canonical_url, AccountNode.id)
    ).all()
    node_by_check_id = _node_by_check_id(session, job_id=job.id)

    observation_by_check_id: dict[str, SourceObservation] = {}
    source_ids_by_node_id: dict[str, list[str]] = {}
    first_party_node_ids: set[str] = set()
    skipped_evidence_sites: list[str] = []
    for check in checks:
        evidence_kind = _evidence_kind(check)
        if evidence_kind is None:
            continue
        node = node_by_check_id.get(check.id)
        observation = _upsert_check_observation(
            session,
            job=job,
            check=check,
            node=node,
            evidence_kind=evidence_kind,
        )
        if observation is None:
            skipped_evidence_sites.append(check.site_name)
            continue
        observation_by_check_id[check.id] = observation
        if node is not None:
            source_ids_by_node_id.setdefault(node.id, []).append(observation.id)
            if _is_exact_first_party_profile(check):
                first_party_node_ids.add(node.id)
    session.flush()

    professional_evidence_by_node = _professional_evidence_by_node(
        session,
        job_id=job.id,
    )
    indexed_node_ids: set[str] = set()
    for node_id, evidence_items in professional_evidence_by_node.items():
        for evidence in evidence_items:
            source_ids_by_node_id.setdefault(node_id, []).append(evidence.observation.id)
            if evidence.observation.source_type == "first_party_profile_api":
                first_party_node_ids.add(node_id)
            elif evidence.observation.source_type == "professional_profile_index":
                indexed_node_ids.add(node_id)
    professional_matches_by_node = _professional_matches(
        job=job,
        nodes=nodes,
        evidence_by_node=professional_evidence_by_node,
        source_ids_by_node_id=source_ids_by_node_id,
    )
    assessments = _assess_accounts(
        job=job,
        nodes=nodes,
        source_ids_by_node_id=source_ids_by_node_id,
        first_party_node_ids=first_party_node_ids,
        indexed_node_ids=indexed_node_ids,
        professional_evidence_by_node=professional_evidence_by_node,
        professional_matches_by_node=professional_matches_by_node,
    )
    person_decision = _decide_person_hypothesis(
        assessments=assessments,
        professional_matches_by_node=professional_matches_by_node,
    )
    claim_specs = _claim_specs(
        checks=checks,
        assessments=assessments,
        observation_by_check_id=observation_by_check_id,
    )
    observations = session.scalars(
        select(SourceObservation)
        .where(SourceObservation.job_id == job.id)
        .order_by(SourceObservation.retrieved_at, SourceObservation.id)
    ).all()
    observation_ids = sorted({observation.id for observation in observations})
    synthesis_view = _grounded_synthesis_view(
        session,
        job=job,
        observation_ids=set(observation_ids),
        person_decision=person_decision,
        assessments=assessments,
    )
    provider_manifest = _provider_manifest(session, runs=runs)
    snapshot_checksum = stable_payload_hash(
        {
            "observations": observation_ids,
            "providers": provider_manifest,
        }
    )
    snapshot = CollectionSnapshot(
        id=new_id(),
        job_id=job.id,
        attempt_id=attempt.id,
        cutoff_at=now,
        observation_ids=observation_ids,
        provider_manifest=provider_manifest,
        policy_version=job.policy_version,
        checksum=snapshot_checksum,
        expires_at=job.expires_at,
    )
    session.add(snapshot)
    session.flush()

    analysis = AnalysisRevision(
        id=new_id(),
        job_id=job.id,
        collection_snapshot_id=snapshot.id,
        status="complete",
        rules_version="adaptive-professional-bridge-v3",
        checksum=stable_payload_hash(
            {
                "snapshot": snapshot_checksum,
                "accounts": [_assessment_checksum_item(item) for item in assessments],
                "claims": [_claim_checksum_item(item) for item in claim_specs],
            }
        ),
        created_at=now,
        expires_at=job.expires_at,
    )
    session.add(analysis)
    session.flush()

    rendered_claims = _persist_claims(
        session,
        job=job,
        analysis=analysis,
        claim_specs=claim_specs,
        observation_ids=set(observation_ids),
    )
    identity_reasons = _identity_reasons(
        assessments,
        person_decision=person_decision,
    )
    identity_reasons["supporting"] = _dedupe_text(
        [
            *identity_reasons["supporting"],
            *synthesis_view.supporting_reasons,
        ]
    )
    identity_reasons["limiting"] = _dedupe_text(
        [
            *identity_reasons["limiting"],
            *synthesis_view.limiting_reasons,
        ]
    )
    limitations = _limitations(
        search_mode=job.search_mode,
        runs=runs,
        checks=checks,
        skipped_evidence_sites=skipped_evidence_sites,
    )
    if synthesis_view.limitation:
        limitations = _dedupe_text([*limitations, synthesis_view.limitation])
    deterministic_summary = _summary(
        job=job,
        assessments=assessments,
        checks=checks,
        person_decision=person_decision,
    )
    rendered_summary = synthesis_view.summary or deterministic_summary
    content = {
        "job_id": job.id,
        "report_type": person_decision.report_type,
        "subject": _subject(
            job,
            assessments=assessments,
            person_decision=person_decision,
        ),
        "summary": rendered_summary,
        "overall_identity_status": person_decision.overall_identity_status,
        "accounts": [_render_account(item) for item in assessments],
        "claims": rendered_claims,
        "identity_reasons": identity_reasons,
        "narrative_sections": list(synthesis_view.narrative_sections),
        "deep_story": synthesis_view.deep_story,
        "synthesis": synthesis_view.metadata,
        "limitations": limitations,
        "generated_at": now.isoformat(),
    }
    report = ReportRevision(
        id=new_id(),
        job_id=job.id,
        analysis_revision_id=analysis.id,
        report_type=person_decision.report_type,
        locale=job.locale,
        status="ready",
        content=content,
        template_version=(
            "grounded-footprint-story-v4"
            if synthesis_view.metadata["mode"] == "llm_grounded"
            else "deterministic-footprint-brief-v3"
        ),
        policy_version=job.policy_version,
        checksum=stable_payload_hash(content),
        created_at=now,
        expires_at=job.expires_at,
    )
    session.add(report)
    session.flush()
    session.add(
        ReportAccessState(
            report_id=report.id,
            job_id=job.id,
            state="active",
            updated_at=now,
        )
    )

    synthesis_ran = any(run.provider_id in GROUNDED_SYNTHESIS_PROVIDER_IDS for run in runs)
    conclusive = all(run.status in _CONCLUSIVE_RUN_STATES for run in runs) and (
        job.search_mode != "deep" or synthesis_ran
    )
    if assessments:
        terminal_status = "ready" if conclusive else "ready_partial"
    else:
        terminal_status = "no_candidates" if conclusive else "ready_partial"
    attempt.collection_snapshot_id = snapshot.id
    attempt.current_analysis_revision_id = analysis.id
    attempt.current_report_revision_id = report.id
    attempt.finished_at = now
    attempt.status = terminal_status
    attempt.terminal_reason = terminal_status
    job.status = terminal_status
    job.exploration_status = "completed"
    job.row_version += 1
    add_event(
        session,
        job_id=job.id,
        event_type="job.ready",
        message=(f"Footprint brief completed with {len(assessments)} possible accounts."),
        created_at=now,
        terminal=True,
    )
    return True


def _node_by_check_id(session: Session, *, job_id: str) -> dict[str, AccountNode]:
    rows = session.execute(
        select(DiscoveryEdge.site_check_id, AccountNode)
        .join(AccountNode, AccountNode.id == DiscoveryEdge.child_account_node_id)
        .where(DiscoveryEdge.job_id == job_id)
        .order_by(
            DiscoveryEdge.site_check_id,
            AccountNode.platform,
            AccountNode.canonical_url,
            AccountNode.id,
        )
    ).all()
    result: dict[str, AccountNode] = {}
    for site_check_id, node in rows:
        result.setdefault(str(site_check_id), node)
    return result


def _professional_evidence_by_node(
    session: Session,
    *,
    job_id: str,
) -> dict[str, tuple[_ProfessionalEvidence, ...]]:
    rows = session.execute(
        select(
            DiscoveryEdge.child_account_node_id,
            SourceObservation,
            ProviderRun,
        )
        .join(
            SourceObservation,
            SourceObservation.id == DiscoveryEdge.source_observation_id,
        )
        .join(
            ProviderRunSourceUse,
            ProviderRunSourceUse.id == SourceObservation.source_use_id,
        )
        .join(
            ProviderRun,
            ProviderRun.id == ProviderRunSourceUse.provider_run_id,
        )
        .where(
            DiscoveryEdge.job_id == job_id,
            DiscoveryEdge.source_observation_id.is_not(None),
            SourceObservation.job_id == job_id,
        )
        .order_by(
            DiscoveryEdge.child_account_node_id,
            SourceObservation.retrieved_at,
            SourceObservation.id,
        )
    ).all()
    result: dict[str, list[_ProfessionalEvidence]] = {}
    for node_id, observation, run in rows:
        config = dict(run.query_config or {})
        source_node_ids = (
            tuple(
                sorted(
                    {value for value in config.get("source_node_ids", []) if isinstance(value, str)}
                )
            )
            if isinstance(config.get("source_node_ids"), list)
            else ()
        )
        configured_name_source_node_ids = config.get("name_source_node_ids")
        name_source_node_ids = (
            tuple(
                sorted(
                    {value for value in configured_name_source_node_ids if isinstance(value, str)}
                )
            )
            if isinstance(configured_name_source_node_ids, list)
            else source_node_ids
        )
        query_name = config.get("full_name")
        query_location = config.get("broad_location")
        result.setdefault(str(node_id), []).append(
            _ProfessionalEvidence(
                observation=observation,
                provider_id=run.provider_id,
                query_name=(
                    safe_text(query_name, max_length=160) if isinstance(query_name, str) else None
                ),
                query_location=(
                    safe_text(query_location, max_length=160)
                    if isinstance(query_location, str)
                    else None
                ),
                source_node_ids=source_node_ids,
                name_source_node_ids=name_source_node_ids,
            )
        )
    return {node_id: tuple(items) for node_id, items in result.items()}


def _professional_matches(
    *,
    job: SearchJob,
    nodes: list[AccountNode],
    evidence_by_node: dict[str, tuple[_ProfessionalEvidence, ...]],
    source_ids_by_node_id: dict[str, list[str]],
) -> dict[str, _ProfessionalMatch]:
    node_by_id = {node.id: node for node in nodes}
    matches: dict[str, _ProfessionalMatch] = {}
    for node_id, evidence_items in evidence_by_node.items():
        node = node_by_id.get(node_id)
        if not node:
            continue
        for evidence in evidence_items:
            query_name = evidence.query_name
            if not query_name:
                continue
            fields = evidence.observation.extracted_fields
            display_name = fields.get("display_name")
            normalized_query = _normalized_display_name(query_name)
            normalized_display = (
                _normalized_display_name(display_name) if isinstance(display_name, str) else None
            )
            name_match = bool(
                normalized_query and normalized_display and normalized_query == normalized_display
            )
            explicit_name_conflict = bool(
                normalized_display and normalized_query and normalized_display != normalized_query
            )
            location = fields.get("location")
            location_match = bool(
                isinstance(location, str)
                and evidence.query_location
                and _locations_compatible(location, evidence.query_location)
            )
            social_handle = fields.get("social_handle")
            direct_social_match = bool(
                isinstance(social_handle, str)
                and job.seed_identifier
                and social_handle.strip().removeprefix("@").casefold()
                == job.seed_identifier.strip().removeprefix("@").casefold()
            )
            root_families = {
                _platform_family(node_by_id[source_id].platform)
                for source_id in evidence.name_source_node_ids
                if source_id in node_by_id
                and _normalized_display_name(node_by_id[source_id].display_name) == normalized_query
            }
            provider_family = (
                "github"
                if evidence.observation.source_type == "first_party_profile_api"
                else "linkedin-index"
            )
            independent_family_count = len(root_families | {provider_family})
            third_family_name_match = name_match and independent_family_count >= 3
            contextual_location_anchor = bool(
                name_match
                and location_match
                and evidence.observation.source_type == "professional_profile_index"
            )
            if explicit_name_conflict or not (
                direct_social_match or contextual_location_anchor or third_family_name_match
            ):
                continue

            reasons: list[str] = []
            confidence = "medium"
            if direct_social_match:
                reasons.append(
                    "An independent professional profile exposes the exact root "
                    "handle as its public social handle."
                )
                confidence = "medium_high"
            if name_match:
                reasons.append(
                    "The professional profile and an exact root-handle profile "
                    "expose the same full display name."
                )
            if contextual_location_anchor:
                reasons.append("The independent profiles expose compatible broad public locations.")
            if third_family_name_match:
                reasons.append(
                    "The same full name appears across three independent source families."
                )
            source_ids = _combined_source_ids(
                (evidence.observation.id,),
                [
                    source_id
                    for source_node_id in evidence.source_node_ids
                    for source_id in source_ids_by_node_id.get(source_node_id, [])
                ],
            )
            candidate = _ProfessionalMatch(
                full_name=query_name,
                source_node_ids=evidence.source_node_ids,
                name_source_node_ids=evidence.name_source_node_ids,
                source_ids=source_ids,
                confidence=confidence,
                reasons=tuple(reasons),
            )
            current = matches.get(node_id)
            if current is None or _confidence_rank(candidate.confidence) > _confidence_rank(
                current.confidence
            ):
                matches[node_id] = candidate
    return matches


def _decide_person_hypothesis(
    *,
    assessments: list[_AccountAssessment],
    professional_matches_by_node: dict[str, _ProfessionalMatch],
) -> _PersonDecision:
    likely_node_ids = {
        assessment.node.id for assessment in assessments if assessment.identity_status == "likely"
    }
    passing = [
        match
        for node_id, match in professional_matches_by_node.items()
        if node_id in likely_node_ids
    ]
    selected_node_ids = {
        assessment.node.id
        for assessment in assessments
        if assessment.node.selection_state == "included"
    }
    selected_passing = [
        match for match in passing if selected_node_ids.intersection(match.name_source_node_ids)
    ]
    selected_anchor_applied = bool(selected_node_ids)
    if selected_anchor_applied:
        passing = selected_passing
    names: dict[str, list[_ProfessionalMatch]] = {}
    for match in passing:
        normalized = _normalized_display_name(match.full_name)
        if normalized:
            names.setdefault(normalized, []).append(match)
    if len(names) != 1:
        return _PersonDecision(
            report_type="account_centric",
            overall_identity_status="unverified",
            full_name=None,
            supporting_source_ids=(),
            reason=None,
        )
    matches = next(iter(names.values()))
    full_name = sorted(
        (match.full_name for match in matches),
        key=lambda value: (len(value), value.casefold()),
    )[0]
    source_ids = tuple(sorted({source_id for match in matches for source_id in match.source_ids}))
    return _PersonDecision(
        report_type="person_centric",
        overall_identity_status="likely",
        full_name=full_name,
        supporting_source_ids=source_ids,
        reason=(
            "Exactly one public full-name hypothesis tied to the selected account "
            "is corroborated by an independent professional-profile anchor."
            if selected_anchor_applied
            else "Exactly one public full-name hypothesis is corroborated by an "
            "independent professional-profile anchor."
        ),
    )


def _evidence_kind(check: MaigretSiteCheck) -> str | None:
    if check.raw_status == "CLAIMED" and check.normalized_status == "found":
        return "claimed"
    if check.normalized_status in _CHANNEL_LIMITED_STATES:
        return "channel_limited"
    return None


def _upsert_check_observation(
    session: Session,
    *,
    job: SearchJob,
    check: MaigretSiteCheck,
    node: AccountNode | None,
    evidence_kind: str,
) -> SourceObservation | None:
    canonical_url = _source_url(check)
    if canonical_url is None:
        return None
    extracted_fields = _allowlisted_observation_fields(
        check=check,
        node=node,
        evidence_kind=evidence_kind,
    )
    first_party_profile = bool(evidence_kind == "claimed" and _is_exact_first_party_profile(check))
    content_hash = stable_payload_hash(
        {
            "site": check.site_key,
            "url": canonical_url,
            "observed_at": check.observed_at,
            "fields": extracted_fields,
        }
    )
    document = session.scalar(
        select(SourceDocument).where(
            SourceDocument.canonical_url == canonical_url,
            SourceDocument.content_hash == content_hash,
        )
    )
    if not document:
        document = SourceDocument(
            id=new_id(),
            canonical_url=canonical_url,
            publisher=(
                safe_text(check.site_name, max_length=160)
                if first_party_profile
                else "Maigret catalog probe"
            ),
            title=safe_text(
                (
                    f"{check.site_name} public profile for @{check.queried_identifier}"
                    if first_party_profile
                    else f"{check.site_name} account presence check"
                ),
                max_length=240,
            ),
            mime_type="application/json",
            content_hash=content_hash,
            lineage_key=(
                "maigret-site:"
                + stable_payload_hash(
                    {
                        "catalog": job.catalog_snapshot_id,
                        "site": check.site_key,
                        "identifier_type": check.queried_identifier_type,
                        "identifier": check.queried_identifier.casefold(),
                    }
                )
            ),
            expires_at=job.expires_at,
        )
        session.add(document)
        session.flush()
    elif document.expires_at is None or document.expires_at < job.expires_at:
        document.expires_at = job.expires_at

    disposition = (
        "accepted"
        if first_party_profile
        else "candidate_discovery"
        if evidence_kind == "claimed"
        else "channel_limited"
    )
    source_use = session.scalar(
        select(ProviderRunSourceUse)
        .where(
            ProviderRunSourceUse.provider_run_id == check.provider_run_id,
            ProviderRunSourceUse.document_id == document.id,
        )
        .order_by(ProviderRunSourceUse.id)
    )
    if not source_use:
        source_use = ProviderRunSourceUse(
            id=new_id(),
            provider_run_id=check.provider_run_id,
            document_id=document.id,
            disposition=disposition,
            policy_version=job.policy_version,
        )
        session.add(source_use)
        session.flush()

    observation = session.scalar(
        select(SourceObservation)
        .where(
            SourceObservation.job_id == job.id,
            SourceObservation.source_use_id == source_use.id,
        )
        .order_by(SourceObservation.id)
    )
    if observation:
        return observation
    excerpt = (
        (
            f"The public {check.site_name} profile exposed the exact "
            f"handle @{check.queried_identifier}."
            if first_party_profile
            else f"{check.site_name} reported the exact account handle as claimed."
        )
        if evidence_kind == "claimed"
        else (
            f"{check.site_name} could not be checked conclusively "
            f"because the channel was {_channel_label(check.normalized_status)}."
        )
    )
    observation = SourceObservation(
        id=new_id(),
        job_id=job.id,
        source_use_id=source_use.id,
        source_type=(
            "first_party_profile"
            if first_party_profile
            else "candidate_discovery"
            if evidence_kind == "claimed"
            else "availability_endpoint"
        ),
        trust_class=(
            "first_party"
            if first_party_profile
            else "scanner_lead"
            if evidence_kind == "claimed"
            else "channel_status"
        ),
        retrieved_at=check.observed_at,
        excerpt=safe_text(excerpt),
        span_locator={
            "kind": "allowlisted_maigret_fields",
            "fields": sorted(extracted_fields),
        },
        extracted_fields=extracted_fields,
        extraction_version="maigret-footprint-v1",
        expires_at=job.expires_at,
    )
    session.add(observation)
    session.flush()
    return observation


def _allowlisted_observation_fields(
    *,
    check: MaigretSiteCheck,
    node: AccountNode | None,
    evidence_kind: str,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "platform": safe_text(check.site_name, max_length=160),
        "handle": safe_text(check.queried_identifier, max_length=160),
        "scanner_status": check.raw_status,
    }
    if evidence_kind == "claimed":
        first_party_profile = _is_exact_first_party_profile(check)
        fields["existence_status"] = (
            "exact_verified" if first_party_profile else "claimed_unverified"
        )
        fields["match_kind"] = "similar_handle" if check.is_similar else "exact_handle"
        fields.update(_allowlisted_public_profile_fields(check))
        if node is not None:
            fields["profile_url"] = node.canonical_url
            if node.display_name:
                fields.setdefault("display_name", node.display_name[:200])
        location = _extract_self_described_location(check.extracted_data)
        if isinstance(location, str):
            fields["self_described_location"] = location
    else:
        fields["existence_status"] = "channel_limited"
        fields["channel_status"] = check.normalized_status
        if check.http_status is not None:
            fields["http_status"] = check.http_status
    return fields


def _extract_self_described_location(
    extracted_data: dict[str, object],
) -> str | None:
    for raw_key, raw_value in extracted_data.items():
        key = str(raw_key).strip().casefold().replace("-", "_").replace(" ", "_")
        if key not in _BIO_FIELDS or not isinstance(raw_value, str):
            continue
        match = _LOCATION_PATTERN.search(raw_value)
        if not match:
            continue
        candidate = " ".join(match.group(1).split()).strip(" ,，.!。·-–—")
        candidate = re.split(r"\s{2,}|(?:\s+[•·]\s+)", candidate, maxsplit=1)[0]
        if (
            not 2 <= len(candidate) <= 80
            or any(character.isdigit() for character in candidate)
            or "://" in candidate
            or "@" in candidate
        ):
            continue
        return safe_text(candidate, max_length=80)
    return None


def _allowlisted_public_profile_fields(
    check: MaigretSiteCheck,
) -> dict[str, object]:
    normalized = {
        str(key).strip().casefold().replace("-", "_").replace(" ", "_"): value
        for key, value in check.extracted_data.items()
    }
    fields: dict[str, object] = {}
    username = _first_text_value(normalized, _USERNAME_FIELDS, maximum=160)
    display_name = _first_text_value(normalized, _DISPLAY_NAME_FIELDS, maximum=200)
    bio = _first_text_value(normalized, tuple(sorted(_BIO_FIELDS)), maximum=1_000)
    location = _first_text_value(normalized, _DIRECT_LOCATION_FIELDS, maximum=160)
    website = _first_text_value(normalized, _WEBSITE_FIELDS, maximum=400)
    if username:
        fields["username"] = username
    if display_name:
        fields["display_name"] = display_name
    if bio:
        fields["bio"] = bio
    if location:
        fields["location"] = location
    if website and _safe_http_url(html.unescape(website)):
        fields["website"] = website
    for key in _BOOLEAN_FIELDS:
        value = normalized.get(key)
        if isinstance(value, bool):
            fields[key] = value
    for canonical_name, aliases in _COUNT_FIELD_ALIASES.items():
        value = next(
            (normalized[alias] for alias in aliases if alias in normalized),
            None,
        )
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            fields[canonical_name] = value
        elif isinstance(value, str) and _COUNT_PATTERN.fullmatch(value.strip()):
            fields[canonical_name] = value.strip()
    return fields


def _first_text_value(
    values: dict[str, object],
    keys: tuple[str, ...],
    *,
    maximum: int,
) -> str | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str):
            normalized = safe_text(value, max_length=maximum)
            if normalized:
                return normalized
    return None


def _is_exact_first_party_profile(check: MaigretSiteCheck) -> bool:
    if (
        check.raw_status != "CLAIMED"
        or check.normalized_status != "found"
        or check.is_similar
        or not check.url_user
    ):
        return False
    public_fields = _allowlisted_public_profile_fields(check)
    username = public_fields.get("username")
    if (
        not isinstance(username, str)
        or html.unescape(username).strip().removeprefix("@").casefold()
        != check.queried_identifier.strip().removeprefix("@").casefold()
    ):
        return False
    try:
        parsed = urlsplit(check.url_user)
    except ValueError:
        return False
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    platform = _platform_key(check.site_name)
    hostname = parsed.hostname.casefold().removeprefix("www.")
    handle = check.queried_identifier.strip().removeprefix("@").casefold()
    path = parsed.path.rstrip("/").casefold()
    rules = {
        "clubhouse": ({"clubhouse.com"}, {f"/@{handle}"}),
        "github": ({"github.com"}, {f"/{handle}"}),
        "instagram": ({"instagram.com"}, {f"/{handle}"}),
        "pinterest": ({"pinterest.com"}, {f"/{handle}"}),
        "reddit": ({"reddit.com"}, {f"/user/{handle}", f"/u/{handle}"}),
        "threads": (
            {"threads.com", "threads.net"},
            {f"/@{handle}"},
        ),
        "tiktok": ({"tiktok.com"}, {f"/@{handle}"}),
        "x": ({"x.com", "twitter.com"}, {f"/{handle}"}),
        "youtube": ({"youtube.com"}, {f"/@{handle}"}),
    }
    hosts_and_paths = rules.get(platform)
    return bool(hosts_and_paths and hostname in hosts_and_paths[0] and path in hosts_and_paths[1])


def _assess_accounts(
    *,
    job: SearchJob,
    nodes: list[AccountNode],
    source_ids_by_node_id: dict[str, list[str]],
    first_party_node_ids: set[str],
    indexed_node_ids: set[str],
    professional_evidence_by_node: dict[str, tuple[_ProfessionalEvidence, ...]],
    professional_matches_by_node: dict[str, _ProfessionalMatch],
) -> list[_AccountAssessment]:
    exact_nodes = [node for node in nodes if _is_exact_handle(node, job)]
    selected_node = selected_anchor_from_nodes(exact_nodes, job=job)
    seed_node = selected_node or next(
        (
            node
            for node in exact_nodes
            if job.seed_platform
            and _platform_key(node.platform) == _platform_key(job.seed_platform)
        ),
        None,
    )
    reference_name = (
        _normalized_display_name(seed_node.display_name)
        if seed_node and seed_node.id in first_party_node_ids
        else None
    )
    reference_node = seed_node if reference_name else None
    reference_kind = "selected" if selected_node and reference_name else "seed"
    if not reference_name:
        name_counts = Counter()
        seen_name_families: set[tuple[str, str]] = set()
        for node in exact_nodes:
            normalized = (
                _normalized_display_name(node.display_name)
                if node.id in first_party_node_ids
                else None
            )
            key = (normalized or "", _platform_family(node.platform))
            if not normalized or key in seen_name_families:
                continue
            seen_name_families.add(key)
            name_counts[normalized] += 1
        repeated = sorted(
            ((-count, normalized) for normalized, count in name_counts.items() if count >= 2)
        )
        reference_name = repeated[0][1] if repeated else None
        reference_kind = "repeated"
        reference_node = next(
            (
                node
                for node in exact_nodes
                if node.id in first_party_node_ids
                if _normalized_display_name(node.display_name) == reference_name
            ),
            None,
        )
    repeated_reference_source_ids = tuple(
        sorted(
            {
                source_id
                for node in exact_nodes
                if node.id in first_party_node_ids
                and _normalized_display_name(node.display_name) == reference_name
                for source_id in source_ids_by_node_id.get(node.id, [])
            }
        )
    )
    professional_support_by_source_node: dict[str, list[_ProfessionalMatch]] = {}
    node_by_id = {node.id: node for node in nodes}
    for match in professional_matches_by_node.values():
        normalized_match_name = _normalized_display_name(match.full_name)
        for source_node_id in match.name_source_node_ids:
            source_node = node_by_id.get(source_node_id)
            if not source_node or (
                _normalized_display_name(source_node.display_name) != normalized_match_name
                and not _shares_surname_token(
                    normalized_match_name or "",
                    _normalized_display_name(source_node.display_name) or "",
                )
            ):
                continue
            professional_support_by_source_node.setdefault(
                source_node_id,
                [],
            ).append(match)

    assessments: list[_AccountAssessment] = []
    for node in nodes:
        sources = tuple(sorted(set(source_ids_by_node_id.get(node.id, []))))
        association_sources = sources
        exact_handle = _is_exact_handle(node, job)
        is_reference_node = bool(seed_node and node.id == seed_node.id)
        if node.id in first_party_node_ids:
            existence_status = "exact_verified"
        elif node.id in indexed_node_ids:
            existence_status = "indexed_profile"
        else:
            existence_status = "claimed_unverified"
        professional_evidence = professional_evidence_by_node.get(node.id, ())
        if professional_evidence and existence_status == "exact_verified":
            existence_reason = "A first-party public profile API returned this exact account."
        elif existence_status == "exact_verified":
            existence_reason = "The exact first-party public profile exposed the queried handle."
        elif existence_status == "indexed_profile":
            existence_reason = "A bounded search index returned this public professional profile."
        else:
            existence_reason = (
                "The Maigret catalog probe reported this account candidate as claimed."
            )
        reasons = [existence_reason]
        identity_status = "unverified"
        confidence = "low"
        normalized_name = _normalized_display_name(node.display_name)
        professional_match = professional_matches_by_node.get(node.id)
        supporting_matches = professional_support_by_source_node.get(node.id, [])

        if professional_evidence:
            if professional_match:
                identity_status = "likely"
                confidence = professional_match.confidence
                association_sources = _combined_source_ids(
                    sources,
                    list(professional_match.source_ids),
                )
                reasons.extend(professional_match.reasons)
                reasons.append(
                    "This supports a likely public-profile association, not a "
                    "confirmed legal identity."
                )
            else:
                query_names = {
                    normalized
                    for evidence in professional_evidence
                    if (normalized := _normalized_display_name(evidence.query_name))
                }
                if normalized_name and query_names and normalized_name not in query_names:
                    identity_status = "excluded"
                    confidence = "medium"
                    reasons.append(
                        "The professional profile's display name conflicts with "
                        "the root name hypothesis that produced the search lead."
                    )
                else:
                    reasons.append(
                        "A name-derived professional search result needs an "
                        "independent location, cross-link, or third-family anchor."
                    )
        elif supporting_matches:
            chosen = sorted(
                supporting_matches,
                key=lambda item: (
                    -_confidence_rank(item.confidence),
                    item.full_name.casefold(),
                ),
            )[0]
            identity_status = "likely"
            confidence = chosen.confidence
            association_sources = _combined_source_ids(
                sources,
                list(chosen.source_ids),
            )
            reasons.extend(chosen.reasons)
            reasons.append(
                "An independent professional profile corroborates this exact root-handle profile."
            )
        elif is_reference_node:
            reasons.append(
                "The selected account anchor does not establish the real-world person."
                if reference_kind == "selected"
                else "Seed-platform account existence does not establish the real-world person."
            )
        elif not exact_handle:
            reasons.append(
                "A similar handle is only a discovery lead and is not an identity match."
            )
        elif (
            reference_name and normalized_name == reference_name and node.id in first_party_node_ids
        ):
            identity_status = "likely"
            confidence = "medium"
            comparison_node = reference_node
            if reference_kind == "repeated" and comparison_node is node:
                comparison_node = next(
                    (
                        candidate
                        for candidate in exact_nodes
                        if candidate.id != node.id
                        and _normalized_display_name(candidate.display_name) == reference_name
                    ),
                    None,
                )
            association_sources = _combined_source_ids(
                sources,
                source_ids_by_node_id.get(
                    comparison_node.id,
                    [],
                )
                if comparison_node
                else [],
            )
            reasons.append(
                "This exact-handle account was explicitly selected as the search anchor."
                if reference_kind == "selected" and node.id == reference_node.id
                else "The exact handle and display name match the selected account anchor."
                if reference_kind == "selected"
                else "The exact handle and display name match the seed-platform account."
                if reference_kind == "seed"
                else "At least two exact-handle accounts share the same display name."
            )
            reasons.append("This is an account association signal, not confirmation of a person.")
        elif (
            reference_name
            and normalized_name
            and _shares_surname_token(reference_name, normalized_name)
        ):
            identity_status = "unverified"
            confidence = "low"
            association_sources = _combined_source_ids(
                sources,
                list(repeated_reference_source_ids),
            )
            reasons.append(
                "The exact handle and shared surname are weak contextual signals "
                "because the reference full display name repeats on two first-party "
                "accounts."
            )
            reasons.append(
                "The differing given names require an independent person-level anchor "
                "before this account can be associated."
            )
        elif (
            reference_name
            and normalized_name
            and _display_names_incompatible(reference_name, normalized_name)
        ):
            identity_status = "excluded"
            confidence = "medium"
            association_sources = _combined_source_ids(
                sources,
                source_ids_by_node_id.get(reference_node.id, []) if reference_node else [],
            )
            reasons.append(
                "The display name is incompatible with the selected account anchor."
                if reference_kind == "selected"
                else "The display name is incompatible with the seed-platform account."
                if reference_kind == "seed"
                else "The display name conflicts with the repeated candidate group."
            )
        elif exact_handle:
            reasons.append(
                "An exact handle alone is insufficient to associate accounts to one person."
            )

        assessments.append(
            _AccountAssessment(
                node=node,
                existence_status=existence_status,
                identity_status=identity_status,
                confidence=confidence,
                source_ids=sources,
                association_source_ids=association_sources,
                reasons=tuple(reasons),
            )
        )
    return assessments


def _claim_specs(
    *,
    checks: list[MaigretSiteCheck],
    assessments: list[_AccountAssessment],
    observation_by_check_id: dict[str, SourceObservation],
) -> list[_ClaimSpec]:
    specs: list[_ClaimSpec] = []
    check_by_node_id: dict[str, MaigretSiteCheck] = {}
    for check in checks:
        observation = observation_by_check_id.get(check.id)
        if not observation or _evidence_kind(check) != "claimed":
            continue
        profile_url = observation.extracted_fields.get("profile_url")
        if not isinstance(profile_url, str):
            continue
        for assessment in assessments:
            if assessment.node.canonical_url == profile_url:
                check_by_node_id.setdefault(assessment.node.id, check)
                break

    for assessment in assessments:
        if not assessment.source_ids:
            continue
        node = assessment.node
        check = check_by_node_id.get(node.id)
        professional_fields = _professional_profile_fields(node)
        is_professional = bool(professional_fields)
        specs.append(
            _ClaimSpec(
                predicate="account.existence",
                label=_bounded(f"{node.platform} account presence", 120),
                value=_bounded(f"@{node.canonical_handle} on {node.platform}", 400),
                confidence=(
                    "high" if assessment.existence_status == "exact_verified" else "medium"
                ),
                source_ids=assessment.source_ids,
                qualification=(
                    (
                        "GitHub's first-party public API returned this account; "
                        "existence does not by itself identify who controls it."
                        if is_professional
                        else "An exact first-party public profile exposed the queried "
                        "handle; this does not identify who controls it."
                    )
                    if assessment.existence_status == "exact_verified"
                    else (
                        "This profile was returned by a bounded professional search "
                        "index and may be stale; it is not a first-party verification."
                        if assessment.existence_status == "indexed_profile"
                        else "Maigret is used for candidate discovery; a claimed "
                        "result does not establish that the account belongs to the subject."
                    )
                ),
            )
        )
        if node.display_name:
            specs.append(
                _ClaimSpec(
                    predicate="account.display_name",
                    label=_bounded(f"{node.platform} display name", 120),
                    value=_bounded(node.display_name, 400),
                    confidence=(
                        "high" if assessment.existence_status == "exact_verified" else "medium"
                    ),
                    source_ids=assessment.source_ids,
                    qualification=(
                        (
                            "First-party API display name observed at collection time; "
                            "it may change and does not establish a legal identity."
                            if is_professional
                            else "First-party public display name observed at collection "
                            "time; it may change and does not establish a legal identity."
                        )
                        if assessment.existence_status == "exact_verified"
                        else (
                            "Search-index display name; it may be stale and does not "
                            "establish a legal identity."
                            if assessment.existence_status == "indexed_profile"
                            else "Scanner-extracted public display name; it may be stale "
                            "and does not establish a legal identity."
                        )
                    ),
                )
            )
        profile_fields = (
            professional_fields
            if professional_fields
            else (
                _allowlisted_public_profile_fields(check)
                if check is not None and assessment.existence_status == "exact_verified"
                else {}
            )
        )
        headline = profile_fields.get("headline")
        if isinstance(headline, str):
            specs.append(
                _ClaimSpec(
                    predicate="professional.public_headline",
                    label=_bounded(f"{node.platform} public headline", 120),
                    value=_bounded(headline, 400),
                    confidence="medium",
                    source_ids=assessment.source_ids,
                    qualification=(
                        "Public professional-profile headline observed through the "
                        "bounded provider; it may be self-described or stale."
                    ),
                )
            )
        public_bio = profile_fields.get("bio")
        if isinstance(public_bio, str) and (
            not is_professional or assessment.identity_status == "likely"
        ):
            specs.append(
                _ClaimSpec(
                    predicate="account.public_bio",
                    label=_bounded(f"{node.platform} public bio", 120),
                    value=_bounded(public_bio, 400),
                    confidence="high",
                    source_ids=assessment.source_ids,
                    qualification=(
                        "First-party public bio observed at collection time. It is "
                        "self-described, may change, and is not independently verified."
                    ),
                )
            )
        location = (
            profile_fields.get("location")
            if is_professional and assessment.identity_status == "likely"
            else (
                _extract_self_described_location(check.extracted_data)
                if check is not None
                else None
            )
        )
        if location:
            specs.append(
                _ClaimSpec(
                    predicate="account.self_described_location",
                    label="Self-described broad location",
                    value=location,
                    confidence="medium" if is_professional else "low",
                    source_ids=assessment.source_ids,
                    qualification=(
                        "Public professional-profile location observed through "
                        "the bounded provider; it may be self-described, broad, or stale."
                        if is_professional
                        else "Derived only from an explicit public bio location marker; "
                        "it is not a precise or current residence."
                    ),
                )
            )
        if is_professional and assessment.identity_status == "likely":
            specs.extend(
                _professional_history_claim_specs(
                    assessment=assessment,
                    fields=professional_fields,
                )
            )
        if assessment.identity_status == "likely":
            specs.append(
                _ClaimSpec(
                    predicate="account.association",
                    label=_bounded(f"{node.platform} account association", 120),
                    value=_bounded(
                        f"@{node.canonical_handle} is likely associated with the account cluster",
                        400,
                    ),
                    confidence="medium",
                    source_ids=assessment.association_source_ids,
                    qualification=_association_qualification(assessment),
                )
            )
        elif assessment.identity_status in {"excluded", "conflicting"}:
            specs.append(
                _ClaimSpec(
                    predicate="account.association_exclusion",
                    label=_bounded(f"{node.platform} association conflict", 120),
                    value=_bounded(
                        f"@{node.canonical_handle} is excluded from the main account cluster",
                        400,
                    ),
                    confidence="medium",
                    source_ids=assessment.association_source_ids,
                    qualification="The public display name conflicts with the reference account.",
                )
            )

    for check in checks:
        observation = observation_by_check_id.get(check.id)
        if not observation or _evidence_kind(check) != "channel_limited":
            continue
        specs.append(
            _ClaimSpec(
                predicate="channel.coverage",
                label=_bounded(f"{check.site_name} channel status", 120),
                value=check.normalized_status,
                confidence="high",
                source_ids=(observation.id,),
                qualification=(
                    f"The {_channel_label(check.normalized_status)} check cannot establish "
                    "account presence or absence on this channel."
                ),
            )
        )
    return specs


def _professional_profile_fields(node: AccountNode) -> dict[str, object]:
    if not isinstance(node.profile_data, dict):
        return {}
    professional_sources = node.profile_data.get("professional_sources")
    if isinstance(professional_sources, dict):
        for provider_id in (
            "github_professional_search_v1",
            "exa_people_search_v1",
        ):
            value = professional_sources.get(provider_id)
            if isinstance(value, dict):
                return value
    provider_id = node.profile_data.get("source_provider")
    fields = node.profile_data.get("fields")
    if provider_id not in {
        "exa_people_search_v1",
        "github_professional_search_v1",
    } or not isinstance(fields, dict):
        return {}
    return fields


def _professional_history_claim_specs(
    *,
    assessment: _AccountAssessment,
    fields: dict[str, object],
) -> list[_ClaimSpec]:
    specs: list[_ClaimSpec] = []
    node = assessment.node
    indexed = assessment.existence_status == "indexed_profile"
    qualification = (
        "Derived from a professional-profile search index at collection time; "
        "the role may be cached, stale, self-described, and not independently verified."
        if indexed
        else "Observed through a first-party public profile API at collection time; "
        "the field may be self-described and is not independently verified."
    )
    company = fields.get("company")
    if isinstance(company, str):
        specs.append(
            _ClaimSpec(
                predicate="professional.public_company",
                label=_bounded(f"{node.platform} public company", 120),
                value=_bounded(company, 400),
                confidence="medium",
                source_ids=assessment.source_ids,
                qualification=qualification,
            )
        )
    website = fields.get("website")
    if isinstance(website, str):
        specs.append(
            _ClaimSpec(
                predicate="professional.public_website",
                label=_bounded(f"{node.platform} public website", 120),
                value=_bounded(website, 400),
                confidence="medium",
                source_ids=assessment.source_ids,
                qualification=(
                    "Public profile field observed at collection time; ownership of "
                    "the linked site was not independently verified."
                ),
            )
        )
    work_history = fields.get("work_history")
    if isinstance(work_history, list):
        for index, role in enumerate(work_history[:5], start=1):
            if not isinstance(role, dict):
                continue
            title = role.get("title")
            company_name = role.get("company")
            if not isinstance(title, str) and not isinstance(company_name, str):
                continue
            value = " at ".join(
                part
                for part in (
                    title if isinstance(title, str) else None,
                    company_name if isinstance(company_name, str) else None,
                )
                if part
            )
            specs.append(
                _ClaimSpec(
                    predicate="professional.role",
                    label=_bounded(
                        f"{node.platform} public role {index}",
                        120,
                    ),
                    value=_bounded(value, 400),
                    confidence="medium",
                    source_ids=assessment.source_ids,
                    qualification=qualification,
                )
            )
    education_history = fields.get("education_history")
    if isinstance(education_history, list):
        for index, education in enumerate(education_history[:5], start=1):
            if not isinstance(education, dict):
                continue
            degree = education.get("degree")
            institution = education.get("institution")
            if not isinstance(degree, str) and not isinstance(institution, str):
                continue
            value = " — ".join(
                part
                for part in (
                    degree if isinstance(degree, str) else None,
                    institution if isinstance(institution, str) else None,
                )
                if part
            )
            specs.append(
                _ClaimSpec(
                    predicate="professional.education",
                    label=_bounded(
                        f"{node.platform} public education {index}",
                        120,
                    ),
                    value=_bounded(value, 400),
                    confidence="medium",
                    source_ids=assessment.source_ids,
                    qualification=(
                        "Derived from a professional-profile search index at "
                        "collection time; education may be cached, stale, self-described, "
                        "and not independently verified."
                    ),
                )
            )
    return specs


def _persist_claims(
    session: Session,
    *,
    job: SearchJob,
    analysis: AnalysisRevision,
    claim_specs: list[_ClaimSpec],
    observation_ids: set[str],
) -> list[dict[str, object]]:
    lineage_by_observation_id = {
        str(observation_id): str(lineage_key)
        for observation_id, lineage_key in session.execute(
            select(SourceObservation.id, SourceDocument.lineage_key)
            .join(
                ProviderRunSourceUse,
                ProviderRunSourceUse.id == SourceObservation.source_use_id,
            )
            .join(
                SourceDocument,
                SourceDocument.id == ProviderRunSourceUse.document_id,
            )
            .where(SourceObservation.id.in_(sorted(observation_ids)))
        ).all()
    }
    rendered: list[dict[str, object]] = []
    for spec in claim_specs:
        if any(source_id not in observation_ids for source_id in spec.source_ids):
            raise ValueError("Claim evidence cannot cross the frozen footprint snapshot")
        claim = Claim(
            id=new_id(),
            job_id=job.id,
            analysis_revision_id=analysis.id,
            predicate=spec.predicate,
            label=spec.label,
            value=spec.value,
            confidence=spec.confidence,
            displayable=True,
            policy_reason="footprint display allowlist v1",
        )
        session.add(claim)
        for source_id in spec.source_ids:
            session.add(
                ClaimEvidence(
                    id=new_id(),
                    claim_id=claim.id,
                    observation_id=source_id,
                    relation="supports",
                    independence_group=_bounded(
                        lineage_by_observation_id.get(
                            source_id,
                            f"observation:{source_id}",
                        ),
                        160,
                    ),
                    rationale="Deterministic bounded footprint rule",
                )
            )
        rendered.append(
            {
                "claim_id": claim.id,
                "predicate": claim.predicate,
                "label": claim.label,
                "value": claim.value,
                "confidence": claim.confidence,
                "source_ids": list(spec.source_ids),
                "qualification": spec.qualification,
            }
        )
    return rendered


def _grounded_synthesis_view(
    session: Session,
    *,
    job: SearchJob,
    observation_ids: set[str],
    person_decision: _PersonDecision,
    assessments: list[_AccountAssessment],
) -> _SynthesisView:
    if str(job.search_mode or "").casefold() != "deep":
        return _SynthesisView(
            summary=None,
            narrative_sections=(),
            deep_story=None,
            supporting_reasons=(),
            limiting_reasons=(),
            metadata={
                "mode": "deterministic",
                "status": "complete",
                "provider": None,
                "model": None,
                "prompt_version": "deterministic-footprint-v3",
                "fallback_reason": None,
            },
            limitation=None,
        )

    synthesis_run = session.scalar(
        select(ProviderRun)
        .where(
            ProviderRun.job_id == job.id,
            ProviderRun.provider_id.in_(GROUNDED_SYNTHESIS_PROVIDER_IDS),
        )
        .order_by(ProviderRun.logical_run_id)
    )
    synthesis_provider = _synthesis_provider_for_run(synthesis_run)
    result = session.scalar(
        select(GroundedSynthesisResult).where(GroundedSynthesisResult.job_id == job.id)
    )
    if not result:
        return _synthesis_fallback(
            provider=synthesis_provider,
            model=None,
            prompt_version="grounded-footprint-v4",
            reason="grounded_synthesis_not_run",
        )
    if result.status != "success" or not isinstance(result.output, dict):
        return _synthesis_fallback(
            provider=synthesis_provider,
            model=result.model,
            prompt_version=result.prompt_version,
            reason=result.error_code or result.status,
        )

    output = result.output
    summary = output.get("summary")
    summary_source_ids = _validated_source_ids(
        output.get("summary_source_ids"),
        allowed=observation_ids,
        maximum=12,
    )
    if not isinstance(summary, str) or not summary.strip() or not summary_source_ids:
        return _synthesis_fallback(
            provider=synthesis_provider,
            model=result.model,
            prompt_version=result.prompt_version,
            reason="grounded_synthesis_invalid_persisted_output",
        )

    schema_version = output.get("schema_version")
    rich_output = schema_version in {
        "grounded-digital-footprint-v2",
        "grounded-digital-footprint-v3",
        "grounded-digital-footprint-v4",
    }
    raw_sections = output.get("narrative_sections")
    if not isinstance(raw_sections, list) or len(raw_sections) > (12 if rich_output else 6):
        return _synthesis_fallback(
            provider=synthesis_provider,
            model=result.model,
            prompt_version=result.prompt_version,
            reason="grounded_synthesis_invalid_persisted_output",
        )
    sections: list[dict[str, object]] = []
    section_keys: set[str] = set()
    for item in raw_sections:
        if not isinstance(item, dict):
            return _synthesis_fallback(
                provider=synthesis_provider,
                model=result.model,
                prompt_version=result.prompt_version,
                reason="grounded_synthesis_invalid_persisted_output",
            )
        key = item.get("key")
        title = _validated_text(item.get("title"), maximum=120)
        body = _validated_text(item.get("body"), maximum=4_000)
        source_ids = _validated_source_ids(
            item.get("source_ids"),
            allowed=observation_ids,
            maximum=12,
        )
        if (
            not isinstance(key, str)
            or not key.strip()
            or title is None
            or body is None
            or not source_ids
        ):
            return _synthesis_fallback(
                provider=synthesis_provider,
                model=result.model,
                prompt_version=result.prompt_version,
                reason="grounded_synthesis_invalid_persisted_output",
            )
        bounded_key = _bounded(key, 64)
        if bounded_key.casefold() in section_keys:
            continue
        section_keys.add(bounded_key.casefold())
        raw_highlights = item.get("highlights", []) if rich_output else []
        highlights = _validated_cited_texts(
            raw_highlights,
            allowed=observation_ids,
            maximum=6,
        )
        if highlights is None:
            return _synthesis_fallback(
                provider=synthesis_provider,
                model=result.model,
                prompt_version=result.prompt_version,
                reason="grounded_synthesis_invalid_persisted_output",
            )
        sections.append(
            {
                "key": bounded_key,
                "title": title,
                "body": body,
                "source_ids": list(source_ids),
                "highlights": list(highlights),
            }
        )

    supporting = _validated_grounded_reasons(
        output.get("supporting_reasons"),
        allowed=observation_ids,
    )
    limiting = _validated_grounded_reasons(
        output.get("limiting_reasons"),
        allowed=observation_ids,
    )
    if supporting is None or limiting is None:
        return _synthesis_fallback(
            provider=synthesis_provider,
            model=result.model,
            prompt_version=result.prompt_version,
            reason="grounded_synthesis_invalid_persisted_output",
        )
    deep_story = None
    rendered_summary = _bounded(summary, 2_400)
    if rich_output:
        deep_story = _validated_deep_story(
            output,
            allowed_source_ids=observation_ids,
            person_decision=person_decision,
            assessments=assessments,
        )
        if deep_story is None:
            return _synthesis_fallback(
                provider=synthesis_provider,
                model=result.model,
                prompt_version=result.prompt_version,
                reason="grounded_synthesis_invalid_persisted_output",
            )
        rendered_summary = str(deep_story["conclusion"])
    return _SynthesisView(
        summary=rendered_summary,
        narrative_sections=tuple(sections),
        deep_story=deep_story,
        supporting_reasons=supporting,
        limiting_reasons=limiting,
        metadata={
            "mode": "llm_grounded",
            "status": "complete",
            "provider": synthesis_provider,
            "model": _bounded(result.model, 80),
            "prompt_version": _bounded(result.prompt_version, 64),
            "fallback_reason": None,
        },
        limitation=None,
    )


def _synthesis_fallback(
    *,
    provider: str | None,
    model: str | None,
    prompt_version: str,
    reason: str,
) -> _SynthesisView:
    missing_configuration = reason in {
        "grounded_synthesis_disabled",
        "openai_api_key_missing",
        "openrouter_api_key_missing",
    }
    return _SynthesisView(
        summary=None,
        narrative_sections=(),
        deep_story=None,
        supporting_reasons=(),
        limiting_reasons=(),
        metadata={
            "mode": "deterministic",
            "status": "fallback",
            "provider": provider,
            "model": _bounded(model, 80) if model else None,
            "prompt_version": _bounded(prompt_version, 64),
            "fallback_reason": _bounded(reason, 80),
        },
        limitation=(
            "The Deep story engine was not configured; a Quick-grade deterministic "
            "evidence report was delivered as a partial fallback."
            if missing_configuration
            else "The Deep story did not complete or pass source validation; a "
            "Quick-grade deterministic evidence report was delivered as a partial fallback."
        ),
    )


def _synthesis_provider_for_run(run: ProviderRun | None) -> str | None:
    if run is None:
        return None
    query_config = run.query_config if isinstance(run.query_config, dict) else {}
    gateway = str(query_config.get("gateway", "")).strip().casefold()
    if gateway in {"openai", "openrouter"}:
        return gateway
    if run.provider_id == "openai_grounded_synthesis_v1":
        return "openai"
    return None


def _validated_deep_story(
    output: dict[str, object],
    *,
    allowed_source_ids: set[str],
    person_decision: _PersonDecision,
    assessments: list[_AccountAssessment],
) -> dict[str, object] | None:
    schema_version = output.get("schema_version")
    if schema_version not in {
        "grounded-digital-footprint-v2",
        "grounded-digital-footprint-v3",
        "grounded-digital-footprint-v4",
    }:
        return None
    report_synthesis = output.get("report_synthesis")
    if not isinstance(report_synthesis, dict):
        return None
    report_type = report_synthesis.get("report_type")
    identity_status = report_synthesis.get("identity_status")
    confidence = report_synthesis.get("overall_confidence")
    conclusion = _validated_text(
        report_synthesis.get("one_sentence_conclusion"),
        maximum=1_000,
    )
    major_boundary = _validated_text(
        report_synthesis.get("major_boundary"),
        maximum=500,
    )
    conclusion_source_ids = _validated_source_ids(
        report_synthesis.get("source_ids"),
        allowed=allowed_source_ids,
        maximum=8,
    )
    calibration_is_valid = (
        _report_type_is_calibrated(
            model_report_type=report_type,
            model_identity_status=identity_status,
            model_confidence=confidence,
            deterministic_report_type=person_decision.report_type,
        )
        and _identity_status_is_calibrated(
            model_status=identity_status,
            deterministic_status=person_decision.overall_identity_status,
        )
        and _overall_confidence_is_calibrated(
            model_confidence=confidence,
            deterministic_status=person_decision.overall_identity_status,
        )
    )
    if conclusion is None or major_boundary is None or not conclusion_source_ids:
        return None
    if not calibration_is_valid:
        if person_decision.overall_identity_status == "unverified":
            report_type = "account_centric"
            identity_status = "possible"
            confidence = "medium"
            boundary = "The host evidence rules leave the person-level association unverified."
        elif person_decision.overall_identity_status == "likely":
            report_type = "person_centric"
            identity_status = "likely"
            confidence = "medium_high" if confidence == "high" else confidence
            boundary = "The host evidence rules support a likely, not confirmed, association."
        else:
            return None
        conclusion = _plain_bounded(
            f"{conclusion.rstrip('.')}; however, {boundary[0].lower()}{boundary[1:]}",
            1_000,
        )
        major_boundary = _plain_bounded(
            f"{major_boundary.rstrip('.')}. {boundary}",
            500,
        )
    if (
        not _report_type_is_calibrated(
            model_report_type=report_type,
            model_identity_status=identity_status,
            model_confidence=confidence,
            deterministic_report_type=person_decision.report_type,
        )
        or not _identity_status_is_calibrated(
            model_status=identity_status,
            deterministic_status=person_decision.overall_identity_status,
        )
        or not _overall_confidence_is_calibrated(
            model_confidence=confidence,
            deterministic_status=person_decision.overall_identity_status,
        )
        or conclusion is None
        or major_boundary is None
        or not conclusion_source_ids
    ):
        return None

    likely_public_identity = _validated_optional_text(
        report_synthesis.get("likely_public_identity"),
        maximum=240,
    )
    broad_location = _validated_optional_text(
        report_synthesis.get("broad_location"),
        maximum=240,
    )
    if (
        person_decision.overall_identity_status == "unverified"
        and likely_public_identity is not None
        and (identity_status not in {"possible", "likely"} or confidence not in {"low", "medium"})
    ):
        return None
    overview = _validated_text(output.get("summary"), maximum=2_400)
    overview_source_ids = _validated_source_ids(
        output.get("summary_source_ids"),
        allowed=allowed_source_ids,
        maximum=8,
    )
    if overview is None or not overview_source_ids:
        return None

    identity_facts = _validated_identity_facts(
        output.get("identity_facts"),
        allowed_source_ids=allowed_source_ids,
    )
    account_insights = _validated_account_insights(
        output.get("account_assessments"),
        allowed_source_ids=allowed_source_ids,
        assessments=assessments,
    )
    curated_claims = _validated_curated_claims(
        output.get("claims"),
        allowed_source_ids=allowed_source_ids,
        deterministic_identity_status=person_decision.overall_identity_status,
    )
    excluded_candidates = _validated_excluded_candidates(
        output.get("excluded_candidates"),
        allowed_source_ids=allowed_source_ids,
        assessments=assessments,
    )
    channel_coverage = _validated_channel_coverage(
        output.get("channel_coverage"),
        allowed_source_ids=allowed_source_ids,
    )
    next_verification_steps = _validated_cited_texts(
        output.get("next_verification_steps"),
        allowed=allowed_source_ids,
        maximum=6,
    )
    subject_profile = None
    if schema_version in {
        "grounded-digital-footprint-v3",
        "grounded-digital-footprint-v4",
    }:
        subject_profile = _validated_subject_profile(
            output.get("subject_profile"),
            allowed_source_ids=allowed_source_ids,
            require_career_timeline=schema_version == "grounded-digital-footprint-v4",
        )
    if any(
        value is None
        for value in (
            identity_facts,
            account_insights,
            curated_claims,
            excluded_candidates,
            channel_coverage,
            next_verification_steps,
        )
    ) or (
        schema_version
        in {
            "grounded-digital-footprint-v3",
            "grounded-digital-footprint-v4",
        }
        and subject_profile is None
    ):
        return None
    result: dict[str, object] = {
        "version": (
            "deep-story-v4"
            if schema_version == "grounded-digital-footprint-v4"
            else (
                "deep-story-v3"
                if schema_version == "grounded-digital-footprint-v3"
                else "deep-story-v2"
            )
        ),
        "overview": overview,
        "overview_source_ids": list(overview_source_ids),
        "conclusion": conclusion,
        "conclusion_source_ids": list(conclusion_source_ids),
        "overall_confidence": confidence,
        "likely_public_identity": likely_public_identity,
        "broad_location": broad_location,
        "major_boundary": major_boundary,
        "identity_facts": list(identity_facts),
        "account_insights": list(account_insights),
        "curated_claims": list(curated_claims),
        "excluded_candidates": list(excluded_candidates),
        "channel_coverage": list(channel_coverage),
        "next_verification_steps": list(next_verification_steps),
    }
    if subject_profile is not None:
        result["subject_profile"] = subject_profile
    return result


def _validated_subject_profile(
    value: object,
    *,
    allowed_source_ids: set[str],
    require_career_timeline: bool,
) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    answers: dict[str, dict[str, object]] = {}
    for key in ("identity", "location", "occupation", "education"):
        answer = _validated_profile_answer(
            value.get(key),
            allowed_source_ids=allowed_source_ids,
        )
        if answer is None:
            return None
        answers[key] = answer

    traits: dict[str, list[dict[str, object]]] = {}
    for key in ("interests", "likes", "dislikes"):
        items = _validated_profile_traits(
            value.get(key),
            allowed_source_ids=allowed_source_ids,
            field_name=key,
        )
        if items is None:
            return None
        traits[key] = list(items)

    unknowns = _validated_profile_unknowns(
        value.get("unknowns"),
        allowed_source_ids=allowed_source_ids,
    )
    if unknowns is None:
        return None
    result: dict[str, object] = {
        **answers,
        **traits,
        "unknowns": list(unknowns),
        "career_timeline": [],
    }
    if not require_career_timeline:
        return result

    career_timeline = _validated_career_timeline(
        value.get("career_timeline"),
        allowed_source_ids=allowed_source_ids,
    )
    if career_timeline is None:
        return None
    result["career_timeline"] = list(career_timeline)
    return result


def _validated_profile_answer(
    value: object,
    *,
    allowed_source_ids: set[str],
) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    answer = _validated_optional_text(value.get("value"), maximum=600)
    confidence = value.get("confidence")
    basis = value.get("basis")
    explanation = _validated_text(value.get("explanation"), maximum=500)
    source_ids = _validated_optional_source_ids(
        value.get("source_ids"),
        allowed=allowed_source_ids,
        maximum=8,
    )
    known_bases = {"observed", "self_described", "indexed", "inferred", "mixed"}
    if explanation is None or source_ids is None:
        return None
    answer_is_supported = (
        answer is not None
        and confidence in {"low", "medium", "medium_high", "high"}
        and basis in known_bases
        and bool(source_ids)
    )
    if not answer_is_supported:
        answer = None
        confidence = None
        basis = "unknown"
        source_ids = ()
    return {
        "value": answer,
        "confidence": confidence,
        "basis": basis,
        "explanation": explanation,
        "source_ids": list(source_ids),
    }


def _validated_profile_traits(
    value: object,
    *,
    allowed_source_ids: set[str],
    field_name: str,
) -> tuple[dict[str, object], ...] | None:
    if not isinstance(value, list) or len(value) > 8:
        return None
    result: list[dict[str, object]] = []
    labels: set[str] = set()
    known_bases = {"observed", "self_described", "indexed", "inferred", "mixed"}
    for item in value:
        if not isinstance(item, dict):
            return None
        label = _validated_text(item.get("label"), maximum=240)
        confidence = item.get("confidence")
        basis = item.get("basis")
        explanation = _validated_text(item.get("explanation"), maximum=500)
        source_ids = _validated_optional_source_ids(
            item.get("source_ids"),
            allowed=allowed_source_ids,
            maximum=8,
        )
        if (
            label is None
            or confidence not in {"low", "medium", "medium_high", "high"}
            or basis not in known_bases
            or explanation is None
            or source_ids is None
        ):
            return None
        if (
            label.casefold() in labels
            or not source_ids
            or (field_name == "dislikes" and basis not in {"observed", "self_described", "mixed"})
        ):
            continue
        labels.add(label.casefold())
        result.append(
            {
                "label": label,
                "confidence": confidence,
                "basis": basis,
                "explanation": explanation,
                "source_ids": list(source_ids),
            }
        )
    return tuple(result)


def _validated_profile_unknowns(
    value: object,
    *,
    allowed_source_ids: set[str],
) -> tuple[dict[str, object], ...] | None:
    allowed_topics = {
        "identity",
        "location",
        "occupation",
        "education",
        "interests",
        "likes",
        "dislikes",
        "projects",
        "other",
    }
    if not isinstance(value, list) or len(value) > 8:
        return None
    result: list[dict[str, object]] = []
    topics: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return None
        topic = item.get("topic")
        explanation = _validated_text(item.get("explanation"), maximum=500)
        source_ids = _validated_optional_source_ids(
            item.get("source_ids"),
            allowed=allowed_source_ids,
            maximum=8,
        )
        if (
            not isinstance(topic, str)
            or topic not in allowed_topics
            or explanation is None
            or source_ids is None
        ):
            return None
        if topic in topics:
            continue
        topics.add(topic)
        result.append(
            {
                "topic": topic,
                "explanation": explanation,
                "source_ids": list(source_ids),
            }
        )
    return tuple(result)


def _validated_career_timeline(
    value: object,
    *,
    allowed_source_ids: set[str],
) -> tuple[dict[str, object], ...] | None:
    if not isinstance(value, list) or len(value) > 12:
        return None
    result: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    allowed_bases = {"observed", "self_described", "indexed", "mixed"}
    for item in value:
        if not isinstance(item, dict):
            return None
        source_ids = _validated_optional_source_ids(
            item.get("source_ids"),
            allowed=allowed_source_ids,
            maximum=8,
        )
        if source_ids is None:
            return None
        entry_type = item.get("entry_type")
        title = _validated_text(item.get("title"), maximum=240)
        organization = _validated_optional_text(item.get("organization"), maximum=240)
        timeframe = _validated_optional_text(item.get("timeframe"), maximum=240)
        currentness = item.get("currentness")
        confidence = item.get("confidence")
        basis = item.get("basis")
        explanation = _validated_text(item.get("explanation"), maximum=500)
        if (
            entry_type not in {"work", "education"}
            or title is None
            or currentness not in {"current", "recent", "historical", "unclear"}
            or confidence not in {"low", "medium", "medium_high", "high"}
            or basis not in allowed_bases
            or explanation is None
            or not source_ids
        ):
            continue
        if (basis == "indexed" and currentness == "current") or (
            timeframe is None and currentness in {"current", "recent"}
        ):
            currentness = "unclear"
        key = (
            entry_type,
            title.casefold(),
            organization.casefold() if organization else "",
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "entry_type": entry_type,
                "title": title,
                "organization": organization,
                "timeframe": timeframe,
                "currentness": currentness,
                "confidence": confidence,
                "basis": basis,
                "explanation": explanation,
                "source_ids": list(source_ids),
            }
        )
    return tuple(result)


def _validated_identity_facts(
    value: object,
    *,
    allowed_source_ids: set[str],
) -> tuple[dict[str, object], ...] | None:
    if not isinstance(value, list) or len(value) > 12:
        return None
    result: list[dict[str, object]] = []
    labels: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return None
        label = _validated_text(item.get("label"), maximum=120)
        fact_value = _validated_text(item.get("value"), maximum=600)
        confidence = item.get("confidence")
        status = item.get("status")
        qualification = _validated_optional_text(item.get("qualification"), maximum=500)
        source_ids = _validated_source_ids(
            item.get("source_ids"),
            allowed=allowed_source_ids,
            maximum=8,
        )
        if (
            label is None
            or fact_value is None
            or confidence not in {"low", "medium", "medium_high", "high"}
            or status
            not in {
                "observed",
                "self_described",
                "indexed",
                "likely",
                "independently_unverified",
                "unknown",
            }
            or not source_ids
        ):
            return None
        if label.casefold() in labels:
            continue
        labels.add(label.casefold())
        result.append(
            {
                "label": label,
                "value": fact_value,
                "confidence": confidence,
                "status": status,
                "qualification": qualification,
                "source_ids": list(source_ids),
            }
        )
    return tuple(result)


def _validated_account_insights(
    value: object,
    *,
    allowed_source_ids: set[str],
    assessments: list[_AccountAssessment],
) -> tuple[dict[str, object], ...] | None:
    if not isinstance(value, list) or len(value) > 30:
        return None
    by_id = {item.node.id: item for item in assessments}
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return None
        account_id = item.get("account_id")
        assessment = by_id.get(account_id) if isinstance(account_id, str) else None
        rationale = _validated_text(item.get("rationale"), maximum=500)
        source_ids = _validated_source_ids(
            item.get("source_ids"),
            allowed=allowed_source_ids,
            maximum=8,
        )
        public_facts = _validated_cited_texts(
            item.get("public_facts"),
            allowed=allowed_source_ids,
            maximum=6,
        )
        association_reasons = _validated_cited_texts(
            item.get("association_reasons"),
            allowed=allowed_source_ids,
            maximum=6,
        )
        if (
            assessment is None
            or rationale is None
            or not source_ids
            or public_facts is None
            or association_reasons is None
            or item.get("canonical_url") != assessment.node.canonical_url
            or str(item.get("canonical_handle", "")).casefold()
            != assessment.node.canonical_handle.casefold()
            or str(item.get("platform", "")).casefold() != assessment.node.platform.casefold()
            or item.get("association_status")
            not in {
                "confirmed",
                "likely",
                "possible",
                "unverified",
                "excluded",
                "not_applicable",
            }
        ):
            return None
        if account_id in seen:
            continue
        model_association = item.get("association_status")
        if assessment.identity_status in {"unverified", "excluded"} and (
            model_association in {"confirmed", "likely", "possible"}
        ):
            boundary = (
                "The host account graph excludes this profile from the person cluster."
                if assessment.identity_status == "excluded"
                else "The host account graph leaves this person-level association unverified."
            )
            rationale = _plain_bounded(f"{rationale.rstrip('.')}. {boundary}", 500)
        seen.add(account_id)
        result.append(
            {
                "account_id": account_id,
                "rationale": rationale,
                "source_ids": list(source_ids),
                "public_facts": list(public_facts),
                "association_reasons": list(association_reasons),
            }
        )
    return tuple(result)


def _validated_curated_claims(
    value: object,
    *,
    allowed_source_ids: set[str],
    deterministic_identity_status: str,
) -> tuple[dict[str, object], ...] | None:
    if not isinstance(value, list) or len(value) > 16:
        return None
    result: list[dict[str, object]] = []
    claim_ids: set[str] = set()
    claim_keys: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            return None
        claim_id = _validated_text(item.get("claim_id"), maximum=160)
        predicate = _validated_text(item.get("predicate"), maximum=120)
        label = _validated_text(item.get("label"), maximum=120)
        claim_value = _validated_text(item.get("value"), maximum=600)
        confidence = item.get("confidence")
        status = item.get("status")
        qualification = _validated_optional_text(item.get("qualification"), maximum=500)
        source_ids = _validated_source_ids(
            item.get("source_ids"),
            allowed=allowed_source_ids,
            maximum=8,
        )
        contradicting_source_ids = _validated_optional_source_ids(
            item.get("contradicting_source_ids"),
            allowed=allowed_source_ids,
            maximum=8,
        )
        supporting_evidence = _validated_cited_texts(
            item.get("supporting_evidence"),
            allowed=allowed_source_ids,
            maximum=6,
        )
        limiting_evidence = _validated_cited_texts(
            item.get("limiting_evidence"),
            allowed=allowed_source_ids,
            maximum=6,
        )
        if (
            claim_id is None
            or predicate is None
            or label is None
            or claim_value is None
            or confidence not in {"low", "medium", "medium_high", "high"}
            or status
            not in {
                "confirmed",
                "likely",
                "possible",
                "independently_unverified",
                "contradicted",
                "unknown",
            }
            or not source_ids
            or contradicting_source_ids is None
            or supporting_evidence is None
            or limiting_evidence is None
        ):
            return None
        claim_key = (predicate, claim_value.casefold())
        if claim_id in claim_ids or claim_key in claim_keys:
            continue
        if predicate == "person.public_identity" and not _person_claim_status_is_calibrated(
            model_status=status,
            deterministic_status=deterministic_identity_status,
        ):
            if deterministic_identity_status == "unverified":
                status = "possible"
                if confidence in {"high", "medium_high"}:
                    confidence = "medium"
            elif deterministic_identity_status == "likely":
                status = "likely"
                if confidence == "high":
                    confidence = "medium_high"
            boundary = "Person-level association remains qualified by the host evidence rules."
            qualification = _plain_bounded(
                (f"{qualification.rstrip('.')}. {boundary}" if qualification else boundary),
                500,
            )
        claim_ids.add(claim_id)
        claim_keys.add(claim_key)
        result.append(
            {
                "claim_id": claim_id,
                "predicate": predicate,
                "label": label,
                "value": claim_value,
                "confidence": confidence,
                "status": status,
                "source_ids": list(source_ids),
                "contradicting_source_ids": list(contradicting_source_ids),
                "qualification": qualification,
                "supporting_evidence": list(supporting_evidence),
                "limiting_evidence": list(limiting_evidence),
            }
        )
    return tuple(result)


def _validated_excluded_candidates(
    value: object,
    *,
    allowed_source_ids: set[str],
    assessments: list[_AccountAssessment],
) -> tuple[dict[str, object], ...] | None:
    if not isinstance(value, list) or len(value) > 16:
        return None
    by_id = {item.node.id: item for item in assessments}
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        account_id = item.get("account_id")
        label = _validated_text(item.get("label"), maximum=240)
        disposition = item.get("disposition")
        reason = _validated_text(item.get("reason"), maximum=500)
        source_ids = _validated_source_ids(
            item.get("source_ids"),
            allowed=allowed_source_ids,
            maximum=8,
        )
        if (
            label is None
            or disposition
            not in {
                "excluded",
                "unverified",
                "derivative",
                "no_exact_hit",
                "separate_cluster",
            }
            or reason is None
            or not source_ids
        ):
            return None
        if account_id is not None:
            if not isinstance(account_id, str):
                return None
            assessment = by_id.get(account_id)
            if assessment is None or (
                item.get("canonical_url") is not None
                and item.get("canonical_url") != assessment.node.canonical_url
            ):
                return None
            if assessment.identity_status in {"confirmed", "likely"}:
                continue
            if disposition == "excluded" and assessment.identity_status not in {
                "conflicting",
                "excluded",
            }:
                disposition = "unverified"
        elif item.get("canonical_url") is not None:
            return None
        result.append(
            {
                "account_id": account_id,
                "label": label,
                "disposition": disposition,
                "reason": reason,
                "source_ids": list(source_ids),
            }
        )
    return tuple(result)


def _validated_channel_coverage(
    value: object,
    *,
    allowed_source_ids: set[str],
) -> tuple[dict[str, object], ...] | None:
    if not isinstance(value, list) or len(value) > 24:
        return None
    result: list[dict[str, object]] = []
    channels: set[str] = set()
    allowed_statuses = {
        "confirmed",
        "likely",
        "candidate",
        "unverified",
        "no_exact_hit",
        "channel_limited",
        "excluded",
        "not_checked",
    }
    for item in value:
        if not isinstance(item, dict):
            return None
        channel = _validated_text(item.get("channel"), maximum=120)
        status = item.get("status")
        detail = _validated_text(item.get("detail"), maximum=500)
        source_ids = _validated_source_ids(
            item.get("source_ids"),
            allowed=allowed_source_ids,
            maximum=8,
        )
        if channel is None or status not in allowed_statuses or detail is None or not source_ids:
            return None
        if channel.casefold() in channels:
            continue
        channels.add(channel.casefold())
        result.append(
            {
                "channel": channel,
                "status": status,
                "detail": detail,
                "source_ids": list(source_ids),
            }
        )
    return tuple(result)


def _identity_status_is_calibrated(
    *,
    model_status: object,
    deterministic_status: str,
) -> bool:
    allowed_by_deterministic = {
        "unverified": {"likely", "possible", "ambiguous", "unresolved"},
        "likely": {"likely", "possible", "ambiguous", "unresolved"},
        "confirmed": {"confirmed", "likely", "possible", "ambiguous", "unresolved"},
    }
    return model_status in allowed_by_deterministic.get(deterministic_status, set())


def _report_type_is_calibrated(
    *,
    model_report_type: object,
    model_identity_status: object,
    model_confidence: object,
    deterministic_report_type: str,
) -> bool:
    if model_report_type == deterministic_report_type:
        return True
    return (
        deterministic_report_type == "account_centric"
        and model_report_type == "person_centric"
        and model_identity_status in {"possible", "likely"}
        and model_confidence in {"low", "medium"}
    )


def _account_status_is_calibrated(
    *,
    model_status: object,
    deterministic_status: str,
) -> bool:
    if model_status not in {
        "confirmed",
        "likely",
        "possible",
        "unverified",
        "excluded",
        "not_applicable",
    }:
        return False
    if deterministic_status == "confirmed":
        return True
    if deterministic_status == "likely":
        return model_status != "confirmed"
    return model_status not in {"confirmed", "likely"}


def _overall_confidence_is_calibrated(
    *,
    model_confidence: object,
    deterministic_status: str,
) -> bool:
    allowed_by_deterministic = {
        "unverified": {"low", "medium"},
        "likely": {"low", "medium", "medium_high"},
        "confirmed": {"low", "medium", "medium_high", "high"},
    }
    return model_confidence in allowed_by_deterministic.get(deterministic_status, set())


def _person_claim_status_is_calibrated(
    *,
    model_status: object,
    deterministic_status: str,
) -> bool:
    allowed_by_deterministic = {
        "unverified": {
            "possible",
            "independently_unverified",
            "contradicted",
            "unknown",
        },
        "likely": {
            "likely",
            "possible",
            "independently_unverified",
            "contradicted",
            "unknown",
        },
        "confirmed": {
            "confirmed",
            "likely",
            "possible",
            "independently_unverified",
            "contradicted",
            "unknown",
        },
    }
    return model_status in allowed_by_deterministic.get(deterministic_status, set())


def _validated_text(value: object, *, maximum: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _plain_bounded(value, maximum)


def _plain_bounded(value: str, maximum: int) -> str:
    cleaned = html.unescape(value)
    cleaned = re.sub(r"<[^>]*>", " ", cleaned)
    cleaned = cleaned.replace("<", "").replace(">", "")
    cleaned = " ".join(cleaned.split())
    cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
    return cleaned[:maximum]


def _validated_optional_text(value: object, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _validated_text(value, maximum=maximum)


def _validated_cited_texts(
    value: object,
    *,
    allowed: set[str],
    maximum: int,
) -> tuple[dict[str, object], ...] | None:
    if not isinstance(value, list) or len(value) > maximum:
        return None
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        text = _validated_text(item.get("text"), maximum=500)
        source_ids = _validated_source_ids(
            item.get("source_ids"),
            allowed=allowed,
            maximum=8,
        )
        if text is None or not source_ids:
            return None
        result.append({"text": text, "source_ids": list(source_ids)})
    return tuple(result)


def _validated_source_ids(
    value: object,
    *,
    allowed: set[str],
    maximum: int,
) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        return None
    result: list[str] = []
    seen: set[str] = set()
    for source_id in value:
        if not isinstance(source_id, str) or source_id not in allowed or source_id in seen:
            return None
        seen.add(source_id)
        result.append(source_id)
    return tuple(result)


def _validated_optional_source_ids(
    value: object,
    *,
    allowed: set[str],
    maximum: int,
) -> tuple[str, ...] | None:
    if not isinstance(value, list) or len(value) > maximum:
        return None
    if not value:
        return ()
    return _validated_source_ids(value, allowed=allowed, maximum=maximum)


def _validated_grounded_reasons(
    value: object,
    *,
    allowed: set[str],
) -> tuple[str, ...] | None:
    if not isinstance(value, list) or len(value) > 12:
        return None
    reasons: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        text = item.get("text")
        source_ids = _validated_source_ids(
            item.get("source_ids"),
            allowed=allowed,
            maximum=8,
        )
        if not isinstance(text, str) or not text.strip() or not source_ids:
            return None
        reasons.append(_bounded(text, 400))
    return tuple(_dedupe_text(reasons))


def _dedupe_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _provider_manifest(
    session: Session,
    *,
    runs: list[ProviderRun],
) -> list[dict[str, object]]:
    scans = {
        scan.provider_run_id: scan
        for scan in session.scalars(
            select(MaigretScanRun).where(
                MaigretScanRun.provider_run_id.in_([run.id for run in runs])
            )
        ).all()
    }
    syntheses = {
        result.provider_run_id: result
        for result in session.scalars(
            select(GroundedSynthesisResult).where(
                GroundedSynthesisResult.provider_run_id.in_([run.id for run in runs])
            )
        ).all()
    }
    manifest: list[dict[str, object]] = []
    for run in runs:
        item: dict[str, object] = {
            "provider_run_id": run.id,
            "provider_id": run.provider_id,
            "logical_run_id": run.logical_run_id,
            "status": run.status,
            "result_count": run.result_count,
            "required_for_finalization": run.required_for_finalization,
            "parent_run_id": run.parent_run_id,
            "depth": run.depth,
            "query_config_checksum": stable_payload_hash(run.query_config or {}),
        }
        if run.provider_id == "exa_people_search_v1":
            item["max_results"] = _manifest_bound(
                run.query_config,
                "max_results",
                maximum=5,
            )
            item["max_results_per_query"] = item["max_results"]
        elif run.provider_id == "github_professional_search_v1":
            item["max_profiles"] = _manifest_bound(
                run.query_config,
                "max_profiles",
                maximum=3,
            )
        elif run.provider_id in GROUNDED_SYNTHESIS_PROVIDER_IDS:
            synthesis = syntheses.get(run.id)
            if synthesis:
                item.update(
                    {
                        "gateway": _synthesis_provider_for_run(run),
                        "synthesis_status": synthesis.status,
                        "model": synthesis.model,
                        "prompt_version": synthesis.prompt_version,
                        "input_checksum": synthesis.input_checksum,
                        "output_checksum": (
                            stable_payload_hash(synthesis.output) if synthesis.output else None
                        ),
                    }
                )
        if (
            run.provider_id in {"exa_people_search_v1", "github_professional_search_v1"}
            and isinstance(run.query_config, dict)
            and run.query_config.get("retrieval_mode") in {"adaptive", "deep"}
        ):
            item.update(
                {
                    "retrieval_mode": "adaptive",
                    "query_budget": _manifest_bound(
                        run.query_config,
                        "query_budget",
                        maximum=36,
                    ),
                    "request_budget": _manifest_bound(
                        run.query_config,
                        "request_budget",
                        maximum=64,
                    ),
                    "result_budget": _manifest_bound(
                        run.query_config,
                        "result_budget",
                        maximum=50,
                    ),
                    "unique_profile_budget": _manifest_bound(
                        run.query_config,
                        "result_budget",
                        maximum=50,
                    ),
                    "time_budget_seconds": _manifest_bound(
                        run.query_config,
                        "time_budget_seconds",
                        maximum=300,
                    ),
                    "stagnation_query_limit": _manifest_bound(
                        run.query_config,
                        "stagnation_query_limit",
                        maximum=6,
                    ),
                }
            )
        scan = scans.get(run.id)
        if scan:
            item.update(
                {
                    "catalog_snapshot_id": scan.catalog_snapshot_id,
                    "selected_site_manifest_checksum": (scan.selected_site_manifest_checksum),
                    "selected_count": scan.selected_count,
                    "completed_count": scan.completed_count,
                    "found_count": scan.found_count,
                    "not_found_count": scan.not_found_count,
                    "unknown_count": scan.unknown_count,
                    "illegal_count": scan.illegal_count,
                }
            )
        manifest.append(item)
    return manifest


def _identity_reasons(
    assessments: list[_AccountAssessment],
    *,
    person_decision: _PersonDecision,
) -> dict[str, list[str]]:
    supporting = sorted(
        {
            reason
            for assessment in assessments
            if assessment.identity_status == "likely"
            for reason in assessment.reasons
            if "match" in reason.casefold() or "share" in reason.casefold()
        }
    )
    if person_decision.reason:
        supporting.append(person_decision.reason)
    limiting = {
        "Maigret catalog results are discovery signals and do not prove "
        "that multiple accounts belong to one person.",
    }
    if person_decision.overall_identity_status == "likely":
        limiting.add(
            "The person-level association is likely, not confirmed; no reciprocal "
            "first-party cross-link or unique stable identifier was collected."
        )
    else:
        limiting.add(
            "No unique full-name hypothesis met the independent professional-anchor threshold."
        )
    if any(item.identity_status in {"excluded", "conflicting"} for item in assessments):
        limiting.add(
            "At least one candidate has a conflicting public display name and "
            "was not merged into the main account cluster."
        )
    if any(not item.node.display_name for item in assessments):
        limiting.add("Some candidates have no allowlisted display name for comparison.")
    display_names = {
        normalized
        for item in assessments
        if item.existence_status == "exact_verified"
        if (normalized := _normalized_display_name(item.node.display_name))
    }
    if len(display_names) > 1:
        limiting.add(
            "Exact first-party profiles expose differing display names; an independent "
            "person-level anchor is required to resolve them."
        )
    return {
        "supporting": supporting,
        "limiting": sorted(limiting),
    }


def _limitations(
    *,
    search_mode: str | None,
    runs: list[ProviderRun],
    checks: list[MaigretSiteCheck],
    skipped_evidence_sites: list[str],
) -> list[str]:
    limitations = {
        "This adaptive scan uses job-level request, result, and time budgets; it "
        "does not cover every service, private profile, deleted profile, or "
        "historical account.",
        "Maigret claimed results identify account candidates; they do not verify "
        "the real-world person behind an account.",
        "Scanner-extracted public display names and bio signals may be stale or incomplete.",
    }
    professional_runs = [
        run
        for run in runs
        if run.provider_id in {"exa_people_search_v1", "github_professional_search_v1"}
    ]
    if professional_runs:
        limitations.add(
            "Professional search expanded query variants adaptively under an "
            "aggregate job budget; name-only results remain unverified."
        )
    if any(
        run.provider_id == "exa_people_search_v1" and run.result_count > 0
        for run in professional_runs
    ):
        limitations.add(
            "LinkedIn professional fields came through a search index and may be "
            "cached, incomplete, or stale rather than first-party live profile data."
        )
    for check in checks:
        if check.normalized_status in _CHANNEL_LIMITED_STATES:
            limitations.add(
                f"{check.site_name} was {_channel_label(check.normalized_status)}; "
                "presence or absence there is unknown."
            )
    for run in runs:
        if run.status in _CONCLUSIVE_RUN_STATES or run.status == "partial_success":
            continue
        if run.provider_id == "maigret_discovery_v1":
            limitations.add(
                f"A Maigret scan shard ended as {_channel_label(run.status)}; "
                "its uncompleted channels remain unknown."
            )
        elif run.provider_id == "exa_people_search_v1":
            limitations.add(
                f"The adaptive Exa people search ended as {_channel_label(run.status)}; "
                "professional-profile coverage is incomplete."
            )
        elif run.provider_id == "github_professional_search_v1":
            limitations.add(
                f"The adaptive GitHub professional search ended as "
                f"{_channel_label(run.status)}; GitHub coverage is incomplete."
            )
    for site_name in skipped_evidence_sites:
        limitations.add(
            f"{site_name} produced a relevant check without a safe source URL, "
            "so it was not promoted into report evidence."
        )
    return sorted(limitations)


def _summary(
    *,
    job: SearchJob,
    assessments: list[_AccountAssessment],
    checks: list[MaigretSiteCheck],
    person_decision: _PersonDecision,
) -> str:
    handle = _bounded(f"@{job.seed_identifier or ''}", 170)
    limited_count = sum(check.normalized_status in _CHANNEL_LIMITED_STATES for check in checks)
    if (
        assessments
        and person_decision.overall_identity_status == "likely"
        and person_decision.full_name
    ):
        summary = (
            f"Found {len(assessments)} public account candidate"
            f"{'s' if len(assessments) != 1 else ''} for {handle}. "
            f"Independent professional evidence supports a likely association with "
            f"{person_decision.full_name}, while weaker or conflicting leads remain separate."
        )
    elif assessments:
        summary = (
            f"Found {len(assessments)} public account candidate"
            f"{'s' if len(assessments) != 1 else ''} for {handle}. "
            "The available Maigret evidence supports an account-centric brief, "
            "but it does not establish one real-world person."
        )
    else:
        summary = (
            f"No account candidates were reported for {handle} in this bounded catalog scan. "
            "This does not prove that the handle is absent elsewhere."
        )
    if limited_count:
        summary += (
            f" {limited_count} channel check"
            f"{'s were' if limited_count != 1 else ' was'} inconclusive."
        )
    return summary


def _subject(
    job: SearchJob,
    *,
    assessments: list[_AccountAssessment],
    person_decision: _PersonDecision,
) -> str:
    handle = f"@{job.seed_identifier or ''}"
    if person_decision.overall_identity_status == "likely" and person_decision.full_name:
        return _bounded(f"{person_decision.full_name} ({handle})", 240)
    selected_account = next(
        (
            assessment.node
            for assessment in assessments
            if assessment.node.selection_state == "included"
            and assessment.existence_status == "exact_verified"
            and _is_exact_handle(assessment.node, job)
        ),
        None,
    )
    if selected_account and selected_account.display_name:
        return _bounded(
            f"{html.unescape(selected_account.display_name)} ({handle})",
            240,
        )
    seed_account = next(
        (
            assessment.node
            for assessment in assessments
            if job.seed_platform
            and assessment.existence_status == "exact_verified"
            and _is_exact_handle(assessment.node, job)
            and _platform_key(assessment.node.platform) == _platform_key(job.seed_platform)
        ),
        None,
    )
    if seed_account and seed_account.display_name:
        return _bounded(
            f"{html.unescape(seed_account.display_name)} ({handle})",
            240,
        )
    if job.seed_platform:
        return _bounded(f"{handle} on {job.seed_platform}", 240)
    return _bounded(handle, 240)


def _render_account(assessment: _AccountAssessment) -> dict[str, object]:
    node = assessment.node
    return {
        "candidate_id": node.id,
        "platform": node.platform,
        "handle": node.canonical_handle,
        "profile_url": node.canonical_url,
        "display_name": node.display_name,
        "existence_status": assessment.existence_status,
        "identity_status": assessment.identity_status,
        "confidence": assessment.confidence,
        "source_ids": list(assessment.source_ids),
        "reasons": list(assessment.reasons),
    }


def _assessment_checksum_item(
    assessment: _AccountAssessment,
) -> dict[str, object]:
    return {
        "candidate_id": assessment.node.id,
        "existence_status": assessment.existence_status,
        "identity_status": assessment.identity_status,
        "confidence": assessment.confidence,
        "source_ids": list(assessment.source_ids),
        "association_source_ids": list(assessment.association_source_ids),
        "reasons": list(assessment.reasons),
    }


def _claim_checksum_item(spec: _ClaimSpec) -> dict[str, object]:
    return {
        "predicate": spec.predicate,
        "label": spec.label,
        "value": spec.value,
        "confidence": spec.confidence,
        "source_ids": list(spec.source_ids),
        "qualification": spec.qualification,
    }


def _association_qualification(assessment: _AccountAssessment) -> str:
    if any(
        "professional profile" in reason.casefold() or "independent profiles" in reason.casefold()
        for reason in assessment.reasons
    ):
        return (
            "Based on a source-linked professional-profile anchor plus an exact "
            "full-name and contextual or direct public match. The association is "
            "likely, not a confirmed legal identity."
        )
    if any("shared surname" in reason.casefold() for reason in assessment.reasons):
        return (
            "Based on the exact handle, a reference display name repeated on two "
            "first-party accounts, and a shared surname. Differing given names keep "
            "the real-world person unverified."
        )
    return (
        "Based on the exact handle and matching display name; the real-world person "
        "remains unverified."
    )


def _locations_compatible(left: str, right: str) -> bool:
    ignored = {
        "area",
        "bay",
        "ca",
        "city",
        "greater",
        "state",
        "states",
        "the",
        "united",
        "usa",
    }

    def tokens(value: str) -> set[str]:
        normalized = " ".join(
            _NAME_TOKEN_PATTERN.findall(unicodedata.normalize("NFKC", value).casefold())
        )
        result = {token for token in normalized.split() if token not in ignored and len(token) >= 3}
        if any(
            region in normalized
            for region in (
                "bay area",
                "san francisco",
                "san jose",
                "santa clara",
                "silicon valley",
                "oakland",
            )
        ):
            result.add("region:sf-bay-area")
        return result

    left_tokens = tokens(left)
    right_tokens = tokens(right)
    return bool(left_tokens and right_tokens and left_tokens & right_tokens)


def _platform_family(platform: str) -> str:
    key = _platform_key(platform)
    return "meta" if key in {"instagram", "threads"} else key


def _confidence_rank(value: str) -> int:
    return {
        "low": 1,
        "medium": 2,
        "medium_high": 3,
        "high": 4,
    }.get(value, 0)


def _manifest_bound(
    config: dict[str, object] | None,
    key: str,
    *,
    maximum: int,
) -> int:
    raw = config.get(key) if isinstance(config, dict) else None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = maximum
    return max(1, min(maximum, value))


def _source_url(check: MaigretSiteCheck) -> str | None:
    for candidate in (check.url_user, check.url_probe, check.url_main):
        if candidate and len(candidate) <= 400 and _safe_http_url(candidate):
            return candidate
    return None


def _safe_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return bool(
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    )


def _is_exact_handle(node: AccountNode, job: SearchJob) -> bool:
    return is_exact_handle_account(node, job)


def _platform_key(value: str) -> str:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if character.isalnum()
    )
    return _PLATFORM_ALIASES.get(normalized, normalized)


def _normalized_display_name(value: str | None) -> str | None:
    if not value:
        return None
    normalized = unicodedata.normalize("NFKC", html.unescape(value)).casefold()
    tokens = _NAME_TOKEN_PATTERN.findall(normalized)
    return " ".join(tokens) or None


def _display_names_incompatible(left: str, right: str) -> bool:
    if left == right:
        return False
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    return bool(left_tokens and right_tokens and left_tokens.isdisjoint(right_tokens))


def _shares_surname_token(left: str, right: str) -> bool:
    left_tokens = left.split()
    right_tokens = right.split()
    return bool(
        len(left_tokens) >= 2
        and len(right_tokens) >= 2
        and len(left_tokens[-1]) >= 2
        and left_tokens[-1] == right_tokens[-1]
    )


def _combined_source_ids(
    left: tuple[str, ...],
    right: list[str],
) -> tuple[str, ...]:
    return tuple(sorted(set(left).union(right)))


def _channel_label(value: str) -> str:
    return value.replace("_", " ")


def _bounded(value: str, max_length: int) -> str:
    return safe_text(value, max_length=max_length)
