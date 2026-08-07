from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pydantic import SecretStr
from sqlalchemy import func, select

from apps.api.app.core.db import build_engine, build_session_factory
from apps.api.app.models.entities import (
    Base,
    GroundedSynthesisResult,
    JobAttempt,
    OutboxMessage,
    ProviderRun,
    SearchJob,
    new_id,
)
from apps.api.app.services.grounded_synthesis_scheduling import (
    GROUNDED_SYNTHESIS_PROVIDER_ID,
    schedule_grounded_synthesis_if_ready,
)


def _factory():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def _add_job(factory, *, now: datetime, search_mode: str, run_status: str) -> str:
    job_id = new_id()
    attempt_id = new_id()
    with factory() as session, session.begin():
        session.add(
            SearchJob(
                id=job_id,
                user_id="test-user",
                retry_of_job_id=None,
                normalized_identifier_hmac="a" * 64,
                canonical_input_url_ciphertext=None,
                input_provider_id="maigret_discovery_v1",
                canonicalization_version="seed-identifier-v1",
                eligibility_verification_id=None,
                job_kind="footprint_discovery",
                seed_kind="platform_identifier",
                seed_platform="instagram",
                seed_identifier_type="handle",
                seed_identifier="octaviyao",
                normalized_seed="instagram:handle:octaviyao",
                search_mode=search_mode,
                catalog_profile="quick",
                catalog_snapshot_id=None,
                exploration_status="running",
                purpose="digital_footprint",
                fixture_key=None,
                status="discovering",
                active_attempt_id=attempt_id,
                accepted_at=now,
                collection_cutoff_at=now + timedelta(minutes=5),
                fallback_at=now + timedelta(minutes=5),
                deadline_at=now + timedelta(minutes=5),
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
        session.flush()
        session.add(
            ProviderRun(
                id=new_id(),
                job_id=job_id,
                attempt_id=attempt_id,
                logical_run_id="maigret:root:000",
                provider_id="maigret_discovery_v1",
                parent_run_id=None,
                depth=0,
                query_config={"site_names": ["Instagram"]},
                status=run_status,
                required_for_finalization=True,
                lease_generation=1,
                lease_expires_at=None,
                acceptance_epoch=1,
                result_count=1,
                deadline_at=now + timedelta(minutes=4),
                expires_at=now + timedelta(days=1),
            )
        )
    return job_id


def test_quick_mode_never_schedules_grounded_synthesis():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _factory()
    job_id = _add_job(factory, now=now, search_mode="quick", run_status="success")

    with factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert not schedule_grounded_synthesis_if_ready(
            session,
            job=job,
            now=now,
            settings=SimpleNamespace(grounded_synthesis_enabled=True),
        )

    with factory() as session:
        assert (
            session.scalar(
                select(func.count(ProviderRun.id)).where(
                    ProviderRun.provider_id == GROUNDED_SYNTHESIS_PROVIDER_ID
                )
            )
            == 0
        )


def test_deep_mode_records_missing_key_and_continues_without_outbox():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _factory()
    job_id = _add_job(factory, now=now, search_mode="deep", run_status="success")

    with factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert not schedule_grounded_synthesis_if_ready(
            session,
            job=job,
            now=now,
            settings=SimpleNamespace(
                grounded_synthesis_enabled=True,
                openai_api_key=None,
            ),
        )

    with factory() as session:
        run = session.scalar(
            select(ProviderRun).where(
                ProviderRun.job_id == job_id,
                ProviderRun.provider_id == GROUNDED_SYNTHESIS_PROVIDER_ID,
            )
        )
        result = session.get(GroundedSynthesisResult, run.id if run else "")
        assert run is not None and run.status == "skipped_configuration"
        assert result is not None
        assert result.error_code == "openai_api_key_missing"
        assert session.scalar(select(func.count(OutboxMessage.id))) == 0


def test_deep_mode_schedules_exactly_one_fenced_synthesis_run():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _factory()
    job_id = _add_job(factory, now=now, search_mode="deep", run_status="success")
    settings = SimpleNamespace(
        grounded_synthesis_enabled=True,
        openai_api_key=SecretStr("test-key"),
        openai_synthesis_model="gpt-5.6",
    )

    with factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert schedule_grounded_synthesis_if_ready(
            session,
            job=job,
            now=now,
            settings=settings,
        )
        assert not schedule_grounded_synthesis_if_ready(
            session,
            job=job,
            now=now,
            settings=settings,
        )

    with factory() as session:
        run = session.scalar(
            select(ProviderRun).where(
                ProviderRun.job_id == job_id,
                ProviderRun.provider_id == GROUNDED_SYNTHESIS_PROVIDER_ID,
            )
        )
        message = session.scalar(
            select(OutboxMessage).where(OutboxMessage.topic == "grounded_synthesis_run")
        )
        assert run is not None and run.status == "pending"
        assert run.logical_run_id == "synthesis:openai:grounded:v2"
        assert run.query_config["gateway"] == "openai"
        assert run.query_config["model"] == "gpt-5.6"
        assert "budget_seconds" not in run.query_config
        assert run.deadline_at is None
        assert message is not None
        assert message.payload == {"provider_run_id": run.id}


def test_deep_mode_snapshots_openrouter_gateway_and_model():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _factory()
    job_id = _add_job(factory, now=now, search_mode="deep", run_status="success")
    settings = SimpleNamespace(
        grounded_synthesis_enabled=True,
        grounded_synthesis_provider="openrouter",
        openrouter_api_key=SecretStr("test-openrouter-key"),
        openrouter_synthesis_model="~deepseek/deepseek-v4-flash-latest",
    )

    with factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert schedule_grounded_synthesis_if_ready(
            session,
            job=job,
            now=now,
            settings=settings,
        )

    with factory() as session:
        run = session.scalar(
            select(ProviderRun).where(
                ProviderRun.job_id == job_id,
                ProviderRun.provider_id == GROUNDED_SYNTHESIS_PROVIDER_ID,
            )
        )
        assert run is not None and run.status == "pending"
        assert run.logical_run_id == "synthesis:openrouter:grounded:v2"
        assert run.query_config["gateway"] == "openrouter"
        assert run.query_config["model"] == "~deepseek/deepseek-v4-flash-latest"
        assert run.query_config["max_output_tokens"] == 32_000
        assert run.query_config["max_attempts"] == 3
        assert run.query_config["retry_backoff_seconds"] == 2


def test_deep_mode_records_missing_openrouter_key():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _factory()
    job_id = _add_job(factory, now=now, search_mode="deep", run_status="success")

    with factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert not schedule_grounded_synthesis_if_ready(
            session,
            job=job,
            now=now,
            settings=SimpleNamespace(
                grounded_synthesis_enabled=True,
                grounded_synthesis_provider="openrouter",
                openrouter_api_key=None,
            ),
        )

    with factory() as session:
        run = session.scalar(
            select(ProviderRun).where(
                ProviderRun.job_id == job_id,
                ProviderRun.provider_id == GROUNDED_SYNTHESIS_PROVIDER_ID,
            )
        )
        result = session.get(GroundedSynthesisResult, run.id if run else "")
        assert run is not None and run.status == "skipped_configuration"
        assert run.query_config["gateway"] == "openrouter"
        assert result is not None
        assert result.error_code == "openrouter_api_key_missing"


def test_deep_mode_waits_for_nonterminal_retrieval():
    now = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    factory = _factory()
    job_id = _add_job(factory, now=now, search_mode="deep", run_status="running")

    with factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert not schedule_grounded_synthesis_if_ready(
            session,
            job=job,
            now=now,
            settings=SimpleNamespace(
                grounded_synthesis_enabled=True,
                openai_api_key=SecretStr("test-key"),
            ),
        )

    with factory() as session:
        assert (
            session.scalar(
                select(func.count(ProviderRun.id)).where(
                    ProviderRun.provider_id == GROUNDED_SYNTHESIS_PROVIDER_ID
                )
            )
            == 0
        )


def test_deep_mode_schedules_after_bounded_retrieval_cutoff():
    accepted_at = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    after_cutoff = accepted_at + timedelta(minutes=6)
    factory = _factory()
    job_id = _add_job(
        factory,
        now=accepted_at,
        search_mode="deep",
        run_status="success",
    )

    with factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert job.deadline_at.replace(tzinfo=UTC) < after_cutoff
        assert schedule_grounded_synthesis_if_ready(
            session,
            job=job,
            now=after_cutoff,
            settings=SimpleNamespace(
                grounded_synthesis_enabled=True,
                openai_api_key=SecretStr("test-key"),
            ),
        )

    with factory() as session:
        run = session.scalar(
            select(ProviderRun).where(
                ProviderRun.job_id == job_id,
                ProviderRun.provider_id == GROUNDED_SYNTHESIS_PROVIDER_ID,
            )
        )
        assert run is not None and run.status == "pending"
        assert run.deadline_at is None
