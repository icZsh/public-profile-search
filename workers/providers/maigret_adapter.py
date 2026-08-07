"""Bounded adapter for Maigret's asynchronous Python search API.

The adapter intentionally receives both the search callable and the already selected
site catalog.  It does not load Maigret settings, update a catalog, or invoke the CLI.
This keeps catalog promotion and recursive discovery in the host application.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from urllib.parse import urlsplit

_MAX_IDENTIFIER_LENGTH = 512
_MAX_LINK_LENGTH = 2_048
_MAX_DETAIL_LENGTH = 1_000
_MAX_FIELD_NAME_LENGTH = 128
_MAX_FIELD_STRING_LENGTH = 2_000
_MAX_COLLECTION_ITEMS = 50
_MAX_DATABASE_RANK = 2_147_483_647
_MAX_PUBLIC_COUNT = 1_000_000_000_000

_COMMON_PUBLIC_FIELD_ALIASES = {
    "username": "username",
    "handle": "username",
    "displayname": "display_name",
    "fullname": "display_name",
    "name": "display_name",
    "bio": "bio",
    "biography": "bio",
    "description": "bio",
    "website": "website",
    "externalurl": "website",
    "location": "location",
    "verified": "is_verified",
    "isverified": "is_verified",
    "private": "is_private",
    "isprivate": "is_private",
    "followers": "follower_count",
    "followercount": "follower_count",
    "followerscount": "follower_count",
    "following": "following_count",
    "followingcount": "following_count",
    "posts": "post_count",
    "postcount": "post_count",
    "postscount": "post_count",
    "mediacount": "post_count",
}
_PROVIDER_PUBLIC_FIELD_ALIASES = {
    "instagram": {
        "edgefollowedby": "follower_count",
        "edgefollow": "following_count",
        "edgeownertotimelinemedia": "post_count",
    },
    "threads": {
        "category": "category",
        "categoryname": "category",
        "topic": "category",
        "topics": "category",
    },
    "clubhouse": {
        "numfollowers": "follower_count",
        "numfollowing": "following_count",
        "nummembers": "follower_count",
    },
}


class MaigretSearchFunction(Protocol):
    def __call__(self, **kwargs: object) -> Awaitable[Mapping[str, object] | None]: ...


@dataclass(frozen=True)
class MaigretScanConfig:
    """Host-owned limits plus deliberately non-overridable network behavior."""

    timeout_seconds: float = 10.0
    max_connections: int = 20
    max_sites: int = 50

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be greater than 0 and at most 30")
        if not 0 < self.max_connections <= 20:
            raise ValueError("max_connections must be between 1 and 20")
        if not 0 < self.max_sites <= 100:
            raise ValueError("max_sites must be between 1 and 100")


@dataclass(frozen=True)
class MaigretProgress:
    identifier: str
    maigret_id_type: str
    completed_sites: int
    selected_sites: int
    site_name: str | None = None
    maigret_status: str | None = None


@dataclass(frozen=True)
class MaigretExtractedIdentifier:
    value: str
    maigret_id_type: str
    source_site_id: str


@dataclass(frozen=True)
class MaigretExtractedLink:
    url: str
    source_site_id: str


@dataclass(frozen=True)
class MaigretExtractedField:
    name: str
    value: object
    source_site_id: str


@dataclass(frozen=True)
class MaigretAccountCandidate:
    site_id: str
    site_name: str
    url: str
    queried_identifier: str
    maigret_id_type: str
    relationship: str


@dataclass(frozen=True)
class MaigretSiteCheck:
    site_id: str
    site_name: str
    queried_identifier: str
    maigret_id_type: str
    maigret_status: str
    product_status: str
    url_main: str | None
    url_user: str | None
    url_probe: str | None
    http_status: int | None
    rank: int | None
    tags: tuple[str, ...]
    is_similar: bool
    context: str | None
    error_type: str | None
    error_detail: str | None
    extracted_identifiers: tuple[MaigretExtractedIdentifier, ...]
    extracted_links: tuple[MaigretExtractedLink, ...]
    extracted_fields: tuple[MaigretExtractedField, ...]


@dataclass(frozen=True)
class MaigretCoverage:
    selected: int
    completed: int
    claimed: int
    available: int
    unknown: int
    illegal: int


@dataclass(frozen=True)
class MaigretScanResult:
    catalog_snapshot_id: str
    queried_identifier: str
    product_identifier_type: str
    maigret_id_type: str
    selected_site_ids: tuple[str, ...]
    status: str
    cancelled: bool
    site_checks: tuple[MaigretSiteCheck, ...]
    account_candidates: tuple[MaigretAccountCandidate, ...]
    extracted_identifiers: tuple[MaigretExtractedIdentifier, ...]
    extracted_links: tuple[MaigretExtractedLink, ...]
    extracted_fields: tuple[MaigretExtractedField, ...]
    coverage: MaigretCoverage


class MaigretScanCancelled(asyncio.CancelledError):
    """Cancellation that carries the normalized checks completed so far."""

    def __init__(self, partial_result: MaigretScanResult) -> None:
        super().__init__("Maigret scan cancelled after preserving partial results")
        self.partial_result = partial_result


ProgressCallback = Callable[[MaigretProgress], object]
PartialResultCallback = Callable[[MaigretScanResult], object]


class _ProgressNotifier:
    """Silent Maigret notifier that exposes only bounded aggregate progress."""

    def __init__(
        self,
        *,
        identifier: str,
        maigret_id_type: str,
        selected_sites: int,
        callback: ProgressCallback | None,
        logger: logging.Logger,
    ) -> None:
        self._identifier = identifier
        self._maigret_id_type = maigret_id_type
        self._selected_sites = selected_sites
        self._callback = callback
        self._logger = logger
        self._completed_sites = 0

    def start(self, username: str, id_type: str) -> None:
        self._emit(site_name=None, maigret_status=None)

    def update(self, result: object, is_similar: bool = False) -> None:
        del is_similar
        self._completed_sites += 1
        self._emit(
            site_name=_safe_text(_value(result, "site_name")),
            maigret_status=_maigret_status(_value(result, "status"))[0],
        )

    def finish(self) -> None:
        return None

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        del message, args, kwargs

    def enrich(self, message: str, *args: object, **kwargs: object) -> None:
        del message, args, kwargs

    def _emit(self, *, site_name: str | None, maigret_status: str | None) -> None:
        if self._callback is None:
            return
        progress = MaigretProgress(
            identifier=self._identifier,
            maigret_id_type=self._maigret_id_type,
            completed_sites=self._completed_sites,
            selected_sites=self._selected_sites,
            site_name=site_name,
            maigret_status=maigret_status,
        )
        try:
            callback_result = self._callback(progress)
            if inspect.isawaitable(callback_result):
                callback_result.close()
                self._logger.warning("Ignoring awaitable Maigret progress callback")
        except Exception:
            self._logger.warning("Maigret progress callback failed", exc_info=True)


class MaigretDiscoveryAdapter:
    """Normalize one bounded Maigret identifier scan into product-neutral records."""

    def __init__(
        self,
        *,
        search_function: MaigretSearchFunction,
        catalog: Mapping[str, object],
        catalog_snapshot_id: str,
        config: MaigretScanConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._search = search_function
        self._catalog = dict(catalog)
        self._catalog_snapshot_id = catalog_snapshot_id.strip()
        self._config = config or MaigretScanConfig()
        self._logger = logger or logging.getLogger(__name__)
        if logger is None:
            self._logger.setLevel(logging.WARNING)

        if not self._catalog_snapshot_id:
            raise ValueError("catalog_snapshot_id is required")
        if not self._catalog:
            raise ValueError("catalog must contain at least one selected site")
        if any(not isinstance(site_id, str) or not site_id.strip() for site_id in self._catalog):
            raise ValueError("catalog site IDs must be non-empty strings")
        if len(self._catalog) > self._config.max_sites:
            raise ValueError(
                "catalog exceeds the configured shard limit; select a bounded shard first"
            )

    async def scan(
        self,
        identifier: str,
        *,
        product_identifier_type: str = "handle",
        on_progress: ProgressCallback | None = None,
        on_partial_result: PartialResultCallback | None = None,
    ) -> MaigretScanResult:
        normalized_identifier = _normalize_identifier(identifier)
        normalized_product_type = _normalize_product_identifier_type(product_identifier_type)
        maigret_id_type = map_product_identifier_type(normalized_product_type)
        selected_site_ids = tuple(self._catalog)
        partial_results: dict[str, object] = {}
        notifier = _ProgressNotifier(
            identifier=normalized_identifier,
            maigret_id_type=maigret_id_type,
            selected_sites=len(selected_site_ids),
            callback=on_progress,
            logger=self._logger,
        )

        try:
            returned_results = await self._search(
                username=normalized_identifier,
                site_dict=dict(self._catalog),
                logger=self._logger,
                query_notify=notifier,
                timeout=self._config.timeout_seconds,
                is_parsing_enabled=True,
                is_enrich_enabled=False,
                id_type=maigret_id_type,
                debug=False,
                forced=False,
                max_connections=self._config.max_connections,
                no_progressbar=True,
                cookies=None,
                retries=0,
                check_domains=False,
                proxy=None,
                tor_proxy=None,
                i2p_proxy=None,
                cloudflare_bypass=None,
                keywords=None,
                output_container=partial_results,
            )
        except asyncio.CancelledError as exc:
            partial = self._build_result(
                identifier=normalized_identifier,
                product_identifier_type=normalized_product_type,
                maigret_id_type=maigret_id_type,
                raw_results=partial_results,
                cancelled=True,
            )
            _deliver_partial_result(on_partial_result, partial, self._logger)
            raise MaigretScanCancelled(partial) from exc

        if returned_results is not None:
            if not isinstance(returned_results, Mapping):
                raise TypeError("Maigret search must return a mapping or None")
            partial_results.update(returned_results)

        return self._build_result(
            identifier=normalized_identifier,
            product_identifier_type=normalized_product_type,
            maigret_id_type=maigret_id_type,
            raw_results=partial_results,
            cancelled=False,
        )

    def _build_result(
        self,
        *,
        identifier: str,
        product_identifier_type: str,
        maigret_id_type: str,
        raw_results: Mapping[str, object],
        cancelled: bool,
    ) -> MaigretScanResult:
        site_checks = tuple(
            _normalize_site_check(
                site_id=site_id,
                catalog_site=self._catalog[site_id],
                raw_result=raw_results[site_id],
                identifier=identifier,
                maigret_id_type=maigret_id_type,
            )
            for site_id in self._catalog
            if site_id in raw_results and isinstance(raw_results[site_id], Mapping)
        )
        candidates = tuple(
            MaigretAccountCandidate(
                site_id=check.site_id,
                site_name=check.site_name,
                url=check.url_user,
                queried_identifier=identifier,
                maigret_id_type=maigret_id_type,
                relationship=(
                    "similar_handle_result" if check.is_similar else "exact_handle_result"
                ),
            )
            for check in site_checks
            if check.product_status == "found" and check.url_user
        )
        extracted_identifiers = _deduplicate(
            item for check in site_checks for item in check.extracted_identifiers
        )
        extracted_links = _deduplicate(
            item for check in site_checks for item in check.extracted_links
        )
        extracted_fields = _deduplicate(
            item for check in site_checks for item in check.extracted_fields
        )
        coverage = MaigretCoverage(
            selected=len(self._catalog),
            completed=len(site_checks),
            claimed=sum(check.product_status == "found" for check in site_checks),
            available=sum(check.product_status == "not_found" for check in site_checks),
            unknown=sum(
                check.product_status not in {"found", "not_found", "inapplicable"}
                for check in site_checks
            ),
            illegal=sum(check.product_status == "inapplicable" for check in site_checks),
        )
        return MaigretScanResult(
            catalog_snapshot_id=self._catalog_snapshot_id,
            queried_identifier=identifier,
            product_identifier_type=product_identifier_type,
            maigret_id_type=maigret_id_type,
            selected_site_ids=tuple(self._catalog),
            status=_aggregate_status(site_checks, coverage, cancelled=cancelled),
            cancelled=cancelled,
            site_checks=site_checks,
            account_candidates=candidates,
            extracted_identifiers=extracted_identifiers,
            extracted_links=extracted_links,
            extracted_fields=extracted_fields,
            coverage=coverage,
        )


def map_product_identifier_type(product_identifier_type: str) -> str:
    """Translate product vocabulary without leaking ``handle`` into Maigret."""

    normalized = _normalize_product_identifier_type(product_identifier_type)
    mappings = {
        "handle": "username",
        "username": "username",
        "gaia_id": "gaia_id",
        "steam_id": "steam_id",
        "wikimapia_uid": "wikimapia_uid",
        "uidme_uguid": "uidme_uguid",
        "yandex_public_id": "yandex_public_id",
        "vk_id": "vk_id",
        "ok_id": "ok_id",
        "yelp_userid": "yelp_userid",
        "qq_id": "qq_id",
        "bilibili_id": "bilibili_id",
    }
    try:
        return mappings[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported product identifier type: {product_identifier_type}") from exc


def _normalize_product_identifier_type(product_identifier_type: str) -> str:
    if not isinstance(product_identifier_type, str):
        raise TypeError("product_identifier_type must be a string")
    normalized = product_identifier_type.strip().casefold().replace("-", "_")
    if not normalized:
        raise ValueError("product_identifier_type must not be empty")
    return normalized


def _normalize_identifier(identifier: str) -> str:
    if not isinstance(identifier, str):
        raise TypeError("identifier must be a string")
    normalized = identifier.strip()
    if not normalized:
        raise ValueError("identifier must not be empty")
    if len(normalized) > _MAX_IDENTIFIER_LENGTH:
        raise ValueError("identifier exceeds the adapter limit")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError("identifier contains control characters")
    return normalized


def _normalize_site_check(
    *,
    site_id: str,
    catalog_site: object,
    raw_result: object,
    identifier: str,
    maigret_id_type: str,
) -> MaigretSiteCheck:
    assert isinstance(raw_result, Mapping)
    status_container = raw_result.get("status")
    raw_status, recognized_status = _maigret_status(_value(status_container, "status"))
    context = _safe_text(_value(status_container, "context"))
    error = _value(status_container, "error")
    error_type = _safe_text(_value(error, "type"))
    error_detail = _safe_text(_value(error, "desc")) or _safe_text(error)
    http_status = _integer(raw_result.get("http_status"))
    if not recognized_status:
        error_type = error_type or "Unrecognized status"
        detail = _safe_text(_value(status_container, "status"))
        error_detail = error_detail or (
            f"Unsupported Maigret status: {detail}" if detail else "Missing Maigret status"
        )

    site_object = raw_result.get("site", catalog_site)
    site_name = (
        _safe_text(_value(status_container, "site_name"))
        or _safe_text(_value(site_object, "name"))
        or site_id
    )
    url_main = _safe_text(raw_result.get("url_main")) or _safe_text(_value(site_object, "url_main"))
    url_user = _safe_text(raw_result.get("url_user")) or _safe_text(
        _value(status_container, "site_url_user")
    )
    url_probe = _safe_text(raw_result.get("url_probe"))
    rank = _integer(raw_result.get("rank"))
    if rank is None:
        rank = _integer(_value(site_object, "alexa_rank"))
    if rank is not None and not 0 <= rank <= _MAX_DATABASE_RANK:
        rank = None
    tags = _normalize_tags(
        _value(status_container, "tags") or raw_result.get("tags") or _value(site_object, "tags")
    )
    is_similar = bool(raw_result.get("is_similar", _value(site_object, "similar_search") or False))
    product_status = _product_status(
        raw_status,
        error_type=error_type,
        error_detail=error_detail,
        context=context,
        http_status=http_status,
    )

    if product_status == "found":
        extracted_identifiers = _normalize_extracted_identifiers(
            raw_result.get("ids_usernames"),
            source_site_id=site_id,
        )
        extracted_links = _normalize_extracted_links(
            raw_result.get("ids_links"),
            source_site_id=site_id,
        )
        extracted_fields = _normalize_extracted_fields(
            _extracted_data(raw_result, status_container),
            source_site_id=site_id,
        )
    else:
        extracted_identifiers = ()
        extracted_links = ()
        extracted_fields = ()

    return MaigretSiteCheck(
        site_id=site_id,
        site_name=site_name,
        queried_identifier=identifier,
        maigret_id_type=maigret_id_type,
        maigret_status=raw_status,
        product_status=product_status,
        url_main=url_main,
        url_user=url_user,
        url_probe=url_probe,
        http_status=http_status,
        rank=rank,
        tags=tags,
        is_similar=is_similar,
        context=context,
        error_type=error_type,
        error_detail=error_detail,
        extracted_identifiers=extracted_identifiers,
        extracted_links=extracted_links,
        extracted_fields=extracted_fields,
    )


def _maigret_status(value: object) -> tuple[str, bool]:
    if isinstance(value, Enum):
        token = value.name
    else:
        enum_name = _value(value, "name")
        token = enum_name if isinstance(enum_name, str) else value
    rendered = str(token or "").strip().upper()
    if "." in rendered:
        rendered = rendered.rsplit(".", 1)[-1]
    for status in ("CLAIMED", "AVAILABLE", "UNKNOWN", "ILLEGAL"):
        if rendered == status:
            return status, True
    return "UNKNOWN", False


def _product_status(
    maigret_status: str,
    *,
    error_type: str | None,
    error_detail: str | None,
    context: str | None,
    http_status: int | None,
) -> str:
    detail = " ".join(value.casefold() for value in (error_type, error_detail, context) if value)
    if "interrupted" in detail or "cancelled" in detail or "canceled" in detail:
        return "cancelled"
    if any(
        marker in detail
        for marker in ("check is disabled", "unsupported identifier", "no tor gateway", "no i2p")
    ) or (error_type and error_type.casefold() == "skipped"):
        return "skipped_configuration"
    if http_status == 429 or any(
        marker in detail
        for marker in (
            "rate limit",
            "too many requests",
            "retry-after",
            "retry after",
            "throttled",
        )
    ):
        return "rate_limited"
    if any(
        marker in detail
        for marker in (
            "captcha",
            "bot protection",
            "cloudflare",
            "challenge",
            "waf",
            "request blocked",
            "access denied",
        )
    ):
        return "captcha_blocked"
    if http_status == 401 or any(
        marker in detail
        for marker in (
            "login required",
            "log in required",
            "sign in required",
            "auth required",
            "authentication required",
            "authorization required",
            "unauthorized",
        )
    ):
        return "auth_required"
    if http_status in {403, 412, 999} or any(
        marker in detail
        for marker in (
            "http 403",
            "status 403",
            "403 forbidden",
            "http 412",
            "status 412",
            "precondition failed",
            "http 999",
            "status 999",
        )
    ):
        return "captcha_blocked"
    if any(
        marker in detail
        for marker in (
            "timeout",
            "timed out",
            "deadline exceeded",
            "connection deadline",
        )
    ):
        return "timeout"
    if (
        http_status is not None
        and 500 <= http_status <= 599
        or any(
            marker in detail
            for marker in (
                "network error",
                "connection error",
                "connection reset",
                "connection refused",
                "name resolution",
                "dns error",
                "ssl error",
                "tls error",
            )
        )
    ):
        return "provider_error"
    if maigret_status == "CLAIMED":
        return "found"
    if maigret_status == "AVAILABLE":
        return "not_found"
    if maigret_status == "ILLEGAL":
        return "inapplicable"
    return "provider_error"


def _extracted_data(raw_result: Mapping[str, object], status_container: object) -> object:
    status_data = _value(status_container, "ids_data")
    if isinstance(status_data, Mapping):
        return status_data
    status_json_data = _value(status_container, "ids")
    if isinstance(status_json_data, Mapping):
        return status_json_data
    return raw_result.get("ids_data")


def _normalize_extracted_identifiers(
    value: object,
    *,
    source_site_id: str,
) -> tuple[MaigretExtractedIdentifier, ...]:
    if not isinstance(value, Mapping):
        return ()
    identifiers: list[MaigretExtractedIdentifier] = []
    for raw_value, raw_type in value.items():
        identifier = _safe_text(raw_value, maximum=_MAX_IDENTIFIER_LENGTH)
        identifier_type = _safe_text(raw_type, maximum=_MAX_FIELD_NAME_LENGTH)
        if not identifier or not identifier_type:
            continue
        identifiers.append(
            MaigretExtractedIdentifier(
                value=identifier,
                maigret_id_type=identifier_type.casefold().replace("-", "_"),
                source_site_id=source_site_id,
            )
        )
    return _deduplicate(identifiers)


def _normalize_extracted_links(
    value: object,
    *,
    source_site_id: str,
) -> tuple[MaigretExtractedLink, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    links: list[MaigretExtractedLink] = []
    for raw_link in value:
        link = _safe_text(raw_link, maximum=_MAX_LINK_LENGTH)
        if not link or not _is_absolute_http_url(link):
            continue
        links.append(MaigretExtractedLink(url=link, source_site_id=source_site_id))
    return _deduplicate(links)


def _normalize_extracted_fields(
    value: object,
    *,
    source_site_id: str,
) -> tuple[MaigretExtractedField, ...]:
    if not isinstance(value, Mapping):
        return ()
    provider_key = source_site_id.strip().casefold()
    aliases = dict(_COMMON_PUBLIC_FIELD_ALIASES)
    aliases.update(_PROVIDER_PUBLIC_FIELD_ALIASES.get(provider_key, {}))
    candidates: list[tuple[int, str, str, object]] = []
    for raw_name in value:
        name = _safe_text(raw_name, maximum=_MAX_FIELD_NAME_LENGTH)
        if not name:
            continue
        compact_name = "".join(character for character in name.casefold() if character.isalnum())
        public_name = aliases.get(compact_name)
        if not public_name:
            continue
        candidates.append(
            (
                0 if compact_name == public_name.replace("_", "") else 1,
                name,
                public_name,
                value[raw_name],
            )
        )

    fields: list[MaigretExtractedField] = []
    emitted_names: set[str] = set()
    ordered_candidates = sorted(
        candidates,
        key=lambda item: (item[0], item[1].casefold(), item[2]),
    )
    for _priority, _raw_name, public_name, raw_value in ordered_candidates[:_MAX_COLLECTION_ITEMS]:
        if public_name in emitted_names:
            continue
        public_value = _public_display_value(public_name, raw_value)
        if public_value is None:
            continue
        fields.append(
            MaigretExtractedField(
                name=public_name,
                value=public_value,
                source_site_id=source_site_id,
            )
        )
        emitted_names.add(public_name)
    return tuple(fields)


def _public_display_value(name: str, value: object) -> object | None:
    if name in {"username", "display_name", "bio", "location"}:
        maximum = _MAX_IDENTIFIER_LENGTH if name == "username" else _MAX_FIELD_STRING_LENGTH
        return _safe_text(value, maximum=maximum)
    if name == "website":
        rendered = _safe_text(value, maximum=_MAX_LINK_LENGTH)
        return rendered if rendered and _is_absolute_http_url(rendered) else None
    if name in {"is_verified", "is_private"}:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            rendered = value.strip().casefold()
            if rendered in {"true", "yes", "1"}:
                return True
            if rendered in {"false", "no", "0"}:
                return False
        return None
    if name in {"follower_count", "following_count", "post_count"}:
        if isinstance(value, Mapping):
            value = value.get("count")
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if 0 <= value <= _MAX_PUBLIC_COUNT else None
        if isinstance(value, float) and value.is_integer():
            rendered = int(value)
            return rendered if 0 <= rendered <= _MAX_PUBLIC_COUNT else None
        if isinstance(value, str):
            digits = value.strip().replace(",", "")
            if digits.isdigit():
                rendered = int(digits)
                return rendered if rendered <= _MAX_PUBLIC_COUNT else None
        return None
    if name == "category":
        if isinstance(value, str):
            return _safe_text(value, maximum=_MAX_FIELD_STRING_LENGTH)
        if isinstance(value, (list, tuple, set, frozenset)):
            rendered = [
                text
                for item in list(value)[:10]
                if (text := _safe_text(item, maximum=_MAX_FIELD_NAME_LENGTH))
            ]
            return rendered or None
    return None


def _aggregate_status(
    site_checks: tuple[MaigretSiteCheck, ...],
    coverage: MaigretCoverage,
    *,
    cancelled: bool,
) -> str:
    if cancelled:
        return "cancelled"
    conclusive = {
        "found",
        "not_found",
        "inapplicable",
    }
    conclusive_count = sum(check.product_status in conclusive for check in site_checks)
    has_error = any(check.product_status not in conclusive for check in site_checks)
    incomplete = coverage.completed < coverage.selected
    if incomplete or has_error:
        return "partial_success" if conclusive_count else "provider_error"
    if coverage.claimed:
        return "success"
    return "no_result"


def _deliver_partial_result(
    callback: PartialResultCallback | None,
    result: MaigretScanResult,
    logger: logging.Logger,
) -> None:
    if callback is None:
        return
    try:
        callback_result = callback(result)
        if inspect.isawaitable(callback_result):
            callback_result.close()
            logger.warning("Ignoring awaitable Maigret partial-result callback")
    except Exception:
        logger.warning("Maigret partial-result callback failed", exc_info=True)


def _value(container: object, name: str) -> object:
    if isinstance(container, Mapping):
        return container.get(name)
    return getattr(container, name, None)


def _safe_text(value: object, *, maximum: int = _MAX_DETAIL_LENGTH) -> str | None:
    if value is None:
        return None
    try:
        text = " ".join(str(value).split())
    except Exception:
        return None
    if not text:
        return None
    return text[:maximum]


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _normalize_tags(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    tags = {
        normalized
        for item in value
        if (normalized := _safe_text(item, maximum=_MAX_FIELD_NAME_LENGTH))
    }
    return tuple(sorted(tags))


def _is_absolute_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _deduplicate[T](items: Iterable[T]) -> tuple[T, ...]:
    unique: list[T] = []
    for item in items:
        if item in unique:
            continue
        unique.append(item)
    return tuple(unique)
