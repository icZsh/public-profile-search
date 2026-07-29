def completeness_outcome(claim_predicates: set[str]) -> str:
    has_name = "identity.public_display_name" in claim_predicates
    has_supported_account = bool(
        {
            "account.explicitly_linked_public_profile",
            "account.verified_input_profile",
        }
        & claim_predicates
    )
    if has_name and has_supported_account:
        return "ready"
    if has_name:
        return "ready_partial"
    return "insufficient_evidence"
