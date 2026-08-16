import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from apps.api.app.core.errors import ApiError
from apps.api.app.models.entities import (
    AccountNode,
    JobAttempt,
    ReportAccessState,
    ReportRevision,
    SearchJob,
)
from apps.api.app.services.deletion import delete_locked_job

_FOOTPRINT_JOB_KIND = "footprint_discovery"
_TERMINAL_HISTORY_STATUSES = {
    "ready",
    "ready_partial",
    "no_candidates",
    "failed",
    "cancelled",
}
_RESULT_STATUSES = {"ready", "ready_partial", "no_candidates"}


def _invalid_cursor() -> ApiError:
    return ApiError(422, "invalid_request", "The history cursor is invalid.")


def _encode_cursor(accepted_at: datetime, job_id: str) -> str:
    payload = json.dumps(
        {"accepted_at": accepted_at.isoformat(), "job_id": job_id},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(payload, dict):
            raise ValueError
        accepted_at = datetime.fromisoformat(str(payload["accepted_at"]))
        job_id = str(UUID(str(payload["job_id"])))
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise _invalid_cursor() from exc
    return accepted_at, job_id


def _after_cursor(accepted_at, job_id, cursor: tuple[datetime, str]):
    cursor_time, cursor_id = cursor
    return or_(
        accepted_at < cursor_time,
        (accepted_at == cursor_time) & (job_id < cursor_id),
    )


def _visible_history_filters(*, user_id: str, now) -> tuple[object, ...]:
    return (
        SearchJob.user_id == user_id,
        SearchJob.job_kind == _FOOTPRINT_JOB_KIND,
        SearchJob.expires_at > now,
    )


def _run_summaries(
    session: Session,
    jobs: list[SearchJob],
    *,
    result_reads_enabled: bool,
) -> dict[str, dict[str, object]]:
    if not jobs:
        return {}
    job_ids = [job.id for job in jobs]
    finished_at_by_job = {
        str(job_id): finished_at
        for job_id, finished_at in session.execute(
            select(JobAttempt.job_id, JobAttempt.finished_at).where(
                JobAttempt.job_id.in_(job_ids)
            )
        ).all()
    }
    candidate_count_by_job = {
        str(job_id): int(candidate_count)
        for job_id, candidate_count in session.execute(
            select(AccountNode.job_id, func.count(AccountNode.id))
            .where(AccountNode.job_id.in_(job_ids))
            .group_by(AccountNode.job_id)
        ).all()
    }
    available_job_ids = (
        {
            str(job_id)
            for (job_id,) in session.execute(
                select(ReportRevision.job_id)
                .join(
                    ReportAccessState,
                    ReportAccessState.report_id == ReportRevision.id,
                )
                .where(
                    ReportRevision.job_id.in_(job_ids),
                    ReportRevision.status == "ready",
                    ReportRevision.report_type.in_({"account_centric", "person_centric"}),
                    ReportAccessState.job_id == ReportRevision.job_id,
                    ReportAccessState.state == "active",
                )
            ).all()
        }
        if result_reads_enabled
        else set()
    )
    return {
        job.id: {
            "job_id": job.id,
            "status": job.status,
            "search_mode": job.search_mode,
            "synthesis_model": job.synthesis_model,
            "accepted_at": job.accepted_at,
            "finished_at": finished_at_by_job.get(job.id),
            "expires_at": job.expires_at,
            "candidate_count": candidate_count_by_job.get(job.id, 0),
            "result_available": (
                job.status in _RESULT_STATUSES and job.id in available_job_ids
            ),
            "refresh_of_job_id": job.refresh_of_job_id,
        }
        for job in jobs
    }


def _seed_summary(job: SearchJob) -> dict[str, object]:
    return {
        "kind": (
            "bare_handle" if job.seed_kind == "bare_handle" else "platform_identifier"
        ),
        "platform": job.seed_platform,
        "identifier": job.seed_identifier,
    }


def list_history_groups(
    session: Session,
    *,
    user_id: str,
    now,
    q: str | None,
    cursor: str | None,
    limit: int,
    result_reads_enabled: bool,
) -> dict[str, object]:
    ranked = (
        select(
            SearchJob.id.label("job_id"),
            SearchJob.normalized_identifier_hmac.label("seed_hmac"),
            SearchJob.accepted_at.label("accepted_at"),
            func.count(SearchJob.id)
            .over(partition_by=SearchJob.normalized_identifier_hmac)
            .label("run_count"),
            func.row_number()
            .over(
                partition_by=SearchJob.normalized_identifier_hmac,
                order_by=(SearchJob.accepted_at.desc(), SearchJob.id.desc()),
            )
            .label("row_number"),
        )
        .where(*_visible_history_filters(user_id=user_id, now=now))
        .subquery()
    )
    statement = (
        select(
            ranked.c.job_id,
            ranked.c.accepted_at,
            ranked.c.run_count,
        )
        .join(SearchJob, SearchJob.id == ranked.c.job_id)
        .where(ranked.c.row_number == 1)
    )
    normalized_q = (q or "").strip().casefold()
    if normalized_q:
        statement = statement.where(
            func.lower(SearchJob.seed_identifier).contains(normalized_q, autoescape=True)
        )
    if cursor:
        statement = statement.where(
            _after_cursor(ranked.c.accepted_at, ranked.c.job_id, _decode_cursor(cursor))
        )
    rows = session.execute(
        statement.order_by(ranked.c.accepted_at.desc(), ranked.c.job_id.desc()).limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    job_ids = [str(row.job_id) for row in page_rows]
    jobs_by_id = {
        job.id: job
        for job in session.scalars(select(SearchJob).where(SearchJob.id.in_(job_ids))).all()
    }
    ordered_jobs = [jobs_by_id[job_id] for job_id in job_ids if job_id in jobs_by_id]
    summaries = _run_summaries(
        session,
        ordered_jobs,
        result_reads_enabled=result_reads_enabled,
    )
    items = []
    for row in page_rows:
        job = jobs_by_id.get(str(row.job_id))
        if job is None:
            continue
        items.append(
            {
                "representative_job_id": job.id,
                "seed": _seed_summary(job),
                "latest_run": summaries[job.id],
                "run_count": int(row.run_count),
            }
        )
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_cursor(last.accepted_at, str(last.job_id))
    return {"items": items, "next_cursor": next_cursor}


def list_related_history_runs(
    session: Session,
    *,
    representative_job_id: str,
    user_id: str,
    now,
    cursor: str | None,
    limit: int,
    result_reads_enabled: bool,
) -> dict[str, object]:
    representative = session.scalar(
        select(SearchJob).where(
            SearchJob.id == representative_job_id,
            *_visible_history_filters(user_id=user_id, now=now),
        )
    )
    if representative is None:
        raise ApiError(404, "job_not_found", "The discovery job was not found.")
    statement = select(SearchJob).where(
        *_visible_history_filters(user_id=user_id, now=now),
        SearchJob.normalized_identifier_hmac
        == representative.normalized_identifier_hmac,
    )
    if cursor:
        statement = statement.where(
            _after_cursor(SearchJob.accepted_at, SearchJob.id, _decode_cursor(cursor))
        )
    jobs = list(
        session.scalars(
            statement.order_by(SearchJob.accepted_at.desc(), SearchJob.id.desc()).limit(limit + 1)
        ).all()
    )
    has_more = len(jobs) > limit
    page_jobs = jobs[:limit]
    summaries = _run_summaries(
        session,
        page_jobs,
        result_reads_enabled=result_reads_enabled,
    )
    next_cursor = None
    if has_more and page_jobs:
        last = page_jobs[-1]
        next_cursor = _encode_cursor(last.accepted_at, last.id)
    return {
        "items": [summaries[job.id] for job in page_jobs],
        "next_cursor": next_cursor,
    }


def clear_terminal_history(
    session: Session,
    *,
    user_id: str,
    now,
    limit: int,
) -> dict[str, object]:
    jobs = list(
        session.scalars(
            select(SearchJob)
            .where(
                SearchJob.user_id == user_id,
                SearchJob.job_kind == _FOOTPRINT_JOB_KIND,
                SearchJob.status.in_(_TERMINAL_HISTORY_STATUSES),
            )
            .order_by(SearchJob.accepted_at.desc(), SearchJob.id.desc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )
    for job in jobs:
        delete_locked_job(session, job=job, now=now)
    session.flush()
    has_more = bool(
        session.scalar(
            select(SearchJob.id)
            .where(
                SearchJob.user_id == user_id,
                SearchJob.job_kind == _FOOTPRINT_JOB_KIND,
                SearchJob.status.in_(_TERMINAL_HISTORY_STATUSES),
            )
            .limit(1)
        )
    )
    return {"deleted_count": len(jobs), "has_more": has_more}
