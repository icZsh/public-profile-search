# Provider matrix

| Provider ID | Kind | Evaluation status | MVP status | Network destination | Allowed retained data | Scope and volume | Kill switch |
|---|---|---|---|---|---|---|---|
| `fixture_primary_v1` | synthetic fixture | `prototype_only` | test-only | none | bundled synthetic fields | local deterministic demo/tests | remove from registry or stop all jobs |
| `fixture_linked_v1` | synthetic fixture | `prototype_only` | test-only | none | bundled synthetic fields | local deterministic demo/tests | remove from registry or stop all jobs |
| `github_public_profile_v1` | GitHub REST public user record | `approved_for_limited_evaluation` | **not `approved_for_mvp`** | fixed `https://api.github.com/users/{login}` only | sanitized public display name and canonical public profile URL; account ID only as keyed HMAC; bio/body not retained | project-owner, single-user localhost self-audit; interactive profile-control and operator review required; no username discovery, batch collection, automated live benchmark, shared service, or production | `GITHUB_PROVIDER_ENABLED=false` |

## Meaning of the GitHub status

The GitHub entry records the project owner's local authorization to exercise a minimal
public-user endpoint while evaluating this code path. It is not GitHub endorsement,
provider terms approval, legal or privacy signoff, commercial-use approval, permission
for bulk probes, or authorization to process third-party targets.

The adapter must never be described or promoted as `approved_for_mvp` from this record.
Invite alpha, staging, production, public deployment, and automated live benchmarking
remain blocked until a separate provider/legal/privacy/security review explicitly
changes the matrix and records reviewer, jurisdiction, volume, retention, quota, cost,
and incident conditions.

## Limited-evaluation conditions

- Purpose is `self_audit` and the submitter must prove profile control.
- A separate local operator confirms adult and public-professional/creator scope.
- Approval expires after 24 hours by default and is rechecked before fetch, persistence,
  and display.
- Only the fixed GitHub user endpoint may be called; the optional API token is
  server-side and never user supplied.
- The response body and bio are transient. Only the fields listed in
  [`provider-contracts.md`](./provider-contracts.md) may cross the adapter boundary.
- The provider kill switch must be available before any live local run.
