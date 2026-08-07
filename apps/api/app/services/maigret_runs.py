import asyncio
import unicodedata
from datetime import UTC, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.core.crypto import stable_payload_hash
from apps.api.app.models.entities import (
    AccountNode,
    DiscoveredIdentifier,
    DiscoveryEdge,
    JobAttempt,
    JobDeletionTombstone,
    MaigretCatalogSnapshot,
    MaigretScanRun,
    MaigretSiteCheck,
    ProviderAttempt,
    ProviderRun,
    SearchJob,
    new_id,
)
from apps.api.app.policy.redaction import safe_text
from apps.api.app.services.events import add_event
from workers.providers.maigret_adapter import (
    MaigretDiscoveryAdapter,
    MaigretScanCancelled,
    MaigretScanResult,
)
from workers.providers.maigret_catalog import (
    MaigretCatalogError,
    build_maigret_adapter,
)
from workers.providers.public_profile_metadata import enrich_first_party_metadata

PROVIDER_TERMINAL_STATES = {
    "success",
    "partial_success",
    "no_result",
    "timeout",
    "rate_limited",
    "captcha_blocked",
    "auth_required",
    "provider_error",
    "invalid_response",
    "skipped_configuration",
    "cancelled",
    "closed_at_cutoff",
}
JOB_TERMINAL_STATES = {
    "ready",
    "ready_partial",
    "no_candidates",
    "failed",
    "cancelled",
}


def _deadline_reached(deadline, now) -> bool:
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return deadline <= now


def _close_unleased_scan(
    session: Session,
    *,
    job: SearchJob,
    run: ProviderRun,
    scan: MaigretScanRun,
    now,
    status: str,
    error_code: str,
    settings=None,
) -> None:
    run.status = status
    run.lease_expires_at = None
    scan.status = status
    scan.finished_at = now
    scan.error_code = error_code
    finalize_discovery_if_complete(session, job=job, now=now, settings=settings)


def process_maigret_scan_run(
    session_factory: sessionmaker[Session],
    *,
    settings,
    clock,
    provider_run_id: str,
    adapter: MaigretDiscoveryAdapter | None = None,
) -> None:
    lease = _lease_scan(
        session_factory,
        settings=settings,
        clock=clock,
        provider_run_id=provider_run_id,
    )
    if not lease:
        return
    generation, acceptance_epoch, job_id, scan_config, manifest = lease

    result: MaigretScanResult | None = None
    failure_status: str | None = None
    failure_code: str | None = None
    try:
        resolved_adapter = adapter or build_maigret_adapter(
            manifest=manifest,
            site_names=list(scan_config["site_names"]),
            catalog_snapshot_id=str(scan_config["catalog_snapshot_id"]),
            timeout_seconds=int(scan_config["timeout_seconds"]),
            max_connections=int(scan_config["max_connections"]),
            maigret_id_type=str(scan_config["maigret_identifier_type"]),
        )
        result = asyncio.run(
            resolved_adapter.scan(
                str(scan_config["identifier_value"]),
                product_identifier_type=str(scan_config["product_identifier_type"]),
            )
        )
        result = enrich_first_party_metadata(result)
    except MaigretScanCancelled as exc:
        result = exc.partial_result
    except MaigretCatalogError:
        failure_status = "provider_error"
        failure_code = "maigret_catalog_invalid"
    except (TypeError, ValueError):
        failure_status = "provider_error"
        failure_code = "maigret_adapter_invalid"
    except Exception:
        failure_status = "provider_error"
        failure_code = "maigret_unexpected_failure"

    with session_factory() as session, session.begin():
        run = session.scalar(
            select(ProviderRun).where(ProviderRun.id == provider_run_id).with_for_update()
        )
        job = session.scalar(select(SearchJob).where(SearchJob.id == job_id).with_for_update())
        scan = session.get(MaigretScanRun, provider_run_id)
        attempt = session.scalar(
            select(ProviderAttempt).where(
                ProviderAttempt.provider_run_id == provider_run_id,
                ProviderAttempt.generation == generation,
            )
        )
        stale = bool(
            not run
            or not job
            or not scan
            or session.get(JobDeletionTombstone, job_id)
            or run.status != "running"
            or run.lease_generation != generation
            or run.acceptance_epoch != acceptance_epoch
            or job.acceptance_epoch != acceptance_epoch
        )
        if stale:
            if attempt:
                attempt.finished_at = clock.now()
                attempt.status = "completed_after_fence"
                attempt.completion_disposition = "late_payload_discarded"
            return

        now = clock.now()
        if result is None:
            run.status = failure_status or "provider_error"
            run.lease_expires_at = None
            scan.status = failure_status or "provider_error"
            scan.finished_at = now
            scan.error_code = failure_code
            if attempt:
                attempt.finished_at = now
                attempt.status = run.status
                attempt.completion_disposition = "in_budget"
                attempt.error_code = failure_code
        else:
            _persist_scan_result(
                session,
                job=job,
                run=run,
                scan=scan,
                result=result,
                observed_at=now,
            )
            run.status = result.status
            run.result_count = len(result.account_candidates)
            run.lease_expires_at = None
            scan.status = result.status
            scan.completed_count = result.coverage.completed
            scan.found_count = result.coverage.claimed
            scan.not_found_count = result.coverage.available
            scan.unknown_count = result.coverage.unknown
            scan.illegal_count = result.coverage.illegal
            scan.finished_at = now
            scan.error_code = None
            if attempt:
                attempt.finished_at = now
                attempt.status = result.status
                attempt.completion_disposition = (
                    "partial_preserved" if result.cancelled else "in_budget"
                )
            add_event(
                session,
                job_id=job.id,
                event_type="discovery.catalog_progress",
                message=(
                    f"Checked {result.coverage.completed} of "
                    f"{result.coverage.selected} sites in this shard."
                ),
                created_at=now,
            )

        finalize_discovery_if_complete(session, job=job, now=now, settings=settings)


def _lease_scan(
    session_factory: sessionmaker[Session],
    *,
    settings,
    clock,
    provider_run_id: str,
) -> tuple[int, int, str, dict[str, object], dict[str, object]] | None:
    with session_factory() as session, session.begin():
        run = session.scalar(
            select(ProviderRun).where(ProviderRun.id == provider_run_id).with_for_update()
        )
        scan = session.get(MaigretScanRun, provider_run_id)
        if (
            not run
            or not scan
            or run.provider_id != "maigret_discovery_v1"
            or run.status not in {"pending", "retry_scheduled"}
        ):
            return None
        job = session.scalar(select(SearchJob).where(SearchJob.id == run.job_id).with_for_update())
        if (
            not job
            or job.job_kind != "footprint_discovery"
            or job.status in JOB_TERMINAL_STATES
            or session.get(JobDeletionTombstone, run.job_id)
        ):
            run.status = "cancelled"
            scan.status = "cancelled"
            return None
        now = clock.now()
        if _deadline_reached(run.deadline_at, now):
            _close_unleased_scan(
                session,
                job=job,
                run=run,
                scan=scan,
                now=now,
                status="closed_at_cutoff",
                error_code="maigret_deadline_exceeded",
                settings=settings,
            )
            return None
        if not settings.maigret_enabled:
            _close_unleased_scan(
                session,
                job=job,
                run=run,
                scan=scan,
                now=now,
                status="cancelled",
                error_code="maigret_disabled",
                settings=settings,
            )
            return None
        snapshot = session.get(MaigretCatalogSnapshot, scan.catalog_snapshot_id)
        if not snapshot:
            _close_unleased_scan(
                session,
                job=job,
                run=run,
                scan=scan,
                now=now,
                status="provider_error",
                error_code="maigret_catalog_missing",
                settings=settings,
            )
            return None
        run.status = "running"
        run.lease_generation += 1
        run.lease_expires_at = now + timedelta(seconds=settings.maigret_run_lease_seconds)
        run.acceptance_epoch = job.acceptance_epoch
        scan.status = "running"
        scan.started_at = now
        scan.error_code = None
        session.add(
            ProviderAttempt(
                provider_run_id=run.id,
                generation=run.lease_generation,
                started_at=now,
                finished_at=None,
                status="running",
                completion_disposition=None,
                error_code=None,
            )
        )
        attempt = session.get(JobAttempt, run.attempt_id)
        if job.status == "queued":
            job.status = "discovering"
            job.exploration_status = "running"
            job.row_version += 1
            if attempt:
                attempt.status = "running"
            add_event(
                session,
                job_id=job.id,
                event_type="discovery.catalog_scan_started",
                message=f"Maigret started checking @{scan.identifier_value}.",
                created_at=now,
            )
        return (
            run.lease_generation,
            job.acceptance_epoch,
            job.id,
            {
                "site_names": list(scan.site_names),
                "catalog_snapshot_id": scan.catalog_snapshot_id,
                "timeout_seconds": scan.timeout_seconds,
                "max_connections": scan.max_connections,
                "maigret_identifier_type": scan.maigret_identifier_type,
                "product_identifier_type": scan.product_identifier_type,
                "identifier_value": scan.identifier_value,
            },
            dict(snapshot.selection_policy),
        )


def _persist_scan_result(
    session: Session,
    *,
    job: SearchJob,
    run: ProviderRun,
    scan: MaigretScanRun,
    result: MaigretScanResult,
    observed_at,
) -> None:
    for check in result.site_checks:
        extracted_fields = {item.name: item.value for item in check.extracted_fields}
        extracted_usernames = {
            item.value: item.maigret_id_type for item in check.extracted_identifiers
        }
        extracted_links = [item.url for item in check.extracted_links]
        checksum_payload = {
            "site": check.site_id,
            "status": check.maigret_status,
            "product_status": check.product_status,
            "url": check.url_user,
            "http_status": check.http_status,
            "fields": extracted_fields,
            "usernames": extracted_usernames,
            "links": extracted_links,
        }
        stored = session.scalar(
            select(MaigretSiteCheck).where(
                MaigretSiteCheck.provider_run_id == run.id,
                MaigretSiteCheck.site_key == check.site_id,
            )
        )
        if not stored:
            stored = MaigretSiteCheck(
                id=new_id(),
                job_id=job.id,
                provider_run_id=run.id,
                site_key=check.site_id,
                site_name=check.site_name,
                source_name=None,
                queried_identifier=check.queried_identifier,
                queried_identifier_type=check.maigret_id_type,
                url_main=check.url_main,
                url_user=check.url_user,
                url_probe=check.url_probe,
                raw_status=check.maigret_status,
                normalized_status=check.product_status,
                error_type=check.error_type,
                error_context=safe_text(
                    check.error_detail or check.context or "",
                    max_length=1_000,
                )
                or None,
                http_status=check.http_status,
                is_similar=check.is_similar,
                rank=check.rank,
                tags=list(check.tags),
                extracted_data=extracted_fields,
                extracted_usernames=extracted_usernames,
                extracted_links=extracted_links,
                result_checksum=stable_payload_hash(checksum_payload),
                observed_at=observed_at,
            )
            session.add(stored)
            session.flush()

        if check.product_status == "found" and check.url_user and _safe_http_url(check.url_user):
            node = session.scalar(
                select(AccountNode).where(
                    AccountNode.job_id == job.id,
                    AccountNode.canonical_url == check.url_user,
                )
            )
            if not node:
                display_name = _display_name(extracted_fields)
                node = AccountNode(
                    id=new_id(),
                    job_id=job.id,
                    platform=check.site_name,
                    canonical_handle=check.queried_identifier,
                    canonical_url=check.url_user,
                    display_name=display_name,
                    identity_confidence_tier="weak" if check.is_similar else "possible",
                    selection_state="undecided",
                    is_similar=check.is_similar,
                    profile_data={
                        "fields": extracted_fields,
                        "links": extracted_links,
                        "tags": list(check.tags),
                    },
                    first_observed_at=observed_at,
                    last_observed_at=observed_at,
                )
                session.add(node)
                session.flush()
                add_event(
                    session,
                    job_id=job.id,
                    event_type="candidate.discovered",
                    message=(
                        f"Found a possible @{job.seed_identifier} account on {check.site_name}."
                    ),
                    created_at=observed_at,
                )
            else:
                node.last_observed_at = observed_at
            existing_edge = session.scalar(
                select(DiscoveryEdge.id).where(
                    DiscoveryEdge.provider_run_id == run.id,
                    DiscoveryEdge.site_check_id == stored.id,
                    DiscoveryEdge.child_account_node_id == node.id,
                )
            )
            if not existing_edge:
                session.add(
                    DiscoveryEdge(
                        id=new_id(),
                        job_id=job.id,
                        provider_run_id=run.id,
                        site_check_id=stored.id,
                        child_account_node_id=node.id,
                        parent_seed=job.normalized_seed or "",
                        discovery_method=(
                            "similar_handle_result"
                            if check.is_similar
                            else "username_catalog_probe"
                        ),
                        discovery_engine="maigret",
                        depth=0,
                        created_at=observed_at,
                    )
                )

        for identifier in check.extracted_identifiers:
            _store_discovered_identifier(
                session,
                job=job,
                site_check_id=stored.id,
                identifier_type=identifier.maigret_id_type,
                identifier_value=identifier.value,
                source_kind="ids_usernames",
                observed_at=observed_at,
            )
        for link in check.extracted_links:
            _store_discovered_identifier(
                session,
                job=job,
                site_check_id=stored.id,
                identifier_type="url",
                identifier_value=link.url,
                source_kind="ids_links",
                observed_at=observed_at,
            )


def _store_discovered_identifier(
    session: Session,
    *,
    job: SearchJob,
    site_check_id: str,
    identifier_type: str,
    identifier_value: str,
    source_kind: str,
    observed_at,
) -> None:
    normalized_type = identifier_type.strip().casefold().replace("-", "_")
    normalized = _normalize_discovered_identifier(identifier_value, normalized_type)
    if not normalized_type or not normalized:
        return
    root_type = (job.seed_identifier_type or "").strip().casefold().replace("-", "_")
    root_value = _normalize_discovered_identifier(job.seed_identifier or "", root_type)
    username_types = {"handle", "username"}
    if (
        normalized
        and normalized == root_value
        and (normalized_type == root_type or {normalized_type, root_type}.issubset(username_types))
    ):
        return
    existing = session.scalar(
        select(DiscoveredIdentifier.id).where(
            DiscoveredIdentifier.job_id == job.id,
            DiscoveredIdentifier.identifier_type == normalized_type,
            DiscoveredIdentifier.normalized_value == normalized,
        )
    )
    if existing:
        return
    session.add(
        DiscoveredIdentifier(
            id=new_id(),
            job_id=job.id,
            parent_site_check_id=site_check_id,
            identifier_type=normalized_type,
            identifier_value=identifier_value,
            normalized_value=normalized,
            source_kind=source_kind,
            scheduled=False,
            created_at=observed_at,
        )
    )


def _normalize_discovered_identifier(value: str, identifier_type: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if identifier_type in {"handle", "username"} and normalized.startswith("@"):
        normalized = normalized[1:]
    return normalized.casefold()


def finalize_discovery_if_complete(
    session: Session,
    *,
    job: SearchJob,
    now,
    settings=None,
) -> bool:
    from apps.api.app.services.anchor_selection import (
        expire_anchor_checkpoint_if_needed,
    )
    from apps.api.app.services.footprint_finalization import (
        finalize_footprint_if_complete,
    )
    from apps.api.app.services.grounded_synthesis_scheduling import (
        schedule_grounded_synthesis_if_ready,
    )
    from apps.api.app.services.professional_search_scheduling import (
        schedule_professional_search_if_ready,
    )

    if (
        job.exploration_status == "awaiting_anchor"
        and not expire_anchor_checkpoint_if_needed(
            session,
            job=job,
            now=now,
        )
    ):
        return False
    if schedule_professional_search_if_ready(
        session,
        job=job,
        now=now,
        settings=settings,
    ):
        return False
    # Scheduling can create a fresh checkpoint during this call. It remains open,
    # so stop here until selection or the reserved-window cutoff advances it.
    if job.exploration_status == "awaiting_anchor":
        return False
    if schedule_grounded_synthesis_if_ready(
        session,
        job=job,
        now=now,
        settings=settings,
    ):
        return False
    return finalize_footprint_if_complete(session, job=job, now=now)


def _safe_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return bool(
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    )


def _display_name(fields: dict[str, object]) -> str | None:
    for key in ("display_name", "fullname", "full_name", "name"):
        value = fields.get(key)
        if isinstance(value, str):
            normalized = safe_text(value, max_length=200)
            if normalized:
                return normalized
    return None
