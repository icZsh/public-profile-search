from uuid import uuid4

from sqlalchemy import select

from apps.api.app.models.entities import (
    JobDeletionTombstone,
    OutboxMessage,
    ProviderRun,
    SearchJob,
    SourceObservation,
)
from apps.api.app.services.provider_runs import process_provider_run


def create_job(client, auth_headers, create_payload, key="prototype-key-0001"):
    return client.post(
        "/v1/search-jobs",
        headers={**auth_headers, "Idempotency-Key": key},
        json=create_payload,
    )


def run_all_provider_tasks(app, settings, clock, job_id: str) -> None:
    factory = app.state.session_factory
    processed: set[str] = set()
    while True:
        with factory() as session:
            run_ids = session.scalars(
                select(ProviderRun.id).where(
                    ProviderRun.job_id == job_id,
                    ProviderRun.status == "pending",
                )
            ).all()
        pending = [run_id for run_id in run_ids if run_id not in processed]
        if not pending:
            return
        for run_id in pending:
            process_provider_run(
                factory,
                settings=settings,
                clock=clock,
                provider_run_id=run_id,
            )
            processed.add(run_id)


def test_vertical_slice_produces_deterministic_brief(
    client, app, settings, clock, auth_headers, create_payload
):
    response = create_job(client, auth_headers, create_payload)
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert response.json()["status"] == "queued"

    with app.state.session_factory() as session:
        assert session.scalar(select(OutboxMessage.id)) is not None

    run_all_provider_tasks(app, settings, clock, job_id)

    status = client.get(f"/v1/search-jobs/{job_id}", headers=auth_headers)
    assert status.status_code == 200
    assert status.json()["status"] == "complete"

    brief = client.get(f"/v1/search-jobs/{job_id}/brief", headers=auth_headers)
    assert brief.status_code == 200
    assert brief.json()["subject"] == "Alex Chen"
    assert {claim["predicate"] for claim in brief.json()["claims"]} == {
        "identity.public_display_name",
        "account.explicitly_linked_public_profile",
    }

    evidence = client.get(f"/v1/search-jobs/{job_id}/evidence", headers=auth_headers)
    assert evidence.status_code == 200
    assert len(evidence.json()["items"]) == 2
    assert all(".example.test/" in item["url"] for item in evidence.json()["items"])


def test_idempotency_returns_same_job_and_rejects_changed_payload(
    client, auth_headers, create_payload
):
    first = create_job(client, auth_headers, create_payload, key="same-request-key")
    second = create_job(client, auth_headers, create_payload, key="same-request-key")
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]

    changed = {**create_payload, "locale": "zh-CN"}
    conflict = create_job(client, auth_headers, changed, key="same-request-key")
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "idempotency_conflict"


def test_owner_isolation_hides_job(client, auth_headers, create_payload):
    created = create_job(client, auth_headers, create_payload)
    job_id = created.json()["job_id"]
    other_headers = {
        **auth_headers,
        "X-Prototype-User": str(uuid4()),
    }
    hidden = client.get(f"/v1/search-jobs/{job_id}", headers=other_headers)
    assert hidden.status_code == 404
    assert hidden.json()["error_code"] == "job_not_found"


def test_delete_removes_job_data_and_leaves_write_fence(
    client, app, settings, clock, auth_headers, create_payload
):
    created = create_job(client, auth_headers, create_payload)
    job_id = created.json()["job_id"]
    run_all_provider_tasks(app, settings, clock, job_id)

    deleted = client.delete(f"/v1/search-jobs/{job_id}", headers=auth_headers)
    assert deleted.status_code == 204

    with app.state.session_factory() as session:
        assert session.get(SearchJob, job_id) is None
        assert session.get(JobDeletionTombstone, job_id) is not None
        assert (
            session.scalar(select(SourceObservation.id).where(SourceObservation.job_id == job_id))
            is None
        )
    assert client.get(f"/v1/search-jobs/{job_id}", headers=auth_headers).status_code == 404


def test_suppression_revokes_existing_report_and_blocks_new_job(
    client, app, settings, clock, auth_headers, create_payload
):
    created = create_job(client, auth_headers, create_payload)
    job_id = created.json()["job_id"]
    run_all_provider_tasks(app, settings, clock, job_id)

    suppressed = client.post(
        "/v1/prototype/suppressions",
        headers={"X-Prototype-Admin-Token": settings.prototype_admin_token},
        json={"profile_url": settings.fixture_url},
    )
    assert suppressed.status_code == 204
    assert client.get(f"/v1/search-jobs/{job_id}/brief", headers=auth_headers).status_code == 404

    blocked = create_job(
        client,
        auth_headers,
        create_payload,
        key="post-suppression-key",
    )
    assert blocked.status_code == 404
    assert blocked.json()["error_code"] == "result_unavailable"
