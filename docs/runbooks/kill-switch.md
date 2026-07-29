# Local prototype kill switches

These controls are for the single-user localhost prototype. They are not a substitute
for production incident response, centrally managed configuration, audited access, or
infrastructure egress controls.

## Stop the GitHub provider

Set:

```dotenv
GITHUB_PROVIDER_ENABLED=false
```

Restart the API and worker. New GitHub verification requests and new GitHub jobs return a
safe provider-disabled response. Already queued GitHub work is fenced as
`policy_blocked` before a provider lease is issued; the registry also fails closed as
`skipped_circuit_open` if it is reached during a switch race. Neither path persists
source evidence. The synthetic demo remains available unless the global jobs switch is
also off.

Use this first for suspected provider-policy change, schema drift, unexpected traffic,
rate-limit pressure, Safe Fetch regression, or possible real-data leakage.

## Stop all new jobs

Set:

```dotenv
PROTOTYPE_JOBS_ENABLED=false
```

Restart the API. New jobs return `prototype_disabled`. This does not by itself revoke
existing report reads or disable eligibility endpoints, so combine it with the provider
and report-read switches when containment requires both.

## Revoke report reads

Set:

```dotenv
PROTOTYPE_REPORT_READS_ENABLED=false
```

Restart the API. Brief and evidence reads fail closed. Existing database rows are not
deleted by this switch.

## Suppress one profile

The restricted local admin endpoint accepts the exact allowlisted profile URL:

```bash
curl -i \
  -H "X-Prototype-Admin-Token: $PROTOTYPE_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"profile_url":"https://github.com/example"}' \
  http://localhost:8800/v1/prototype/suppressions
```

Suppression stores a keyed-HMAC identifier, invalidates matching eligibility, fences
matching in-flight work, blocks future work, and revokes matching report reads without
exposing the suppression reason. This local endpoint does not provide an unsuppress
operation; inspect the incident before altering data manually.

## Delete one job

An owner can delete a job through `DELETE /v1/search-jobs/{job_id}`. Deletion removes
per-job state and unreferenced source documents, then writes a seven-day tombstone to
prevent queued work from resurrecting the job. It does not delete the separate
eligibility or suppression record.

## Recovery

Before re-enabling a provider:

1. identify the triggering condition without logging profile content;
2. run contract, Safe Fetch, eligibility, provider, and suppression tests;
3. confirm the provider remains within the exact local matrix scope;
4. rotate a potentially exposed server token or encryption/HMAC key using a deliberate
   migration rather than an in-place ad hoc edit; and
5. restart the API and workers and perform only a controlled owner-profile check.

Do not re-enable the GitHub adapter for alpha or production based on this runbook; that
requires a separate provider and release approval.
