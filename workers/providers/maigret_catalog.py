import hashlib
import importlib.metadata
import importlib.resources
import json
from collections.abc import Mapping

from maigret import search as maigret_search
from maigret.sites import MaigretDatabase

from workers.providers.maigret_adapter import (
    MaigretDiscoveryAdapter,
    MaigretScanConfig,
)


class MaigretCatalogError(RuntimeError):
    pass


def build_maigret_adapter(
    *,
    manifest: Mapping[str, object],
    site_names: list[str],
    catalog_snapshot_id: str,
    timeout_seconds: int,
    max_connections: int,
    maigret_id_type: str,
) -> MaigretDiscoveryAdapter:
    expected_version = str(manifest.get("package_version", ""))
    installed_version = importlib.metadata.version("maigret")
    if installed_version != expected_version:
        raise MaigretCatalogError(
            f"Maigret version mismatch: expected {expected_version}, got {installed_version}"
        )

    resource = importlib.resources.files("maigret").joinpath("resources/data.json")
    raw_bytes = resource.read_bytes()
    actual_checksum = hashlib.sha256(raw_bytes).hexdigest()
    expected_checksum = str(manifest.get("database_sha256", ""))
    if actual_checksum != expected_checksum:
        raise MaigretCatalogError("The installed Maigret catalog checksum is not promoted.")

    try:
        database = MaigretDatabase().load_from_str(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise MaigretCatalogError("The installed Maigret catalog is invalid.") from exc

    selected = database.ranked_sites_dict(
        names=site_names,
        disabled=False,
        id_type=maigret_id_type,
        excluded_tags=["tor", "i2p", "dns"],
    )
    exact_selected = {
        name: selected[name]
        for name in site_names
        if name in selected
        and not getattr(selected[name], "disabled", False)
        and getattr(selected[name], "protocol", "") not in {"tor", "i2p", "dns"}
    }
    missing = sorted(set(site_names) - set(exact_selected))
    if missing:
        raise MaigretCatalogError(
            f"Promoted catalog sites are unavailable for {maigret_id_type}: {', '.join(missing)}"
        )

    return MaigretDiscoveryAdapter(
        search_function=maigret_search,
        catalog=exact_selected,
        catalog_snapshot_id=catalog_snapshot_id,
        config=MaigretScanConfig(
            timeout_seconds=timeout_seconds,
            max_connections=max_connections,
            max_sites=len(exact_selected),
        ),
    )
