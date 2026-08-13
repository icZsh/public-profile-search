import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from apps.api.app.core.config import get_settings


def _column(engine: sa.Engine) -> dict[str, object] | None:
    return next(
        (
            column
            for column in sa.inspect(engine).get_columns("search_job")
            if column["name"] == "synthesis_model"
        ),
        None,
    )


def test_footprint_synthesis_model_migration_round_trip(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    sa.Table(
        "search_job",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    alembic_version = sa.Table(
        "alembic_version",
        metadata,
        sa.Column("version_num", sa.String(64), primary_key=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            alembic_version.insert().values(version_num="0006_unbounded_synthesis")
        )

    config = Config("alembic.ini")
    command.upgrade(config, "head")
    upgraded = _column(engine)
    assert upgraded is not None
    assert upgraded["nullable"] is True
    assert upgraded["type"].length == 80

    command.downgrade(config, "0006_unbounded_synthesis")
    assert _column(engine) is None

    get_settings.cache_clear()
