import json

import httpx
import pytest

from workers.providers.maigret_adapter import (
    MaigretAccountCandidate,
    MaigretCoverage,
    MaigretScanResult,
    MaigretSiteCheck,
)
from workers.providers.public_profile_metadata import (
    PublicProfileMetadataError,
    enrich_first_party_metadata,
    parse_clubhouse_profile,
    parse_threads_profile,
)


def test_threads_metadata_requires_and_extracts_exact_handle():
    body = """
    <html>
      <head>
        <meta property="og:title"
              content="Example Person (&#064;octaviyao) &#x2022; Threads, Say more" />
        <meta property="og:description"
              content="70 Followers &#x2022; 0 Threads. See the latest conversations." />
      </head>
    </html>
    """

    metadata = parse_threads_profile(body, expected_handle="octaviyao")

    assert metadata.display_fields() == {
        "username": "octaviyao",
        "fullname": "Example Person",
        "follower_count": "70",
        "posts_count": "0",
    }
    with pytest.raises(PublicProfileMetadataError, match="exact handle"):
        parse_threads_profile(body, expected_handle="another_handle")


def test_clubhouse_metadata_uses_first_party_profile_object():
    payload = {
        "props": {
            "pageProps": {
                "metaProps": {
                    "og_canonical_url": "https://www.clubhouse.com/@octaviyao",
                },
                "routeProps": {
                    "user": {
                        "username": "octaviyao",
                        "full_name": "Example Person",
                        "bio": "Public bio\nSecond line",
                        "photo_url": "https://cdn.example/private-id.jpg",
                    },
                    "num_followers": 6,
                    "num_following": 4,
                },
            }
        }
    }
    body = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'

    metadata = parse_clubhouse_profile(body, expected_handle="octaviyao")

    assert metadata.display_fields() == {
        "username": "octaviyao",
        "fullname": "Example Person",
        "bio": "Public bio\nSecond line",
        "follower_count": "6",
        "following_count": "4",
    }
    assert "photo" not in metadata.display_fields()


def test_enrichment_only_adds_verified_fields_to_supported_claimed_profiles():
    check = MaigretSiteCheck(
        site_id="Clubhouse",
        site_name="Clubhouse",
        queried_identifier="alice",
        maigret_id_type="username",
        maigret_status="CLAIMED",
        product_status="found",
        url_main="https://www.clubhouse.com",
        url_user="https://www.clubhouse.com/@alice",
        url_probe="https://www.clubhouse.com/@alice",
        http_status=200,
        rank=10,
        tags=("social",),
        is_similar=False,
        context=None,
        error_type=None,
        error_detail=None,
        extracted_identifiers=(),
        extracted_links=(),
        extracted_fields=(),
    )
    result = MaigretScanResult(
        catalog_snapshot_id="fixture",
        queried_identifier="alice",
        product_identifier_type="handle",
        maigret_id_type="username",
        selected_site_ids=("Clubhouse",),
        status="success",
        cancelled=False,
        site_checks=(check,),
        account_candidates=(
            MaigretAccountCandidate(
                site_id="Clubhouse",
                site_name="Clubhouse",
                url="https://www.clubhouse.com/@alice",
                queried_identifier="alice",
                maigret_id_type="username",
                relationship="exact_handle_result",
            ),
        ),
        extracted_identifiers=(),
        extracted_links=(),
        extracted_fields=(),
        coverage=MaigretCoverage(
            selected=1,
            completed=1,
            claimed=1,
            available=0,
            unknown=0,
            illegal=0,
        ),
    )
    payload = {
        "props": {
            "pageProps": {
                "routeProps": {
                    "user": {
                        "username": "alice",
                        "full_name": "Alice Example",
                        "bio": "Public bio",
                    },
                    "num_followers": 12,
                    "num_following": 3,
                }
            }
        }
    }

    enriched = enrich_first_party_metadata(
        result,
        fetch_html=lambda _url: (
            f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        ),
    )

    fields = {field.name: field.value for field in enriched.site_checks[0].extracted_fields}
    assert fields == {
        "username": "alice",
        "fullname": "Alice Example",
        "bio": "Public bio",
        "follower_count": "12",
        "following_count": "3",
    }

    assert (
        enrich_first_party_metadata(
            result,
            fetch_html=lambda _url: "<html><title>Generic page</title></html>",
        )
        is result
    )

    def network_failure(_url):
        raise httpx.ConnectError("offline")

    assert enrich_first_party_metadata(result, fetch_html=network_failure) is result
