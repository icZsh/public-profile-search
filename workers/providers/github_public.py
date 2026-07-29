import re
import unicodedata
from dataclasses import dataclass

from apps.api.app.core.crypto import (
    UnsafePrototypeUrl,
    canonicalize_github_profile_url,
    keyed_hmac,
)
from apps.api.app.safe_fetch.service import SafeFetchError, SafeFetchGateway
from workers.providers.base import ProviderDocument, ProviderResult


@dataclass(frozen=True)
class GitHubPublicProfile:
    account_id: int
    login: str
    display_name: str
    canonical_url: str
    bio: str


@dataclass(frozen=True)
class GitHubProfileError(Exception):
    status: str
    error_code: str


def _safe_display_name(value: object, login: str) -> str:
    if not isinstance(value, str):
        return login
    candidate = " ".join(value.split())[:120]
    if not candidate:
        return login
    if any(unicodedata.category(character).startswith("C") for character in candidate):
        return login
    lowered = candidate.casefold()
    looks_like_contact = bool(
        re.search(r"\bhttps?://|\bwww\.|\b\S+@\S+\.\S+\b", lowered)
        or len(re.sub(r"\D", "", candidate)) >= 7
        or any(character in candidate for character in "<>")
    )
    return login if looks_like_contact else candidate


def _status_for_safe_fetch(error_code: str) -> str:
    if error_code == "network_timeout":
        return "timeout"
    if error_code in {
        "redirect_blocked",
        "invalid_content_type",
        "unsupported_content_encoding",
        "response_too_large",
        "invalid_content_length",
        "invalid_json",
        "invalid_response",
    }:
        return "invalid_response"
    return "provider_error"


def fetch_github_public_profile(
    gateway: SafeFetchGateway,
    canonical_profile_url: str,
) -> GitHubPublicProfile:
    try:
        target = canonicalize_github_profile_url(canonical_profile_url)
    except UnsafePrototypeUrl as exc:
        raise GitHubProfileError("invalid_response", "invalid_profile_url") from exc

    try:
        response = gateway.fetch_github_user(target.handle)
    except SafeFetchError as exc:
        raise GitHubProfileError(
            _status_for_safe_fetch(exc.code),
            f"safe_fetch_{exc.code}",
        ) from exc

    if response.status_code == 404:
        raise GitHubProfileError("no_result", "github_profile_not_found")
    if response.status_code in {403, 429}:
        raise GitHubProfileError("rate_limited", "github_rate_limited")
    if response.status_code == 401:
        raise GitHubProfileError("auth_required", "github_auth_required")
    if response.status_code >= 500:
        raise GitHubProfileError("provider_error", "github_unavailable")
    if response.status_code != 200:
        raise GitHubProfileError("invalid_response", "github_unexpected_status")

    try:
        payload = response.json()
    except ValueError as exc:
        raise GitHubProfileError("invalid_response", "github_invalid_json") from exc
    if not isinstance(payload, dict):
        raise GitHubProfileError("invalid_response", "github_invalid_payload")

    login = payload.get("login")
    account_id = payload.get("id")
    html_url = payload.get("html_url")
    account_type = payload.get("type")
    if (
        not isinstance(login, str)
        or login.casefold() != target.handle
        or not isinstance(account_id, int)
        or isinstance(account_id, bool)
        or account_id <= 0
        or not isinstance(html_url, str)
        or account_type != "User"
    ):
        raise GitHubProfileError("invalid_response", "github_identity_mismatch")
    try:
        response_target = canonicalize_github_profile_url(html_url)
    except UnsafePrototypeUrl as exc:
        raise GitHubProfileError("invalid_response", "github_invalid_html_url") from exc
    if response_target.canonical_url != target.canonical_url:
        raise GitHubProfileError("invalid_response", "github_identity_mismatch")

    bio_value = payload.get("bio")
    bio = bio_value[:1_000] if isinstance(bio_value, str) else ""
    return GitHubPublicProfile(
        account_id=account_id,
        login=target.handle,
        display_name=_safe_display_name(payload.get("name"), target.handle),
        canonical_url=target.canonical_url,
        bio=bio,
    )


def run_github_provider(
    *,
    canonical_profile_url: str,
    gateway: SafeFetchGateway,
    hmac_key: str,
) -> ProviderResult:
    provider_id = "github_public_profile_v1"
    try:
        profile = fetch_github_public_profile(gateway, canonical_profile_url)
    except GitHubProfileError as exc:
        return ProviderResult(
            provider_id=provider_id,
            status=exc.status,
            documents=(),
            error_code=exc.error_code,
        )

    subject_identifier = f"github-account-v1:{profile.account_id}"
    lineage_hmac = keyed_hmac(subject_identifier, hmac_key)
    document = ProviderDocument(
        canonical_url=profile.canonical_url,
        publisher="GitHub",
        title=f"{profile.display_name} · GitHub public profile",
        lineage_key=f"github-account:{lineage_hmac[:24]}",
        source_type="verified_input_profile",
        trust_class="self_reported",
        excerpt=(
            f"GitHub identifies this submitted public profile as "
            f"{profile.display_name} ({profile.login})."
        ),
        span_locator={"kind": "allowlisted_fields", "fields": ["login", "name", "html_url"]},
        extracted_fields={
            "display_name": profile.display_name,
            "verified_profile_url": profile.canonical_url,
        },
    )
    return ProviderResult(
        provider_id=provider_id,
        status="success",
        documents=(document,),
        subject_identifier=subject_identifier,
    )
