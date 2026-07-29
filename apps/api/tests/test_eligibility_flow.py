import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from apps.api.app.models.entities import (
    EligibilityVerification,
    ProviderRun,
    SearchJob,
    SourceDocument,
    SourceObservation,
)
from apps.api.app.safe_fetch.service import SafeFetchResponse
from apps.api.app.services.provider_runs import process_provider_run


class FakeGitHubGateway:
    def __init__(self) -> None:
        self.bio = ""
        self.account_id = 101
        self.login = "octocat"

    def fetch_github_user(self, username: str) -> SafeFetchResponse:
        assert username == self.login
        payload = {
            "login": self.login,
            "id": self.account_id,
            "html_url": f"https://github.com/{self.login}",
            "type": "User",
            "name": "The Octocat",
            "bio": self.bio,
            "email": "must-not-be-retained@example.test",
            "location": "must-not-be-retained",
            "avatar_url": "https://avatars.example.test/private",
            "followers": 99,
        }
        return SafeFetchResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body=json.dumps(payload).encode(),
        )


def _create_verification(client, auth_headers) -> dict[str, object]:
    response = client.post(
        "/v1/eligibility-verifications",
        headers=auth_headers,
        json={
            "profile_url": "https://GitHub.com/OctoCat/",
            "purpose": "self_audit",
        },
    )
    assert response.status_code == 201
    return response.json()


def _approve(client, settings, verification_id: str):
    return client.post(
        f"/v1/prototype/eligibility-verifications/{verification_id}/decision",
        headers={"X-Prototype-Admin-Token": settings.prototype_admin_token},
        json={
            "decision": "approve",
            "review_code": "adult_public_professional_context_confirmed",
            "reviewer_id": "test-reviewer",
        },
    )


def _search_payload(verification: dict[str, object]) -> dict[str, object]:
    return {
        "profile_url": verification["canonical_profile_url"],
        "purpose": "self_audit",
        "target_relationship": "self",
        "eligibility_reference_id": verification["verification_id"],
        "attestation_policy_version": verification["policy_version"],
        "locale": "en",
    }


def test_control_proof_requires_separate_admin_review_and_minimizes_storage(
    client, app, settings, clock, auth_headers
):
    gateway = FakeGitHubGateway()
    app.state.safe_fetch_factory = lambda: gateway

    created = _create_verification(client, auth_headers)
    challenge = str(created["challenge_value"])
    verification_id = str(created["verification_id"])
    assert created["status"] == "pending_control"
    assert created["canonical_profile_url"] == "https://github.com/octocat"

    with app.state.session_factory() as session:
        stored = session.get(EligibilityVerification, verification_id)
        assert stored is not None
        assert challenge not in str(stored.challenge_token_hmac)
        assert "github.com" not in str(stored.canonical_url_ciphertext)

    blocked = client.post(
        "/v1/search-jobs",
        headers={**auth_headers, "Idempotency-Key": "before-review-key"},
        json=_search_payload(created),
    )
    assert blocked.status_code == 404
    assert blocked.json()["error_code"] == "result_unavailable"

    gateway.bio = f"Testing my profile. {challenge}"
    completed = client.post(
        f"/v1/eligibility-verifications/{verification_id}/complete",
        headers=auth_headers,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "review_pending"
    assert completed.json()["challenge_value"] is None

    still_blocked = client.post(
        "/v1/search-jobs",
        headers={**auth_headers, "Idempotency-Key": "still-before-review"},
        json=_search_payload(created),
    )
    assert still_blocked.status_code == 404

    admin_hidden = client.get(
        f"/v1/prototype/eligibility-verifications/{verification_id}",
    )
    assert admin_hidden.status_code == 401

    approved = _approve(client, settings, verification_id)
    assert approved.status_code == 200
    approved_body = approved.json()
    assert approved_body["status"] == "eligible"
    assert approved_body["eligibility_reference_id"] == verification_id

    created_job = client.post(
        "/v1/search-jobs",
        headers={**auth_headers, "Idempotency-Key": "github-approved-job"},
        json=_search_payload(approved_body),
    )
    assert created_job.status_code == 202
    job_id = created_job.json()["job_id"]

    with app.state.session_factory() as session:
        run_id = session.scalar(select(ProviderRun.id).where(ProviderRun.job_id == job_id))
    assert run_id is not None
    process_provider_run(
        app.state.session_factory,
        settings=settings,
        clock=clock,
        provider_run_id=run_id,
        safe_fetch_gateway=gateway,
    )

    brief = client.get(f"/v1/search-jobs/{job_id}/brief", headers=auth_headers)
    assert brief.status_code == 200
    assert brief.json()["subject"] == "The Octocat"
    assert {claim["predicate"] for claim in brief.json()["claims"]} == {
        "identity.public_display_name",
        "account.verified_input_profile",
    }

    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        observations = session.scalars(
            select(SourceObservation).where(SourceObservation.job_id == job_id)
        ).all()
        assert job is not None
        assert "github.com" not in str(job.canonical_input_url_ciphertext)
        serialized = json.dumps(
            [
                {
                    "excerpt": observation.excerpt,
                    "fields": observation.extracted_fields,
                    "span": observation.span_locator,
                }
                for observation in observations
            ]
        ).casefold()
        assert challenge.casefold() not in serialized
        for prohibited in ("email", "location", "avatar", "followers", "bio"):
            assert prohibited not in serialized

    clock.value += timedelta(hours=settings.eligibility_approval_ttl_hours, seconds=1)
    expired_read = client.get(f"/v1/search-jobs/{job_id}/brief", headers=auth_headers)
    assert expired_read.status_code == 404
    assert expired_read.json()["error_code"] == "result_unavailable"

    deleted = client.delete(f"/v1/search-jobs/{job_id}", headers=auth_headers)
    assert deleted.status_code == 204
    with app.state.session_factory() as session:
        assert session.scalar(select(SourceDocument.id)) is None


def test_stable_github_account_id_mismatch_blocks_persistence(
    client, app, settings, clock, auth_headers
):
    gateway = FakeGitHubGateway()
    app.state.safe_fetch_factory = lambda: gateway
    created = _create_verification(client, auth_headers)
    gateway.bio = str(created["challenge_value"])
    completed = client.post(
        f"/v1/eligibility-verifications/{created['verification_id']}/complete",
        headers=auth_headers,
    )
    assert completed.status_code == 200
    approved = _approve(client, settings, str(created["verification_id"]))
    assert approved.status_code == 200

    job_response = client.post(
        "/v1/search-jobs",
        headers={**auth_headers, "Idempotency-Key": "reassigned-account-job"},
        json=_search_payload(approved.json()),
    )
    assert job_response.status_code == 202
    job_id = job_response.json()["job_id"]
    gateway.account_id = 202

    with app.state.session_factory() as session:
        run_id = session.scalar(select(ProviderRun.id).where(ProviderRun.job_id == job_id))
    assert run_id is not None
    process_provider_run(
        app.state.session_factory,
        settings=settings,
        clock=clock,
        provider_run_id=run_id,
        safe_fetch_gateway=gateway,
    )

    status = client.get(f"/v1/search-jobs/{job_id}", headers=auth_headers)
    assert status.status_code == 200
    assert status.json()["status"] == "result_unavailable"
    with app.state.session_factory() as session:
        assert (
            session.scalar(select(SourceObservation.id).where(SourceObservation.job_id == job_id))
            is None
        )


def test_verification_is_owner_scoped_and_wrong_bio_remains_pending(client, app, auth_headers):
    gateway = FakeGitHubGateway()
    app.state.safe_fetch_factory = lambda: gateway
    created = _create_verification(client, auth_headers)
    verification_id = str(created["verification_id"])
    other_headers = {
        **auth_headers,
        "X-Prototype-User": str(uuid4()),
    }

    hidden = client.get(
        f"/v1/eligibility-verifications/{verification_id}",
        headers=other_headers,
    )
    assert hidden.status_code == 404

    status = client.get(
        f"/v1/eligibility-verifications/{verification_id}",
        headers=auth_headers,
    )
    assert status.status_code == 200
    assert status.json()["challenge_value"] is None

    gateway.bio = "No matching control token is present."
    wrong = client.post(
        f"/v1/eligibility-verifications/{verification_id}/complete",
        headers=auth_headers,
    )
    assert wrong.status_code == 200
    assert wrong.json()["status"] == "pending_control"
    assert wrong.json()["attempts_remaining"] == 4
