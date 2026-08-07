from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from workers.providers.maigret_adapter import (
    MaigretExtractedField,
    MaigretScanResult,
    MaigretSiteCheck,
)

_HANDLE_PATTERN = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z", re.ASCII)
_NEXT_DATA_PATTERN = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_META_PATTERN = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?P<name>[^"\']+)["\'][^>]+'
    r'content=["\'](?P<content>[^"\']*)["\'][^>]*>',
    re.IGNORECASE,
)
_META_REVERSED_PATTERN = re.compile(
    r'<meta[^>]+content=["\'](?P<content>[^"\']*)["\'][^>]+'
    r'(?:property|name)=["\'](?P<name>[^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)
_THREADS_TITLE_PATTERN = re.compile(
    r"\A(?P<name>.*?)\s*\(@(?P<handle>[^)]+)\)\s*[•·-]\s*Threads\b",
    re.IGNORECASE,
)
_COUNT_PATTERN = re.compile(
    r"(?P<followers>[\d.,]+(?:[KMB])?)\s+Followers?\s*[•·]\s*"
    r"(?P<posts>[\d.,]+(?:[KMB])?)\s+Threads?\b",
    re.IGNORECASE,
)
_MAX_BODY_BYTES = 1_000_000


@dataclass(frozen=True)
class PublicProfileMetadata:
    platform: str
    handle: str
    canonical_url: str
    display_name: str | None = None
    bio: str | None = None
    follower_count: str | None = None
    following_count: str | None = None
    posts_count: str | None = None

    def display_fields(self) -> dict[str, str]:
        fields = {"username": self.handle}
        optional = {
            "fullname": self.display_name,
            "bio": self.bio,
            "follower_count": self.follower_count,
            "following_count": self.following_count,
            "posts_count": self.posts_count,
        }
        fields.update({key: value for key, value in optional.items() if value})
        return fields


class PublicProfileMetadataError(ValueError):
    pass


FetchHtml = Callable[[str], str]


def parse_threads_profile(
    body: str,
    *,
    expected_handle: str,
) -> PublicProfileMetadata:
    normalized_handle = _normalize_handle(expected_handle)
    metadata = _html_metadata(body)
    title = metadata.get("og:title") or _title(body)
    match = _THREADS_TITLE_PATTERN.match(title or "")
    if not match or match.group("handle").casefold() != normalized_handle.casefold():
        raise PublicProfileMetadataError("Threads page did not expose the exact handle")
    display_name = _safe_text(match.group("name"), maximum=160)
    description = metadata.get("og:description") or metadata.get("description") or ""
    count_match = _COUNT_PATTERN.search(description)
    return PublicProfileMetadata(
        platform="Threads",
        handle=normalized_handle,
        canonical_url=f"https://www.threads.com/@{normalized_handle}",
        display_name=display_name,
        follower_count=count_match.group("followers") if count_match else None,
        posts_count=count_match.group("posts") if count_match else None,
    )


def parse_clubhouse_profile(
    body: str,
    *,
    expected_handle: str,
) -> PublicProfileMetadata:
    normalized_handle = _normalize_handle(expected_handle)
    match = _NEXT_DATA_PATTERN.search(body)
    if not match:
        raise PublicProfileMetadataError("Clubhouse page did not expose profile data")
    try:
        payload = json.loads(html.unescape(match.group(1)))
        page_props = payload["props"]["pageProps"]
        route_props = page_props["routeProps"]
        user = route_props["user"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise PublicProfileMetadataError("Clubhouse profile data was malformed") from exc
    if not isinstance(user, dict):
        raise PublicProfileMetadataError("Clubhouse profile data was malformed")
    username = user.get("username")
    if not isinstance(username, str) or username.casefold() != normalized_handle.casefold():
        raise PublicProfileMetadataError("Clubhouse page did not expose the exact handle")
    canonical_url = f"https://www.clubhouse.com/@{normalized_handle}"
    meta_props = page_props.get("metaProps")
    if isinstance(meta_props, dict):
        candidate_url = meta_props.get("og_canonical_url")
        if isinstance(candidate_url, str) and _is_exact_profile_url(
            candidate_url,
            hostname="www.clubhouse.com",
            expected_path=f"/@{normalized_handle}",
        ):
            canonical_url = candidate_url
    return PublicProfileMetadata(
        platform="Clubhouse",
        handle=normalized_handle,
        canonical_url=canonical_url,
        display_name=_safe_text(user.get("full_name"), maximum=160),
        bio=_safe_text(user.get("bio"), maximum=1_000, preserve_newlines=True),
        follower_count=_safe_count(route_props.get("num_followers")),
        following_count=_safe_count(route_props.get("num_following")),
    )


def enrich_first_party_metadata(
    result: MaigretScanResult,
    *,
    fetch_html: FetchHtml | None = None,
) -> MaigretScanResult:
    resolved_fetcher = fetch_html or _fetch_html
    checks: list[MaigretSiteCheck] = []
    changed = False
    for check in result.site_checks:
        parser = _parser_for(check)
        if parser is None or not check.url_user:
            checks.append(check)
            continue
        try:
            metadata = parser(
                resolved_fetcher(check.url_user),
                expected_handle=check.queried_identifier,
            )
        except (PublicProfileMetadataError, httpx.HTTPError, UnicodeDecodeError):
            checks.append(check)
            continue
        existing = {field.name for field in check.extracted_fields}
        additions = tuple(
            MaigretExtractedField(
                name=name,
                value=value,
                source_site_id=check.site_id,
            )
            for name, value in metadata.display_fields().items()
            if name not in existing
        )
        if not additions:
            checks.append(check)
            continue
        checks.append(
            replace(
                check,
                extracted_fields=check.extracted_fields + additions,
            )
        )
        changed = True
    if not changed:
        return result
    normalized_checks = tuple(checks)
    extracted_fields = _deduplicate_fields(
        field for check in normalized_checks for field in check.extracted_fields
    )
    return replace(
        result,
        site_checks=normalized_checks,
        extracted_fields=extracted_fields,
    )


def _parser_for(
    check: MaigretSiteCheck,
) -> Callable[..., PublicProfileMetadata] | None:
    if check.maigret_status != "CLAIMED" or check.product_status != "found":
        return None
    name = check.site_name.casefold()
    hostname = (urlsplit(check.url_user or "").hostname or "").casefold()
    if name == "threads" and hostname in {"threads.com", "www.threads.com", "threads.net"}:
        return parse_threads_profile
    if name == "clubhouse" and hostname in {"clubhouse.com", "www.clubhouse.com"}:
        return parse_clubhouse_profile
    return None


def _fetch_html(url: str) -> str:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or hostname
        not in {
            "threads.com",
            "www.threads.com",
            "threads.net",
            "www.threads.net",
            "clubhouse.com",
            "www.clubhouse.com",
        }
    ):
        raise PublicProfileMetadataError("Profile metadata host is not allowlisted")
    if hostname in {"threads.net", "www.threads.net"}:
        parsed = parsed._replace(netloc="www.threads.com")
        url = urlunsplit(parsed)
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity",
        "User-Agent": "public-profile-search-prototype/0.3",
    }
    with httpx.Client(
        timeout=httpx.Timeout(12.0),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        response = client.get(url, headers=headers)
    if response.status_code != 200:
        raise PublicProfileMetadataError("Profile metadata page was unavailable")
    media_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
    if media_type not in {"text/html", "application/xhtml+xml"}:
        raise PublicProfileMetadataError("Profile metadata response was not HTML")
    if len(response.content) > _MAX_BODY_BYTES:
        raise PublicProfileMetadataError("Profile metadata response was too large")
    return response.content.decode("utf-8")


def _html_metadata(body: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for pattern in (_META_PATTERN, _META_REVERSED_PATTERN):
        for match in pattern.finditer(body):
            name = match.group("name").casefold()
            if name not in values:
                values[name] = html.unescape(match.group("content")).strip()
    return values


def _title(body: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    return html.unescape(match.group(1)).strip() if match else None


def _normalize_handle(value: str) -> str:
    normalized = value.strip().removeprefix("@")
    if not _HANDLE_PATTERN.fullmatch(normalized):
        raise PublicProfileMetadataError("Profile handle is invalid")
    return normalized


def _safe_text(
    value: Any,
    *,
    maximum: int,
    preserve_newlines: bool = False,
) -> str | None:
    if not isinstance(value, str):
        return None
    if preserve_newlines:
        normalized = "\n".join(" ".join(line.split()) for line in value.splitlines()).strip()
    else:
        normalized = " ".join(value.split())
    return normalized[:maximum] or None


def _safe_count(value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[\d.,]+(?:[KMB])?", value, re.IGNORECASE):
        return value
    return None


def _is_exact_profile_url(
    value: str,
    *,
    hostname: str,
    expected_path: str,
) -> bool:
    parsed = urlsplit(value)
    return bool(
        parsed.scheme.casefold() == "https"
        and (parsed.hostname or "").casefold() == hostname
        and parsed.path.rstrip("/") == expected_path.rstrip("/")
        and not parsed.query
        and not parsed.fragment
    )


def _deduplicate_fields(
    fields: Any,
) -> tuple[MaigretExtractedField, ...]:
    unique: dict[tuple[str, str, str], MaigretExtractedField] = {}
    for field in fields:
        key = (field.source_site_id, field.name, repr(field.value))
        unique.setdefault(key, field)
    return tuple(unique.values())
