from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import delete, func, select

from apps.api.app.core.clock import FixedClock
from apps.api.app.core.db import build_engine, build_session_factory
from apps.api.app.models.entities import (
    AccountNode,
    Base,
    DiscoveredIdentifier,
    DiscoveryEdge,
    JobAttempt,
    JobDeletionTombstone,
    MaigretCatalogSnapshot,
    MaigretScanRun,
    MaigretSiteCheck,
    OutboxMessage,
    ProviderAttempt,
    ProviderRun,
    SearchJob,
    new_id,
)
from apps.api.app.services.deletion import delete_job
from apps.api.app.services.maigret_runs import process_maigret_scan_run
from workers.maintenance.deadline_watchdog import finalize_expired_jobs
from workers.maintenance.outbox_dispatcher import dispatch_once, maintenance_once
from workers.maintenance.reconciler import reclaim_expired_leases
from workers.maintenance.retention import remove_expired_search_jobs
from workers.orchestrator.celery_app import celery_app


def session_factory():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def add_maigret_run(factory, *, now: datetime, deadline_at: datetime) -> tuple[str, str, str]:
    snapshot_id = new_id()
    job_id = new_id()
    attempt_id = new_id()
    provider_run_id = new_id()
    with factory() as session, session.begin():
        session.add(
            MaigretCatalogSnapshot(
                id=snapshot_id,
                package_version="0.6.3",
                upstream_revision="fixture-revision",
                database_checksum="a" * 64,
                manifest_checksum="b" * 64,
                catalog_site_count=1,
                selection_policy={"profiles": {"quick": {"site_names": ["Example"]}}},
                created_at=now,
            )
        )
        session.add(
            SearchJob(
                id=job_id,
                user_id="test-user",
                refresh_of_job_id=None,
                history_reuse_policy=None,
                normalized_identifier_hmac="c" * 64,
                canonical_input_url_ciphertext=None,
                input_provider_id="maigret_discovery_v1",
                canonicalization_version="seed-identifier-v1",
                eligibility_verification_id=None,
                job_kind="footprint_discovery",
                seed_kind="bare_handle",
                seed_platform=None,
                seed_identifier_type="handle",
                seed_identifier="alice",
                normalized_seed="*:handle:alice",
                search_mode="quick",
                catalog_profile="quick",
                catalog_snapshot_id=snapshot_id,
                exploration_status="running",
                purpose="digital_footprint",
                fixture_key=None,
                status="discovering",
                active_attempt_id=attempt_id,
                accepted_at=now,
                collection_cutoff_at=deadline_at,
                fallback_at=deadline_at,
                deadline_at=deadline_at,
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
                id=provider_run_id,
                job_id=job_id,
                attempt_id=attempt_id,
                logical_run_id="maigret:root:000",
                provider_id="maigret_discovery_v1",
                parent_run_id=None,
                depth=0,
                query_config={"site_names": ["Example"]},
                status="running",
                required_for_finalization=True,
                lease_generation=1,
                lease_expires_at=now - timedelta(seconds=1),
                acceptance_epoch=1,
                result_count=0,
                deadline_at=deadline_at,
                expires_at=now + timedelta(days=1),
            )
        )
        session.flush()
        session.add(
            MaigretScanRun(
                provider_run_id=provider_run_id,
                catalog_snapshot_id=snapshot_id,
                product_identifier_type="handle",
                maigret_identifier_type="username",
                identifier_value="alice",
                site_names=["Example"],
                selected_site_manifest_checksum="d" * 64,
                scan_profile="quick",
                status="running",
                selected_count=1,
                completed_count=0,
                found_count=0,
                not_found_count=0,
                unknown_count=0,
                illegal_count=0,
                timeout_seconds=3,
                max_connections=1,
                started_at=now - timedelta(seconds=30),
                finished_at=None,
                error_code=None,
            )
        )
        session.add(
            ProviderAttempt(
                provider_run_id=provider_run_id,
                generation=1,
                started_at=now - timedelta(seconds=30),
                finished_at=None,
                status="running",
                completion_disposition=None,
                error_code=None,
            )
        )
    return snapshot_id, job_id, provider_run_id


class RecordingPublisher:
    def __init__(self) -> None:
        self.provider_runs: list[tuple[str, str]] = []
        self.maigret_runs: list[tuple[str, str]] = []

    def send_provider_run(
        self, provider_run_id: str, task_id: str, *, priority: int = 0
    ) -> None:
        self.provider_runs.append((provider_run_id, task_id))

    def send_maigret_scan_run(
        self, provider_run_id: str, task_id: str, *, priority: int = 0
    ) -> None:
        self.maigret_runs.append((provider_run_id, task_id))


def test_dispatcher_routes_maigret_outbox_to_dedicated_task():
    factory = session_factory()
    message_id = new_id()
    with factory() as session, session.begin():
        session.add(
            OutboxMessage(
                id=message_id,
                topic="maigret_scan_run",
                dedupe_key="maigret-scan:run-1:generation:1",
                payload={"provider_run_id": "run-1", "scan_run_id": "run-1"},
                created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
                dispatched_at=None,
                attempts=0,
            )
        )

    publisher = RecordingPublisher()
    assert dispatch_once(factory, publisher) is True
    assert publisher.provider_runs == []
    assert publisher.maigret_runs == [("run-1", "maigret-scan:run-1:generation:1")]
    with factory() as session:
        message = session.get(OutboxMessage, message_id)
        assert message is not None
        assert message.attempts == 1
        assert message.dispatched_at is not None


def test_dispatcher_sends_high_priority_history_revalidation_first():
    factory = session_factory()
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    low_id = new_id()
    high_id = new_id()
    with factory() as session, session.begin():
        session.add_all(
            [
                OutboxMessage(
                    id=low_id,
                    topic="maigret_scan_run",
                    dedupe_key="maigret-scan:low:generation:1",
                    payload={"provider_run_id": "low", "scan_run_id": "low"},
                    priority=0,
                    created_at=now,
                    dispatched_at=None,
                    attempts=0,
                ),
                OutboxMessage(
                    id=high_id,
                    topic="maigret_scan_run",
                    dedupe_key="maigret-scan:high:generation:1",
                    payload={"provider_run_id": "high", "scan_run_id": "high"},
                    priority=9,
                    created_at=now,
                    dispatched_at=None,
                    attempts=0,
                ),
            ]
        )

    class PriorityRecordingPublisher:
        def __init__(self) -> None:
            self.maigret_runs: list[tuple[str, str, int]] = []

        def send_maigret_scan_run(
            self,
            provider_run_id: str,
            task_id: str,
            *,
            priority: int = 0,
        ) -> None:
            self.maigret_runs.append((provider_run_id, task_id, priority))

    publisher = PriorityRecordingPublisher()
    assert dispatch_once(factory, publisher) is True
    assert publisher.maigret_runs == [("high", "maigret-scan:high:generation:1", 9)]
    with factory() as session:
        high = session.get(OutboxMessage, high_id)
        low = session.get(OutboxMessage, low_id)
        assert high is not None and high.dispatched_at is not None
        assert low is not None and low.dispatched_at is None


def test_retention_fences_and_deletes_an_expired_active_job():
    factory = session_factory()
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    _snapshot_id, job_id, provider_run_id = add_maigret_run(
        factory,
        now=now,
        deadline_at=now + timedelta(minutes=5),
    )
    with factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None and job.status == "discovering"
        job.expires_at = now - timedelta(seconds=1)

    assert remove_expired_search_jobs(factory, now=now, batch_size=1) == 1
    with factory() as session:
        assert session.get(SearchJob, job_id) is None
        assert session.get(ProviderRun, provider_run_id) is None
        tombstone = session.get(JobDeletionTombstone, job_id)
        assert tombstone is not None
        assert tombstone.write_fence == 2
        assert tombstone.deleted_at.replace(tzinfo=UTC) == now


def test_celery_registers_maigret_task_and_queue_route():
    assert "prototype.process_maigret_scan_run" in celery_app.tasks
    assert celery_app.conf.task_routes["prototype.process_maigret_scan_run"] == {
        "queue": "maigret_scan"
    }


def test_reconciler_retries_maigret_run_on_the_same_queue():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    factory = session_factory()
    _snapshot_id, _job_id, run_id = add_maigret_run(
        factory,
        now=now,
        deadline_at=now + timedelta(minutes=2),
    )

    assert reclaim_expired_leases(factory, now=now) == 1

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        scan = session.get(MaigretScanRun, run_id)
        attempt = session.scalar(
            select(ProviderAttempt).where(
                ProviderAttempt.provider_run_id == run_id,
                ProviderAttempt.generation == 1,
            )
        )
        message = session.scalar(
            select(OutboxMessage).where(
                OutboxMessage.payload["provider_run_id"].as_string() == run_id
            )
        )
        assert run is not None and run.status == "retry_scheduled"
        assert run.lease_expires_at is None
        assert scan is not None and scan.status == "retry_scheduled"
        assert scan.error_code == "maigret_lease_expired"
        assert attempt is not None and attempt.status == "abandoned_lease_expired"
        assert attempt.error_code == "lease_expired"
        assert message is not None
        assert message.topic == "maigret_scan_run"
        assert message.dedupe_key == f"maigret-scan:{run_id}:generation:2"


def test_maintenance_pass_reclaims_expired_running_maigret_shard():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    factory = session_factory()
    _snapshot_id, _job_id, run_id = add_maigret_run(
        factory,
        now=now,
        deadline_at=now + timedelta(minutes=2),
    )

    maintenance_once(
        factory,
        settings=SimpleNamespace(),
        clock=FixedClock(now),
    )

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        scan = session.get(MaigretScanRun, run_id)
        attempt = session.scalar(
            select(ProviderAttempt).where(
                ProviderAttempt.provider_run_id == run_id,
                ProviderAttempt.generation == 1,
            )
        )
        retry_message = session.scalar(
            select(OutboxMessage).where(
                OutboxMessage.payload["provider_run_id"].as_string() == run_id,
                OutboxMessage.dispatched_at.is_(None),
            )
        )
        assert run is not None and run.status == "retry_scheduled"
        assert run.lease_expires_at is None
        assert scan is not None and scan.status == "retry_scheduled"
        assert scan.error_code == "maigret_lease_expired"
        assert attempt is not None and attempt.status == "abandoned_lease_expired"
        assert attempt.error_code == "lease_expired"
        assert retry_message is not None
        assert retry_message.topic == "maigret_scan_run"


def test_reconciler_closes_expired_maigret_run_at_cutoff_without_retry():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    factory = session_factory()
    _snapshot_id, job_id, run_id = add_maigret_run(
        factory,
        now=now,
        deadline_at=now - timedelta(seconds=1),
    )

    assert reclaim_expired_leases(factory, now=now) == 1

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        scan = session.get(MaigretScanRun, run_id)
        job = session.get(SearchJob, job_id)
        message_count = session.scalar(select(func.count(OutboxMessage.id)))
        assert run is not None and run.status == "closed_at_cutoff"
        assert scan is not None and scan.status == "closed_at_cutoff"
        assert scan.error_code == "maigret_deadline_exceeded"
        assert job is not None and job.status == "ready_partial"
        assert job.exploration_status == "completed"
        assert message_count == 0


def test_scan_dispatched_after_deadline_closes_without_calling_adapter():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    factory = session_factory()
    _snapshot_id, job_id, run_id = add_maigret_run(
        factory,
        now=now,
        deadline_at=now - timedelta(seconds=1),
    )
    with factory() as session, session.begin():
        run = session.get(ProviderRun, run_id)
        scan = session.get(MaigretScanRun, run_id)
        assert run is not None and scan is not None
        run.status = "pending"
        run.lease_expires_at = None
        run.lease_generation = 0
        scan.status = "pending"
        scan.started_at = None
        session.execute(delete(ProviderAttempt).where(ProviderAttempt.provider_run_id == run_id))

    process_maigret_scan_run(
        factory,
        settings=SimpleNamespace(maigret_enabled=True, maigret_run_lease_seconds=180),
        clock=FixedClock(now),
        provider_run_id=run_id,
        adapter=object(),
    )

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        scan = session.get(MaigretScanRun, run_id)
        job = session.get(SearchJob, job_id)
        attempt_count = session.scalar(select(func.count(ProviderAttempt.id)))
        assert run is not None and run.status == "closed_at_cutoff"
        assert scan is not None and scan.status == "closed_at_cutoff"
        assert scan.error_code == "maigret_deadline_exceeded"
        assert job is not None and job.status == "ready_partial"
        assert attempt_count == 0


def test_disabled_maigret_closes_scan_and_finalizes_discovery():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    factory = session_factory()
    _snapshot_id, job_id, run_id = add_maigret_run(
        factory,
        now=now,
        deadline_at=now + timedelta(minutes=2),
    )
    with factory() as session, session.begin():
        run = session.get(ProviderRun, run_id)
        scan = session.get(MaigretScanRun, run_id)
        assert run is not None and scan is not None
        run.status = "pending"
        run.lease_expires_at = None
        run.lease_generation = 0
        scan.status = "pending"
        scan.started_at = None
        session.execute(delete(ProviderAttempt).where(ProviderAttempt.provider_run_id == run_id))

    process_maigret_scan_run(
        factory,
        settings=SimpleNamespace(maigret_enabled=False, maigret_run_lease_seconds=180),
        clock=FixedClock(now),
        provider_run_id=run_id,
        adapter=object(),
    )

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        scan = session.get(MaigretScanRun, run_id)
        job = session.get(SearchJob, job_id)
        assert run is not None and run.status == "cancelled"
        assert scan is not None and scan.status == "cancelled"
        assert scan.error_code == "maigret_disabled"
        assert job is not None and job.status == "ready_partial"


def test_missing_catalog_is_terminal_without_leaving_a_running_attempt():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    factory = session_factory()
    snapshot_id, job_id, run_id = add_maigret_run(
        factory,
        now=now,
        deadline_at=now + timedelta(minutes=2),
    )
    with factory() as session, session.begin():
        run = session.get(ProviderRun, run_id)
        scan = session.get(MaigretScanRun, run_id)
        assert run is not None and scan is not None
        run.status = "pending"
        run.lease_expires_at = None
        run.lease_generation = 0
        scan.status = "pending"
        scan.started_at = None
        session.execute(delete(ProviderAttempt).where(ProviderAttempt.provider_run_id == run_id))
        session.execute(
            delete(MaigretCatalogSnapshot).where(MaigretCatalogSnapshot.id == snapshot_id)
        )

    process_maigret_scan_run(
        factory,
        settings=SimpleNamespace(maigret_enabled=True, maigret_run_lease_seconds=180),
        clock=FixedClock(now),
        provider_run_id=run_id,
        adapter=object(),
    )

    with factory() as session:
        run = session.get(ProviderRun, run_id)
        scan = session.get(MaigretScanRun, run_id)
        job = session.get(SearchJob, job_id)
        attempt_count = session.scalar(select(func.count(ProviderAttempt.id)))
        assert run is not None and run.status == "provider_error"
        assert run.lease_expires_at is None
        assert scan is not None and scan.status == "provider_error"
        assert scan.finished_at == now.replace(tzinfo=None)
        assert scan.error_code == "maigret_catalog_missing"
        assert job is not None and job.status == "ready_partial"
        assert attempt_count == 0


def test_deadline_watchdog_uses_discovery_finalizer_for_queued_maigret_job():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    factory = session_factory()
    _snapshot_id, job_id, run_id = add_maigret_run(
        factory,
        now=now,
        deadline_at=now - timedelta(seconds=1),
    )
    with factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        run = session.get(ProviderRun, run_id)
        scan = session.get(MaigretScanRun, run_id)
        assert job is not None and run is not None and scan is not None
        job.status = "queued"
        run.status = "pending"
        run.lease_expires_at = None
        scan.status = "pending"
        session.execute(delete(ProviderAttempt).where(ProviderAttempt.provider_run_id == run_id))

    assert (
        finalize_expired_jobs(
            factory,
            settings=SimpleNamespace(),
            clock=FixedClock(now),
        )
        == 1
    )

    with factory() as session:
        job = session.get(SearchJob, job_id)
        run = session.get(ProviderRun, run_id)
        scan = session.get(MaigretScanRun, run_id)
        assert job is not None and job.status == "ready_partial"
        assert run is not None and run.status == "closed_at_cutoff"
        assert scan is not None and scan.status == "closed_at_cutoff"


def test_deadline_watchdog_preserves_deadline_free_synthesis_run():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    factory = session_factory()
    _snapshot_id, job_id, retrieval_run_id = add_maigret_run(
        factory,
        now=now,
        deadline_at=now - timedelta(seconds=1),
    )
    synthesis_run_id = new_id()
    with factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        retrieval_run = session.get(ProviderRun, retrieval_run_id)
        assert job is not None and retrieval_run is not None
        job.search_mode = "deep"
        session.add(
            ProviderRun(
                id=synthesis_run_id,
                job_id=job_id,
                attempt_id=retrieval_run.attempt_id,
                logical_run_id="synthesis:openrouter:grounded:v2",
                provider_id="grounded_synthesis_v2",
                parent_run_id=None,
                depth=2,
                query_config={"gateway": "openrouter", "model": "test-model"},
                status="pending",
                required_for_finalization=True,
                lease_generation=0,
                lease_expires_at=None,
                acceptance_epoch=job.acceptance_epoch,
                result_count=0,
                deadline_at=None,
                expires_at=job.expires_at,
            )
        )

    assert (
        finalize_expired_jobs(
            factory,
            settings=SimpleNamespace(),
            clock=FixedClock(now),
        )
        == 0
    )

    with factory() as session:
        job = session.get(SearchJob, job_id)
        retrieval_run = session.get(ProviderRun, retrieval_run_id)
        synthesis_run = session.get(ProviderRun, synthesis_run_id)
        assert job is not None and job.status == "discovering"
        assert retrieval_run is not None and retrieval_run.status == "closed_at_cutoff"
        assert synthesis_run is not None and synthesis_run.status == "pending"
        assert synthesis_run.deadline_at is None


def test_delete_job_removes_maigret_graph_rows_but_keeps_catalog_snapshot():
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    factory = session_factory()
    snapshot_id, job_id, run_id = add_maigret_run(
        factory,
        now=now,
        deadline_at=now + timedelta(minutes=2),
    )
    site_check_id = new_id()
    account_node_id = new_id()
    with factory() as session, session.begin():
        session.add(
            MaigretSiteCheck(
                id=site_check_id,
                job_id=job_id,
                provider_run_id=run_id,
                site_key="Example",
                site_name="Example",
                source_name=None,
                queried_identifier="alice",
                queried_identifier_type="username",
                url_main="https://example.test",
                url_user="https://example.test/alice",
                url_probe="https://example.test/alice",
                raw_status="CLAIMED",
                normalized_status="found",
                error_type=None,
                error_context=None,
                http_status=200,
                is_similar=False,
                rank=1,
                tags=["social"],
                extracted_data={},
                extracted_usernames={},
                extracted_links=[],
                result_checksum="e" * 64,
                observed_at=now,
            )
        )
        session.add(
            AccountNode(
                id=account_node_id,
                job_id=job_id,
                platform="Example",
                canonical_handle="alice",
                canonical_url="https://example.test/alice",
                display_name="Alice",
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
                provider_run_id=run_id,
                site_check_id=site_check_id,
                child_account_node_id=account_node_id,
                parent_seed="*:handle:alice",
                discovery_method="username_catalog_probe",
                discovery_engine="maigret",
                depth=0,
                created_at=now,
            )
        )
        session.add(
            DiscoveredIdentifier(
                id=new_id(),
                job_id=job_id,
                parent_site_check_id=site_check_id,
                identifier_type="username",
                identifier_value="alice-dev",
                normalized_value="alice-dev",
                source_kind="ids_usernames",
                scheduled=False,
                created_at=now,
            )
        )
        session.add(
            OutboxMessage(
                id=new_id(),
                topic="maigret_scan_run",
                dedupe_key=f"maigret-scan:{run_id}:generation:2",
                payload={"provider_run_id": run_id, "scan_run_id": run_id},
                created_at=now,
                dispatched_at=None,
                attempts=0,
            )
        )

    with factory() as session, session.begin():
        delete_job(session, job_id=job_id, user_id="test-user", now=now)

    with factory() as session:
        assert session.get(SearchJob, job_id) is None
        assert session.get(ProviderRun, run_id) is None
        assert session.get(MaigretScanRun, run_id) is None
        assert session.get(MaigretSiteCheck, site_check_id) is None
        assert session.get(AccountNode, account_node_id) is None
        assert (
            session.scalar(select(DiscoveryEdge.id).where(DiscoveryEdge.job_id == job_id)) is None
        )
        assert (
            session.scalar(
                select(DiscoveredIdentifier.id).where(DiscoveredIdentifier.job_id == job_id)
            )
            is None
        )
        assert (
            session.scalar(
                select(OutboxMessage.id).where(
                    OutboxMessage.payload["provider_run_id"].as_string() == run_id
                )
            )
            is None
        )
        assert session.get(MaigretCatalogSnapshot, snapshot_id) is not None
        assert session.get(JobDeletionTombstone, job_id) is not None
