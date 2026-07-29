"""Restricted local review tool for a control-verified eligibility request."""

import argparse
import re

import httpx

from apps.api.app.core.config import get_settings

REVIEWER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")


def _request_json(
    method: str,
    url: str,
    *,
    admin_token: str,
    payload: dict[str, str] | None = None,
) -> dict[str, object]:
    response = httpx.request(
        method,
        url,
        headers={
            "X-Prototype-Admin-Token": admin_token,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=10.0,
        trust_env=False,
    )
    if not response.is_success:
        try:
            message = str(response.json().get("message", "Review request failed."))
        except (ValueError, AttributeError):
            message = "Review request failed."
        raise SystemExit(f"{message} (HTTP {response.status_code})")
    result = response.json()
    if not isinstance(result, dict):
        raise SystemExit("The review service returned an invalid response.")
    return result


def _reviewer_id(value: str | None) -> str:
    candidate = value or input("Reviewer ID (letters, digits, dot, dash, underscore): ").strip()
    if not REVIEWER_PATTERN.fullmatch(candidate):
        raise SystemExit("Reviewer ID must be 3–80 safe identifier characters.")
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Review a GitHub control proof and explicitly decide adult/public-professional "
            "eligibility for this local self-audit."
        )
    )
    parser.add_argument("verification_id")
    parser.add_argument("--reviewer")
    parser.add_argument("--api-base", default="http://localhost:8800")
    parser.add_argument("--decision", choices=("approve", "deny"))
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required with --decision for a non-interactive decision.",
    )
    args = parser.parse_args()
    if args.decision and not args.confirm:
        raise SystemExit("--decision requires --confirm.")

    settings = get_settings()
    base = args.api_base.rstrip("/")
    resource = f"{base}/v1/prototype/eligibility-verifications/{args.verification_id}"
    summary = _request_json(
        "GET",
        resource,
        admin_token=settings.prototype_admin_token,
    )
    print(f"Profile: {summary.get('canonical_profile_url')}")
    print(f"Purpose: {summary.get('purpose')}")
    print(f"Control verified: {summary.get('control_verified_at')}")
    print(f"Review deadline: {summary.get('review_expires_at')}")
    print(f"Current state: {summary.get('internal_state')}")
    print()
    print(
        "Approval is allowed only after independently confirming that this is an adult "
        "profile in the approved public professional/creator scope."
    )

    reviewer_id = _reviewer_id(args.reviewer)
    if args.decision:
        decision = args.decision
    else:
        entered = input("Type APPROVE or DENY: ").strip().casefold()
        if entered not in {"approve", "deny"}:
            raise SystemExit("No decision recorded.")
        decision = entered

    review_code = (
        "adult_public_professional_context_confirmed"
        if decision == "approve"
        else "unable_to_confirm_scope"
    )
    result = _request_json(
        "POST",
        f"{resource}/decision",
        admin_token=settings.prototype_admin_token,
        payload={
            "decision": decision,
            "review_code": review_code,
            "reviewer_id": reviewer_id,
        },
    )
    print(f"Decision recorded. Public status: {result.get('status')}")
    if result.get("eligibility_expires_at"):
        print(f"Eligibility expires: {result['eligibility_expires_at']}")


if __name__ == "__main__":
    main()
