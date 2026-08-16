from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from apps.api.app.models.entities import (
    AccountNode,
    DiscoveryEdge,
    JobAttempt,
    MaigretSiteCheck,
    OutboxMessage,
    ProviderRun,
    ReportAccessState,
    SearchJob,
    SourceObservation,
    new_id,
)
from apps.api.app.services.deep_models import DEFAULT_DEEP_SYNTHESIS_MODEL
from apps.api.app.services.professional_search_scheduling import (
    GITHUB_PROFESSIONAL_PROVIDER_ID,
    schedule_professional_search_if_ready,
)
from apps.api.tests.test_footprint_discovery import seed_footprint_report


def _job_payload(
    *,
    identifier: str,
    search_mode: str = "quick",
    synthesis_model: str | None = None,
    locale: str = "en-US",
    history_policy: str = "new_job",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "seed": {
            "kind": "platform_identifier",
            "platform": "github",
            "identifier_type": "handle",
            "identifier": identifier,
        },
        "search_mode": search_mode,
        "locale": locale,
        "history_policy": history_policy,
    }
    if synthesis_model is not None:
        payload["synthesis_model"] = synthesis_model
    return payload


def _create_job(client, headers, *, key: str, **payload_options):
    return client.post(
        "/v1/footprint-jobs",
        headers={**headers, "Idempotency-Key": key},
        json=_job_payload(**payload_options),
    )


def _add_positive_site(app, clock, *, job_id: str, site_name: str) -> None:
    with app.state.session_factory() as session, session.begin():
        run = session.scalar(
            select(ProviderRun)
            .where(ProviderRun.job_id == job_id)
            .order_by(ProviderRun.logical_run_id)
        )
        assert run is not None
        session.add(
            MaigretSiteCheck(
                id=new_id(),
                job_id=job_id,
                provider_run_id=run.id,
                site_key=site_name.casefold(),
                site_name=site_name,
                source_name=None,
                queried_identifier="history-handle",
                queried_identifier_type="username",
                url_main=f"https://{site_name.casefold()}.example",
                url_user=f"https://{site_name.casefold()}.example/history-handle",
                url_probe=f"https://{site_name.casefold()}.example/history-handle",
                raw_status="CLAIMED",
                normalized_status="found",
                error_type=None,
                error_context=None,
                http_status=200,
                is_similar=False,
                rank=1,
                tags=["social"],
                extracted_data={"display_name": "Historical Name Must Be Revalidated"},
                extracted_usernames={"username": "history-handle"},
                extracted_links=[],
                result_checksum="a" * 64,
                observed_at=clock.now(),
            )
        )
        session.add(
            AccountNode(
                id=new_id(),
                job_id=job_id,
                platform=site_name.casefold(),
                canonical_handle="history-handle",
                canonical_url=f"https://{site_name.casefold()}.example/history-handle",
                display_name="Historical Name Must Be Revalidated",
                identity_confidence_tier="possible",
                selection_state="undecided",
                is_similar=False,
                profile_data={},
                first_observed_at=clock.now(),
                last_observed_at=clock.now(),
            )
        )


def _add_current_name_check(
    session,
    *,
    job: SearchJob,
    run: ProviderRun,
    clock,
    platform: str,
    display_name: str,
    ordinal: int,
) -> str:
    platform_urls = {
        "GitHub": f"https://github.com/{job.seed_identifier}",
        "Pinterest": f"https://www.pinterest.com/{job.seed_identifier}",
    }
    check_id = new_id()
    node_id = new_id()
    profile_url = platform_urls[platform]
    session.add(
        MaigretSiteCheck(
            id=check_id,
            job_id=job.id,
            provider_run_id=run.id,
            site_key=f"fresh-{platform.casefold()}",
            site_name=platform,
            source_name=None,
            queried_identifier=job.seed_identifier or "",
            queried_identifier_type="username",
            url_main=profile_url.rsplit("/", 1)[0],
            url_user=profile_url,
            url_probe=profile_url,
            raw_status="CLAIMED",
            normalized_status="found",
            error_type=None,
            error_context=None,
            http_status=200,
            is_similar=False,
            rank=ordinal,
            tags=["social"],
            extracted_data={
                "username": job.seed_identifier,
                "full_name": display_name,
            },
            extracted_usernames={},
            extracted_links=[],
            result_checksum=f"{ordinal:064x}",
            observed_at=clock.now() + timedelta(seconds=ordinal),
        )
    )
    session.add(
        AccountNode(
            id=node_id,
            job_id=job.id,
            platform=platform,
            canonical_handle=job.seed_identifier or "",
            canonical_url=profile_url,
            display_name=display_name,
            identity_confidence_tier="possible",
            selection_state="undecided",
            is_similar=False,
            profile_data={},
            first_observed_at=clock.now(),
            last_observed_at=clock.now(),
        )
    )
    session.flush()
    session.add(
        DiscoveryEdge(
            id=new_id(),
            job_id=job.id,
            provider_run_id=run.id,
            site_check_id=check_id,
            source_observation_id=None,
            child_account_node_id=node_id,
            parent_seed=job.normalized_seed or "",
            discovery_method="username_catalog_probe",
            discovery_engine="maigret",
            depth=0,
            created_at=clock.now(),
        )
    )
    return node_id


def test_prefer_existing_returns_200_only_for_exact_mode_model_and_locale(
    client,
    auth_headers,
):
    source = _create_job(
        client,
        auth_headers,
        key="history-exact-source",
        identifier="exact-settings",
        search_mode="deep",
        synthesis_model=DEFAULT_DEEP_SYNTHESIS_MODEL,
    )
    assert source.status_code == 202
    source_id = source.json()["job_id"]

    exact = _create_job(
        client,
        auth_headers,
        key="history-exact-reopen",
        identifier="exact-settings",
        search_mode="deep",
        synthesis_model=DEFAULT_DEEP_SYNTHESIS_MODEL,
        history_policy="prefer_existing",
    )
    assert exact.status_code == 200
    assert exact.json()["job_id"] == source_id

    variants = (
        {
            "key": "history-exact-mode",
            "search_mode": "quick",
        },
        {
            "key": "history-exact-model",
            "search_mode": "deep",
        },
        {
            "key": "history-exact-locale",
            "search_mode": "deep",
            "synthesis_model": DEFAULT_DEEP_SYNTHESIS_MODEL,
            "locale": "zh-CN",
        },
    )
    created_ids = set()
    for variant in variants:
        key = str(variant.pop("key"))
        response = _create_job(
            client,
            auth_headers,
            key=key,
            identifier="exact-settings",
            history_policy="prefer_existing",
            **variant,
        )
        assert response.status_code == 202
        assert response.json()["job_id"] != source_id
        created_ids.add(response.json()["job_id"])
    assert len(created_ids) == len(variants)

    explicitly_new = _create_job(
        client,
        auth_headers,
        key="history-exact-force-new",
        identifier="exact-settings",
        search_mode="deep",
        synthesis_model=DEFAULT_DEEP_SYNTHESIS_MODEL,
        history_policy="new_job",
    )
    assert explicitly_new.status_code == 202
    assert explicitly_new.json()["job_id"] != source_id


def test_prefer_existing_reopens_an_accessible_saved_result(
    client,
    app,
    clock,
    auth_headers,
):
    source = _create_job(
        client,
        auth_headers,
        key="history-saved-source",
        identifier="saved-result",
    )
    assert source.status_code == 202
    source_id = source.json()["job_id"]
    seed_footprint_report(app, clock, job_id=source_id)

    reopened = _create_job(
        client,
        auth_headers,
        key="history-saved-reopen",
        identifier="saved-result",
        history_policy="prefer_existing",
    )
    assert reopened.status_code == 200
    assert reopened.json()["job_id"] == source_id


def test_refresh_preserves_user_choices_and_uses_current_runtime_settings(
    client,
    app,
    clock,
    settings,
    auth_headers,
):
    source = _create_job(
        client,
        auth_headers,
        key="history-refresh-settings-source",
        identifier="refresh-settings",
        search_mode="deep",
        synthesis_model=DEFAULT_DEEP_SYNTHESIS_MODEL,
        locale="zh-CN",
    )
    assert source.status_code == 202
    source_id = source.json()["job_id"]
    with app.state.session_factory() as session, session.begin():
        source_job = session.get(SearchJob, source_id)
        assert source_job is not None
        source_job.input_provider_id = "retired-provider"
        source_job.catalog_profile = "retired-profile"
        source_job.catalog_snapshot_id = None
        source_job.policy_version = "retired-policy"

    settings.policy_version = "current-policy"
    settings.retention_days = 17
    refreshed = client.post(
        f"/v1/footprint-jobs/{source_id}/refresh",
        headers={**auth_headers, "Idempotency-Key": "history-refresh-settings"},
    )
    assert refreshed.status_code == 202
    body = refreshed.json()
    assert body["job_id"] != source_id
    assert body["refresh_of_job_id"] == source_id
    assert body["seed"] == source.json()["seed"]
    assert body["search_mode"] == "deep"
    assert body["synthesis_model"] == DEFAULT_DEEP_SYNTHESIS_MODEL

    with app.state.session_factory() as session:
        job = session.get(SearchJob, body["job_id"])
        assert job is not None
        assert job.locale == "zh-CN"
        assert job.refresh_of_job_id == source_id
        assert job.input_provider_id == "maigret_discovery_v1"
        assert job.catalog_profile == "deep"
        assert job.catalog_snapshot_id is not None
        assert job.policy_version == "current-policy"
        assert job.expires_at.replace(tzinfo=clock.now().tzinfo) == clock.now() + timedelta(
            days=17
        )

    replay = client.post(
        f"/v1/footprint-jobs/{source_id}/refresh",
        headers={**auth_headers, "Idempotency-Key": "history-refresh-settings"},
    )
    assert replay.status_code == 202
    assert replay.json()["job_id"] == body["job_id"]


def test_refresh_prioritizes_positive_current_catalog_sites_without_copying_evidence(
    client,
    app,
    clock,
    auth_headers,
):
    source = _create_job(
        client,
        auth_headers,
        key="history-hints-source",
        identifier="history-handle",
    )
    assert source.status_code == 202
    source_id = source.json()["job_id"]
    seed_footprint_report(app, clock, job_id=source_id)
    _add_positive_site(app, clock, job_id=source_id, site_name="Clubhouse")

    refreshed = client.post(
        f"/v1/footprint-jobs/{source_id}/refresh",
        headers={**auth_headers, "Idempotency-Key": "history-hints-refresh"},
    )
    assert refreshed.status_code == 202
    refresh_id = refreshed.json()["job_id"]

    with app.state.session_factory() as session:
        job = session.get(SearchJob, refresh_id)
        runs = session.scalars(
            select(ProviderRun)
            .where(ProviderRun.job_id == refresh_id)
            .order_by(ProviderRun.logical_run_id)
        ).all()
        assert job is not None and runs
        assert job.history_reuse_policy == "planner_hints_revalidated_v1"
        assert runs[0].query_config["site_names"][0] == "Clubhouse"
        assert runs[0].query_config["history_revalidation"] is True
        assert runs[0].query_config["history_positive_site_count"] == 1

        priorities = {
            str(message.payload["provider_run_id"]): message.priority
            for message in session.scalars(select(OutboxMessage)).all()
            if message.payload.get("provider_run_id") in {run.id for run in runs}
        }
        assert priorities[runs[0].id] == 9
        assert all(priorities[run.id] == 0 for run in runs[1:])
        assert (
            session.scalar(
                select(SourceObservation).where(SourceObservation.job_id == refresh_id)
            )
            is None
        )
        assert (
            session.scalar(
                select(MaigretSiteCheck).where(MaigretSiteCheck.job_id == refresh_id)
            )
            is None
        )


def test_professional_history_hints_only_prioritize_names_seen_again_freshly(
    client,
    app,
    clock,
    auth_headers,
):
    source = _create_job(
        client,
        auth_headers,
        key="history-professional-source",
        identifier="professional-hints",
        search_mode="deep",
    )
    assert source.status_code == 202
    source_id = source.json()["job_id"]
    seed_footprint_report(app, clock, job_id=source_id)
    with app.state.session_factory() as session, session.begin():
        session.add(
            AccountNode(
                id=new_id(),
                job_id=source_id,
                platform="github",
                canonical_handle="bob-prior",
                canonical_url="https://github.com/bob-prior",
                display_name="Bob Example",
                identity_confidence_tier="possible",
                selection_state="included",
                is_similar=False,
                profile_data={
                    "professional_sources": {
                        GITHUB_PROFESSIONAL_PROVIDER_ID: {"name": "Bob Example"}
                    }
                },
                first_observed_at=clock.now(),
                last_observed_at=clock.now(),
            )
        )

    refreshed = client.post(
        f"/v1/footprint-jobs/{source_id}/refresh",
        headers={
            **auth_headers,
            "Idempotency-Key": "history-professional-refresh",
        },
    )
    assert refreshed.status_code == 202
    refresh_id = refreshed.json()["job_id"]

    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, refresh_id)
        assert job is not None
        roots = session.scalars(
            select(ProviderRun)
            .where(ProviderRun.job_id == refresh_id)
            .order_by(ProviderRun.logical_run_id)
        ).all()
        assert roots
        for root in roots:
            root.status = "success"
        alice_node_id = _add_current_name_check(
            session,
            job=job,
            run=roots[0],
            clock=clock,
            platform="GitHub",
            display_name="Alice Example",
            ordinal=1,
        )
        bob_node_id = _add_current_name_check(
            session,
            job=job,
            run=roots[0],
            clock=clock,
            platform="Pinterest",
            display_name="Bob Example",
            ordinal=2,
        )
        assert schedule_professional_search_if_ready(
            session,
            job=job,
            now=clock.now(),
            settings=SimpleNamespace(
                professional_search_enabled=True,
                exa_people_search_enabled=False,
                github_people_search_enabled=True,
                github_provider_enabled=True,
            ),
        )

    with app.state.session_factory() as session:
        runs = session.scalars(
            select(ProviderRun)
            .where(
                ProviderRun.job_id == refresh_id,
                ProviderRun.provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID,
            )
            .order_by(ProviderRun.logical_run_id)
        ).all()
        assert len(runs) == 2
        assert runs[0].query_config["full_name"] == "Bob Example"
        assert runs[0].query_config["history_revalidation"] is True
        assert runs[0].query_config["candidate_logins"][0] == "bob-prior"
        assert runs[0].query_config["name_source_node_ids"] == [bob_node_id]
        assert runs[1].query_config["full_name"] == "Alice Example"
        assert "history_revalidation" not in runs[1].query_config
        assert runs[1].query_config["name_source_node_ids"] == [alice_node_id]
        refresh_handles = set(
            session.scalars(
                select(AccountNode.canonical_handle).where(
                    AccountNode.job_id == refresh_id
                )
            ).all()
        )
        assert "bob-prior" not in refresh_handles


@pytest.mark.parametrize(
    ("source_status", "revoke_report"),
    (("no_candidates", False), ("failed", False), ("ready", True)),
)
def test_refresh_does_not_use_hints_from_ineligible_history(
    client,
    app,
    clock,
    auth_headers,
    source_status,
    revoke_report,
):
    suffix = f"{source_status}-{'revoked' if revoke_report else 'active'}"
    source = _create_job(
        client,
        auth_headers,
        key=f"history-ineligible-source-{suffix}",
        identifier="history-handle",
    )
    assert source.status_code == 202
    source_id = source.json()["job_id"]
    seed_footprint_report(app, clock, job_id=source_id)
    _add_positive_site(app, clock, job_id=source_id, site_name="Clubhouse")
    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, source_id)
        assert job is not None
        job.status = source_status
        if revoke_report:
            attempt = session.get(JobAttempt, job.active_attempt_id)
            assert attempt is not None and attempt.current_report_revision_id
            access = session.get(ReportAccessState, attempt.current_report_revision_id)
            assert access is not None
            access.state = "revoked"

    refreshed = client.post(
        f"/v1/footprint-jobs/{source_id}/refresh",
        headers={
            **auth_headers,
            "Idempotency-Key": f"history-ineligible-refresh-{suffix}",
        },
    )
    assert refreshed.status_code == 202
    refresh_id = refreshed.json()["job_id"]

    with app.state.session_factory() as session:
        job = session.get(SearchJob, refresh_id)
        runs = session.scalars(
            select(ProviderRun)
            .where(ProviderRun.job_id == refresh_id)
            .order_by(ProviderRun.logical_run_id)
        ).all()
        assert job is not None and runs
        assert job.refresh_of_job_id == source_id
        assert job.history_reuse_policy is None
        assert runs[0].query_config["site_names"][0] == "GitHub"
        assert "history_revalidation" not in runs[0].query_config
        refresh_run_ids = {run.id for run in runs}
        priorities = [
            message.priority
            for message in session.scalars(select(OutboxMessage)).all()
            if message.payload.get("provider_run_id") in refresh_run_ids
        ]
        assert priorities and set(priorities) == {0}


@pytest.mark.parametrize(
    "path_suffix",
    ("", "/candidates", "/history", "/brief", "/evidence"),
)
def test_expired_jobs_are_hidden_from_owner_reads(
    client,
    app,
    clock,
    auth_headers,
    path_suffix,
):
    created = _create_job(
        client,
        auth_headers,
        key=f"history-expired-{path_suffix.replace('/', '-') or 'job'}",
        identifier="expired-owner-read",
    )
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        job.expires_at = clock.now()

    response = client.get(
        f"/v1/footprint-jobs/{job_id}{path_suffix}",
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_expired_idempotency_replay_cannot_expose_the_old_job(
    client,
    app,
    clock,
    auth_headers,
):
    key = "history-expired-idempotency"
    created = _create_job(
        client,
        auth_headers,
        key=key,
        identifier="expired-idempotency",
    )
    assert created.status_code == 202
    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, created.json()["job_id"])
        assert job is not None
        job.expires_at = clock.now()

    replay = _create_job(
        client,
        auth_headers,
        key=key,
        identifier="expired-idempotency",
    )
    assert replay.status_code == 409
    assert replay.json()["error_code"] == "idempotency_conflict"
