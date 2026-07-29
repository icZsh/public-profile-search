import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from apps.api.app.core.auth import (
    AuthContext,
    require_prototype_admin,
    require_prototype_auth,
)
from apps.api.app.core.db import get_session
from apps.api.app.models.entities import JobEvent
from apps.api.app.schemas.generated import (
    CreateSearchJobRequest,
    EvidenceListResponse,
    FastBriefResponse,
    PrototypeConfigResponse,
    SearchJobResponse,
    SuppressionRequest,
)
from apps.api.app.services.deletion import delete_job
from apps.api.app.services.jobs import create_job, job_response, owner_job
from apps.api.app.services.reports import get_brief, get_evidence
from apps.api.app.services.suppression import suppress_profile

router = APIRouter(prefix="/v1")


@router.get("/prototype-config", response_model=PrototypeConfigResponse)
def prototype_config(
    request: Request,
    _auth: AuthContext = Depends(require_prototype_auth),
) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "fixture_url": settings.fixture_url,
        "eligibility_reference_id": settings.fixture_eligibility_reference_id,
        "purpose": "self_audit",
        "attestation_policy_version": settings.policy_version,
        "allowed_profile_hosts": ["github.com"],
        "github_provider_enabled": settings.github_provider_enabled,
    }


@router.post("/search-jobs", response_model=SearchJobResponse, status_code=202)
def create_search_job(
    body: CreateSearchJobRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    payload = body.model_dump(mode="json")
    job, _created = create_job(
        session,
        settings=request.app.state.settings,
        clock=request.app.state.clock,
        user_id=auth.user_id,
        idempotency_key=idempotency_key,
        request_payload=payload,
    )
    session.commit()
    return job_response(job)


@router.get("/search-jobs/{job_id}", response_model=SearchJobResponse)
def get_search_job(
    job_id: UUID,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    job = owner_job(session, job_id=str(job_id), user_id=auth.user_id)
    return job_response(job)


@router.get("/search-jobs/{job_id}/events")
def stream_search_job_events(
    job_id: UUID,
    request: Request,
    last_event_id_query: int = Query(default=0, alias="last_event_id", ge=0),
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    auth: AuthContext = Depends(require_prototype_auth),
):
    with request.app.state.session_factory() as session:
        owner_job(session, job_id=str(job_id), user_id=auth.user_id)
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


@router.get("/search-jobs/{job_id}/brief", response_model=FastBriefResponse)
def get_search_job_brief(
    job_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return get_brief(
        session,
        job_id=str(job_id),
        user_id=auth.user_id,
        reads_enabled=request.app.state.settings.prototype_report_reads_enabled,
        settings=request.app.state.settings,
        now=request.app.state.clock.now(),
    )


@router.get("/search-jobs/{job_id}/evidence", response_model=EvidenceListResponse)
def get_search_job_evidence(
    job_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return {
        "items": get_evidence(
            session,
            job_id=str(job_id),
            user_id=auth.user_id,
            reads_enabled=request.app.state.settings.prototype_report_reads_enabled,
            settings=request.app.state.settings,
            now=request.app.state.clock.now(),
        )
    }


@router.delete("/search-jobs/{job_id}", status_code=204)
def delete_search_job(
    job_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_prototype_auth),
    session: Session = Depends(get_session),
) -> Response:
    delete_job(
        session,
        job_id=str(job_id),
        user_id=auth.user_id,
        now=request.app.state.clock.now(),
    )
    session.commit()
    return Response(status_code=204)


@router.post("/prototype/suppressions", status_code=204)
def create_prototype_suppression(
    body: SuppressionRequest,
    request: Request,
    _admin: None = Depends(require_prototype_admin),
    session: Session = Depends(get_session),
) -> Response:
    suppress_profile(
        session,
        settings=request.app.state.settings,
        profile_url=str(body.profile_url),
        now=request.app.state.clock.now(),
    )
    session.commit()
    return Response(status_code=204)
