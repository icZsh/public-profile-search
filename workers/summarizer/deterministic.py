from datetime import datetime


def render_fast_brief(
    *,
    job_id: str,
    claims: list[dict[str, object]],
    generated_at: datetime,
    provider_id: str,
) -> dict[str, object]:
    name_claim = next(
        (claim for claim in claims if claim["predicate"] == "identity.public_display_name"),
        None,
    )
    linked_claim = next(
        (
            claim
            for claim in claims
            if claim["predicate"] == "account.explicitly_linked_public_profile"
        ),
        None,
    )
    verified_input_claim = next(
        (claim for claim in claims if claim["predicate"] == "account.verified_input_profile"),
        None,
    )
    is_synthetic = provider_id.startswith("fixture_")
    subject = str(name_claim["value"]) if name_claim else "Unknown public profile"
    if is_synthetic and name_claim and linked_claim:
        summary = (
            f"The synthetic source set supports the public display name {subject} "
            "and an explicitly linked synthetic code profile."
        )
    elif is_synthetic and name_claim:
        summary = f"The synthetic source supports the public display name {subject}."
    elif name_claim and verified_input_claim:
        summary = (
            f"The submitted GitHub profile supports the public display name {subject} "
            "and is bound to the control-verified input account."
        )
    elif name_claim:
        summary = f"The approved public source supports the display name {subject}."
    else:
        summary = "The approved sources do not support a useful public profile brief."
    limitations = (
        [
            "This brief uses synthetic fixtures and does not describe a real person.",
            "It confirms explicit links only; it is not a real-world identity verification.",
        ]
        if is_synthetic
        else [
            "This brief uses only allowlisted fields from the submitted public GitHub profile.",
            (
                "Profile control and local eligibility review do not independently verify "
                "every self-reported profile statement."
            ),
        ]
    )
    return {
        "job_id": job_id,
        "subject": subject,
        "summary": summary,
        "claims": claims,
        "limitations": limitations,
        "generated_at": generated_at.isoformat(),
    }
