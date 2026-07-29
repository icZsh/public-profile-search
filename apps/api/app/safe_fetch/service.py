from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

GITHUB_API_HOST = "api.github.com"
GITHUB_API_PORT = 443
GITHUB_USERNAME_PATTERN = re.compile(
    r"\A[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z",
    re.ASCII,
)

Resolver = Callable[[str, int], Iterable[str]]
PeerIpGetter = Callable[[httpx.Response], str | None]
MonotonicClock = Callable[[], float]


class NetworkFetchDisabled(RuntimeError):
    """Raised when a caller attempts to use the legacy generic fetch interface."""


class SafeFetchError(RuntimeError):
    """A fetch failure whose code and message are safe to expose or log."""

    def __init__(self, code: str, message: str = "The approved provider request failed."):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SafeFetchResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SafeFetchError("invalid_json") from exc


def _default_resolver(host: str, port: int) -> tuple[str, ...]:
    try:
        answers = socket.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as exc:
        raise SafeFetchError("dns_resolution_failed") from exc
    return tuple(dict.fromkeys(str(answer[4][0]) for answer in answers))


def _default_peer_ip_getter(response: httpx.Response) -> str | None:
    stream = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        return None
    try:
        server_address = stream.get_extra_info("server_addr")
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if not server_address:
        return None
    if isinstance(server_address, (tuple, list)):
        return str(server_address[0]) if server_address else None
    return str(server_address)


def _validated_global_ip(
    value: str,
    *,
    unavailable_code: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    candidate = value.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError as exc:
        raise SafeFetchError(unavailable_code) from exc
    if (
        not address.is_global
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_private
        or address.is_reserved
        or address.is_unspecified
    ):
        raise SafeFetchError("unsafe_destination")
    return address


def _secret_value(value: object) -> str:
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return str(getter())
    return str(value)


class SafeFetchGateway:
    """Fetches one fixed, allowlisted GitHub public-profile API resource."""

    def __init__(
        self,
        settings: object | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver | None = None,
        peer_ip_getter: PeerIpGetter | None = None,
        monotonic: MonotonicClock | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._resolver = resolver or _default_resolver
        self._peer_ip_getter = peer_ip_getter or _default_peer_ip_getter
        self._monotonic = monotonic or time.monotonic

    def fetch(self, _url: str) -> bytes:
        """The old arbitrary-URL interface intentionally remains unavailable."""

        raise NetworkFetchDisabled("Generic network fetching is disabled.")

    def fetch_github_user(self, username: str) -> SafeFetchResponse:
        if self._settings is None:
            raise SafeFetchError("safe_fetch_not_configured")
        normalized_username = self._validate_username(username)
        maximum_bytes = self._positive_setting("safe_fetch_max_bytes")
        total_timeout = self._positive_setting("safe_fetch_total_timeout_seconds")
        connect_timeout = self._positive_setting("safe_fetch_connect_timeout_seconds")
        read_timeout = self._positive_setting("safe_fetch_read_timeout_seconds")
        started_at = self._monotonic()

        try:
            resolved_addresses = tuple(
                dict.fromkeys(
                    str(address) for address in self._resolver(GITHUB_API_HOST, GITHUB_API_PORT)
                )
            )
        except SafeFetchError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise SafeFetchError("dns_resolution_failed") from exc
        if not resolved_addresses:
            raise SafeFetchError("dns_resolution_failed")
        for address in resolved_addresses:
            _validated_global_ip(address, unavailable_code="dns_resolution_failed")
        self._check_deadline(started_at, total_timeout)

        url = f"https://{GITHUB_API_HOST}/users/{normalized_username}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
            "User-Agent": "public-profile-search-prototype/0.2",
            "X-GitHub-Api-Version": str(self._settings.github_api_version),
        }
        api_token = _secret_value(getattr(self._settings, "github_api_token", None))
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=connect_timeout,
            pool=connect_timeout,
        )
        try:
            with (
                httpx.Client(
                    transport=self._transport,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream("GET", url, headers=headers) as response,
            ):
                self._check_deadline(started_at, total_timeout)
                self._validate_peer(response)
                if 300 <= response.status_code < 400:
                    raise SafeFetchError("redirect_blocked")
                self._validate_response_headers(response, maximum_bytes)
                body = self._read_bounded_body(
                    response,
                    maximum_bytes=maximum_bytes,
                    started_at=started_at,
                    total_timeout=total_timeout,
                )
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                result = SafeFetchResponse(
                    status_code=response.status_code,
                    headers=response_headers,
                    body=body,
                )
                result.json()
                return result
        except SafeFetchError:
            raise
        except httpx.TimeoutException as exc:
            raise SafeFetchError("network_timeout") from exc
        except httpx.RequestError as exc:
            raise SafeFetchError("network_error") from exc

    @staticmethod
    def _validate_username(username: str) -> str:
        if not isinstance(username, str) or not GITHUB_USERNAME_PATTERN.fullmatch(username):
            raise SafeFetchError("invalid_username")
        return username.lower()

    def _positive_setting(self, name: str) -> float:
        try:
            value = float(getattr(self._settings, name))
        except (AttributeError, TypeError, ValueError) as exc:
            raise SafeFetchError("safe_fetch_not_configured") from exc
        if value <= 0:
            raise SafeFetchError("safe_fetch_not_configured")
        return value

    def _check_deadline(self, started_at: float, total_timeout: float) -> None:
        if self._monotonic() - started_at > total_timeout:
            raise SafeFetchError("network_timeout")

    def _validate_peer(self, response: httpx.Response) -> None:
        try:
            peer_ip = self._peer_ip_getter(response)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise SafeFetchError("peer_ip_unavailable") from exc
        if not peer_ip:
            raise SafeFetchError("peer_ip_unavailable")
        _validated_global_ip(peer_ip, unavailable_code="peer_ip_unavailable")

    @staticmethod
    def _validate_response_headers(response: httpx.Response, maximum_bytes: float) -> None:
        content_encoding = response.headers.get("content-encoding", "").strip().lower()
        if content_encoding and content_encoding != "identity":
            raise SafeFetchError("unsupported_content_encoding")

        media_type = response.headers.get("content-type", "").split(";", 1)[0]
        media_type = media_type.strip().lower()
        is_json = media_type == "application/json" or (
            media_type.startswith("application/") and media_type.endswith("+json")
        )
        if not is_json:
            raise SafeFetchError("invalid_content_type")

        content_length = response.headers.get("content-length")
        if content_length is None:
            return
        try:
            declared_length = int(content_length, 10)
        except ValueError as exc:
            raise SafeFetchError("invalid_content_length") from exc
        if declared_length < 0:
            raise SafeFetchError("invalid_content_length")
        if declared_length > maximum_bytes:
            raise SafeFetchError("response_too_large")

    def _read_bounded_body(
        self,
        response: httpx.Response,
        *,
        maximum_bytes: float,
        started_at: float,
        total_timeout: float,
    ) -> bytes:
        body = bytearray()
        for chunk in response.iter_raw():
            self._check_deadline(started_at, total_timeout)
            if len(body) + len(chunk) > maximum_bytes:
                raise SafeFetchError("response_too_large")
            body.extend(chunk)
        self._check_deadline(started_at, total_timeout)
        return bytes(body)
