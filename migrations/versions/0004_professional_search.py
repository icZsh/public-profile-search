"""Add source-observation lineage for professional-search discoveries.

Revision ID: 0004_professional
Revises: 0003_maigret
Create Date: 2026-07-30

Migration 0001 imports live ORM metadata, so a fresh database may already contain
this column and these constraints before this revision runs. Every operation is
conditional so fresh installs and upgrades from 0003 converge without rewriting
existing Maigret-backed discovery edges.
"""

from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op

revision = "0004_professional"
down_revision = "0003_maigret"
branch_labels = None
depends_on = None

_TABLE_NAME = "discovery_edge"
_OBSERVATION_FOREIGN_KEY = "fk_discovery_edge_source_observation_id"
_OBSERVATION_UNIQUE = "uq_discovery_observation_edge"
_LINEAGE_CHECK = "ck_discovery_edge_exactly_one_lineage"


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _columns() -> dict[str, dict[str, object]]:
    return {
        str(column["name"]): column
        for column in _inspector().get_columns(_TABLE_NAME)
    }


def _foreign_keys() -> list[dict[str, object]]:
    return list(_inspector().get_foreign_keys(_TABLE_NAME))


def _has_foreign_key(constrained_columns: Iterable[str]) -> bool:
    expected = tuple(constrained_columns)
    return any(
        tuple(str(column) for column in foreign_key["constrained_columns"])
        == expected
        for foreign_key in _foreign_keys()
    )


def _foreign_key_name(constrained_columns: Iterable[str]) -> str | None:
    expected = tuple(constrained_columns)
    for foreign_key in _foreign_keys():
        actual = tuple(
            str(column) for column in foreign_key["constrained_columns"]
        )
        if actual == expected:
            name = foreign_key.get("name")
            return str(name) if name else None
    return None


def _has_unique_constraint(
    constrained_columns: Iterable[str],
    *,
    name: str,
) -> bool:
    expected = tuple(constrained_columns)
    return any(
        constraint.get("name") == name
        or tuple(
            str(column) for column in constraint.get("column_names") or ()
        )
        == expected
        for constraint in _inspector().get_unique_constraints(_TABLE_NAME)
    )


def _has_check_constraint(name: str) -> bool:
    return any(
        constraint.get("name") == name
        for constraint in _inspector().get_check_constraints(_TABLE_NAME)
    )


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _upgrade_sqlite(
    *,
    add_observation_column: bool,
    make_site_check_nullable: bool,
    add_observation_foreign_key: bool,
    add_observation_unique: bool,
    add_lineage_check: bool,
) -> None:
    if not any(
        (
            add_observation_column,
            make_site_check_nullable,
            add_observation_foreign_key,
            add_observation_unique,
            add_lineage_check,
        )
    ):
        return

    with op.batch_alter_table(_TABLE_NAME, recreate="always") as batch_op:
        if add_observation_column:
            batch_op.add_column(
                sa.Column(
                    "source_observation_id",
                    sa.String(length=36),
                    nullable=True,
                )
            )
        if make_site_check_nullable:
            batch_op.alter_column(
                "site_check_id",
                existing_type=sa.String(length=36),
                nullable=True,
            )
        if add_observation_foreign_key:
            batch_op.create_foreign_key(
                _OBSERVATION_FOREIGN_KEY,
                "source_observation",
                ["source_observation_id"],
                ["id"],
                ondelete="CASCADE",
            )
        if add_observation_unique:
            batch_op.create_unique_constraint(
                _OBSERVATION_UNIQUE,
                [
                    "provider_run_id",
                    "source_observation_id",
                    "child_account_node_id",
                ],
            )
        if add_lineage_check:
            batch_op.create_check_constraint(
                _LINEAGE_CHECK,
                """
                (
                    site_check_id IS NOT NULL
                    AND source_observation_id IS NULL
                )
                OR
                (
                    site_check_id IS NULL
                    AND source_observation_id IS NOT NULL
                )
                """,
            )


def upgrade() -> None:
    columns = _columns()
    add_observation_column = "source_observation_id" not in columns
    make_site_check_nullable = not bool(columns["site_check_id"]["nullable"])
    add_observation_foreign_key = not _has_foreign_key(
        ("source_observation_id",)
    )
    add_observation_unique = not _has_unique_constraint(
        (
            "provider_run_id",
            "source_observation_id",
            "child_account_node_id",
        ),
        name=_OBSERVATION_UNIQUE,
    )
    add_lineage_check = not _has_check_constraint(_LINEAGE_CHECK)

    if _is_sqlite():
        _upgrade_sqlite(
            add_observation_column=add_observation_column,
            make_site_check_nullable=make_site_check_nullable,
            add_observation_foreign_key=add_observation_foreign_key,
            add_observation_unique=add_observation_unique,
            add_lineage_check=add_lineage_check,
        )
        return

    if add_observation_column:
        op.add_column(
            _TABLE_NAME,
            sa.Column(
                "source_observation_id",
                sa.String(length=36),
                nullable=True,
            ),
        )
    if make_site_check_nullable:
        op.alter_column(
            _TABLE_NAME,
            "site_check_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
    if add_observation_foreign_key:
        op.create_foreign_key(
            _OBSERVATION_FOREIGN_KEY,
            _TABLE_NAME,
            "source_observation",
            ["source_observation_id"],
            ["id"],
            ondelete="CASCADE",
        )
    if add_observation_unique:
        op.create_unique_constraint(
            _OBSERVATION_UNIQUE,
            _TABLE_NAME,
            [
                "provider_run_id",
                "source_observation_id",
                "child_account_node_id",
            ],
        )
    if add_lineage_check:
        op.create_check_constraint(
            _LINEAGE_CHECK,
            _TABLE_NAME,
            """
            (
                site_check_id IS NOT NULL
                AND source_observation_id IS NULL
            )
            OR
            (
                site_check_id IS NULL
                AND source_observation_id IS NOT NULL
            )
            """,
        )


def _observation_backed_edge_count() -> int:
    discovery_edge = sa.table(
        _TABLE_NAME,
        sa.column("source_observation_id", sa.String()),
    )
    return int(
        op.get_bind().scalar(
            sa.select(sa.func.count())
            .select_from(discovery_edge)
            .where(discovery_edge.c.source_observation_id.is_not(None))
        )
        or 0
    )


def downgrade() -> None:
    if "source_observation_id" not in _columns():
        return
    if _observation_backed_edge_count():
        raise RuntimeError(
            "Cannot downgrade while source-observation-backed discovery edges exist"
        )

    observation_foreign_key_name = _foreign_key_name(
        ("source_observation_id",)
    )
    has_observation_unique = _has_unique_constraint(
        (
            "provider_run_id",
            "source_observation_id",
            "child_account_node_id",
        ),
        name=_OBSERVATION_UNIQUE,
    )
    has_lineage_check = _has_check_constraint(_LINEAGE_CHECK)

    if _is_sqlite():
        with op.batch_alter_table(_TABLE_NAME, recreate="always") as batch_op:
            if has_lineage_check:
                batch_op.drop_constraint(_LINEAGE_CHECK, type_="check")
            if has_observation_unique:
                batch_op.drop_constraint(_OBSERVATION_UNIQUE, type_="unique")
            if observation_foreign_key_name:
                batch_op.drop_constraint(
                    observation_foreign_key_name,
                    type_="foreignkey",
                )
            batch_op.drop_column("source_observation_id")
            batch_op.alter_column(
                "site_check_id",
                existing_type=sa.String(length=36),
                nullable=False,
            )
        return

    if has_lineage_check:
        op.drop_constraint(_LINEAGE_CHECK, _TABLE_NAME, type_="check")
    if has_observation_unique:
        op.drop_constraint(_OBSERVATION_UNIQUE, _TABLE_NAME, type_="unique")
    if observation_foreign_key_name:
        op.drop_constraint(
            observation_foreign_key_name,
            _TABLE_NAME,
            type_="foreignkey",
        )
    op.drop_column(_TABLE_NAME, "source_observation_id")
    op.alter_column(
        _TABLE_NAME,
        "site_check_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
