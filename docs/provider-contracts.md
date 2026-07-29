# Provider contract

A provider returns canonical execution status plus structured source observations. It
cannot emit claims, confidence decisions, eligibility decisions, or report prose.

## Canonical provider-run status

```text
pending | leased | running | retry_scheduled |
success | no_result | timeout | rate_limited | captcha_blocked |
auth_required | invalid_response | provider_error |
skipped_budget | skipped_circuit_open | closed_at_finalization | cancelled
```

`no_result` means the provider gave a valid, authoritative negative response. Timeouts,
rate limits, access failures, unsafe responses, disabled providers, and missing tools
must retain their distinct status and must never be translated into “no account.”

The current prototype registers:

- `fixture_primary_v1`
- `fixture_linked_v1`
- `github_public_profile_v1`

## GitHub adapter input contract

The adapter receives an already canonicalized, decrypted
`https://github.com/{normalized-login}` value from the worker. It cannot fetch that URL
or any arbitrary URL. It passes only the validated login to Safe Fetch, which constructs
the exact `https://api.github.com/users/{login}` request.

A response is eligible for extraction only when:

- the HTTP status is 200 and the payload is a JSON object;
- `type` is exactly `User`;
- `login` matches the normalized submitted handle;
- `id` is a positive integer; and
- `html_url` canonicalizes to the exact submitted profile URL.

The numeric `id` becomes `github-account-v1:{id}` transiently and is keyed-HMACed for
lineage and eligibility binding. The raw account ID is not stored.

## Allowed output

One successful GitHub response produces one `verified_input_profile` observation:

| Field | Handling |
|---|---|
| `login` | identity validation and safe fallback display name |
| `name` | whitespace-normalized, capped at 120 characters, rejected as a display name if it contains control characters or resembles contact data |
| `html_url` | exact canonical-profile validation and display-approved evidence URL |
| `id` | transient stable-account binding; stored only as keyed HMAC |
| `bio` | transient eligibility challenge scan only; never emitted or persisted |

All other response fields—including email, location, company, blog, avatar, follower
counts, and arbitrary metadata—are ignored.

## GitHub status mapping

| Condition | Provider status | Error code |
|---|---|---|
| Valid 200 `User` payload with matching identity | `success` | none |
| HTTP 404 | `no_result` | `github_profile_not_found` |
| HTTP 403 or 429 | `rate_limited` | `github_rate_limited` |
| HTTP 401 | `auth_required` | `github_auth_required` |
| HTTP 5xx | `provider_error` | `github_unavailable` |
| Network deadline exceeded | `timeout` | `safe_fetch_network_timeout` |
| Redirect, invalid MIME/encoding/length, oversize body, invalid JSON, malformed schema, or identity mismatch | `invalid_response` | specific safe-fetch or GitHub validation code |
| Other DNS, network, peer-observation, or Safe Fetch failure | `provider_error` | specific `safe_fetch_*` code |
| Provider switch closes after lease but before registry dispatch | `skipped_circuit_open` | `github_provider_disabled` |
| Unregistered provider ID | `provider_error` | `provider_not_registered` |

Safe Fetch error messages are generic and exclude the profile URL and login. The API
maps eligibility-check rate limits to `provider_rate_limited`; other unsafe or
unavailable checks become a safe `service_unavailable` response.

The worker checks the provider switch before leasing a queued GitHub run. A disabled
queued job therefore becomes `policy_blocked`; the registry status above is a second
fail-closed guard for an in-flight switch race.

## Fixture contract

Fixture adapters have no HTTP client and load only bundled JSON. They remain the
deterministic correctness and benchmark path. A fixture adapter status must follow the
same canonical status vocabulary as a live adapter.
