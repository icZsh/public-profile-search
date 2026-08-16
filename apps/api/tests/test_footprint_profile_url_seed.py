import pytest
from sqlalchemy import select

from apps.api.app.core.crypto import decrypt_value
from apps.api.app.models.entities import MaigretScanRun, ProviderRun, SearchJob


def create_profile_url_job(
    client,
    auth_headers,
    *,
    key: str,
    profile_url: str,
    **seed_assertions: str,
):
    return client.post(
        "/v1/footprint-jobs",
        headers={**auth_headers, "Idempotency-Key": key},
        json={
            "seed": {
                "kind": "profile_url",
                "profile_url": profile_url,
                **seed_assertions,
            },
            "search_mode": "quick",
            "locale": "en-US",
        },
    )


@pytest.mark.parametrize(
    ("profile_url", "platform", "handle", "canonical_url"),
    [
        (
            "https://WWW.GitHub.com/OctoCat/",
            "github",
            "octocat",
            "https://github.com/octocat",
        ),
        (
            "https://www.instagram.com/Octaviyao/",
            "instagram",
            "octaviyao",
            "https://instagram.com/octaviyao",
        ),
        (
            "https://www.linkedin.com/in/Raymond-Gu-123/",
            "linkedin",
            "raymond-gu-123",
            "https://linkedin.com/in/raymond-gu-123",
        ),
        (
            "https://www.reddit.com/u/Test_User/",
            "reddit",
            "test_user",
            "https://reddit.com/user/test_user",
        ),
        (
            "https://www.tiktok.com/@Octaviyao/",
            "tiktok",
            "octaviyao",
            "https://tiktok.com/@octaviyao",
        ),
        (
            "https://twitter.com/Octaviyao/",
            "x",
            "octaviyao",
            "https://x.com/octaviyao",
        ),
        (
            "https://www.youtube.com/@Octaviyao/",
            "youtube",
            "octaviyao",
            "https://youtube.com/@octaviyao",
        ),
    ],
)
def test_profile_url_seed_infers_normalizes_and_persists_equivalent_handle(
    client,
    app,
    settings,
    auth_headers,
    profile_url: str,
    platform: str,
    handle: str,
    canonical_url: str,
):
    response = create_profile_url_job(
        client,
        auth_headers,
        key=f"profile-url-{platform}-{handle}",
        profile_url=profile_url,
    )

    assert response.status_code == 202
    body = response.json()
    assert body["seed"] == {
        "kind": "profile_url",
        "profile_url": canonical_url,
        "platform": platform,
        "identifier_type": "handle",
        "identifier": handle,
    }

    with app.state.session_factory() as session:
        job = session.get(SearchJob, body["job_id"])
        assert job is not None
        assert job.seed_kind == "profile_url"
        assert job.seed_platform == platform
        assert job.seed_identifier_type == "handle"
        assert job.seed_identifier == handle
        assert job.normalized_seed == f"{platform}:handle:{handle}"
        assert job.canonicalization_version == "footprint-profile-url-v1"
        assert job.canonical_input_url_ciphertext is not None
        assert canonical_url not in job.canonical_input_url_ciphertext
        assert (
            decrypt_value(
                job.canonical_input_url_ciphertext,
                settings.profile_url_encryption_key,
            )
            == canonical_url
        )
        scan_identifiers = session.scalars(
            select(MaigretScanRun.identifier_value)
            .join(ProviderRun, ProviderRun.id == MaigretScanRun.provider_run_id)
            .where(ProviderRun.job_id == job.id)
        ).all()
        assert scan_identifiers
        assert set(scan_identifiers) == {handle}

    retrieved = client.get(
        f"/v1/footprint-jobs/{body['job_id']}",
        headers=auth_headers,
    )
    assert retrieved.status_code == 200
    assert retrieved.json()["seed"] == body["seed"]


def test_profile_url_seed_accepts_matching_optional_normalized_assertions(
    client,
    auth_headers,
):
    response = create_profile_url_job(
        client,
        auth_headers,
        key="profile-url-matching-assertions",
        profile_url="https://twitter.com/Octaviyao/",
        platform="twitter",
        identifier_type="handle",
        identifier="@Octaviyao",
    )

    assert response.status_code == 202
    assert response.json()["seed"] == {
        "kind": "profile_url",
        "profile_url": "https://x.com/octaviyao",
        "platform": "x",
        "identifier_type": "handle",
        "identifier": "octaviyao",
    }


@pytest.mark.parametrize(
    "seed_assertions",
    [
        {"platform": "github"},
        {"identifier": "someone_else"},
    ],
)
def test_profile_url_seed_rejects_conflicting_normalized_assertions(
    client,
    auth_headers,
    seed_assertions: dict[str, str],
):
    response = create_profile_url_job(
        client,
        auth_headers,
        key=f"profile-url-conflict-{next(iter(seed_assertions))}",
        profile_url="https://www.instagram.com/octaviyao/",
        **seed_assertions,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_request"


@pytest.mark.parametrize(
    "profile_url",
    [
        "http://github.com/octocat",
        "https://github.com.evil.example/octocat",
        "https://user@github.com/octocat",
        "https://github.com:443/octocat",
        "https://github.com/octocat?tab=repositories",
        "https://github.com/octocat#bio",
        "https://github.com/octocat%2Frepositories",
        "https://github.com/octocat/repositories",
        "https://instagram.com/octaviyao/tagged",
        "https://example.com/octaviyao",
    ],
)
def test_profile_url_seed_rejects_unsafe_or_unsupported_urls(
    client,
    auth_headers,
    profile_url: str,
):
    response = create_profile_url_job(
        client,
        auth_headers,
        key=f"profile-url-invalid-{abs(hash(profile_url))}",
        profile_url=profile_url,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_request"


def test_equivalent_profile_urls_share_the_idempotency_payload(
    client,
    auth_headers,
):
    first = create_profile_url_job(
        client,
        auth_headers,
        key="profile-url-equivalent-idempotency",
        profile_url="https://WWW.INSTAGRAM.com/Octaviyao/",
    )
    second = create_profile_url_job(
        client,
        auth_headers,
        key="profile-url-equivalent-idempotency",
        profile_url="https://instagram.com/octaviyao",
    )

    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]
