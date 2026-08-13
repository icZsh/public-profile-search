"""Persist the curated synthesis model selected for a Deep footprint job.

Revision ID: 0007_footprint_synthesis_model
Revises: 0006_unbounded_synthesis
Create Date: 2026-08-11

Migration 0001 imports live ORM metadata, so a fresh database may already contain
this column before this revision runs. The operations are conditional so fresh
installs and upgrades from 0006 converge.
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_footprint_synthesis_model"
down_revision = "0006_unbounded_synthesis"
branch_labels = None
depends_on = None

_TABLE_NAME = "search_job"
_COLUMN_NAME = "synthesis_model"


def _table_exists() -> bool:
    return _TABLE_NAME in sa.inspect(op.get_bind()).get_table_names()


def _column_names() -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(_TABLE_NAME)
    }


def upgrade() -> None:
    if _table_exists() and _COLUMN_NAME not in _column_names():
        op.add_column(
            _TABLE_NAME,
            sa.Column(_COLUMN_NAME, sa.String(length=80), nullable=True),
        )


def downgrade() -> None:
    if _table_exists() and _COLUMN_NAME in _column_names():
        op.drop_column(_TABLE_NAME, _COLUMN_NAME)
