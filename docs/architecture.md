# Prototype architecture

The prototype preserves the planned control-plane boundaries while adding one tightly
scoped live adapter for a user-controlled GitHub profile.

```text
Web
 ├─ synthetic demo ────────────────────────────────────────────────┐
 └─ GitHub URL → control challenge → operator scope decision ─────┤
                                                                  v
FastAPI → PostgreSQL transaction → SearchJob / JobAttempt / ProviderRun
                                └→ safe JobEvent / OutboxMessage
Outbox dispatcher → Redis/Celery → fixture adapter or GitHub adapter
GitHub adapter → Safe Fetch → fixed api.github.com user endpoint
Worker → immutable collection snapshot → analysis revision → report revision
Web ← PostgreSQL-backed polling and SSE replay
```

PostgreSQL owns lifecycle and report state. Redis is disposable delivery
infrastructure. Workers are idempotent, check the job acceptance epoch, and refuse to
persist after suppression, deletion, eligibility expiry, or GitHub account-ID mismatch.

## Admission and eligibility

The live path accepts only a direct `https://github.com/{login}` URL. Canonicalization:

- requires HTTPS and the exact `github.com` host;
- rejects credentials, custom ports, query strings, fragments, percent-encoding,
  backslashes, non-ASCII input, and extra path segments;
- validates the GitHub login grammar; and
- case-folds the login and emits one canonical URL.

The canonical URL is indexed using a versioned keyed HMAC and encrypted with Fernet in
the eligibility and job input records. It is decrypted only at the narrow service or
worker boundary that needs it.

Eligibility has two independent steps:

```text
verification_pending
  └─ matching temporary token in public GitHub bio
      → control_verified_review_pending
          └─ restricted operator confirms adult + public-professional scope
              → eligible_verified_self (24-hour default)
```

The challenge is returned only at creation, stored as a keyed HMAC, expires after 30
minutes by default, and is cleared when the flow terminates or advances. The GitHub API
body and bio are transient. Proof of control does not prove age or approved scope.

When control succeeds, the numeric GitHub account ID is stored as a keyed HMAC. Before
persisting provider output, the worker resolves the profile again and requires the same
account-ID HMAC. A renamed account can remain bound to the same account in a future
canonicalization design, but the current adapter also requires the returned canonical
URL to match the submitted handle; reassignment or mismatch fails closed.

## Safe Fetch boundary

`SafeFetchGateway.fetch_github_user` is the only live network operation. It constructs
`https://api.github.com/users/{validated-login}` itself; callers cannot supply a host,
port, scheme, query, or redirect destination. The legacy generic `fetch(url)` method
always raises.

The gateway:

- resolves only `api.github.com:443` and rejects the entire answer set if any address is
  non-global, private, loopback, link-local, multicast, reserved, or unspecified;
- requires the connected peer IP to be observable and global;
- uses HTTPS `GET`, `trust_env=false`, and `follow_redirects=false`;
- rejects every redirect rather than following `Location`;
- sends `Accept: application/vnd.github+json` and `Accept-Encoding: identity`;
- optionally sends a server-only bearer token;
- accepts only JSON media types and identity encoding;
- enforces both `Content-Length` and streamed-byte limits (256 KiB by default); and
- applies connect, read, and wall-clock deadlines (3, 5, and 8 seconds by default).

This is a fail-closed application boundary for local evaluation. It is not a substitute
for production DNS pinning, an egress proxy/firewall, workload isolation, audited secret
storage, or provider-specific quota and circuit-breaker infrastructure.

## Provider and evidence boundary

The fixture adapters still load version-controlled JSON and never use a network client.
The GitHub adapter accepts only a valid `User` response whose `login`, `html_url`, and
numeric `id` agree with the submitted profile. It may emit:

- the safe display name, falling back to the login; and
- the control-verified canonical profile URL.

It does not emit the bio, email, location, company, blog, avatar, social counts, or
arbitrary fields. The adapter returns structured observations, not claims or prose.
Deterministic correlation and reporting remain the only output path; there is no LLM
client.

## Prototype-only deviations

- Authentication is a fixed local browser token plus user UUID; administration uses a
  separate fixed local token. Production mode refuses this configuration.
- The GitHub provider has only project-owner authorization for limited local evaluation;
  it is not `approved_for_mvp`.
- Network egress is constrained in application code, not enforced by infrastructure.
- The operator review is a local CLI, not a production-grade adjudication system.
- PostgreSQL-backed event polling is used without the optional Redis wake-up
  optimization.
- Full automated retention sweeps, key rotation, OAuth, quotas, dashboards, and incident
  automation remain incomplete.
