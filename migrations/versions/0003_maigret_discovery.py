"""Add Maigret-backed footprint discovery.

Revision ID: 0003_maigret
Revises: 0002_github_eval
Create Date: 2026-07-29

Migration 0001 imports live ORM metadata, so a fresh database may already contain
these tables and columns before this revision runs. Every operation is conditional so
fresh installs and upgrades from 0002 converge.
"""

import sqlalchemy as sa
from alembic import op

from apps.api.app.models import Base

revision = "0003_maigret"
down_revision = "0002_github_eval"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> dict[str, dict[str, object]]:
    return {
        str(column["name"]): column
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _add_column_if_missing(table_name: str, column: sa.Column[object]) -> None:
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def _create_model_table(table_name: str) -> None:
    if table_name not in _table_names():
        Base.metadata.tables[table_name].create(bind=op.get_bind(), checkfirst=True)


def upgrade() -> None:
    _create_model_table("maigret_catalog_snapshot")

    _add_column_if_missing(
        "search_job",
        sa.Column(
            "job_kind",
            sa.String(length=40),
            nullable=False,
            server_default="fast_brief",
        ),
    )
    for name, length in (
        ("seed_kind", 40),
        ("seed_platform", 80),
        ("seed_identifier_type", 40),
        ("seed_identifier", 160),
        ("normalized_seed", 240),
        ("search_mode", 24),
        ("catalog_profile", 40),
        ("exploration_status", 40),
    ):
        _add_column_if_missing(
            "search_job",
            sa.Column(name, sa.String(length=length), nullable=True),
        )
    _add_column_if_missing(
        "search_job",
        sa.Column(
            "catalog_snapshot_id",
            sa.String(length=36),
            sa.ForeignKey("maigret_catalog_snapshot.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )

    eligibility_column = _columns("search_job").get("eligibility_verification_id")
    if eligibility_column is not None and not bool(eligibility_column["nullable"]):
        op.alter_column(
            "search_job",
            "eligibility_verification_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )

    _add_column_if_missing(
        "provider_run",
        sa.Column("parent_run_id", sa.String(length=36), nullable=True),
    )
    _add_column_if_missing(
        "provider_run",
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "provider_run",
        sa.Column("query_config", sa.JSON(), nullable=True),
    )

    for table_name in (
        "maigret_scan_run",
        "maigret_site_check",
        "account_node",
        "discovery_edge",
        "discovered_identifier",
    ):
        _create_model_table(table_name)


def downgrade() -> None:
    for table_name in (
        "discovered_identifier",
        "discovery_edge",
        "account_node",
        "maigret_site_check",
        "maigret_scan_run",
    ):
        if table_name in _table_names():
            op.drop_table(table_name)

    for name in (
        "query_config",
        "depth",
        "parent_run_id",
    ):
        if name in _columns("provider_run"):
            op.drop_column("provider_run", name)

    for name in (
        "exploration_status",
        "catalog_snapshot_id",
        "catalog_profile",
        "search_mode",
        "normalized_seed",
        "seed_identifier",
        "seed_identifier_type",
        "seed_platform",
        "seed_kind",
        "job_kind",
    ):
        if name in _columns("search_job"):
            op.drop_column("search_job", name)

    if "maigret_catalog_snapshot" in _table_names():
        op.drop_table("maigret_catalog_snapshot")
