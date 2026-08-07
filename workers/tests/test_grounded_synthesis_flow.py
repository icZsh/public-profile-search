from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace

import httpx
from sqlalchemy import func, select

import apps.api.app.services.grounded_synthesis_runs as synthesis_runs_service
import apps.api.app.services.maigret_runs as maigret_runs_service
import workers.maintenance.reconciler as reconciler_service
import workers.orchestrator.tasks as orchestrator_tasks
from apps.api.app.core.clock import FixedClock
from apps.api.app.core.db import build_engine, build_session_factory
from apps.api.app.models.entities import (
    AccountNode,
    Base,
    DiscoveryEdge,
    GroundedSynthesisResult,
    JobAttempt,
    MaigretSiteCheck,
    OutboxMessage,
    ProviderAttempt,
    ProviderRun,
    SearchJob,
    SourceObservation,
    new_id,
)
from apps.api.app.services.grounded_synthesis_runs import (
    process_grounded_synthesis_run,
)
from apps.api.app.services.grounded_synthesis_scheduling import (
    GROUNDED_SYNTHESIS_PROMPT_VERSION,
    GROUNDED_SYNTHESIS_PROVIDER_ID,
)
from workers.maintenance.outbox_dispatcher import CeleryPublisher, dispatch_once
from workers.maintenance.reconciler import reclaim_expired_leases
from workers.orchestrator.celery_app import celery_app
from workers.providers.grounded_synthesis import (
    GroundedSynthesisOutcome,
    GroundedSynthesisOutput,
    SynthesisUsage,
)


def _session_factory():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def _settings(**overrides):
    values = {
        "grounded_synthesis_enabled": True,
        "openai_api_key": "test-openai-key",
        "grounded_synthesis_run_lease_seconds": 120,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _add_deep_synthesis_run(
    factory,
    *,
    now: datetime,
    run_status: str = "pending",
    run_deadline: datetime | None = None,
    lease_generation: int = 0,
    lease_expires_at: datetime | None = None,
    search_mode: str = "deep",
) -> tuple[str, str, str, str]:
    job_id = new_id()
    attempt_id = new_id()
    maigret_run_id = new_id()
    synthesis_run_id = new_id()
    check_id = new_id()
    node_id = new_id()
    deadline = run_deadline or now + timedelta(minutes=3)
    with factory() as session, session.begin():
        session.add(
            SearchJob(
                id=job_id,
                user_id="synthesis-test-user",
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
        session.add_all(
            [
                ProviderRun(
                    id=maigret_run_id,
                    job_id=job_id,
                    attempt_id=attempt_id,
                    logical_run_id="maigret:root:000",
                    provider_id="maigret_discovery_v1",
                    parent_run_id=None,
                    depth=0,
                    query_config={},
                    status="success",
                    required_for_finalization=True,
                    lease_generation=1,
                    lease_expires_at=None,
                    acceptance_epoch=1,
                    result_count=1,
                    deadline_at=deadline,
                    expires_at=now + timedelta(days=1),
                ),
                ProviderRun(
                    id=synthesis_run_id,
                    job_id=job_id,
                    attempt_id=attempt_id,
                    logical_run_id="synthesis:openai:grounded:v1",
                    provider_id=GROUNDED_SYNTHESIS_PROVIDER_ID,
                    parent_run_id=None,
                    depth=2,
                    query_config={
                        "model": "gpt-5.6-sol",
                        "prompt_version": GROUNDED_SYNTHESIS_PROMPT_VERSION,
                        "reasoning_effort": "low",
                        "max_output_tokens": 1_200,
                        "max_attempts": 3,
                        "retry_backoff_seconds": 0,
                        "max_evidence_items": 40,
                        "max_evidence_characters": 8_000,
                        "budget_seconds": 60,
                    },
                    status=run_status,
                    required_for_finalization=True,
                    lease_generation=lease_generation,
                    lease_expires_at=lease_expires_at,
                    acceptance_epoch=1,
                    result_count=0,
                    deadline_at=deadline,
                    expires_at=now + timedelta(days=1),
                ),
            ]
        )
        session.flush()
        session.add(
            MaigretSiteCheck(
                id=check_id,
                job_id=job_id,
                provider_run_id=maigret_run_id,
                site_key="instagram",
                site_name="Instagram",
                source_name=None,
                queried_identifier="alice",
                queried_identifier_type="username",
                url_main="https://www.instagram.com",
                url_user="https://www.instagram.com/alice",
                url_probe="https://www.instagram.com/alice",
                raw_status="CLAIMED",
                normalized_status="found",
                error_type=None,
                error_context=None,
                http_status=200,
                is_similar=False,
                rank=1,
                tags=["social"],
                extracted_data={
                    "username": "alice",
                    "full_name": "Alice Example",
                    "bio": "Engineer at Example Labs",
                    "followers": 321,
                },
                extracted_usernames={},
                extracted_links=[],
                result_checksum="b" * 64,
                observed_at=now,
            )
        )
        session.add(
            AccountNode(
                id=node_id,
                job_id=job_id,
                platform="Instagram",
                canonical_handle="alice",
                canonical_url="https://www.instagram.com/alice",
                display_name="Alice Example",
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
                provider_run_id=maigret_run_id,
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
        if run_status == "running":
            session.add(
                ProviderAttempt(
                    id=new_id(),
                    provider_run_id=synthesis_run_id,
                    generation=lease_generation,
                    started_at=now - timedelta(minutes=2),
                    finished_at=None,
                    status="running",
                    completion_disposition=None,
                    error_code=None,
                )
            )
    return job_id, attempt_id, synthesis_run_id, check_id


def _success_output(source_id: str) -> GroundedSynthesisOutput:
    return GroundedSynthesisOutput.model_validate(
        {
            "summary": "The public Instagram profile describes an engineering role.",
            "summary_source_ids": [source_id],
            "narrative_sections": [
                {
                    "key": "professional",
                    "title": "Public professional context",
                    "body": "The profile self-describes work in engineering.",
                    "source_ids": [source_id],
                }
            ],
            "claims": [],
            "supporting_reasons": [
                {
                    "text": "The exact public handle exposes the profile description.",
                    "source_ids": [source_id],
                }
            ],
            "limiting_reasons": [
                {
                    "text": "The description is self-reported.",
                    "source_ids": [source_id],
                }
            ],
        }
    )


def test_synthesis_service_materializes_sources_calls_runner_and_persists(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
    )
    finalized: list[str] = []
    observed_call: dict[str, object] = {}

    def fake_finalize(session, *, job, now, settings=None):
        finalized.append(job.id)
        return True

    def fake_runner(**kwargs):
        observed_call.update(kwargs)
        source_id = kwargs["sources"][0].source_id
        return GroundedSynthesisOutcome(
            status="success",
            output=_success_output(source_id),
            usage=SynthesisUsage(
                input_tokens=120,
                output_tokens=80,
                total_tokens=200,
            ),
            error_code=None,
            input_checksum="f" * 64,
            response_id="resp_test",
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        fake_finalize,
    )
    process_grounded_synthesis_run(
        factory,
        settings=_settings(),
        clock=FixedClock(now),
        provider_run_id=run_id,
        synthesizer=fake_runner,
    )

    assert finalized == [job_id]
    assert observed_call["model"] == "gpt-5.6-sol"
    assert observed_call["reasoning_effort"] == "low"
    assert observed_call["max_output_tokens"] == 1_200
    assert observed_call["max_sources"] == 40
    assert observed_call["max_packet_chars"] == 8_000
    assert observed_call["timeout_seconds"] is None
    assert observed_call["seed"].platform == "instagram"
    assert len(observed_call["sources"]) == 1
    source = observed_call["sources"][0]
    assert source.source_type == "first_party_profile"
    assert source.extracted_fields["bio"] == "Engineer at Example Labs"
    assert len(observed_call["accounts"]) == 1
    assert observed_call["accounts"][0].source_ids == (source.source_id,)

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        result = session.get(GroundedSynthesisResult, run_id)
        observation = session.get(SourceObservation, source.source_id)
        attempt = session.scalar(
            select(ProviderAttempt).where(
                ProviderAttempt.provider_run_id == run_id,
                ProviderAttempt.generation == 1,
            )
        )
        assert run is not None and run.status == "success"
        assert run.result_count == 1
        assert run.lease_expires_at is None
        assert result is not None and result.status == "success"
        assert result.output["summary_source_ids"] == [source.source_id]
        assert result.usage == {
            "input_tokens": 120,
            "output_tokens": 80,
            "total_tokens": 200,
            "reasoning_tokens": None,
            "cached_input_tokens": None,
        }
        assert result.input_checksum == "f" * 64
        assert observation is not None
        assert attempt is not None and attempt.status == "success"
        assert attempt.completion_disposition == "in_budget"


def test_synthesis_retries_model_output_defects_on_the_openai_gateway(monkeypatch):
    # Error codes carry no gateway prefix, so the retry set applies to whichever
    # gateway is configured. This previously only retried on OpenRouter, which
    # left the default gateway with no retries at all.
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    _job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(factory, now=now)
    with factory() as session, session.begin():
        run = session.get(ProviderRun, run_id)
        assert run is not None
        run.query_config = {
            **dict(run.query_config),
            "gateway": "openai",
            "max_attempts": 3,
            "retry_backoff_seconds": 0,
        }

    calls = 0

    def flaky_runner(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return GroundedSynthesisOutcome(
                status="invalid_response",
                output=None,
                usage=SynthesisUsage(input_tokens=100, output_tokens=30, total_tokens=130),
                error_code="output_unknown_source_id",
                input_checksum="a" * 64,
                response_id="resp_ungrounded",
                model=kwargs["model"],
            )
        return GroundedSynthesisOutcome(
            status="success",
            output=_success_output(kwargs["sources"][0].source_id),
            usage=SynthesisUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            error_code=None,
            input_checksum="a" * 64,
            response_id="resp_success",
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        lambda *args, **kwargs: True,
    )
    process_grounded_synthesis_run(
        factory,
        settings=_settings(),
        clock=FixedClock(now),
        provider_run_id=run_id,
        synthesizer=flaky_runner,
    )

    assert calls == 2
    with factory() as session:
        run = session.get(ProviderRun, run_id)
        assert run is not None and run.status == "success"


def test_synthesis_retries_truncation_with_a_wider_output_budget(monkeypatch):
    # A truncated response is only worth retrying if the retry gets more room,
    # so the budget has to widen toward the ceiling on each attempt.
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    _job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(factory, now=now)
    with factory() as session, session.begin():
        run = session.get(ProviderRun, run_id)
        assert run is not None
        run.query_config = {
            **dict(run.query_config),
            "max_output_tokens": 16_000,
            "max_attempts": 3,
            "retry_backoff_seconds": 0,
        }

    budgets = []

    def truncating_runner(**kwargs):
        budgets.append(kwargs["max_output_tokens"])
        if len(budgets) < 3:
            return GroundedSynthesisOutcome(
                status="invalid_response",
                output=None,
                usage=SynthesisUsage(input_tokens=100, output_tokens=30, total_tokens=130),
                error_code="incomplete_max_output_tokens",
                input_checksum="a" * 64,
                response_id="resp_truncated",
                model=kwargs["model"],
            )
        return GroundedSynthesisOutcome(
            status="success",
            output=_success_output(kwargs["sources"][0].source_id),
            usage=SynthesisUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            error_code=None,
            input_checksum="a" * 64,
            response_id="resp_success",
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        lambda *args, **kwargs: True,
    )
    process_grounded_synthesis_run(
        factory,
        settings=_settings(),
        clock=FixedClock(now),
        provider_run_id=run_id,
        synthesizer=truncating_runner,
    )

    assert budgets == [16_000, 24_000, 32_000]
    with factory() as session:
        run = session.get(ProviderRun, run_id)
        assert run is not None and run.status == "success"


def test_synthesis_stops_retrying_truncation_once_at_the_ceiling(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    _job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(factory, now=now)
    with factory() as session, session.begin():
        run = session.get(ProviderRun, run_id)
        assert run is not None
        run.query_config = {
            **dict(run.query_config),
            "max_output_tokens": 32_000,
            "max_attempts": 3,
            "retry_backoff_seconds": 0,
        }

    calls = 0

    def truncating_runner(**kwargs):
        nonlocal calls
        calls += 1
        return GroundedSynthesisOutcome(
            status="invalid_response",
            output=None,
            usage=SynthesisUsage(input_tokens=100, output_tokens=30, total_tokens=130),
            error_code="incomplete_max_output_tokens",
            input_checksum="a" * 64,
            response_id="resp_truncated",
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        lambda *args, **kwargs: True,
    )
    process_grounded_synthesis_run(
        factory,
        settings=_settings(),
        clock=FixedClock(now),
        provider_run_id=run_id,
        synthesizer=truncating_runner,
    )

    # No headroom left, so the identical call is not repeated.
    assert calls == 1
    with factory() as session:
        result = session.get(GroundedSynthesisResult, run_id)
        assert result is not None
        assert result.error_code == "incomplete_max_output_tokens"


def test_synthesis_retries_transient_openrouter_failure_and_aggregates_usage(
    monkeypatch,
):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    _job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
    )
    with factory() as session, session.begin():
        run = session.get(ProviderRun, run_id)
        assert run is not None
        run.query_config = {
            **dict(run.query_config),
            "gateway": "openrouter",
            "model": "~deepseek/deepseek-v4-flash-latest",
            "max_attempts": 3,
            "retry_backoff_seconds": 0,
        }

    calls = 0

    def flaky_runner(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return GroundedSynthesisOutcome(
                status="provider_error",
                output=None,
                usage=SynthesisUsage(
                    input_tokens=100,
                    output_tokens=30,
                    total_tokens=130,
                ),
                error_code="provider_unavailable",
                input_checksum="a" * 64,
                response_id="resp_failed",
                model=kwargs["model"],
            )
        source_id = kwargs["sources"][0].source_id
        return GroundedSynthesisOutcome(
            status="success",
            output=_success_output(source_id),
            usage=SynthesisUsage(
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
            ),
            error_code=None,
            input_checksum="a" * 64,
            response_id="resp_success",
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        lambda *args, **kwargs: True,
    )
    process_grounded_synthesis_run(
        factory,
        settings=_settings(openrouter_api_key="test-openrouter-key"),
        clock=FixedClock(now),
        provider_run_id=run_id,
        synthesizer=flaky_runner,
    )

    assert calls == 2
    with factory() as session:
        run = session.get(ProviderRun, run_id)
        result = session.get(GroundedSynthesisResult, run_id)
        assert run is not None and run.status == "success"
        assert result is not None and result.status == "success"
        assert result.error_code is None
        assert result.usage == {
            "input_tokens": 200,
            "output_tokens": 80,
            "total_tokens": 280,
            "reasoning_tokens": None,
            "cached_input_tokens": None,
        }


def test_synthesis_exhausts_transient_retries_before_persisting_fallback(
    monkeypatch,
):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    _job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
    )
    with factory() as session, session.begin():
        run = session.get(ProviderRun, run_id)
        assert run is not None
        run.query_config = {
            **dict(run.query_config),
            "gateway": "openrouter",
            "max_attempts": 3,
            "retry_backoff_seconds": 0,
        }

    calls = 0

    def unavailable_runner(**kwargs):
        nonlocal calls
        calls += 1
        return GroundedSynthesisOutcome(
            status="provider_error",
            output=None,
            usage=SynthesisUsage(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
            ),
            error_code="provider_unavailable",
            input_checksum="c" * 64,
            response_id=f"resp_failed_{calls}",
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        lambda *args, **kwargs: True,
    )
    process_grounded_synthesis_run(
        factory,
        settings=_settings(openrouter_api_key="test-openrouter-key"),
        clock=FixedClock(now),
        provider_run_id=run_id,
        synthesizer=unavailable_runner,
    )

    assert calls == 3
    with factory() as session:
        result = session.get(GroundedSynthesisResult, run_id)
        provider_attempt_count = session.scalar(
            select(func.count(ProviderAttempt.id)).where(
                ProviderAttempt.provider_run_id == run_id
            )
        )
        assert result is not None and result.status == "provider_error"
        assert result.error_code == "provider_unavailable"
        assert result.usage == {
            "input_tokens": 30,
            "output_tokens": 15,
            "total_tokens": 45,
            "reasoning_tokens": None,
            "cached_input_tokens": None,
        }
        assert provider_attempt_count == 1


def test_synthesis_does_not_retry_model_refusal(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    _job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
    )
    calls = 0

    def refusal_runner(**kwargs):
        nonlocal calls
        calls += 1
        return GroundedSynthesisOutcome(
            status="invalid_response",
            output=None,
            usage=None,
            error_code="response_refusal",
            input_checksum="b" * 64,
            response_id="resp_invalid",
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        lambda *args, **kwargs: True,
    )
    process_grounded_synthesis_run(
        factory,
        settings=_settings(),
        clock=FixedClock(now),
        provider_run_id=run_id,
        synthesizer=refusal_runner,
    )

    assert calls == 1


def test_synthesis_service_uses_snapshotted_openrouter_gateway(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    _job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
    )
    with factory() as session, session.begin():
        run = session.get(ProviderRun, run_id)
        assert run is not None
        run.query_config = {
            **dict(run.query_config),
            "gateway": "openrouter",
            "model": "openai/gpt-5.6-sol",
        }

    observed_call: dict[str, object] = {}

    def fake_runner(**kwargs):
        observed_call.update(kwargs)
        return GroundedSynthesisOutcome(
            status="no_result",
            output=None,
            usage=None,
            error_code="synthesis_no_evidence",
            input_checksum="a" * 64,
            response_id=None,
            model=kwargs["model"],
        )

    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        lambda *args, **kwargs: True,
    )
    process_grounded_synthesis_run(
        factory,
        settings=_settings(
            grounded_synthesis_provider="openai",
            openai_api_key="wrong-gateway-key",
            openrouter_api_key="test-openrouter-key",
            openrouter_http_referer="http://localhost:3417",
            openrouter_app_title="tracebrief test",
        ),
        clock=FixedClock(now),
        provider_run_id=run_id,
        synthesizer=fake_runner,
    )

    assert observed_call["provider"] == "openrouter"
    assert observed_call["api_key"] == "test-openrouter-key"
    assert observed_call["model"] == "openai/gpt-5.6-sol"
    assert observed_call["http_referer"] == "http://localhost:3417"
    assert observed_call["app_title"] == "tracebrief test"


def test_synthesis_service_missing_key_persists_fallback_without_network(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    _job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
    )
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        lambda *args, **kwargs: True,
    )
    process_grounded_synthesis_run(
        factory,
        settings=_settings(openai_api_key=None),
        clock=FixedClock(now),
        provider_run_id=run_id,
        transport=httpx.MockTransport(handler),
    )

    assert not called
    with factory() as session:
        run = session.get(ProviderRun, run_id)
        result = session.get(GroundedSynthesisResult, run_id)
        assert run is not None and run.status == "skipped_configuration"
        assert result is not None and result.output is None
        assert result.error_code == "api_key_missing"


def test_synthesis_service_never_runs_for_quick_job():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    _job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
        search_mode="quick",
    )
    runner_called = False

    def runner(**kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("Quick jobs must not invoke synthesis")

    process_grounded_synthesis_run(
        factory,
        settings=_settings(),
        clock=FixedClock(now),
        provider_run_id=run_id,
        synthesizer=runner,
    )

    assert not runner_called
    with factory() as session:
        run = session.get(ProviderRun, run_id)
        assert run is not None and run.status == "cancelled"
        assert session.get(GroundedSynthesisResult, run_id) is None
        assert session.scalar(select(func.count(SourceObservation.id))) == 0


def test_synthesis_completion_is_discarded_after_acceptance_fence(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
    )

    def superseding_runner(**kwargs):
        with factory() as session, session.begin():
            job = session.get(SearchJob, job_id)
            assert job is not None
            job.acceptance_epoch += 1
        source_id = kwargs["sources"][0].source_id
        return GroundedSynthesisOutcome(
            status="success",
            output=_success_output(source_id),
            usage=None,
            error_code=None,
            input_checksum="e" * 64,
            response_id="resp_late",
            model="gpt-5.6-sol",
        )

    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        lambda *args, **kwargs: True,
    )
    process_grounded_synthesis_run(
        factory,
        settings=_settings(),
        clock=FixedClock(now),
        provider_run_id=run_id,
        synthesizer=superseding_runner,
    )

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        attempt = session.scalar(
            select(ProviderAttempt).where(ProviderAttempt.provider_run_id == run_id)
        )
        assert run is not None and run.status == "running"
        assert attempt is not None and attempt.status == "completed_after_fence"
        assert attempt.completion_disposition == "late_payload_discarded"
        assert session.get(GroundedSynthesisResult, run_id) is None


def test_synthesis_dispatched_after_old_deadline_runs_and_persists(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
        run_deadline=now - timedelta(seconds=1),
    )
    runner_called = False
    finalized: list[str] = []

    def runner(**kwargs):
        nonlocal runner_called
        runner_called = True
        source_id = kwargs["sources"][0].source_id
        return GroundedSynthesisOutcome(
            status="success",
            output=_success_output(source_id),
            usage=None,
            error_code=None,
            input_checksum="d" * 64,
            response_id="resp_after_old_deadline",
            model=kwargs["model"],
        )

    def fake_finalize(session, *, job, now, settings=None):
        finalized.append(job.id)
        return True

    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        fake_finalize,
    )
    process_grounded_synthesis_run(
        factory,
        settings=_settings(),
        clock=FixedClock(now),
        provider_run_id=run_id,
        synthesizer=runner,
    )

    assert runner_called
    assert finalized == [job_id]
    with factory() as session:
        run = session.get(ProviderRun, run_id)
        result = session.get(GroundedSynthesisResult, run_id)
        attempt_count = session.scalar(
            select(func.count(ProviderAttempt.id)).where(ProviderAttempt.provider_run_id == run_id)
        )
        assert run is not None and run.status == "success"
        assert result is not None and result.status == "success"
        assert result.error_code is None
        assert attempt_count == 1


def test_synthesis_heartbeat_renews_lease_during_unbounded_call(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    clock = FixedClock(now)
    factory = _session_factory()
    _job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
    )
    renewed = Event()
    original_renew = synthesis_runs_service._renew_synthesis_lease

    def recording_renew(*args, **kwargs):
        result = original_renew(*args, **kwargs)
        if result:
            renewed.set()
        return result

    monkeypatch.setattr(
        synthesis_runs_service,
        "_lease_heartbeat_interval",
        lambda _lease_seconds: 0.01,
    )
    monkeypatch.setattr(
        synthesis_runs_service,
        "_renew_synthesis_lease",
        recording_renew,
    )
    monkeypatch.setattr(
        maigret_runs_service,
        "finalize_discovery_if_complete",
        lambda *args, **kwargs: True,
    )

    def slow_runner(**kwargs):
        clock.value = now + timedelta(minutes=10)
        assert renewed.wait(timeout=1.0)
        with factory() as session:
            run = session.get(ProviderRun, run_id)
            assert run is not None
            assert run.lease_expires_at.replace(tzinfo=UTC) > clock.value
        source_id = kwargs["sources"][0].source_id
        return GroundedSynthesisOutcome(
            status="success",
            output=_success_output(source_id),
            usage=None,
            error_code=None,
            input_checksum="c" * 64,
            response_id="resp_slow",
            model=kwargs["model"],
        )

    process_grounded_synthesis_run(
        factory,
        settings=_settings(grounded_synthesis_run_lease_seconds=30),
        clock=clock,
        provider_run_id=run_id,
        synthesizer=slow_runner,
    )

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        result = session.get(GroundedSynthesisResult, run_id)
        assert run is not None and run.status == "success"
        assert run.lease_expires_at is None
        assert result is not None and result.status == "success"


def test_synthesis_ownership_loss_cancels_provider_io_and_discards_output(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
    )

    class FenceThenBlockTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.cancelled = Event()

        async def handle_async_request(self, _request: httpx.Request) -> httpx.Response:
            with factory() as session, session.begin():
                job = session.get(SearchJob, job_id)
                assert job is not None
                job.acceptance_epoch += 1
            try:
                await asyncio.wait_for(asyncio.Event().wait(), timeout=2.0)
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
            raise AssertionError("Ownership loss did not cancel provider I/O")

    transport = FenceThenBlockTransport()
    monkeypatch.setattr(
        synthesis_runs_service,
        "_lease_heartbeat_interval",
        lambda _lease_seconds: 0.01,
    )
    process_grounded_synthesis_run(
        factory,
        settings=_settings(),
        clock=FixedClock(now),
        provider_run_id=run_id,
        transport=transport,
    )

    assert transport.cancelled.is_set()
    with factory() as session:
        run = session.get(ProviderRun, run_id)
        result = session.get(GroundedSynthesisResult, run_id)
        attempt = session.scalar(
            select(ProviderAttempt).where(ProviderAttempt.provider_run_id == run_id)
        )
        assert run is not None and run.status == "running"
        assert result is None
        assert attempt is not None and attempt.status == "completed_after_fence"
        assert attempt.completion_disposition == "late_payload_discarded"


class _RecordingPublisher:
    def __init__(self) -> None:
        self.provider_runs: list[tuple[str, str]] = []
        self.maigret_runs: list[tuple[str, str]] = []
        self.professional_runs: list[tuple[str, str]] = []
        self.synthesis_runs: list[tuple[str, str]] = []

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

    def send_grounded_synthesis_run(
        self,
        provider_run_id: str,
        task_id: str,
    ) -> None:
        self.synthesis_runs.append((provider_run_id, task_id))


def test_dispatcher_and_celery_use_grounded_synthesis_queue():
    factory = _session_factory()
    message_id = new_id()
    with factory() as session, session.begin():
        session.add(
            OutboxMessage(
                id=message_id,
                topic="grounded_synthesis_run",
                dedupe_key="grounded-synthesis:run-1:generation:1",
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
    assert publisher.professional_runs == []
    assert publisher.synthesis_runs == [("run-1", "grounded-synthesis:run-1:generation:1")]
    assert "prototype.process_grounded_synthesis_run" in celery_app.tasks
    synthesis_task = celery_app.tasks["prototype.process_grounded_synthesis_run"]
    assert synthesis_task.acks_late is True
    assert synthesis_task.acks_on_failure_or_timeout is False
    assert synthesis_task.reject_on_worker_lost is True
    assert celery_app.conf.task_routes["prototype.process_grounded_synthesis_run"] == {
        "queue": "grounded_synthesis"
    }
    assert "process_grounded_synthesis_run_task" in orchestrator_tasks.__all__


def test_celery_publisher_sends_synthesis_task_to_dedicated_queue(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_send_task(name, *, args, task_id, queue):
        calls.append(
            {
                "name": name,
                "args": args,
                "task_id": task_id,
                "queue": queue,
            }
        )

    monkeypatch.setattr(celery_app, "send_task", fake_send_task)
    CeleryPublisher().send_grounded_synthesis_run(
        "run-1",
        "grounded-synthesis:run-1:generation:1",
    )

    assert calls == [
        {
            "name": "prototype.process_grounded_synthesis_run",
            "args": ["run-1"],
            "task_id": "grounded-synthesis:run-1:generation:1",
            "queue": "grounded_synthesis",
        }
    ]


def test_reconciler_closes_ambiguous_synthesis_lease_without_requeue(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
        run_status="running",
        lease_generation=2,
        lease_expires_at=now - timedelta(seconds=1),
    )
    with factory() as session, session.begin():
        run = session.get(ProviderRun, run_id)
        assert run is not None
        run.deadline_at = None
    finalized: list[str] = []

    def fake_finalize(session, *, job, now, settings=None):
        finalized.append(job.id)
        return True

    monkeypatch.setattr(
        reconciler_service,
        "finalize_discovery_if_complete",
        fake_finalize,
    )
    assert reclaim_expired_leases(factory, now=now) == 1

    assert finalized == [job_id]
    with factory() as session:
        run = session.get(ProviderRun, run_id)
        result = session.get(GroundedSynthesisResult, run_id)
        attempt = session.scalar(
            select(ProviderAttempt).where(
                ProviderAttempt.provider_run_id == run_id,
                ProviderAttempt.generation == 2,
            )
        )
        message_count = session.scalar(select(func.count(OutboxMessage.id)))
        assert run is not None and run.status == "provider_error"
        assert run.lease_expires_at is None
        assert attempt is not None and attempt.status == "abandoned_lease_expired"
        assert attempt.completion_disposition == "late_payload_discarded"
        assert result is not None and result.status == "provider_error"
        assert result.error_code == "grounded_synthesis_lease_expired_ambiguous"
        assert message_count == 0


def test_reconciler_closes_ambiguous_adaptive_professional_lease(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
        run_status="running",
        lease_generation=2,
        lease_expires_at=now - timedelta(seconds=1),
    )
    with factory() as session, session.begin():
        run = session.get(ProviderRun, run_id)
        assert run is not None
        run.provider_id = "exa_people_search_v1"
        run.query_config = {
            "retrieval_mode": "adaptive",
            "full_name": "Alice Example",
        }
    finalized: list[str] = []

    def fake_finalize(session, *, job, now, settings=None):
        finalized.append(job.id)
        return True

    monkeypatch.setattr(
        reconciler_service,
        "finalize_discovery_if_complete",
        fake_finalize,
    )
    assert reclaim_expired_leases(factory, now=now) == 1

    assert finalized == [job_id]
    with factory() as session:
        run = session.get(ProviderRun, run_id)
        attempt = session.scalar(
            select(ProviderAttempt).where(
                ProviderAttempt.provider_run_id == run_id,
                ProviderAttempt.generation == 2,
            )
        )
        message_count = session.scalar(select(func.count(OutboxMessage.id)))
        assert run is not None and run.status == "provider_error"
        assert run.lease_expires_at is None
        assert attempt is not None and attempt.status == "abandoned_lease_expired"
        assert message_count == 0


def test_reconciler_closes_synthesis_at_cutoff_and_records_fallback(monkeypatch):
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _session_factory()
    job_id, _attempt_id, run_id, _check_id = _add_deep_synthesis_run(
        factory,
        now=now,
        run_status="running",
        run_deadline=now - timedelta(seconds=1),
        lease_generation=1,
        lease_expires_at=now - timedelta(seconds=2),
    )
    finalized: list[str] = []

    def fake_finalize(session, *, job, now, settings=None):
        finalized.append(job.id)
        return True

    monkeypatch.setattr(
        reconciler_service,
        "finalize_discovery_if_complete",
        fake_finalize,
    )
    assert reclaim_expired_leases(factory, now=now) == 1

    assert finalized == [job_id]
    with factory() as session:
        run = session.get(ProviderRun, run_id)
        result = session.get(GroundedSynthesisResult, run_id)
        message_count = session.scalar(select(func.count(OutboxMessage.id)))
        assert run is not None and run.status == "closed_at_cutoff"
        assert result is not None and result.status == "closed_at_cutoff"
        assert result.error_code == "grounded_synthesis_deadline_exceeded"
        assert message_count == 0
