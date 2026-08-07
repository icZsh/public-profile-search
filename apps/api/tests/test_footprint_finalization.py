import json

from sqlalchemy import func, select

from apps.api.app.models.entities import (
    AnalysisRevision,
    Claim,
    ClaimEvidence,
    CollectionSnapshot,
    JobAttempt,
    MaigretScanRun,
    ProviderRun,
    ReportAccessState,
    ReportRevision,
    SearchJob,
    SourceDocument,
    SourceObservation,
)
from apps.api.app.services.maigret_runs import (
    finalize_discovery_if_complete,
    process_maigret_scan_run,
)
from apps.api.tests.test_footprint_discovery import (
    StaticAdapter,
    create_footprint_job,
    scan_result,
)
from workers.providers.maigret_adapter import (
    MaigretAccountCandidate,
    MaigretCoverage,
    MaigretExtractedField,
    MaigretScanResult,
    MaigretSiteCheck,
)


def _profile_result(
    *,
    snapshot_id: str,
    identifier: str,
    site_name: str,
    profile_url: str,
    display_name: str,
    selected_count: int,
    bio: str | None = None,
) -> MaigretScanResult:
    field_values: list[tuple[str, object]] = [
        ("username", identifier),
        ("display_name", display_name),
        ("is_private", False),
        ("is_verified", False),
        ("follower_count", "1.2K"),
        ("following_count", 42),
        ("posts_count", 7),
        ("uid", "raw-platform-id-should-not-escape"),
        ("avatar_url", "https://images.example/private-avatar.jpg"),
        ("email", "raw-address@example.test"),
    ]
    if bio:
        field_values.append(("bio", bio))
    fields = tuple(
        MaigretExtractedField(
            name=name,
            value=value,
            source_site_id=site_name,
        )
        for name, value in field_values
    )
    check = MaigretSiteCheck(
        site_id=site_name,
        site_name=site_name,
        queried_identifier=identifier,
        maigret_id_type="username",
        maigret_status="CLAIMED",
        product_status="found",
        url_main=profile_url.split("/", 3)[0] + "//" + profile_url.split("/", 3)[2],
        url_user=profile_url,
        url_probe=profile_url,
        http_status=200,
        rank=10,
        tags=("social",),
        is_similar=False,
        context=None,
        error_type=None,
        error_detail=None,
        extracted_identifiers=(),
        extracted_links=(),
        extracted_fields=fields,
    )
    return MaigretScanResult(
        catalog_snapshot_id=snapshot_id,
        queried_identifier=identifier,
        product_identifier_type="handle",
        maigret_id_type="username",
        selected_site_ids=(site_name,),
        status="success",
        cancelled=False,
        site_checks=(check,),
        account_candidates=(
            MaigretAccountCandidate(
                site_id=site_name,
                site_name=site_name,
                url=profile_url,
                queried_identifier=identifier,
                maigret_id_type="username",
                relationship="exact_handle_result",
            ),
        ),
        extracted_identifiers=(),
        extracted_links=(),
        extracted_fields=fields,
        coverage=MaigretCoverage(
            selected=selected_count,
            completed=selected_count,
            claimed=1,
            available=max(0, selected_count - 1),
            unknown=0,
            illegal=0,
        ),
    )


def _limited_result(
    *,
    snapshot_id: str,
    identifier: str,
    site_name: str,
    selected_count: int,
) -> MaigretScanResult:
    check = MaigretSiteCheck(
        site_id=site_name,
        site_name=site_name,
        queried_identifier=identifier,
        maigret_id_type="username",
        maigret_status="UNKNOWN",
        product_status="rate_limited",
        url_main=f"https://www.{site_name.casefold()}.com",
        url_user=None,
        url_probe=f"https://www.{site_name.casefold()}.com/user/{identifier}",
        http_status=429,
        rank=10,
        tags=("social",),
        is_similar=False,
        context="Too many requests",
        error_type="rate limit",
        error_detail="HTTP 429",
        extracted_identifiers=(),
        extracted_links=(),
        extracted_fields=(),
    )
    return MaigretScanResult(
        catalog_snapshot_id=snapshot_id,
        queried_identifier=identifier,
        product_identifier_type="handle",
        maigret_id_type="username",
        selected_site_ids=(site_name,),
        status="partial_success",
        cancelled=False,
        site_checks=(check,),
        account_candidates=(),
        extracted_identifiers=(),
        extracted_links=(),
        extracted_fields=(),
        coverage=MaigretCoverage(
            selected=selected_count,
            completed=selected_count,
            claimed=0,
            available=0,
            unknown=selected_count,
            illegal=0,
        ),
    )


def _job_scan_context(app, *, job_id: str):
    with app.state.session_factory() as session:
        job = session.get(SearchJob, job_id)
        assert job is not None
        runs = session.scalars(
            select(ProviderRun)
            .where(ProviderRun.job_id == job_id)
            .order_by(ProviderRun.logical_run_id)
        ).all()
        return (
            str(job.catalog_snapshot_id),
            [(run.id, session.get(MaigretScanRun, run.id).selected_count) for run in runs],
        )


def _process_results(
    app,
    settings,
    clock,
    *,
    run_specs: list[tuple[str, MaigretScanResult]],
) -> None:
    for run_id, result in run_specs:
        process_maigret_scan_run(
            app.state.session_factory,
            settings=settings,
            clock=clock,
            provider_run_id=run_id,
            adapter=StaticAdapter(result),
        )


def test_finalization_freezes_allowlisted_first_party_and_channel_evidence(
    client,
    app,
    settings,
    clock,
    auth_headers,
    monkeypatch,
):
    monkeypatch.setattr(
        "apps.api.app.services.maigret_runs.enrich_first_party_metadata",
        lambda result: result,
    )
    created = create_footprint_job(
        client,
        auth_headers,
        key="footprint-finalization-evidence",
        identifier="alice",
        platform="instagram",
    )
    job_id = created.json()["job_id"]
    snapshot_id, runs = _job_scan_context(app, job_id=job_id)
    _process_results(
        app,
        settings,
        clock,
        run_specs=[
            (
                runs[0][0],
                _profile_result(
                    snapshot_id=snapshot_id,
                    identifier="alice",
                    site_name="Instagram",
                    profile_url="https://www.instagram.com/alice/",
                    display_name="Alice Example",
                    bio="Builder and maker 📍 San Francisco Bay Area",
                    selected_count=runs[0][1],
                ),
            ),
            (
                runs[1][0],
                _profile_result(
                    snapshot_id=snapshot_id,
                    identifier="alice",
                    site_name="Threads",
                    profile_url="https://www.threads.com/@alice",
                    display_name="Alice Example",
                    selected_count=runs[1][1],
                ),
            ),
            (
                runs[2][0],
                _limited_result(
                    snapshot_id=snapshot_id,
                    identifier="alice",
                    site_name="Reddit",
                    selected_count=runs[2][1],
                ),
            ),
        ],
    )

    brief_response = client.get(
        f"/v1/footprint-jobs/{job_id}/brief",
        headers=auth_headers,
    )
    assert brief_response.status_code == 200
    brief = brief_response.json()
    assert brief["report_type"] == "account_centric"
    assert brief["overall_identity_status"] == "unverified"
    assert brief["subject"] == "Alice Example (@alice)"
    accounts = {item["platform"]: item for item in brief["accounts"]}
    assert accounts["Instagram"]["existence_status"] == "exact_verified"
    assert accounts["Instagram"]["identity_status"] == "unverified"
    assert accounts["Threads"]["existence_status"] == "exact_verified"
    assert accounts["Threads"]["identity_status"] == "likely"

    location_claim = next(
        item for item in brief["claims"] if item["predicate"] == "account.self_described_location"
    )
    assert location_claim["value"] == "San Francisco Bay Area"
    channel_claim = next(
        item for item in brief["claims"] if item["predicate"] == "channel.coverage"
    )
    assert channel_claim["value"] == "rate_limited"
    association_claim = next(
        item for item in brief["claims"] if item["predicate"] == "account.association"
    )
    assert len(association_claim["source_ids"]) == 2
    instagram_display_name = next(
        item
        for item in brief["claims"]
        if item["predicate"] == "account.display_name" and item["label"].startswith("Instagram")
    )
    assert instagram_display_name["confidence"] == "high"
    assert instagram_display_name["qualification"].startswith("First-party public display name")
    instagram_bio = next(
        item
        for item in brief["claims"]
        if item["predicate"] == "account.public_bio" and item["label"].startswith("Instagram")
    )
    assert instagram_bio["value"].endswith("San Francisco Bay Area")
    assert instagram_bio["confidence"] == "high"

    serialized_brief = json.dumps(brief)
    assert "raw-platform-id-should-not-escape" not in serialized_brief
    assert "private-avatar.jpg" not in serialized_brief
    assert "raw-address@example.test" not in serialized_brief
    with app.state.session_factory() as session:
        attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == job_id))
        report = session.scalar(select(ReportRevision).where(ReportRevision.job_id == job_id))
        snapshot = session.scalar(
            select(CollectionSnapshot).where(CollectionSnapshot.job_id == job_id)
        )
        analysis = session.scalar(select(AnalysisRevision).where(AnalysisRevision.job_id == job_id))
        assert attempt is not None and report is not None
        assert snapshot is not None and analysis is not None
        assert attempt.current_report_revision_id == report.id
        assert attempt.current_analysis_revision_id == analysis.id
        assert attempt.collection_snapshot_id == snapshot.id
        assert session.get(ReportAccessState, report.id).state == "active"

        observations = session.scalars(
            select(SourceObservation)
            .where(SourceObservation.job_id == job_id)
            .order_by(SourceObservation.id)
        ).all()
        assert len(observations) == 3
        assert sorted(item.source_type for item in observations) == [
            "availability_endpoint",
            "first_party_profile",
            "first_party_profile",
        ]
        assert {item.id for item in observations} == set(snapshot.observation_ids)
        first_party_fields = next(
            item.extracted_fields
            for item in observations
            if item.extracted_fields.get("self_described_location")
        )
        assert first_party_fields["username"] == "alice"
        assert first_party_fields["bio"].endswith("San Francisco Bay Area")
        assert first_party_fields["follower_count"] == "1.2K"
        assert first_party_fields["following_count"] == 42
        assert first_party_fields["post_count"] == 7
        assert "uid" not in first_party_fields
        assert "avatar_url" not in first_party_fields
        assert "email" not in first_party_fields

        persisted_association = session.scalar(
            select(Claim).where(
                Claim.job_id == job_id,
                Claim.predicate == "account.association",
            )
        )
        assert persisted_association is not None
        assert (
            session.scalar(
                select(func.count(ClaimEvidence.id)).where(
                    ClaimEvidence.claim_id == persisted_association.id
                )
            )
            == 2
        )
        source_publishers = session.scalars(
            select(SourceDocument.publisher).where(
                SourceDocument.canonical_url.in_(
                    [
                        "https://www.instagram.com/alice/",
                        "https://www.threads.com/@alice",
                    ]
                )
            )
        ).all()
        assert "Instagram" in source_publishers
        counts_before = (
            session.scalar(
                select(func.count(CollectionSnapshot.id)).where(CollectionSnapshot.job_id == job_id)
            ),
            session.scalar(
                select(func.count(AnalysisRevision.id)).where(AnalysisRevision.job_id == job_id)
            ),
            session.scalar(
                select(func.count(ReportRevision.id)).where(ReportRevision.job_id == job_id)
            ),
        )

    with app.state.session_factory() as session, session.begin():
        job = session.get(SearchJob, job_id)
        assert job is not None
        assert not finalize_discovery_if_complete(session, job=job, now=clock.now())
    with app.state.session_factory() as session:
        counts_after = (
            session.scalar(
                select(func.count(CollectionSnapshot.id)).where(CollectionSnapshot.job_id == job_id)
            ),
            session.scalar(
                select(func.count(AnalysisRevision.id)).where(AnalysisRevision.job_id == job_id)
            ),
            session.scalar(
                select(func.count(ReportRevision.id)).where(ReportRevision.job_id == job_id)
            ),
        )
    assert counts_after == counts_before == (1, 1, 1)


def test_seed_is_not_exact_verified_without_first_party_profile_metadata(
    client,
    app,
    settings,
    clock,
    auth_headers,
    monkeypatch,
):
    monkeypatch.setattr(
        "apps.api.app.services.maigret_runs.enrich_first_party_metadata",
        lambda result: result,
    )
    created = create_footprint_job(
        client,
        auth_headers,
        key="footprint-finalization-scanner-only",
        identifier="alice",
        platform="github",
    )
    job_id = created.json()["job_id"]
    snapshot_id, runs = _job_scan_context(app, job_id=job_id)
    _process_results(
        app,
        settings,
        clock,
        run_specs=[
            (
                runs[0][0],
                _profile_result(
                    snapshot_id=snapshot_id,
                    identifier="alice",
                    site_name="GitHub",
                    profile_url="https://github.example/alice",
                    display_name="Alice Example",
                    selected_count=runs[0][1],
                ),
            ),
            (
                runs[1][0],
                _profile_result(
                    snapshot_id=snapshot_id,
                    identifier="alice",
                    site_name="GitLab",
                    profile_url="https://gitlab.example/alice",
                    display_name="Bob Other",
                    selected_count=runs[1][1],
                ),
            ),
            (
                runs[2][0],
                scan_result(
                    snapshot_id=snapshot_id,
                    identifier="alice",
                    site_name="Available",
                    found=False,
                    selected_count=runs[2][1],
                ),
            ),
        ],
    )

    brief = client.get(
        f"/v1/footprint-jobs/{job_id}/brief",
        headers=auth_headers,
    ).json()
    accounts = {item["platform"]: item for item in brief["accounts"]}
    assert accounts["GitHub"]["existence_status"] == "claimed_unverified"
    assert accounts["GitHub"]["identity_status"] == "unverified"
    assert accounts["GitLab"]["identity_status"] == "unverified"
    assert brief["subject"] == "@alice on github"
    exclusions = [
        item for item in brief["claims"] if item["predicate"] == "account.association_exclusion"
    ]
    assert exclusions == []
    with app.state.session_factory() as session:
        source_types = session.scalars(
            select(SourceObservation.source_type)
            .where(SourceObservation.job_id == job_id)
            .order_by(SourceObservation.source_type)
        ).all()
    assert source_types == ["candidate_discovery", "candidate_discovery"]


def test_supported_first_party_profile_can_be_verified_then_excluded_from_cluster(
    client,
    app,
    settings,
    clock,
    auth_headers,
    monkeypatch,
):
    monkeypatch.setattr(
        "apps.api.app.services.maigret_runs.enrich_first_party_metadata",
        lambda result: result,
    )
    created = create_footprint_job(
        client,
        auth_headers,
        key="footprint-finalization-first-party-conflict",
        identifier="alice",
        platform="instagram",
    )
    job_id = created.json()["job_id"]
    snapshot_id, runs = _job_scan_context(app, job_id=job_id)
    _process_results(
        app,
        settings,
        clock,
        run_specs=[
            (
                runs[0][0],
                _profile_result(
                    snapshot_id=snapshot_id,
                    identifier="alice",
                    site_name="Instagram",
                    profile_url="https://www.instagram.com/alice/",
                    display_name="Alice Example",
                    selected_count=runs[0][1],
                ),
            ),
            (
                runs[1][0],
                _profile_result(
                    snapshot_id=snapshot_id,
                    identifier="alice",
                    site_name="Pinterest",
                    profile_url="https://www.pinterest.com/alice/",
                    display_name="Different Person",
                    selected_count=runs[1][1],
                ),
            ),
            (
                runs[2][0],
                scan_result(
                    snapshot_id=snapshot_id,
                    identifier="alice",
                    site_name="Available",
                    found=False,
                    selected_count=runs[2][1],
                ),
            ),
        ],
    )

    brief = client.get(
        f"/v1/footprint-jobs/{job_id}/brief",
        headers=auth_headers,
    ).json()
    accounts = {item["platform"]: item for item in brief["accounts"]}
    assert accounts["Pinterest"]["existence_status"] == "exact_verified"
    assert accounts["Pinterest"]["identity_status"] == "excluded"
    pinterest_display_name = next(
        item
        for item in brief["claims"]
        if item["predicate"] == "account.display_name" and item["label"].startswith("Pinterest")
    )
    assert pinterest_display_name["confidence"] == "high"


def test_repeated_first_party_reference_name_does_not_promote_shared_surname(
    client,
    app,
    settings,
    clock,
    auth_headers,
    monkeypatch,
):
    monkeypatch.setattr(
        "apps.api.app.services.maigret_runs.enrich_first_party_metadata",
        lambda result: result,
    )
    created = create_footprint_job(
        client,
        auth_headers,
        key="footprint-finalization-surname-rule",
        identifier="shared_handle",
        platform="instagram",
    )
    job_id = created.json()["job_id"]
    snapshot_id, runs = _job_scan_context(app, job_id=job_id)
    profiles = (
        ("Instagram", "https://www.instagram.com/shared_handle/", "Raymond Gu"),
        ("Threads", "https://www.threads.com/@shared_handle", "Raymond Gu"),
        ("Clubhouse", "https://www.clubhouse.com/@shared_handle", "Jingyao Gu"),
    )
    _process_results(
        app,
        settings,
        clock,
        run_specs=[
            (
                run_id,
                _profile_result(
                    snapshot_id=snapshot_id,
                    identifier="shared_handle",
                    site_name=site_name,
                    profile_url=profile_url,
                    display_name=display_name,
                    selected_count=selected_count,
                ),
            )
            for (run_id, selected_count), (site_name, profile_url, display_name) in zip(
                runs,
                profiles,
                strict=True,
            )
        ],
    )

    brief = client.get(
        f"/v1/footprint-jobs/{job_id}/brief",
        headers=auth_headers,
    ).json()
    assert brief["report_type"] == "account_centric"
    assert brief["overall_identity_status"] == "unverified"
    accounts = {item["platform"]: item for item in brief["accounts"]}
    assert accounts["Clubhouse"]["identity_status"] == "unverified"
    assert accounts["Clubhouse"]["confidence"] == "low"
    assert any("shared surname" in reason for reason in accounts["Clubhouse"]["reasons"])
    clubhouse_claims = [
        item
        for item in brief["claims"]
        if item["predicate"] == "account.association" and item["label"].startswith("Clubhouse")
    ]
    assert clubhouse_claims == []
    assert any(
        "differing display names" in reason for reason in brief["identity_reasons"]["limiting"]
    )


def test_conclusive_no_candidates_still_creates_coverage_brief(
    client,
    app,
    settings,
    clock,
    auth_headers,
):
    created = create_footprint_job(
        client,
        auth_headers,
        key="footprint-finalization-no-candidates",
        identifier="no_candidate",
        platform="github",
    )
    job_id = created.json()["job_id"]
    snapshot_id, runs = _job_scan_context(app, job_id=job_id)
    _process_results(
        app,
        settings,
        clock,
        run_specs=[
            (
                run_id,
                scan_result(
                    snapshot_id=snapshot_id,
                    identifier="no_candidate",
                    site_name=f"Available{index}",
                    found=False,
                    selected_count=selected_count,
                ),
            )
            for index, (run_id, selected_count) in enumerate(runs)
        ],
    )

    job_response = client.get(
        f"/v1/footprint-jobs/{job_id}",
        headers=auth_headers,
    )
    brief_response = client.get(
        f"/v1/footprint-jobs/{job_id}/brief",
        headers=auth_headers,
    )
    assert job_response.json()["status"] == "no_candidates"
    assert brief_response.status_code == 200
    assert brief_response.json()["accounts"] == []
    assert brief_response.json()["claims"] == []
    assert brief_response.json()["overall_identity_status"] == "unverified"
    with app.state.session_factory() as session:
        snapshot = session.scalar(
            select(CollectionSnapshot).where(CollectionSnapshot.job_id == job_id)
        )
        assert snapshot is not None
        assert snapshot.observation_ids == []
