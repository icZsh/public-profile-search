from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
from threading import Event, Thread

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.core.crypto import stable_payload_hash
from apps.api.app.models.entities import (
    AccountNode,
    DiscoveryEdge,
    GroundedSynthesisResult,
    JobAttempt,
    JobDeletionTombstone,
    MaigretSiteCheck,
    ProviderAttempt,
    ProviderRun,
    ProviderRunSourceUse,
    SearchJob,
    SourceDocument,
    SourceObservation,
    new_id,
)
from apps.api.app.services.events import add_event
from apps.api.app.services.grounded_synthesis_scheduling import (
    GROUNDED_SYNTHESIS_PROMPT_VERSION,
    GROUNDED_SYNTHESIS_PROVIDER_IDS,
)
from workers.providers.grounded_synthesis import (
    DEFAULT_SYNTHESIS_MODEL,
    EvidenceAccountInput,
    EvidenceSeedInput,
    EvidenceSourceInput,
    GroundedSynthesisOutcome,
    SynthesisUsage,
    synthesize_grounded_footprint,
)

_JOB_TERMINAL_STATES = {
    "ready",
    "ready_partial",
    "no_candidates",
    "failed",
    "cancelled",
}
_RESULT_STATUSES = {
    "success",
    "no_result",
    "skipped_configuration",
    "timeout",
    "rate_limited",
    "auth_required",
    "provider_error",
    "invalid_response",
}
# Synthesis error codes are gateway-agnostic, so this set covers whichever
# gateway is configured. The output_* codes are model-output defects -- invalid
# JSON, a fabricated URL, a citation to a source that was never in the packet --
# which a fresh sample often gets right.
_RETRYABLE_SYNTHESIS_ERRORS = {
    "network_error",
    "output_account_mismatch",
    "output_contains_contact_data",
    "output_invalid_json",
    "output_schema_invalid",
    "output_unknown_account_id",
    "output_unknown_source_id",
    "output_unknown_url",
    "provider_overloaded",
    "provider_unavailable",
    "rate_limit_exceeded",
    "rate_limited",
    "request_timeout",
    "response_text_missing",
    "server",
    "timeout",
    "unavailable",
}
# A response that ran out of the output budget is retryable, but only if the
# retry gets more room -- repeating the same cap just truncates again.
# _escalated_output_limit widens the cap toward the schema ceiling.
_TRUNCATION_ERRORS = {"incomplete_max_output_tokens"}
_MAX_OUTPUT_TOKEN_CEILING = 32_000
_SOURCE_TYPE_PRIORITY = {
    "first_party_profile": 0,
    "first_party_profile_api": 0,
    "professional_profile_index": 1,
    "candidate_discovery": 2,
    "availability_endpoint": 3,
}

SynthesisRunner = Callable[..., GroundedSynthesisOutcome]


@dataclass(frozen=True)
class _SynthesisLease:
    generation: int
    acceptance_epoch: int
    job_id: str
    query_config: dict[str, object]
    seed: EvidenceSeedInput
    sources: tuple[EvidenceSourceInput, ...]
    accounts: tuple[EvidenceAccountInput, ...]
    timeout_seconds: float | None
    lease_seconds: int


class _SynthesisLeaseHeartbeat:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock,
        provider_run_id: str,
        lease: _SynthesisLease,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._provider_run_id = provider_run_id
        self._lease = lease
        self._stop = Event()
        self.ownership_lost = Event()
        self._thread = Thread(
            target=self._run,
            name=f"synthesis-lease-heartbeat-{provider_run_id[:8]}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        interval = _lease_heartbeat_interval(self._lease.lease_seconds)
        while not self._stop.wait(interval):
            try:
                renewed = _renew_synthesis_lease(
                    self._session_factory,
                    clock=self._clock,
                    provider_run_id=self._provider_run_id,
                    generation=self._lease.generation,
                    acceptance_epoch=self._lease.acceptance_epoch,
                    job_id=self._lease.job_id,
                    lease_seconds=self._lease.lease_seconds,
                )
            except Exception:
                # A transient database failure must not terminate a healthy request's
                # heartbeat loop. The next interval gets another chance to renew.
                continue
            if not renewed:
                self.ownership_lost.set()
                return


def process_grounded_synthesis_run(
    session_factory: sessionmaker[Session],
    *,
    settings,
    clock,
    provider_run_id: str,
    synthesizer: SynthesisRunner | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    lease = _lease_run(
        session_factory,
        settings=settings,
        clock=clock,
        provider_run_id=provider_run_id,
    )
    if lease is None:
        return

    runner = synthesizer or synthesize_grounded_footprint
    heartbeat = _SynthesisLeaseHeartbeat(
        session_factory,
        clock=clock,
        provider_run_id=provider_run_id,
        lease=lease,
    )
    heartbeat.start()
    try:
        outcome = _execute_synthesis(
            runner=runner,
            settings=settings,
            lease=lease,
            cancel_event=heartbeat.ownership_lost,
            transport=transport,
        )
    finally:
        heartbeat.stop()

    with session_factory() as session, session.begin():
        job = session.scalar(
            select(SearchJob).where(SearchJob.id == lease.job_id).with_for_update()
        )
        run = session.scalar(
            select(ProviderRun).where(ProviderRun.id == provider_run_id).with_for_update()
        )
        attempt = session.scalar(
            select(ProviderAttempt).where(
                ProviderAttempt.provider_run_id == provider_run_id,
                ProviderAttempt.generation == lease.generation,
            )
        )
        stale = bool(
            not run
            or not job
            or job.status in _JOB_TERMINAL_STATES
            or session.get(JobDeletionTombstone, lease.job_id)
            or run.status != "running"
            or run.lease_generation != lease.generation
            or run.acceptance_epoch != lease.acceptance_epoch
            or job.acceptance_epoch != lease.acceptance_epoch
        )
        if stale:
            if attempt and attempt.status == "running" and attempt.finished_at is None:
                attempt.finished_at = clock.now()
                attempt.status = "completed_after_fence"
                attempt.completion_disposition = "late_payload_discarded"
            return

        now = clock.now()
        status = outcome.status if outcome.status in _RESULT_STATUSES else "provider_error"
        error_code = outcome.error_code
        if status == "success" and outcome.output is None:
            status = "invalid_response"
            error_code = error_code or "grounded_synthesis_output_missing"
        output = (
            outcome.output.model_dump(mode="json")
            if status == "success" and outcome.output is not None
            else None
        )
        usage = asdict(outcome.usage) if outcome.usage is not None else None
        _upsert_result(
            session,
            run=run,
            job=job,
            status=status,
            model=outcome.model,
            prompt_version=_query_text(
                lease.query_config.get("prompt_version"),
                maximum=64,
            )
            or GROUNDED_SYNTHESIS_PROMPT_VERSION,
            input_checksum=outcome.input_checksum,
            output=output,
            usage=usage,
            error_code=error_code,
            created_at=now,
        )
        run.status = status
        run.result_count = 1 if output is not None else 0
        run.lease_expires_at = None
        if attempt:
            attempt.finished_at = now
            attempt.status = status
            attempt.completion_disposition = "in_budget"
            attempt.error_code = error_code
        add_event(
            session,
            job_id=job.id,
            event_type="discovery.synthesis_progress",
            message=_completion_message(status),
            created_at=now,
        )

        from apps.api.app.services.maigret_runs import (
            finalize_discovery_if_complete,
        )

        finalize_discovery_if_complete(
            session,
            job=job,
            now=now,
            settings=settings,
        )


def _lease_run(
    session_factory: sessionmaker[Session],
    *,
    settings,
    clock,
    provider_run_id: str,
) -> _SynthesisLease | None:
    with session_factory() as session, session.begin():
        run_reference = session.get(ProviderRun, provider_run_id)
        if run_reference is None:
            return None
        job = session.scalar(
            select(SearchJob)
            .where(SearchJob.id == run_reference.job_id)
            .with_for_update()
        )
        run = session.scalar(
            select(ProviderRun).where(ProviderRun.id == provider_run_id).with_for_update()
        )
        if (
            not run
            or run.provider_id not in GROUNDED_SYNTHESIS_PROVIDER_IDS
            or run.status not in {"pending", "retry_scheduled"}
        ):
            return None
        if (
            not job
            or run.job_id != job.id
            or job.job_kind != "footprint_discovery"
            or job.search_mode != "deep"
            or job.status in _JOB_TERMINAL_STATES
            or session.get(JobDeletionTombstone, run.job_id)
        ):
            run.status = "cancelled"
            run.lease_expires_at = None
            return None

        now = clock.now()
        query_config = dict(run.query_config or {})

        run.status = "running"
        run.lease_generation += 1
        lease_seconds = _bounded_int(
            getattr(settings, "grounded_synthesis_run_lease_seconds", 120),
            default=120,
            minimum=30,
            maximum=300,
        )
        run.lease_expires_at = now + timedelta(seconds=lease_seconds)
        run.acceptance_epoch = job.acceptance_epoch
        session.add(
            ProviderAttempt(
                id=new_id(),
                provider_run_id=run.id,
                generation=run.lease_generation,
                started_at=now,
                finished_at=None,
                status="running",
                completion_disposition=None,
                error_code=None,
            )
        )
        active_attempt = session.get(JobAttempt, run.attempt_id)
        if active_attempt and active_attempt.status == "queued":
            active_attempt.status = "running"
        if job.status == "queued":
            job.status = "discovering"
            job.row_version += 1

        seed, sources, accounts = _load_evidence_inputs(
            session,
            job=job,
        )
        return _SynthesisLease(
            generation=run.lease_generation,
            acceptance_epoch=job.acceptance_epoch,
            job_id=job.id,
            query_config=query_config,
            seed=seed,
            sources=sources,
            accounts=accounts,
            timeout_seconds=None,
            lease_seconds=lease_seconds,
        )


def _lease_heartbeat_interval(lease_seconds: int) -> float:
    # This heartbeat doubles as cooperative user-cancellation detection for the
    # potentially expensive synthesis request, so do not let a long lease make
    # Stop search take tens of seconds to reach provider I/O.
    return max(0.5, min(2.0, lease_seconds / 3.0))


def _renew_synthesis_lease(
    session_factory: sessionmaker[Session],
    *,
    clock,
    provider_run_id: str,
    generation: int,
    acceptance_epoch: int,
    job_id: str,
    lease_seconds: int,
) -> bool:
    with session_factory() as session, session.begin():
        job = session.scalar(
            select(SearchJob).where(SearchJob.id == job_id).with_for_update()
        )
        run = session.scalar(
            select(ProviderRun).where(ProviderRun.id == provider_run_id).with_for_update()
        )
        if (
            not job
            or not run
            or job.status in _JOB_TERMINAL_STATES
            or session.get(JobDeletionTombstone, job_id)
            or run.status != "running"
            or run.lease_generation != generation
            or run.acceptance_epoch != acceptance_epoch
            or job.acceptance_epoch != acceptance_epoch
        ):
            return False
        run.lease_expires_at = clock.now() + timedelta(seconds=lease_seconds)
        return True


def _load_evidence_inputs(
    session: Session,
    *,
    job: SearchJob,
) -> tuple[
    EvidenceSeedInput,
    tuple[EvidenceSourceInput, ...],
    tuple[EvidenceAccountInput, ...],
]:
    observation_by_check_id = _materialize_maigret_observations(
        session,
        job=job,
    )
    rows = session.execute(
        select(SourceObservation, SourceDocument)
        .join(
            ProviderRunSourceUse,
            ProviderRunSourceUse.id == SourceObservation.source_use_id,
        )
        .join(
            SourceDocument,
            SourceDocument.id == ProviderRunSourceUse.document_id,
        )
        .where(SourceObservation.job_id == job.id)
        .order_by(SourceObservation.id)
    ).all()
    ordered_rows = sorted(
        rows,
        key=lambda row: (
            _SOURCE_TYPE_PRIORITY.get(row[0].source_type, 9),
            row[0].id,
        ),
    )
    sources = tuple(
        EvidenceSourceInput(
            source_id=observation.id,
            source_type=observation.source_type,
            trust_class=observation.trust_class,
            publisher=document.publisher,
            title=document.title,
            canonical_url=document.canonical_url,
            excerpt=observation.excerpt,
            extracted_fields=(
                observation.extracted_fields
                if isinstance(observation.extracted_fields, dict)
                else {}
            ),
        )
        for observation, document in ordered_rows
    )

    source_ids_by_node_id: dict[str, list[str]] = {}
    edge_rows = session.execute(
        select(
            DiscoveryEdge.child_account_node_id,
            DiscoveryEdge.site_check_id,
            DiscoveryEdge.source_observation_id,
        )
        .where(DiscoveryEdge.job_id == job.id)
        .order_by(DiscoveryEdge.child_account_node_id, DiscoveryEdge.id)
    ).all()
    for node_id, site_check_id, source_observation_id in edge_rows:
        source_id = (
            str(source_observation_id)
            if source_observation_id
            else (
                observation_by_check_id.get(str(site_check_id)).id
                if site_check_id and observation_by_check_id.get(str(site_check_id)) is not None
                else None
            )
        )
        if source_id:
            source_ids_by_node_id.setdefault(str(node_id), []).append(source_id)

    nodes = session.scalars(
        select(AccountNode)
        .where(AccountNode.job_id == job.id)
        .order_by(AccountNode.platform, AccountNode.canonical_url, AccountNode.id)
    ).all()
    accounts = tuple(
        EvidenceAccountInput(
            account_id=node.id,
            platform=node.platform,
            canonical_handle=node.canonical_handle,
            canonical_url=node.canonical_url,
            display_name=node.display_name,
            source_ids=tuple(dict.fromkeys(source_ids_by_node_id.get(node.id, ()))),
        )
        for node in nodes
    )
    seed = EvidenceSeedInput(
        platform=job.seed_platform or "unspecified",
        identifier_type=job.seed_identifier_type or "handle",
        identifier=job.seed_identifier or job.normalized_seed or "unknown",
    )
    return seed, sources, accounts


def _materialize_maigret_observations(
    session: Session,
    *,
    job: SearchJob,
) -> dict[str, SourceObservation]:
    from apps.api.app.services.footprint_finalization import (
        _evidence_kind,
        _node_by_check_id,
        _upsert_check_observation,
    )

    node_by_check_id = _node_by_check_id(session, job_id=job.id)
    checks = session.scalars(
        select(MaigretSiteCheck)
        .where(MaigretSiteCheck.job_id == job.id)
        .order_by(
            MaigretSiteCheck.site_name,
            MaigretSiteCheck.site_key,
            MaigretSiteCheck.id,
        )
    ).all()
    result: dict[str, SourceObservation] = {}
    for check in checks:
        evidence_kind = _evidence_kind(check)
        if evidence_kind is None:
            continue
        observation = _upsert_check_observation(
            session,
            job=job,
            check=check,
            node=node_by_check_id.get(check.id),
            evidence_kind=evidence_kind,
        )
        if observation is not None:
            result[check.id] = observation
    return result


def _execute_synthesis(
    *,
    runner: SynthesisRunner,
    settings,
    lease: _SynthesisLease,
    cancel_event: Event | None,
    transport: httpx.AsyncBaseTransport | None,
) -> GroundedSynthesisOutcome:
    query_config = lease.query_config
    model = _query_text(query_config.get("model"), maximum=80) or DEFAULT_SYNTHESIS_MODEL
    gateway = (
        _query_text(query_config.get("gateway"), maximum=20) or "openai"
    ).casefold()
    if gateway not in {"openai", "openrouter"}:
        return _fallback_outcome(
            status="invalid_response",
            error_code="grounded_synthesis_provider_invalid",
            model=model,
            job_id=lease.job_id,
        )
    if not bool(getattr(settings, "grounded_synthesis_enabled", True)):
        return _fallback_outcome(
            status="skipped_configuration",
            error_code="grounded_synthesis_disabled",
            model=model,
            job_id=lease.job_id,
        )
    api_key = _secret_value(
        getattr(
            settings,
            "openrouter_api_key" if gateway == "openrouter" else "openai_api_key",
            None,
        )
    )
    runner_kwargs = {
        "api_key": api_key,
        "provider": gateway,
        "http_referer": (
            _query_text(
                getattr(settings, "openrouter_http_referer", None),
                maximum=500,
            )
            if gateway == "openrouter"
            else None
        ),
        "app_title": (
            _query_text(
                getattr(settings, "openrouter_app_title", None),
                maximum=120,
            )
            if gateway == "openrouter"
            else None
        ),
        "seed": lease.seed,
        "sources": lease.sources,
        "accounts": lease.accounts,
        "model": model,
        "reasoning_effort": (
            _query_text(
                query_config.get("reasoning_effort"),
                maximum=12,
            )
            or "medium"
        ),
        "max_output_tokens": _bounded_int(
            query_config.get("max_output_tokens"),
            default=32_000,
            minimum=256,
            maximum=32_000,
        ),
        "max_sources": _bounded_int(
            query_config.get("max_evidence_items"),
            default=40,
            minimum=1,
            maximum=40,
        ),
        "max_packet_chars": _bounded_int(
            query_config.get("max_evidence_characters"),
            default=60_000,
            minimum=2_000,
            maximum=100_000,
        ),
        "timeout_seconds": lease.timeout_seconds,
        "cancel_event": cancel_event,
        "safety_identifier": stable_payload_hash(
            {"job_id": lease.job_id, "purpose": "grounded_synthesis"}
        )[:64],
        "transport": transport,
    }
    max_attempts = _bounded_int(
        query_config.get("max_attempts"),
        default=3,
        minimum=1,
        maximum=5,
    )
    retry_backoff_seconds = _bounded_int(
        query_config.get("retry_backoff_seconds"),
        default=2,
        minimum=0,
        maximum=30,
    )
    total_usage: SynthesisUsage | None = None
    for attempt_index in range(max_attempts):
        if cancel_event is not None and cancel_event.is_set():
            return _fallback_outcome(
                status="provider_error",
                error_code="request_cancelled",
                model=model,
                job_id=lease.job_id,
            )
        try:
            outcome = runner(**runner_kwargs)
        except (TypeError, ValueError):
            return _fallback_outcome(
                status="invalid_response",
                error_code="grounded_synthesis_input_invalid",
                model=model,
                job_id=lease.job_id,
            )
        except Exception:
            outcome = _fallback_outcome(
                status="provider_error",
                error_code="grounded_synthesis_unexpected_failure",
                model=model,
                job_id=lease.job_id,
            )

        total_usage = _combined_usage(total_usage, outcome.usage)
        outcome = _outcome_with_usage(outcome, total_usage)
        if (
            not _retryable_synthesis_outcome(outcome)
            or attempt_index + 1 >= max_attempts
        ):
            return outcome

        if outcome.error_code in _TRUNCATION_ERRORS:
            escalated = _escalated_output_limit(
                runner_kwargs["max_output_tokens"],
                attempts_remaining=max_attempts - attempt_index - 1,
            )
            if escalated is None:
                # Already at the ceiling; another identical call would truncate
                # in the same place, so fall back to the deterministic brief.
                return outcome
            runner_kwargs["max_output_tokens"] = escalated

        delay_seconds = min(
            30,
            retry_backoff_seconds * (2**attempt_index),
        )
        retry_wait = cancel_event or Event()
        if retry_wait.wait(delay_seconds):
            return outcome

    raise AssertionError("synthesis retry loop exhausted without returning")


def _retryable_synthesis_outcome(outcome: GroundedSynthesisOutcome) -> bool:
    return (
        outcome.error_code in _RETRYABLE_SYNTHESIS_ERRORS
        or outcome.error_code in _TRUNCATION_ERRORS
    )


def _escalated_output_limit(current: int, *, attempts_remaining: int) -> int | None:
    """Widen the output budget after a truncation, in even steps to the ceiling.

    Returns None once the ceiling is already in force, since repeating the same
    budget would truncate at the same place.
    """

    if current >= _MAX_OUTPUT_TOKEN_CEILING or attempts_remaining < 1:
        return None
    step = (_MAX_OUTPUT_TOKEN_CEILING - current) // attempts_remaining
    return min(_MAX_OUTPUT_TOKEN_CEILING, current + max(step, 1))


def _combined_usage(
    total: SynthesisUsage | None,
    current: SynthesisUsage | None,
) -> SynthesisUsage | None:
    if current is None:
        return total
    if total is None:
        return current
    return SynthesisUsage(
        input_tokens=total.input_tokens + current.input_tokens,
        output_tokens=total.output_tokens + current.output_tokens,
        total_tokens=total.total_tokens + current.total_tokens,
        reasoning_tokens=_combined_optional(total.reasoning_tokens, current.reasoning_tokens),
        cached_input_tokens=_combined_optional(
            total.cached_input_tokens,
            current.cached_input_tokens,
        ),
    )


def _combined_optional(total: int | None, current: int | None) -> int | None:
    if total is None or current is None:
        return None
    return total + current


def _outcome_with_usage(
    outcome: GroundedSynthesisOutcome,
    usage: SynthesisUsage | None,
) -> GroundedSynthesisOutcome:
    if outcome.usage == usage:
        return outcome
    return GroundedSynthesisOutcome(
        status=outcome.status,
        output=outcome.output,
        usage=usage,
        error_code=outcome.error_code,
        input_checksum=outcome.input_checksum,
        response_id=outcome.response_id,
        model=outcome.model,
    )


def _fallback_outcome(
    *,
    status,
    error_code: str,
    model: str,
    job_id: str,
) -> GroundedSynthesisOutcome:
    return GroundedSynthesisOutcome(
        status=status,
        output=None,
        usage=None,
        error_code=error_code,
        input_checksum=stable_payload_hash(
            {
                "job_id": job_id,
                "model": model,
                "fallback_reason": error_code,
            }
        ),
        response_id=None,
        model=model,
    )


def _upsert_result(
    session: Session,
    *,
    run: ProviderRun,
    job: SearchJob,
    status: str,
    model: str,
    prompt_version: str,
    input_checksum: str,
    output: dict[str, object] | None,
    usage: dict[str, object] | None,
    error_code: str | None,
    created_at,
) -> None:
    result = session.get(GroundedSynthesisResult, run.id)
    if result is None:
        result = GroundedSynthesisResult(
            provider_run_id=run.id,
            job_id=job.id,
            status=status,
            model=model,
            prompt_version=prompt_version,
            input_checksum=input_checksum,
            output=output,
            usage=usage,
            error_code=error_code,
            created_at=created_at,
            expires_at=job.expires_at,
        )
        session.add(result)
        return
    result.status = status
    result.model = model
    result.prompt_version = prompt_version
    result.input_checksum = input_checksum
    result.output = output
    result.usage = usage
    result.error_code = error_code
    result.created_at = created_at
    result.expires_at = job.expires_at


def _completion_message(status: str) -> str:
    if status == "success":
        return "Source-grounded Deep narrative synthesis completed."
    if status == "no_result":
        return "No source evidence was available for narrative synthesis."
    if status == "skipped_configuration":
        return "Narrative synthesis was not configured; deterministic output will be used."
    return "Narrative synthesis did not complete; deterministic output will be used."


def _secret_value(value: object) -> str | None:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        value = getter()
    return value.strip() if isinstance(value, str) and value.strip() else None


def _query_text(value: object, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized[:maximum] if normalized else None


def _bounded_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))
