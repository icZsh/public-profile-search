"""Allow deadline-free grounded-synthesis provider runs.

Revision ID: 0006_unbounded_synthesis
Revises: 0005_grounded_synthesis
Create Date: 2026-08-03

Retrieval provider runs continue to receive concrete deadlines. Only the optional
grounded-synthesis run uses NULL to mean that story composition has no wall-clock
cutoff.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_unbounded_synthesis"
down_revision = "0005_grounded_synthesis"
branch_labels = None
depends_on = None

_TABLE_NAME = "provider_run"
_COLUMN_NAME = "deadline_at"
_COLUMN_TYPE = sa.DateTime(timezone=True)


def _deadline_column() -> dict[str, object] | None:
    columns = sa.inspect(op.get_bind()).get_columns(_TABLE_NAME)
    return next(
        (column for column in columns if column.get("name") == _COLUMN_NAME),
        None,
    )


def _set_nullable(*, nullable: bool) -> None:
    column = _deadline_column()
    if column is None or bool(column["nullable"]) == nullable:
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE_NAME, recreate="always") as batch_op:
            batch_op.alter_column(
                _COLUMN_NAME,
                existing_type=_COLUMN_TYPE,
                nullable=nullable,
            )
        return
    op.alter_column(
        _TABLE_NAME,
        _COLUMN_NAME,
        existing_type=_COLUMN_TYPE,
        nullable=nullable,
    )


def upgrade() -> None:
    _set_nullable(nullable=True)


def downgrade() -> None:
    provider_run = sa.table(
        _TABLE_NAME,
        sa.column(_COLUMN_NAME, _COLUMN_TYPE),
        sa.column("expires_at", _COLUMN_TYPE),
    )
    op.execute(
        provider_run.update()
        .where(provider_run.c.deadline_at.is_(None))
        .values(deadline_at=provider_run.c.expires_at)
    )
    _set_nullable(nullable=False)
