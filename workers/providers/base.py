from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderDocument:
    canonical_url: str
    publisher: str
    title: str
    lineage_key: str
    source_type: str
    trust_class: str
    excerpt: str
    span_locator: dict[str, object]
    extracted_fields: dict[str, object]


@dataclass(frozen=True)
class ProviderResult:
    provider_id: str
    status: str
    documents: tuple[ProviderDocument, ...]
    error_code: str | None = None
    subject_identifier: str | None = None
