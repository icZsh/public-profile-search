from __future__ import annotations

import unicodedata
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.core.errors import ApiError
from apps.api.app.models.entities import AccountNode, SearchJob
from apps.api.app.services.discovery_jobs import owner_footprint_job
from apps.api.app.services.events import add_event

_TERMINAL_JOB_STATES = {
    "ready",
    "ready_partial",
    "no_candidates",
    "failed",
    "cancelled",
}
MIN_ANCHOR_SELECTION_SECONDS = 30
MIN_PROFESSIONAL_SEARCH_SECONDS = 30


def is_exact_handle_account(node: AccountNode, job: SearchJob) -> bool:
    return bool(
        not node.is_similar
        and job.seed_identifier
        and unicodedata.normalize("NFKC", node.canonical_handle).casefold()
        == unicodedata.normalize("NFKC", job.seed_identifier).casefold()
    )


def selected_anchor_from_nodes(
    nodes: list[AccountNode] | tuple[AccountNode, ...],
    *,
    job: SearchJob,
) -> AccountNode | None:
    return next(
        (
            node
            for node in nodes
            if node.selection_state == "included" and is_exact_handle_account(node, job)
        ),
        None,
    )


def selected_anchor(
    session: Session,
    *,
    job: SearchJob,
) -> AccountNode | None:
    nodes = session.scalars(
        select(AccountNode)
        .where(
            AccountNode.job_id == job.id,
            AccountNode.selection_state == "included",
        )
        .order_by(AccountNode.first_observed_at, AccountNode.id)
    ).all()
    return selected_anchor_from_nodes(nodes, job=job)


def eligible_anchor_candidate_ids(
    session: Session,
    *,
    job: SearchJob,
    settings: object,
    now=None,
) -> frozenset[str]:
    """Return the exact account nodes that provide a plausible name hypothesis."""

    if now is not None and not anchor_selection_is_open(job=job, now=now):
        return frozenset()

    # Imported lazily because professional scheduling also consumes the selected
    # anchor when ordering its hypotheses.
    from apps.api.app.services.professional_search_scheduling import (
        derive_professional_name_hypotheses,
    )

    maximum_names = _bounded_int(
        getattr(settings, "adaptive_professional_search_max_names", 4),
        default=4,
        minimum=1,
        maximum=6,
    )
    hypotheses = derive_professional_name_hypotheses(
        session,
        job=job,
        maximum_names=max(2, maximum_names),
        include_context_anchors=False,
    )
    return frozenset(
        node_id
        for hypothesis in hypotheses
        for node_id in hypothesis.name_source_node_ids
    )


def anchor_selection_is_open(*, job: SearchJob, now) -> bool:
    """Keep a minimum retrieval window after the user makes a choice."""

    deadline = job.deadline_at
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return (deadline - now).total_seconds() >= MIN_PROFESSIONAL_SEARCH_SECONDS


def expire_anchor_checkpoint_if_needed(
    session: Session,
    *,
    job: SearchJob,
    now,
) -> bool:
    """Leave an expired chooser so the remaining bounded workflow can continue."""

    if job.exploration_status != "awaiting_anchor" or anchor_selection_is_open(
        job=job,
        now=now,
    ):
        return False
    job.exploration_status = "running"
    job.row_version += 1
    add_event(
        session,
        job_id=job.id,
        event_type="discovery.anchor_window_expired",
        message=(
            "No anchor was selected before the checkpoint closed; continuing "
            "within the remaining bounded search window using the available "
            "account evidence."
        ),
        created_at=now,
    )
    return True


def select_footprint_anchor(
    session: Session,
    *,
    job_id: str,
    user_id: str,
    candidate_id: str,
    clock,
    settings: object,
) -> tuple[SearchJob, AccountNode]:
    job = owner_footprint_job(
        session,
        job_id=job_id,
        user_id=user_id,
        for_update=True,
    )
    nodes = session.scalars(
        select(AccountNode)
        .where(AccountNode.job_id == job.id)
        .order_by(AccountNode.first_observed_at, AccountNode.id)
        .with_for_update()
    ).all()
    # Sample the cutoff only after both the job and its candidates are locked.
    # A request that waited on either lock must not use a stale pre-lock time.
    now = clock.now()
    candidate = next((node for node in nodes if node.id == candidate_id), None)
    if candidate is None:
        raise ApiError(
            404,
            "anchor_candidate_not_found",
            "The anchor candidate was not found for this discovery job.",
        )
    if job.seed_kind != "bare_handle":
        raise ApiError(
            409,
            "anchor_selection_not_required",
            "This discovery job already has a platform anchor.",
        )
    if not is_exact_handle_account(candidate, job):
        raise ApiError(
            422,
            "anchor_candidate_invalid",
            "Only an exact-handle candidate can be selected as the anchor.",
        )

    current = selected_anchor_from_nodes(nodes, job=job)
    if current and current.id == candidate.id:
        return job, current
    if job.status in _TERMINAL_JOB_STATES:
        raise ApiError(
            409,
            "anchor_selection_closed",
            "This discovery job has already been finalized.",
        )
    if job.exploration_status != "awaiting_anchor":
        raise ApiError(
            409,
            "anchor_selection_unavailable",
            "This discovery job is not waiting for an anchor selection.",
        )
    if not anchor_selection_is_open(job=job, now=now):
        expire_anchor_checkpoint_if_needed(
            session,
            job=job,
            now=now,
        )
        # Imported lazily to keep the scan -> scheduling -> selection module graph
        # acyclic. The API route commits this transition before returning the 409.
        from apps.api.app.services.maigret_runs import finalize_discovery_if_complete

        finalize_discovery_if_complete(
            session,
            job=job,
            now=now,
            settings=settings,
        )
        session.flush()
        raise ApiError(
            409,
            "anchor_selection_expired",
            "The anchor selection window has closed.",
        )
    if candidate.id not in eligible_anchor_candidate_ids(
        session,
        job=job,
        settings=settings,
        now=now,
    ):
        raise ApiError(
            422,
            "anchor_candidate_not_hypothesis",
            "The selected account does not participate in a plausible name hypothesis.",
        )

    for node in nodes:
        if node.selection_state == "included":
            node.selection_state = "undecided"
    candidate.selection_state = "included"
    job.exploration_status = "running"
    job.row_version += 1
    add_event(
        session,
        job_id=job.id,
        event_type="discovery.anchor_selected",
        message=f"Selected the {candidate.platform} account as the search anchor.",
        created_at=now,
    )
    session.flush()

    # Imported lazily to keep the scan -> scheduling -> selection module graph acyclic.
    from apps.api.app.services.maigret_runs import finalize_discovery_if_complete

    finalize_discovery_if_complete(
        session,
        job=job,
        now=now,
        settings=settings,
    )
    return job, candidate


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))
