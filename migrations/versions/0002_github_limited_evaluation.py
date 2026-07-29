"""Add persistence for GitHub limited evaluation.

Revision ID: 0002_github_eval
Revises: 0001_phase2
Create Date: 2026-07-25

The initial migration imports live ORM metadata. A fresh database can therefore
already contain these columns by the time this revision runs. Every schema
operation below first inspects the database so both fresh installs and existing
0001 databases converge on the same shape.
"""

from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op

revision = "0002_github_eval"
down_revision = "0001_phase2"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> dict[str, dict[str, object]]:
    return {
        str(column["name"]): column for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _add_column_if_missing(table_name: str, column: sa.Column[object]) -> None:
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def _set_nullable(
    table_name: str,
    column_name: str,
    *,
    nullable: bool,
    existing_type: sa.types.TypeEngine[object],
) -> None:
    column = _columns(table_name).get(column_name)
    if column is not None and bool(column["nullable"]) != nullable:
        op.alter_column(
            table_name,
            column_name,
            existing_type=existing_type,
            nullable=nullable,
        )


def _foreign_keys(table_name: str) -> list[dict[str, object]]:
    return list(sa.inspect(op.get_bind()).get_foreign_keys(table_name))


def _has_foreign_key(table_name: str, constrained_columns: Iterable[str]) -> bool:
    expected = tuple(constrained_columns)
    return any(
        tuple(str(column) for column in foreign_key["constrained_columns"]) == expected
        for foreign_key in _foreign_keys(table_name)
    )


def _indexes(table_name: str) -> list[dict[str, object]]:
    return list(sa.inspect(op.get_bind()).get_indexes(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in _indexes(table_name))


def _drop_column_if_present(table_name: str, column_name: str) -> None:
    if column_name in _columns(table_name):
        op.drop_column(table_name, column_name)


def upgrade() -> None:
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("provider_id", sa.String(length=80), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("canonicalization_version", sa.String(length=32), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("canonical_url_ciphertext", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("provider_subject_hmac", sa.String(length=64), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("verification_method", sa.String(length=64), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("challenge_token_hmac", sa.String(length=64), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("challenge_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("review_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("attempt_count", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("control_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("reviewer_id", sa.String(length=80), nullable=True),
    )
    _add_column_if_missing(
        "eligibility_verification",
        sa.Column("review_code", sa.String(length=120), nullable=True),
    )

    eligibility = sa.table(
        "eligibility_verification",
        sa.column("provider_id", sa.String()),
        sa.column("canonicalization_version", sa.String()),
        sa.column("verification_method", sa.String()),
        sa.column("attempt_count", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("verified_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        eligibility.update()
        .where(eligibility.c.provider_id.is_(None))
        .values(provider_id="fixture_primary_v1")
    )
    op.execute(
        eligibility.update()
        .where(eligibility.c.canonicalization_version.is_(None))
        .values(canonicalization_version="profile-url-v1")
    )
    op.execute(
        eligibility.update()
        .where(eligibility.c.verification_method.is_(None))
        .values(verification_method="synthetic_seed")
    )
    op.execute(
        eligibility.update().where(eligibility.c.attempt_count.is_(None)).values(attempt_count=0)
    )
    op.execute(
        eligibility.update()
        .where(eligibility.c.created_at.is_(None))
        .values(created_at=sa.func.coalesce(eligibility.c.verified_at, sa.func.now()))
    )

    _set_nullable(
        "eligibility_verification",
        "provider_id",
        nullable=False,
        existing_type=sa.String(length=80),
    )
    _set_nullable(
        "eligibility_verification",
        "canonicalization_version",
        nullable=False,
        existing_type=sa.String(length=32),
    )
    _set_nullable(
        "eligibility_verification",
        "verification_method",
        nullable=False,
        existing_type=sa.String(length=64),
    )
    _set_nullable(
        "eligibility_verification",
        "attempt_count",
        nullable=False,
        existing_type=sa.Integer(),
    )
    _set_nullable(
        "eligibility_verification",
        "created_at",
        nullable=False,
        existing_type=sa.DateTime(timezone=True),
    )
    _set_nullable(
        "eligibility_verification",
        "verified_at",
        nullable=True,
        existing_type=sa.DateTime(timezone=True),
    )

    _add_column_if_missing(
        "search_job",
        sa.Column("canonical_input_url_ciphertext", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "search_job",
        sa.Column("input_provider_id", sa.String(length=80), nullable=True),
    )
    _add_column_if_missing(
        "search_job",
        sa.Column("canonicalization_version", sa.String(length=32), nullable=True),
    )
    _add_column_if_missing(
        "search_job",
        sa.Column("eligibility_verification_id", sa.String(length=36), nullable=True),
    )
    _add_column_if_missing(
        "search_job",
        sa.Column("purpose", sa.String(length=64), nullable=True),
    )

    search_job = sa.table(
        "search_job",
        sa.column("user_id", sa.String()),
        sa.column("normalized_identifier_hmac", sa.String()),
        sa.column("input_provider_id", sa.String()),
        sa.column("canonicalization_version", sa.String()),
        sa.column("eligibility_verification_id", sa.String()),
        sa.column("purpose", sa.String()),
    )
    op.execute(
        search_job.update()
        .where(search_job.c.input_provider_id.is_(None))
        .values(input_provider_id="fixture_primary_v1")
    )
    op.execute(
        search_job.update()
        .where(search_job.c.canonicalization_version.is_(None))
        .values(canonicalization_version="profile-url-v1")
    )
    op.execute(
        search_job.update().where(search_job.c.purpose.is_(None)).values(purpose="self_audit")
    )
    op.execute(
        sa.text(
            """
            UPDATE search_job AS search
            SET eligibility_verification_id = (
                SELECT verification.id
                FROM eligibility_verification AS verification
                WHERE verification.user_id = search.user_id
                  AND verification.identifier_hmac =
                      search.normalized_identifier_hmac
                ORDER BY verification.verified_at DESC NULLS LAST,
                         verification.id
                LIMIT 1
            )
            WHERE search.eligibility_verification_id IS NULL
            """
        )
    )
    missing_verification_count = op.get_bind().scalar(
        sa.select(sa.func.count())
        .select_from(search_job)
        .where(search_job.c.eligibility_verification_id.is_(None))
    )
    if missing_verification_count:
        raise RuntimeError(
            "Cannot migrate search_job rows without a matching eligibility verification"
        )

    _set_nullable(
        "search_job",
        "input_provider_id",
        nullable=False,
        existing_type=sa.String(length=80),
    )
    _set_nullable(
        "search_job",
        "canonicalization_version",
        nullable=False,
        existing_type=sa.String(length=32),
    )
    _set_nullable(
        "search_job",
        "eligibility_verification_id",
        nullable=False,
        existing_type=sa.String(length=36),
    )
    _set_nullable(
        "search_job",
        "purpose",
        nullable=False,
        existing_type=sa.String(length=64),
    )
    _set_nullable(
        "search_job",
        "fixture_key",
        nullable=True,
        existing_type=sa.String(length=64),
    )

    if not _has_foreign_key("search_job", ("eligibility_verification_id",)):
        op.create_foreign_key(
            "fk_search_job_eligibility_verification_id",
            "search_job",
            "eligibility_verification",
            ["eligibility_verification_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    eligibility_index = "ix_search_job_eligibility_verification_id"
    if not _has_index("search_job", eligibility_index):
        op.create_index(
            eligibility_index,
            "search_job",
            ["eligibility_verification_id"],
            unique=False,
        )

    _add_column_if_missing(
        "source_document",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    _drop_column_if_present("source_document", "expires_at")

    eligibility_index = "ix_search_job_eligibility_verification_id"
    if _has_index("search_job", eligibility_index):
        op.drop_index(eligibility_index, table_name="search_job")
    for foreign_key in _foreign_keys("search_job"):
        constrained_columns = tuple(str(column) for column in foreign_key["constrained_columns"])
        if constrained_columns == ("eligibility_verification_id",):
            constraint_name = foreign_key.get("name")
            if constraint_name:
                op.drop_constraint(
                    str(constraint_name),
                    "search_job",
                    type_="foreignkey",
                )

    if "fixture_key" in _columns("search_job"):
        op.execute(
            sa.text(
                """
                UPDATE search_job
                SET fixture_key = 'unknown'
                WHERE fixture_key IS NULL
                """
            )
        )
        _set_nullable(
            "search_job",
            "fixture_key",
            nullable=False,
            existing_type=sa.String(length=64),
        )

    for column_name in (
        "purpose",
        "eligibility_verification_id",
        "canonicalization_version",
        "input_provider_id",
        "canonical_input_url_ciphertext",
    ):
        _drop_column_if_present("search_job", column_name)

    if "verified_at" in _columns("eligibility_verification"):
        op.execute(
            sa.text(
                """
                UPDATE eligibility_verification
                SET verified_at = COALESCE(
                    verified_at,
                    control_verified_at,
                    reviewed_at,
                    created_at,
                    CURRENT_TIMESTAMP
                )
                WHERE verified_at IS NULL
                """
            )
        )
        _set_nullable(
            "eligibility_verification",
            "verified_at",
            nullable=False,
            existing_type=sa.DateTime(timezone=True),
        )

    for column_name in (
        "review_code",
        "reviewer_id",
        "reviewed_at",
        "control_verified_at",
        "created_at",
        "last_checked_at",
        "attempt_count",
        "review_expires_at",
        "challenge_expires_at",
        "challenge_token_hmac",
        "verification_method",
        "provider_subject_hmac",
        "canonical_url_ciphertext",
        "canonicalization_version",
        "provider_id",
    ):
        _drop_column_if_present("eligibility_verification", column_name)
