from __future__ import annotations

import html
import unicodedata
from datetime import UTC, timedelta
from math import ceil
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.core.crypto import stable_payload_hash
from apps.api.app.models.entities import (
    AccountNode,
    DiscoveryEdge,
    JobAttempt,
    JobDeletionTombstone,
    ProviderAttempt,
    ProviderRun,
    ProviderRunSourceUse,
    SearchJob,
    SourceDocument,
    SourceObservation,
    new_id,
)
from apps.api.app.policy.redaction import safe_text
from apps.api.app.safe_fetch.service import SafeFetchGateway
from apps.api.app.services.events import add_event
from apps.api.app.services.professional_search_scheduling import (
    EXA_PEOPLE_PROVIDER_ID,
    GITHUB_PROFESSIONAL_PROVIDER_ID,
    PROFESSIONAL_PROVIDER_IDS,
)
from workers.providers.professional_search import (
    ProfessionalProfile,
    ProfessionalSearchResult,
    search_exa_people,
    search_exa_people_adaptive,
    search_github_people,
)

_JOB_TERMINAL_STATES = {
    "ready",
    "ready_partial",
    "no_candidates",
    "failed",
    "cancelled",
}
_RESULT_STATUSES = {
    "success",
    "partial_success",
    "no_result",
    "timeout",
    "rate_limited",
    "auth_required",
    "provider_error",
    "invalid_response",
    "skipped_configuration",
}
_ADAPTIVE_RETRIEVAL_MODES = {"adaptive", "deep"}


def process_professional_search_run(
    session_factory: sessionmaker[Session],
    *,
    settings,
    clock,
    provider_run_id: str,
    gateway: SafeFetchGateway | None = None,
) -> None:
    lease = _lease_run(
        session_factory,
        settings=settings,
        clock=clock,
        provider_run_id=provider_run_id,
    )
    if not lease:
        return
    generation, acceptance_epoch, job_id, provider_id, query_config = lease

    result = _execute_search(
        settings=settings,
        provider_id=provider_id,
        query_config=query_config,
        gateway=gateway or SafeFetchGateway(settings),
    )

    with session_factory() as session, session.begin():
        run = session.scalar(
            select(ProviderRun).where(ProviderRun.id == provider_run_id).with_for_update()
        )
        job = session.scalar(select(SearchJob).where(SearchJob.id == job_id).with_for_update())
        attempt = session.scalar(
            select(ProviderAttempt).where(
                ProviderAttempt.provider_run_id == provider_run_id,
                ProviderAttempt.generation == generation,
            )
        )
        stale = bool(
            not run
            or not job
            or session.get(JobDeletionTombstone, job_id)
            or run.status != "running"
            or run.lease_generation != generation
            or run.acceptance_epoch != acceptance_epoch
            or job.acceptance_epoch != acceptance_epoch
        )
        if stale:
            if attempt:
                attempt.finished_at = clock.now()
                attempt.status = "completed_after_fence"
                attempt.completion_disposition = "late_payload_discarded"
            return

        now = clock.now()
        if _deadline_reached(run.deadline_at, now):
            run.status = "closed_at_cutoff"
            run.result_count = 0
            run.lease_expires_at = None
            if attempt:
                attempt.finished_at = now
                attempt.status = "closed_at_cutoff"
                attempt.completion_disposition = "late_payload_discarded"
                attempt.error_code = "professional_deadline_exceeded"
            add_event(
                session,
                job_id=job.id,
                event_type="discovery.professional_search_progress",
                message=(
                    "An adaptive professional search completed after its cutoff; "
                    "the late payload was discarded."
                ),
                created_at=now,
            )
            from apps.api.app.services.maigret_runs import (
                finalize_discovery_if_complete,
            )

            finalize_discovery_if_complete(
                session,
                job=job,
                now=now,
                settings=settings,
            )
            return
        accepted_count = _persist_search_result(
            session,
            job=job,
            run=run,
            result=result,
            observed_at=now,
        )
        status = result.status if result.status in _RESULT_STATUSES else "provider_error"
        if result.profiles and accepted_count < len(result.profiles):
            status = "partial_success" if accepted_count else "invalid_response"
        run.status = status
        run.result_count = accepted_count
        run.lease_expires_at = None
        if attempt:
            attempt.finished_at = now
            attempt.status = status
            attempt.completion_disposition = (
                "partial_preserved" if status == "partial_success" else "in_budget"
            )
            attempt.error_code = result.error_code
        add_event(
            session,
            job_id=job.id,
            event_type="discovery.professional_search_progress",
            message=_completion_message(
                provider_id=provider_id,
                status=status,
                accepted_count=accepted_count,
            ),
            created_at=now,
        )
        from apps.api.app.services.maigret_runs import finalize_discovery_if_complete

        finalize_discovery_if_complete(
            session,
            job=job,
            now=now,
            settings=settings,
        )


def _lease_run(
    session_factory: sessionmaker[Session],
    *,
    settings,
    clock,
    provider_run_id: str,
) -> tuple[int, int, str, str, dict[str, object]] | None:
    with session_factory() as session, session.begin():
        run = session.scalar(
            select(ProviderRun).where(ProviderRun.id == provider_run_id).with_for_update()
        )
        if (
            not run
            or run.provider_id not in PROFESSIONAL_PROVIDER_IDS
            or run.status not in {"pending", "retry_scheduled"}
        ):
            return None
        job = session.scalar(select(SearchJob).where(SearchJob.id == run.job_id).with_for_update())
        if (
            not job
            or job.job_kind != "footprint_discovery"
            or job.status in _JOB_TERMINAL_STATES
            or session.get(JobDeletionTombstone, run.job_id)
        ):
            run.status = "cancelled"
            run.lease_expires_at = None
            return None
        now = clock.now()
        if _deadline_reached(run.deadline_at, now):
            run.status = "closed_at_cutoff"
            run.lease_expires_at = None
            from apps.api.app.services.maigret_runs import finalize_discovery_if_complete

            finalize_discovery_if_complete(
                session,
                job=job,
                now=now,
                settings=settings,
            )
            return None

        query_config = dict(run.query_config or {})
        run.status = "running"
        run.lease_generation += 1
        lease_seconds = _bounded_int(
            getattr(settings, "professional_search_run_lease_seconds", 60),
            default=60,
            minimum=15,
            maximum=180,
        )
        if query_config.get("retrieval_mode") in _ADAPTIVE_RETRIEVAL_MODES:
            planned_seconds = _bounded_float(
                query_config.get("time_budget_seconds"),
                default=120.0,
                minimum=0.1,
                maximum=300.0,
            )
            remaining_seconds = _remaining_seconds(run.deadline_at, now)
            query_config["time_budget_seconds"] = min(
                planned_seconds,
                remaining_seconds,
            )
            # Keep the fencing lease alive for the entire adaptive wave plus a
            # small persistence margin. Otherwise a long adaptive run can be
            # requeued while its first generation is still consuming the
            # aggregate request envelope.
            lease_seconds = max(
                lease_seconds,
                min(315, ceil(query_config["time_budget_seconds"]) + 15),
            )
        run.lease_expires_at = now + timedelta(seconds=lease_seconds)
        run.acceptance_epoch = job.acceptance_epoch
        session.add(
            ProviderAttempt(
                id=new_id(),
                provider_run_id=run.id,
                generation=run.lease_generation,
                started_at=now,
                finished_at=None,
                status="running",
                completion_disposition=None,
                error_code=None,
            )
        )
        active_attempt = session.get(JobAttempt, run.attempt_id)
        if active_attempt and active_attempt.status == "queued":
            active_attempt.status = "running"
        if job.status == "queued":
            job.status = "discovering"
            job.row_version += 1
        return (
            run.lease_generation,
            job.acceptance_epoch,
            job.id,
            run.provider_id,
            query_config,
        )


def _execute_search(
    *,
    settings,
    provider_id: str,
    query_config: dict[str, object],
    gateway: SafeFetchGateway,
) -> ProfessionalSearchResult:
    if not bool(getattr(settings, "professional_search_enabled", False)):
        return ProfessionalSearchResult(
            provider_id=provider_id,
            status="skipped_configuration",
            profiles=(),
            error_code="professional_search_disabled",
        )
    full_name = _query_text(query_config.get("full_name"), maximum=160)
    if not full_name:
        return ProfessionalSearchResult(
            provider_id=provider_id,
            status="invalid_response",
            profiles=(),
            error_code="professional_full_name_invalid",
        )
    adaptive_mode = query_config.get("retrieval_mode") in _ADAPTIVE_RETRIEVAL_MODES
    try:
        if provider_id == EXA_PEOPLE_PROVIDER_ID:
            if not bool(getattr(settings, "exa_people_search_enabled", False)):
                return ProfessionalSearchResult(
                    provider_id=provider_id,
                    status="skipped_configuration",
                    profiles=(),
                    error_code="exa_people_search_disabled",
                )
            if not _secret_present(getattr(settings, "exa_api_key", None)):
                return ProfessionalSearchResult(
                    provider_id=provider_id,
                    status="skipped_configuration",
                    profiles=(),
                    error_code="exa_api_key_missing",
                )
            if adaptive_mode:
                queries = tuple(
                    value
                    for value in (
                        _query_text(item, maximum=500)
                        for item in _bounded_list(query_config.get("queries"), 36)
                    )
                    if value
                )
                if not queries:
                    return ProfessionalSearchResult(
                        provider_id=provider_id,
                        status="invalid_response",
                        profiles=(),
                        error_code="professional_queries_invalid",
                    )
                return search_exa_people_adaptive(
                    queries=queries,
                    gateway=gateway,
                    request_budget=_bounded_int(
                        query_config.get("request_budget"),
                        default=len(queries),
                        minimum=1,
                        maximum=64,
                    ),
                    profile_budget=_bounded_int(
                        query_config.get("result_budget"),
                        default=5,
                        minimum=1,
                        maximum=50,
                    ),
                    time_budget_seconds=_bounded_float(
                        query_config.get("time_budget_seconds"),
                        default=120.0,
                        minimum=0.1,
                        maximum=300.0,
                    ),
                    stagnation_query_limit=_bounded_int(
                        query_config.get("stagnation_query_limit"),
                        default=3,
                        minimum=1,
                        maximum=6,
                    ),
                    max_results_per_query=_bounded_int(
                        query_config.get("max_results"),
                        default=5,
                        minimum=1,
                        maximum=5,
                    ),
                )
            query = _query_text(query_config.get("query"), maximum=500) or full_name
            maximum = _bounded_int(
                query_config.get("max_results"),
                default=5,
                minimum=1,
                maximum=5,
            )
            return search_exa_people(
                query=query,
                gateway=gateway,
                max_results=maximum,
            )
        if provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID:
            if not bool(getattr(settings, "github_people_search_enabled", False)) or not bool(
                getattr(settings, "github_provider_enabled", True)
            ):
                return ProfessionalSearchResult(
                    provider_id=provider_id,
                    status="skipped_configuration",
                    profiles=(),
                    error_code="github_people_search_disabled",
                )
            maximum = _bounded_int(
                query_config.get("max_profiles"),
                default=3,
                minimum=1,
                maximum=3,
            )
            candidate_logins = tuple(
                value
                for value in (
                    _query_text(item, maximum=39)
                    for item in _bounded_list(
                        query_config.get("candidate_logins"),
                        3 if adaptive_mode else 1,
                    )
                )
                if value
            )
            if adaptive_mode:
                return search_github_people(
                    full_name=full_name,
                    gateway=gateway,
                    max_profiles=maximum,
                    candidate_logins=candidate_logins,
                    request_budget=_bounded_int(
                        query_config.get("request_budget"),
                        default=maximum + 1,
                        minimum=2,
                        maximum=4,
                    ),
                    time_budget_seconds=_bounded_float(
                        query_config.get("time_budget_seconds"),
                        default=120.0,
                        minimum=0.1,
                        maximum=300.0,
                    ),
                )
            return search_github_people(
                full_name=full_name,
                gateway=gateway,
                max_profiles=maximum,
                candidate_logins=candidate_logins,
            )
    except (TypeError, ValueError):
        return ProfessionalSearchResult(
            provider_id=provider_id,
            status="provider_error",
            profiles=(),
            error_code="professional_adapter_invalid",
        )
    except Exception:
        return ProfessionalSearchResult(
            provider_id=provider_id,
            status="provider_error",
            profiles=(),
            error_code="professional_unexpected_failure",
        )
    return ProfessionalSearchResult(
        provider_id=provider_id,
        status="provider_error",
        profiles=(),
        error_code="professional_provider_unknown",
    )


def _persist_search_result(
    session: Session,
    *,
    job: SearchJob,
    run: ProviderRun,
    result: ProfessionalSearchResult,
    observed_at,
) -> int:
    accepted = 0
    for profile in result.profiles:
        fields = _allowlisted_fields(profile)
        if not fields or not _profile_url_allowed(run.provider_id, profile.profile_url):
            continue
        content_hash = stable_payload_hash(fields)
        document = session.scalar(
            select(SourceDocument).where(
                SourceDocument.canonical_url == profile.profile_url,
                SourceDocument.content_hash == content_hash,
            )
        )
        if not document:
            document = SourceDocument(
                id=new_id(),
                canonical_url=profile.profile_url,
                publisher=(
                    "GitHub"
                    if run.provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID
                    else "LinkedIn profile indexed by Exa"
                ),
                title=safe_text(
                    profile.display_name or profile.handle or f"{profile.platform} public profile",
                    max_length=240,
                ),
                mime_type="application/json",
                content_hash=content_hash,
                lineage_key=(
                    f"github-profile:{profile.handle.casefold()}"
                    if run.provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID
                    else "linkedin-index:"
                    + stable_payload_hash(profile.profile_url.casefold())[:48]
                ),
                expires_at=job.expires_at,
            )
            session.add(document)
            session.flush()
        elif document.expires_at is None or document.expires_at < job.expires_at:
            document.expires_at = job.expires_at

        source_use = session.scalar(
            select(ProviderRunSourceUse).where(
                ProviderRunSourceUse.provider_run_id == run.id,
                ProviderRunSourceUse.document_id == document.id,
            )
        )
        if not source_use:
            source_use = ProviderRunSourceUse(
                id=new_id(),
                provider_run_id=run.id,
                document_id=document.id,
                disposition=(
                    "accepted"
                    if run.provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID
                    else "candidate_discovery"
                ),
                policy_version=job.policy_version,
            )
            session.add(source_use)
            session.flush()

        observation = session.scalar(
            select(SourceObservation).where(
                SourceObservation.job_id == job.id,
                SourceObservation.source_use_id == source_use.id,
            )
        )
        if not observation:
            source_type = (
                "first_party_profile_api"
                if run.provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID
                else "professional_profile_index"
            )
            observation = SourceObservation(
                id=new_id(),
                job_id=job.id,
                source_use_id=source_use.id,
                source_type=source_type,
                trust_class=(
                    "first_party_api"
                    if run.provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID
                    else "search_index"
                ),
                retrieved_at=observed_at,
                excerpt=safe_text(
                    (
                        f"GitHub's public API returned the profile @{profile.handle}."
                        if run.provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID
                        else f"Exa indexed this public LinkedIn profile for "
                        f"{profile.display_name or profile.handle}."
                    ),
                    max_length=1_000,
                ),
                span_locator={
                    "kind": "allowlisted_professional_profile_fields",
                    "fields": sorted(fields),
                },
                extracted_fields=fields,
                extraction_version="professional-search-v1",
                expires_at=job.expires_at,
            )
            session.add(observation)
            session.flush()

        node = session.scalar(
            select(AccountNode).where(
                AccountNode.job_id == job.id,
                AccountNode.canonical_url == profile.profile_url,
            )
        )
        if not node:
            node = AccountNode(
                id=new_id(),
                job_id=job.id,
                platform=profile.platform,
                canonical_handle=profile.handle,
                canonical_url=profile.profile_url,
                display_name=profile.display_name,
                identity_confidence_tier="possible",
                selection_state="undecided",
                is_similar=False,
                profile_data={
                    "source_provider": run.provider_id,
                    "fields": fields,
                    "professional_sources": {
                        run.provider_id: fields,
                    },
                },
                first_observed_at=observed_at,
                last_observed_at=observed_at,
            )
            session.add(node)
            session.flush()
            add_event(
                session,
                job_id=job.id,
                event_type="candidate.discovered",
                message=f"Found a possible professional profile on {profile.platform}.",
                created_at=observed_at,
            )
        else:
            node.last_observed_at = observed_at
            if not node.display_name and profile.display_name:
                node.display_name = profile.display_name
            profile_data = dict(node.profile_data) if isinstance(node.profile_data, dict) else {}
            professional_sources = profile_data.get("professional_sources")
            if not isinstance(professional_sources, dict):
                professional_sources = {}
            professional_sources[run.provider_id] = fields
            profile_data["professional_sources"] = professional_sources
            node.profile_data = profile_data

        existing_edge = session.scalar(
            select(DiscoveryEdge.id).where(
                DiscoveryEdge.provider_run_id == run.id,
                DiscoveryEdge.source_observation_id == observation.id,
                DiscoveryEdge.child_account_node_id == node.id,
            )
        )
        if not existing_edge:
            session.add(
                DiscoveryEdge(
                    id=new_id(),
                    job_id=job.id,
                    provider_run_id=run.id,
                    site_check_id=None,
                    source_observation_id=observation.id,
                    child_account_node_id=node.id,
                    parent_seed=job.normalized_seed or "",
                    discovery_method=(
                        "github_professional_search"
                        if run.provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID
                        else "professional_index_search"
                    ),
                    discovery_engine=(
                        "github" if run.provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID else "exa"
                    ),
                    depth=1,
                    created_at=observed_at,
                )
            )
        accepted += 1
    return accepted


def _allowlisted_fields(profile: ProfessionalProfile) -> dict[str, object]:
    fields: dict[str, object] = {
        "platform": safe_text(profile.platform, max_length=160),
        "profile_url": profile.profile_url,
        "handle": safe_text(profile.handle, max_length=160),
    }
    text_fields = {
        "display_name": (profile.display_name, 200),
        "headline": (profile.headline, 300),
        "location": (profile.location, 160),
        "bio": (profile.bio, 1_000),
        "company": (profile.company, 240),
        "website": (profile.website, 400),
        "social_handle": (profile.social_handle, 160),
    }
    for key, (value, maximum) in text_fields.items():
        if value:
            normalized = safe_text(value, max_length=maximum)
            if normalized:
                fields[key] = normalized
    work_history = [
        {
            key: normalized
            for key, value in {
                "title": role.title,
                "company": role.company,
                "location": role.location,
                "start_date": role.start_date,
                "end_date": role.end_date,
            }.items()
            if value and (normalized := safe_text(value, max_length=240))
        }
        for role in profile.work_history[:8]
    ]
    education_history = [
        {
            key: normalized
            for key, value in {
                "degree": education.degree,
                "institution": education.institution,
                "start_date": education.start_date,
                "end_date": education.end_date,
            }.items()
            if value and (normalized := safe_text(value, max_length=240))
        }
        for education in profile.education_history[:8]
    ]
    highlights = [
        normalized
        for value in profile.highlights[:5]
        if (normalized := safe_text(value, max_length=1_000))
    ]
    if work_history:
        fields["work_history"] = work_history
    if education_history:
        fields["education_history"] = education_history
    if highlights:
        fields["highlights"] = highlights
    if not fields["platform"] or not fields["handle"]:
        return {}
    return fields


def _profile_url_allowed(provider_id: str, value: str) -> bool:
    try:
        parsed = urlsplit(value)
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
    host = parsed.hostname.casefold().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]
    if provider_id == EXA_PEOPLE_PROVIDER_ID:
        return host == "linkedin.com" and len(parts) == 2 and parts[0].casefold() == "in"
    if provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID:
        return host == "github.com" and len(parts) == 1
    return False


def _completion_message(
    *,
    provider_id: str,
    status: str,
    accepted_count: int,
) -> str:
    provider = "GitHub" if provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID else "Exa"
    if status == "skipped_configuration":
        return f"{provider} professional search was skipped because it is not configured."
    if status == "no_result":
        return f"{provider} professional search returned no bounded profile results."
    if status in {"success", "partial_success"}:
        return (
            f"{provider} professional search kept {accepted_count} source-linked "
            f"profile {'result' if accepted_count == 1 else 'results'}."
        )
    return f"{provider} professional search ended as {status.replace('_', ' ')}."


def _query_text(value: object, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value)
    for _ in range(3):
        decoded = html.unescape(normalized)
        if decoded == normalized:
            break
        normalized = decoded
    normalized = " ".join(normalized.split())[:maximum]
    return normalized or None


def _bounded_list(value: object, maximum: int) -> list[object]:
    if not isinstance(value, list):
        return []
    return value[:maximum]


def _secret_present(value: object) -> bool:
    if value is None:
        return False
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        value = getter()
    return bool(str(value).strip())


def _deadline_reached(deadline, now) -> bool:
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return deadline <= now


def _remaining_seconds(deadline, now) -> float:
    if deadline.tzinfo is None and now.tzinfo is not None:
        deadline = deadline.replace(tzinfo=now.tzinfo)
    if now.tzinfo is None and deadline.tzinfo is not None:
        now = now.replace(tzinfo=deadline.tzinfo)
    return max(0.1, (deadline - now).total_seconds())


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _bounded_float(
    value: object,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))
