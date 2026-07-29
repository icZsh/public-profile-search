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
        "/v1/prototype/suppressions",
    }
    assert required_paths <= set(openapi["paths"])

    operation_ids = [
        operation["operationId"] for _path, _method, operation in _operations(openapi)
    ]
    assert len(operation_ids) == len(set(operation_ids)), "operationId values must be unique"
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

    assert "job_queued" in events["properties"]["type"]["enum"]
    assert {
        "brief_ready",
        "insufficient_evidence",
        "result_unavailable",
        "job_cancelled",
    } <= set(events["properties"]["type"]["enum"])
    _assert_error_registry(errors)
    print("Contracts are structurally valid, including eligibility and admin auth boundaries.")


if __name__ == "__main__":
    main()
