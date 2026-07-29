from typing import Final

DISPLAYABLE_PREDICATES: Final[frozenset[str]] = frozenset(
    {
        "identity.public_display_name",
        "account.explicitly_linked_public_profile",
        "account.verified_input_profile",
    }
)

FORBIDDEN_FIELD_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "email",
        "phone",
        "address",
        "birthday",
        "religion",
        "politic",
        "ethnicity",
        "medical",
        "disability",
        "sexual",
        "gender",
        "immigration",
    }
)


def assert_displayable(predicate: str, value: str) -> None:
    if predicate not in DISPLAYABLE_PREDICATES:
        raise ValueError(f"Predicate is not displayable: {predicate}")
    lowered = value.casefold()
    if any(token in lowered for token in FORBIDDEN_FIELD_TOKENS):
        raise ValueError("Value failed the prototype sensitive-data policy")
