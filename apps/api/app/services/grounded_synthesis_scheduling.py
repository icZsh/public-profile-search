from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.crypto import stable_payload_hash
from apps.api.app.models.entities import (
    GroundedSynthesisResult,
    OutboxMessage,
    ProviderRun,
    SearchJob,
    new_id,
)
from apps.api.app.services.deep_models import (
    DEFAULT_DEEP_SYNTHESIS_MODEL,
    is_curated_deep_synthesis_model,
)
from apps.api.app.services.events import add_event

GROUNDED_SYNTHESIS_PROVIDER_ID = "grounded_synthesis_v2"
LEGACY_OPENAI_GROUNDED_SYNTHESIS_PROVIDER_ID = "openai_grounded_synthesis_v1"
GROUNDED_SYNTHESIS_PROVIDER_IDS = frozenset(
    {
        GROUNDED_SYNTHESIS_PROVIDER_ID,
        LEGACY_OPENAI_GROUNDED_SYNTHESIS_PROVIDER_ID,
    }
)
GROUNDED_SYNTHESIS_PROMPT_VERSION = "grounded-footprint-v4"
GROUNDED_SYNTHESIS_TERMINAL_STATES = {
    "success",
    "partial_success",
    "no_result",
    "timeout",
    "rate_limited",
    "auth_required",
    "provider_error",
    "invalid_response",
    "cancelled",
    "closed_at_cutoff",
    "skipped_configuration",
}
_RETRIEVAL_TERMINAL_STATES = {
    *GROUNDED_SYNTHESIS_TERMINAL_STATES,
    "captcha_blocked",
}
_TERMINAL_JOB_STATES = {
    "ready",
    "ready_partial",
    "no_candidates",
    "failed",
    "cancelled",
}


def schedule_grounded_synthesis_if_ready(
    session: Session,
    *,
    job: SearchJob,
    now,
    settings: object | None,
) -> bool:
    """Schedule the optional Deep-mode narrative pass after retrieval is complete.

    Missing configuration is recorded as a terminal provider result so Deep jobs
    immediately continue to the deterministic finalizer instead of hanging.
    """

    if (
        job.job_kind != "footprint_discovery"
        or job.search_mode != "deep"
        or job.status in _TERMINAL_JOB_STATES
    ):
        return False
    session.flush()
    runs = session.scalars(
        select(ProviderRun)
        .where(ProviderRun.job_id == job.id)
        .order_by(ProviderRun.logical_run_id)
        .with_for_update()
    ).all()
    if any(run.provider_id in GROUNDED_SYNTHESIS_PROVIDER_IDS for run in runs):
        return False
    if not runs or any(run.status not in _RETRIEVAL_TERMINAL_STATES for run in runs):
        return False

    selected_model = job.synthesis_model
    if selected_model is not None:
        gateway = "openrouter"
        model = (
            selected_model
            if is_curated_deep_synthesis_model(selected_model)
            else DEFAULT_DEEP_SYNTHESIS_MODEL
        )
        key_present = _secret_present(getattr(settings, "openrouter_api_key", None))
    else:
        gateway = _synthesis_gateway(
            getattr(settings, "grounded_synthesis_provider", "openai")
        )
    if selected_model is None and gateway == "openrouter":
        model = _bounded_text(
            getattr(
                settings,
                "openrouter_synthesis_model",
                "~deepseek/deepseek-v4-flash-latest",
            ),
            default="~deepseek/deepseek-v4-flash-latest",
            maximum=80,
        )
        key_present = _secret_present(
            getattr(settings, "openrouter_api_key", None)
        )
    elif selected_model is None:
        model = _bounded_text(
            getattr(settings, "openai_synthesis_model", "gpt-5.6-sol"),
            default="gpt-5.6-sol",
            maximum=80,
        )
        key_present = _secret_present(getattr(settings, "openai_api_key", None))
    enabled = bool(getattr(settings, "grounded_synthesis_enabled", True))
    skip_code = (
        "grounded_synthesis_disabled"
        if not enabled
        else "api_key_missing"
        if not key_present
        else None
    )
    run = ProviderRun(
        id=new_id(),
        job_id=job.id,
        attempt_id=job.active_attempt_id,
        logical_run_id=f"synthesis:{gateway}:grounded:v2",
        provider_id=GROUNDED_SYNTHESIS_PROVIDER_ID,
        parent_run_id=None,
        depth=2,
        query_config={
            "gateway": gateway,
            "model": model,
            "prompt_version": GROUNDED_SYNTHESIS_PROMPT_VERSION,
            "reasoning_effort": _reasoning_effort(
                getattr(
                    settings,
                    "grounded_synthesis_reasoning_effort",
                    getattr(settings, "openai_synthesis_reasoning_effort", "medium"),
                )
            ),
            "max_output_tokens": _bounded_int(
                getattr(
                    settings,
                    "grounded_synthesis_max_output_tokens",
                    getattr(settings, "openai_synthesis_max_output_tokens", 16_000),
                ),
                default=16_000,
                minimum=800,
                maximum=32_000,
            ),
            "max_attempts": _bounded_int(
                getattr(settings, "grounded_synthesis_max_attempts", 3),
                default=3,
                minimum=1,
                maximum=5,
            ),
            "retry_backoff_seconds": _bounded_int(
                getattr(settings, "grounded_synthesis_retry_backoff_seconds", 2),
                default=2,
                minimum=0,
                maximum=30,
            ),
            "max_evidence_items": _bounded_int(
                getattr(settings, "grounded_synthesis_max_evidence_items", 40),
                default=40,
                minimum=10,
                maximum=40,
            ),
            "max_evidence_characters": _bounded_int(
                getattr(settings, "grounded_synthesis_max_evidence_characters", 60_000),
                default=60_000,
                minimum=5_000,
                maximum=100_000,
            ),
        },
        status="skipped_configuration" if skip_code else "pending",
        required_for_finalization=True,
        lease_generation=0,
        lease_expires_at=None,
        acceptance_epoch=job.acceptance_epoch,
        result_count=0,
        deadline_at=None,
        expires_at=job.expires_at,
    )
    session.add(run)
    session.flush()

    if skip_code:
        session.add(
            GroundedSynthesisResult(
                provider_run_id=run.id,
                job_id=job.id,
                status="skipped_configuration",
                model=model,
                prompt_version=GROUNDED_SYNTHESIS_PROMPT_VERSION,
                input_checksum=stable_payload_hash(
                    {"job_id": job.id, "fallback_reason": skip_code}
                ),
                output=None,
                usage=None,
                error_code=skip_code,
                created_at=now,
                expires_at=job.expires_at,
            )
        )
        add_event(
            session,
            job_id=job.id,
            event_type="discovery.synthesis_progress",
            message=(
                "The Deep story engine is not configured; a Quick-grade evidence "
                "report will be delivered as a partial fallback."
            ),
            created_at=now,
        )
        session.flush()
        return False

    session.add(
        OutboxMessage(
            id=new_id(),
            topic="grounded_synthesis_run",
            dedupe_key=f"grounded-synthesis:{run.id}:generation:1",
            payload={"provider_run_id": run.id},
            created_at=now,
            dispatched_at=None,
            attempts=0,
        )
    )
    job.exploration_status = "running"
    job.row_version += 1
    add_event(
        session,
        job_id=job.id,
        event_type="discovery.synthesis_started",
        message="Adaptive retrieval is complete; composing the source-grounded Deep story.",
        created_at=now,
    )
    return True


def _secret_present(value: object) -> bool:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        value = getter()
    return bool(isinstance(value, str) and value.strip())


def _reasoning_effort(value: object) -> str:
    normalized = str(value).strip().casefold()
    return normalized if normalized in {"none", "low", "medium", "high"} else "low"


def _synthesis_gateway(value: object) -> str:
    normalized = str(value).strip().casefold()
    return normalized if normalized in {"openai", "openrouter"} else "openai"


def _bounded_text(value: object, *, default: str, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    return normalized[:maximum] or default


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
