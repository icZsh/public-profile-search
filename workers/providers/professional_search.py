from __future__ import annotations

import hashlib
import ipaddress
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from urllib.parse import unquote, urlsplit

from apps.api.app.core.crypto import UnsafePrototypeUrl, canonicalize_github_profile_url
from apps.api.app.safe_fetch.service import (
    EXA_MAX_PEOPLE_RESULTS,
    GITHUB_MAX_USER_SEARCH_RESULTS,
    GITHUB_USERNAME_PATTERN,
    SafeFetchError,
    SafeFetchGateway,
    SafeFetchResponse,
)
from workers.providers.base import ProviderDocument, ProviderResult

EXA_PROVIDER_ID = "exa_people_search_v1"
GITHUB_PROVIDER_ID = "github_professional_search_v1"
LINKEDIN_HANDLE_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{1,99}\Z", re.ASCII)
SOCIAL_HANDLE_PATTERN = re.compile(r"\A[A-Za-z0-9_]{1,30}\Z", re.ASCII)
EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")
DEEP_MAX_QUERY_COUNT = 36
DEEP_MAX_REQUEST_COUNT = 64
DEEP_MAX_PROFILE_COUNT = 50
DEEP_MAX_TIME_BUDGET_SECONDS = 300.0
DEEP_MAX_STAGNATION_QUERIES = 6


@dataclass(frozen=True)
class ProfessionalRole:
    title: str | None
    company: str | None
    location: str | None
    start_date: str | None
    end_date: str | None


@dataclass(frozen=True)
class ProfessionalEducation:
    degree: str | None
    institution: str | None
    start_date: str | None
    end_date: str | None


@dataclass(frozen=True)
class ProfessionalProfile:
    provider_id: str
    platform: str
    profile_url: str
    handle: str
    display_name: str | None
    headline: str | None
    location: str | None
    bio: str | None
    company: str | None
    website: str | None
    social_handle: str | None
    work_history: tuple[ProfessionalRole, ...]
    education_history: tuple[ProfessionalEducation, ...]
    highlights: tuple[str, ...]


@dataclass(frozen=True)
class ProfessionalSearchResult:
    provider_id: str
    status: str
    profiles: tuple[ProfessionalProfile, ...]
    error_code: str | None = None


def search_exa_people(
    *,
    query: str,
    gateway: SafeFetchGateway,
    max_results: int = EXA_MAX_PEOPLE_RESULTS,
) -> ProfessionalSearchResult:
    if not _valid_limit(max_results, EXA_MAX_PEOPLE_RESULTS):
        return _failure(EXA_PROVIDER_ID, "invalid_response", "invalid_result_limit")
    try:
        response = gateway.search_exa_people(query, num_results=max_results)
    except SafeFetchError as exc:
        return _safe_fetch_failure(EXA_PROVIDER_ID, exc)

    failure = _response_failure(EXA_PROVIDER_ID, response)
    if failure is not None:
        return failure
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return _failure(EXA_PROVIDER_ID, "invalid_response", "exa_invalid_payload")

    profiles: list[ProfessionalProfile] = []
    seen_urls: set[str] = set()
    for item in payload["results"][:EXA_MAX_PEOPLE_RESULTS]:
        profile = _parse_exa_profile(item)
        if profile is None or profile.profile_url in seen_urls:
            continue
        seen_urls.add(profile.profile_url)
        profiles.append(profile)
        if len(profiles) >= max_results:
            break
    if not profiles:
        return _failure(EXA_PROVIDER_ID, "no_result", "exa_no_linkedin_people_results")
    return ProfessionalSearchResult(
        provider_id=EXA_PROVIDER_ID,
        status="success",
        profiles=tuple(profiles),
    )


def search_exa_people_adaptive(
    *,
    queries: tuple[str, ...],
    gateway: SafeFetchGateway,
    request_budget: int,
    profile_budget: int,
    time_budget_seconds: float,
    stagnation_query_limit: int = 3,
    max_results_per_query: int = EXA_MAX_PEOPLE_RESULTS,
    monotonic: Callable[[], float] = time.monotonic,
) -> ProfessionalSearchResult:
    """Run deterministic query variants until evidence saturates or a budget is spent."""

    if (
        not isinstance(queries, tuple)
        or not 1 <= len(queries) <= DEEP_MAX_QUERY_COUNT
        or any(_normalized_search_query(query) is None for query in queries)
        or not _valid_limit(request_budget, DEEP_MAX_REQUEST_COUNT)
        or not _valid_limit(profile_budget, DEEP_MAX_PROFILE_COUNT)
        or not _valid_limit(max_results_per_query, EXA_MAX_PEOPLE_RESULTS)
        or not _valid_limit(
            stagnation_query_limit,
            DEEP_MAX_STAGNATION_QUERIES,
        )
        or not _valid_duration(time_budget_seconds)
    ):
        return _failure(EXA_PROVIDER_ID, "invalid_response", "invalid_adaptive_budget")

    started_at = monotonic()
    profiles: list[ProfessionalProfile] = []
    seen_urls: set[str] = set()
    failures: list[ProfessionalSearchResult] = []
    stagnant_queries = 0
    timed_out = False
    for query in queries[:request_budget]:
        if monotonic() - started_at >= time_budget_seconds:
            timed_out = True
            break
        remaining = profile_budget - len(profiles)
        if remaining <= 0:
            break
        result = search_exa_people(
            query=query,
            gateway=gateway,
            max_results=max_results_per_query,
        )
        novel_count = 0
        if result.status == "success":
            for profile in result.profiles:
                if profile.profile_url in seen_urls:
                    continue
                seen_urls.add(profile.profile_url)
                profiles.append(profile)
                novel_count += 1
                if len(profiles) >= profile_budget:
                    break
        else:
            failures.append(result)
            if result.status not in {"no_result"}:
                break
        stagnant_queries = 0 if novel_count else stagnant_queries + 1
        if stagnant_queries >= stagnation_query_limit:
            break

    if timed_out:
        failures.append(
            _failure(
                EXA_PROVIDER_ID,
                "timeout",
                "professional_search_time_budget_exhausted",
            )
        )
    if profiles:
        serious_failure = next(
            (failure for failure in failures if failure.status != "no_result"),
            None,
        )
        return ProfessionalSearchResult(
            provider_id=EXA_PROVIDER_ID,
            status="partial_success" if serious_failure else "success",
            profiles=tuple(profiles),
            error_code=serious_failure.error_code if serious_failure else None,
        )
    if failures:
        return _highest_priority_failure(failures)
    return _failure(EXA_PROVIDER_ID, "no_result", "exa_no_linkedin_people_results")


def search_github_people(
    *,
    full_name: str,
    gateway: SafeFetchGateway,
    max_profiles: int = GITHUB_MAX_USER_SEARCH_RESULTS,
    candidate_logins: tuple[str, ...] = (),
    request_budget: int | None = None,
    time_budget_seconds: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> ProfessionalSearchResult:
    if not _valid_limit(max_profiles, GITHUB_MAX_USER_SEARCH_RESULTS):
        return _failure(GITHUB_PROVIDER_ID, "invalid_response", "invalid_profile_limit")
    if request_budget is not None and not (
        isinstance(request_budget, int)
        and not isinstance(request_budget, bool)
        and 2 <= request_budget <= GITHUB_MAX_USER_SEARCH_RESULTS + 1
    ):
        return _failure(GITHUB_PROVIDER_ID, "invalid_response", "invalid_request_budget")
    if time_budget_seconds is not None and not _valid_duration(time_budget_seconds):
        return _failure(GITHUB_PROVIDER_ID, "invalid_response", "invalid_time_budget")
    normalized_name = _normalized_full_name(full_name)
    if normalized_name is None:
        return _failure(GITHUB_PROVIDER_ID, "invalid_response", "invalid_full_name")
    direct_candidates = _validated_candidate_logins(candidate_logins)
    if direct_candidates is None:
        return _failure(GITHUB_PROVIDER_ID, "invalid_response", "invalid_candidate_logins")

    started_at = monotonic() if time_budget_seconds is not None else None
    search_failure: ProfessionalSearchResult | None = None
    search_logins: tuple[str, ...] = ()
    timed_out = bool(
        started_at is not None
        and time_budget_seconds is not None
        and monotonic() - started_at >= time_budget_seconds
    )
    if timed_out:
        return _failure(
            GITHUB_PROVIDER_ID,
            "timeout",
            "professional_search_time_budget_exhausted",
        )
    try:
        search_response = gateway.search_github_users(normalized_name, per_page=max_profiles)
    except SafeFetchError as exc:
        search_failure = _safe_fetch_failure(GITHUB_PROVIDER_ID, exc)
    else:
        search_failure = _response_failure(GITHUB_PROVIDER_ID, search_response)
        if search_failure is None:
            search_logins = _parse_github_search_logins(search_response)
            if search_logins is None:
                search_failure = _failure(
                    GITHUB_PROVIDER_ID,
                    "invalid_response",
                    "github_search_invalid_payload",
                )
                search_logins = ()

    concatenated_login = _normalized_name_login(normalized_name)
    ordered_logins = _dedupe(
        (
            *direct_candidates,
            *((concatenated_login,) if concatenated_login else ()),
            *search_logins,
        )
    )

    profiles: list[ProfessionalProfile] = []
    fetch_failures: list[ProfessionalSearchResult] = []
    maximum_fetches = (
        max_profiles if request_budget is None else min(max_profiles, request_budget - 1)
    )
    seen_urls: set[str] = set()
    for login in ordered_logins[:maximum_fetches]:
        if (
            started_at is not None
            and time_budget_seconds is not None
            and monotonic() - started_at >= time_budget_seconds
        ):
            timed_out = True
            break
        try:
            response = gateway.fetch_github_user(login)
        except SafeFetchError as exc:
            fetch_failures.append(_safe_fetch_failure(GITHUB_PROVIDER_ID, exc))
            continue
        failure = _response_failure(GITHUB_PROVIDER_ID, response, not_found_is_no_result=True)
        if failure is not None:
            fetch_failures.append(failure)
            continue
        profile = _parse_github_profile(response, expected_login=login)
        if profile is None:
            fetch_failures.append(
                _failure(
                    GITHUB_PROVIDER_ID,
                    "invalid_response",
                    "github_profile_invalid_payload",
                )
            )
            continue
        if profile.profile_url in seen_urls:
            continue
        seen_urls.add(profile.profile_url)
        profiles.append(profile)

    if timed_out:
        fetch_failures.append(
            _failure(
                GITHUB_PROVIDER_ID,
                "timeout",
                "professional_search_time_budget_exhausted",
            )
        )
    if profiles:
        serious_failures = [
            failure
            for failure in [
                *fetch_failures,
                *((search_failure,) if search_failure else ()),
            ]
            if failure.status != "no_result"
        ]
        serious_failure = _highest_priority_failure(serious_failures) if serious_failures else None
        return ProfessionalSearchResult(
            provider_id=GITHUB_PROVIDER_ID,
            status="partial_success" if serious_failure else "success",
            profiles=tuple(profiles),
            error_code=serious_failure.error_code if serious_failure else None,
        )
    failures = [*fetch_failures, *((search_failure,) if search_failure else ())]
    if failures:
        return _highest_priority_failure(failures)
    return _failure(GITHUB_PROVIDER_ID, "no_result", "github_people_not_found")


def to_provider_result(result: ProfessionalSearchResult) -> ProviderResult:
    status = "provider_error" if result.status == "invalid_response" else result.status
    if result.status != "success":
        return ProviderResult(
            provider_id=result.provider_id,
            status=status,
            documents=(),
            error_code=result.error_code,
        )
    documents = tuple(_profile_document(profile) for profile in result.profiles)
    return ProviderResult(
        provider_id=result.provider_id,
        status="success" if documents else "no_result",
        documents=documents,
        error_code=None if documents else "professional_profiles_empty",
    )


def _parse_exa_profile(value: object) -> ProfessionalProfile | None:
    if not isinstance(value, dict):
        return None
    target = _canonical_linkedin_profile(value.get("url"))
    if target is None:
        return None
    profile_url, handle = target
    properties = _person_properties(value.get("entities"))
    if properties is None:
        return None

    work_history = _parse_work_history(properties.get("workHistory"))
    education_history = _parse_education_history(properties.get("educationHistory"))
    company = next((role.company for role in work_history if role.company), None)
    return ProfessionalProfile(
        provider_id=EXA_PROVIDER_ID,
        platform="LinkedIn",
        profile_url=profile_url,
        handle=handle,
        display_name=_safe_text(properties.get("name"), 160),
        headline=_safe_text(value.get("title"), 240),
        location=_safe_text(properties.get("location"), 200),
        bio=None,
        company=company,
        website=None,
        social_handle=None,
        work_history=work_history,
        education_history=education_history,
        highlights=_safe_highlights(value.get("highlights")),
    )


def _person_properties(entities: object) -> dict[str, object] | None:
    if not isinstance(entities, list):
        return None
    for entity in entities[:5]:
        if not isinstance(entity, dict) or entity.get("type") != "person":
            continue
        properties = entity.get("properties")
        if isinstance(properties, dict):
            return properties
    return None


def _parse_work_history(value: object) -> tuple[ProfessionalRole, ...]:
    if not isinstance(value, list):
        return ()
    roles: list[ProfessionalRole] = []
    for item in value[:5]:
        if not isinstance(item, dict):
            continue
        company_value = item.get("company")
        dates = item.get("dates")
        roles.append(
            ProfessionalRole(
                title=_safe_text(item.get("title"), 200),
                company=(
                    _safe_text(company_value.get("name"), 200)
                    if isinstance(company_value, dict)
                    else None
                ),
                location=_safe_text(item.get("location"), 200),
                start_date=(_safe_text(dates.get("from"), 32) if isinstance(dates, dict) else None),
                end_date=_safe_text(dates.get("to"), 32) if isinstance(dates, dict) else None,
            )
        )
    return tuple(roles)


def _parse_education_history(value: object) -> tuple[ProfessionalEducation, ...]:
    if not isinstance(value, list):
        return ()
    education: list[ProfessionalEducation] = []
    for item in value[:5]:
        if not isinstance(item, dict):
            continue
        institution = item.get("institution")
        dates = item.get("dates")
        education.append(
            ProfessionalEducation(
                degree=_safe_text(item.get("degree"), 200),
                institution=(
                    _safe_text(institution.get("name"), 200)
                    if isinstance(institution, dict)
                    else None
                ),
                start_date=(_safe_text(dates.get("from"), 32) if isinstance(dates, dict) else None),
                end_date=_safe_text(dates.get("to"), 32) if isinstance(dates, dict) else None,
            )
        )
    return tuple(education)


def _parse_github_search_logins(response: SafeFetchResponse) -> tuple[str, ...] | None:
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return None
    logins: list[str] = []
    for item in payload["items"][:GITHUB_MAX_USER_SEARCH_RESULTS]:
        if not isinstance(item, dict) or item.get("type") != "User":
            continue
        login = item.get("login")
        if isinstance(login, str) and GITHUB_USERNAME_PATTERN.fullmatch(login):
            logins.append(login.lower())
    return _dedupe(tuple(logins))


def _parse_github_profile(
    response: SafeFetchResponse,
    *,
    expected_login: str,
) -> ProfessionalProfile | None:
    payload = response.json()
    if not isinstance(payload, dict):
        return None
    login = payload.get("login")
    html_url = payload.get("html_url")
    if (
        not isinstance(login, str)
        or login.casefold() != expected_login.casefold()
        or payload.get("type") != "User"
        or not isinstance(html_url, str)
    ):
        return None
    try:
        canonical_target = canonicalize_github_profile_url(html_url)
    except UnsafePrototypeUrl:
        return None
    if canonical_target.handle != expected_login.casefold():
        return None
    social_handle = _safe_text(payload.get("twitter_username"), 30)
    if social_handle is not None:
        social_handle = social_handle.removeprefix("@")
        if not SOCIAL_HANDLE_PATTERN.fullmatch(social_handle):
            social_handle = None
    return ProfessionalProfile(
        provider_id=GITHUB_PROVIDER_ID,
        platform="GitHub",
        profile_url=canonical_target.canonical_url,
        handle=canonical_target.handle,
        display_name=_safe_text(payload.get("name"), 160),
        headline=None,
        location=_safe_text(payload.get("location"), 200),
        bio=_redacted_text(payload.get("bio"), 1_000),
        company=_safe_text(payload.get("company"), 200),
        website=_safe_public_url(payload.get("blog")),
        social_handle=social_handle,
        work_history=(),
        education_history=(),
        highlights=(),
    )


def _canonical_linkedin_profile(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() not in {"linkedin.com", "www.linkedin.com"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    if len(segments) != 2 or segments[0].casefold() != "in":
        return None
    handle = segments[1]
    if not LINKEDIN_HANDLE_PATTERN.fullmatch(handle):
        return None
    normalized_handle = handle.lower()
    return f"https://www.linkedin.com/in/{normalized_handle}", normalized_handle


def _validated_candidate_logins(value: tuple[str, ...]) -> tuple[str, ...] | None:
    if not isinstance(value, tuple) or len(value) > GITHUB_MAX_USER_SEARCH_RESULTS:
        return None
    normalized: list[str] = []
    for login in value:
        if not isinstance(login, str) or not GITHUB_USERNAME_PATTERN.fullmatch(login):
            return None
        normalized.append(login.lower())
    return _dedupe(tuple(normalized))


def _normalized_name_login(full_name: str) -> str | None:
    if not isinstance(full_name, str):
        return None
    normalized = unicodedata.normalize("NFKD", full_name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    login = "".join(character for character in ascii_name if character.isalnum()).lower()
    return login if GITHUB_USERNAME_PATTERN.fullmatch(login) else None


def _normalized_full_name(full_name: object) -> str | None:
    if not isinstance(full_name, str):
        return None
    if any(
        unicodedata.category(character).startswith("C") and character not in "\t\r\n"
        for character in full_name
    ):
        return None
    normalized = " ".join(full_name.split())
    if not normalized or len(normalized) > 160 or '"' in normalized or "\\" in normalized:
        return None
    return normalized


def _normalized_search_query(query: object) -> str | None:
    if not isinstance(query, str):
        return None
    if any(
        unicodedata.category(character).startswith("C") and character not in "\t\r\n"
        for character in query
    ):
        return None
    normalized = " ".join(query.split())
    return normalized if normalized and len(normalized) <= 500 else None


def _safe_highlights(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    highlights: list[str] = []
    remaining = 1_000
    for item in value[:5]:
        text = _redacted_text(item, min(500, remaining))
        if not text:
            continue
        highlights.append(text)
        remaining -= len(text)
        if remaining <= 0:
            break
    return tuple(highlights)


def _safe_text(value: object, maximum_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    if any(
        unicodedata.category(character).startswith("C") and character not in "\t\r\n"
        for character in value
    ):
        return None
    candidate = " ".join(value.split())
    return candidate[:maximum_length] if candidate else None


def _redacted_text(value: object, maximum_length: int) -> str | None:
    candidate = _safe_text(value, maximum_length)
    if candidate is None:
        return None
    candidate = EMAIL_PATTERN.sub("[redacted contact]", candidate)
    candidate = PHONE_PATTERN.sub("[redacted contact]", candidate)
    return candidate[:maximum_length]


def _safe_public_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname.casefold() == "localhost" or "." not in parsed.hostname:
            return None
    else:
        if not address.is_global:
            return None
    return parsed.geturl()


def _response_failure(
    provider_id: str,
    response: SafeFetchResponse,
    *,
    not_found_is_no_result: bool = False,
) -> ProfessionalSearchResult | None:
    if response.status_code == 200:
        return None
    if response.status_code == 401:
        return _failure(provider_id, "auth_required", f"{provider_id}_auth_required")
    if response.status_code in {403, 429}:
        return _failure(provider_id, "rate_limited", f"{provider_id}_rate_limited")
    if response.status_code == 404 and not_found_is_no_result:
        return _failure(provider_id, "no_result", f"{provider_id}_not_found")
    if response.status_code >= 500:
        return _failure(provider_id, "provider_error", f"{provider_id}_unavailable")
    return _failure(provider_id, "invalid_response", f"{provider_id}_unexpected_status")


def _safe_fetch_failure(provider_id: str, error: SafeFetchError) -> ProfessionalSearchResult:
    if error.code == "network_timeout":
        status = "timeout"
    elif error.code in {"exa_auth_required", "safe_fetch_not_configured"}:
        status = "auth_required"
    elif error.code in {
        "redirect_blocked",
        "invalid_content_type",
        "unsupported_content_encoding",
        "response_too_large",
        "invalid_content_length",
        "invalid_json",
        "invalid_query",
        "invalid_full_name",
        "invalid_username",
        "invalid_result_limit",
    }:
        status = "invalid_response"
    else:
        status = "provider_error"
    return _failure(provider_id, status, f"safe_fetch_{error.code}")


def _highest_priority_failure(
    failures: list[ProfessionalSearchResult],
) -> ProfessionalSearchResult:
    priority = {
        "auth_required": 0,
        "rate_limited": 1,
        "timeout": 2,
        "provider_error": 3,
        "invalid_response": 4,
        "no_result": 5,
    }
    return min(failures, key=lambda item: priority.get(item.status, 99))


def _profile_document(profile: ProfessionalProfile) -> ProviderDocument:
    is_exa = profile.provider_id == EXA_PROVIDER_ID
    source_family = "exa_people" if is_exa else "github_api"
    target_platform = profile.platform.casefold()
    extracted_fields: dict[str, object] = {
        "source_family": source_family,
        "target_platform": target_platform,
        "handle": profile.handle,
    }
    optional_fields = {
        "display_name": profile.display_name,
        "headline": profile.headline,
        "location": profile.location,
        "bio": profile.bio,
        "company": profile.company,
        "website": profile.website,
        "social_handle": profile.social_handle,
    }
    extracted_fields.update(
        {field: value for field, value in optional_fields.items() if value is not None}
    )
    if profile.work_history:
        extracted_fields["work_history"] = [asdict(role) for role in profile.work_history]
    if profile.education_history:
        extracted_fields["education_history"] = [asdict(item) for item in profile.education_history]
    if profile.highlights:
        extracted_fields["highlights"] = list(profile.highlights)

    display = profile.display_name or profile.handle
    detail = next(
        (
            value
            for value in (
                profile.headline,
                profile.company,
                profile.location,
                profile.bio,
            )
            if value
        ),
        None,
    )
    excerpt = f"{display} ({profile.handle})"
    if detail:
        excerpt = f"{excerpt}: {detail}"
    fields = sorted(extracted_fields)
    lineage_hash = hashlib.sha256(profile.profile_url.encode("utf-8")).hexdigest()[:24]
    return ProviderDocument(
        canonical_url=profile.profile_url,
        publisher="Exa people index" if is_exa else "GitHub",
        title=f"{display} · {profile.platform} professional profile",
        lineage_key=f"professional-profile:{target_platform}:{lineage_hash}",
        source_type="professional_profile_index" if is_exa else "first_party_profile_api",
        trust_class="indexed_professional_profile" if is_exa else "first_party",
        excerpt=excerpt[:1_000],
        span_locator={"kind": "allowlisted_fields", "fields": fields},
        extracted_fields=extracted_fields,
    )


def _valid_limit(value: object, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= maximum


def _valid_duration(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 < float(value) <= DEEP_MAX_TIME_BUDGET_SECONDS
    )


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _failure(
    provider_id: str,
    status: str,
    error_code: str,
) -> ProfessionalSearchResult:
    return ProfessionalSearchResult(
        provider_id=provider_id,
        status=status,
        profiles=(),
        error_code=error_code,
    )
