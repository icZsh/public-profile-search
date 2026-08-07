from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace

import httpx

from apps.api.app.safe_fetch.service import SafeFetchGateway
from workers.providers.professional_search import (
    EXA_PROVIDER_ID,
    GITHUB_PROVIDER_ID,
    ProfessionalSearchResult,
    search_exa_people,
    search_exa_people_adaptive,
    search_github_people,
    to_provider_result,
)

PUBLIC_IP = "140.82.112.3"


def _gateway(handler) -> SafeFetchGateway:
    settings = SimpleNamespace(
        exa_api_key="exa-secret",
        github_api_version="2026-03-10",
        github_api_token=None,
        safe_fetch_max_bytes=65_536,
        safe_fetch_total_timeout_seconds=8,
        safe_fetch_connect_timeout_seconds=2,
        safe_fetch_read_timeout_seconds=3,
    )
    return SafeFetchGateway(
        settings,
        transport=httpx.MockTransport(handler),
        resolver=lambda host, port: [PUBLIC_IP],
        peer_ip_getter=lambda response: PUBLIC_IP,
        monotonic=lambda: 0.0,
    )


def _json_response(payload: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers={"Content-Type": "application/json"},
        stream=httpx.ByteStream(json.dumps(payload).encode()),
    )


def test_exa_adapter_keeps_only_linkedin_people_and_allowlisted_person_fields():
    payload = {
        "requestId": "internal-request-id",
        "results": [
            {
                "id": "internal-result-id",
                "title": "Alice Example - Staff Engineer",
                "url": "https://www.linkedin.com/in/Alice-Example?trk=search",
                "image": "https://cdn.example/avatar.jpg",
                "highlights": ["Staff engineer. Contact alice@example.test or +1 (555) 123-4567."],
                "entities": [
                    {
                        "id": "internal-person-id",
                        "type": "person",
                        "version": 1,
                        "properties": {
                            "name": "Alice Example",
                            "firstName": "Alice",
                            "lastName": "Example",
                            "location": "Bay Area",
                            "email": "alice@example.test",
                            "workHistory": [
                                {
                                    "title": "Staff Engineer",
                                    "location": "Bay Area",
                                    "dates": {"from": "2024-01-01", "to": None},
                                    "company": {
                                        "id": "internal-company-id",
                                        "name": "Example Labs",
                                    },
                                }
                            ],
                            "educationHistory": [
                                {
                                    "degree": "MS Computer Science",
                                    "dates": {"from": "2018", "to": "2020"},
                                    "institution": {
                                        "id": "internal-school-id",
                                        "name": "Example University",
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
            {
                "title": "Wrong host",
                "url": "https://linkedin.example/in/alice",
                "entities": [{"type": "person", "properties": {"name": "Wrong Host"}}],
            },
            {
                "title": "Wrong path",
                "url": "https://www.linkedin.com/company/example",
                "entities": [{"type": "person", "properties": {"name": "Wrong Path"}}],
            },
            {
                "title": "No typed person",
                "url": "https://www.linkedin.com/in/not-a-person",
                "entities": [{"type": "company", "properties": {"name": "Example"}}],
            },
        ],
    }
    observed_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed_body.update(json.loads(request.content))
        return _json_response(payload)

    result = search_exa_people(
        query="Alice Example software engineer",
        gateway=_gateway(handler),
    )

    assert result.status == "success"
    assert len(result.profiles) == 1
    profile = result.profiles[0]
    assert profile.provider_id == EXA_PROVIDER_ID
    assert profile.platform == "LinkedIn"
    assert profile.profile_url == "https://www.linkedin.com/in/alice-example"
    assert profile.handle == "alice-example"
    assert profile.display_name == "Alice Example"
    assert profile.location == "Bay Area"
    assert profile.company == "Example Labs"
    assert profile.work_history[0].title == "Staff Engineer"
    assert profile.education_history[0].institution == "Example University"
    assert profile.highlights == (
        "Staff engineer. Contact [redacted contact] or [redacted contact].",
    )
    serialized = json.dumps(asdict(profile), sort_keys=True)
    for forbidden in (
        "alice@example.test",
        "avatar.jpg",
        "internal-request-id",
        "internal-result-id",
        "internal-person-id",
        "internal-company-id",
        "internal-school-id",
    ):
        assert forbidden not in serialized
    assert observed_body["category"] == "people"
    assert observed_body["type"] == "fast"
    assert observed_body["numResults"] == 5
    assert "includeDomains" not in observed_body


def test_adaptive_exa_dedupes_canonical_profiles_and_stops_at_profile_budget():
    observed_queries: list[str] = []
    observed_limits: list[int] = []

    def person(handle: str, name: str) -> dict[str, object]:
        return {
            "title": f"{name} - Engineer",
            "url": f"https://www.linkedin.com/in/{handle}?trk=search",
            "entities": [{"type": "person", "properties": {"name": name}}],
        }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = str(body["query"])
        observed_queries.append(query)
        observed_limits.append(int(body["numResults"]))
        if query == "Alice Example alice":
            return _json_response(
                {
                    "results": [
                        person("alice-example", "Alice Example"),
                        person("alice-alt", "Alice Example"),
                    ]
                }
            )
        return _json_response(
            {
                "results": [
                    person("Alice-Example", "Alice Example"),
                    person("alice-third", "Alice Example"),
                ]
            }
        )

    result = search_exa_people_adaptive(
        queries=(
            "Alice Example alice",
            "Alice Example Bay Area",
            "Alice Example Example Labs",
        ),
        gateway=_gateway(handler),
        request_budget=3,
        profile_budget=3,
        time_budget_seconds=60,
        stagnation_query_limit=3,
        monotonic=lambda: 0.0,
    )

    assert result.status == "success"
    assert observed_queries == [
        "Alice Example alice",
        "Alice Example Bay Area",
    ]
    assert observed_limits == [5, 5]
    assert [profile.profile_url for profile in result.profiles] == [
        "https://www.linkedin.com/in/alice-example",
        "https://www.linkedin.com/in/alice-alt",
        "https://www.linkedin.com/in/alice-third",
    ]


def test_adaptive_exa_stops_after_configured_stagnation():
    observed_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_queries.append(str(json.loads(request.content)["query"]))
        return _json_response({"results": []})

    result = search_exa_people_adaptive(
        queries=("one", "two", "three", "four"),
        gateway=_gateway(handler),
        request_budget=4,
        profile_budget=10,
        time_budget_seconds=60,
        stagnation_query_limit=2,
        monotonic=lambda: 0.0,
    )

    assert result.status == "no_result"
    assert observed_queries == ["one", "two"]


def test_github_adapter_prioritizes_bounded_candidates_then_name_login_and_search():
    requested_profiles: list[str] = []
    observed_query = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_query
        if request.url.path == "/search/users":
            observed_query = request.url.params["q"]
            return _json_response(
                {
                    "total_count": 4,
                    "items": [
                        {"login": "search-one", "type": "User", "id": 101},
                        {"login": "search-two", "type": "User", "id": 102},
                        {"login": "search-three", "type": "User", "id": 103},
                        {"login": "search-four", "type": "User", "id": 104},
                    ],
                }
            )
        login = request.url.path.removeprefix("/users/")
        requested_profiles.append(login)
        return _json_response(
            {
                "login": login,
                "name": "Alice Example" if login == "aliceexample" else None,
                "html_url": f"https://github.com/{login}",
                "type": "User",
                "bio": "Engineer alice@example.test +1 (555) 123-4567",
                "company": "Example Labs",
                "location": "Bay Area",
                "blog": "http://unsafe.example",
                "twitter_username": "@invalid-handle",
                "email": "alice@example.test",
                "avatar_url": "https://avatars.example/internal.jpg",
                "id": 999,
                "node_id": "internal-node-id",
            }
        )

    result = search_github_people(
        full_name="Alice Example",
        gateway=_gateway(handler),
        max_profiles=3,
        candidate_logins=("candidate-one", "AliceExample"),
    )

    assert result.status == "success"
    assert observed_query == 'fullname:"Alice Example" type:user'
    assert requested_profiles == ["candidate-one", "aliceexample", "search-one"]
    assert [profile.handle for profile in result.profiles] == [
        "candidate-one",
        "aliceexample",
        "search-one",
    ]
    assert all(profile.provider_id == GITHUB_PROVIDER_ID for profile in result.profiles)
    assert result.profiles[0].bio == "Engineer [redacted contact] [redacted contact]"
    assert result.profiles[0].website is None
    assert result.profiles[0].social_handle is None
    serialized = json.dumps(asdict(result), sort_keys=True)
    for forbidden in (
        "alice@example.test",
        "avatars.example",
        "internal-node-id",
        '"id": 999',
        "search-two",
        "search-three",
        "search-four",
    ):
        assert forbidden not in serialized


def test_deep_github_request_budget_limits_profile_fetches():
    requested_profiles: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/users":
            return _json_response(
                {
                    "total_count": 3,
                    "items": [
                        {"login": "search-one", "type": "User"},
                        {"login": "search-two", "type": "User"},
                        {"login": "search-three", "type": "User"},
                    ],
                }
            )
        login = request.url.path.removeprefix("/users/")
        requested_profiles.append(login)
        return _json_response(
            {
                "login": login,
                "name": "Alice Example",
                "html_url": f"https://github.com/{login}",
                "type": "User",
            }
        )

    result = search_github_people(
        full_name="Alice Example",
        gateway=_gateway(handler),
        max_profiles=3,
        candidate_logins=("alice", "aliceexample"),
        request_budget=2,
        time_budget_seconds=60,
        monotonic=lambda: 0.0,
    )

    assert result.status == "success"
    assert requested_profiles == ["alice"]
    assert [profile.handle for profile in result.profiles] == ["alice"]


def test_github_success_with_rate_limited_search_is_partial_and_keeps_profile():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/users":
            return _json_response({}, status_code=429)
        login = request.url.path.removeprefix("/users/")
        return _json_response(
            {
                "login": login,
                "name": "Alice Example",
                "html_url": f"https://github.com/{login}",
                "type": "User",
            }
        )

    result = search_github_people(
        full_name="Alice Example",
        gateway=_gateway(handler),
        max_profiles=1,
        candidate_logins=("alice",),
        request_budget=2,
        time_budget_seconds=60,
        monotonic=lambda: 0.0,
    )

    assert result.status == "partial_success"
    assert [profile.handle for profile in result.profiles] == ["alice"]
    assert result.error_code == "github_professional_search_v1_rate_limited"


def test_github_adapter_rejects_unbounded_or_invalid_direct_candidates_without_network():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return _json_response({})

    too_many = search_github_people(
        full_name="Alice Example",
        gateway=_gateway(handler),
        candidate_logins=("one", "two", "three", "four"),
    )
    invalid = search_github_people(
        full_name="Alice Example",
        gateway=_gateway(handler),
        candidate_logins=("valid", "not/a/login"),
    )
    invalid_name = search_github_people(
        full_name='Alice "Example"',
        gateway=_gateway(handler),
        candidate_logins=("valid",),
    )

    assert too_many.status == "invalid_response"
    assert invalid.status == "invalid_response"
    assert invalid_name.status == "invalid_response"
    assert not called


def test_provider_conversion_has_stable_target_lineage_and_maps_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "results": [
                    {
                        "title": "Alice Example - Engineer",
                        "url": "https://www.linkedin.com/in/alice-example",
                        "highlights": ["Engineer at Example Labs"],
                        "entities": [
                            {
                                "type": "person",
                                "properties": {
                                    "name": "Alice Example",
                                    "workHistory": [
                                        {
                                            "title": "Engineer",
                                            "company": {"name": "Example Labs"},
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ]
            }
        )

    first = to_provider_result(
        search_exa_people(query="first query", gateway=_gateway(handler), max_results=1)
    )
    second = to_provider_result(
        search_exa_people(query="different query", gateway=_gateway(handler), max_results=1)
    )

    assert first.status == "success"
    assert len(first.documents) == 1
    document = first.documents[0]
    assert document.source_type == "professional_profile_index"
    assert document.trust_class == "indexed_professional_profile"
    assert document.extracted_fields["source_family"] == "exa_people"
    assert document.extracted_fields["target_platform"] == "linkedin"
    assert document.lineage_key == second.documents[0].lineage_key

    invalid = to_provider_result(
        ProfessionalSearchResult(
            provider_id=EXA_PROVIDER_ID,
            status="invalid_response",
            profiles=(),
            error_code="exa_invalid_payload",
        )
    )
    assert invalid.status == "provider_error"
    assert invalid.error_code == "exa_invalid_payload"
