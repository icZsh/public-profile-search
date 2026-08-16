import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_history_migration_renames_lineage_and_adds_indexes(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'history-migration.db'}")
    metadata = sa.MetaData()
    search_job = sa.Table(
        "search_job",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("job_kind", sa.String(40), nullable=False),
        sa.Column("normalized_identifier_hmac", sa.String(64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("retry_of_job_id", sa.String(36), nullable=True),
    )
    outbox = sa.Table(
        "outbox_message",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dispatched_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    sa.Index("ix_outbox_undispatched", outbox.c.dispatched_at, outbox.c.created_at)
    metadata.create_all(engine)

    migration = importlib.import_module(
        "migrations.versions.0008_footprint_history"
    )
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()

        inspector = sa.inspect(connection)
        search_columns = {
            str(column["name"]): column
            for column in inspector.get_columns(search_job.name)
        }
        assert "retry_of_job_id" not in search_columns
        assert search_columns["refresh_of_job_id"]["nullable"] is True
        assert search_columns["history_reuse_policy"]["nullable"] is True
        assert any(
            tuple(foreign_key["constrained_columns"]) == ("refresh_of_job_id",)
            and foreign_key["referred_table"] == "search_job"
            and foreign_key["options"].get("ondelete") == "SET NULL"
            for foreign_key in inspector.get_foreign_keys(search_job.name)
        )
        search_indexes = {
            str(index["name"]): tuple(index["column_names"])
            for index in inspector.get_indexes(search_job.name)
        }
        assert search_indexes["ix_search_job_owner_history"] == (
            "user_id",
            "job_kind",
            "accepted_at",
            "id",
        )
        assert search_indexes["ix_search_job_owner_exact_seed"] == (
            "user_id",
            "job_kind",
            "normalized_identifier_hmac",
            "accepted_at",
            "id",
        )
        assert search_indexes["ix_search_job_expiry"] == ("expires_at", "id")
        assert search_indexes["ix_search_job_refresh_lineage"] == (
            "refresh_of_job_id",
        )

        outbox_columns = {
            str(column["name"]): column
            for column in inspector.get_columns(outbox.name)
        }
        assert outbox_columns["priority"]["nullable"] is False
        outbox_indexes = {
            str(index["name"]): tuple(index["column_names"])
            for index in inspector.get_indexes(outbox.name)
        }
        assert outbox_indexes["ix_outbox_undispatched"] == (
            "dispatched_at",
            "priority",
            "created_at",
            "id",
        )

        migration.downgrade()
        downgraded = sa.inspect(connection)
        assert "retry_of_job_id" in {
            str(column["name"])
            for column in downgraded.get_columns(search_job.name)
        }
        assert "refresh_of_job_id" not in {
            str(column["name"])
            for column in downgraded.get_columns(search_job.name)
        }
        assert "priority" not in {
            str(column["name"])
            for column in downgraded.get_columns(outbox.name)
        }
