from __future__ import annotations

import html
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.crypto import stable_payload_hash
from apps.api.app.models.entities import (
    AccountNode,
    DiscoveryEdge,
    MaigretSiteCheck,
    OutboxMessage,
    ProviderRun,
    SearchJob,
    new_id,
)
from apps.api.app.policy.redaction import safe_text
from apps.api.app.services.anchor_selection import (
    MIN_ANCHOR_SELECTION_SECONDS,
    MIN_PROFESSIONAL_SEARCH_SECONDS,
    selected_anchor,
)
from apps.api.app.services.events import add_event
from apps.api.app.services.footprint_finalization import (
    _allowlisted_public_profile_fields,
    _extract_self_described_location,
    _is_exact_first_party_profile,
    _platform_key,
)

MAIGRET_PROVIDER_ID = "maigret_discovery_v1"
EXA_PEOPLE_PROVIDER_ID = "exa_people_search_v1"
GITHUB_PROFESSIONAL_PROVIDER_ID = "github_professional_search_v1"
PROFESSIONAL_PROVIDER_IDS = {
    EXA_PEOPLE_PROVIDER_ID,
    GITHUB_PROFESSIONAL_PROVIDER_ID,
}
PROFESSIONAL_TERMINAL_STATES = {
    "success",
    "partial_success",
    "no_result",
    "timeout",
    "rate_limited",
    "auth_required",
    "provider_error",
    "invalid_response",
    "cancelled",
    "closed_at_cutoff",
    "skipped_configuration",
}
_MAIGRET_TERMINAL_STATES = {
    "success",
    "partial_success",
    "no_result",
    "timeout",
    "rate_limited",
    "captcha_blocked",
    "auth_required",
    "provider_error",
    "cancelled",
    "closed_at_cutoff",
    "skipped_configuration",
}
_NAME_TOKEN = re.compile(r"[^\W\d_]+(?:['’.-][^\W\d_]+)*", flags=re.UNICODE)
_GITHUB_LOGIN = re.compile(
    r"\A[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z",
    flags=re.ASCII,
)
_EMAIL_LIKE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_COMPANY_BIO_PATTERNS = (
    re.compile(
        r"\b(?:works?|working)\s+(?:at|@)\s+([^\n\r|,，;；•·]{2,80})",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:engineer|designer|developer|manager|researcher|scientist)"
        r"\s*@\s*([^\n\r|,，;；•·]{2,80})",
        flags=re.IGNORECASE,
    ),
)
_EDUCATION_BIO_PATTERNS = (
    re.compile(
        r"\b(?:studied|studying|student|alumni|alumnus|alumna)"
        r"\s+(?:at|@|from)\s+([^\n\r|,，;；•·]{2,80})",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mcs|msc|ms|ma|meng|bs|ba|bsc|phd)\s*@\s*"
        r"([^\n\r|,，;；•·]{2,80})",
        flags=re.IGNORECASE,
    ),
)
_COMPANY_FIELDS = (
    "company",
    "current_company",
    "employer",
    "organization",
    "organisation",
    "workplace",
)
_EDUCATION_FIELDS = (
    "alma_mater",
    "college",
    "education",
    "institution",
    "school",
    "university",
)
_ADAPTIVE_MAX_NAMES = 6
_ADAPTIVE_MAX_QUERIES = 36
_ADAPTIVE_MAX_REQUESTS = 64
_ADAPTIVE_MAX_PROFILES = 50
_ADAPTIVE_MAX_BUDGET_SECONDS = 300
_ADAPTIVE_MAX_STAGNATION_QUERIES = 6
_ADAPTIVE_EXA_PROFILES_PER_REQUEST = 5
_ADAPTIVE_EXA_PROFILES_PER_RUN = 15
_ADAPTIVE_GITHUB_PROFILES_PER_RUN = 3
_QUICK_ADAPTIVE_MAX_NAMES = 2
_QUICK_ADAPTIVE_MAX_QUERIES = 6
_QUICK_ADAPTIVE_MAX_REQUESTS = 6
_QUICK_ADAPTIVE_MAX_PROFILES = 10
_QUICK_ADAPTIVE_MAX_BUDGET_SECONDS = 40
_QUICK_ADAPTIVE_MAX_STAGNATION_QUERIES = 2


@dataclass(frozen=True)
class ProfessionalNameHypothesis:
    full_name: str
    broad_location: str | None
    source_check_ids: tuple[str, ...]
    source_node_ids: tuple[str, ...]
    provenance_families: tuple[str, ...]
    name_source_node_ids: tuple[str, ...] = ()
    company_anchors: tuple[str, ...] = ()
    education_anchors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdaptiveProfessionalRunPlan:
    hypothesis_index: int
    provider_id: str
    queries: tuple[str, ...]
    candidate_logins: tuple[str, ...]
    request_budget: int
    result_budget: int


@dataclass(frozen=True)
class AdaptiveProfessionalSearchPolicy:
    maximum_names: int
    max_queries: int
    max_requests: int
    max_profiles: int
    budget_seconds: int
    stagnation_queries: int
    github_allowed: bool


@dataclass
class _AdaptivePlanState:
    hypothesis_index: int
    provider_id: str
    queries: tuple[str, ...]
    candidate_logins: tuple[str, ...]
    query_budget: int = 0
    request_budget: int = 0
    result_budget: int = 0


def schedule_professional_search_if_ready(
    session: Session,
    *,
    job: SearchJob,
    now,
    settings: object | None,
) -> bool:
    """Schedule one adaptive professional-search wave after root discovery.

    The function is deliberately idempotent: the first professional ProviderRun
    prevents a second wave from being created by concurrent completion paths.
    """

    if not bool(getattr(settings, "professional_search_enabled", False)):
        return False
    if job.job_kind != "footprint_discovery" or _deadline_reached(job.deadline_at, now):
        return False

    session.flush()
    runs = session.scalars(
        select(ProviderRun)
        .where(ProviderRun.job_id == job.id)
        .order_by(ProviderRun.logical_run_id)
        .with_for_update()
    ).all()
    if any(run.provider_id in PROFESSIONAL_PROVIDER_IDS for run in runs):
        return False
    maigret_runs = [run for run in runs if run.provider_id == MAIGRET_PROVIDER_ID]
    if not maigret_runs or any(run.status not in _MAIGRET_TERMINAL_STATES for run in maigret_runs):
        return False

    policy = effective_adaptive_professional_search_policy(
        settings=settings,
        search_mode=job.search_mode,
    )
    maximum_names = policy.maximum_names
    hypotheses = derive_professional_name_hypotheses(
        session,
        job=job,
        maximum_names=max(2, maximum_names),
        include_context_anchors=True,
    )
    if not hypotheses:
        return False

    exa_enabled = bool(getattr(settings, "exa_people_search_enabled", True))
    github_enabled = (
        policy.github_allowed
        and bool(getattr(settings, "github_people_search_enabled", True))
        and bool(getattr(settings, "github_provider_enabled", True))
    )
    adaptive_exa_available = exa_enabled and _secret_present(getattr(settings, "exa_api_key", None))
    anchor = selected_anchor(session, job=job)
    if (
        job.seed_kind == "bare_handle"
        and len(hypotheses) > 1
        and anchor is None
        and (adaptive_exa_available or github_enabled)
        and _seconds_until(job.deadline_at, now)
        >= MIN_ANCHOR_SELECTION_SECONDS + MIN_PROFESSIONAL_SEARCH_SECONDS
    ):
        if job.exploration_status != "awaiting_anchor":
            job.exploration_status = "awaiting_anchor"
            job.row_version += 1
            add_event(
                session,
                job_id=job.id,
                event_type="discovery.anchor_required",
                message=(
                    "Multiple public name hypotheses were found. Select one "
                    "exact-handle account to guide the professional search."
                ),
                created_at=now,
            )
        return False
    hypotheses = hypotheses[:maximum_names]
    exa_limit = _bounded_int(
        getattr(settings, "professional_search_max_results_per_query", 5),
        default=5,
        minimum=1,
        maximum=5,
    )
    github_limit = _bounded_int(
        getattr(settings, "professional_search_max_github_profiles", 3),
        default=3,
        minimum=1,
        maximum=3,
    )
    budget_seconds = policy.budget_seconds
    wave_deadline = _earlier_datetime(
        job.deadline_at,
        now + timedelta(seconds=budget_seconds),
    )
    scheduled = 0
    adaptive_plans = build_adaptive_professional_query_plan(
        hypotheses,
        root_handle=job.seed_identifier or "",
        exa_enabled=adaptive_exa_available,
        github_enabled=github_enabled,
        max_queries=policy.max_queries,
        max_requests=policy.max_requests,
        max_profiles=policy.max_profiles,
    )
    adaptive_plans_by_hypothesis: dict[int, list[AdaptiveProfessionalRunPlan]] = defaultdict(list)
    for plan in adaptive_plans:
        adaptive_plans_by_hypothesis[plan.hypothesis_index].append(plan)

    for index, hypothesis in enumerate(hypotheses):
        common_config: dict[str, object] = {
            "full_name": hypothesis.full_name,
            "root_handle": job.seed_identifier or "",
            "broad_location": hypothesis.broad_location,
            "source_check_ids": list(hypothesis.source_check_ids),
            "source_node_ids": list(hypothesis.source_node_ids),
            "name_source_node_ids": list(hypothesis.name_source_node_ids),
            "provenance_families": list(hypothesis.provenance_families),
            "budget_seconds": budget_seconds,
        }
        parent_run_id = _parent_run_id(session, hypothesis.source_check_ids)
        suffix = stable_payload_hash(
            {
                "name": hypothesis.full_name.casefold(),
                "checks": hypothesis.source_check_ids,
            }
        )[:10]
        for plan in adaptive_plans_by_hypothesis[index]:
            query_config: dict[str, object] = {
                **common_config,
                "retrieval_mode": "adaptive",
                "queries": list(plan.queries),
                "query_budget": len(plan.queries),
                "request_budget": plan.request_budget,
                "result_budget": plan.result_budget,
                "time_budget_seconds": budget_seconds,
                "stagnation_query_limit": policy.stagnation_queries,
                "company_anchors": list(hypothesis.company_anchors),
                "education_anchors": list(hypothesis.education_anchors),
            }
            if plan.provider_id == EXA_PEOPLE_PROVIDER_ID:
                query_config.update(
                    {
                        "query": plan.queries[0],
                        "max_results": min(
                            exa_limit,
                            plan.result_budget,
                        ),
                    }
                )
            else:
                query_config.update(
                    {
                        "candidate_logins": list(plan.candidate_logins),
                        "max_profiles": min(
                            github_limit,
                            plan.result_budget,
                        ),
                    }
                )
            _add_professional_run(
                session,
                job=job,
                now=now,
                logical_run_id=(
                    f"professional:"
                    f"{'exa' if plan.provider_id == EXA_PEOPLE_PROVIDER_ID else 'github'}:"
                    f"{index:02d}:{suffix}"
                ),
                provider_id=plan.provider_id,
                parent_run_id=parent_run_id,
                deadline_at=wave_deadline,
                query_config=query_config,
            )
            scheduled += 1

    if not scheduled:
        return False
    job.exploration_status = "running"
    job.row_version += 1
    add_event(
        session,
        job_id=job.id,
        event_type="discovery.professional_search_started",
        message=(
            f"Started {scheduled} adaptive professional search "
            f"{'run' if scheduled == 1 else 'runs'} from {len(hypotheses)} public name "
            f"{'hypothesis' if len(hypotheses) == 1 else 'hypotheses'}."
        ),
        created_at=now,
    )
    return True


def effective_adaptive_professional_search_policy(
    *,
    settings: object | None,
    search_mode: str | None,
) -> AdaptiveProfessionalSearchPolicy:
    """Resolve the configured adaptive envelope against product-mode ceilings."""

    configured = AdaptiveProfessionalSearchPolicy(
        maximum_names=_bounded_int(
            getattr(settings, "adaptive_professional_search_max_names", 4),
            default=4,
            minimum=1,
            maximum=_ADAPTIVE_MAX_NAMES,
        ),
        max_queries=_bounded_int(
            getattr(settings, "adaptive_professional_search_max_queries", 20),
            default=20,
            minimum=1,
            maximum=_ADAPTIVE_MAX_QUERIES,
        ),
        max_requests=_bounded_int(
            getattr(settings, "adaptive_professional_search_max_requests", 32),
            default=32,
            minimum=1,
            maximum=_ADAPTIVE_MAX_REQUESTS,
        ),
        max_profiles=_bounded_int(
            getattr(settings, "adaptive_professional_search_max_profiles", 30),
            default=30,
            minimum=1,
            maximum=_ADAPTIVE_MAX_PROFILES,
        ),
        budget_seconds=_bounded_int(
            getattr(settings, "adaptive_professional_search_budget_seconds", 120),
            default=120,
            minimum=30,
            maximum=_ADAPTIVE_MAX_BUDGET_SECONDS,
        ),
        stagnation_queries=_bounded_int(
            getattr(settings, "adaptive_professional_search_stagnation_queries", 3),
            default=3,
            minimum=1,
            maximum=_ADAPTIVE_MAX_STAGNATION_QUERIES,
        ),
        github_allowed=True,
    )
    if str(search_mode or "quick").casefold() == "deep":
        return configured
    return AdaptiveProfessionalSearchPolicy(
        maximum_names=min(configured.maximum_names, _QUICK_ADAPTIVE_MAX_NAMES),
        max_queries=min(configured.max_queries, _QUICK_ADAPTIVE_MAX_QUERIES),
        max_requests=min(configured.max_requests, _QUICK_ADAPTIVE_MAX_REQUESTS),
        max_profiles=min(configured.max_profiles, _QUICK_ADAPTIVE_MAX_PROFILES),
        budget_seconds=min(
            configured.budget_seconds,
            _QUICK_ADAPTIVE_MAX_BUDGET_SECONDS,
        ),
        stagnation_queries=min(
            configured.stagnation_queries,
            _QUICK_ADAPTIVE_MAX_STAGNATION_QUERIES,
        ),
        github_allowed=False,
    )


def build_adaptive_professional_query_plan(
    hypotheses: tuple[ProfessionalNameHypothesis, ...],
    *,
    root_handle: str,
    exa_enabled: bool,
    github_enabled: bool,
    max_queries: int,
    max_requests: int,
    max_profiles: int,
) -> tuple[AdaptiveProfessionalRunPlan, ...]:
    """Allocate a deterministic aggregate budget across adaptive retrieval runs."""

    query_cap = _bounded_int(
        max_queries,
        default=20,
        minimum=1,
        maximum=_ADAPTIVE_MAX_QUERIES,
    )
    request_cap = _bounded_int(
        max_requests,
        default=32,
        minimum=1,
        maximum=_ADAPTIVE_MAX_REQUESTS,
    )
    profile_cap = _bounded_int(
        max_profiles,
        default=30,
        minimum=1,
        maximum=_ADAPTIVE_MAX_PROFILES,
    )
    proposals: list[_AdaptivePlanState] = []
    for index, hypothesis in enumerate(hypotheses[:_ADAPTIVE_MAX_NAMES]):
        if exa_enabled:
            queries = _adaptive_exa_queries(hypothesis, root_handle=root_handle)
            if queries:
                proposals.append(
                    _AdaptivePlanState(
                        hypothesis_index=index,
                        provider_id=EXA_PEOPLE_PROVIDER_ID,
                        queries=queries,
                        candidate_logins=(),
                    )
                )
        if github_enabled:
            candidates = _adaptive_github_candidates(
                root_handle=root_handle if index == 0 else "",
                full_name=hypothesis.full_name,
            )
            proposals.append(
                _AdaptivePlanState(
                    hypothesis_index=index,
                    provider_id=GITHUB_PROFESSIONAL_PROVIDER_ID,
                    queries=(hypothesis.full_name,),
                    candidate_logins=candidates,
                )
            )

    remaining_queries = query_cap
    remaining_requests = request_cap
    remaining_profiles = profile_cap
    active: list[_AdaptivePlanState] = []
    for proposal in proposals:
        minimum_requests = 1 if proposal.provider_id == EXA_PEOPLE_PROVIDER_ID else 2
        if remaining_queries < 1 or remaining_requests < minimum_requests or remaining_profiles < 1:
            continue
        proposal.query_budget = 1
        proposal.request_budget = minimum_requests
        proposal.result_budget = 1
        remaining_queries -= 1
        remaining_requests -= minimum_requests
        remaining_profiles -= 1
        active.append(proposal)

    while remaining_queries and remaining_requests:
        allocated = False
        for proposal in active:
            if proposal.provider_id != EXA_PEOPLE_PROVIDER_ID:
                continue
            if proposal.query_budget >= len(proposal.queries):
                continue
            proposal.query_budget += 1
            proposal.request_budget += 1
            remaining_queries -= 1
            remaining_requests -= 1
            allocated = True
            if not remaining_queries or not remaining_requests:
                break
        if not allocated:
            break

    while remaining_profiles:
        allocated = False
        for proposal in active:
            if proposal.provider_id == EXA_PEOPLE_PROVIDER_ID:
                maximum_for_run = min(
                    _ADAPTIVE_EXA_PROFILES_PER_RUN,
                    proposal.query_budget * _ADAPTIVE_EXA_PROFILES_PER_REQUEST,
                )
                additional_requests = 0
            else:
                maximum_for_run = _ADAPTIVE_GITHUB_PROFILES_PER_RUN
                additional_requests = 1
            if proposal.result_budget >= maximum_for_run:
                continue
            if additional_requests and remaining_requests < additional_requests:
                continue
            proposal.result_budget += 1
            proposal.request_budget += additional_requests
            remaining_profiles -= 1
            remaining_requests -= additional_requests
            allocated = True
            if not remaining_profiles:
                break
        if not allocated:
            break

    return tuple(
        AdaptiveProfessionalRunPlan(
            hypothesis_index=proposal.hypothesis_index,
            provider_id=proposal.provider_id,
            queries=proposal.queries[: proposal.query_budget],
            candidate_logins=proposal.candidate_logins,
            request_budget=proposal.request_budget,
            result_budget=proposal.result_budget,
        )
        for proposal in active
    )


def derive_professional_name_hypotheses(
    session: Session,
    *,
    job: SearchJob,
    maximum_names: int = 2,
    include_context_anchors: bool = False,
) -> tuple[ProfessionalNameHypothesis, ...]:
    anchor = selected_anchor(session, job=job)
    anchor_name = (
        _plausible_full_name(anchor.display_name)
        if anchor and isinstance(anchor.display_name, str)
        else None
    )
    anchor_name_key = _normalized_name_key(anchor_name) if anchor_name else None
    checks = session.scalars(
        select(MaigretSiteCheck)
        .where(MaigretSiteCheck.job_id == job.id)
        .order_by(MaigretSiteCheck.observed_at, MaigretSiteCheck.id)
    ).all()
    edge_rows = session.execute(
        select(DiscoveryEdge.site_check_id, AccountNode.id)
        .join(AccountNode, AccountNode.id == DiscoveryEdge.child_account_node_id)
        .where(
            DiscoveryEdge.job_id == job.id,
            DiscoveryEdge.site_check_id.is_not(None),
        )
    ).all()
    node_id_by_check_id = {
        str(check_id): str(node_id) for check_id, node_id in edge_rows if check_id
    }

    by_name: dict[str, list[tuple[MaigretSiteCheck, str, str | None]]] = defaultdict(list)
    all_profile_context: list[tuple[MaigretSiteCheck, str | None]] = []
    company_anchors_by_check: dict[str, tuple[str, ...]] = {}
    education_anchors_by_check: dict[str, tuple[str, ...]] = {}
    display_by_key: dict[str, str] = {}
    for check in checks:
        if not _is_exact_first_party_profile(check):
            continue
        fields = _allowlisted_public_profile_fields(check)
        value = fields.get("display_name")
        if not isinstance(value, str):
            continue
        full_name = _plausible_full_name(value)
        if not full_name:
            continue
        key = _normalized_name_key(full_name)
        display_by_key.setdefault(key, full_name)
        location = _broad_location(check, fields)
        all_profile_context.append((check, location))
        company_anchors, education_anchors = (
            _profile_context_anchors(check) if include_context_anchors else ((), ())
        )
        company_anchors_by_check[check.id] = company_anchors
        education_anchors_by_check[check.id] = education_anchors
        by_name[key].append(
            (
                check,
                _provenance_family(check.site_name),
                location,
            )
        )

    ranked: list[tuple[tuple[object, ...], ProfessionalNameHypothesis]] = []
    for key, observations in by_name.items():
        families = tuple(sorted({family for _, family, _ in observations}))
        name_check_ids = {check.id for check, _, _ in observations}
        node_ids = tuple(
            sorted(
                node_id_by_check_id[check_id]
                for check_id in name_check_ids
                if check_id in node_id_by_check_id
            )
        )
        locations = [location for _, _, location in observations if location is not None]
        company_anchors = _dedupe_casefolded(
            tuple(
                anchor
                for check, _, _ in observations
                for anchor in company_anchors_by_check.get(check.id, ())
            )
        )[:3]
        education_anchors = _dedupe_casefolded(
            tuple(
                anchor
                for check, _, _ in observations
                for anchor in education_anchors_by_check.get(check.id, ())
            )
        )[:3]
        location = _most_common_text(locations)
        context_check_ids: set[str] = set()
        if location is None:
            location = _most_common_text(
                [
                    candidate_location
                    for _, candidate_location in all_profile_context
                    if candidate_location is not None
                ]
            )
            if location:
                context_check_ids = {
                    check.id
                    for check, candidate_location in all_profile_context
                    if candidate_location
                    and _normalized_context(candidate_location) == _normalized_context(location)
                }
        if include_context_anchors and not company_anchors:
            company_anchors = _dedupe_casefolded(
                tuple(
                    anchor
                    for check, _ in all_profile_context
                    for anchor in company_anchors_by_check.get(check.id, ())
                )
            )[:3]
            context_check_ids.update(
                check.id
                for check, _ in all_profile_context
                if company_anchors_by_check.get(check.id)
            )
        if include_context_anchors and not education_anchors:
            education_anchors = _dedupe_casefolded(
                tuple(
                    anchor
                    for check, _ in all_profile_context
                    for anchor in education_anchors_by_check.get(check.id, ())
                )
            )[:3]
            context_check_ids.update(
                check.id
                for check, _ in all_profile_context
                if education_anchors_by_check.get(check.id)
            )
        check_ids = tuple(sorted(name_check_ids | context_check_ids))
        node_ids = tuple(
            sorted(
                set(node_ids)
                | {
                    node_id_by_check_id[check_id]
                    for check_id in context_check_ids
                    if check_id in node_id_by_check_id
                }
            )
        )
        seed_family = _provenance_family(job.seed_platform or "")
        has_seed = seed_family in families if job.seed_platform else False
        has_selected_anchor = bool(anchor_name_key and key == anchor_name_key)
        hypothesis = ProfessionalNameHypothesis(
            full_name=display_by_key[key],
            broad_location=location,
            source_check_ids=check_ids,
            source_node_ids=node_ids,
            provenance_families=families,
            name_source_node_ids=tuple(
                sorted(
                    node_id_by_check_id[check_id]
                    for check_id in name_check_ids
                    if check_id in node_id_by_check_id
                )
            ),
            company_anchors=company_anchors,
            education_anchors=education_anchors,
        )
        ranked.append(
            (
                (
                    -int(has_selected_anchor),
                    -len(families),
                    -int(has_seed),
                    observations[0][0].observed_at,
                    key,
                ),
                hypothesis,
            )
        )
    ranked.sort(key=lambda item: item[0])
    return tuple(
        item[1]
        for item in ranked[
            : _bounded_int(
                maximum_names,
                default=2,
                minimum=1,
                maximum=_ADAPTIVE_MAX_NAMES,
            )
        ]
    )


def _add_professional_run(
    session: Session,
    *,
    job: SearchJob,
    now,
    logical_run_id: str,
    provider_id: str,
    parent_run_id: str | None,
    deadline_at,
    query_config: dict[str, object],
) -> None:
    run = ProviderRun(
        id=new_id(),
        job_id=job.id,
        attempt_id=job.active_attempt_id,
        logical_run_id=logical_run_id,
        provider_id=provider_id,
        parent_run_id=parent_run_id,
        depth=1,
        query_config=query_config,
        status="pending",
        required_for_finalization=True,
        lease_generation=0,
        lease_expires_at=None,
        acceptance_epoch=job.acceptance_epoch,
        result_count=0,
        deadline_at=deadline_at,
        expires_at=job.expires_at,
    )
    session.add(run)
    session.flush()
    session.add(
        OutboxMessage(
            id=new_id(),
            topic="professional_search_run",
            dedupe_key=f"professional-search:{run.id}:generation:1",
            payload={"provider_run_id": run.id},
            created_at=now,
            dispatched_at=None,
            attempts=0,
        )
    )


def _parent_run_id(session: Session, check_ids: tuple[str, ...]) -> str | None:
    if not check_ids:
        return None
    return session.scalar(
        select(MaigretSiteCheck.provider_run_id)
        .where(MaigretSiteCheck.id.in_(check_ids))
        .order_by(MaigretSiteCheck.provider_run_id)
        .limit(1)
    )


def _adaptive_exa_queries(
    hypothesis: ProfessionalNameHypothesis,
    *,
    root_handle: str,
) -> tuple[str, ...]:
    name = hypothesis.full_name
    handle = _plain_search_text(root_handle.strip().removeprefix("@"), maximum=80)
    # Preserve the broad-name query before trying narrower anchors. This
    # guarantees adaptive stagnation cannot suppress the baseline recall path.
    candidates: list[str] = []
    if hypothesis.broad_location:
        candidates.append(f"{name} {hypothesis.broad_location}")
    candidates.append(name)
    if handle:
        candidates.append(f"{name} {handle}")
    candidates.extend(f"{name} {anchor}" for anchor in hypothesis.company_anchors[:3])
    candidates.extend(f"{name} {anchor}" for anchor in hypothesis.education_anchors[:3])
    return _dedupe_casefolded(
        tuple(
            query
            for candidate in candidates
            if (query := _plain_search_text(candidate, maximum=500))
        )
    )


def _adaptive_github_candidates(
    *,
    root_handle: str,
    full_name: str,
) -> tuple[str, ...]:
    candidates: list[str] = []
    normalized_handle = root_handle.strip().removeprefix("@")
    if _GITHUB_LOGIN.fullmatch(normalized_handle):
        candidates.append(normalized_handle.casefold())
    derived = _derived_github_login(full_name)
    if derived:
        candidates.append(derived)
    return tuple(dict.fromkeys(candidates))[:3]


def _profile_context_anchors(
    check: MaigretSiteCheck,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    normalized = {
        str(key).strip().casefold().replace("-", "_").replace(" ", "_"): value
        for key, value in check.extracted_data.items()
    }
    companies = _anchors_from_fields(normalized, _COMPANY_FIELDS)
    education = _anchors_from_fields(normalized, _EDUCATION_FIELDS)
    public_fields = _allowlisted_public_profile_fields(check)
    bio = public_fields.get("bio")
    if isinstance(bio, str):
        companies = (
            *companies,
            *(
                anchor
                for pattern in _COMPANY_BIO_PATTERNS
                if (match := pattern.search(bio))
                if (anchor := _anchor_text(match.group(1)))
            ),
        )
        education = (
            *education,
            *(
                anchor
                for pattern in _EDUCATION_BIO_PATTERNS
                if (match := pattern.search(bio))
                if (anchor := _anchor_text(match.group(1)))
            ),
        )
    return _dedupe_casefolded(companies)[:3], _dedupe_casefolded(education)[:3]


def _anchors_from_fields(
    values: dict[str, object],
    keys: tuple[str, ...],
) -> tuple[str, ...]:
    anchors: list[str] = []
    for key in keys:
        value = values.get(key)
        for candidate in _nested_anchor_values(value):
            anchor = _anchor_text(candidate)
            if anchor:
                anchors.append(anchor)
    return _dedupe_casefolded(tuple(anchors))


def _nested_anchor_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(
            candidate
            for key in ("name", "title", "label", "institution", "company")
            if isinstance((candidate := value.get(key)), str)
        )
    if isinstance(value, list):
        return tuple(candidate for item in value[:5] for candidate in _nested_anchor_values(item))
    return ()


def _anchor_text(value: str) -> str | None:
    candidate = _plain_search_text(value, maximum=80)
    if not candidate:
        return None
    candidate = candidate.strip(" \t\r\n,，.!。:：·•-–—")
    if not 2 <= len(candidate) <= 80 or "://" in candidate or _EMAIL_LIKE.search(candidate):
        return None
    return candidate


def _plain_search_text(value: str, *, maximum: int) -> str:
    candidate = unicodedata.normalize("NFKC", value)
    # Evidence may already have crossed an output-sanitization boundary. Decode
    # a small, fixed number of entity layers before constructing a JSON query.
    for _ in range(3):
        decoded = html.unescape(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    return " ".join(candidate.split())[:maximum]


def _dedupe_casefolded(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = unicodedata.normalize("NFKC", value).casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return tuple(deduped)


def _plausible_full_name(value: str) -> str | None:
    normalized = _plain_search_text(value, maximum=80)
    if (
        not normalized
        or any(character.isdigit() for character in normalized)
        or "@" in normalized
        or "://" in normalized
    ):
        return None
    tokens = _NAME_TOKEN.findall(normalized)
    if (
        len(tokens) == 1
        and tokens[0] == normalized
        and 2 <= len(normalized) <= 8
        and all(character.isalpha() for character in normalized)
        and any(not character.isascii() for character in normalized)
    ):
        return normalized
    if not 2 <= len(tokens) <= 4:
        return None
    joined = re.sub(r"[\s'’.-]+", "", "".join(tokens)).casefold()
    comparable = re.sub(r"[\s'’.-]+", "", normalized).casefold()
    if joined != comparable:
        return None
    return " ".join(tokens)


def _secret_present(value: object) -> bool:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        value = getter()
    return bool(isinstance(value, str) and value.strip())


def _normalized_name_key(value: str) -> str:
    return " ".join(
        "".join(
            character
            for character in unicodedata.normalize("NFKD", token.casefold())
            if not unicodedata.combining(character)
        )
        for token in value.split()
    )


def _broad_location(
    check: MaigretSiteCheck,
    fields: dict[str, object],
) -> str | None:
    direct = fields.get("location")
    if isinstance(direct, str):
        value = safe_text(direct, max_length=80)
        if value and not any(character.isdigit() for character in value):
            return value
    return _extract_self_described_location(check.extracted_data)


def _most_common_text(values: list[str]) -> str | None:
    if not values:
        return None
    counts: dict[str, tuple[int, str]] = {}
    for value in values:
        key = unicodedata.normalize("NFKC", value).casefold()
        count, display = counts.get(key, (0, value))
        counts[key] = (count + 1, display)
    return sorted(
        counts.values(),
        key=lambda item: (-item[0], item[1].casefold()),
    )[0][1]


def _normalized_context(value: str) -> str:
    return " ".join(_NAME_TOKEN.findall(unicodedata.normalize("NFKC", value).casefold()))


def _provenance_family(platform: str) -> str:
    key = _platform_key(platform)
    if key in {"instagram", "threads"}:
        return "meta"
    return key or "unknown"


def _derived_github_login(full_name: str) -> str | None:
    value = "".join(
        character
        for character in unicodedata.normalize("NFKD", full_name)
        if character.isascii() and character.isalnum()
    ).lower()
    return value if 1 <= len(value) <= 39 else None


def _deadline_reached(deadline, now) -> bool:
    if deadline.tzinfo is None and now.tzinfo is not None:
        deadline = deadline.replace(tzinfo=now.tzinfo)
    if now.tzinfo is None and deadline.tzinfo is not None:
        now = now.replace(tzinfo=deadline.tzinfo)
    return deadline <= now


def _seconds_until(deadline, now) -> float:
    if deadline.tzinfo is None and now.tzinfo is not None:
        deadline = deadline.replace(tzinfo=now.tzinfo)
    if now.tzinfo is None and deadline.tzinfo is not None:
        now = now.replace(tzinfo=deadline.tzinfo)
    return (deadline - now).total_seconds()


def _earlier_datetime(left, right):
    comparison_left = left
    comparison_right = right
    if comparison_left.tzinfo is None and comparison_right.tzinfo is not None:
        comparison_left = comparison_left.replace(tzinfo=comparison_right.tzinfo)
    if comparison_right.tzinfo is None and comparison_left.tzinfo is not None:
        comparison_right = comparison_right.replace(tzinfo=comparison_left.tzinfo)
    return left if comparison_left <= comparison_right else right


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))
