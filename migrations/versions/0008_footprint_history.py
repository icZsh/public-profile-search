"""Add owner-scoped footprint history, refresh lineage, and outbox priority.

Revision ID: 0008_footprint_history
Revises: 0007_footprint_synthesis_model
Create Date: 2026-08-15

Migration 0001 imports live ORM metadata, so fresh databases may already contain
these columns, constraints, and indexes. Operations are conditional so fresh
installs and upgrades from 0007 converge.
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_footprint_history"
down_revision = "0007_footprint_synthesis_model"
branch_labels = None
depends_on = None

_SEARCH_JOB = "search_job"
_OUTBOX = "outbox_message"
_REFRESH_FK = "fk_search_job_refresh_of_job_id_search_job"


def _inspector():
    return sa.inspect(op.get_bind())


def _table_names() -> set[str]:
    return set(_inspector().get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {str(column["name"]) for column in _inspector().get_columns(table_name)}


def _index_columns(table_name: str) -> dict[str, tuple[str | None, ...]]:
    return {
        str(index["name"]): tuple(index.get("column_names") or ())
        for index in _inspector().get_indexes(table_name)
    }


def _refresh_fk_exists() -> bool:
    return any(
        foreign_key.get("referred_table") == _SEARCH_JOB
        and tuple(foreign_key.get("constrained_columns") or ()) == ("refresh_of_job_id",)
        for foreign_key in _inspector().get_foreign_keys(_SEARCH_JOB)
    )


def _rename_retry_column() -> None:
    columns = _column_names(_SEARCH_JOB)
    if "retry_of_job_id" not in columns or "refresh_of_job_id" in columns:
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(_SEARCH_JOB) as batch:
            batch.alter_column(
                "retry_of_job_id",
                existing_type=sa.String(length=36),
                new_column_name="refresh_of_job_id",
            )
    else:
        op.alter_column(
            _SEARCH_JOB,
            "retry_of_job_id",
            existing_type=sa.String(length=36),
            new_column_name="refresh_of_job_id",
        )


def _ensure_refresh_fk() -> None:
    if _refresh_fk_exists():
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(_SEARCH_JOB) as batch:
            batch.create_foreign_key(
                _REFRESH_FK,
                _SEARCH_JOB,
                ["refresh_of_job_id"],
                ["id"],
                ondelete="SET NULL",
            )
    else:
        op.create_foreign_key(
            _REFRESH_FK,
            _SEARCH_JOB,
            _SEARCH_JOB,
            ["refresh_of_job_id"],
            ["id"],
            ondelete="SET NULL",
        )


def _ensure_index(table_name: str, name: str, columns: list[str]) -> None:
    # Some migration round-trip tests intentionally model only the column
    # introduced by the immediately preceding revision. Keep this conditional
    # migration safe for those partial/legacy schemas as well as full installs.
    if not set(columns).issubset(_column_names(table_name)):
        return
    indexes = _index_columns(table_name)
    expected = tuple(columns)
    if indexes.get(name) == expected:
        return
    if name in indexes:
        op.drop_index(name, table_name=table_name)
    op.create_index(name, table_name, columns, unique=False)


def upgrade() -> None:
    tables = _table_names()
    if _SEARCH_JOB in tables:
        _rename_retry_column()
        columns = _column_names(_SEARCH_JOB)
        if "refresh_of_job_id" not in columns:
            op.add_column(
                _SEARCH_JOB,
                sa.Column("refresh_of_job_id", sa.String(length=36), nullable=True),
            )
        if "history_reuse_policy" not in columns:
            op.add_column(
                _SEARCH_JOB,
                sa.Column("history_reuse_policy", sa.String(length=64), nullable=True),
            )
        _ensure_refresh_fk()
        _ensure_index(
            _SEARCH_JOB,
            "ix_search_job_owner_history",
            ["user_id", "job_kind", "accepted_at", "id"],
        )
        _ensure_index(
            _SEARCH_JOB,
            "ix_search_job_owner_exact_seed",
            [
                "user_id",
                "job_kind",
                "normalized_identifier_hmac",
                "accepted_at",
                "id",
            ],
        )
        _ensure_index(
            _SEARCH_JOB,
            "ix_search_job_expiry",
            ["expires_at", "id"],
        )
        _ensure_index(
            _SEARCH_JOB,
            "ix_search_job_refresh_lineage",
            ["refresh_of_job_id"],
        )

    if _OUTBOX in tables:
        columns = _column_names(_OUTBOX)
        if "priority" not in columns:
            op.add_column(
                _OUTBOX,
                sa.Column(
                    "priority",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                ),
            )
        _ensure_index(
            _OUTBOX,
            "ix_outbox_undispatched",
            ["dispatched_at", "priority", "created_at", "id"],
        )


def downgrade() -> None:
    tables = _table_names()
    if _OUTBOX in tables:
        indexes = _index_columns(_OUTBOX)
        if "ix_outbox_undispatched" in indexes:
            op.drop_index("ix_outbox_undispatched", table_name=_OUTBOX)
        columns = _column_names(_OUTBOX)
        if "priority" in columns:
            op.drop_column(_OUTBOX, "priority")
        op.create_index(
            "ix_outbox_undispatched",
            _OUTBOX,
            ["dispatched_at", "created_at"],
            unique=False,
        )

    if _SEARCH_JOB not in tables:
        return
    indexes = _index_columns(_SEARCH_JOB)
    for name in (
        "ix_search_job_refresh_lineage",
        "ix_search_job_expiry",
        "ix_search_job_owner_exact_seed",
        "ix_search_job_owner_history",
    ):
        if name in indexes:
            op.drop_index(name, table_name=_SEARCH_JOB)
    if _refresh_fk_exists():
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(_SEARCH_JOB) as batch:
                batch.drop_constraint(_REFRESH_FK, type_="foreignkey")
        else:
            op.drop_constraint(_REFRESH_FK, _SEARCH_JOB, type_="foreignkey")
    columns = _column_names(_SEARCH_JOB)
    if "history_reuse_policy" in columns:
        op.drop_column(_SEARCH_JOB, "history_reuse_policy")
    columns = _column_names(_SEARCH_JOB)
    if "refresh_of_job_id" in columns and "retry_of_job_id" not in columns:
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(_SEARCH_JOB) as batch:
                batch.alter_column(
                    "refresh_of_job_id",
                    existing_type=sa.String(length=36),
                    new_column_name="retry_of_job_id",
                )
        else:
            op.alter_column(
                _SEARCH_JOB,
                "refresh_of_job_id",
                existing_type=sa.String(length=36),
                new_column_name="retry_of_job_id",
            )
