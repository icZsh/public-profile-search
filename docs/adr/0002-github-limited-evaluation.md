# ADR 0002: GitHub direct-URL local limited evaluation

Status: accepted for project-owner local limited evaluation; not approved for MVP,
invite alpha, production, public deployment, third-party targets, or bulk benchmarks

## Context

The fixture-only vertical slice proved orchestration and deterministic evidence flow but
could not exercise an editable real public-profile URL. Enabling arbitrary URLs,
username discovery, or automatic eligibility would materially exceed the approved
product and safety boundary.

A self-control challenge can show that the local user controls a profile, but it cannot
establish adulthood or that the profile is in the approved public-professional/creator
scope. GitHub handles can also be renamed or reassigned, so a URL alone is not a stable
account identity.

## Decision

Add one provider, `github_public_profile_v1`, under these constraints:

1. Accept only a direct HTTPS URL on the exact `github.com` host with one valid login
   path segment. Reject credentials, ports, query/fragment/encoded ambiguity, arbitrary
   URLs, and username-only discovery.
2. Keep the synthetic fixture path as the no-network demo and deterministic benchmark.
3. Prove control with a random token temporarily placed in the public GitHub bio. Store
   only a keyed HMAC of the token and process the API body and bio transiently.
4. Require a separate restricted operator decision confirming adult and
   public-professional/creator scope. Control proof alone never issues eligibility.
5. Make review-pending state and issued approval expire after 24 hours by default.
6. Encrypt canonical URL inputs in eligibility and job rows and use a versioned keyed
   HMAC for matching/suppression.
7. Bind the verification to GitHub's stable numeric account ID as a keyed HMAC and
   recheck it before provider output is persisted.
8. Route the only network call through a fail-closed Safe Fetch method that constructs
   the fixed `api.github.com/users/{login}` destination, rejects unsafe DNS/peer IPs and
   redirects, disables environment proxies, requires JSON/identity encoding, bounds
   response bytes, and applies short deadlines. Keep generic URL fetching disabled.
9. Retain only a sanitized display name and canonical public profile URL as evidence.
   Do not retain the bio, response body, email, location, company, blog, avatar, counts,
   or raw numeric account ID.
10. Provide `GITHUB_PROVIDER_ENABLED` as the per-provider kill switch. Keep the optional
    GitHub API token server-side.

## Authorization statement

`approved_for_limited_evaluation` records only the project owner's authorization for a
single-user localhost self-audit. It is not GitHub endorsement, broad provider-terms or
legal approval, privacy/security signoff, commercial authorization, or
`approved_for_mvp`. This ADR cannot be used to authorize automated live benchmarks,
shared use, invite-alpha traffic, or production deployment.

## Consequences

- The web UI can accept an editable real profile URL without becoming a people-search
  product.
- Eligibility is intentionally slower and requires local human judgment.
- Handle reassignment fails closed before persistence because account-ID binding is
  rechecked.
- The stored evidence is useful but narrow: a public display name and the
  control-verified input profile only.
- Provider failures remain structured and never become “no account” by implication.
- The application Safe Fetch boundary reduces SSRF and hostile-response risk in local
  evaluation.

## Remaining blockers

- Application checks do not enforce infrastructure-level egress isolation or DNS
  pinning.
- Fixed prototype tokens and the CLI reviewer are not production authentication or
  authorization.
- Provider/legal/privacy review, quota and cost policy, complete retention, key
  rotation, subject-rights workflow, observability, incident drills, independent
  quality measurement, and production hosting remain open.
- GitHub must remain **not `approved_for_mvp`** until a separate signed decision updates
  the provider and release matrices.
