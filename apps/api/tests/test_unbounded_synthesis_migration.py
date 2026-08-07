from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from apps.api.app.core.config import get_settings


def _deadline_column(engine: sa.Engine) -> dict[str, object]:
    return next(
        column
        for column in sa.inspect(engine).get_columns("provider_run")
        if column["name"] == "deadline_at"
    )


def test_unbounded_synthesis_migration_round_trip(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    provider_run = sa.Table(
        "provider_run",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    alembic_version = sa.Table(
        "alembic_version",
        metadata,
        sa.Column("version_num", sa.String(32), primary_key=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            alembic_version.insert().values(version_num="0005_grounded_synthesis")
        )

    config = Config("alembic.ini")
    command.upgrade(config, "head")
    assert _deadline_column(engine)["nullable"] is True

    expires_at = datetime(2026, 8, 4, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            provider_run.insert().values(
                id="synthesis-run",
                deadline_at=None,
                expires_at=expires_at,
            )
        )

    command.downgrade(config, "0005_grounded_synthesis")
    assert _deadline_column(engine)["nullable"] is False
    with engine.connect() as connection:
        restored_deadline = connection.scalar(
            sa.select(provider_run.c.deadline_at).where(
                provider_run.c.id == "synthesis-run"
            )
        )
    assert restored_deadline == expires_at.replace(tzinfo=None)

    get_settings.cache_clear()
