import asyncio
import logging
from enum import Enum
from types import SimpleNamespace

import pytest

from workers.providers.maigret_adapter import (
    MaigretDiscoveryAdapter,
    MaigretScanCancelled,
    MaigretScanConfig,
    map_product_identifier_type,
)


class FakeStatus(Enum):
    CLAIMED = "Claimed"
    AVAILABLE = "Available"
    UNKNOWN = "Unknown"
    ILLEGAL = "Illegal"


def status(
    value: FakeStatus,
    *,
    site_name: str,
    url: str = "",
    ids_data=None,
    error=None,
    context=None,
):
    return SimpleNamespace(
        status=value,
        site_name=site_name,
        site_url_user=url,
        ids_data=ids_data,
        error=error,
        context=context,
        tags=["social"],
    )


def test_scan_uses_safe_library_options_and_normalizes_discovery():
    captured = {}
    progress = []
    catalog = {
        "Alpha": SimpleNamespace(name="Alpha", url_main="https://alpha.test"),
        "Beta": SimpleNamespace(name="Beta", url_main="https://beta.test"),
    }

    async def fake_search(**kwargs):
        captured.update(kwargs)
        claimed = status(
            FakeStatus.CLAIMED,
            site_name="Alpha",
            url="https://alpha.test/alice",
            ids_data={"display_name": "Alice", "nested": {"score": 1}},
        )
        available = status(FakeStatus.AVAILABLE, site_name="Beta")
        kwargs["query_notify"].start(kwargs["username"], kwargs["id_type"])
        kwargs["query_notify"].update(claimed)
        kwargs["query_notify"].update(available)
        return {
            "Beta": {
                "status": available,
                "url_user": "https://beta.test/alice",
                "http_status": 404,
                "rank": 9_223_372_036_854_775_807,
            },
            "Alpha": {
                "status": claimed,
                "url_main": "https://alpha.test",
                "url_user": "https://alpha.test/alice",
                "url_probe": "https://alpha.test/alice",
                "http_status": 200,
                "rank": 5,
                "is_similar": False,
                "ids_usernames": {
                    "alice_dev": "username",
                    "76561198000000000": "steam_id",
                },
                "ids_links": [
                    " https://portfolio.example/alice ",
                    "https://portfolio.example/alice",
                    "javascript:alert(1)",
                    "https://user:secret@example.test/private",
                ],
            },
            "Unexpected": {"status": claimed},
        }

    adapter = MaigretDiscoveryAdapter(
        search_function=fake_search,
        catalog=catalog,
        catalog_snapshot_id="maigret-0.6.3:test",
    )
    result = asyncio.run(adapter.scan("  Alice  ", on_progress=progress.append))

    assert captured["username"] == "Alice"
    assert captured["logger"].getEffectiveLevel() >= logging.WARNING
    assert captured["id_type"] == "username"
    assert captured["site_dict"] == catalog
    assert captured["is_parsing_enabled"] is True
    assert captured["is_enrich_enabled"] is False
    assert captured["retries"] == 0
    assert captured["check_domains"] is False
    assert captured["proxy"] is None
    assert captured["tor_proxy"] is None
    assert captured["i2p_proxy"] is None
    assert captured["cookies"] is None
    assert captured["cloudflare_bypass"] is None
    assert captured["forced"] is False
    assert captured["no_progressbar"] is True
    assert isinstance(captured["output_container"], dict)

    assert result.status == "success"
    assert result.selected_site_ids == ("Alpha", "Beta")
    assert [check.site_id for check in result.site_checks] == ["Alpha", "Beta"]
    assert result.coverage.selected == result.coverage.completed == 2
    assert result.coverage.claimed == result.coverage.available == 1
    assert result.site_checks[1].rank is None
    assert len(result.account_candidates) == 1
    assert result.account_candidates[0].relationship == "exact_handle_result"
    assert {(item.value, item.maigret_id_type) for item in result.extracted_identifiers} == {
        ("alice_dev", "username"),
        ("76561198000000000", "steam_id"),
    }
    assert [item.url for item in result.extracted_links] == ["https://portfolio.example/alice"]
    assert {item.name for item in result.extracted_fields} == {"display_name"}
    assert [item.completed_sites for item in progress] == [0, 1, 2]


def test_statuses_and_unknown_error_details_are_kept_distinct():
    catalog = {
        name: SimpleNamespace(name=name)
        for name in (
            "Claimed",
            "Available",
            "Illegal",
            "Timeout",
            "Rate",
            "Captcha",
            "Auth",
            "Skipped",
        )
    }

    async def fake_search(**kwargs):
        del kwargs
        return {
            "Claimed": {
                "status": {"status": "Claimed", "site_name": "Claimed"},
                "url_user": "https://claimed.test/alice",
            },
            "Available": {"status": status(FakeStatus.AVAILABLE, site_name="Available")},
            "Illegal": {"status": status(FakeStatus.ILLEGAL, site_name="Illegal")},
            "Timeout": {
                "status": status(
                    FakeStatus.UNKNOWN,
                    site_name="Timeout",
                    error=SimpleNamespace(type="Request timeout", desc="deadline"),
                )
            },
            "Rate": {
                "status": status(
                    FakeStatus.UNKNOWN,
                    site_name="Rate",
                    error=SimpleNamespace(type="HTTP", desc="429 Too Many Requests"),
                ),
                "http_status": 429,
            },
            "Captcha": {
                "status": status(
                    FakeStatus.UNKNOWN,
                    site_name="Captcha",
                    error=SimpleNamespace(type="Bot protection", desc="Cloudflare challenge"),
                )
            },
            "Auth": {
                "status": status(
                    FakeStatus.UNKNOWN,
                    site_name="Auth",
                    error=SimpleNamespace(type="Login required", desc="authorization needed"),
                )
            },
            "Skipped": {
                "status": status(
                    FakeStatus.UNKNOWN,
                    site_name="Skipped",
                    error=SimpleNamespace(type="Skipped", desc="no tor gateway configured"),
                )
            },
        }

    result = asyncio.run(
        MaigretDiscoveryAdapter(
            search_function=fake_search,
            catalog=catalog,
            catalog_snapshot_id="fixture",
        ).scan("alice")
    )

    assert {check.site_id: check.product_status for check in result.site_checks} == {
        "Claimed": "found",
        "Available": "not_found",
        "Illegal": "inapplicable",
        "Timeout": "timeout",
        "Rate": "rate_limited",
        "Captcha": "captcha_blocked",
        "Auth": "auth_required",
        "Skipped": "skipped_configuration",
    }
    assert result.status == "partial_success"
    assert result.coverage == result.coverage.__class__(
        selected=8,
        completed=8,
        claimed=1,
        available=1,
        unknown=5,
        illegal=1,
    )


def test_channel_restrictions_override_claimed_and_available_statuses():
    cases = {
        "Claimed403": (
            FakeStatus.CLAIMED,
            403,
            SimpleNamespace(type="HTTP", desc="Forbidden"),
            "captcha_blocked",
        ),
        "Available412": (
            FakeStatus.AVAILABLE,
            412,
            SimpleNamespace(type="HTTP", desc="Precondition failed"),
            "captcha_blocked",
        ),
        "Claimed429": (
            FakeStatus.CLAIMED,
            429,
            SimpleNamespace(type="HTTP", desc="Too Many Requests"),
            "rate_limited",
        ),
        "Available999": (
            FakeStatus.AVAILABLE,
            999,
            SimpleNamespace(type="HTTP", desc="Request denied"),
            "captcha_blocked",
        ),
        "ClaimedCaptcha": (
            FakeStatus.CLAIMED,
            200,
            SimpleNamespace(type="Bot protection", desc="Captcha challenge"),
            "captcha_blocked",
        ),
        "AvailableLogin": (
            FakeStatus.AVAILABLE,
            200,
            SimpleNamespace(type="Login required", desc="Sign in required"),
            "auth_required",
        ),
        "ClaimedTimeout": (
            FakeStatus.CLAIMED,
            None,
            SimpleNamespace(type="Request timeout", desc="Connection timed out"),
            "timeout",
        ),
        "Claimed503": (
            FakeStatus.CLAIMED,
            503,
            SimpleNamespace(type="HTTP", desc="Service unavailable"),
            "provider_error",
        ),
        "AvailableNetwork": (
            FakeStatus.AVAILABLE,
            None,
            SimpleNamespace(type="Network error", desc="Connection reset"),
            "provider_error",
        ),
    }
    catalog = {name: SimpleNamespace(name=name) for name in cases}

    async def fake_search(**kwargs):
        del kwargs
        return {
            name: {
                "status": status(
                    raw_status,
                    site_name=name,
                    url=f"https://{name.casefold()}.test/alice",
                    ids_data={"display_name": "Must not escape"},
                    error=error,
                ),
                "url_user": f"https://{name.casefold()}.test/alice",
                "http_status": http_status,
                "ids_usernames": {"alice_elsewhere": "username"},
            }
            for name, (raw_status, http_status, error, _expected) in cases.items()
        }

    result = asyncio.run(
        MaigretDiscoveryAdapter(
            search_function=fake_search,
            catalog=catalog,
            catalog_snapshot_id="fixture",
        ).scan("alice")
    )

    assert {check.site_id: check.product_status for check in result.site_checks} == {
        name: expected for name, (*_inputs, expected) in cases.items()
    }
    assert result.account_candidates == ()
    assert result.extracted_identifiers == ()
    assert result.extracted_fields == ()
    assert result.status == "provider_error"
    assert result.coverage == result.coverage.__class__(
        selected=len(cases),
        completed=len(cases),
        claimed=0,
        available=0,
        unknown=len(cases),
        illegal=0,
    )


def test_extracted_fields_use_public_provider_allowlists():
    catalog = {
        name: SimpleNamespace(name=name)
        for name in ("Instagram", "Threads", "Clubhouse", "Example")
    }
    profile_data = {
        "Instagram": {
            "username": "alice",
            "full_name": "Alice Example",
            "biography": "Public bio",
            "external_url": "https://portfolio.example/alice",
            "is_private": False,
            "is_verified": True,
            "edge_followed_by": {"count": 123},
            "edge_follow": {"count": 45},
            "edge_owner_to_timeline_media": {"count": 6},
            "id": "internal-id",
            "facebook_uid": "internal-facebook-id",
            "email": "alice@example.test",
            "phone_number": "+15555550123",
            "profile_pic_url_hd": "https://cdn.example/signed-avatar",
            "raw_json": {"secret": "extractor output"},
        },
        "Threads": {
            "username": "alice",
            "full_name": "Alice Example",
            "biography": "Threads bio",
            "category_name": "Technology",
            "follower_count": "1,234",
            "is_verified": False,
            "user_id": "internal-id",
            "email": "alice@example.test",
            "profile_pic_url": "https://cdn.example/signed-avatar",
        },
        "Clubhouse": {
            "username": "alice",
            "name": "Alice Example",
            "bio": "Clubhouse bio",
            "num_followers": 20,
            "num_following": 5,
            "is_verified": True,
            "user_id": "internal-id",
            "phone": "+15555550123",
            "photo_url": "https://cdn.example/signed-avatar",
        },
        "Example": {
            "display_name": "Alice Example",
            "bio": "Public bio",
            "location": "Philadelphia",
            "website": "https://portfolio.example/alice",
            "verified": "true",
            "id": "internal-id",
            "email": "alice@example.test",
            "avatar": "https://cdn.example/signed-avatar",
            "nested": {"extractor": "output"},
        },
    }

    async def fake_search(**kwargs):
        del kwargs
        return {
            name: {
                "status": status(
                    FakeStatus.CLAIMED,
                    site_name=name,
                    url=f"https://{name.casefold()}.test/alice",
                    ids_data=fields,
                ),
                "url_user": f"https://{name.casefold()}.test/alice",
                "http_status": 200,
            }
            for name, fields in profile_data.items()
        }

    result = asyncio.run(
        MaigretDiscoveryAdapter(
            search_function=fake_search,
            catalog=catalog,
            catalog_snapshot_id="fixture",
        ).scan("alice")
    )
    by_site = {
        check.site_id: {field.name: field.value for field in check.extracted_fields}
        for check in result.site_checks
    }

    assert by_site == {
        "Instagram": {
            "bio": "Public bio",
            "display_name": "Alice Example",
            "follower_count": 123,
            "following_count": 45,
            "is_private": False,
            "is_verified": True,
            "post_count": 6,
            "username": "alice",
            "website": "https://portfolio.example/alice",
        },
        "Threads": {
            "bio": "Threads bio",
            "category": "Technology",
            "display_name": "Alice Example",
            "follower_count": 1234,
            "is_verified": False,
            "username": "alice",
        },
        "Clubhouse": {
            "bio": "Clubhouse bio",
            "display_name": "Alice Example",
            "follower_count": 20,
            "following_count": 5,
            "is_verified": True,
            "username": "alice",
        },
        "Example": {
            "bio": "Public bio",
            "display_name": "Alice Example",
            "is_verified": True,
            "location": "Philadelphia",
            "website": "https://portfolio.example/alice",
        },
    }


def test_cancellation_raises_with_normalized_partial_result():
    catalog = {
        "Completed": SimpleNamespace(name="Completed"),
        "Pending": SimpleNamespace(name="Pending"),
    }
    delivered = []

    async def cancelling_search(**kwargs):
        kwargs["output_container"]["Completed"] = {
            "status": status(
                FakeStatus.CLAIMED,
                site_name="Completed",
                url="https://completed.test/alice",
            ),
            "url_user": "https://completed.test/alice",
            "ids_usernames": {"alice_elsewhere": "username"},
        }
        raise asyncio.CancelledError

    adapter = MaigretDiscoveryAdapter(
        search_function=cancelling_search,
        catalog=catalog,
        catalog_snapshot_id="fixture",
    )

    with pytest.raises(MaigretScanCancelled) as raised:
        asyncio.run(adapter.scan("alice", on_partial_result=delivered.append))

    partial = raised.value.partial_result
    assert partial.cancelled is True
    assert partial.status == "cancelled"
    assert partial.coverage.selected == 2
    assert partial.coverage.completed == 1
    assert partial.account_candidates[0].url == "https://completed.test/alice"
    assert partial.extracted_identifiers[0].value == "alice_elsewhere"
    assert delivered == [partial]


def test_identifier_mapping_and_bounds_fail_closed():
    async def unused_search(**kwargs):
        del kwargs
        return {}

    assert map_product_identifier_type("handle") == "username"
    assert map_product_identifier_type("Steam-ID") == "steam_id"
    with pytest.raises(ValueError, match="unsupported"):
        map_product_identifier_type("email")
    with pytest.raises(ValueError, match="shard limit"):
        MaigretDiscoveryAdapter(
            search_function=unused_search,
            catalog={"one": object(), "two": object()},
            catalog_snapshot_id="fixture",
            config=MaigretScanConfig(max_sites=1),
        )
