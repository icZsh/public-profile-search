from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import httpx
import pytest

from workers.providers.grounded_synthesis import (
    DEFAULT_SYNTHESIS_MODEL,
    EvidenceAccountInput,
    EvidenceSeedInput,
    EvidenceSourceInput,
    GroundingValidationError,
    build_evidence_packet,
    grounded_synthesis_json_schema,
    request_grounded_synthesis,
    synthesize_grounded_footprint,
    validate_grounded_synthesis,
)


def _seed() -> EvidenceSeedInput:
    return EvidenceSeedInput(
        platform="instagram",
        identifier_type="handle",
        identifier="alice",
    )


def _source(
    source_id: str = "source-1",
    *,
    canonical_url: str | None = None,
    excerpt: str = "Alice Example describes herself as an engineer at Example Labs.",
    extracted_fields: dict[str, object] | None = None,
) -> EvidenceSourceInput:
    return EvidenceSourceInput(
        source_id=source_id,
        source_type="first_party_profile_api",
        trust_class="first_party",
        publisher="GitHub",
        title="Alice Example · GitHub professional profile",
        canonical_url=canonical_url or f"https://github.com/alice-{source_id}",
        excerpt=excerpt,
        extracted_fields=extracted_fields
        or {
            "display_name": "Alice Example",
            "bio": "Engineer at Example Labs",
            "company": "Example Labs",
            "location": "San Francisco Bay Area",
        },
    )


def _account(source_ids: tuple[str, ...] = ("source-1",)) -> EvidenceAccountInput:
    return EvidenceAccountInput(
        account_id="account-1",
        platform="GitHub",
        canonical_handle="alice",
        canonical_url="https://github.com/alice",
        display_name="Alice Example",
        source_ids=source_ids,
    )


def _valid_output(source_id: str = "source-1") -> dict[str, object]:
    return {
        "schema_version": "grounded-digital-footprint-v4",
        "report_synthesis": {
            "report_type": "account_centric",
            "one_sentence_conclusion": (
                "The public profile presents Alice Example as an engineer at Example Labs, "
                "but the professional details remain self-described."
            ),
            "identity_status": "possible",
            "overall_confidence": "medium",
            "likely_public_identity": "Alice Example",
            "broad_location": "San Francisco Bay Area",
            "major_boundary": (
                "The available evidence is one first-party account and does not independently "
                "verify the professional details."
            ),
            "source_ids": [source_id],
        },
        "subject_profile": {
            "identity": {
                "value": "Alice Example, a public GitHub profile using @alice",
                "confidence": "medium",
                "basis": "mixed",
                "explanation": (
                    "The public display name and handle appear together on the profile."
                ),
                "source_ids": [source_id],
            },
            "location": {
                "value": "San Francisco Bay Area",
                "confidence": "medium",
                "basis": "self_described",
                "explanation": "The public profile self-describes this broad location.",
                "source_ids": [source_id],
            },
            "occupation": {
                "value": "Engineer at Example Labs",
                "confidence": "medium",
                "basis": "self_described",
                "explanation": "The public bio names the role and company.",
                "source_ids": [source_id],
            },
            "education": {
                "value": None,
                "confidence": None,
                "basis": "unknown",
                "explanation": "No reliable public education evidence was supplied.",
                "source_ids": [],
            },
            "interests": [
                {
                    "label": "Software engineering",
                    "confidence": "medium",
                    "basis": "self_described",
                    "explanation": "The profile publicly describes engineering work.",
                    "source_ids": [source_id],
                }
            ],
            "likes": [],
            "dislikes": [],
            "unknowns": [
                {
                    "topic": "education",
                    "explanation": "No reliable public education evidence was supplied.",
                    "source_ids": [],
                },
                {
                    "topic": "likes",
                    "explanation": "No explicit or repeated positive preference was supplied.",
                    "source_ids": [],
                },
                {
                    "topic": "dislikes",
                    "explanation": "No explicit public dislike was supplied.",
                    "source_ids": [],
                },
            ],
            "career_timeline": [
                {
                    "entry_type": "work",
                    "title": "Engineer",
                    "organization": "Example Labs",
                    "timeframe": None,
                    "currentness": "unclear",
                    "confidence": "medium",
                    "basis": "self_described",
                    "explanation": "The public bio names this role without dates.",
                    "source_ids": [source_id],
                }
            ],
        },
        "summary": (
            "Alice Example's public GitHub profile ties a display name, Bay Area location, "
            "and self-described engineering role at Example Labs to one account. The evidence "
            "supports an account-level profile, while the role and employer should not be "
            "treated as independently verified."
        ),
        "summary_source_ids": [source_id],
        "identity_facts": [
            {
                "label": "Public display name",
                "value": "Alice Example",
                "confidence": "high",
                "status": "observed",
                "qualification": "Displayed on the first-party public profile.",
                "source_ids": [source_id],
            },
            {
                "label": "Broad location",
                "value": "San Francisco Bay Area",
                "confidence": "medium",
                "status": "self_described",
                "qualification": "Self-described and not independently verified.",
                "source_ids": [source_id],
            },
        ],
        "account_assessments": [
            {
                "account_id": "account-1",
                "platform": "GitHub",
                "canonical_handle": "alice",
                "canonical_url": "https://github.com/alice",
                "existence_status": "exact_verified",
                "association_status": "possible",
                "confidence": "medium",
                "rationale": (
                    "The exact public account exposes the display name and professional bio."
                ),
                "source_ids": [source_id],
                "public_facts": [
                    {
                        "text": "The public profile displays the name Alice Example.",
                        "source_ids": [source_id],
                    },
                    {
                        "text": "The profile self-describes an engineering role.",
                        "source_ids": [source_id],
                    },
                ],
                "association_reasons": [
                    {
                        "text": (
                            "The display name, company, and location appear on the same account."
                        ),
                        "source_ids": [source_id],
                    }
                ],
            }
        ],
        "narrative_sections": [
            {
                "key": "professional",
                "title": "Professional profile",
                "body": (
                    "The profile tells a compact professional story centered on engineering "
                    "work at Example Labs, but both the role and company are self-described."
                ),
                "source_ids": [source_id],
                "highlights": [
                    {
                        "text": "The public bio names an engineering role at Example Labs.",
                        "source_ids": [source_id],
                    }
                ],
            }
        ],
        "claims": [
            {
                "claim_id": "claim-1",
                "predicate": "professional.public_company",
                "label": "Public company",
                "value": "Example Labs",
                "confidence": "medium",
                "status": "independently_unverified",
                "source_ids": [source_id],
                "contradicting_source_ids": [],
                "qualification": "Self-described on a public profile.",
                "supporting_evidence": [
                    {
                        "text": "The public bio names Example Labs.",
                        "source_ids": [source_id],
                    }
                ],
                "limiting_evidence": [
                    {
                        "text": "No independent employer source is present.",
                        "source_ids": [source_id],
                    }
                ],
            }
        ],
        "supporting_reasons": [
            {
                "text": "The display name and professional description are present together.",
                "source_ids": [source_id],
            }
        ],
        "limiting_reasons": [
            {
                "text": "The role is self-described and is not independently verified.",
                "source_ids": [source_id],
            }
        ],
        "excluded_candidates": [],
        "channel_coverage": [
            {
                "channel": "GitHub",
                "status": "confirmed",
                "detail": "An exact public profile was available for assessment.",
                "source_ids": [source_id],
            }
        ],
        "next_verification_steps": [
            {
                "text": (
                    "A first-party cross-link to another profile would strengthen person-level "
                    "association."
                ),
                "source_ids": [source_id],
            }
        ],
    }


def _legacy_output(source_id: str = "source-1") -> dict[str, object]:
    return {
        "summary": "Public profile evidence describes an engineering role.",
        "summary_source_ids": [source_id],
        "narrative_sections": [
            {
                "key": "professional",
                "title": "Professional profile",
                "body": "A first-party profile self-describes an engineering role.",
                "source_ids": [source_id],
            }
        ],
        "claims": [],
        "supporting_reasons": [],
        "limiting_reasons": [],
    }


def _api_payload(
    output: dict[str, object],
    *,
    status: str = "completed",
    output_items: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": "resp_test_123",
        "object": "response",
        "status": status,
        "error": None,
        "incomplete_details": None,
        "model": DEFAULT_SYNTHESIS_MODEL,
        "output": output_items
        if output_items is not None
        else [
            {"id": "rs_1", "type": "reasoning", "summary": []},
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(output),
                        "annotations": [],
                    }
                ],
            },
        ],
        "usage": {
            "input_tokens": 120,
            "output_tokens": 80,
            "total_tokens": 200,
        },
    }


def _packet():
    return build_evidence_packet(
        seed=_seed(),
        sources=[_source()],
        accounts=[_account()],
    )


def test_evidence_packet_is_bounded_allowlisted_and_contact_redacted():
    sources = [
        _source(
            f"source-{index}",
            excerpt=(
                f"Alice {index} can be reached at alice{index}@example.test or +1 (555) 123-4567."
            ),
            extracted_fields={
                "display_name": "Alice Example",
                "email": "alice@example.test",
                "phone": "+1 555 123 4567",
                "bio": "Email alice@example.test or call +1 555 123 4567.",
                "internal_payload": "must not pass through",
                "work_history": [
                    {
                        "title": "Engineer",
                        "company": "Example Labs",
                        "email": "manager@example.test",
                    }
                ],
            },
        )
        for index in range(5)
    ]
    packet = build_evidence_packet(
        seed=_seed(),
        sources=sources,
        accounts=[
            replace(
                _account(("source-0", "unknown-source")),
                display_name="Alice alice@example.test",
            )
        ],
        max_sources=2,
        max_chars=4_000,
    )

    assert len(packet.sources) == 2
    assert packet.sources_truncated is True
    assert packet.accounts[0].source_ids == ("source-0",)
    serialized = packet.model_dump_json()
    assert "[redacted contact]" in serialized
    for forbidden in (
        "alice@example.test",
        "alice0@example.test",
        "manager@example.test",
        "555",
        "internal_payload",
        "unknown-source",
    ):
        assert forbidden not in serialized
    assert len(serialized) <= 4_000


def test_evidence_packet_character_budget_and_invalid_urls_are_enforced():
    packet = build_evidence_packet(
        seed=_seed(),
        sources=[
            _source(
                f"source-{index}",
                excerpt="profile evidence " * 100,
            )
            for index in range(40)
        ],
        accounts=[_account()] * 5,
        max_chars=2_500,
    )
    rejected = build_evidence_packet(
        seed=_seed(),
        sources=[
            _source("http-source", canonical_url="http://example.com/alice"),
            _source("local-source", canonical_url="https://localhost/alice"),
            _source(
                "contact-source",
                canonical_url="https://example.com/alice%40example.test",
            ),
        ],
    )
    query_stripped = build_evidence_packet(
        seed=_seed(),
        sources=[
            _source(
                "query-source",
                canonical_url=("https://example.com/alice?email=alice@example.test#contact"),
                extracted_fields={
                    "website": "https://alice.example/about?phone=15551234567",
                },
            )
        ],
    )

    assert len(packet.model_dump_json()) <= 2_500
    assert packet.sources_truncated is True
    assert rejected.sources == ()
    assert query_stripped.sources[0].canonical_url == "https://example.com/alice"
    assert query_stripped.sources[0].extracted_fields["website"] == ("https://alice.example/about")
    assert "alice@example.test" not in query_stripped.model_dump_json()


@pytest.mark.parametrize("max_chars", [2_000, 2_500, 4_000, 9_000, 20_000, 48_000])
def test_evidence_packet_budget_is_tight_at_every_truncation_boundary(max_chars):
    # The character budget is enforced with running totals rather than by
    # re-serializing each candidate packet. Pin the observable contract: the
    # packet fits its budget, and it is maximal -- one more source would not.
    sources = [
        _source(f"source-{index}", excerpt="profile evidence " * 30) for index in range(40)
    ]
    accounts = [_account((f"source-{index}",)) for index in range(30)]

    packet = build_evidence_packet(
        seed=_seed(),
        sources=sources,
        accounts=accounts,
        max_chars=max_chars,
    )

    assert len(packet.model_dump_json(exclude_none=False)) <= max_chars
    if packet.sources_truncated and len(packet.sources) < len(sources):
        one_more = build_evidence_packet(
            seed=_seed(),
            sources=sources[: len(packet.sources) + 1],
            accounts=(),
            max_chars=100_000,
        )
        assert len(one_more.sources) == len(packet.sources) + 1
        account_reserve = min(max_chars // 4, 30 * 480)
        source_budget = max(2_000, max_chars - account_reserve)
        assert len(one_more.model_dump_json(exclude_none=False)) > source_budget


def test_usage_captures_reasoning_and_cached_token_details():
    # `max_output_tokens` budgets reasoning and visible output together, so the
    # reasoning split has to survive into the persisted usage record.
    payload = _api_payload(_valid_output())
    payload["usage"] = {
        "input_tokens": 1_200,
        "output_tokens": 900,
        "total_tokens": 2_100,
        "input_tokens_details": {"cached_tokens": 1_024},
        "output_tokens_details": {"reasoning_tokens": 640},
    }

    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key="test-api-key",
        reasoning_effort="medium",
        max_output_tokens=2_500,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )

    assert outcome.usage is not None
    assert outcome.usage.reasoning_tokens == 640
    assert outcome.usage.cached_input_tokens == 1_024


def test_usage_details_are_optional_when_the_gateway_omits_them():
    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key="test-api-key",
        reasoning_effort="medium",
        max_output_tokens=2_500,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_api_payload(_valid_output()))
        ),
    )

    assert outcome.usage is not None
    assert outcome.usage.total_tokens == 200
    assert outcome.usage.reasoning_tokens is None
    assert outcome.usage.cached_input_tokens is None


def test_output_schema_is_strict_and_requires_grounding_for_summary():
    schema = grounded_synthesis_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["enum"] == ["grounded-digital-footprint-v4"]
    assert schema["properties"]["report_synthesis"] == {"$ref": "#/$defs/GroundedReportSynthesis"}
    assert schema["properties"]["subject_profile"] == {"$ref": "#/$defs/GroundedSubjectProfile"}
    assert '"default"' not in json.dumps(schema)
    assert "summary_source_ids" in schema["required"]
    assert "identity_facts" in schema["required"]
    assert "subject_profile" in schema["required"]
    subject_profile = schema["$defs"]["GroundedSubjectProfile"]
    assert set(subject_profile["required"]) == {
        "identity",
        "location",
        "occupation",
        "education",
        "interests",
        "likes",
        "dislikes",
        "unknowns",
        "career_timeline",
    }
    assert "account_assessments" in schema["required"]
    assert "excluded_candidates" in schema["required"]
    assert "channel_coverage" in schema["required"]
    assert "next_verification_steps" in schema["required"]
    assert schema["properties"]["summary_source_ids"]["minItems"] == 1
    for definition in schema["$defs"].values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False
            assert set(definition["properties"]) == set(definition["required"])
    predicates = schema["$defs"]["GroundedClaim"]["properties"]["predicate"]["enum"]
    assert "professional.role" in predicates
    assert "person.public_identity" in predicates
    assert "person.private_contact" not in predicates
    assert schema["$defs"]["GroundedTimelineEntry"]["properties"]["entry_type"]["enum"] == [
        "work",
        "education",
    ]


def test_output_schema_enumerates_only_packet_grounding_identifiers():
    schema = grounded_synthesis_json_schema(packet=_packet())

    assert schema["properties"]["summary_source_ids"]["items"]["enum"] == ["source-1"]
    for definition in schema["$defs"].values():
        properties = definition.get("properties", {})
        for name, property_schema in properties.items():
            if name.endswith("source_ids"):
                assert property_schema["items"]["enum"] == ["source-1"]

    account = schema["$defs"]["GroundedAccountAssessment"]["properties"]
    assert account["account_id"]["enum"] == ["account-1"]
    assert account["canonical_url"]["enum"] == ["https://github.com/alice"]
    assert account["canonical_handle"]["enum"] == ["alice"]
    assert account["platform"]["enum"] == ["GitHub"]


def test_v1_persisted_output_remains_loadable_but_provider_validation_requires_v2():
    legacy = _legacy_output()

    persisted = validate_grounded_synthesis(legacy, packet=_packet())
    assert persisted.schema_version == "grounded-digital-footprint-v1"
    assert persisted.report_synthesis is None
    assert persisted.identity_facts == ()

    with pytest.raises(GroundingValidationError) as exc_info:
        validate_grounded_synthesis(
            legacy,
            packet=_packet(),
            require_rich_v2=True,
        )

    assert exc_info.value.code == "output_schema_version_invalid"


def test_v2_persisted_output_remains_loadable_without_subject_profile():
    legacy_v2 = _valid_output()
    legacy_v2["schema_version"] = "grounded-digital-footprint-v2"
    legacy_v2.pop("subject_profile")

    output = validate_grounded_synthesis(
        legacy_v2,
        packet=_packet(),
        require_rich_v2=True,
    )

    assert output.schema_version == "grounded-digital-footprint-v2"
    assert output.subject_profile is None


def test_v3_persisted_output_remains_loadable_without_v4_career_timeline():
    legacy_v3 = _valid_output()
    legacy_v3["schema_version"] = "grounded-digital-footprint-v3"
    legacy_v3["subject_profile"].pop("career_timeline")

    output = validate_grounded_synthesis(legacy_v3, packet=_packet())

    assert output.schema_version == "grounded-digital-footprint-v3"
    assert output.subject_profile is not None
    assert output.subject_profile.career_timeline == ()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("channel_coverage"),
        lambda value: value["account_assessments"][0].pop("public_facts"),
        lambda value: value["narrative_sections"][0].pop("highlights"),
        lambda value: value["claims"][0].pop("status"),
        lambda value: value["claims"][0].pop("supporting_evidence"),
        lambda value: value["subject_profile"].pop("career_timeline"),
    ],
)
def test_current_provider_validation_rejects_implicit_legacy_defaults(mutate):
    value = _valid_output()
    mutate(value)

    with pytest.raises(GroundingValidationError) as exc_info:
        validate_grounded_synthesis(
            value,
            packet=_packet(),
            require_rich_v2=True,
        )

    assert exc_info.value.code == "output_schema_invalid"


def test_v3_profile_answer_semantics_are_left_for_host_normalization():
    value = _valid_output()
    value["schema_version"] = "grounded-digital-footprint-v3"
    value["subject_profile"]["occupation"] = {
        "value": None,
        "confidence": "medium",
        "basis": "unknown",
        "explanation": "No reliable occupation evidence was supplied.",
        "source_ids": [],
    }

    output = validate_grounded_synthesis(
        value,
        packet=_packet(),
        require_template_v3=True,
    )

    assert output.subject_profile is not None
    assert output.subject_profile.occupation.value is None
    assert output.subject_profile.occupation.confidence == "medium"


def test_v3_profile_preserves_inferred_dislike_for_host_filtering():
    value = _valid_output()
    value["schema_version"] = "grounded-digital-footprint-v3"
    value["subject_profile"]["dislikes"] = [
        {
            "label": "Meetings",
            "confidence": "low",
            "basis": "inferred",
            "explanation": "A single post complained about a meeting.",
            "source_ids": ["source-1"],
        }
    ]

    output = validate_grounded_synthesis(
        value,
        packet=_packet(),
        require_template_v3=True,
    )

    assert output.subject_profile is not None
    assert output.subject_profile.dislikes[0].basis == "inferred"


def test_v4_weak_timeline_enums_are_preserved_for_host_filtering():
    value = _valid_output()
    profile = value["subject_profile"]
    profile["career_timeline"][0]["currentness"] = "possibly_current"

    output = validate_grounded_synthesis(
        value,
        packet=_packet(),
        require_template_v4=True,
    )

    assert output.subject_profile is not None
    assert output.subject_profile.career_timeline[0].currentness == "possibly_current"


def test_v4_timeline_pre_normalizer_fills_missing_array():
    value = _valid_output()
    profile = value["subject_profile"]
    profile.pop("career_timeline")

    output = validate_grounded_synthesis(
        value,
        packet=_packet(),
        require_template_v4=True,
    )

    assert output.subject_profile is not None
    assert output.subject_profile.career_timeline == ()


def test_v4_timeline_pre_normalizer_drops_partial_items_and_unknown_keys():
    value = _valid_output()
    profile = value["subject_profile"]
    profile["career_timeline"][0]["unexpected_note"] = "Ignore this extra key."
    profile["career_timeline"].append(
        {
            "entry_type": "work",
            "title": "Missing required fields",
            "source_ids": ["source-1"],
        }
    )

    output = validate_grounded_synthesis(
        value,
        packet=_packet(),
        require_template_v4=True,
    )

    assert output.subject_profile is not None
    assert len(output.subject_profile.career_timeline) == 1


def test_rich_story_units_are_individually_grounded():
    output = validate_grounded_synthesis(
        _valid_output(),
        packet=_packet(),
        require_rich_v2=True,
    )

    assert output.report_synthesis is not None
    assert output.report_synthesis.report_type == "account_centric"
    assert output.identity_facts[0].status == "observed"
    assert output.account_assessments[0].account_id == "account-1"
    assert output.account_assessments[0].public_facts[0].source_ids == ("source-1",)
    assert output.narrative_sections[0].highlights[0].source_ids == ("source-1",)
    assert output.claims[0].status == "independently_unverified"
    assert output.claims[0].limiting_evidence[0].source_ids == ("source-1",)
    assert output.channel_coverage[0].status == "confirmed"


def test_numeric_public_handle_is_not_misclassified_as_contact_data():
    numeric_account = EvidenceAccountInput(
        account_id="account-numeric",
        platform="GitHub",
        canonical_handle="15096819",
        canonical_url="https://github.com/15096819",
        display_name=None,
        source_ids=("source-1",),
    )
    packet = build_evidence_packet(
        seed=_seed(),
        sources=[_source()],
        accounts=[numeric_account],
    )
    value = _valid_output()
    value["account_assessments"][0].update(
        account_id="account-numeric",
        canonical_handle="15096819",
        canonical_url="https://github.com/15096819",
    )
    value["summary"] = (
        "The public profile 15096819 describes an engineering role, while the "
        "person-level association remains unverified."
    )

    output = validate_grounded_synthesis(
        value,
        packet=packet,
        require_rich_v2=True,
    )

    assert output.account_assessments[0].canonical_handle == "15096819"


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda value: value.update(summary_source_ids=["unknown-source"]),
            "output_unknown_source_id",
        ),
        (
            lambda value: value.update(
                summary="Contact Alice at alice@example.test for more information."
            ),
            "output_contains_contact_data",
        ),
        (
            lambda value: value.update(
                summary="A different profile appears at https://example.com/invented."
            ),
            "output_unknown_url",
        ),
        (
            lambda value: value["claims"][0].update(predicate="person.private_contact"),
            "output_schema_invalid",
        ),
        (
            lambda value: value["account_assessments"][0].update(account_id="unknown-account"),
            "output_unknown_account_id",
        ),
        (
            lambda value: value["account_assessments"][0].update(
                canonical_url="https://github.com/alice-source-1"
            ),
            "output_account_mismatch",
        ),
        (
            lambda value: value["subject_profile"]["career_timeline"][0].update(
                source_ids=["unknown-source"]
            ),
            "output_unknown_source_id",
        ),
    ],
)
def test_grounding_validator_rejects_unknown_sources_contacts_urls_predicates_and_accounts(
    mutate,
    expected_code: str,
):
    value = _valid_output()
    mutate(value)

    with pytest.raises(GroundingValidationError) as exc_info:
        validate_grounded_synthesis(value, packet=_packet())

    assert exc_info.value.code == expected_code


def test_grounding_validator_accepts_evidence_url_and_professional_date_range():
    value = _valid_output()
    value["summary"] = "The profile at https://github.com/alice-source-1 lists work from 2018-2024."

    output = validate_grounded_synthesis(value, packet=_packet())

    assert output.summary.endswith("2018-2024.")


def test_responses_client_uses_fixed_host_current_contract_and_parses_success():
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("Authorization")
        observed["body"] = json.loads(request.content)
        observed["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json=_api_payload(_valid_output()))

    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key="test-api-key",
        reasoning_effort="medium",
        max_output_tokens=2_500,
        safety_identifier="job-hmac-123",
        transport=httpx.MockTransport(handler),
    )

    assert outcome.status == "success"
    assert outcome.output is not None
    assert outcome.output.summary_source_ids == ("source-1",)
    assert outcome.error_code is None
    assert outcome.response_id == "resp_test_123"
    assert outcome.model == "gpt-5.6-sol"
    assert outcome.usage is not None
    assert outcome.usage.total_tokens == 200
    assert len(outcome.input_checksum) == 64
    assert observed["url"] == "https://api.openai.com/v1/responses"
    assert observed["authorization"] == "Bearer test-api-key"
    assert observed["timeout"] == {
        "connect": 10.0,
        "read": 300.0,
        "write": 30.0,
        "pool": 10.0,
    }
    body = observed["body"]
    assert body["model"] == "gpt-5.6-sol"
    assert body["store"] is False
    assert body["reasoning"] == {"effort": "medium"}
    assert body["max_output_tokens"] == 2_500
    assert body["safety_identifier"] == "job-hmac-123"
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["name"] == "grounded_digital_footprint_v4"
    assert body["text"]["format"]["schema"]["additionalProperties"] is False
    assert body["text"]["format"]["schema"]["properties"]["summary_source_ids"]["items"][
        "enum"
    ] == ["source-1"]
    assert body["text"]["verbosity"] == "medium"
    assert (
        "Keep account existence separate from same-person association"
        in body["input"][0]["content"]
    )
    system_prompt = body["input"][0]["content"]
    assert "Build career_timeline from public work and education evidence only" in system_prompt
    assert "potentially stale" in system_prompt


def test_explicit_finite_timeout_remains_available_for_non_deep_callers():
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json=_api_payload(_valid_output()))

    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key="test-api-key",
        timeout_seconds=12.5,
        transport=httpx.MockTransport(handler),
    )

    assert outcome.status == "success"
    assert observed["timeout"] == {
        "connect": 12.5,
        "read": 12.5,
        "write": 12.5,
        "pool": 12.5,
    }


def test_cancellation_event_aborts_inflight_deadline_free_http_request():
    class BlockingTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.started = Event()
            self.cancelled = Event()

        async def handle_async_request(self, _request: httpx.Request) -> httpx.Response:
            self.started.set()
            try:
                await asyncio.wait_for(asyncio.Event().wait(), timeout=2.0)
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
            raise AssertionError("The deadline-free request was not cooperatively cancelled")

    transport = BlockingTransport()
    cancel_event = Event()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            request_grounded_synthesis,
            packet=_packet(),
            api_key="test-api-key",
            timeout_seconds=None,
            cancel_event=cancel_event,
            transport=transport,
        )
        assert transport.started.wait(timeout=1.0)
        cancel_event.set()
        outcome = future.result(timeout=1.0)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    assert transport.cancelled.is_set()
    assert outcome.status == "provider_error"
    assert outcome.error_code == "request_cancelled"


def test_openrouter_client_uses_fixed_host_headers_model_schema_and_private_routing():
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("Authorization")
        observed["http_referer"] = request.headers.get("HTTP-Referer")
        observed["app_title"] = request.headers.get("X-OpenRouter-Title")
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json=_api_payload(_valid_output()))

    outcome = synthesize_grounded_footprint(
        api_key="test-openrouter-key",
        provider="openrouter",
        http_referer="http://localhost:3417",
        app_title="Tracebrief test",
        seed=_seed(),
        sources=[_source()],
        accounts=[_account()],
        model="~deepseek/deepseek-v4-flash-latest",
        reasoning_effort="medium",
        max_output_tokens=16_000,
        transport=httpx.MockTransport(handler),
    )

    assert outcome.status == "success"
    assert outcome.output is not None
    assert outcome.model == "~deepseek/deepseek-v4-flash-latest"
    assert observed["url"] == "https://openrouter.ai/api/v1/responses"
    assert observed["authorization"] == "Bearer test-openrouter-key"
    assert observed["http_referer"] == "http://localhost:3417"
    assert observed["app_title"] == "Tracebrief test"
    body = observed["body"]
    assert body["model"] == "~deepseek/deepseek-v4-flash-latest"
    assert body["provider"] == {
        "allow_fallbacks": True,
        "require_parameters": True,
        "data_collection": "deny",
    }
    assert body["reasoning"] == {"effort": "medium"}
    assert body["max_output_tokens"] == 16_000
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["name"] == "grounded_digital_footprint_v4"
    assert body["text"]["format"]["schema"]["additionalProperties"] is False
    assert "verbosity" not in body["text"]
    assert "tools" not in body
    assert "plugins" not in body


def test_openrouter_missing_key_skips_without_network():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key=None,
        provider="openrouter",
        model="openai/gpt-5.6-sol",
        transport=httpx.MockTransport(handler),
    )

    assert outcome.status == "skipped_configuration"
    assert outcome.error_code == "api_key_missing"
    assert outcome.used_deterministic_fallback is True
    assert not called


@pytest.mark.parametrize(
    ("error_type", "expected_status"),
    [
        ("authentication", "auth_required"),
        ("rate_limit_exceeded", "rate_limited"),
        ("timeout", "timeout"),
        ("provider_overloaded", "provider_error"),
        ("invalid_request", "invalid_response"),
    ],
)
def test_openrouter_failed_response_maps_top_level_typed_error(
    error_type: str,
    expected_status: str,
):
    payload = {
        **_api_payload(_valid_output()),
        "status": "failed",
        "error": {"code": "server_error", "message": "provider failure"},
        "error_type": error_type,
    }

    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key="test-openrouter-key",
        provider="openrouter",
        model="openai/gpt-5.6-sol",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)),
    )

    assert outcome.status == expected_status
    assert outcome.error_code == error_type
    assert outcome.output is None


def test_openrouter_http_error_prefers_typed_error_over_lossy_status():
    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key="test-openrouter-key",
        provider="openrouter",
        model="openai/gpt-5.6-sol",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                500,
                json={
                    "status": "failed",
                    "error": {
                        "code": "server_error",
                        "message": "Invalid credentials",
                    },
                    "error_type": "authentication",
                },
            )
        ),
    )

    assert outcome.status == "auth_required"
    assert outcome.error_code == "authentication"


def test_missing_key_and_empty_evidence_skip_without_network():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    missing_key = request_grounded_synthesis(
        packet=_packet(),
        api_key=None,
        transport=httpx.MockTransport(handler),
    )
    empty_packet = build_evidence_packet(seed=_seed(), sources=[])
    no_evidence = request_grounded_synthesis(
        packet=empty_packet,
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    assert missing_key.status == "skipped_configuration"
    assert missing_key.error_code == "api_key_missing"
    assert missing_key.used_deterministic_fallback is True
    assert no_evidence.status == "no_result"
    assert no_evidence.error_code == "synthesis_no_evidence"
    assert not called


@pytest.mark.parametrize(
    "render",
    [
        lambda payload: f"```json\n{payload}\n```",
        lambda payload: f"Here is the report:\n{payload}",
    ],
)
def test_completed_response_accepts_a_single_wrapped_json_object(render):
    text = render(json.dumps(_valid_output()))
    payload = _api_payload(
        _valid_output(),
        output_items=[
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    )

    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key="test-api-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)),
    )

    assert outcome.status == "success"
    assert outcome.output is not None


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (
            {
                **_api_payload(_valid_output()),
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
            },
            "incomplete_max_output_tokens",
        ),
        (
            _api_payload(
                _valid_output(),
                output_items=[
                    {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "refusal",
                                "refusal": "I cannot complete that request.",
                            }
                        ],
                    }
                ],
            ),
            "response_refusal",
        ),
        (
            _api_payload(
                _valid_output(),
                output_items=[
                    {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "{not-json"}],
                    }
                ],
            ),
            "output_invalid_json",
        ),
    ],
)
def test_incomplete_refusal_and_malformed_output_become_fallbacks(
    payload: dict[str, object],
    expected_code: str,
):
    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key="test-api-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)),
    )

    assert outcome.status == "invalid_response"
    assert outcome.output is None
    assert outcome.error_code == expected_code
    assert outcome.used_deterministic_fallback is True


def test_ungrounded_model_output_becomes_fallback():
    output = _valid_output()
    output["summary_source_ids"] = ["invented-source"]

    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key="test-api-key",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=_api_payload(output))
        ),
    )

    assert outcome.status == "invalid_response"
    assert outcome.error_code == "output_unknown_source_id"
    assert outcome.output is None


def test_provider_response_using_legacy_shape_becomes_fallback():
    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key="test-api-key",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=_api_payload(_legacy_output()))
        ),
    )

    assert outcome.status == "invalid_response"
    assert outcome.error_code == "output_schema_version_invalid"
    assert outcome.output is None


@pytest.mark.parametrize(
    ("status_code", "expected_status", "expected_code"),
    [
        (401, "auth_required", "auth_required"),
        (429, "rate_limited", "rate_limited"),
        (500, "provider_error", "unavailable"),
        (422, "invalid_response", "unexpected_status"),
    ],
)
def test_http_errors_become_provider_compatible_fallbacks(
    status_code: int,
    expected_status: str,
    expected_code: str,
):
    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key="test-api-key",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status_code, json={"error": "test"})
        ),
    )

    assert outcome.status == expected_status
    assert outcome.error_code == expected_code
    assert outcome.output is None


def test_timeout_becomes_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("test timeout", request=request)

    outcome = request_grounded_synthesis(
        packet=_packet(),
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    assert outcome.status == "timeout"
    assert outcome.error_code == "request_timeout"


def test_high_level_callable_builds_packet_and_has_stable_checksum():
    first = synthesize_grounded_footprint(
        api_key=None,
        seed=_seed(),
        sources=[_source()],
        accounts=[_account()],
    )
    second = synthesize_grounded_footprint(
        api_key=None,
        seed=_seed(),
        sources=[_source()],
        accounts=[_account()],
    )

    assert first.model == DEFAULT_SYNTHESIS_MODEL == "gpt-5.6-sol"
    assert first.status == "skipped_configuration"
    assert first.input_checksum == second.input_checksum
