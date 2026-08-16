from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from apps.api.app.core.crypto import stable_payload_hash
from apps.api.app.core.db import build_engine, build_session_factory
from apps.api.app.models.entities import (
    AccountNode,
    Base,
    CollectionSnapshot,
    DiscoveryEdge,
    GroundedSynthesisResult,
    JobAttempt,
    MaigretSiteCheck,
    ProviderRun,
    ProviderRunSourceUse,
    ReportRevision,
    SearchJob,
    SourceDocument,
    SourceObservation,
    new_id,
)
from apps.api.app.schemas.generated import FootprintBriefResponse
from apps.api.app.services.footprint_finalization import (
    _PersonDecision,
    _validated_deep_story,
    _validated_text,
    finalize_footprint_if_complete,
)
from apps.api.app.services.grounded_synthesis_scheduling import (
    GROUNDED_SYNTHESIS_PROVIDER_ID,
)
from apps.api.app.services.professional_search_scheduling import (
    EXA_PEOPLE_PROVIDER_ID,
    GITHUB_PROFESSIONAL_PROVIDER_ID,
)

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
HANDLE = "octaviyao"


def test_reader_facing_synthesis_text_decodes_entities_and_strips_markup():
    assert (
        _validated_text(
            "Bio says &#x27;la | sf&#x27; and <b>public</b>.",
            maximum=120,
        )
        == "Bio says 'la | sf' and public."
    )


@dataclass(frozen=True)
class _Graph:
    factory: object
    job_id: str
    attempt_id: str
    root_run_id: str


def _new_graph(*, search_mode: str = "quick") -> _Graph:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    job_id = new_id()
    attempt_id = new_id()
    root_run_id = new_id()
    deadline = NOW + timedelta(minutes=5)
    expires_at = NOW + timedelta(days=1)

    with factory() as session, session.begin():
        session.add(
            SearchJob(
                id=job_id,
                user_id="professional-finalization-test-user",
                refresh_of_job_id=None,
                history_reuse_policy=None,
                normalized_identifier_hmac="a" * 64,
                canonical_input_url_ciphertext=None,
                input_provider_id="maigret_discovery_v1",
                canonicalization_version="seed-identifier-v1",
                eligibility_verification_id=None,
                job_kind="footprint_discovery",
                seed_kind="platform_identifier",
                seed_platform="instagram",
                seed_identifier_type="handle",
                seed_identifier=HANDLE,
                normalized_seed=f"instagram:handle:{HANDLE}",
                search_mode=search_mode,
                catalog_profile="quick",
                catalog_snapshot_id=None,
                exploration_status="running",
                purpose="digital_footprint",
                fixture_key=None,
                status="discovering",
                active_attempt_id=attempt_id,
                accepted_at=NOW,
                collection_cutoff_at=deadline,
                fallback_at=deadline,
                deadline_at=deadline,
                completion_policy_id="candidate-map-v1",
                policy_version="test-policy",
                locale="en-US",
                acceptance_epoch=1,
                row_version=1,
                cancelled_at=None,
                expires_at=expires_at,
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
                started_at=NOW,
                finished_at=None,
                terminal_reason=None,
            )
        )
        session.flush()
        session.add(
            ProviderRun(
                id=root_run_id,
                job_id=job_id,
                attempt_id=attempt_id,
                logical_run_id="maigret:root:000",
                provider_id="maigret_discovery_v1",
                parent_run_id=None,
                depth=0,
                query_config={"site_names": ["Instagram", "Clubhouse"]},
                status="success",
                required_for_finalization=True,
                lease_generation=1,
                lease_expires_at=None,
                acceptance_epoch=1,
                result_count=1,
                deadline_at=deadline,
                expires_at=expires_at,
            )
        )

    return _Graph(
        factory=factory,
        job_id=job_id,
        attempt_id=attempt_id,
        root_run_id=root_run_id,
    )


def _add_exact_root_profile(
    graph: _Graph,
    *,
    platform: str,
    display_name: str,
    location: str,
    ordinal: int,
) -> str:
    profile_urls = {
        "Instagram": f"https://www.instagram.com/{HANDLE}/",
        "Clubhouse": f"https://www.clubhouse.com/@{HANDLE}",
    }
    profile_url = profile_urls[platform]
    node_id = new_id()
    check_id = new_id()
    with graph.factory() as session, session.begin():
        session.add(
            MaigretSiteCheck(
                id=check_id,
                job_id=graph.job_id,
                provider_run_id=graph.root_run_id,
                site_key=f"{platform.casefold()}-{ordinal}",
                site_name=platform,
                source_name=None,
                queried_identifier=HANDLE,
                queried_identifier_type="username",
                url_main=profile_url.split(f"/{HANDLE}", 1)[0],
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
                        "name": display_name,
                        "ordinal": ordinal,
                    }
                ),
                observed_at=NOW + timedelta(seconds=ordinal),
            )
        )
        session.add(
            AccountNode(
                id=node_id,
                job_id=graph.job_id,
                platform=platform,
                canonical_handle=HANDLE,
                canonical_url=profile_url,
                display_name=display_name,
                identity_confidence_tier="possible",
                selection_state="undecided",
                is_similar=False,
                profile_data={},
                first_observed_at=NOW,
                last_observed_at=NOW,
            )
        )
        session.flush()
        session.add(
            DiscoveryEdge(
                id=new_id(),
                job_id=graph.job_id,
                provider_run_id=graph.root_run_id,
                site_check_id=check_id,
                source_observation_id=None,
                child_account_node_id=node_id,
                parent_seed=f"instagram:handle:{HANDLE}",
                discovery_method="username_catalog_probe",
                discovery_engine="maigret",
                depth=0,
                created_at=NOW,
            )
        )
    return node_id


def _add_professional_result(
    graph: _Graph,
    *,
    provider_id: str,
    full_name: str,
    source_node_id: str,
    context_source_node_ids: tuple[str, ...] = (),
    ordinal: int,
    platform: str,
    profile_url: str,
    handle: str,
    display_name: str | None,
    location: str | None = None,
    query_location: str | None = None,
    work_history: list[dict[str, str]] | None = None,
    education_history: list[dict[str, str]] | None = None,
    status: str = "success",
) -> tuple[str, str]:
    run_id = new_id()
    observation_id = new_id()
    node_id = new_id()
    expires_at = NOW + timedelta(days=1)
    source_type = (
        "first_party_profile_api"
        if provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID
        else "professional_profile_index"
    )
    fields: dict[str, object] = {
        "platform": platform,
        "profile_url": profile_url,
        "handle": handle,
    }
    if display_name is not None:
        fields["display_name"] = display_name
    if location is not None:
        fields["location"] = location
    if work_history is not None:
        fields["work_history"] = work_history
    if education_history is not None:
        fields["education_history"] = education_history

    query_config: dict[str, object] = {
        "full_name": full_name,
        "source_node_ids": sorted({source_node_id, *context_source_node_ids}),
        "name_source_node_ids": [source_node_id],
    }
    if query_location is not None:
        query_config["broad_location"] = query_location
    if provider_id == EXA_PEOPLE_PROVIDER_ID:
        query_config["max_results"] = 5
    else:
        query_config["max_profiles"] = 3

    with graph.factory() as session, session.begin():
        session.add(
            ProviderRun(
                id=run_id,
                job_id=graph.job_id,
                attempt_id=graph.attempt_id,
                logical_run_id=f"professional:{provider_id}:{ordinal:02d}",
                provider_id=provider_id,
                parent_run_id=graph.root_run_id,
                depth=1,
                query_config=query_config,
                status=status,
                required_for_finalization=True,
                lease_generation=1,
                lease_expires_at=None,
                acceptance_epoch=1,
                result_count=1,
                deadline_at=NOW + timedelta(minutes=5),
                expires_at=expires_at,
            )
        )
        session.flush()
        document = SourceDocument(
            id=new_id(),
            canonical_url=profile_url,
            publisher=platform,
            title=f"{platform} public profile for {display_name or handle}",
            mime_type="application/json",
            content_hash=stable_payload_hash(
                {
                    "provider": provider_id,
                    "profile_url": profile_url,
                    "fields": fields,
                }
            ),
            lineage_key=f"{provider_id}:{handle}",
            expires_at=expires_at,
        )
        session.add(document)
        session.flush()
        source_use = ProviderRunSourceUse(
            id=new_id(),
            provider_run_id=run_id,
            document_id=document.id,
            disposition=(
                "accepted"
                if provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID
                else "candidate_discovery"
            ),
            policy_version="test-policy",
        )
        session.add(source_use)
        session.flush()
        session.add(
            SourceObservation(
                id=observation_id,
                job_id=graph.job_id,
                source_use_id=source_use.id,
                source_type=source_type,
                trust_class=(
                    "first_party_api"
                    if provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID
                    else "search_index"
                ),
                retrieved_at=NOW + timedelta(seconds=10 + ordinal),
                excerpt=f"Public professional profile for {display_name or handle}.",
                span_locator={
                    "kind": "allowlisted_professional_profile_fields",
                    "fields": sorted(fields),
                },
                extracted_fields=fields,
                extraction_version="professional-search-v1",
                expires_at=expires_at,
            )
        )
        session.add(
            AccountNode(
                id=node_id,
                job_id=graph.job_id,
                platform=platform,
                canonical_handle=handle,
                canonical_url=profile_url,
                display_name=display_name,
                identity_confidence_tier="possible",
                selection_state="undecided",
                is_similar=False,
                profile_data={
                    "source_provider": provider_id,
                    "fields": fields,
                    "professional_sources": {provider_id: fields},
                },
                first_observed_at=NOW,
                last_observed_at=NOW,
            )
        )
        session.flush()
        session.add(
            DiscoveryEdge(
                id=new_id(),
                job_id=graph.job_id,
                provider_run_id=run_id,
                site_check_id=None,
                source_observation_id=observation_id,
                child_account_node_id=node_id,
                parent_seed=f"instagram:handle:{HANDLE}",
                discovery_method=(
                    "github_professional_search"
                    if provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID
                    else "professional_index_search"
                ),
                discovery_engine=(
                    "github" if provider_id == GITHUB_PROFESSIONAL_PROVIDER_ID else "exa"
                ),
                depth=1,
                created_at=NOW,
            )
        )
    return node_id, observation_id


def _add_terminal_professional_run(
    graph: _Graph,
    *,
    provider_id: str,
    status: str,
) -> str:
    run_id = new_id()
    with graph.factory() as session, session.begin():
        session.add(
            ProviderRun(
                id=run_id,
                job_id=graph.job_id,
                attempt_id=graph.attempt_id,
                logical_run_id=f"professional:{provider_id}:terminal",
                provider_id=provider_id,
                parent_run_id=graph.root_run_id,
                depth=1,
                query_config={
                    "full_name": "Alice Example",
                    "max_results": 5,
                },
                status=status,
                required_for_finalization=True,
                lease_generation=1,
                lease_expires_at=None,
                acceptance_epoch=1,
                result_count=0,
                deadline_at=NOW + timedelta(minutes=5),
                expires_at=NOW + timedelta(days=1),
            )
        )
    return run_id


def _add_grounded_synthesis_result(
    graph: _Graph,
    *,
    source_id: str,
    cited_source_id: str | None = None,
    output_override: dict[str, object] | None = None,
    gateway: str = "openai",
) -> str:
    run_id = new_id()
    expires_at = NOW + timedelta(days=1)
    citation = cited_source_id or source_id
    model = "openai/gpt-5.6-sol" if gateway == "openrouter" else "gpt-5.6-sol"
    output = output_override or {
        "summary": (
            "The source-linked professional profile describes product design work at Example Labs."
        ),
        "summary_source_ids": [citation],
        "narrative_sections": [
            {
                "key": "professional",
                "title": "Professional profile",
                "body": ("The public profile describes a product role and names Example Labs."),
                "source_ids": [citation],
            }
        ],
        "claims": [],
        "supporting_reasons": [
            {
                "text": "The profile combines the public name and role.",
                "source_ids": [citation],
            }
        ],
        "limiting_reasons": [
            {
                "text": "The professional description is self-reported.",
                "source_ids": [citation],
            }
        ],
    }
    with graph.factory() as session, session.begin():
        schema_version = output.get("schema_version")
        prompt_version = {
            "grounded-digital-footprint-v4": "grounded-footprint-v4",
            "grounded-digital-footprint-v3": "grounded-footprint-v3",
            "grounded-digital-footprint-v2": "grounded-footprint-v2",
        }.get(schema_version, "grounded-footprint-v1")
        session.add(
            ProviderRun(
                id=run_id,
                job_id=graph.job_id,
                attempt_id=graph.attempt_id,
                logical_run_id=(
                    "synthesis:openrouter:grounded:v2"
                    if gateway == "openrouter"
                    else "synthesis:openai:grounded:v1"
                ),
                provider_id=(
                    GROUNDED_SYNTHESIS_PROVIDER_ID
                    if gateway == "openrouter"
                    else "openai_grounded_synthesis_v1"
                ),
                parent_run_id=None,
                depth=2,
                query_config={
                    **({"gateway": gateway} if gateway == "openrouter" else {}),
                    "model": model,
                    "prompt_version": prompt_version,
                },
                status="success",
                required_for_finalization=True,
                lease_generation=1,
                lease_expires_at=None,
                acceptance_epoch=1,
                result_count=1,
                deadline_at=NOW + timedelta(minutes=5),
                expires_at=expires_at,
            )
        )
        session.flush()
        session.add(
            GroundedSynthesisResult(
                provider_run_id=run_id,
                job_id=graph.job_id,
                status="success",
                model=model,
                prompt_version=prompt_version,
                input_checksum="f" * 64,
                output=output,
                usage={
                    "input_tokens": 120,
                    "output_tokens": 80,
                    "total_tokens": 200,
                },
                error_code=None,
                created_at=NOW,
                expires_at=expires_at,
            )
        )
    return run_id


def _finalize(graph: _Graph) -> tuple[dict[str, object], CollectionSnapshot]:
    with graph.factory() as session, session.begin():
        job = session.get(SearchJob, graph.job_id)
        assert job is not None
        assert finalize_footprint_if_complete(session, job=job, now=NOW)

    with graph.factory() as session:
        report = session.scalar(select(ReportRevision).where(ReportRevision.job_id == graph.job_id))
        snapshot = session.scalar(
            select(CollectionSnapshot).where(CollectionSnapshot.job_id == graph.job_id)
        )
        assert report is not None
        assert snapshot is not None
        return dict(report.content), snapshot


def _account(
    brief: dict[str, object],
    *,
    platform: str,
) -> dict[str, object]:
    accounts = brief["accounts"]
    assert isinstance(accounts, list)
    return next(
        item for item in accounts if isinstance(item, dict) and item["platform"] == platform
    )


def _claims(brief: dict[str, object]) -> list[dict[str, object]]:
    claims = brief["claims"]
    assert isinstance(claims, list)
    return [item for item in claims if isinstance(item, dict)]


def test_exa_name_and_location_bridge_promotes_one_person_and_freezes_all_evidence():
    graph = _new_graph()
    root_node_id = _add_exact_root_profile(
        graph,
        platform="Instagram",
        display_name="Alice Example",
        location="San Francisco Bay Area",
        ordinal=1,
    )
    _, exa_observation_id = _add_professional_result(
        graph,
        provider_id=EXA_PEOPLE_PROVIDER_ID,
        full_name="Alice Example",
        source_node_id=root_node_id,
        ordinal=1,
        platform="LinkedIn",
        profile_url="https://www.linkedin.com/in/alice-example",
        handle="alice-example",
        display_name="Alice Example",
        location="San Francisco, California",
        query_location="San Francisco Bay Area",
        work_history=[
            {
                "title": "Founder",
                "company": "Example Labs",
            }
        ],
    )

    brief, snapshot = _finalize(graph)

    assert brief["report_type"] == "person_centric"
    assert brief["overall_identity_status"] == "likely"
    assert brief["subject"] == f"Alice Example (@{HANDLE})"
    linkedin = _account(brief, platform="LinkedIn")
    assert linkedin["existence_status"] == "indexed_profile"
    assert linkedin["identity_status"] == "likely"

    with graph.factory() as session:
        all_observation_ids = set(
            session.scalars(
                select(SourceObservation.id).where(SourceObservation.job_id == graph.job_id)
            ).all()
        )
    assert exa_observation_id in all_observation_ids
    assert set(snapshot.observation_ids) == all_observation_ids
    assert len(all_observation_ids) == 2

    role_claim = next(
        claim for claim in _claims(brief) if claim["predicate"] == "professional.role"
    )
    assert role_claim["value"] == "Founder at Example Labs"
    assert "cached, stale" in str(role_claim["qualification"])
    assert role_claim["source_ids"] == [exa_observation_id]


def test_exa_name_only_stays_account_centric_and_suppresses_history_claims():
    graph = _new_graph()
    root_node_id = _add_exact_root_profile(
        graph,
        platform="Instagram",
        display_name="Alice Example",
        location="San Francisco Bay Area",
        ordinal=1,
    )
    _add_professional_result(
        graph,
        provider_id=EXA_PEOPLE_PROVIDER_ID,
        full_name="Alice Example",
        source_node_id=root_node_id,
        ordinal=1,
        platform="LinkedIn",
        profile_url="https://www.linkedin.com/in/alice-name-only",
        handle="alice-name-only",
        display_name="Alice Example",
        work_history=[
            {
                "title": "Founder",
                "company": "Uncorroborated Company",
            }
        ],
        education_history=[
            {
                "degree": "Example Degree",
                "institution": "Uncorroborated University",
            }
        ],
    )

    brief, _ = _finalize(graph)

    assert brief["report_type"] == "account_centric"
    assert brief["overall_identity_status"] == "unverified"
    linkedin = _account(brief, platform="LinkedIn")
    assert linkedin["existence_status"] == "indexed_profile"
    assert linkedin["identity_status"] == "unverified"
    predicates = {claim["predicate"] for claim in _claims(brief)}
    assert "professional.role" not in predicates
    assert "professional.education" not in predicates


def test_github_derived_login_without_display_name_remains_unverified():
    graph = _new_graph()
    root_node_id = _add_exact_root_profile(
        graph,
        platform="Instagram",
        display_name="Alice Example",
        location="San Francisco Bay Area",
        ordinal=1,
    )
    _add_professional_result(
        graph,
        provider_id=GITHUB_PROFESSIONAL_PROVIDER_ID,
        full_name="Alice Example",
        source_node_id=root_node_id,
        ordinal=1,
        platform="GitHub",
        profile_url="https://github.com/aliceexample",
        handle="aliceexample",
        display_name=None,
        location="San Francisco",
        query_location="San Francisco Bay Area",
    )

    brief, _ = _finalize(graph)

    assert brief["report_type"] == "account_centric"
    assert brief["overall_identity_status"] == "unverified"
    github = _account(brief, platform="GitHub")
    assert github["existence_status"] == "exact_verified"
    assert github["identity_status"] == "unverified"
    assert github["display_name"] is None
    assert any(
        "name-derived professional search result" in reason.casefold()
        for reason in github["reasons"]
    )


def test_two_conflicting_passing_names_keep_report_account_centric():
    graph = _new_graph()
    alice_root_id = _add_exact_root_profile(
        graph,
        platform="Instagram",
        display_name="Alice Example",
        location="San Francisco Bay Area",
        ordinal=1,
    )
    bob_root_id = _add_exact_root_profile(
        graph,
        platform="Clubhouse",
        display_name="Bob Builder",
        location="New York City",
        ordinal=2,
    )
    _add_professional_result(
        graph,
        provider_id=EXA_PEOPLE_PROVIDER_ID,
        full_name="Alice Example",
        source_node_id=alice_root_id,
        ordinal=1,
        platform="LinkedIn",
        profile_url="https://www.linkedin.com/in/alice-example",
        handle="alice-example",
        display_name="Alice Example",
        location="San Francisco, California",
        query_location="San Francisco Bay Area",
    )
    _add_professional_result(
        graph,
        provider_id=EXA_PEOPLE_PROVIDER_ID,
        full_name="Bob Builder",
        source_node_id=bob_root_id,
        ordinal=2,
        platform="LinkedIn",
        profile_url="https://www.linkedin.com/in/bob-builder",
        handle="bob-builder",
        display_name="Bob Builder",
        location="New York, New York",
        query_location="New York City",
    )

    brief, _ = _finalize(graph)

    assert brief["report_type"] == "account_centric"
    assert brief["overall_identity_status"] == "unverified"
    linkedin_accounts = [
        account
        for account in brief["accounts"]
        if isinstance(account, dict) and account["platform"] == "LinkedIn"
    ]
    assert len(linkedin_accounts) == 2
    assert {account["identity_status"] for account in linkedin_accounts} == {"likely"}
    assert any(
        "unique full-name hypothesis" in reason for reason in brief["identity_reasons"]["limiting"]
    )


def test_context_fallback_node_does_not_gain_professional_identity_support():
    graph = _new_graph()
    selected_root_id = _add_exact_root_profile(
        graph,
        platform="Instagram",
        display_name="Jingyao Gu",
        location="San Francisco Bay Area",
        ordinal=1,
    )
    competing_root_id = _add_exact_root_profile(
        graph,
        platform="Clubhouse",
        display_name="Raymond Gu",
        location="New York City",
        ordinal=2,
    )
    with graph.factory() as session, session.begin():
        selected_root = session.get(AccountNode, selected_root_id)
        assert selected_root is not None
        selected_root.selection_state = "included"

    _add_professional_result(
        graph,
        provider_id=EXA_PEOPLE_PROVIDER_ID,
        full_name="Raymond Gu",
        source_node_id=competing_root_id,
        context_source_node_ids=(selected_root_id,),
        ordinal=1,
        platform="LinkedIn",
        profile_url="https://www.linkedin.com/in/raymond-gu",
        handle="raymond-gu",
        display_name="Raymond Gu",
        location="San Francisco, California",
        query_location="San Francisco Bay Area",
    )

    brief, _ = _finalize(graph)

    assert brief["report_type"] == "account_centric"
    assert brief["overall_identity_status"] == "unverified"
    instagram = _account(brief, platform="Instagram")
    clubhouse = _account(brief, platform="Clubhouse")
    linkedin = _account(brief, platform="LinkedIn")
    assert instagram["display_name"] == "Jingyao Gu"
    assert instagram["identity_status"] == "unverified"
    assert not any(
        "professional profile corroborates" in reason.casefold() for reason in instagram["reasons"]
    )
    assert clubhouse["identity_status"] == "likely"
    assert linkedin["identity_status"] == "likely"


def test_selected_anchor_decision_requires_exact_name_source_lineage():
    graph = _new_graph()
    selected_root_id = _add_exact_root_profile(
        graph,
        platform="Instagram",
        display_name="Alice Example",
        location="San Francisco Bay Area",
        ordinal=1,
    )
    name_source_root_id = _add_exact_root_profile(
        graph,
        platform="Clubhouse",
        display_name="Alice Example",
        location="New York City",
        ordinal=2,
    )
    with graph.factory() as session, session.begin():
        selected_root = session.get(AccountNode, selected_root_id)
        assert selected_root is not None
        selected_root.selection_state = "included"

    _add_professional_result(
        graph,
        provider_id=EXA_PEOPLE_PROVIDER_ID,
        full_name="Alice Example",
        source_node_id=name_source_root_id,
        context_source_node_ids=(selected_root_id,),
        ordinal=1,
        platform="LinkedIn",
        profile_url="https://www.linkedin.com/in/alice-example-context",
        handle="alice-example-context",
        display_name="Alice Example",
        location="San Francisco, California",
        query_location="San Francisco Bay Area",
    )

    brief, _ = _finalize(graph)

    assert brief["report_type"] == "account_centric"
    assert brief["overall_identity_status"] == "unverified"
    assert _account(brief, platform="Instagram")["identity_status"] == "unverified"


def test_skipped_configuration_is_terminal_and_produces_partial_brief():
    graph = _new_graph()
    _add_exact_root_profile(
        graph,
        platform="Instagram",
        display_name="Alice Example",
        location="San Francisco Bay Area",
        ordinal=1,
    )
    _add_terminal_professional_run(
        graph,
        provider_id=EXA_PEOPLE_PROVIDER_ID,
        status="skipped_configuration",
    )

    brief, snapshot = _finalize(graph)

    assert brief["report_type"] == "account_centric"
    assert brief["overall_identity_status"] == "unverified"
    assert len(snapshot.observation_ids) == 1
    assert any(
        "exa people search ended as skipped configuration" in limitation.casefold()
        for limitation in brief["limitations"]
    )
    with graph.factory() as session:
        job = session.get(SearchJob, graph.job_id)
        attempt = session.get(JobAttempt, graph.attempt_id)
        assert job is not None and job.status == "ready_partial"
        assert attempt is not None and attempt.status == "ready_partial"


def test_deep_report_merges_only_source_grounded_narrative():
    graph = _new_graph(search_mode="deep")
    root_node_id = _add_exact_root_profile(
        graph,
        platform="Instagram",
        display_name="Alice Example",
        location="San Francisco Bay Area",
        ordinal=1,
    )
    _, professional_source_id = _add_professional_result(
        graph,
        provider_id=GITHUB_PROFESSIONAL_PROVIDER_ID,
        full_name="Alice Example",
        source_node_id=root_node_id,
        ordinal=1,
        platform="GitHub",
        profile_url="https://github.com/aliceexample",
        handle="aliceexample",
        display_name="Alice Example",
        location="San Francisco",
        query_location="San Francisco Bay Area",
    )
    _add_grounded_synthesis_result(
        graph,
        source_id=professional_source_id,
    )

    brief, snapshot = _finalize(graph)

    assert brief["synthesis"] == {
        "mode": "llm_grounded",
        "status": "complete",
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "prompt_version": "grounded-footprint-v1",
        "fallback_reason": None,
    }
    assert brief["narrative_sections"][0]["source_ids"] == [professional_source_id]
    assert "product design work" in brief["summary"]
    github_manifest = next(
        item
        for item in snapshot.provider_manifest
        if item["provider_id"] == GITHUB_PROFESSIONAL_PROVIDER_ID
    )
    assert github_manifest["max_profiles"] == 3
    synthesis_manifest = next(
        item
        for item in snapshot.provider_manifest
        if item["provider_id"] == "openai_grounded_synthesis_v1"
    )
    assert synthesis_manifest["model"] == "gpt-5.6-sol"
    assert synthesis_manifest["gateway"] == "openai"
    assert synthesis_manifest["output_checksum"]


def test_deep_v4_report_exposes_profile_and_career_timeline():
    graph = _new_graph(search_mode="deep")
    root_node_id = _add_exact_root_profile(
        graph,
        platform="Instagram",
        display_name="Alice Example",
        location="San Francisco Bay Area",
        ordinal=1,
    )
    professional_node_id, professional_source_id = _add_professional_result(
        graph,
        provider_id=EXA_PEOPLE_PROVIDER_ID,
        full_name="Alice Example",
        source_node_id=root_node_id,
        ordinal=1,
        platform="LinkedIn",
        profile_url="https://www.linkedin.com/in/alice-example",
        handle="alice-example",
        display_name="Alice Example",
        location="San Francisco, California",
        query_location="San Francisco Bay Area",
        work_history=[{"title": "Founder", "company": "Example Labs"}],
    )
    cited = [professional_source_id]
    _add_grounded_synthesis_result(
        graph,
        source_id=professional_source_id,
        gateway="openrouter",
        output_override={
            "schema_version": "grounded-digital-footprint-v4",
            "report_synthesis": {
                "report_type": "person_centric",
                "one_sentence_conclusion": (
                    "The public evidence likely connects Alice Example's Instagram "
                    "and indexed professional presence."
                ),
                "identity_status": "likely",
                "overall_confidence": "medium",
                "likely_public_identity": "Alice Example",
                "broad_location": "San Francisco Bay Area",
                "major_boundary": (
                    "The professional record is indexed and no reciprocal first-party "
                    "cross-link was collected."
                ),
                "source_ids": cited,
            },
            "subject_profile": {
                "identity": {
                    "value": "Alice Example",
                    "confidence": "medium",
                    "basis": "mixed",
                    "explanation": (
                        "The public name and broad location align across the profiles."
                    ),
                    "source_ids": cited,
                },
                "location": {
                    "value": "San Francisco Bay Area",
                    "confidence": "medium",
                    "basis": "mixed",
                    "explanation": "Compatible broad locations appear in the profiles.",
                    "source_ids": cited,
                },
                "occupation": {
                    "value": "Founder at Example Labs",
                    "confidence": "medium",
                    "basis": "indexed",
                    "explanation": (
                        "An indexed professional profile reports this role and may be stale."
                    ),
                    "source_ids": cited,
                },
                "education": {
                    "value": None,
                    "confidence": "medium",
                    "basis": "indexed",
                    "explanation": "No reliable public education record was collected.",
                    "source_ids": cited,
                },
                "interests": [],
                "likes": [],
                "dislikes": [
                    {
                        "label": "Long meetings",
                        "confidence": "low",
                        "basis": "inferred",
                        "explanation": "A preference should not be inferred from sparse activity.",
                        "source_ids": cited,
                    }
                ],
                "unknowns": [
                    {
                        "topic": "education",
                        "explanation": "No reliable public education record was collected.",
                        "source_ids": [],
                    },
                    {
                        "topic": "likes",
                        "explanation": "No reliable public preferences were collected.",
                        "source_ids": [],
                    },
                    {
                        "topic": "dislikes",
                        "explanation": "No explicit public dislikes were collected.",
                        "source_ids": [],
                    },
                ],
                "career_timeline": [
                    {
                        "entry_type": "work",
                        "title": "Founder",
                        "organization": "Example Labs",
                        "timeframe": None,
                        "currentness": "current",
                        "confidence": "medium",
                        "basis": "indexed",
                        "explanation": (
                            "The indexed professional profile reports this role without dates."
                        ),
                        "source_ids": cited,
                    },
                    {
                        "entry_type": "work",
                        "title": "Guessed advisor",
                        "organization": None,
                        "timeframe": None,
                        "currentness": "unclear",
                        "confidence": "low",
                        "basis": "inferred",
                        "explanation": "This unsupported inference should be omitted.",
                        "source_ids": cited,
                    },
                ],
            },
            "summary": (
                "Across the cited profiles, the shared public name and compatible broad "
                "location support one likely person hypothesis while the professional "
                "details remain potentially stale."
            ),
            "summary_source_ids": cited,
            "identity_facts": [
                {
                    "label": "Public identity",
                    "value": "Alice Example",
                    "confidence": "medium",
                    "status": "likely",
                    "qualification": "Supported by compatible public profile context.",
                    "source_ids": cited,
                }
            ],
            "account_assessments": [
                {
                    "account_id": professional_node_id,
                    "platform": "LinkedIn",
                    "canonical_handle": "alice-example",
                    "canonical_url": "https://www.linkedin.com/in/alice-example",
                    "existence_status": "candidate",
                    "association_status": "likely",
                    "confidence": "medium_high",
                    "rationale": ("The indexed profile shares the public name and broad location."),
                    "source_ids": cited,
                    "public_facts": [
                        {
                            "text": "The profile names a founder role at Example Labs.",
                            "source_ids": cited,
                        }
                    ],
                    "association_reasons": [
                        {
                            "text": "The name and broad location are compatible.",
                            "source_ids": cited,
                        }
                    ],
                }
            ],
            "narrative_sections": [
                {
                    "key": "professional",
                    "title": "Professional footprint",
                    "body": (
                        "The indexed professional profile describes a founder role at "
                        "Example Labs, but it should be treated as potentially stale."
                    ),
                    "source_ids": cited,
                    "highlights": [
                        {
                            "text": "The role is indexed rather than first-party verified.",
                            "source_ids": cited,
                        }
                    ],
                }
            ],
            "claims": [
                {
                    "claim_id": "professional-role",
                    "predicate": "professional.role",
                    "label": "Public role",
                    "value": "Founder at Example Labs",
                    "confidence": "medium_high",
                    "status": "likely",
                    "source_ids": cited,
                    "contradicting_source_ids": [],
                    "qualification": "Indexed professional information may be stale.",
                    "supporting_evidence": [
                        {
                            "text": "The indexed work history names the role and company.",
                            "source_ids": cited,
                        }
                    ],
                    "limiting_evidence": [
                        {
                            "text": "No independent current employer source was collected.",
                            "source_ids": cited,
                        }
                    ],
                }
            ],
            "supporting_reasons": [
                {
                    "text": "The public name and broad location agree.",
                    "source_ids": cited,
                }
            ],
            "limiting_reasons": [
                {
                    "text": "The professional source is an index.",
                    "source_ids": cited,
                }
            ],
            "excluded_candidates": [],
            "channel_coverage": [
                {
                    "channel": "LinkedIn",
                    "status": "likely",
                    "detail": "One indexed professional profile supported the hypothesis.",
                    "source_ids": cited,
                }
            ],
            "next_verification_steps": [
                {
                    "text": "A reciprocal first-party cross-link would strengthen the association.",
                    "source_ids": cited,
                }
            ],
        },
    )

    brief, _snapshot = _finalize(graph)

    assert brief["summary"].startswith("The public evidence likely connects")
    assert brief["deep_story"]["version"] == "deep-story-v4"
    assert brief["deep_story"]["subject_profile"]["location"]["value"] == ("San Francisco Bay Area")
    assert brief["deep_story"]["subject_profile"]["occupation"]["value"] == (
        "Founder at Example Labs"
    )
    assert brief["deep_story"]["subject_profile"]["dislikes"] == []
    assert brief["deep_story"]["subject_profile"]["education"] == {
        "value": None,
        "confidence": None,
        "basis": "unknown",
        "explanation": "No reliable public education record was collected.",
        "source_ids": [],
    }
    assert brief["deep_story"]["subject_profile"]["career_timeline"][0]["currentness"] == "unclear"
    assert len(brief["deep_story"]["subject_profile"]["career_timeline"]) == 1
    assert set(brief["deep_story"]["subject_profile"]) == {
        "identity",
        "location",
        "occupation",
        "education",
        "interests",
        "likes",
        "dislikes",
        "unknowns",
        "career_timeline",
    }
    assert brief["deep_story"]["identity_facts"][0]["value"] == "Alice Example"
    assert brief["deep_story"]["account_insights"][0]["account_id"] == professional_node_id
    assert brief["deep_story"]["curated_claims"][0]["value"] == ("Founder at Example Labs")
    assert brief["deep_story"]["curated_claims"][0]["confidence"] == "medium_high"
    assert brief["deep_story"]["channel_coverage"][0]["channel"] == "LinkedIn"
    assert brief["narrative_sections"][0]["highlights"][0]["source_ids"] == cited
    assert brief["synthesis"]["prompt_version"] == "grounded-footprint-v4"
    assert brief["synthesis"]["provider"] == "openrouter"
    FootprintBriefResponse.model_validate(brief)


def test_deep_without_a_synthesis_run_is_ready_partial():
    graph = _new_graph(search_mode="deep")
    _add_exact_root_profile(
        graph,
        platform="Instagram",
        display_name="Alice Example",
        location="San Francisco Bay Area",
        ordinal=1,
    )

    brief, _snapshot = _finalize(graph)

    assert brief["synthesis"]["status"] == "fallback"
    assert brief["synthesis"]["fallback_reason"] == "grounded_synthesis_not_run"
    with graph.factory() as session:
        job = session.get(SearchJob, graph.job_id)
        attempt = session.get(JobAttempt, graph.attempt_id)
        assert job is not None and job.status == "ready_partial"
        assert attempt is not None and attempt.status == "ready_partial"


def test_deep_story_allows_qualified_identity_and_downgrades_overclaim():
    source_id = new_id()
    person_decision = _PersonDecision(
        report_type="account_centric",
        overall_identity_status="unverified",
        full_name=None,
        supporting_source_ids=(),
        reason=None,
    )
    output: dict[str, object] = {
        "schema_version": "grounded-digital-footprint-v2",
        "report_synthesis": {
            "report_type": "account_centric",
            "one_sentence_conclusion": (
                "The evidence supports an account-level story, not a resolved person."
            ),
            "identity_status": "possible",
            "overall_confidence": "medium",
            "likely_public_identity": None,
            "broad_location": None,
            "major_boundary": "No direct cross-platform identity link was collected.",
            "source_ids": [source_id],
        },
        "summary": "One public account exposes a bounded set of self-described facts.",
        "summary_source_ids": [source_id],
        "identity_facts": [],
        "account_assessments": [],
        "claims": [
            {
                "claim_id": "public-identity",
                "predicate": "person.public_identity",
                "label": "Public identity",
                "value": "Alice Example",
                "confidence": "medium",
                "status": "possible",
                "source_ids": [source_id],
                "contradicting_source_ids": [],
                "qualification": "The person-level association remains unresolved.",
                "supporting_evidence": [],
                "limiting_evidence": [],
            }
        ],
        "excluded_candidates": [],
        "channel_coverage": [],
        "next_verification_steps": [],
    }

    assert (
        _validated_deep_story(
            output,
            allowed_source_ids={source_id},
            person_decision=person_decision,
            assessments=[],
        )
        is not None
    )

    report_synthesis = output["report_synthesis"]
    assert isinstance(report_synthesis, dict)
    report_synthesis["overall_confidence"] = "high"
    normalized = _validated_deep_story(
        output,
        allowed_source_ids={source_id},
        person_decision=person_decision,
        assessments=[],
    )
    assert normalized is not None
    assert normalized["overall_confidence"] == "medium"
    assert "person-level association unverified" in normalized["major_boundary"]

    report_synthesis["overall_confidence"] = "medium"
    report_synthesis["report_type"] = "person_centric"
    report_synthesis["likely_public_identity"] = "Alice Example"
    assert (
        _validated_deep_story(
            output,
            allowed_source_ids={source_id},
            person_decision=person_decision,
            assessments=[],
        )
        is not None
    )

    report_synthesis["report_type"] = "account_centric"
    report_synthesis["likely_public_identity"] = None
    claims = output["claims"]
    assert isinstance(claims, list)
    claim = claims[0]
    assert isinstance(claim, dict)
    claim["status"] = "confirmed"
    downgraded = _validated_deep_story(
        output,
        allowed_source_ids={source_id},
        person_decision=person_decision,
        assessments=[],
    )
    assert downgraded is not None
    assert downgraded["curated_claims"][0]["status"] == "possible"
    assert downgraded["curated_claims"][0]["confidence"] == "medium"


def test_deep_report_rejects_persisted_narrative_with_unknown_source():
    graph = _new_graph(search_mode="deep")
    root_node_id = _add_exact_root_profile(
        graph,
        platform="Instagram",
        display_name="Alice Example",
        location="San Francisco Bay Area",
        ordinal=1,
    )
    _, professional_source_id = _add_professional_result(
        graph,
        provider_id=GITHUB_PROFESSIONAL_PROVIDER_ID,
        full_name="Alice Example",
        source_node_id=root_node_id,
        ordinal=1,
        platform="GitHub",
        profile_url="https://github.com/aliceexample",
        handle="aliceexample",
        display_name="Alice Example",
        location="San Francisco",
        query_location="San Francisco Bay Area",
    )
    _add_grounded_synthesis_result(
        graph,
        source_id=professional_source_id,
        cited_source_id="unknown-source",
    )

    brief, _ = _finalize(graph)

    assert brief["narrative_sections"] == []
    assert brief["synthesis"]["mode"] == "deterministic"
    assert brief["synthesis"]["status"] == "fallback"
    assert brief["synthesis"]["fallback_reason"] == "grounded_synthesis_invalid_persisted_output"
