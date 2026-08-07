from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from apps.api.app.models.entities import (
    AccountNode,
    AnalysisRevision,
    CollectionSnapshot,
    DiscoveredIdentifier,
    JobAttempt,
    JobEvent,
    MaigretScanRun,
    OutboxMessage,
    ProviderRun,
    ProviderRunSourceUse,
    ReportAccessState,
    ReportRevision,
    SearchJob,
    SourceDocument,
    SourceObservation,
    new_id,
)
from apps.api.app.services.maigret_runs import process_maigret_scan_run
from workers.providers.maigret_adapter import (
    MaigretAccountCandidate,
    MaigretCoverage,
    MaigretExtractedField,
    MaigretExtractedIdentifier,
    MaigretExtractedLink,
    MaigretScanResult,
    MaigretSiteCheck,
)


class StaticAdapter:
    def __init__(self, result: MaigretScanResult) -> None:
        self.result = result

    async def scan(
        self,
        identifier: str,
        *,
        product_identifier_type: str = "handle",
    ) -> MaigretScanResult:
        assert identifier == self.result.queried_identifier
        assert product_identifier_type == self.result.product_identifier_type
        return self.result


def create_footprint_job(
    client,
    auth_headers,
    *,
    key: str = "footprint-request-0001",
    identifier: str = "alice",
    platform: str = "github",
    search_mode: str = "quick",
):
    return client.post(
        "/v1/footprint-jobs",
        headers={**auth_headers, "Idempotency-Key": key},
        json={
            "seed": {
                "kind": "platform_identifier",
                "platform": platform,
                "identifier_type": "handle",
                "identifier": identifier,
            },
            "search_mode": search_mode,
            "locale": "en-US",
        },
    )


def seed_footprint_report(app, clock, *, job_id: str) -> tuple[dict[str, object], str]:
    now = clock.now()
    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        attempt = session.get(JobAttempt, job.active_attempt_id)
        provider_run = session.scalar(
            select(ProviderRun)
            .where(ProviderRun.job_id == job_id)
            .order_by(ProviderRun.logical_run_id)
        )
        assert attempt is not None and provider_run is not None

        handle = job.seed_identifier or "profile"
        platform = job.seed_platform or "other"
        profile_url = f"https://profiles.example.test/{platform}/{handle}"
        document_id = new_id()
        source_use_id = new_id()
        observation_id = new_id()
        snapshot_id = new_id()
        analysis_id = new_id()
        report_id = new_id()
        candidate_id = new_id()
        claim_id = new_id()

        session.add(
            SourceDocument(
                id=document_id,
                canonical_url=profile_url,
                publisher=platform,
                title=f"{platform} public profile",
                mime_type="text/html",
                content_hash="1" * 64,
                lineage_key=f"{platform}:{handle}",
                expires_at=job.expires_at,
            )
        )
        session.add(
            ProviderRunSourceUse(
                id=source_use_id,
                provider_run_id=provider_run.id,
                document_id=document_id,
                disposition="accepted",
                policy_version=job.policy_version,
            )
        )
        session.add(
            SourceObservation(
                id=observation_id,
                job_id=job.id,
                source_use_id=source_use_id,
                source_type="first_party_profile",
                trust_class="first_party",
                retrieved_at=now,
                excerpt=f"Public profile for @{handle}.",
                span_locator={"kind": "profile"},
                extracted_fields={"handle": handle},
                extraction_version="test-v1",
                expires_at=job.expires_at,
            )
        )
        session.add(
            CollectionSnapshot(
                id=snapshot_id,
                job_id=job.id,
                attempt_id=attempt.id,
                cutoff_at=now,
                observation_ids=[observation_id],
                provider_manifest=[],
                policy_version=job.policy_version,
                checksum="2" * 64,
                expires_at=job.expires_at,
            )
        )
        session.add(
            AnalysisRevision(
                id=analysis_id,
                job_id=job.id,
                collection_snapshot_id=snapshot_id,
                status="complete",
                rules_version="test-v1",
                checksum="3" * 64,
                created_at=now,
                expires_at=job.expires_at,
            )
        )
        content: dict[str, object] = {
            "job_id": job.id,
            "report_type": "account_centric",
            "subject": f"@{handle}",
            "summary": "One public account was assessed from the available evidence.",
            "overall_identity_status": "unverified",
            "accounts": [
                {
                    "candidate_id": candidate_id,
                    "platform": platform,
                    "handle": handle,
                    "profile_url": profile_url,
                    "display_name": None,
                    "existence_status": "exact_verified",
                    "identity_status": "unverified",
                    "confidence": "medium",
                    "source_ids": [observation_id],
                    "reasons": ["The first-party profile uses the queried handle."],
                }
            ],
            "claims": [
                {
                    "claim_id": claim_id,
                    "predicate": "account.exact_profile",
                    "label": "Exact public profile",
                    "value": f"{platform} @{handle}",
                    "confidence": "medium",
                    "source_ids": [observation_id],
                    "qualification": "Account existence does not establish a person match.",
                }
            ],
            "identity_reasons": {
                "supporting": ["The queried handle appears on the profile."],
                "limiting": ["No independent same-person signal was available."],
            },
            "limitations": ["This is an account-centric result."],
            "generated_at": now.isoformat(),
        }
        session.add(
            ReportRevision(
                id=report_id,
                job_id=job.id,
                analysis_revision_id=analysis_id,
                report_type="account_centric",
                locale=job.locale,
                status="ready",
                content=content,
                template_version="test-v1",
                policy_version=job.policy_version,
                checksum="4" * 64,
                created_at=now,
                expires_at=job.expires_at,
            )
        )
        session.add(
            ReportAccessState(
                report_id=report_id,
                job_id=job.id,
                state="active",
                updated_at=now,
            )
        )
        attempt.collection_snapshot_id = snapshot_id
        attempt.current_analysis_revision_id = analysis_id
        attempt.current_report_revision_id = report_id
        job.status = "ready"
        job.exploration_status = "completed"
    return content, observation_id


def scan_result(
    *,
    snapshot_id: str,
    identifier: str,
    site_name: str,
    found: bool,
    selected_count: int = 1,
) -> MaigretScanResult:
    url = f"https://{site_name.casefold()}.example/{identifier}" if found else None
    identifiers = (
        (
            MaigretExtractedIdentifier(
                value=identifier,
                maigret_id_type="username",
                source_site_id=site_name,
            ),
            MaigretExtractedIdentifier(
                value=f"{identifier}_dev",
                maigret_id_type="username",
                source_site_id=site_name,
            ),
        )
        if found
        else ()
    )
    links = (
        (
            MaigretExtractedLink(
                url=f"https://portfolio.example/{identifier}",
                source_site_id=site_name,
            ),
        )
        if found
        else ()
    )
    fields = (
        (
            MaigretExtractedField(
                name="display_name",
                value="Alice Example",
                source_site_id=site_name,
            ),
        )
        if found
        else ()
    )
    check = MaigretSiteCheck(
        site_id=site_name,
        site_name=site_name,
        queried_identifier=identifier,
        maigret_id_type="username",
        maigret_status="CLAIMED" if found else "AVAILABLE",
        product_status="found" if found else "not_found",
        url_main=f"https://{site_name.casefold()}.example",
        url_user=url,
        url_probe=url,
        http_status=200 if found else 404,
        rank=10,
        tags=("social",),
        is_similar=False,
        context=None,
        error_type=None,
        error_detail=None,
        extracted_identifiers=identifiers,
        extracted_links=links,
        extracted_fields=fields,
    )
    candidates = (
        (
            MaigretAccountCandidate(
                site_id=site_name,
                site_name=site_name,
                url=url or "",
                queried_identifier=identifier,
                maigret_id_type="username",
                relationship="exact_handle_result",
            ),
        )
        if found
        else ()
    )
    return MaigretScanResult(
        catalog_snapshot_id=snapshot_id,
        queried_identifier=identifier,
        product_identifier_type="handle",
        maigret_id_type="username",
        selected_site_ids=(site_name,),
        status="success" if found else "no_result",
        cancelled=False,
        site_checks=(check,),
        account_candidates=candidates,
        extracted_identifiers=identifiers,
        extracted_links=links,
        extracted_fields=fields,
        coverage=MaigretCoverage(
            selected=selected_count,
            completed=selected_count,
            claimed=1 if found else 0,
            available=selected_count - 1 if found else selected_count,
            unknown=0,
            illegal=0,
        ),
    )


def test_footprint_job_discovers_candidates_progressively(
    client,
    app,
    settings,
    clock,
    auth_headers,
):
    created = create_footprint_job(client, auth_headers)
    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "queued"
    assert body["search_mode"] == "quick"
    assert body["deep_progress"] is None
    assert body["coverage"] == {
        "selected": 20,
        "completed": 0,
        "claimed": 0,
        "available": 0,
        "unknown": 0,
        "illegal": 0,
    }
    assert body["catalog"]["engine"] == "maigret"
    assert body["catalog"]["package_version"] == "0.6.3"
    assert body["catalog"]["profile"] == "quick"
    job_id = body["job_id"]

    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        assert job is not None
        run_ids = session.scalars(
            select(ProviderRun.id)
            .where(ProviderRun.job_id == job_id)
            .order_by(ProviderRun.logical_run_id)
        ).all()
        run_sizes = {
            run_id: session.get(MaigretScanRun, run_id).selected_count for run_id in run_ids
        }
        assert len(run_ids) == 3
        assert (
            session.scalar(
                select(func.count(OutboxMessage.id)).where(
                    OutboxMessage.topic == "maigret_scan_run"
                )
            )
            == 3
        )
        snapshot_id = str(job.catalog_snapshot_id)

    process_maigret_scan_run(
        app.state.session_factory,
        settings=settings,
        clock=clock,
        provider_run_id=run_ids[0],
        adapter=StaticAdapter(
            scan_result(
                snapshot_id=snapshot_id,
                identifier="alice",
                site_name="GitHub",
                found=True,
                selected_count=run_sizes[run_ids[0]],
            )
        ),
    )

    in_progress = client.get(f"/v1/footprint-jobs/{job_id}", headers=auth_headers)
    assert in_progress.status_code == 200
    assert in_progress.json()["status"] == "discovering"
    assert in_progress.json()["coverage"]["completed"] == 7

    candidates = client.get(
        f"/v1/footprint-jobs/{job_id}/candidates",
        headers=auth_headers,
    )
    assert candidates.status_code == 200
    assert candidates.json()["extracted_identifier_count"] == 2
    assert candidates.json()["items"] == [
        {
            "candidate_id": candidates.json()["items"][0]["candidate_id"],
            "platform": "GitHub",
            "handle": "alice",
            "profile_url": "https://github.example/alice",
            "display_name": "Alice Example",
            "relationship": "unresolved",
            "identity_tier": "possible",
            "selection_state": "undecided",
            "anchor_eligible": False,
            "is_similar": False,
            "profile_data": {
                "fields": {"display_name": "Alice Example"},
                "links": ["https://portfolio.example/alice"],
                "tags": ["social"],
            },
            "discovered_at": candidates.json()["items"][0]["discovered_at"],
            "evidence": [
                {
                    "site_check_id": candidates.json()["items"][0]["evidence"][0]["site_check_id"],
                    "site_name": "GitHub",
                    "status": "CLAIMED",
                    "discovery_method": "username_catalog_probe",
                    "observed_at": candidates.json()["items"][0]["evidence"][0]["observed_at"],
                }
            ],
        }
    ]

    for index, run_id in enumerate(run_ids[1:], start=1):
        process_maigret_scan_run(
            app.state.session_factory,
            settings=settings,
            clock=clock,
            provider_run_id=run_id,
            adapter=StaticAdapter(
                scan_result(
                    snapshot_id=snapshot_id,
                    identifier="alice",
                    site_name=f"Available{index}",
                    found=False,
                    selected_count=run_sizes[run_id],
                )
            ),
        )

    complete = client.get(f"/v1/footprint-jobs/{job_id}", headers=auth_headers)
    assert complete.status_code == 200
    assert complete.json()["status"] == "ready"
    assert complete.json()["exploration_status"] == "completed"
    assert complete.json()["coverage"] == {
        "selected": 20,
        "completed": 20,
        "claimed": 1,
        "available": 19,
        "unknown": 0,
        "illegal": 0,
    }


def test_deep_footprint_job_reuses_quick_catalog_and_preserves_mode(
    client,
    app,
    auth_headers,
):
    created = create_footprint_job(
        client,
        auth_headers,
        key="deep-footprint-request",
        search_mode="deep",
    )

    assert created.status_code == 202
    body = created.json()
    assert body["search_mode"] == "deep"
    assert body["catalog"]["profile"] == "quick"
    assert body["coverage"]["selected"] == 20
    assert body["deep_progress"] == {
        "current_phase": "queued",
        "phase_started_at": body["accepted_at"],
        "finished_at": None,
    }

    with app.state.session_factory() as session:
        job = session.get(SearchJob, body["job_id"])
        assert job is not None
        assert job.search_mode == "deep"
        assert job.catalog_profile == "quick"


def test_deep_progress_tracks_lifecycle_events_and_anchor_resolution(
    client,
    app,
    clock,
    auth_headers,
):
    created = create_footprint_job(
        client,
        auth_headers,
        key="deep-progress-lifecycle",
        search_mode="deep",
    )
    job_id = created.json()["job_id"]

    transitions = [
        (
            "discovery.catalog_scan_started",
            "account_scan",
            "running",
            False,
        ),
        (
            "discovery.anchor_required",
            "awaiting_anchor",
            "awaiting_anchor",
            False,
        ),
        (
            "discovery.anchor_selected",
            "professional_enrichment",
            "running",
            False,
        ),
        (
            "discovery.professional_search_started",
            "professional_enrichment",
            "running",
            False,
        ),
        (
            "discovery.synthesis_started",
            "report_generation",
            "running",
            False,
        ),
        (
            "finalization_started",
            "finalizing",
            "running",
            False,
        ),
        (
            "job.ready",
            "complete",
            "completed",
            True,
        ),
    ]

    for offset, (event_type, phase, exploration_status, terminal) in enumerate(
        transitions,
        start=1,
    ):
        event_at = clock.now() + timedelta(seconds=offset * 10)
        with app.state.session_factory() as session, session.begin():
            job = session.get(SearchJob, job_id)
            assert job is not None
            job.status = "ready" if terminal else "discovering"
            job.exploration_status = exploration_status
            sequence = int(
                session.scalar(
                    select(func.coalesce(func.max(JobEvent.sequence), 0)).where(
                        JobEvent.job_id == job_id
                    )
                )
                or 0
            )
            session.add(
                JobEvent(
                    id=new_id(),
                    job_id=job_id,
                    sequence=sequence + 1,
                    event_type=event_type,
                    message=f"Entered {phase}.",
                    terminal=terminal,
                    created_at=event_at,
                )
            )

        response = client.get(f"/v1/footprint-jobs/{job_id}", headers=auth_headers)
        assert response.status_code == 200
        progress = response.json()["deep_progress"]
        assert progress["current_phase"] == phase
        assert progress["phase_started_at"].startswith(event_at.replace(tzinfo=None).isoformat())
        if terminal:
            assert progress["finished_at"].startswith(
                event_at.replace(tzinfo=None).isoformat()
            )
        else:
            assert progress["finished_at"] is None


def test_deep_progress_keeps_the_first_catalog_shard_start_time(
    client,
    app,
    clock,
    auth_headers,
):
    created = create_footprint_job(
        client,
        auth_headers,
        key="deep-progress-catalog-clock",
        search_mode="deep",
    )
    job_id = created.json()["job_id"]
    first_started_at = clock.now() + timedelta(seconds=10)
    second_started_at = clock.now() + timedelta(seconds=20)

    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        job.status = "discovering"
        job.exploration_status = "running"
        session.add_all(
            [
                JobEvent(
                    id=new_id(),
                    job_id=job_id,
                    sequence=2,
                    event_type="discovery.catalog_scan_started",
                    message="First catalog shard started.",
                    terminal=False,
                    created_at=first_started_at,
                ),
                JobEvent(
                    id=new_id(),
                    job_id=job_id,
                    sequence=3,
                    event_type="discovery.catalog_scan_started",
                    message="Second catalog shard started.",
                    terminal=False,
                    created_at=second_started_at,
                ),
            ]
        )

    response = client.get(f"/v1/footprint-jobs/{job_id}", headers=auth_headers)
    assert response.status_code == 200
    progress = response.json()["deep_progress"]
    assert progress["current_phase"] == "account_scan"
    assert progress["phase_started_at"].startswith(
        first_started_at.replace(tzinfo=None).isoformat()
    )


def test_deep_progress_uses_synthesis_progress_and_cancelled_at_fallback(
    client,
    app,
    clock,
    auth_headers,
):
    created = create_footprint_job(
        client,
        auth_headers,
        key="deep-progress-fallbacks",
        search_mode="deep",
    )
    job_id = created.json()["job_id"]
    synthesis_at = clock.now() + timedelta(seconds=10)
    cancelled_at = clock.now() + timedelta(seconds=20)
    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        job.status = "discovering"
        job.exploration_status = "running"
        session.add(
            JobEvent(
                id=new_id(),
                job_id=job_id,
                sequence=2,
                event_type="discovery.synthesis_progress",
                message="Deep story fallback is ready.",
                terminal=False,
                created_at=synthesis_at,
            )
        )

    composing = client.get(f"/v1/footprint-jobs/{job_id}", headers=auth_headers)
    assert composing.status_code == 200
    assert composing.json()["deep_progress"]["current_phase"] == "report_generation"
    assert composing.json()["deep_progress"]["finished_at"] is None
    assert composing.json()["deep_progress"]["phase_started_at"].startswith(
        synthesis_at.replace(tzinfo=None).isoformat()
    )

    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        job.status = "cancelled"
        job.exploration_status = "cancelled"
        job.cancelled_at = cancelled_at

    cancelled = client.get(f"/v1/footprint-jobs/{job_id}", headers=auth_headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["deep_progress"]["current_phase"] == "report_generation"
    assert cancelled.json()["deep_progress"]["phase_started_at"].startswith(
        synthesis_at.replace(tzinfo=None).isoformat()
    )
    assert cancelled.json()["deep_progress"]["finished_at"].startswith(
        cancelled_at.replace(tzinfo=None).isoformat()
    )


def test_failed_deep_progress_uses_attempt_finished_at_without_completing_phase(
    client,
    app,
    clock,
    auth_headers,
):
    created = create_footprint_job(
        client,
        auth_headers,
        key="deep-progress-failed-attempt",
        search_mode="deep",
    )
    job_id = created.json()["job_id"]
    scan_started_at = clock.now() + timedelta(seconds=10)
    failed_at = clock.now() + timedelta(seconds=30)
    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        attempt = session.get(JobAttempt, job.active_attempt_id)
        assert attempt is not None
        job.status = "failed"
        job.exploration_status = "cancelled"
        attempt.status = "failed"
        attempt.finished_at = failed_at
        session.add(
            JobEvent(
                id=new_id(),
                job_id=job_id,
                sequence=2,
                event_type="discovery.catalog_scan_started",
                message="Account scan started.",
                terminal=False,
                created_at=scan_started_at,
            )
        )

    failed = client.get(f"/v1/footprint-jobs/{job_id}", headers=auth_headers)
    assert failed.status_code == 200
    assert failed.json()["deep_progress"]["current_phase"] == "account_scan"
    assert failed.json()["deep_progress"]["phase_started_at"].startswith(
        scan_started_at.replace(tzinfo=None).isoformat()
    )
    assert failed.json()["deep_progress"]["finished_at"].startswith(
        failed_at.replace(tzinfo=None).isoformat()
    )


def test_instagram_seed_prioritizes_meta_and_clubhouse_probes(
    client,
    app,
    auth_headers,
):
    created = create_footprint_job(
        client,
        auth_headers,
        key="instagram-priority-request",
        identifier="octaviyao",
        platform="instagram",
    )
    assert created.status_code == 202
    job_id = created.json()["job_id"]

    with app.state.session_factory() as session:
        runs = session.scalars(
            select(MaigretScanRun)
            .join(ProviderRun, ProviderRun.id == MaigretScanRun.provider_run_id)
            .where(ProviderRun.job_id == job_id)
            .order_by(ProviderRun.logical_run_id)
        ).all()

    selected_sites = [site for run in runs for site in run.site_names]
    assert selected_sites[:3] == ["Instagram", "Threads", "Clubhouse"]
    assert len(runs) == 3
    assert [run.selected_count for run in runs] == [7, 7, 6]
    assert len(selected_sites) == len(set(selected_sites)) == 20


def test_root_and_job_global_duplicate_pivots_are_not_counted(
    client,
    app,
    settings,
    clock,
    auth_headers,
):
    created = create_footprint_job(
        client,
        auth_headers,
        key="pivot-deduplication-request",
    )
    job_id = created.json()["job_id"]
    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        run_ids = session.scalars(
            select(ProviderRun.id)
            .where(ProviderRun.job_id == job_id)
            .order_by(ProviderRun.logical_run_id)
        ).all()
        assert job is not None
        snapshot_id = str(job.catalog_snapshot_id)

    for run_id, site_name in zip(run_ids[:2], ("First", "Second"), strict=True):
        process_maigret_scan_run(
            app.state.session_factory,
            settings=settings,
            clock=clock,
            provider_run_id=run_id,
            adapter=StaticAdapter(
                scan_result(
                    snapshot_id=snapshot_id,
                    identifier="alice",
                    site_name=site_name,
                    found=True,
                )
            ),
        )

    candidates = client.get(
        f"/v1/footprint-jobs/{job_id}/candidates",
        headers=auth_headers,
    )
    assert candidates.status_code == 200
    assert candidates.json()["extracted_identifier_count"] == 2
    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count(DiscoveredIdentifier.id)).where(
                    DiscoveredIdentifier.job_id == job_id
                )
            )
            == 2
        )


def test_scan_result_is_enriched_before_persistence(
    client,
    app,
    settings,
    clock,
    auth_headers,
    monkeypatch,
):
    created = create_footprint_job(
        client,
        auth_headers,
        key="metadata-enrichment-wiring-request",
    )
    job_id = created.json()["job_id"]
    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        run_id = session.scalar(
            select(ProviderRun.id)
            .where(ProviderRun.job_id == job_id)
            .order_by(ProviderRun.logical_run_id)
        )
        assert job is not None and run_id is not None
        result = scan_result(
            snapshot_id=str(job.catalog_snapshot_id),
            identifier="alice",
            site_name="GitHub",
            found=True,
        )

    enriched_results = []

    def record_enrichment(value):
        enriched_results.append(value)
        return value

    monkeypatch.setattr(
        "apps.api.app.services.maigret_runs.enrich_first_party_metadata",
        record_enrichment,
    )
    process_maigret_scan_run(
        app.state.session_factory,
        settings=settings,
        clock=clock,
        provider_run_id=run_id,
        adapter=StaticAdapter(result),
    )

    assert enriched_results == [result]
    with app.state.session_factory() as session:
        assert (
            session.scalar(select(func.count(AccountNode.id)).where(AccountNode.job_id == job_id))
            == 1
        )


def test_footprint_brief_and_evidence_use_owner_scoped_report_reads(
    client,
    app,
    clock,
    auth_headers,
):
    created = create_footprint_job(
        client,
        auth_headers,
        key="footprint-report-read-request",
    )
    job_id = created.json()["job_id"]

    pending_brief = client.get(
        f"/v1/footprint-jobs/{job_id}/brief",
        headers=auth_headers,
    )
    pending_evidence = client.get(
        f"/v1/footprint-jobs/{job_id}/evidence",
        headers=auth_headers,
    )
    assert pending_brief.status_code == pending_evidence.status_code == 409
    assert pending_brief.json()["error_code"] == "job_not_ready"

    expected, observation_id = seed_footprint_report(
        app,
        clock,
        job_id=job_id,
    )
    brief = client.get(
        f"/v1/footprint-jobs/{job_id}/brief",
        headers=auth_headers,
    )
    assert brief.status_code == 200
    assert set(brief.json()) == {
        "job_id",
        "report_type",
        "subject",
        "summary",
        "overall_identity_status",
        "accounts",
        "claims",
        "identity_reasons",
        "narrative_sections",
        "deep_story",
        "synthesis",
        "limitations",
        "generated_at",
    }
    assert brief.json()["job_id"] == job_id
    assert brief.json()["report_type"] == expected["report_type"]
    assert brief.json()["overall_identity_status"] == "unverified"
    assert brief.json()["accounts"][0]["source_ids"] == [observation_id]
    assert brief.json()["claims"][0]["qualification"]
    assert brief.json()["narrative_sections"] == []
    assert brief.json()["deep_story"] is None
    assert brief.json()["synthesis"] is None

    evidence = client.get(
        f"/v1/footprint-jobs/{job_id}/evidence",
        headers=auth_headers,
    )
    assert evidence.status_code == 200
    assert evidence.json()["items"] == [
        {
            "evidence_id": observation_id,
            "source_type": "first_party_profile",
            "trust_class": "first_party",
            "publisher": "github",
            "title": "github public profile",
            "url": "https://profiles.example.test/github/alice",
            "excerpt": "Public profile for @alice.",
            "retrieved_at": evidence.json()["items"][0]["retrieved_at"],
        }
    ]

    other_headers = {
        **auth_headers,
        "X-Prototype-User": str(uuid4()),
    }
    assert (
        client.get(
            f"/v1/footprint-jobs/{job_id}/brief",
            headers=other_headers,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/footprint-jobs/{job_id}/evidence",
            headers=other_headers,
        ).status_code
        == 404
    )


def test_footprint_report_reads_fail_closed_without_active_access(
    client,
    app,
    clock,
    auth_headers,
):
    created = create_footprint_job(
        client,
        auth_headers,
        key="footprint-report-access-request",
    )
    job_id = created.json()["job_id"]
    seed_footprint_report(app, clock, job_id=job_id)

    with app.state.session_factory() as session, session.begin():
        access = session.scalar(select(ReportAccessState).where(ReportAccessState.job_id == job_id))
        assert access is not None
        access.state = "revoked"

    hidden_brief = client.get(
        f"/v1/footprint-jobs/{job_id}/brief",
        headers=auth_headers,
    )
    hidden_evidence = client.get(
        f"/v1/footprint-jobs/{job_id}/evidence",
        headers=auth_headers,
    )
    assert hidden_brief.status_code == hidden_evidence.status_code == 404
    assert hidden_brief.json()["error_code"] == "result_unavailable"


def test_footprint_idempotency_validation_and_owner_isolation(
    client,
    auth_headers,
):
    first = create_footprint_job(client, auth_headers, key="same-footprint-request")
    second = create_footprint_job(client, auth_headers, key="same-footprint-request")
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]

    conflict = create_footprint_job(
        client,
        auth_headers,
        key="same-footprint-request",
        identifier="bob",
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "idempotency_conflict"

    invalid = create_footprint_job(
        client,
        auth_headers,
        key="invalid-footprint-request",
        identifier="https://github.com/alice",
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "invalid_request"

    other_headers = {
        **auth_headers,
        "X-Prototype-User": str(uuid4()),
    }
    hidden = client.get(
        f"/v1/footprint-jobs/{first.json()['job_id']}",
        headers=other_headers,
    )
    assert hidden.status_code == 404
    assert hidden.json()["error_code"] == "job_not_found"


def test_concurrent_idempotency_claim_replays_the_committed_winner(
    client,
    app,
    auth_headers,
    monkeypatch,
):
    first = create_footprint_job(
        client,
        auth_headers,
        key="raced-footprint-request",
    )
    assert first.status_code == 202

    from apps.api.app.services import discovery_jobs

    original_lookup = discovery_jobs._idempotent_footprint_job
    lookup_count = 0

    def miss_before_unique_claim(*args, **kwargs):
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count == 1:
            return None
        return original_lookup(*args, **kwargs)

    monkeypatch.setattr(
        discovery_jobs,
        "_idempotent_footprint_job",
        miss_before_unique_claim,
    )
    replay = create_footprint_job(
        client,
        auth_headers,
        key="raced-footprint-request",
    )

    assert replay.status_code == 202
    assert replay.json()["job_id"] == first.json()["job_id"]
    assert lookup_count == 2
    with app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count(SearchJob.id)).where(
                    SearchJob.job_kind == "footprint_discovery"
                )
            )
            == 1
        )


def test_delete_footprint_job_removes_discovery_records(
    client,
    app,
    settings,
    clock,
    auth_headers,
):
    created = create_footprint_job(
        client,
        auth_headers,
        key="delete-footprint-request",
    )
    job_id = created.json()["job_id"]
    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        run_id = session.scalar(select(ProviderRun.id).where(ProviderRun.job_id == job_id))
        assert job is not None and run_id is not None
        snapshot_id = str(job.catalog_snapshot_id)
    process_maigret_scan_run(
        app.state.session_factory,
        settings=settings,
        clock=clock,
        provider_run_id=run_id,
        adapter=StaticAdapter(
            scan_result(
                snapshot_id=snapshot_id,
                identifier="alice",
                site_name="GitHub",
                found=True,
            )
        ),
    )

    deleted = client.delete(f"/v1/footprint-jobs/{job_id}", headers=auth_headers)
    assert deleted.status_code == 204
    with app.state.session_factory() as session:
        assert session.get(SearchJob, job_id) is None
        assert session.scalar(select(AccountNode.id).where(AccountNode.job_id == job_id)) is None
        assert (
            session.scalar(
                select(DiscoveredIdentifier.id).where(DiscoveredIdentifier.job_id == job_id)
            )
            is None
        )
        assert (
            session.scalar(
                select(MaigretScanRun.provider_run_id)
                .join(
                    ProviderRun,
                    ProviderRun.id == MaigretScanRun.provider_run_id,
                )
                .where(ProviderRun.job_id == job_id)
            )
            is None
        )
