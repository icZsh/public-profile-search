from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, select

import apps.api.app.services.maigret_runs as maigret_runs_service
import apps.api.app.services.professional_search_runs as professional_runs_service
import apps.api.app.services.professional_search_scheduling as professional_scheduling_service
from apps.api.app.core.clock import FixedClock
from apps.api.app.core.db import build_engine, build_session_factory
from apps.api.app.models.entities import (
    AccountNode,
    Base,
    DiscoveryEdge,
    JobAttempt,
    MaigretSiteCheck,
    OutboxMessage,
    ProviderAttempt,
    ProviderRun,
    ProviderRunSourceUse,
    SearchJob,
    SourceDocument,
    SourceObservation,
    new_id,
)
from apps.api.app.services.anchor_selection import eligible_anchor_candidate_ids
from apps.api.app.services.professional_search_runs import (
    process_professional_search_run,
)
from apps.api.app.services.professional_search_scheduling import (
    EXA_PEOPLE_PROVIDER_ID,
    GITHUB_PROFESSIONAL_PROVIDER_ID,
    PROFESSIONAL_PROVIDER_IDS,
    AdaptiveProfessionalRunPlan,
    ProfessionalNameHypothesis,
    build_adaptive_professional_query_plan,
    schedule_professional_search_if_ready,
)
from workers.maintenance.outbox_dispatcher import dispatch_once
from workers.maintenance.reconciler import reclaim_expired_leases
from workers.orchestrator.celery_app import celery_app
from workers.providers.professional_search import (
    ProfessionalProfile,
    ProfessionalSearchResult,
)


def _session_factory():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def _add_job(
    factory,
    *,
    now: datetime,
    deadline_at: datetime | None = None,
    search_mode: str = "quick",
) -> tuple[str, str]:
    job_id = new_id()
    attempt_id = new_id()
    deadline = deadline_at or now + timedelta(minutes=5)
    with factory() as session, session.begin():
        session.add(
            SearchJob(
                id=job_id,
                user_id="professional-test-user",
                retry_of_job_id=None,
                normalized_identifier_hmac="a" * 64,
                canonical_input_url_ciphertext=None,
                input_provider_id="maigret_discovery_v1",
                canonicalization_version="seed-identifier-v1",
                eligibility_verification_id=None,
                job_kind="footprint_discovery",
                seed_kind="platform_handle",
                seed_platform="instagram",
                seed_identifier_type="handle",
                seed_identifier="alice",
                normalized_seed="instagram:handle:alice",
                search_mode=search_mode,
                catalog_profile=search_mode,
                catalog_snapshot_id=None,
                exploration_status="running",
                purpose="digital_footprint",
                fixture_key=None,
                status="discovering",
                active_attempt_id=attempt_id,
                accepted_at=now,
                collection_cutoff_at=deadline,
                fallback_at=deadline,
                deadline_at=deadline,
                completion_policy_id="candidate-map-v1",
                policy_version="test-policy",
                locale="en-US",
                acceptance_epoch=1,
                row_version=1,
                cancelled_at=None,
                expires_at=now + timedelta(days=1),
            )
        )
        session.flush()
        session.add(
            JobAttempt(
                id=attempt_id,
                job_id=job_id,
                attempt_no=1,
                status="running",
                collection_snapshot_id=None,
                current_analysis_revision_id=None,
                current_report_revision_id=None,
                started_at=now,
                finished_at=None,
                terminal_reason=None,
            )
        )
    return job_id, attempt_id


def _add_provider_run(
    session,
    *,
    job_id: str,
    attempt_id: str,
    now: datetime,
    provider_id: str,
    status: str,
    logical_run_id: str,
    query_config: dict[str, object] | None = None,
    lease_generation: int = 0,
    lease_expires_at: datetime | None = None,
) -> str:
    run_id = new_id()
    session.add(
        ProviderRun(
            id=run_id,
            job_id=job_id,
            attempt_id=attempt_id,
            logical_run_id=logical_run_id,
            provider_id=provider_id,
            parent_run_id=None,
            depth=0 if provider_id == "maigret_discovery_v1" else 1,
            query_config=query_config or {},
            status=status,
            required_for_finalization=True,
            lease_generation=lease_generation,
            lease_expires_at=lease_expires_at,
            acceptance_epoch=1,
            result_count=0,
            deadline_at=now + timedelta(minutes=5),
            expires_at=now + timedelta(days=1),
        )
    )
    session.flush()
    return run_id


def _add_exact_profile_check(
    session,
    *,
    job_id: str,
    provider_run_id: str,
    now: datetime,
    platform: str,
    display_name: str,
    ordinal: int,
    extra_data: dict[str, object] | None = None,
) -> str:
    routes = {
        "Instagram": "https://www.instagram.com/alice",
        "Threads": "https://www.threads.net/@alice",
        "GitHub": "https://github.com/alice",
        "Pinterest": "https://www.pinterest.com/alice",
    }
    check_id = new_id()
    node_id = new_id()
    profile_url = routes[platform]
    session.add(
        MaigretSiteCheck(
            id=check_id,
            job_id=job_id,
            provider_run_id=provider_run_id,
            site_key=f"{platform.casefold()}-{ordinal}",
            site_name=platform,
            source_name=None,
            queried_identifier="alice",
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
                "username": "alice",
                "full_name": display_name,
                "location": "San Francisco Bay Area",
                **(extra_data or {}),
            },
            extracted_usernames={},
            extracted_links=[],
            result_checksum=f"{ordinal:064x}",
            observed_at=now + timedelta(seconds=ordinal),
        )
    )
    session.add(
        AccountNode(
            id=node_id,
            job_id=job_id,
            platform=platform,
            canonical_handle="alice",
            canonical_url=profile_url,
            display_name=display_name,
            identity_confidence_tier="possible",
            selection_state="undecided",
            is_similar=False,
            profile_data={},
            first_observed_at=now,
            last_observed_at=now,
        )
    )
    session.flush()
    session.add(
        DiscoveryEdge(
            id=new_id(),
            job_id=job_id,
            provider_run_id=provider_run_id,
            site_check_id=check_id,
            source_observation_id=None,
            child_account_node_id=node_id,
            parent_seed="instagram:handle:alice",
            discovery_method="username_catalog_probe",
            discovery_engine="maigret",
            depth=0,
            created_at=now,
        )
    )
    session.flush()
    return node_id


def _settings(**overrides):
    values = {
        "professional_search_enabled": True,
        "exa_people_search_enabled": True,
        "github_people_search_enabled": True,
        "professional_search_max_results_per_query": 5,
        "professional_search_max_github_profiles": 3,
        "professional_search_run_lease_seconds": 60,
        "adaptive_professional_search_max_names": 4,
        "adaptive_professional_search_max_queries": 20,
        "adaptive_professional_search_max_requests": 32,
        "adaptive_professional_search_max_profiles": 30,
        "adaptive_professional_search_budget_seconds": 120,
        "adaptive_professional_search_stagnation_queries": 3,
        "exa_api_key": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _pending_professional_run(
    factory,
    *,
    now: datetime,
    provider_id: str,
) -> tuple[str, str]:
    job_id, attempt_id = _add_job(factory, now=now)
    with factory() as session, session.begin():
        run_id = _add_provider_run(
            session,
            job_id=job_id,
            attempt_id=attempt_id,
            now=now,
            provider_id=provider_id,
            status="pending",
            logical_run_id=f"professional:{provider_id}",
            query_config={
                "full_name": "Alice Example",
                "query": "Alice Example San Francisco",
                "candidate_logins": ["aliceexample"],
                "max_results": 5,
                "max_profiles": 3,
            },
        )
    return job_id, run_id


def _github_profile() -> ProfessionalProfile:
    return ProfessionalProfile(
        provider_id=GITHUB_PROFESSIONAL_PROVIDER_ID,
        platform="GitHub",
        profile_url="https://github.com/aliceexample",
        handle="aliceexample",
        display_name="Alice Example",
        headline=None,
        location="San Francisco Bay Area",
        bio="Public software profile",
        company="Example Labs",
        website="https://alice.example",
        social_handle="alice_example",
        work_history=(),
        education_history=(),
        highlights=(),
    )


def _disable_finalizer(monkeypatch) -> None:
    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        lambda _session, **_kwargs: False,
    )


def test_scheduler_waits_for_all_roots_then_creates_one_adaptive_wave():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, attempt_id = _add_job(factory, now=now, search_mode="deep")
    with factory() as session, session.begin():
        first_root = _add_provider_run(
            session,
            job_id=job_id,
            attempt_id=attempt_id,
            now=now,
            provider_id="maigret_discovery_v1",
            status="success",
            logical_run_id="maigret:root:000",
        )
        second_root = _add_provider_run(
            session,
            job_id=job_id,
            attempt_id=attempt_id,
            now=now,
            provider_id="maigret_discovery_v1",
            status="running",
            logical_run_id="maigret:root:001",
        )
        _add_exact_profile_check(
            session,
            job_id=job_id,
            provider_run_id=first_root,
            now=now,
            platform="Instagram",
            display_name="Alice Example",
            ordinal=1,
        )
        _add_exact_profile_check(
            session,
            job_id=job_id,
            provider_run_id=first_root,
            now=now,
            platform="Threads",
            display_name="Raymond Example",
            ordinal=2,
        )
        _add_exact_profile_check(
            session,
            job_id=job_id,
            provider_run_id=second_root,
            now=now,
            platform="GitHub",
            display_name="Third Person",
            ordinal=3,
        )
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert not schedule_professional_search_if_ready(
            session,
            job=job,
            now=now,
            settings=_settings(
                adaptive_professional_search_max_names=2,
                exa_api_key="configured",
            ),
        )

    with factory() as session, session.begin():
        second_root_row = session.get(ProviderRun, second_root)
        assert second_root_row is not None
        second_root_row.status = "no_result"
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert schedule_professional_search_if_ready(
            session,
            job=job,
            now=now,
            settings=_settings(
                adaptive_professional_search_max_names=2,
                exa_api_key="configured",
            ),
        )
        assert not schedule_professional_search_if_ready(
            session,
            job=job,
            now=now,
            settings=_settings(
                adaptive_professional_search_max_names=2,
                exa_api_key="configured",
            ),
        )

    with factory() as session:
        professional_runs = session.scalars(
            select(ProviderRun)
            .where(
                ProviderRun.job_id == job_id,
                ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
            )
            .order_by(ProviderRun.logical_run_id)
        ).all()
        names = {str(run.query_config["full_name"]) for run in professional_runs}
        providers_by_name = {
            name: {
                run.provider_id
                for run in professional_runs
                if run.query_config["full_name"] == name
            }
            for name in names
        }
        messages = session.scalars(
            select(OutboxMessage).where(OutboxMessage.topic == "professional_search_run")
        ).all()
        assert len(professional_runs) == 4
        assert len(names) == 2
        assert all(
            providers == PROFESSIONAL_PROVIDER_IDS for providers in providers_by_name.values()
        )
        assert len(messages) == 4
        assert all(run.depth == 1 and run.parent_run_id for run in professional_runs)
        assert all(
            run.query_config["max_results"] == 5
            for run in professional_runs
            if run.provider_id == EXA_PEOPLE_PROVIDER_ID
        )
        assert all(
            run.query_config["max_profiles"] == 3
            for run in professional_runs
            if run.provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID
        )
        assert all(
            run.query_config["retrieval_mode"] == "adaptive"
            and run.query_config["queries"]
            and run.query_config["request_budget"] >= 1
            for run in professional_runs
        )


def test_quick_mode_uses_exa_only_and_caps_the_adaptive_envelope():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, attempt_id = _add_job(factory, now=now, search_mode="quick")
    with factory() as session, session.begin():
        root_id = _add_provider_run(
            session,
            job_id=job_id,
            attempt_id=attempt_id,
            now=now,
            provider_id="maigret_discovery_v1",
            status="success",
            logical_run_id="maigret:root:000",
        )
        node_ids = [
            _add_exact_profile_check(
                session,
                job_id=job_id,
                provider_run_id=root_id,
                now=now,
                platform=platform,
                display_name=display_name,
                ordinal=index,
                extra_data={"bio": "Data Engineer@TikTok, MCS@UIUC"},
            )
            for index, (platform, display_name) in enumerate(
                (
                    ("Instagram", "Alice Example"),
                    ("Threads", "Beatrice Example"),
                    ("GitHub", "Carla Example"),
                    ("Pinterest", "Diana Example"),
                ),
                start=1,
            )
        ]
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert eligible_anchor_candidate_ids(
            session,
            job=job,
            settings=_settings(exa_api_key="configured"),
            now=now,
        ) == frozenset(node_ids[:2])
        assert schedule_professional_search_if_ready(
            session,
            job=job,
            now=now,
            settings=_settings(exa_api_key="configured"),
        )

    with factory() as session:
        runs = session.scalars(
            select(ProviderRun)
            .where(
                ProviderRun.job_id == job_id,
                ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
            )
            .order_by(ProviderRun.provider_id)
        ).all()
        assert len(runs) == 2
        assert {run.provider_id for run in runs} == {EXA_PEOPLE_PROVIDER_ID}
        job = session.get(SearchJob, job_id)
        assert job is not None and job.search_mode == "quick"
        assert all(run.query_config["retrieval_mode"] == "adaptive" for run in runs)
        assert sum(int(run.query_config["query_budget"]) for run in runs) == 6
        assert sum(int(run.query_config["request_budget"]) for run in runs) == 6
        assert sum(int(run.query_config["result_budget"]) for run in runs) == 10
        assert all(run.query_config["stagnation_query_limit"] == 2 for run in runs)
        assert all(
            run.deadline_at.replace(tzinfo=UTC) == now + timedelta(seconds=40) for run in runs
        )


def test_quick_mode_settings_can_lower_every_effective_cap():
    policy = professional_scheduling_service.effective_adaptive_professional_search_policy(
        settings=_settings(
            adaptive_professional_search_max_names=1,
            adaptive_professional_search_max_queries=4,
            adaptive_professional_search_max_requests=3,
            adaptive_professional_search_max_profiles=7,
            adaptive_professional_search_budget_seconds=35,
            adaptive_professional_search_stagnation_queries=1,
        ),
        search_mode="quick",
    )

    assert policy == professional_scheduling_service.AdaptiveProfessionalSearchPolicy(
        maximum_names=1,
        max_queries=4,
        max_requests=3,
        max_profiles=7,
        budget_seconds=35,
        stagnation_queries=1,
        github_allowed=False,
    )


def test_anchor_eligibility_keeps_two_choices_when_search_cap_is_one():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, attempt_id = _add_job(factory, now=now, search_mode="quick")
    with factory() as session, session.begin():
        root_id = _add_provider_run(
            session,
            job_id=job_id,
            attempt_id=attempt_id,
            now=now,
            provider_id="maigret_discovery_v1",
            status="success",
            logical_run_id="maigret:root:000",
        )
        node_ids = {
            _add_exact_profile_check(
                session,
                job_id=job_id,
                provider_run_id=root_id,
                now=now,
                platform=platform,
                display_name=display_name,
                ordinal=index,
                extra_data={"bio": "Public profile"},
            )
            for index, (platform, display_name) in enumerate(
                (
                    ("Instagram", "Alice Example"),
                    ("Threads", "Beatrice Example"),
                ),
                start=1,
            )
        }
        job = session.get(SearchJob, job_id)
        assert job is not None

        eligible = eligible_anchor_candidate_ids(
            session,
            job=job,
            settings=_settings(adaptive_professional_search_max_names=1),
            now=now,
        )

    assert eligible == frozenset(node_ids)


def test_quick_without_exa_key_neither_falls_back_to_github_nor_waits_for_anchor():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, attempt_id = _add_job(factory, now=now, search_mode="quick")
    with factory() as session, session.begin():
        root_id = _add_provider_run(
            session,
            job_id=job_id,
            attempt_id=attempt_id,
            now=now,
            provider_id="maigret_discovery_v1",
            status="success",
            logical_run_id="maigret:root:000",
        )
        for index, (platform, display_name) in enumerate(
            (
                ("Instagram", "Alice Example"),
                ("Threads", "Beatrice Example"),
            ),
            start=1,
        ):
            _add_exact_profile_check(
                session,
                job_id=job_id,
                provider_run_id=root_id,
                now=now,
                platform=platform,
                display_name=display_name,
                ordinal=index,
                extra_data={"bio": "Public profile"},
            )
        job = session.get(SearchJob, job_id)
        assert job is not None
        job.seed_kind = "bare_handle"

        assert not schedule_professional_search_if_ready(
            session,
            job=job,
            now=now,
            settings=_settings(
                exa_api_key=None,
                github_people_search_enabled=True,
                github_provider_enabled=True,
            ),
        )
        assert job.exploration_status == "running"
        assert (
            session.scalar(
                select(func.count(ProviderRun.id)).where(
                    ProviderRun.job_id == job_id,
                    ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
                )
            )
            == 0
        )


def test_deep_mode_keeps_the_full_configured_anchor_aware_adaptive_plan():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, attempt_id = _add_job(factory, now=now, search_mode="deep")
    with factory() as session, session.begin():
        root_id = _add_provider_run(
            session,
            job_id=job_id,
            attempt_id=attempt_id,
            now=now,
            provider_id="maigret_discovery_v1",
            status="success",
            logical_run_id="maigret:root:000",
        )
        _add_exact_profile_check(
            session,
            job_id=job_id,
            provider_run_id=root_id,
            now=now,
            platform="Instagram",
            display_name="Alice Example",
            ordinal=1,
            extra_data={"bio": "Data Engineer@TikTok, MCS@UIUC"},
        )
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert schedule_professional_search_if_ready(
            session,
            job=job,
            now=now,
            settings=_settings(
                exa_api_key="configured",
                adaptive_professional_search_max_names=1,
                adaptive_professional_search_max_queries=6,
                adaptive_professional_search_max_requests=9,
                adaptive_professional_search_max_profiles=8,
                adaptive_professional_search_budget_seconds=90,
            ),
        )

    with factory() as session:
        runs = session.scalars(
            select(ProviderRun)
            .where(
                ProviderRun.job_id == job_id,
                ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
            )
            .order_by(ProviderRun.provider_id)
        ).all()
        assert len(runs) == 2
        exa = next(run for run in runs if run.provider_id == EXA_PEOPLE_PROVIDER_ID)
        github = next(run for run in runs if run.provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID)
        assert exa.query_config["queries"] == [
            "Alice Example San Francisco Bay Area",
            "Alice Example",
            "Alice Example alice",
            "Alice Example TikTok",
            "Alice Example UIUC",
        ]
        assert exa.query_config["company_anchors"] == ["TikTok"]
        assert exa.query_config["education_anchors"] == ["UIUC"]
        assert github.query_config["candidate_logins"] == ["alice", "aliceexample"]
        assert all(run.query_config["retrieval_mode"] == "adaptive" for run in runs)
        assert sum(int(run.query_config["query_budget"]) for run in runs) == 6
        assert sum(int(run.query_config["request_budget"]) for run in runs) == 9
        assert sum(int(run.query_config["result_budget"]) for run in runs) == 8
        assert all(run.query_config["stagnation_query_limit"] == 3 for run in runs)
        assert all(
            run.deadline_at.replace(tzinfo=UTC) == now + timedelta(seconds=90) for run in runs
        )


def test_adaptive_planner_does_not_spend_small_request_budget_on_unconfigured_exa():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, attempt_id = _add_job(factory, now=now, search_mode="deep")
    with factory() as session, session.begin():
        root_id = _add_provider_run(
            session,
            job_id=job_id,
            attempt_id=attempt_id,
            now=now,
            provider_id="maigret_discovery_v1",
            status="success",
            logical_run_id="maigret:root:000",
        )
        _add_exact_profile_check(
            session,
            job_id=job_id,
            provider_run_id=root_id,
            now=now,
            platform="Instagram",
            display_name="Alice Example",
            ordinal=1,
        )
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert schedule_professional_search_if_ready(
            session,
            job=job,
            now=now,
            settings=_settings(
                exa_api_key=None,
                adaptive_professional_search_max_names=1,
                adaptive_professional_search_max_queries=1,
                adaptive_professional_search_max_requests=2,
                adaptive_professional_search_max_profiles=1,
            ),
        )

    with factory() as session:
        runs = session.scalars(
            select(ProviderRun).where(
                ProviderRun.job_id == job_id,
                ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS),
            )
        ).all()
        assert [run.provider_id for run in runs] == [GITHUB_PROFESSIONAL_PROVIDER_ID]
        assert runs[0].query_config["request_budget"] == 2


def test_adaptive_queries_preserve_broad_baseline_and_decode_html_anchors():
    hypothesis = ProfessionalNameHypothesis(
        full_name="Alice Example",
        broad_location="Bay Area",
        source_check_ids=("check-1",),
        source_node_ids=("node-1",),
        provenance_families=("meta",),
        company_anchors=("Procter &amp;amp; Gamble",),
        education_anchors=(),
    )

    queries = professional_scheduling_service._adaptive_exa_queries(
        hypothesis,
        root_handle="alice",
    )

    assert queries[:2] == ("Alice Example Bay Area", "Alice Example")
    assert "Alice Example Procter & Gamble" in queries
    assert all("&amp;" not in query for query in queries)


def test_plausible_full_names_keep_apostrophes_and_hyphens():
    assert professional_scheduling_service._plausible_full_name("Ana O'Connor") == "Ana O'Connor"
    assert (
        professional_scheduling_service._plausible_full_name("Mary-Jane Smith") == "Mary-Jane Smith"
    )


def test_adaptive_query_planner_is_deterministic_and_never_exceeds_job_caps():
    hypotheses = tuple(
        ProfessionalNameHypothesis(
            full_name=f"Person {name}",
            broad_location="Bay Area",
            source_check_ids=(f"check-{index}",),
            source_node_ids=(f"node-{index}",),
            provenance_families=("meta",),
            company_anchors=("Example Labs",),
            education_anchors=("Example University",),
        )
        for index, name in enumerate(("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"))
    )
    kwargs = {
        "root_handle": "rare-handle",
        "exa_enabled": True,
        "github_enabled": True,
        "max_queries": 7,
        "max_requests": 10,
        "max_profiles": 9,
    }

    first = build_adaptive_professional_query_plan(hypotheses, **kwargs)
    second = build_adaptive_professional_query_plan(hypotheses, **kwargs)

    assert first == second
    assert all(isinstance(plan, AdaptiveProfessionalRunPlan) for plan in first)
    assert sum(len(plan.queries) for plan in first) <= 7
    assert sum(plan.request_budget for plan in first) <= 10
    assert sum(plan.result_budget for plan in first) <= 9
    assert all(plan.request_budget >= len(plan.queries) for plan in first)


def test_adaptive_quick_lease_uses_only_time_remaining_on_shared_wave_deadline():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, attempt_id = _add_job(factory, now=now, search_mode="quick")
    with factory() as session, session.begin():
        run_id = _add_provider_run(
            session,
            job_id=job_id,
            attempt_id=attempt_id,
            now=now,
            provider_id=EXA_PEOPLE_PROVIDER_ID,
            status="pending",
            logical_run_id="professional:exa:adaptive-time",
            query_config={
                "retrieval_mode": "adaptive",
                "full_name": "Alice Example",
                "queries": ["Alice Example alice"],
                "time_budget_seconds": 120,
            },
        )
        run = session.get(ProviderRun, run_id)
        assert run is not None
        run.deadline_at = now + timedelta(seconds=17)

    lease = professional_runs_service._lease_run(
        factory,
        settings=_settings(),
        clock=FixedClock(now),
        provider_run_id=run_id,
    )

    assert lease is not None
    assert lease[4]["time_budget_seconds"] == 17.0
    with factory() as session:
        run = session.get(ProviderRun, run_id)
        assert run is not None
        assert run.lease_expires_at.replace(tzinfo=UTC) == now + timedelta(seconds=60)


def test_adaptive_lease_covers_full_wave_plus_persistence_margin():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, attempt_id = _add_job(factory, now=now, search_mode="deep")
    with factory() as session, session.begin():
        run_id = _add_provider_run(
            session,
            job_id=job_id,
            attempt_id=attempt_id,
            now=now,
            provider_id=EXA_PEOPLE_PROVIDER_ID,
            status="pending",
            logical_run_id="professional:exa:adaptive-lease",
            query_config={
                "retrieval_mode": "adaptive",
                "full_name": "Alice Example",
                "queries": ["Alice Example alice"],
                "time_budget_seconds": 120,
            },
        )
        run = session.get(ProviderRun, run_id)
        assert run is not None
        run.deadline_at = now + timedelta(seconds=120)

    lease = professional_runs_service._lease_run(
        factory,
        settings=_settings(professional_search_run_lease_seconds=60),
        clock=FixedClock(now),
        provider_run_id=run_id,
    )

    assert lease is not None
    with factory() as session:
        run = session.get(ProviderRun, run_id)
        assert run is not None
        assert run.lease_expires_at.replace(tzinfo=UTC) == now + timedelta(seconds=135)


def test_scheduler_does_nothing_without_a_public_full_name():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, attempt_id = _add_job(factory, now=now)
    with factory() as session, session.begin():
        _add_provider_run(
            session,
            job_id=job_id,
            attempt_id=attempt_id,
            now=now,
            provider_id="maigret_discovery_v1",
            status="success",
            logical_run_id="maigret:root:000",
        )
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert not schedule_professional_search_if_ready(
            session,
            job=job,
            now=now,
            settings=_settings(),
        )
        assert (
            session.scalar(
                select(func.count(ProviderRun.id)).where(
                    ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS)
                )
            )
            == 0
        )


def test_scheduler_respects_master_disable_and_cutoff():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    for disabled, deadline_at in (
        (True, now + timedelta(minutes=5)),
        (False, now),
    ):
        factory = _session_factory()
        job_id, attempt_id = _add_job(factory, now=now, deadline_at=deadline_at)
        with factory() as session, session.begin():
            root_id = _add_provider_run(
                session,
                job_id=job_id,
                attempt_id=attempt_id,
                now=now,
                provider_id="maigret_discovery_v1",
                status="success",
                logical_run_id="maigret:root:000",
            )
            _add_exact_profile_check(
                session,
                job_id=job_id,
                provider_run_id=root_id,
                now=now,
                platform="Instagram",
                display_name="Alice Example",
                ordinal=1,
            )
            job = session.get(SearchJob, job_id)
            assert job is not None
            assert not schedule_professional_search_if_ready(
                session,
                job=job,
                now=now,
                settings=_settings(professional_search_enabled=not disabled),
            )
            assert (
                session.scalar(
                    select(func.count(ProviderRun.id)).where(
                        ProviderRun.provider_id.in_(PROFESSIONAL_PROVIDER_IDS)
                    )
                )
                == 0
            )


def test_missing_exa_key_is_a_terminal_skipped_configuration(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, run_id = _pending_professional_run(
        factory,
        now=now,
        provider_id=EXA_PEOPLE_PROVIDER_ID,
    )
    _disable_finalizer(monkeypatch)

    process_professional_search_run(
        factory,
        settings=_settings(exa_api_key=None),
        clock=FixedClock(now),
        provider_run_id=run_id,
        gateway=object(),
    )

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        attempt = session.scalar(
            select(ProviderAttempt).where(ProviderAttempt.provider_run_id == run_id)
        )
        assert run is not None and run.status == "skipped_configuration"
        assert run.result_count == 0
        assert run.lease_expires_at is None
        assert attempt is not None and attempt.status == "skipped_configuration"
        assert attempt.error_code == "exa_api_key_missing"
        assert (
            session.scalar(
                select(func.count(SourceObservation.id)).where(SourceObservation.job_id == job_id)
            )
            == 0
        )


def test_worker_passes_scheduled_adaptive_exa_envelope_to_adapter(monkeypatch):
    captured: dict[str, object] = {}

    def fake_adaptive_search(**kwargs) -> ProfessionalSearchResult:
        captured.update(kwargs)
        return ProfessionalSearchResult(
            provider_id=EXA_PEOPLE_PROVIDER_ID,
            status="no_result",
            profiles=(),
            error_code="exa_no_linkedin_people_results",
        )

    monkeypatch.setattr(
        professional_runs_service,
        "search_exa_people_adaptive",
        fake_adaptive_search,
    )
    result = professional_runs_service._execute_search(
        settings=_settings(exa_api_key="configured"),
        provider_id=EXA_PEOPLE_PROVIDER_ID,
        query_config={
            "retrieval_mode": "adaptive",
            "full_name": "Alice Example",
            "queries": [
                "Alice Example alice",
                "Alice Example Bay Area",
                "Alice Example Example Labs",
            ],
            "request_budget": 3,
            "result_budget": 11,
            "time_budget_seconds": 90,
            "stagnation_query_limit": 2,
            "max_results": 5,
        },
        gateway=object(),
    )

    assert result.status == "no_result"
    assert captured["queries"] == (
        "Alice Example alice",
        "Alice Example Bay Area",
        "Alice Example Example Labs",
    )
    assert captured["request_budget"] == 3
    assert captured["profile_budget"] == 11
    assert captured["time_budget_seconds"] == 90
    assert captured["stagnation_query_limit"] == 2
    assert captured["max_results_per_query"] == 5


def test_worker_persists_source_linked_professional_account(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, run_id = _pending_professional_run(
        factory,
        now=now,
        provider_id=GITHUB_PROFESSIONAL_PROVIDER_ID,
    )
    _disable_finalizer(monkeypatch)
    result = ProfessionalSearchResult(
        provider_id=GITHUB_PROFESSIONAL_PROVIDER_ID,
        status="success",
        profiles=(_github_profile(),),
    )
    monkeypatch.setattr(
        professional_runs_service,
        "_execute_search",
        lambda **_kwargs: result,
    )

    process_professional_search_run(
        factory,
        settings=_settings(),
        clock=FixedClock(now),
        provider_run_id=run_id,
        gateway=object(),
    )

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        document = session.scalar(
            select(SourceDocument).where(
                SourceDocument.canonical_url == "https://github.com/aliceexample"
            )
        )
        source_use = session.scalar(
            select(ProviderRunSourceUse).where(ProviderRunSourceUse.provider_run_id == run_id)
        )
        observation = session.scalar(
            select(SourceObservation).where(SourceObservation.job_id == job_id)
        )
        node = session.scalar(select(AccountNode).where(AccountNode.job_id == job_id))
        edge = session.scalar(select(DiscoveryEdge).where(DiscoveryEdge.job_id == job_id))
        attempt = session.scalar(
            select(ProviderAttempt).where(ProviderAttempt.provider_run_id == run_id)
        )
        assert run is not None and run.status == "success" and run.result_count == 1
        assert document is not None
        assert document.publisher == "GitHub"
        assert document.lineage_key == "github-profile:aliceexample"
        assert source_use is not None
        assert source_use.document_id == document.id
        assert source_use.disposition == "accepted"
        assert observation is not None
        assert observation.source_use_id == source_use.id
        assert observation.source_type == "first_party_profile_api"
        assert observation.trust_class == "first_party_api"
        assert observation.extracted_fields["display_name"] == "Alice Example"
        assert observation.extracted_fields["location"] == "San Francisco Bay Area"
        assert node is not None
        assert node.canonical_url == document.canonical_url
        assert edge is not None
        assert edge.site_check_id is None
        assert edge.source_observation_id == observation.id
        assert edge.child_account_node_id == node.id
        assert edge.discovery_engine == "github"
        assert attempt is not None and attempt.status == "success"


def test_worker_discards_completion_after_acceptance_epoch_changes(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, run_id = _pending_professional_run(
        factory,
        now=now,
        provider_id=GITHUB_PROFESSIONAL_PROVIDER_ID,
    )
    _disable_finalizer(monkeypatch)

    def supersede_job(**_kwargs) -> ProfessionalSearchResult:
        with factory() as session, session.begin():
            job = session.get(SearchJob, job_id)
            assert job is not None
            job.acceptance_epoch += 1
        return ProfessionalSearchResult(
            provider_id=GITHUB_PROFESSIONAL_PROVIDER_ID,
            status="success",
            profiles=(_github_profile(),),
        )

    monkeypatch.setattr(
        professional_runs_service,
        "_execute_search",
        supersede_job,
    )

    process_professional_search_run(
        factory,
        settings=_settings(),
        clock=FixedClock(now),
        provider_run_id=run_id,
        gateway=object(),
    )

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        attempt = session.scalar(
            select(ProviderAttempt).where(ProviderAttempt.provider_run_id == run_id)
        )
        assert run is not None and run.status == "running"
        assert run.result_count == 0
        assert attempt is not None and attempt.status == "completed_after_fence"
        assert attempt.completion_disposition == "late_payload_discarded"
        assert session.scalar(select(func.count(SourceObservation.id))) == 0
        assert session.scalar(select(func.count(AccountNode.id))) == 0
        assert session.scalar(select(func.count(DiscoveryEdge.id))) == 0


class _RecordingPublisher:
    def __init__(self) -> None:
        self.provider_runs: list[tuple[str, str]] = []
        self.maigret_runs: list[tuple[str, str]] = []
        self.professional_runs: list[tuple[str, str]] = []

    def send_provider_run(self, provider_run_id: str, task_id: str) -> None:
        self.provider_runs.append((provider_run_id, task_id))

    def send_maigret_scan_run(self, provider_run_id: str, task_id: str) -> None:
        self.maigret_runs.append((provider_run_id, task_id))

    def send_professional_search_run(
        self,
        provider_run_id: str,
        task_id: str,
    ) -> None:
        self.professional_runs.append((provider_run_id, task_id))


def test_dispatcher_and_celery_use_the_professional_search_queue():
    factory = _session_factory()
    message_id = new_id()
    with factory() as session, session.begin():
        session.add(
            OutboxMessage(
                id=message_id,
                topic="professional_search_run",
                dedupe_key="professional-search:run-1:generation:1",
                payload={"provider_run_id": "run-1"},
                created_at=datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
                dispatched_at=None,
                attempts=0,
            )
        )

    publisher = _RecordingPublisher()
    assert dispatch_once(factory, publisher)
    assert publisher.provider_runs == []
    assert publisher.maigret_runs == []
    assert publisher.professional_runs == [("run-1", "professional-search:run-1:generation:1")]
    assert "prototype.process_professional_search_run" in celery_app.tasks
    assert celery_app.conf.task_routes["prototype.process_professional_search_run"] == {
        "queue": "professional_search"
    }


def test_reconciler_requeues_professional_run_on_its_dedicated_topic():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, attempt_id = _add_job(factory, now=now)
    with factory() as session, session.begin():
        run_id = _add_provider_run(
            session,
            job_id=job_id,
            attempt_id=attempt_id,
            now=now,
            provider_id=EXA_PEOPLE_PROVIDER_ID,
            status="running",
            logical_run_id="professional:exa:00",
            query_config={"full_name": "Alice Example"},
            lease_generation=2,
            lease_expires_at=now - timedelta(seconds=1),
        )
        session.add(
            ProviderAttempt(
                id=new_id(),
                provider_run_id=run_id,
                generation=2,
                started_at=now - timedelta(minutes=1),
                finished_at=None,
                status="running",
                completion_disposition=None,
                error_code=None,
            )
        )

    assert reclaim_expired_leases(factory, now=now) == 1

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        attempt = session.scalar(
            select(ProviderAttempt).where(
                ProviderAttempt.provider_run_id == run_id,
                ProviderAttempt.generation == 2,
            )
        )
        message = session.scalar(
            select(OutboxMessage).where(
                OutboxMessage.payload["provider_run_id"].as_string() == run_id
            )
        )
        assert run is not None and run.status == "retry_scheduled"
        assert run.lease_expires_at is None
        assert attempt is not None and attempt.status == "abandoned_lease_expired"
        assert attempt.completion_disposition == "late_payload_discarded"
        assert message is not None
        assert message.topic == "professional_search_run"
        assert message.dedupe_key == f"professional-search:{run_id}:generation:3"
