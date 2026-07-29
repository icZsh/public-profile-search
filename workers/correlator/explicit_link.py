from dataclasses import dataclass

from apps.api.app.policy.display import assert_displayable


@dataclass(frozen=True)
class ClaimSpec:
    predicate: str
    label: str
    value: str
    confidence: str
    evidence: tuple[tuple[str, str], ...]


def correlate_explicit_link(observations: list[dict[str, object]]) -> list[ClaimSpec]:
    verified_input = next(
        (
            observation
            for observation in observations
            if observation["source_type"] == "verified_input_profile"
        ),
        None,
    )
    if verified_input:
        fields = verified_input["extracted_fields"]
        display_name = str(fields.get("display_name", "")).strip()
        profile_url = str(fields.get("verified_profile_url", "")).strip()
        evidence = ((str(verified_input["id"]), str(verified_input["lineage_key"])),)
        claims: list[ClaimSpec] = []
        if display_name:
            assert_displayable("identity.public_display_name", display_name)
            claims.append(
                ClaimSpec(
                    predicate="identity.public_display_name",
                    label="Public display name",
                    value=display_name,
                    confidence="high",
                    evidence=evidence,
                )
            )
        if profile_url:
            assert_displayable("account.verified_input_profile", profile_url)
            claims.append(
                ClaimSpec(
                    predicate="account.verified_input_profile",
                    label="Control-verified input profile",
                    value=profile_url,
                    confidence="high",
                    evidence=evidence,
                )
            )
        return claims

    primary = next(
        (
            observation
            for observation in observations
            if observation["source_type"] == "self_description"
        ),
        None,
    )
    linked = next(
        (
            observation
            for observation in observations
            if observation["source_type"] == "first_party_linked_profile"
        ),
        None,
    )
    if not primary:
        return []

    primary_fields = primary["extracted_fields"]
    display_name = str(primary_fields.get("display_name", "")).strip()
    claims: list[ClaimSpec] = []
    if display_name:
        assert_displayable("identity.public_display_name", display_name)
        name_evidence = [(str(primary["id"]), str(primary["lineage_key"]))]
        if linked and linked["extracted_fields"].get("display_name") == display_name:
            name_evidence.append((str(linked["id"]), str(linked["lineage_key"])))
        claims.append(
            ClaimSpec(
                predicate="identity.public_display_name",
                label="Public display name",
                value=display_name,
                confidence="high",
                evidence=tuple(name_evidence),
            )
        )

    linked_url = str(primary_fields.get("explicitly_linked_url", "")).strip()
    reciprocal = bool(
        linked
        and linked_url
        and linked["canonical_url"] == linked_url
        and linked["extracted_fields"].get("links_back_to")
        == "https://profiles.example.test/alex-chen"
    )
    if reciprocal:
        assert_displayable("account.explicitly_linked_public_profile", linked_url)
        claims.append(
            ClaimSpec(
                predicate="account.explicitly_linked_public_profile",
                label="Explicitly linked public profile",
                value=linked_url,
                confidence="high",
                evidence=(
                    (str(primary["id"]), str(primary["lineage_key"])),
                    (str(linked["id"]), str(linked["lineage_key"])),
                ),
            )
        )
    return claims
