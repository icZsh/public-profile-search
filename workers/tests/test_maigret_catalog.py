import hashlib
import importlib.metadata
import importlib.resources

from apps.api.app.services.discovery_jobs import load_catalog_manifest
from workers.providers.maigret_catalog import build_maigret_adapter


def test_promoted_quick_catalog_matches_installed_maigret_artifact():
    manifest = load_catalog_manifest("config/maigret-catalog-v0.6.3.json")
    profile = manifest.profile("quick")
    resource = importlib.resources.files("maigret").joinpath("resources/data.json")

    assert importlib.metadata.version("maigret") == manifest.package_version == "0.6.3"
    assert hashlib.sha256(resource.read_bytes()).hexdigest() == manifest.database_checksum
    assert len(profile.site_names) == 20
    assert profile.shard_size == 7
    assert {"Instagram", "Threads", "Clubhouse"}.issubset(profile.site_names)

    for index in range(0, len(profile.site_names), profile.shard_size):
        site_names = list(profile.site_names[index : index + profile.shard_size])
        adapter = build_maigret_adapter(
            manifest=manifest.raw,
            site_names=site_names,
            catalog_snapshot_id=manifest.manifest_checksum,
            timeout_seconds=profile.timeout_seconds,
            max_connections=profile.max_connections,
            maigret_id_type="username",
        )
        assert tuple(adapter._catalog) == tuple(site_names)
