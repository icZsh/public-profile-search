import json
from pathlib import Path

from apps.api.app.safe_fetch.service import SafeFetchGateway
from workers.providers.base import ProviderDocument, ProviderResult
from workers.providers.github_public import run_github_provider

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIRECTORY = ROOT / "fixtures" / "provider-responses"
PROVIDER_FIXTURES = {
    "fixture_primary_v1": "primary-success.json",
    "fixture_linked_v1": "linked-success.json",
}


def run_fixture_provider(provider_id: str) -> ProviderResult:
    filename = PROVIDER_FIXTURES.get(provider_id)
    if not filename:
        return ProviderResult(
            provider_id=provider_id,
            status="provider_error",
            documents=(),
            error_code="provider_not_registered",
        )
    payload = json.loads((FIXTURE_DIRECTORY / filename).read_text())
    documents = tuple(
        ProviderDocument(
            canonical_url=item["canonical_url"],
            publisher=item["publisher"],
            title=item["title"],
            lineage_key=item["lineage_key"],
            source_type=item["source_type"],
            trust_class=item["trust_class"],
            excerpt=item["excerpt"],
            span_locator=item["span_locator"],
            extracted_fields=item["extracted_fields"],
        )
        for item in payload["documents"]
    )
    return ProviderResult(
        provider_id=payload["provider_id"],
        status=payload["status"],
        documents=documents,
    )


def run_provider(
    provider_id: str,
    *,
    canonical_profile_url: str,
    settings,
    safe_fetch_gateway: SafeFetchGateway | None = None,
) -> ProviderResult:
    if provider_id in PROVIDER_FIXTURES:
        return run_fixture_provider(provider_id)
    if provider_id == "github_public_profile_v1":
        if not settings.github_provider_enabled:
            return ProviderResult(
                provider_id=provider_id,
                status="skipped_circuit_open",
                documents=(),
                error_code="github_provider_disabled",
            )
        gateway = safe_fetch_gateway or SafeFetchGateway(settings)
        return run_github_provider(
            canonical_profile_url=canonical_profile_url,
            gateway=gateway,
            hmac_key=settings.prototype_hmac_key,
        )
    return ProviderResult(
        provider_id=provider_id,
        status="provider_error",
        documents=(),
        error_code="provider_not_registered",
    )
