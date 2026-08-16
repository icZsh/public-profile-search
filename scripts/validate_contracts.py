import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _operations(openapi: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    for path, path_item in openapi["paths"].items():
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if operation:
                yield path, method, operation


def _resolve_ref(document: dict[str, Any], ref: str) -> Any:
    assert ref.startswith("#/"), f"Only local OpenAPI references are allowed: {ref}"
    value: Any = document
    for part in ref[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def _refs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref":
                assert isinstance(child, str)
                yield child
            else:
                yield from _refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _refs(child)


def _parameter_names(
    openapi: dict[str, Any],
    path: str,
    operation: dict[str, Any],
) -> set[str]:
    parameters = [
        *openapi["paths"][path].get("parameters", []),
        *operation.get("parameters", []),
    ]
    resolved = [
        _resolve_ref(openapi, parameter["$ref"]) if "$ref" in parameter else parameter
        for parameter in parameters
    ]
    return {parameter["name"] for parameter in resolved}


def _assert_security_and_headers(openapi: dict[str, Any]) -> None:
    owner_operations = {
        ("/v1/prototype-config", "get"),
        ("/v1/eligibility-verifications", "post"),
        ("/v1/eligibility-verifications/{verification_id}", "get"),
        ("/v1/eligibility-verifications/{verification_id}/complete", "post"),
        ("/v1/search-jobs", "post"),
        ("/v1/search-jobs/{job_id}", "get"),
        ("/v1/search-jobs/{job_id}", "delete"),
        ("/v1/search-jobs/{job_id}/events", "get"),
        ("/v1/search-jobs/{job_id}/brief", "get"),
        ("/v1/search-jobs/{job_id}/evidence", "get"),
        ("/v1/footprint-jobs", "get"),
        ("/v1/footprint-jobs", "post"),
        ("/v1/footprint-jobs", "delete"),
        ("/v1/footprint-jobs/{job_id}", "get"),
        ("/v1/footprint-jobs/{job_id}", "delete"),
        ("/v1/footprint-jobs/{job_id}/history", "get"),
        ("/v1/footprint-jobs/{job_id}/refresh", "post"),
        ("/v1/footprint-jobs/{job_id}/cancel", "post"),
        ("/v1/footprint-jobs/{job_id}/candidates", "get"),
        ("/v1/footprint-jobs/{job_id}/anchor", "post"),
        ("/v1/footprint-jobs/{job_id}/brief", "get"),
        ("/v1/footprint-jobs/{job_id}/evidence", "get"),
        ("/v1/footprint-jobs/{job_id}/events", "get"),
    }
    admin_operations = {
        ("/v1/prototype/eligibility-verifications/{verification_id}", "get"),
        (
            "/v1/prototype/eligibility-verifications/{verification_id}/decision",
            "post",
        ),
        ("/v1/prototype/suppressions", "post"),
    }

    actual_operations = {
        (path, method): operation for path, method, operation in _operations(openapi)
    }
    for key in owner_operations:
        operation = actual_operations[key]
        assert operation["security"] == [{"prototypeAuth": []}], key
        assert "X-Prototype-User" in _parameter_names(openapi, key[0], operation), key

    for key in admin_operations:
        operation = actual_operations[key]
        assert operation["security"] == [{"prototypeAdminAuth": []}], key
        assert "X-Prototype-User" not in _parameter_names(openapi, key[0], operation), key

    protected = owner_operations | admin_operations
    for path, method, operation in _operations(openapi):
        if path not in {"/healthz", "/readyz"}:
            assert (path, method) in protected, f"Unclassified protected route: {method} {path}"
            assert operation.get("security"), f"Missing security: {method} {path}"


def _assert_error_registry(errors: dict[str, Any]) -> None:
    required_codes = {
        "authentication_required",
        "unsupported_provider",
        "invalid_request",
        "idempotency_conflict",
        "anchor_candidate_not_found",
        "anchor_candidate_invalid",
        "anchor_candidate_not_hypothesis",
        "anchor_selection_not_required",
        "anchor_selection_closed",
        "anchor_selection_expired",
        "anchor_selection_unavailable",
        "job_not_found",
        "job_not_ready",
        "result_unavailable",
        "prototype_disabled",
        "provider_disabled",
        "provider_rate_limited",
        "verification_not_found",
        "verification_expired",
        "verification_unavailable",
        "verification_cooldown",
        "service_unavailable",
    }
    assert errors["version"] == 2
    assert required_codes <= set(errors["errors"])
    for code, definition in errors["errors"].items():
        assert code.replace("_", "").islower(), code
        statuses = definition["http_status"]
        if isinstance(statuses, int):
            statuses = [statuses]
        assert statuses and all(
            isinstance(status, int) and 400 <= status <= 599 for status in statuses
        )
        assert isinstance(definition["message"], str) and definition["message"].strip()


def main() -> None:
    openapi = yaml.safe_load((ROOT / "contracts" / "openapi.yaml").read_text())
    events = json.loads((ROOT / "contracts" / "events.schema.json").read_text())
    errors = yaml.safe_load((ROOT / "contracts" / "error-codes.yaml").read_text())
    generated_typescript = (
        ROOT / "packages" / "generated-api-client" / "src" / "index.ts"
    ).read_text()

    assert openapi["openapi"].startswith("3.1")
    assert openapi["info"]["version"] == "0.2.0"
    required_paths = {
        "/v1/eligibility-verifications",
        "/v1/eligibility-verifications/{verification_id}",
        "/v1/eligibility-verifications/{verification_id}/complete",
        "/v1/prototype/eligibility-verifications/{verification_id}",
        "/v1/prototype/eligibility-verifications/{verification_id}/decision",
        "/v1/search-jobs",
        "/v1/search-jobs/{job_id}/brief",
        "/v1/footprint-jobs",
        "/v1/footprint-jobs/{job_id}",
        "/v1/footprint-jobs/{job_id}/history",
        "/v1/footprint-jobs/{job_id}/refresh",
        "/v1/footprint-jobs/{job_id}/cancel",
        "/v1/footprint-jobs/{job_id}/candidates",
        "/v1/footprint-jobs/{job_id}/anchor",
        "/v1/footprint-jobs/{job_id}/brief",
        "/v1/footprint-jobs/{job_id}/evidence",
        "/v1/footprint-jobs/{job_id}/events",
        "/v1/prototype/suppressions",
    }
    assert required_paths <= set(openapi["paths"])

    operation_ids = [operation["operationId"] for _path, _method, operation in _operations(openapi)]
    assert len(operation_ids) == len(set(operation_ids)), "operationId values must be unique"
    actual_operations = {
        (path, method): operation for path, method, operation in _operations(openapi)
    }
    expected_footprint_operations = {
        ("/v1/footprint-jobs", "get"): "listFootprintHistory",
        ("/v1/footprint-jobs", "post"): "createFootprintJob",
        ("/v1/footprint-jobs", "delete"): "clearFootprintHistory",
        ("/v1/footprint-jobs/{job_id}", "get"): "getFootprintJob",
        ("/v1/footprint-jobs/{job_id}", "delete"): "deleteFootprintJob",
        ("/v1/footprint-jobs/{job_id}/history", "get"): "listFootprintJobHistory",
        ("/v1/footprint-jobs/{job_id}/refresh", "post"): "refreshFootprintJob",
        ("/v1/footprint-jobs/{job_id}/cancel", "post"): "cancelFootprintJob",
        ("/v1/footprint-jobs/{job_id}/candidates", "get"): "listFootprintCandidates",
        ("/v1/footprint-jobs/{job_id}/anchor", "post"): "selectFootprintAnchor",
        ("/v1/footprint-jobs/{job_id}/brief", "get"): "getFootprintBrief",
        ("/v1/footprint-jobs/{job_id}/evidence", "get"): "getFootprintEvidence",
        ("/v1/footprint-jobs/{job_id}/events", "get"): "streamFootprintJobEvents",
    }
    assert {
        key: actual_operations[key]["operationId"] for key in expected_footprint_operations
    } == expected_footprint_operations
    assert "Idempotency-Key" in _parameter_names(
        openapi,
        "/v1/footprint-jobs",
        actual_operations[("/v1/footprint-jobs", "post")],
    )
    assert "Idempotency-Key" in _parameter_names(
        openapi,
        "/v1/footprint-jobs/{job_id}/refresh",
        actual_operations[("/v1/footprint-jobs/{job_id}/refresh", "post")],
    )
    assert _parameter_names(
        openapi,
        "/v1/footprint-jobs",
        actual_operations[("/v1/footprint-jobs", "get")],
    ) >= {"X-Prototype-User", "q", "cursor", "limit"}
    assert _parameter_names(
        openapi,
        "/v1/footprint-jobs/{job_id}/history",
        actual_operations[("/v1/footprint-jobs/{job_id}/history", "get")],
    ) >= {"X-Prototype-User", "job_id", "cursor", "limit"}
    assert _parameter_names(
        openapi,
        "/v1/footprint-jobs",
        actual_operations[("/v1/footprint-jobs", "delete")],
    ) >= {"X-Prototype-User", "limit"}
    for ref in _refs(openapi):
        _resolve_ref(openapi, ref)

    schemes = openapi["components"]["securitySchemes"]
    assert schemes["prototypeAuth"]["name"] == "X-Prototype-Token"
    assert schemes["prototypeAdminAuth"]["name"] == "X-Prototype-Admin-Token"
    _assert_security_and_headers(openapi)

    schemas = openapi["components"]["schemas"]
    config_required = set(schemas["PrototypeConfig"]["required"])
    assert {"allowed_profile_hosts", "github_provider_enabled"} <= config_required
    assert schemas["PrototypeConfig"]["properties"]["allowed_profile_hosts"]["const"] == [
        "github.com"
    ]

    eligibility = schemas["EligibilityVerification"]
    assert {
        "challenge_value",
        "review_expires_at",
        "eligibility_reference_id",
        "eligibility_expires_at",
        "attempts_remaining",
    } <= set(eligibility["required"])
    assert eligibility["properties"]["status"]["enum"] == [
        "pending_control",
        "review_pending",
        "eligible",
        "expired",
        "unavailable",
    ]
    assert eligibility["properties"]["provider_id"]["const"] == "github_public_profile_v1"

    decision_variants = schemas["EligibilityDecisionRequest"]["oneOf"]
    assert {
        (
            variant["properties"]["decision"]["const"],
            variant["properties"]["review_code"]["const"],
        )
        for variant in decision_variants
    } == {
        ("approve", "adult_public_professional_context_confirmed"),
        ("deny", "unable_to_confirm_scope"),
    }
    for variant in decision_variants:
        assert set(variant["required"]) == {"decision", "review_code", "reviewer_id"}

    footprint_seed_variants = schemas["FootprintSeed"]["oneOf"]
    assert {variant["properties"]["kind"]["const"] for variant in footprint_seed_variants} == {
        "platform_identifier",
        "bare_handle",
        "profile_url",
    }
    platform_seed = next(
        variant
        for variant in footprint_seed_variants
        if variant["properties"]["kind"]["const"] == "platform_identifier"
    )
    bare_seed = next(
        variant
        for variant in footprint_seed_variants
        if variant["properties"]["kind"]["const"] == "bare_handle"
    )
    profile_url_seed = next(
        variant
        for variant in footprint_seed_variants
        if variant["properties"]["kind"]["const"] == "profile_url"
    )
    assert "platform" in platform_seed["required"]
    assert "platform" not in bare_seed["required"]
    assert bare_seed["properties"]["platform"]["type"] == "null"
    assert set(profile_url_seed["required"]) == {"kind", "profile_url"}
    assert profile_url_seed["properties"]["profile_url"]["format"] == "uri"
    assert "platform" not in profile_url_seed["required"]
    assert "identifier" not in profile_url_seed["required"]
    assert all(
        variant["properties"]["identifier_type"]["const"] == "handle"
        for variant in footprint_seed_variants
    )
    footprint_seed_response_variants = schemas["FootprintSeedResponse"]["oneOf"]
    assert {
        variant["properties"]["kind"]["const"]
        for variant in footprint_seed_response_variants
    } == {
        "platform_identifier",
        "bare_handle",
        "profile_url",
    }
    normalized_profile_url_seed = next(
        variant
        for variant in footprint_seed_response_variants
        if variant["properties"]["kind"]["const"] == "profile_url"
    )
    assert set(normalized_profile_url_seed["required"]) == {
        "kind",
        "profile_url",
        "platform",
        "identifier_type",
        "identifier",
    }
    assert (
        schemas["CreateFootprintJobRequest"]["properties"]["seed"]["$ref"]
        == "#/components/schemas/FootprintSeed"
    )
    footprint_search_mode = schemas["CreateFootprintJobRequest"]["properties"]["search_mode"]
    assert footprint_search_mode["enum"] == ["quick", "deep"]
    assert footprint_search_mode["default"] == "quick"
    synthesis_models = [
        "openai/gpt-5.6-luna",
        "openai/gpt-5.4-nano",
        "openai/gpt-5.4-mini",
        "openai/gpt-oss-120b",
        "deepseek/deepseek-v4-flash-0731",
        "qwen/qwen3.5-35b-a3b",
        "z-ai/glm-5.2",
    ]
    assert schemas["FootprintSynthesisModel"]["enum"] == synthesis_models
    create_footprint_job = schemas["CreateFootprintJobRequest"]
    assert create_footprint_job["properties"]["synthesis_model"]["$ref"] == (
        "#/components/schemas/FootprintSynthesisModel"
    )
    synthesis_dependency = create_footprint_job["dependentSchemas"]["synthesis_model"]
    assert synthesis_dependency["required"] == ["search_mode"]
    assert synthesis_dependency["properties"]["search_mode"]["const"] == "deep"
    history_policy = create_footprint_job["properties"]["history_policy"]
    assert history_policy["enum"] == ["new_job", "prefer_existing"]
    assert history_policy["default"] == "new_job"
    assert "history_policy" not in create_footprint_job["required"]

    footprint_create_responses = actual_operations[("/v1/footprint-jobs", "post")]["responses"]
    assert {
        status: footprint_create_responses[status]["content"]["application/json"]["schema"]["$ref"]
        for status in ("200", "202")
    } == {
        "200": "#/components/schemas/FootprintJob",
        "202": "#/components/schemas/FootprintJob",
    }

    footprint_job = schemas["FootprintJob"]
    assert {
        "exploration_status",
        "deep_progress",
        "seed",
        "search_mode",
        "synthesis_model",
        "coverage",
        "catalog",
        "events_url",
        "candidates_url",
        "expires_at",
        "refresh_of_job_id",
    } <= set(footprint_job["required"])
    assert footprint_job["properties"]["status"]["enum"] == [
        "queued",
        "discovering",
        "ready",
        "ready_partial",
        "no_candidates",
        "failed",
        "cancelled",
    ]
    assert footprint_job["properties"]["search_mode"]["enum"] == [
        "quick",
        "deep",
        None,
    ]
    assert footprint_job["properties"]["synthesis_model"]["anyOf"] == [
        {"$ref": "#/components/schemas/FootprintSynthesisModel"},
        {"type": "null"},
    ]
    assert (
        footprint_job["properties"]["seed"]["$ref"]
        == "#/components/schemas/FootprintSeedResponse"
    )
    assert footprint_job["properties"]["exploration_status"]["enum"] == [
        "idle",
        "running",
        "awaiting_anchor",
        "completed",
        "cancelled",
    ]
    assert footprint_job["properties"]["deep_progress"]["anyOf"] == [
        {"$ref": "#/components/schemas/FootprintDeepProgress"},
        {"type": "null"},
    ]
    assert footprint_job["properties"]["expires_at"] == {
        "type": "string",
        "format": "date-time",
    }
    assert footprint_job["properties"]["refresh_of_job_id"] == {
        "type": ["string", "null"],
        "format": "uuid",
    }

    history_seed = schemas["FootprintHistorySeed"]
    assert set(history_seed["required"]) == {"kind", "platform", "identifier"}
    assert history_seed["properties"]["kind"]["enum"] == [
        "platform_identifier",
        "bare_handle",
    ]
    assert history_seed["properties"]["platform"]["type"] == ["string", "null"]

    history_run = schemas["FootprintHistoryRun"]
    assert set(history_run["required"]) == {
        "job_id",
        "status",
        "search_mode",
        "synthesis_model",
        "accepted_at",
        "finished_at",
        "expires_at",
        "candidate_count",
        "result_available",
        "refresh_of_job_id",
    }
    assert history_run["properties"]["search_mode"]["enum"] == ["quick", "deep"]
    assert history_run["properties"]["synthesis_model"]["anyOf"] == [
        {"$ref": "#/components/schemas/FootprintSynthesisModel"},
        {"type": "null"},
    ]
    assert history_run["properties"]["finished_at"] == {
        "type": ["string", "null"],
        "format": "date-time",
    }
    assert history_run["properties"]["candidate_count"]["minimum"] == 0

    history_group = schemas["FootprintHistoryGroup"]
    assert set(history_group["required"]) == {
        "representative_job_id",
        "seed",
        "latest_run",
        "run_count",
    }
    assert history_group["properties"]["seed"]["$ref"] == (
        "#/components/schemas/FootprintHistorySeed"
    )
    assert history_group["properties"]["latest_run"]["$ref"] == (
        "#/components/schemas/FootprintHistoryRun"
    )
    assert history_group["properties"]["run_count"]["minimum"] == 1

    for page_name, item_ref in (
        ("FootprintHistoryGroupPage", "#/components/schemas/FootprintHistoryGroup"),
        ("FootprintHistoryRunPage", "#/components/schemas/FootprintHistoryRun"),
    ):
        page = schemas[page_name]
        assert set(page["required"]) == {"items", "next_cursor"}
        assert page["properties"]["items"]["items"]["$ref"] == item_ref
        assert page["properties"]["next_cursor"]["type"] == ["string", "null"]

    clear_history = schemas["ClearFootprintHistoryResponse"]
    assert set(clear_history["required"]) == {"deleted_count", "has_more"}
    assert clear_history["properties"]["deleted_count"]["minimum"] == 0
    assert clear_history["properties"]["has_more"]["type"] == "boolean"

    history_response_refs = {
        ("/v1/footprint-jobs", "get", "200"): ("#/components/schemas/FootprintHistoryGroupPage"),
        ("/v1/footprint-jobs", "delete", "200"): (
            "#/components/schemas/ClearFootprintHistoryResponse"
        ),
        ("/v1/footprint-jobs/{job_id}/history", "get", "200"): (
            "#/components/schemas/FootprintHistoryRunPage"
        ),
        ("/v1/footprint-jobs/{job_id}/refresh", "post", "202"): (
            "#/components/schemas/FootprintJob"
        ),
    }
    for (path, method, status), expected_ref in history_response_refs.items():
        assert (
            actual_operations[(path, method)]["responses"][status]["content"]["application/json"][
                "schema"
            ]["$ref"]
            == expected_ref
        )

    generated_history_fragments = {
        'export type FootprintHistoryPolicy = "new_job" | "prefer_existing";',
        "history_policy?: FootprintHistoryPolicy;",
        "expires_at: string;",
        "refresh_of_job_id: string | null;",
        "export interface FootprintHistorySeed",
        "export interface FootprintHistoryRun",
        "export interface FootprintHistoryGroup",
        "export interface FootprintHistoryGroupPage",
        "export interface FootprintHistoryRunPage",
        "export interface ClearFootprintHistoryResponse",
    }
    assert all(fragment in generated_typescript for fragment in generated_history_fragments)
    deep_progress = schemas["FootprintDeepProgress"]
    assert set(deep_progress["required"]) == {
        "current_phase",
        "phase_started_at",
        "finished_at",
    }
    assert deep_progress["properties"]["current_phase"]["enum"] == [
        "queued",
        "account_scan",
        "awaiting_anchor",
        "professional_enrichment",
        "report_generation",
        "finalizing",
        "complete",
    ]
    assert deep_progress["properties"]["phase_started_at"]["format"] == "date-time"
    assert deep_progress["properties"]["finished_at"] == {
        "type": ["string", "null"],
        "format": "date-time",
    }
    assert "deep_progress: FootprintDeepProgress | null;" in generated_typescript
    assert "finished_at: string | null;" in generated_typescript
    assert "export type FootprintSynthesisModel" in generated_typescript
    assert "synthesis_model?: FootprintSynthesisModel;" in generated_typescript
    assert "synthesis_model: FootprintSynthesisModel | null;" in generated_typescript
    for synthesis_model in synthesis_models:
        assert f'| "{synthesis_model}"' in generated_typescript, synthesis_model
    for phase in deep_progress["properties"]["current_phase"]["enum"]:
        assert f'| "{phase}"' in generated_typescript, phase
    assert set(schemas["SelectFootprintAnchorRequest"]["required"]) == {
        "candidate_id"
    }
    assert set(schemas["SelectFootprintAnchorResponse"]["required"]) == {
        "job",
        "selected_anchor",
    }
    assert schemas["FootprintCatalog"]["properties"]["engine"]["const"] == "maigret"
    assert set(schemas["FootprintCoverage"]["required"]) == {
        "selected",
        "completed",
        "claimed",
        "available",
        "unknown",
        "illegal",
    }
    assert set(schemas["CandidateList"]["required"]) == {
        "items",
        "extracted_identifier_count",
    }
    assert schemas["AccountCandidate"]["properties"]["relationship"]["const"] == "unresolved"
    assert "anchor_eligible" in schemas["AccountCandidate"]["required"]
    footprint_brief = schemas["FootprintBrief"]
    assert set(footprint_brief["required"]) == {
        "job_id",
        "report_type",
        "subject",
        "summary",
        "overall_identity_status",
        "accounts",
        "claims",
        "identity_reasons",
        "limitations",
        "generated_at",
    }
    assert footprint_brief["properties"]["report_type"]["enum"] == [
        "account_centric",
        "person_centric",
    ]
    assert footprint_brief["properties"]["overall_identity_status"]["enum"] == [
        "confirmed",
        "likely",
        "unverified",
    ]
    footprint_account = schemas["FootprintBriefAccount"]
    assert footprint_account["properties"]["existence_status"]["enum"] == [
        "exact_verified",
        "indexed_profile",
        "claimed_unverified",
        "channel_limited",
        "excluded",
    ]
    assert footprint_account["properties"]["identity_status"]["enum"] == [
        "confirmed",
        "likely",
        "unverified",
        "conflicting",
        "excluded",
    ]
    assert schemas["FootprintBriefClaim"]["properties"]["qualification"]["type"] == [
        "string",
        "null",
    ]

    assert "job_queued" in events["properties"]["type"]["enum"]
    assert {
        "brief_ready",
        "insufficient_evidence",
        "result_unavailable",
        "job_cancelled",
        "job.accepted",
        "discovery.catalog_scan_started",
        "discovery.catalog_progress",
        "discovery.anchor_required",
        "discovery.anchor_selected",
        "discovery.anchor_window_expired",
        "discovery.professional_search_started",
        "discovery.professional_search_progress",
        "discovery.synthesis_started",
        "discovery.synthesis_progress",
        "candidate.discovered",
        "job.ready",
    } <= set(events["properties"]["type"]["enum"])
    for event_type in events["properties"]["type"]["enum"]:
        assert f'| "{event_type}"' in generated_typescript, event_type
    _assert_error_registry(errors)
    print(
        "Contracts are structurally valid, including footprint discovery, "
        "eligibility, and admin auth boundaries."
    )


if __name__ == "__main__":
    main()
