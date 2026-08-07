from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.models.entities import (
    AccountNode,
    DiscoveredIdentifier,
    DiscoveryEdge,
    MaigretSiteCheck,
)
from apps.api.app.services.anchor_selection import eligible_anchor_candidate_ids
from apps.api.app.services.discovery_jobs import owner_footprint_job


def get_candidates(
    session: Session,
    *,
    job_id: str,
    user_id: str,
    settings: object,
    now,
) -> dict[str, object]:
    job = owner_footprint_job(session, job_id=job_id, user_id=user_id)
    anchor_eligible_ids = (
        eligible_anchor_candidate_ids(
            session,
            job=job,
            settings=settings,
            now=now,
        )
        if job.exploration_status == "awaiting_anchor"
        else frozenset()
    )
    rows = session.execute(
        select(AccountNode, DiscoveryEdge, MaigretSiteCheck)
        .join(DiscoveryEdge, DiscoveryEdge.child_account_node_id == AccountNode.id)
        .join(MaigretSiteCheck, MaigretSiteCheck.id == DiscoveryEdge.site_check_id)
        .where(AccountNode.job_id == job_id)
        .order_by(AccountNode.platform, AccountNode.canonical_url, DiscoveryEdge.created_at)
    ).all()
    items_by_id: dict[str, dict[str, object]] = {}
    for node, edge, site_check in rows:
        item = items_by_id.get(node.id)
        evidence = {
            "site_check_id": site_check.id,
            "site_name": site_check.site_name,
            "status": site_check.raw_status,
            "discovery_method": edge.discovery_method,
            "observed_at": site_check.observed_at,
        }
        if item:
            cast_evidence = item["evidence"]
            assert isinstance(cast_evidence, list)
            cast_evidence.append(evidence)
            continue
        items_by_id[node.id] = {
            "candidate_id": node.id,
            "platform": node.platform,
            "handle": node.canonical_handle,
            "profile_url": node.canonical_url,
            "display_name": node.display_name,
            "relationship": "unresolved",
            "identity_tier": node.identity_confidence_tier,
            "selection_state": node.selection_state,
            "anchor_eligible": node.id in anchor_eligible_ids,
            "is_similar": node.is_similar,
            "profile_data": node.profile_data,
            "discovered_at": node.first_observed_at,
            "evidence": [evidence],
        }
    pivot_count = session.scalar(
        select(func.count(DiscoveredIdentifier.id)).where(DiscoveredIdentifier.job_id == job_id)
    )
    return {
        "items": list(items_by_id.values()),
        "extracted_identifier_count": int(pivot_count or 0),
    }
