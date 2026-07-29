# Prototype privacy boundary

## Allowed input and purpose

- The only live input is a direct public GitHub profile URL controlled by the local user.
- The only live purpose is `self_audit` with `target_relationship=self`.
- Username discovery, arbitrary URLs, recursive pivots, credentials, cookies, private
  profiles, and third-party targets are not supported.
- A bundled `.test` fixture remains available without real-profile processing.

`github_public_profile_v1` has project-owner authorization for this local,
single-user evaluation only. That is not broad provider/legal approval, MVP approval,
or permission for production, shared use, or bulk collection.

## Eligibility minimization

The temporary GitHub bio challenge proves account control only. A separate restricted
operator must confirm that the profile is adult and within the approved public
professional/creator scope. Unknown scope is denied; the system does not persist a
guessed age, vulnerability label, or other sensitive inference.

- The challenge is returned once and stored only as a keyed HMAC.
- The fetched GitHub response body and bio are processed in memory and never written as
  evidence, logs, or review data.
- The numeric GitHub account ID is retained only as a keyed HMAC so the worker can detect
  handle reassignment before persistence.
- Control-proof review expires after 24 hours by default; an approval also expires after
  24 hours by default.

## Stored data

- Raw submitted URL spelling is not retained. The canonical input URL is encrypted in
  eligibility and job records and separately indexed using a versioned keyed HMAC.
- After an approved job runs, the public canonical profile URL and a sanitized display
  name may be stored as display-approved evidence and report data.
- GitHub email, location, company, blog, avatar, follower/following counts, bio, and
  unapproved response fields are not persisted.
- Logs and public errors use IDs and safe statuses, never profile content, bio text,
  challenge values, or suppression reasons.
- Jobs, observations, and reports carry a 30-day expiry under the current local policy.
  The job deletion endpoint removes per-job evidence immediately and leaves a seven-day
  resurrection tombstone. The current retention worker only removes expired tombstones
  and expired orphan source documents; a complete production retention sweeper remains
  a release blocker.

## Revocation and deletion

A keyed-HMAC suppression record blocks new verification/work, invalidates matching
eligibility, fences in-flight writes, and revokes matching report reads. User job
deletion removes the job's observations, claims, report revisions, provider records,
events, idempotency state, and unreferenced source documents.

These local controls do not complete the plan's jurisdiction, provider terms, notice,
subject-rights, retention, backup, key rotation, privacy, or security reviews. Real
profile processing must remain local and limited until those gates are independently
satisfied.
