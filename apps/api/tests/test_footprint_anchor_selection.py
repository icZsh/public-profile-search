from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from apps.api.app.core.crypto import stable_payload_hash
from apps.api.app.models.entities import (
    AccountNode,
    DiscoveryEdge,
    JobEvent,
    MaigretScanRun,
    MaigretSiteCheck,
    ProviderRun,
    ReportRevision,
    SearchJob,
    new_id,
)
from apps.api.app.services import anchor_selection as anchor_selection_service
from apps.api.app.services.footprint_finalization import finalize_footprint_if_complete
from apps.api.app.services.maigret_runs import finalize_discovery_if_complete
from apps.api.app.services.professional_search_scheduling import PROFESSIONAL_PROVIDER_IDS
from apps.api.tests.test_professional_footprint_finalization import (
    NOW,
    _add_exact_root_profile,
    _new_graph,
)
from workers.maintenance.deadline_watchdog import finalize_expired_jobs

HANDLE = "octaviyao"


def _create_bare_job(client, auth_headers, *, key: str) -> str:
    response = client.post(
        "/v1/footprint-jobs",
        headers={**auth_headers, "Idempotency-Key": key},
        json={
            "seed": {
                "kind": "bare_handle",
                "identifier_type": "handle",
                "identifier": HANDLE,
            },
            "search_mode": "quick",
            "locale": "en-US",
        },
    )
    assert response.status_code == 202
    return response.json()["job_id"]


def _prepare_ambiguous_root_results(app, clock, *, job_id: str) -> dict[str, str]:
    candidates = (
        (
            "Instagram",
            "Raymond Gu",
            f"https://www.instagram.com/{HANDLE}/",
            "San Francisco Bay Area",
        ),
        (
            "Clubhouse",
            "Jingyao Gu",
            f"https://www.clubhouse.com/@{HANDLE}",
            "San Francisco Bay Area",
        ),
    )
    candidate_ids: dict[str, str] = {}
    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        root_runs = session.scalars(
            select(ProviderRun)
            .where(ProviderRun.job_id == job_id)
            .order_by(ProviderRun.logical_run_id)
        ).all()
        assert root_runs
        for run in root_runs:
            run.status = "success"
            scan = session.get(MaigretScanRun, run.id)
            assert scan is not None
            scan.status = "success"
            scan.completed_count = scan.selected_count
            scan.found_count = 0
            scan.not_found_count = scan.selected_count
            scan.finished_at = clock.now()
        root_runs[0].result_count = len(candidates)
        first_scan = session.get(MaigretScanRun, root_runs[0].id)
        assert first_scan is not None
        first_scan.found_count = len(candidates)
        first_scan.not_found_count = max(0, first_scan.selected_count - len(candidates))
        job.status = "discovering"
        job.exploration_status = "running"

        for ordinal, (platform, display_name, profile_url, location) in enumerate(
            candidates,
            start=1,
        ):
            check_id = new_id()
            node_id = new_id()
            session.add(
                MaigretSiteCheck(
                    id=check_id,
                    job_id=job.id,
                    provider_run_id=root_runs[0].id,
                    site_key=f"anchor-{platform.casefold()}",
                    site_name=platform,
                    source_name=None,
                    queried_identifier=HANDLE,
                    queried_identifier_type="username",
                    url_main=profile_url.rsplit("/", 2)[0],
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
                        "username": HANDLE,
                        "display_name": display_name,
                        "location": location,
                    },
                    extracted_usernames={},
                    extracted_links=[],
                    result_checksum=stable_payload_hash(
                        {
                            "platform": platform,
                            "display_name": display_name,
                        }
                    ),
                    observed_at=clock.now() + timedelta(seconds=ordinal),
                )
            )
            session.add(
                AccountNode(
                    id=node_id,
                    job_id=job.id,
                    platform=platform,
                    canonical_handle=HANDLE,
                    canonical_url=profile_url,
                    display_name=display_name,
                    identity_confidence_tier="possible",
                    selection_state="undecided",
                    is_similar=False,
                    profile_data={},
                    first_observed_at=clock.now() + timedelta(seconds=ordinal),
                    last_observed_at=clock.now() + timedelta(seconds=ordinal),
                )
            )
            session.flush()
            session.add(
                DiscoveryEdge(
                    id=new_id(),
                    job_id=job.id,
                    provider_run_id=root_runs[0].id,
                    site_check_id=check_id,
                    source_observation_id=None,
                    child_account_node_id=node_id,
                    parent_seed=job.normalized_seed or "",
                    discovery_method="username_catalog_probe",
                    discovery_engine="maigret",
                    depth=0,
                    created_at=clock.now() + timedelta(seconds=ordinal),
                )
            )
            candidate_ids[platform] = node_id
    return candidate_ids


def _add_nameless_exact_candidate(app, clock, *, job_id: str) -> str:
    profile_url = f"https://github.com/{HANDLE}"
    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        root_run = session.scalar(
            select(ProviderRun)
            .where(ProviderRun.job_id == job_id)
            .order_by(ProviderRun.logical_run_id)
        )
        assert root_run is not None
        check_id = new_id()
        node_id = new_id()
        session.add(
            MaigretSiteCheck(
                id=check_id,
                job_id=job.id,
                provider_run_id=root_run.id,
                site_key="anchor-github-nameless",
                site_name="GitHub",
                source_name=None,
                queried_identifier=HANDLE,
                queried_identifier_type="username",
                url_main="https://github.com",
                url_user=profile_url,
                url_probe=profile_url,
                raw_status="CLAIMED",
                normalized_status="found",
                error_type=None,
                error_context=None,
                http_status=200,
                is_similar=False,
                rank=3,
                tags=["coding"],
                extracted_data={"username": HANDLE},
                extracted_usernames={},
                extracted_links=[],
                result_checksum=stable_payload_hash(
                    {
                        "platform": "GitHub",
                        "handle": HANDLE,
                    }
                ),
                observed_at=clock.now() + timedelta(seconds=3),
            )
        )
        session.add(
            AccountNode(
                id=node_id,
                job_id=job.id,
                platform="GitHub",
                canonical_handle=HANDLE,
                canonical_url=profile_url,
                display_name=None,
                identity_confidence_tier="possible",
                selection_state="undecided",
                is_similar=False,
                profile_data={},
                first_observed_at=clock.now() + timedelta(seconds=3),
                last_observed_at=clock.now() + timedelta(seconds=3),
            )
        )
        session.flush()
        session.add(
            DiscoveryEdge(
                id=new_id(),
                job_id=job.id,
                provider_run_id=root_run.id,
                site_check_id=check_id,
                source_observation_id=None,
                child_account_node_id=node_id,
                parent_seed=job.normalized_seed or "",
                discovery_method="username_catalog_probe",
                discovery_engine="maigret",
                depth=0,
                created_at=clock.now() + timedelta(seconds=3),
            )
        )
    return node_id


def _enter_anchor_checkpoint(app, settings, clock, *, job_id: str) -> None:
    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert not finalize_discovery_if_complete(
            session,
            job=job,
            now=clock.now(),
            settings=settings,
        )
        assert job.exploration_status == "awaiting_anchor"


def test_bare_handle_checkpoint_is_owner_scoped_and_resumes_from_selected_anchor(
    client,
    app,
    settings,
    clock,
    auth_headers,
):
    settings.professional_search_enabled = True
    settings.exa_people_search_enabled = False
    job_id = _create_bare_job(
        client,
        auth_headers,
        key="bare-anchor-selection",
    )
    candidate_ids = _prepare_ambiguous_root_results(app, clock, job_id=job_id)
    nameless_candidate_id = _add_nameless_exact_candidate(
        app,
        clock,
        job_id=job_id,
    )
    _enter_anchor_checkpoint(app, settings, clock, job_id=job_id)

    choices = client.get(
        f"/v1/footprint-jobs/{job_id}/candidates",
        headers=auth_headers,
    )
    assert choices.status_code == 200
    assert {
        item["platform"]: item["anchor_eligible"]
        for item in choices.json()["items"]
    } == {
        "Clubhouse": True,
        "GitHub": False,
        "Instagram": True,
    }

    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count(ProviderRun.id)).where(
                    ProviderRun.job_id == job_id,
                    ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
                )
            )
            == 0
        )
        event_types = session.scalars(
            select(JobEvent.event_type)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.sequence)
        ).all()
        assert event_types.count("discovery.anchor_required") == 1

    wrong_owner = client.post(
        f"/v1/footprint-jobs/{job_id}/anchor",
        headers={
            **auth_headers,
            "X-Prototype-User": str(uuid4()),
        },
        json={"candidate_id": candidate_ids["Clubhouse"]},
    )
    assert wrong_owner.status_code == 404
    assert wrong_owner.json()["error_code"] == "job_not_found"

    nameless = client.post(
        f"/v1/footprint-jobs/{job_id}/anchor",
        headers=auth_headers,
        json={"candidate_id": nameless_candidate_id},
    )
    assert nameless.status_code == 422
    assert nameless.json()["error_code"] == "anchor_candidate_not_hypothesis"

    selected = client.post(
        f"/v1/footprint-jobs/{job_id}/anchor",
        headers=auth_headers,
        json={"candidate_id": candidate_ids["Clubhouse"]},
    )
    assert selected.status_code == 200
    assert selected.json()["job"]["exploration_status"] == "running"
    assert selected.json()["selected_anchor"] == {
        "candidate_id": candidate_ids["Clubhouse"],
        "platform": "Clubhouse",
        "handle": HANDLE,
        "profile_url": f"https://www.clubhouse.com/@{HANDLE}",
        "display_name": "Jingyao Gu",
        "selection_state": "included",
    }

    with app.state.session_factory() as session:
        nodes = session.scalars(
            select(AccountNode)
            .where(AccountNode.job_id == job_id)
            .order_by(AccountNode.platform)
        ).all()
        states = {node.platform: node.selection_state for node in nodes}
        assert states == {
            "Clubhouse": "included",
            "GitHub": "undecided",
            "Instagram": "undecided",
        }
        professional_runs = session.scalars(
            select(ProviderRun)
            .where(
                ProviderRun.job_id == job_id,
                ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
            )
            .order_by(ProviderRun.logical_run_id)
        ).all()
        assert professional_runs
        assert professional_runs[0].query_config["full_name"] == "Jingyao Gu"
        run_count = len(professional_runs)

    repeated = client.post(
        f"/v1/footprint-jobs/{job_id}/anchor",
        headers=auth_headers,
        json={"candidate_id": candidate_ids["Clubhouse"]},
    )
    assert repeated.status_code == 200
    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count(ProviderRun.id)).where(
                    ProviderRun.job_id == job_id,
                    ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
                )
            )
            == run_count
        )

        professional_runs = session.scalars(
            select(ProviderRun).where(
                ProviderRun.job_id == job_id,
                ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
            )
        ).all()
        for run in professional_runs:
            run.status = "no_result"
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert finalize_discovery_if_complete(
            session,
            job=job,
            now=clock.now(),
            settings=settings,
        )
        session.commit()

    brief = client.get(f"/v1/footprint-jobs/{job_id}/brief", headers=auth_headers)
    assert brief.status_code == 200
    assert brief.json()["subject"] == f"Jingyao Gu (@{HANDLE})"


def test_awaiting_anchor_falls_back_at_existing_job_cutoff(
    client,
    app,
    settings,
    clock,
    auth_headers,
):
    settings.professional_search_enabled = True
    settings.exa_people_search_enabled = False
    job_id = _create_bare_job(
        client,
        auth_headers,
        key="bare-anchor-cutoff-fallback",
    )
    _prepare_ambiguous_root_results(app, clock, job_id=job_id)
    _enter_anchor_checkpoint(app, settings, clock, job_id=job_id)

    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        assert job is not None
        clock.value = job.deadline_at + timedelta(seconds=1)

    assert (
        finalize_expired_jobs(
            app.state.session_factory,
            settings=settings,
            clock=clock,
        )
        == 1
    )
    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert job.status == "ready"
        assert job.exploration_status == "completed"
        assert (
            session.scalar(
                select(func.count(ProviderRun.id)).where(
                    ProviderRun.job_id == job_id,
                    ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(JobEvent.id)).where(
                    JobEvent.job_id == job_id,
                    JobEvent.event_type == "discovery.anchor_window_expired",
                )
            )
            == 1
        )


def test_anchor_selection_closes_before_the_reserved_retrieval_window(
    client,
    app,
    settings,
    clock,
    auth_headers,
    monkeypatch,
):
    settings.professional_search_enabled = True
    settings.exa_people_search_enabled = False
    job_id = _create_bare_job(
        client,
        auth_headers,
        key="bare-anchor-expired-selection",
    )
    candidate_ids = _prepare_ambiguous_root_results(app, clock, job_id=job_id)
    _enter_anchor_checkpoint(app, settings, clock, job_id=job_id)

    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        assert job is not None
        clock.value = job.deadline_at - timedelta(seconds=29)

    choices = client.get(
        f"/v1/footprint-jobs/{job_id}/candidates",
        headers=auth_headers,
    )
    assert choices.status_code == 200
    assert not any(item["anchor_eligible"] for item in choices.json()["items"])

    lock_acquired = False
    original_owner_job = anchor_selection_service.owner_footprint_job

    def record_locked_owner(*args, **kwargs):
        nonlocal lock_acquired
        job = original_owner_job(*args, **kwargs)
        lock_acquired = bool(kwargs.get("for_update"))
        return job

    class LockAwareClock:
        def now(self):
            assert lock_acquired
            return clock.now()

    monkeypatch.setattr(
        anchor_selection_service,
        "owner_footprint_job",
        record_locked_owner,
    )
    app.state.clock = LockAwareClock()
    expired = client.post(
        f"/v1/footprint-jobs/{job_id}/anchor",
        headers=auth_headers,
        json={"candidate_id": candidate_ids["Clubhouse"]},
    )
    assert expired.status_code == 409
    assert expired.json()["error_code"] == "anchor_selection_expired"

    current = client.get(
        f"/v1/footprint-jobs/{job_id}",
        headers=auth_headers,
    )
    assert current.status_code == 200
    assert current.json()["exploration_status"] == "running"

    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count(AccountNode.id)).where(
                    AccountNode.job_id == job_id,
                    AccountNode.selection_state == "included",
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(ProviderRun.id)).where(
                    ProviderRun.job_id == job_id,
                    ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
                )
            )
            > 0
        )
        assert (
            session.scalar(
                select(func.count(JobEvent.id)).where(
                    JobEvent.job_id == job_id,
                    JobEvent.event_type == "discovery.anchor_window_expired",
                )
            )
            == 1
        )


def test_polling_advances_an_expired_anchor_checkpoint_once(
    client,
    app,
    settings,
    clock,
    auth_headers,
):
    settings.professional_search_enabled = True
    settings.exa_people_search_enabled = False
    job_id = _create_bare_job(
        client,
        auth_headers,
        key="bare-anchor-polling-cutoff",
    )
    _prepare_ambiguous_root_results(app, clock, job_id=job_id)
    _enter_anchor_checkpoint(app, settings, clock, job_id=job_id)

    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        assert job is not None
        clock.value = job.deadline_at - timedelta(seconds=29)

    for _ in range(2):
        current = client.get(
            f"/v1/footprint-jobs/{job_id}",
            headers=auth_headers,
        )
        assert current.status_code == 200
        assert current.json()["exploration_status"] == "running"

    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count(JobEvent.id)).where(
                    JobEvent.job_id == job_id,
                    JobEvent.event_type == "discovery.anchor_window_expired",
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count(ProviderRun.id)).where(
                    ProviderRun.job_id == job_id,
                    ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
                )
            )
            > 0
        )


def test_watchdog_advances_anchor_checkpoint_at_reserved_search_window(
    client,
    app,
    settings,
    clock,
    auth_headers,
):
    settings.professional_search_enabled = True
    settings.exa_people_search_enabled = False
    job_id = _create_bare_job(
        client,
        auth_headers,
        key="bare-anchor-watchdog-cutoff",
    )
    _prepare_ambiguous_root_results(app, clock, job_id=job_id)
    _enter_anchor_checkpoint(app, settings, clock, job_id=job_id)

    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        assert job is not None
        clock.value = job.deadline_at - timedelta(seconds=29)

    assert (
        finalize_expired_jobs(
            app.state.session_factory,
            settings=settings,
            clock=clock,
        )
        == 1
    )
    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert job.exploration_status == "running"
        assert job.status == "discovering"
        assert (
            session.scalar(
                select(func.count(ProviderRun.id)).where(
                    ProviderRun.job_id == job_id,
                    ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
                )
            )
            > 0
        )
        assert (
            session.scalar(
                select(func.count(JobEvent.id)).where(
                    JobEvent.job_id == job_id,
                    JobEvent.event_type == "discovery.anchor_window_expired",
                )
            )
            == 1
        )


def test_selected_anchor_overrides_seed_platform_in_final_subject():
    graph = _new_graph()
    _add_exact_root_profile(
        graph,
        platform="Instagram",
        display_name="Raymond Gu",
        location="San Francisco Bay Area",
        ordinal=1,
    )
    selected_id = _add_exact_root_profile(
        graph,
        platform="Clubhouse",
        display_name="Jingyao Gu",
        location="San Francisco Bay Area",
        ordinal=2,
    )
    with graph.factory() as session, session.begin():
        selected = session.get(AccountNode, selected_id)
        job = session.get(SearchJob, graph.job_id)
        assert selected is not None and job is not None
        selected.selection_state = "included"
        assert finalize_footprint_if_complete(session, job=job, now=NOW)

    with graph.factory() as session:
        report = session.scalar(
            select(ReportRevision)
            .where(ReportRevision.job_id == graph.job_id)
            .order_by(ReportRevision.created_at.desc())
        )
        assert report is not None
        assert report.content["subject"] == f"Jingyao Gu (@{HANDLE})"


def test_checkpoint_is_skipped_when_less_than_thirty_seconds_remain(
    client,
    app,
    settings,
    clock,
    auth_headers,
):
    settings.professional_search_enabled = True
    settings.exa_people_search_enabled = False
    job_id = _create_bare_job(
        client,
        auth_headers,
        key="bare-anchor-short-window",
    )
    _prepare_ambiguous_root_results(app, clock, job_id=job_id)
    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        assert job is not None
        clock.value = job.deadline_at - timedelta(seconds=29)

    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert not finalize_discovery_if_complete(
            session,
            job=job,
            now=clock.now(),
            settings=settings,
        )
        assert job.exploration_status == "running"

    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count(ProviderRun.id)).where(
                    ProviderRun.job_id == job_id,
                    ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
                )
            )
            > 0
        )
        assert (
            session.scalar(
                select(func.count(JobEvent.id)).where(
                    JobEvent.job_id == job_id,
                    JobEvent.event_type == "discovery.anchor_required",
                )
            )
            == 0
        )
