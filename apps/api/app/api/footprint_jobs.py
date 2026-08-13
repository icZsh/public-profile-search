import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from apps.api.app.core.auth import AuthContext, require_prototype_auth
from apps.api.app.core.db import get_session
from apps.api.app.core.errors import ApiError
from apps.api.app.models.entities import JobEvent
from apps.api.app.schemas.generated import (
    CandidateListResponse,
    CreateFootprintJobRequest,
    EvidenceListResponse,
    FootprintBriefResponse,
    FootprintJobResponse,
    SelectFootprintAnchorRequest,
    SelectFootprintAnchorResponse,
)
from apps.api.app.services.anchor_selection import (
    anchor_selection_is_open,
    select_footprint_anchor,
)
from apps.api.app.services.candidates import get_candidates
from apps.api.app.services.deletion import delete_job
from apps.api.app.services.discovery_jobs import (
    create_footprint_job,
    footprint_job_response,
    owner_footprint_job,
)
from apps.api.app.services.footprint_cancellation import cancel_footprint_job
from apps.api.app.services.footprint_reports import (
    get_footprint_brief,
    get_footprint_evidence,
)
from apps.api.app.services.maigret_runs import finalize_discovery_if_complete

router = APIRouter(prefix="/v1/footprint-jobs", tags=["footprint-jobs"])


@router.post("", response_model=FootprintJobResponse, status_code=202)
def create_discovery_job(
    body: CreateFootprintJobRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    job, _created = create_footprint_job(
        session,
        settings=request.app.state.settings,
        clock=request.app.state.clock,
        user_id=auth.user_id,
        idempotency_key=idempotency_key,
        request_payload=body.model_dump(mode="json", exclude_none=True),
    )
    session.commit()
    return footprint_job_response(
        session,
        job,
        settings=request.app.state.settings,
    )


@router.get("/{job_id}", response_model=FootprintJobResponse)
def get_discovery_job(
    job_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    job = owner_footprint_job(
        session,
        job_id=str(job_id),
        user_id=auth.user_id,
        for_update=True,
    )
    # The browser polls this route throughout discovery. Advance an expired
    # checkpoint here as a backstop for watchdog cadence so the UI never keeps
    # presenting a chooser that can no longer accept a selection.
    now = request.app.state.clock.now()
    if job.exploration_status == "awaiting_anchor" and not anchor_selection_is_open(
        job=job,
        now=now,
    ):
        finalize_discovery_if_complete(
            session,
            job=job,
            now=now,
            settings=request.app.state.settings,
        )
        session.commit()
    return footprint_job_response(
        session,
        job,
        settings=request.app.state.settings,
    )


@router.get("/{job_id}/candidates", response_model=CandidateListResponse)
def get_discovery_candidates(
    job_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return get_candidates(
        session,
        job_id=str(job_id),
        user_id=auth.user_id,
        settings=request.app.state.settings,
        now=request.app.state.clock.now(),
    )


@router.post(
    "/{job_id}/anchor",
    response_model=SelectFootprintAnchorResponse,
)
def select_discovery_anchor(
    job_id: UUID,
    body: SelectFootprintAnchorRequest,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        job, anchor = select_footprint_anchor(
            session,
            job_id=str(job_id),
            user_id=auth.user_id,
            candidate_id=str(body.candidate_id),
            clock=request.app.state.clock,
            settings=request.app.state.settings,
        )
    except ApiError as exc:
        if exc.error_code == "anchor_selection_expired":
            # The service has atomically left the expired checkpoint and advanced
            # the remaining workflow. Persist that state before returning 409.
            session.commit()
        raise
    session.commit()
    return {
        "job": footprint_job_response(
            session,
            job,
            settings=request.app.state.settings,
        ),
        "selected_anchor": {
            "candidate_id": anchor.id,
            "platform": anchor.platform,
            "handle": anchor.canonical_handle,
            "profile_url": anchor.canonical_url,
            "display_name": anchor.display_name,
            "selection_state": anchor.selection_state,
        },
    }


@router.get("/{job_id}/brief", response_model=FootprintBriefResponse)
def get_discovery_brief(
    job_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return get_footprint_brief(
        session,
        job_id=str(job_id),
        user_id=auth.user_id,
        reads_enabled=request.app.state.settings.prototype_report_reads_enabled,
    )


@router.get("/{job_id}/evidence", response_model=EvidenceListResponse)
def get_discovery_evidence(
    job_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return {
        "items": get_footprint_evidence(
            session,
            job_id=str(job_id),
            user_id=auth.user_id,
            reads_enabled=request.app.state.settings.prototype_report_reads_enabled,
        )
    }


@router.get("/{job_id}/events")
def stream_discovery_job_events(
    job_id: UUID,
    request: Request,
    last_event_id_query: int = Query(default=0, alias="last_event_id", ge=0),
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    auth: AuthContext = Depends(require_prototype_auth),
):
    with request.app.state.session_factory() as session:
        owner_footprint_job(session, job_id=str(job_id), user_id=auth.user_id)
    try:
        header_sequence = int(last_event_id_header or 0)
    except ValueError:
        header_sequence = 0
    starting_sequence = max(last_event_id_query, header_sequence)
    factory = request.app.state.session_factory

    async def event_generator():
        sequence = starting_sequence
        idle_ticks = 0
        while True:
            if await request.is_disconnected():
                return
            with factory() as session:
                events = session.scalars(
                    select(JobEvent)
                    .where(JobEvent.job_id == str(job_id), JobEvent.sequence > sequence)
                    .order_by(JobEvent.sequence)
                ).all()
            if events:
                idle_ticks = 0
                for event in events:
                    sequence = event.sequence
                    payload = {
                        "job_id": event.job_id,
                        "sequence": event.sequence,
                        "type": event.event_type,
                        "message": event.message,
                        "terminal": event.terminal,
                        "created_at": event.created_at.isoformat(),
                    }
                    yield {
                        "id": str(event.sequence),
                        "event": event.event_type,
                        "data": json.dumps(payload),
                    }
                    if event.terminal:
                        return
            else:
                idle_ticks += 1
                if idle_ticks % 25 == 0:
                    yield {"event": "heartbeat", "data": "{}"}
                await asyncio.sleep(0.4)

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "private, no-store",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


@router.post("/{job_id}/cancel", response_model=FootprintJobResponse)
def cancel_discovery_job(
    job_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    job = cancel_footprint_job(
        session,
        job_id=str(job_id),
        user_id=auth.user_id,
        clock=request.app.state.clock,
    )
    session.commit()
    return footprint_job_response(
        session,
        job,
        settings=request.app.state.settings,
    )


@router.delete("/{job_id}", status_code=204)
def delete_discovery_job(
    job_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> Response:
    owner_footprint_job(
        session,
        job_id=str(job_id),
        user_id=auth.user_id,
    )
    delete_job(
        session,
        job_id=str(job_id),
        user_id=auth.user_id,
        now=request.app.state.clock.now(),
    )
    session.commit()
    return Response(status_code=204)
