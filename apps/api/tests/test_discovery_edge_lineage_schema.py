from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.exc import IntegrityError

from apps.api.app.models import Base
from apps.api.app.models.entities import DiscoveryEdge


def _edge_values(
    edge_id: str,
    *,
    site_check_id: str | None,
    source_observation_id: str | None,
) -> dict[str, object]:
    return {
        "id": edge_id,
        "job_id": "job-1",
        "provider_run_id": "provider-run-1",
        "site_check_id": site_check_id,
        "source_observation_id": source_observation_id,
        "child_account_node_id": "account-1",
        "parent_seed": "example",
        "discovery_method": "exact_profile_url",
        "discovery_engine": "test",
        "depth": 0,
        "created_at": datetime(2026, 7, 30, tzinfo=UTC),
    }


def test_discovery_edge_metadata_has_two_exclusive_lineage_paths() -> None:
    table = DiscoveryEdge.__table__

    assert table.c.site_check_id.nullable is True
    assert table.c.source_observation_id.nullable is True
    assert {constraint.name for constraint in table.constraints} >= {
        "ck_discovery_edge_exactly_one_lineage",
        "uq_discovery_probe_edge",
        "uq_discovery_observation_edge",
    }

    observation_foreign_keys = list(table.c.source_observation_id.foreign_keys)
    assert len(observation_foreign_keys) == 1
    assert observation_foreign_keys[0].target_fullname == "source_observation.id"
    assert observation_foreign_keys[0].ondelete == "CASCADE"


def test_discovery_edge_rejects_missing_or_ambiguous_lineage() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    for edge_id, site_check_id, source_observation_id in (
        ("neither", None, None),
        ("both", "site-check-1", "observation-1"),
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert(DiscoveryEdge).values(
                    _edge_values(
                        edge_id,
                        site_check_id=site_check_id,
                        source_observation_id=source_observation_id,
                    )
                )
            )


def test_discovery_edge_accepts_each_lineage_and_deduplicates_observations() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(DiscoveryEdge).values(
                _edge_values(
                    "site-backed",
                    site_check_id="site-check-1",
                    source_observation_id=None,
                )
            )
        )
        connection.execute(
            insert(DiscoveryEdge).values(
                _edge_values(
                    "observation-backed",
                    site_check_id=None,
                    source_observation_id="observation-1",
                )
            )
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(DiscoveryEdge).values(
                _edge_values(
                    "duplicate-observation",
                    site_check_id=None,
                    source_observation_id="observation-1",
                )
            )
        )
