import hashlib
import importlib.metadata
import importlib.resources

from apps.api.app.services.discovery_jobs import load_catalog_manifest
from workers.providers.maigret_catalog import build_maigret_adapter


def test_promoted_catalog_profiles_match_installed_maigret_artifact():
    manifest = load_catalog_manifest("config/maigret-catalog-v0.6.3.json")
    quick = manifest.profile("quick")
    deep = manifest.profile("deep")
    resource = importlib.resources.files("maigret").joinpath("resources/data.json")

    assert importlib.metadata.version("maigret") == manifest.package_version == "0.6.3"
    assert hashlib.sha256(resource.read_bytes()).hexdigest() == manifest.database_checksum
    assert len(quick.site_names) == 20
    assert quick.shard_size == 7
    assert {"Instagram", "Threads", "Clubhouse"}.issubset(quick.site_names)
    assert len(deep.site_names) == len(set(deep.site_names)) == 56
    assert deep.shard_size == 7
    assert deep.site_names[: len(quick.site_names)] == quick.site_names
    assert {"Facebook", "Bluesky", "Docker Hub", "mastodon.social"}.issubset(
        set(deep.site_names) - set(quick.site_names)
    )

    for profile, expected_shard_count in ((quick, 3), (deep, 8)):
        shards = [
            profile.site_names[index : index + profile.shard_size]
            for index in range(0, len(profile.site_names), profile.shard_size)
        ]
        assert len(shards) == expected_shard_count
        for shard in shards:
            site_names = list(shard)
            adapter = build_maigret_adapter(
                manifest=manifest.raw,
                site_names=site_names,
                catalog_snapshot_id=manifest.manifest_checksum,
                timeout_seconds=profile.timeout_seconds,
                max_connections=profile.max_connections,
                maigret_id_type="username",
            )
            assert tuple(adapter._catalog) == tuple(site_names)
