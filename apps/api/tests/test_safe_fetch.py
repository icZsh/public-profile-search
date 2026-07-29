from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import httpx
import pytest

from apps.api.app.safe_fetch.service import (
    NetworkFetchDisabled,
    SafeFetchError,
    SafeFetchGateway,
)

PUBLIC_IP = "140.82.112.3"


def safe_fetch_settings(**overrides):
    values = {
        "github_api_version": "2026-03-10",
        "github_api_token": None,
        "safe_fetch_max_bytes": 256,
        "safe_fetch_total_timeout_seconds": 8,
        "safe_fetch_connect_timeout_seconds": 2,
        "safe_fetch_read_timeout_seconds": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def gateway(handler, **overrides) -> SafeFetchGateway:
    return SafeFetchGateway(
        safe_fetch_settings(**overrides.pop("settings_overrides", {})),
        transport=httpx.MockTransport(handler),
        resolver=overrides.pop("resolver", lambda host, port: [PUBLIC_IP]),
        peer_ip_getter=overrides.pop("peer_ip_getter", lambda response: PUBLIC_IP),
        monotonic=overrides.pop("monotonic", lambda: 0.0),
        **overrides,
    )


def json_response(
    status_code: int = 200,
    *,
    content: bytes = b'{"login":"octocat"}',
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    merged_headers = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        merged_headers.update(headers)
    return httpx.Response(
        status_code,
        stream=httpx.ByteStream(content),
        headers=merged_headers,
    )


def test_fetches_only_exact_github_user_endpoint_with_safe_headers():
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["url"] = str(request.url)
        observed["headers"] = request.headers
        return json_response()

    response = gateway(handler).fetch_github_user("Octo-Cat")

    assert response.status_code == 200
    assert response.json() == {"login": "octocat"}
    assert observed["method"] == "GET"
    assert observed["url"] == "https://api.github.com/users/octo-cat"
    headers = observed["headers"]
    assert isinstance(headers, httpx.Headers)
    assert headers["accept"] == "application/vnd.github+json"
    assert headers["accept-encoding"] == "identity"
    assert headers["x-github-api-version"] == "2026-03-10"
    assert "authorization" not in headers


def test_server_side_token_is_used_without_entering_response_headers():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer server-secret"
        return json_response(headers={"X-RateLimit-Remaining": "59"})

    response = gateway(
        handler,
        settings_overrides={"github_api_token": "server-secret"},
    ).fetch_github_user("octocat")

    assert response.headers["x-ratelimit-remaining"] == "59"
    assert "authorization" not in response.headers


@pytest.mark.parametrize(
    "username",
    [
        "",
        "-octocat",
        "octocat-",
        "octo/cat",
        "octo.cat",
        "octo%2fcat",
        "octo@cat",
        " octocat",
        "octocat ",
        "octo\u2603cat",
        "a" * 40,
    ],
)
def test_rejects_non_github_username_grammar_before_network(username: str):
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return json_response()

    with pytest.raises(SafeFetchError, match="approved provider request") as exc_info:
        gateway(handler).fetch_github_user(username)

    assert exc_info.value.code == "invalid_username"
    assert not called


@pytest.mark.parametrize(
    "unsafe_ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_rejects_dns_answer_sets_containing_any_non_global_address(unsafe_ip: str):
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return json_response()

    client = gateway(handler, resolver=lambda host, port: [PUBLIC_IP, unsafe_ip])
    with pytest.raises(SafeFetchError) as exc_info:
        client.fetch_github_user("octocat")

    assert exc_info.value.code == "unsafe_destination"
    assert not called


class TrackingStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.iterated = False

    def __iter__(self) -> Iterator[bytes]:
        self.iterated = True
        yield from self.chunks


def test_rejects_unsafe_connected_peer_before_reading_body():
    stream = TrackingStream([b'{"login":"octocat"}'])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=stream,
        )

    client = gateway(handler, peer_ip_getter=lambda response: "127.0.0.1")
    with pytest.raises(SafeFetchError) as exc_info:
        client.fetch_github_user("octocat")

    assert exc_info.value.code == "unsafe_destination"
    assert not stream.iterated


def test_fails_closed_when_connected_peer_cannot_be_observed():
    client = gateway(
        lambda request: json_response(),
        peer_ip_getter=lambda response: None,
    )

    with pytest.raises(SafeFetchError) as exc_info:
        client.fetch_github_user("octocat")

    assert exc_info.value.code == "peer_ip_unavailable"


def test_rejects_redirect_without_following_location():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302,
            headers={
                "Content-Type": "application/json",
                "Location": "http://127.0.0.1/latest/meta-data",
            },
            content=b"{}",
        )

    with pytest.raises(SafeFetchError) as exc_info:
        gateway(handler).fetch_github_user("octocat")

    assert exc_info.value.code == "redirect_blocked"
    assert requests == ["https://api.github.com/users/octocat"]


@pytest.mark.parametrize(
    ("headers", "expected_code"),
    [
        ({"Content-Type": "text/html"}, "invalid_content_type"),
        (
            {"Content-Type": "application/json", "Content-Encoding": "gzip"},
            "unsupported_content_encoding",
        ),
        (
            {"Content-Type": "application/json", "Content-Length": "not-a-number"},
            "invalid_content_length",
        ),
        (
            {"Content-Type": "application/json", "Content-Length": "257"},
            "response_too_large",
        ),
    ],
)
def test_rejects_unsafe_response_headers(headers: dict[str, str], expected_code: str):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=headers,
            stream=httpx.ByteStream(b"{}"),
        )

    with pytest.raises(SafeFetchError) as exc_info:
        gateway(handler).fetch_github_user("octocat")

    assert exc_info.value.code == expected_code


def test_caps_actual_streamed_bytes_without_content_length():
    stream = TrackingStream([b'{"value":"', b"x" * 260, b'"}'])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=stream,
        )

    with pytest.raises(SafeFetchError) as exc_info:
        gateway(handler).fetch_github_user("octocat")

    assert exc_info.value.code == "response_too_large"


def test_rejects_invalid_json_even_with_json_media_type():
    with pytest.raises(SafeFetchError) as exc_info:
        gateway(lambda request: json_response(content=b"{broken")).fetch_github_user("octocat")

    assert exc_info.value.code == "invalid_json"


def test_maps_http_timeouts_to_safe_error_without_url_or_username():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(
            "timeout for https://api.github.com/users/private-name",
            request=request,
        )

    with pytest.raises(SafeFetchError) as exc_info:
        gateway(handler).fetch_github_user("private-name")

    assert exc_info.value.code == "network_timeout"
    assert "private-name" not in str(exc_info.value)
    assert "github.com" not in str(exc_info.value)


def test_enforces_absolute_wall_clock_deadline():
    ticks = iter([0.0, 0.0, 0.0, 9.0])

    with pytest.raises(SafeFetchError) as exc_info:
        gateway(
            lambda request: json_response(),
            monotonic=lambda: next(ticks),
        ).fetch_github_user("octocat")

    assert exc_info.value.code == "network_timeout"


def test_legacy_generic_fetch_stays_fail_closed():
    with pytest.raises(NetworkFetchDisabled):
        SafeFetchGateway().fetch("https://example.com")
