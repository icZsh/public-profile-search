import json
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.core.crypto import (
    InvalidEncryptedValue,
    UnsafePrototypeUrl,
    canonicalize_footprint_profile_url,
    decrypt_value,
    encrypt_value,
    keyed_hmac,
    stable_payload_hash,
)
from apps.api.app.core.errors import ApiError
from apps.api.app.models.entities import (
    IdempotencyRecord,
    JobAttempt,
    JobEvent,
    MaigretCatalogSnapshot,
    MaigretScanRun,
    OutboxMessage,
    ProviderRun,
    SearchJob,
    new_id,
)
from apps.api.app.services.events import add_event

ROOT = Path(__file__).resolve().parents[4]
SUPPORTED_PLATFORMS = {
    "github",
    "instagram",
    "linkedin",
    "reddit",
    "tiktok",
    "x",
    "youtube",
    "other",
}
PLATFORM_ALIASES = {
    "twitter": "x",
}
SUPPORTED_SEARCH_MODES = {"quick", "deep"}
CATALOG_PROFILE_BY_SEARCH_MODE = {
    "quick": "quick",
    "deep": "quick",
}
_SUCCESSFUL_FOOTPRINT_JOB_STATUSES = {
    "ready",
    "ready_partial",
    "no_candidates",
}
_UNSUCCESSFUL_FOOTPRINT_JOB_STATUSES = {
    "failed",
    "cancelled",
}


@dataclass(frozen=True)
class CatalogProfile:
    name: str
    site_names: tuple[str, ...]
    shard_size: int
    timeout_seconds: int
    max_connections: int


@dataclass(frozen=True)
class CatalogManifest:
    package_version: str
    upstream_revision: str
    database_checksum: str
    catalog_site_count: int
    manifest_checksum: str
    raw: dict[str, object]

    def profile(self, name: str) -> CatalogProfile:
        profiles = self.raw.get("profiles")
        if not isinstance(profiles, dict) or name not in profiles:
            raise ApiError(422, "invalid_request", "The requested scan profile is unavailable.")
        value = profiles[name]
        if not isinstance(value, dict):
            raise ApiError(503, "service_unavailable", "The catalog profile is invalid.")
        site_names = value.get("site_names")
        if (
            not isinstance(site_names, list)
            or not site_names
            or not all(isinstance(item, str) and item for item in site_names)
            or len(set(site_names)) != len(site_names)
        ):
            raise ApiError(503, "service_unavailable", "The catalog site list is invalid.")
        shard_size = int(value.get("shard_size", 0))
        timeout_seconds = int(value.get("timeout_seconds", 0))
        max_connections = int(value.get("max_connections", 0))
        if not 1 <= shard_size <= 50 or not 1 <= timeout_seconds <= 30:
            raise ApiError(503, "service_unavailable", "The catalog scan limits are invalid.")
        if not 1 <= max_connections <= shard_size:
            raise ApiError(503, "service_unavailable", "The catalog concurrency is invalid.")
        return CatalogProfile(
            name=name,
            site_names=tuple(site_names),
            shard_size=shard_size,
            timeout_seconds=timeout_seconds,
            max_connections=max_connections,
        )


def load_catalog_manifest(path_value: str) -> CatalogManifest:
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    try:
        raw_bytes = path.read_bytes()
        raw = json.loads(raw_bytes)
    except (OSError, ValueError) as exc:
        raise ApiError(503, "service_unavailable", "The discovery catalog is unavailable.") from exc
    if not isinstance(raw, dict):
        raise ApiError(503, "service_unavailable", "The discovery catalog is invalid.")
    required_strings = {
        "package_version": raw.get("package_version"),
        "upstream_revision": raw.get("upstream_revision"),
        "database_sha256": raw.get("database_sha256"),
    }
    if not all(isinstance(value, str) and value for value in required_strings.values()):
        raise ApiError(503, "service_unavailable", "The discovery catalog is invalid.")
    catalog_site_count = raw.get("catalog_site_count")
    if not isinstance(catalog_site_count, int) or isinstance(catalog_site_count, bool):
        raise ApiError(503, "service_unavailable", "The discovery catalog is invalid.")
    return CatalogManifest(
        package_version=str(required_strings["package_version"]),
        upstream_revision=str(required_strings["upstream_revision"]),
        database_checksum=str(required_strings["database_sha256"]),
        catalog_site_count=catalog_site_count,
        manifest_checksum=stable_payload_hash(raw),
        raw=raw,
        )


@dataclass(frozen=True)
class NormalizedFootprintSeed:
    kind: str
    platform: str | None
    identifier: str
    normalized_seed: str
    canonical_profile_url: str | None = None
    canonicalization_version: str = "seed-identifier-v1"


def _normalize_handle(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    if (
        not normalized
        or len(normalized) > 64
        or any(character.isspace() for character in normalized)
        or any(unicodedata.category(character).startswith("C") for character in normalized)
        or any(character in normalized for character in "/\\?#:")
    ):
        raise ApiError(422, "invalid_request", "Enter a valid account handle, not a URL.")
    return normalized


def normalize_seed_details(seed: dict[str, object]) -> NormalizedFootprintSeed:
    kind = str(seed.get("kind", ""))
    if kind not in {"platform_identifier", "bare_handle", "profile_url"}:
        raise ApiError(
            422,
            "invalid_request",
            "Use a platform identifier, bare handle, or supported profile URL.",
        )
    if kind == "profile_url":
        try:
            target = canonicalize_footprint_profile_url(str(seed.get("profile_url", "")))
        except UnsafePrototypeUrl as exc:
            raise ApiError(
                422,
                "invalid_request",
                "Enter a direct HTTPS profile URL from a supported platform.",
            ) from exc
        supplied_platform = seed.get("platform")
        if supplied_platform is not None:
            normalized_platform = PLATFORM_ALIASES.get(
                str(supplied_platform).strip().casefold(),
                str(supplied_platform).strip().casefold(),
            )
            if normalized_platform != target.platform:
                raise ApiError(
                    422,
                    "invalid_request",
                    "The supplied platform does not match the profile URL.",
                )
        supplied_identifier_type = seed.get("identifier_type")
        if supplied_identifier_type not in {None, "handle"}:
            raise ApiError(422, "invalid_request", "The profile URL must identify a handle.")
        supplied_identifier = seed.get("identifier")
        if supplied_identifier is not None:
            normalized_identifier = _normalize_handle(supplied_identifier)
            if normalized_identifier.casefold() != target.handle.casefold():
                raise ApiError(
                    422,
                    "invalid_request",
                    "The supplied handle does not match the profile URL.",
                )
        return NormalizedFootprintSeed(
            kind=kind,
            platform=target.platform,
            identifier=target.handle,
            normalized_seed=f"{target.platform}:handle:{target.handle.casefold()}",
            canonical_profile_url=target.canonical_url,
            canonicalization_version=target.canonicalization_version,
        )

    identifier_type = str(seed.get("identifier_type", "handle"))
    if identifier_type != "handle":
        raise ApiError(422, "invalid_request", "The first discovery slice supports handles.")
    platform: str | None = None
    if kind == "platform_identifier":
        platform = PLATFORM_ALIASES.get(
            str(seed.get("platform", "")).strip().casefold(),
            str(seed.get("platform", "")).strip().casefold(),
        )
        if platform not in SUPPORTED_PLATFORMS:
            raise ApiError(422, "unsupported_provider", "Choose a supported seed platform.")
    value = _normalize_handle(seed.get("identifier", ""))
    normalized_seed = f"{platform or '*'}:handle:{value.casefold()}"
    return NormalizedFootprintSeed(
        kind=kind,
        platform=platform,
        identifier=value,
        normalized_seed=normalized_seed,
    )


def normalize_seed(seed: dict[str, object]) -> tuple[str, str | None, str, str]:
    normalized = normalize_seed_details(seed)
    return (
        normalized.kind,
        normalized.platform,
        normalized.identifier,
        normalized.normalized_seed,
    )


def _is_manifest_checksum_unique_violation(error: IntegrityError) -> bool:
    original = error.orig
    message = str(original).casefold()
    error_args = getattr(original, "args", ())
    error_code = error_args[0] if error_args else None
    is_unique_violation = (
        getattr(original, "sqlstate", None) == "23505"
        or getattr(original, "sqlite_errorname", None) == "SQLITE_CONSTRAINT_UNIQUE"
        or error_code == 1062
        or "unique constraint" in message
        or "duplicate entry" in message
    )
    return is_unique_violation and "manifest_checksum" in message


def _ensure_catalog_snapshot(
    session: Session,
    *,
    manifest: CatalogManifest,
    now,
) -> MaigretCatalogSnapshot:
    values = {
        "id": new_id(),
        "package_version": manifest.package_version,
        "upstream_revision": manifest.upstream_revision,
        "database_checksum": manifest.database_checksum,
        "manifest_checksum": manifest.manifest_checksum,
        "catalog_site_count": manifest.catalog_site_count,
        "selection_policy": manifest.raw,
        "created_at": now,
    }
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        statement = (
            postgresql_insert(MaigretCatalogSnapshot)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[MaigretCatalogSnapshot.manifest_checksum],
            )
        )
    elif dialect_name == "sqlite":
        statement = (
            sqlite_insert(MaigretCatalogSnapshot)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[MaigretCatalogSnapshot.manifest_checksum],
            )
        )
    else:
        snapshot = MaigretCatalogSnapshot(**values)
        try:
            with session.begin_nested():
                session.add(snapshot)
                session.flush()
        except IntegrityError as exc:
            if not _is_manifest_checksum_unique_violation(exc):
                raise
            winner = session.scalar(
                select(MaigretCatalogSnapshot).where(
                    MaigretCatalogSnapshot.manifest_checksum
                    == manifest.manifest_checksum
                )
            )
            if winner is None:
                raise
            return winner
        return snapshot

    with session.begin_nested():
        session.execute(statement)
    snapshot = session.scalar(
        select(MaigretCatalogSnapshot).where(
            MaigretCatalogSnapshot.manifest_checksum == manifest.manifest_checksum
        )
    )
    if snapshot is None:
        raise RuntimeError("Catalog snapshot upsert did not produce a row.")
    return snapshot


def _chunks(values: tuple[str, ...], size: int) -> list[tuple[str, ...]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _prioritize_sites_for_seed(
    site_names: tuple[str, ...],
    *,
    seed_platform: str | None,
) -> tuple[str, ...]:
    if seed_platform != "instagram":
        return site_names
    priority = ("Instagram", "Threads", "Clubhouse")
    selected = set(site_names)
    prioritized = tuple(site for site in priority if site in selected)
    return prioritized + tuple(site for site in site_names if site not in priority)


def _idempotent_footprint_job(
    session: Session,
    *,
    user_id: str,
    idempotency_key: str,
    payload_hash: str,
) -> SearchJob | None:
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    if existing is None:
        return None
    if existing.payload_hash != payload_hash:
        raise ApiError(
            409,
            "idempotency_conflict",
            "This idempotency key was already used for a different request.",
        )
    job = session.get(SearchJob, existing.job_id)
    if not job or job.job_kind != "footprint_discovery":
        raise ApiError(409, "idempotency_conflict", "The prior job is unavailable.")
    return job


def create_footprint_job(
    session: Session,
    *,
    settings,
    clock,
    user_id: str,
    idempotency_key: str,
    request_payload: dict[str, object],
) -> tuple[SearchJob, bool]:
    if not settings.prototype_jobs_enabled:
        raise ApiError(503, "prototype_disabled", "New prototype jobs are temporarily disabled.")
    if not settings.maigret_enabled:
        raise ApiError(503, "provider_disabled", "Profile discovery is temporarily unavailable.")
    if not 8 <= len(idempotency_key) <= 128:
        raise ApiError(422, "invalid_request", "The request could not be accepted.")

    seed = request_payload.get("seed")
    if not isinstance(seed, dict):
        raise ApiError(422, "invalid_request", "A seed identifier is required.")
    normalized = normalize_seed_details(seed)
    seed_kind = normalized.kind
    seed_platform = normalized.platform
    identifier = normalized.identifier
    normalized_seed = normalized.normalized_seed
    search_mode = str(request_payload.get("search_mode", "quick"))
    if search_mode not in SUPPORTED_SEARCH_MODES:
        raise ApiError(422, "invalid_request", "The requested search mode is unavailable.")
    locale = str(request_payload.get("locale", "en-US"))
    if locale not in {"en-US", "zh-CN"}:
        raise ApiError(422, "invalid_request", "The requested locale is unavailable.")

    manifest = load_catalog_manifest(settings.maigret_catalog_manifest)
    profile = manifest.profile(CATALOG_PROFILE_BY_SEARCH_MODE[search_mode])
    selected_sites = _prioritize_sites_for_seed(
        profile.site_names,
        seed_platform=seed_platform,
    )
    shards = _chunks(selected_sites, profile.shard_size)
    if len(shards) > settings.maigret_max_shards_per_job:
        raise ApiError(
            503,
            "service_unavailable",
            "The discovery catalog exceeds its shard budget.",
        )

    normalized_seed_payload: dict[str, object] = {
        "kind": seed_kind,
        "platform": seed_platform,
        "identifier_type": "handle",
        "identifier": identifier,
    }
    if normalized.canonical_profile_url:
        normalized_seed_payload["profile_url"] = normalized.canonical_profile_url
    normalized_payload = {
        "seed": normalized_seed_payload,
        "search_mode": search_mode,
        "locale": locale,
        "manifest_checksum": manifest.manifest_checksum,
    }
    payload_hash = stable_payload_hash(normalized_payload)
    existing_job = _idempotent_footprint_job(
        session,
        user_id=user_id,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    if existing_job is not None:
        return existing_job, False

    now = clock.now()
    expires_at = now + timedelta(days=settings.retention_days)
    deadline_at = now + timedelta(minutes=5)
    snapshot = _ensure_catalog_snapshot(session, manifest=manifest, now=now)
    job = SearchJob(
        id=new_id(),
        user_id=user_id,
        retry_of_job_id=None,
        normalized_identifier_hmac=keyed_hmac(
            normalized_seed,
            settings.prototype_hmac_key,
        ),
        canonical_input_url_ciphertext=(
            encrypt_value(
                normalized.canonical_profile_url,
                settings.profile_url_encryption_key,
            )
            if normalized.canonical_profile_url
            else None
        ),
        input_provider_id="maigret_discovery_v1",
        canonicalization_version=normalized.canonicalization_version,
        eligibility_verification_id=None,
        job_kind="footprint_discovery",
        seed_kind=seed_kind,
        seed_platform=seed_platform,
        seed_identifier_type="handle",
        seed_identifier=identifier,
        normalized_seed=normalized_seed,
        search_mode=search_mode,
        catalog_profile=profile.name,
        catalog_snapshot_id=snapshot.id,
        exploration_status="idle",
        purpose="digital_footprint",
        fixture_key=None,
        status="queued",
        active_attempt_id=new_id(),
        accepted_at=now,
        collection_cutoff_at=deadline_at,
        fallback_at=deadline_at,
        deadline_at=deadline_at,
        completion_policy_id="candidate-map-v1",
        policy_version=settings.policy_version,
        locale=locale,
        acceptance_epoch=1,
        row_version=1,
        cancelled_at=None,
        expires_at=expires_at,
    )
    session.add(job)
    session.flush()
    attempt = JobAttempt(
        id=job.active_attempt_id,
        job_id=job.id,
        attempt_no=1,
        status="queued",
        collection_snapshot_id=None,
        current_analysis_revision_id=None,
        current_report_revision_id=None,
        started_at=now,
        finished_at=None,
        terminal_reason=None,
    )
    session.add(attempt)
    session.flush()

    for shard_index, site_names in enumerate(shards):
        run = ProviderRun(
            id=new_id(),
            job_id=job.id,
            attempt_id=attempt.id,
            logical_run_id=f"maigret:root:{shard_index:03d}",
            provider_id="maigret_discovery_v1",
            parent_run_id=None,
            depth=0,
            query_config={
                "shard_index": shard_index,
                "site_names": list(site_names),
                "catalog_profile": profile.name,
            },
            status="pending",
            required_for_finalization=True,
            lease_generation=0,
            lease_expires_at=None,
            acceptance_epoch=1,
            result_count=0,
            deadline_at=deadline_at,
            expires_at=expires_at,
        )
        session.add(run)
        session.flush()
        selected_manifest_checksum = stable_payload_hash(
            {
                "catalog": manifest.manifest_checksum,
                "identifier_type": "username",
                "sites": list(site_names),
            }
        )
        session.add(
            MaigretScanRun(
                provider_run_id=run.id,
                catalog_snapshot_id=snapshot.id,
                product_identifier_type="handle",
                maigret_identifier_type="username",
                identifier_value=identifier,
                site_names=list(site_names),
                selected_site_manifest_checksum=selected_manifest_checksum,
                scan_profile=profile.name,
                status="pending",
                selected_count=len(site_names),
                completed_count=0,
                found_count=0,
                not_found_count=0,
                unknown_count=0,
                illegal_count=0,
                timeout_seconds=profile.timeout_seconds,
                max_connections=profile.max_connections,
                started_at=None,
                finished_at=None,
                error_code=None,
            )
        )
        session.add(
            OutboxMessage(
                topic="maigret_scan_run",
                dedupe_key=f"maigret-scan:{run.id}:generation:1",
                payload={
                    "provider_run_id": run.id,
                    "scan_run_id": run.id,
                },
                created_at=now,
                dispatched_at=None,
                attempts=0,
            )
        )

    session.add(
        IdempotencyRecord(
            user_id=user_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            job_id=job.id,
            created_at=now,
            expires_at=expires_at,
        )
    )
    add_event(
        session,
        job_id=job.id,
        event_type="job.accepted",
        message=f"Discovery accepted for @{identifier}.",
        created_at=now,
    )
    try:
        # Force the unique idempotency claim inside this service so a concurrent
        # winner can be replayed instead of surfacing a commit-time integrity error.
        session.flush()
    except IntegrityError:
        session.rollback()
        replay = _idempotent_footprint_job(
            session,
            user_id=user_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
        )
        if replay is None:
            raise
        return replay, False
    return job, True


def owner_footprint_job(
    session: Session,
    *,
    job_id: str,
    user_id: str,
    for_update: bool = False,
) -> SearchJob:
    statement = select(SearchJob).where(
        SearchJob.id == job_id,
        SearchJob.user_id == user_id,
        SearchJob.job_kind == "footprint_discovery",
    )
    if for_update:
        statement = statement.with_for_update()
    job = session.scalar(statement)
    if not job:
        raise ApiError(404, "job_not_found", "The discovery job was not found.")
    return job


def _deep_progress(
    session: Session,
    *,
    job: SearchJob,
) -> dict[str, object] | None:
    if job.search_mode != "deep":
        return None

    events = session.execute(
        select(
            JobEvent.event_type,
            JobEvent.created_at,
            JobEvent.sequence,
            JobEvent.terminal,
        )
        .where(JobEvent.job_id == job.id)
        .order_by(JobEvent.sequence)
    ).all()

    def latest_event(*event_types: str):
        matching = [event for event in events if event.event_type in event_types]
        return matching[-1] if matching else None

    def first_event(*event_types: str):
        return next(
            (event for event in events if event.event_type in event_types),
            None,
        )

    latest = events[-1] if events else None
    terminal_finished_at = None
    if job.status in (
        _SUCCESSFUL_FOOTPRINT_JOB_STATUSES | _UNSUCCESSFUL_FOOTPRINT_JOB_STATUSES
    ):
        terminal_event = next(
            (
                event
                for event in reversed(events)
                if event.terminal or event.event_type == "job.ready"
            ),
            None,
        )
        terminal_finished_at = terminal_event.created_at if terminal_event else None
        if terminal_finished_at is None and job.status == "cancelled":
            terminal_finished_at = job.cancelled_at
        if terminal_finished_at is None:
            attempt = session.get(JobAttempt, job.active_attempt_id)
            terminal_finished_at = attempt.finished_at if attempt else None
        if terminal_finished_at is None and latest is not None:
            terminal_finished_at = latest.created_at
        terminal_finished_at = terminal_finished_at or job.accepted_at

    if job.status in _SUCCESSFUL_FOOTPRINT_JOB_STATUSES:
        return {
            "current_phase": "complete",
            "phase_started_at": terminal_finished_at,
            "finished_at": terminal_finished_at,
        }

    finished_at = (
        terminal_finished_at
        if job.status in _UNSUCCESSFUL_FOOTPRINT_JOB_STATUSES
        else None
    )

    finalization_event = latest_event("finalization_started")
    if job.status == "finalizing" or finalization_event is not None:
        return {
            "current_phase": "finalizing",
            "phase_started_at": (
                finalization_event.created_at if finalization_event else job.accepted_at
            ),
            "finished_at": finished_at,
        }

    synthesis_started = latest_event("discovery.synthesis_started")
    synthesis_progress = first_event("discovery.synthesis_progress")
    synthesis_event = synthesis_started or synthesis_progress
    if synthesis_event is not None:
        return {
            "current_phase": "report_generation",
            "phase_started_at": synthesis_event.created_at,
            "finished_at": finished_at,
        }

    professional_started = latest_event("discovery.professional_search_started")
    professional_progress = first_event("discovery.professional_search_progress")
    anchor_required = latest_event("discovery.anchor_required")
    anchor_resolved = latest_event(
        "discovery.anchor_selected",
        "discovery.anchor_window_expired",
    )
    latest_professional_sequence = max(
        (
            event.sequence
            for event in (professional_started, professional_progress)
            if event is not None
        ),
        default=0,
    )
    anchor_is_unresolved = bool(
        (job.exploration_status == "awaiting_anchor" or finished_at is not None)
        and anchor_required is not None
        and anchor_required.sequence
        > max(
            anchor_resolved.sequence if anchor_resolved is not None else 0,
            latest_professional_sequence,
        )
    )
    if anchor_is_unresolved:
        return {
            "current_phase": "awaiting_anchor",
            "phase_started_at": anchor_required.created_at,
            "finished_at": finished_at,
        }

    professional_event = professional_started or anchor_resolved or professional_progress
    if professional_event is not None:
        return {
            "current_phase": "professional_enrichment",
            "phase_started_at": professional_event.created_at,
            "finished_at": finished_at,
        }
    if job.exploration_status == "awaiting_anchor":
        return {
            "current_phase": "awaiting_anchor",
            "phase_started_at": (
                anchor_required.created_at if anchor_required else job.accepted_at
            ),
            "finished_at": finished_at,
        }

    # A Deep job can contain several catalog shards. Keep the phase clock anchored
    # to the first shard instead of resetting it whenever another shard starts.
    catalog_started = first_event("discovery.catalog_scan_started")
    catalog_progress = first_event("discovery.catalog_progress")
    catalog_event = catalog_started or catalog_progress
    if (
        catalog_event is not None
        or job.status == "discovering"
        or job.exploration_status == "running"
    ):
        return {
            "current_phase": "account_scan",
            "phase_started_at": (
                catalog_event.created_at if catalog_event else job.accepted_at
            ),
            "finished_at": finished_at,
        }
    return {
        "current_phase": "queued",
        "phase_started_at": job.accepted_at,
        "finished_at": finished_at,
    }


def footprint_job_response(
    session: Session,
    job: SearchJob,
    *,
    settings,
) -> dict[str, object]:
    coverage = session.execute(
        select(
            func.coalesce(func.sum(MaigretScanRun.selected_count), 0),
            func.coalesce(func.sum(MaigretScanRun.completed_count), 0),
            func.coalesce(func.sum(MaigretScanRun.found_count), 0),
            func.coalesce(func.sum(MaigretScanRun.not_found_count), 0),
            func.coalesce(func.sum(MaigretScanRun.unknown_count), 0),
            func.coalesce(func.sum(MaigretScanRun.illegal_count), 0),
        )
        .join(ProviderRun, ProviderRun.id == MaigretScanRun.provider_run_id)
        .where(ProviderRun.job_id == job.id)
    ).one()
    snapshot = (
        session.get(MaigretCatalogSnapshot, job.catalog_snapshot_id)
        if job.catalog_snapshot_id
        else None
    )
    seed: dict[str, object] = {
        "kind": job.seed_kind,
        "platform": job.seed_platform,
        "identifier_type": job.seed_identifier_type,
        "identifier": job.seed_identifier,
    }
    if job.seed_kind == "profile_url":
        if not job.canonical_input_url_ciphertext:
            raise ApiError(503, "service_unavailable", "The stored profile seed is unavailable.")
        try:
            seed["profile_url"] = decrypt_value(
                job.canonical_input_url_ciphertext,
                settings.profile_url_encryption_key,
            )
        except InvalidEncryptedValue as exc:
            raise ApiError(
                503,
                "service_unavailable",
                "The stored profile seed is unavailable.",
            ) from exc
    return {
        "job_id": job.id,
        "status": job.status,
        "exploration_status": job.exploration_status or "idle",
        "deep_progress": _deep_progress(session, job=job),
        "seed": seed,
        "search_mode": job.search_mode,
        "coverage": {
            "selected": int(coverage[0]),
            "completed": int(coverage[1]),
            "claimed": int(coverage[2]),
            "available": int(coverage[3]),
            "unknown": int(coverage[4]),
            "illegal": int(coverage[5]),
        },
        "catalog": {
            "engine": "maigret",
            "package_version": snapshot.package_version if snapshot else None,
            "database_checksum": snapshot.database_checksum if snapshot else None,
            "profile": job.catalog_profile,
        },
        "events_url": f"/v1/footprint-jobs/{job.id}/events",
        "candidates_url": f"/v1/footprint-jobs/{job.id}/candidates",
        "accepted_at": job.accepted_at,
        "deadline_at": job.deadline_at,
    }
