"""Persist validated, source-grounded narrative synthesis results.

Revision ID: 0005_grounded_synthesis
Revises: 0004_professional
Create Date: 2026-07-30

Migration 0001 imports live ORM metadata, so a fresh database can already contain
this table before this revision runs. The upgrade is conditional so fresh installs
and upgrades from 0004 converge.
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_grounded_synthesis"
down_revision = "0004_professional"
branch_labels = None
depends_on = None

_TABLE_NAME = "grounded_synthesis_result"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE_NAME in inspector.get_table_names():
        return
    op.create_table(
        _TABLE_NAME,
        sa.Column(
            "provider_run_id",
            sa.String(length=36),
            sa.ForeignKey("provider_run.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "job_id",
            sa.String(length=36),
            sa.ForeignKey("search_job.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("input_checksum", sa.String(length=64), nullable=False),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", name="uq_grounded_synthesis_job"),
    )
    op.create_index(
        "ix_grounded_synthesis_result_job_id",
        _TABLE_NAME,
        ["job_id"],
        unique=True,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE_NAME not in inspector.get_table_names():
        return
    op.drop_index(
        "ix_grounded_synthesis_result_job_id",
        table_name=_TABLE_NAME,
    )
    op.drop_table(_TABLE_NAME)
