from datetime import timedelta
from uuid import uuid4

from apps.api.app.models.entities import (
    AccountNode,
    JobAttempt,
    JobDeletionTombstone,
    SearchJob,
    new_id,
)
from apps.api.tests.test_footprint_discovery import seed_footprint_report


def _create_job(
    client,
    headers,
    *,
    identifier: str,
    key: str,
    search_mode: str = "quick",
    platform: str | None = None,
) -> str:
    seed = (
        {
            "kind": "platform_identifier",
            "platform": platform,
            "identifier_type": "handle",
            "identifier": identifier,
        }
        if platform
        else {
            "kind": "bare_handle",
            "identifier_type": "handle",
            "identifier": identifier,
        }
    )
    response = client.post(
        "/v1/footprint-jobs",
        headers={**headers, "Idempotency-Key": key},
        json={
            "seed": seed,
            "search_mode": search_mode,
            "locale": "en-US",
            "history_policy": "new_job",
        },
    )
    assert response.status_code == 202
    return str(response.json()["job_id"])


def test_history_groups_handle_across_modes_with_stable_pagination(
    client,
    app,
    clock,
    auth_headers,
):
    alice_quick = _create_job(
        client,
        auth_headers,
        identifier="Alice",
        key="history-alice-quick",
    )
    clock.value += timedelta(minutes=1)
    alice_deep = _create_job(
        client,
        auth_headers,
        identifier="alice",
        key="history-alice-deep",
        search_mode="deep",
    )
    clock.value += timedelta(minutes=1)
    bob = _create_job(
        client,
        auth_headers,
        identifier="bob",
        key="history-bob-quick",
        platform="github",
    )

    first = client.get("/v1/footprint-jobs?limit=1", headers=auth_headers)
    assert first.status_code == 200
    first_body = first.json()
    assert [item["representative_job_id"] for item in first_body["items"]] == [bob]
    assert first_body["next_cursor"]

    second = client.get(
        "/v1/footprint-jobs",
        headers=auth_headers,
        params={"limit": 1, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200
    group = second.json()["items"][0]
    assert group["representative_job_id"] == alice_deep
    assert group["seed"] == {
        "kind": "bare_handle",
        "platform": None,
        "identifier": "alice",
    }
    assert group["run_count"] == 2
    assert group["latest_run"]["job_id"] == alice_deep
    assert second.json()["next_cursor"] is None

    filtered = client.get("/v1/footprint-jobs?q=ALIC", headers=auth_headers)
    assert filtered.status_code == 200
    assert [item["representative_job_id"] for item in filtered.json()["items"]] == [
        alice_deep
    ]

    related = client.get(
        f"/v1/footprint-jobs/{alice_quick}/history?limit=1",
        headers=auth_headers,
    )
    assert related.status_code == 200
    assert related.json()["items"][0]["job_id"] == alice_deep
    assert related.json()["next_cursor"]
    related_next = client.get(
        f"/v1/footprint-jobs/{alice_quick}/history",
        headers=auth_headers,
        params={"cursor": related.json()["next_cursor"]},
    )
    assert related_next.status_code == 200
    assert [item["job_id"] for item in related_next.json()["items"]] == [alice_quick]

    with app.state.session_factory() as session:
        assert session.get(SearchJob, bob) is not None


def test_history_groups_same_handle_across_seed_types_and_platforms(
    client,
    clock,
    auth_headers,
):
    profile_url = client.post(
        "/v1/footprint-jobs",
        headers={**auth_headers, "Idempotency-Key": "history-profile-url"},
        json={
            "seed": {
                "kind": "profile_url",
                "profile_url": "https://www.instagram.com/Octaviyao/",
            },
            "search_mode": "quick",
            "locale": "en-US",
            "history_policy": "new_job",
        },
    )
    assert profile_url.status_code == 202
    clock.value += timedelta(minutes=1)
    platform_job_id = _create_job(
        client,
        auth_headers,
        identifier="octaviyao",
        key="history-platform-handle",
        platform="instagram",
    )
    clock.value += timedelta(minutes=1)
    other_platform_job_id = _create_job(
        client,
        auth_headers,
        identifier="Octaviyao",
        key="history-other-platform-handle",
        platform="github",
    )
    clock.value += timedelta(minutes=1)
    bare_job_id = _create_job(
        client,
        auth_headers,
        identifier="OCTAVIYAO",
        key="history-bare-handle",
    )

    response = client.get("/v1/footprint-jobs?q=@OCTAVI", headers=auth_headers)
    assert response.status_code == 200
    groups = response.json()["items"]
    assert len(groups) == 1
    group = groups[0]
    assert group["representative_job_id"] == bare_job_id
    assert group["run_count"] == 4
    assert group["seed"] == {
        "kind": "bare_handle",
        "platform": None,
        "identifier": "OCTAVIYAO",
    }

    related = client.get(
        f"/v1/footprint-jobs/{platform_job_id}/history",
        headers=auth_headers,
    )
    assert related.status_code == 200
    assert [item["job_id"] for item in related.json()["items"]] == [
        bare_job_id,
        other_platform_job_id,
        platform_job_id,
        str(profile_url.json()["job_id"]),
    ]


def test_history_is_owner_scoped_and_excludes_expired_jobs(
    client,
    app,
    clock,
    auth_headers,
):
    owner_job_id = _create_job(
        client,
        auth_headers,
        identifier="owner-only",
        key="history-owner-only",
    )
    other_headers = {
        **auth_headers,
        "X-Prototype-User": str(uuid4()),
    }
    other_job_id = _create_job(
        client,
        other_headers,
        identifier="other-only",
        key="history-other-only",
    )
    with app.state.session_factory() as session, session.begin():
        owner_job = session.get(SearchJob, owner_job_id)
        assert owner_job is not None
        owner_job.expires_at = clock.now()

    owner_history = client.get("/v1/footprint-jobs", headers=auth_headers)
    assert owner_history.status_code == 200
    assert owner_history.json()["items"] == []
    expired_related = client.get(
        f"/v1/footprint-jobs/{owner_job_id}/history",
        headers=auth_headers,
    )
    assert expired_related.status_code == 404

    other_history = client.get("/v1/footprint-jobs", headers=other_headers)
    assert other_history.status_code == 200
    assert [item["representative_job_id"] for item in other_history.json()["items"]] == [
        other_job_id
    ]


def test_history_summary_reports_candidate_and_active_result_availability(
    client,
    app,
    clock,
    auth_headers,
):
    job_id = _create_job(
        client,
        auth_headers,
        identifier="available-result",
        key="history-available-result",
        platform="github",
    )
    seed_footprint_report(app, clock, job_id=job_id)
    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        attempt = session.get(JobAttempt, job.active_attempt_id)
        assert attempt is not None
        attempt.finished_at = clock.now()
        job.status = "no_candidates"
        session.add(
            AccountNode(
                id=new_id(),
                job_id=job.id,
                platform="github",
                canonical_handle="available-result",
                canonical_url="https://github.com/available-result",
                display_name=None,
                identity_confidence_tier="possible",
                selection_state="undecided",
                is_similar=False,
                profile_data={},
                first_observed_at=clock.now(),
                last_observed_at=clock.now(),
            )
        )

    response = client.get("/v1/footprint-jobs", headers=auth_headers)
    assert response.status_code == 200
    run = response.json()["items"][0]["latest_run"]
    assert run["candidate_count"] == 1
    assert run["result_available"] is True
    assert run["finished_at"] == clock.now().replace(tzinfo=None).isoformat()


def test_clear_history_deletes_only_terminal_jobs_and_nulls_refresh_lineage(
    client,
    app,
    clock,
    auth_headers,
):
    source_id = _create_job(
        client,
        auth_headers,
        identifier="refreshable",
        key="history-refresh-source",
    )
    clock.value += timedelta(minutes=1)
    child_id = _create_job(
        client,
        auth_headers,
        identifier="refreshable",
        key="history-refresh-child",
    )
    with app.state.session_factory() as session, session.begin():
        source = session.get(SearchJob, source_id)
        child = session.get(SearchJob, child_id)
        assert source is not None and child is not None
        source.status = "ready"
        child.refresh_of_job_id = source.id
        child.history_reuse_policy = "history-hints-v1"

    cleared = client.delete("/v1/footprint-jobs", headers=auth_headers)
    assert cleared.status_code == 200
    assert cleared.json() == {"deleted_count": 1, "has_more": False}

    with app.state.session_factory() as session:
        assert session.get(SearchJob, source_id) is None
        child = session.get(SearchJob, child_id)
        assert child is not None
        assert child.refresh_of_job_id is None
        assert session.get(JobDeletionTombstone, source_id) is not None


def test_clear_history_is_bounded_and_cursor_validation_is_safe(
    client,
    app,
    auth_headers,
):
    first_id = _create_job(
        client,
        auth_headers,
        identifier="terminal-one",
        key="history-terminal-one",
    )
    second_id = _create_job(
        client,
        auth_headers,
        identifier="terminal-two",
        key="history-terminal-two",
    )
    with app.state.session_factory() as session, session.begin():
        first = session.get(SearchJob, first_id)
        second = session.get(SearchJob, second_id)
        assert first is not None and second is not None
        first.status = "failed"
        second.status = "cancelled"

    cleared = client.delete("/v1/footprint-jobs?limit=1", headers=auth_headers)
    assert cleared.status_code == 200
    assert cleared.json() == {"deleted_count": 1, "has_more": True}
    cleared_again = client.delete("/v1/footprint-jobs?limit=1", headers=auth_headers)
    assert cleared_again.status_code == 200
    assert cleared_again.json() == {"deleted_count": 1, "has_more": False}
    assert client.delete("/v1/footprint-jobs?limit=51", headers=auth_headers).status_code == 422

    invalid_cursor = client.get(
        "/v1/footprint-jobs?cursor=not-a-valid-cursor",
        headers=auth_headers,
    )
    assert invalid_cursor.status_code == 422
