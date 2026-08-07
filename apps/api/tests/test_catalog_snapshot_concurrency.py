from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from apps.api.app.models.entities import MaigretCatalogSnapshot
from apps.api.app.services.discovery_jobs import (
    _ensure_catalog_snapshot,
    _is_manifest_checksum_unique_violation,
    load_catalog_manifest,
)


def test_catalog_snapshot_first_writer_is_replayed_across_sessions(
    app,
    client,
    settings,
    clock,
):
    manifest = load_catalog_manifest(settings.maigret_catalog_manifest)
    start = Barrier(2)

    def create_snapshot() -> str:
        with app.state.session_factory() as session, session.begin():
            start.wait(timeout=5)
            snapshot = _ensure_catalog_snapshot(
                session,
                manifest=manifest,
                now=clock.now(),
            )
            return snapshot.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        snapshot_ids = list(executor.map(lambda _: create_snapshot(), range(2)))

    assert len(set(snapshot_ids)) == 1

    with app.state.session_factory() as verification_session:
        assert (
            verification_session.scalar(
                select(func.count(MaigretCatalogSnapshot.id)).where(
                    MaigretCatalogSnapshot.manifest_checksum
                    == manifest.manifest_checksum
                )
            )
            == 1
        )


def test_catalog_snapshot_conflict_does_not_classify_unrelated_integrity_error():
    error = IntegrityError(
        "INSERT",
        {},
        Exception(
            "UNIQUE constraint failed: "
            "maigret_catalog_snapshot.database_checksum"
        ),
    )

    assert not _is_manifest_checksum_unique_violation(error)
