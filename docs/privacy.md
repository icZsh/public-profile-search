# Prototype privacy boundary

## Allowed input and purpose

The local prototype has two bounded flows:

- The current footprint homepage accepts a public handle, a platform-qualified handle,
  or a supported public profile URL and searches only the configured public-data
  providers and catalog sites.
- The earlier Fast Brief flow accepts a direct public GitHub profile URL controlled by
  the local user and remains limited to `self_audit` with
  `target_relationship=self`.
- A bundled `.test` fixture remains available without real-profile processing.

Neither flow authorizes credentials, cookies, private profiles, facial recognition,
contact-detail enrichment, or unbounded recursive pivots. Provider results are public
candidates, not proof that accounts belong to one person. The configured live adapters
have project-owner authorization for this local, single-user evaluation only. That is
not broad provider/legal approval, MVP approval, or permission for production, shared
use, or bulk collection.

## Owner scope and prototype authentication

History and all footprint reads are server-backed and scoped to the user ID supplied by
the prototype authentication headers. Responses use private/no-store caching; the
browser does not create a second history database in local storage.

This is not production multi-user isolation. The checked-in local setup gives the
browser a visible token and a fixed prototype user ID. Any browser or trusted-LAN
device configured with those same values is treated as the same owner and can see and
delete the same jobs and history. The application rejects production mode while this
authentication model is enabled.

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

- Footprint jobs store the submitted handle/platform seed and normalized seed metadata.
  Supported canonical input URLs are encrypted, and equivalent seeds are indexed with
  a versioned keyed HMAC. The exact normalized platform/handle groups a supported
  profile URL with its platform-qualified handle; a bare handle remains a separate
  group.
- Search history is not a second copy of results. It is a minimized owner-scoped view
  over the existing job, candidate-count, status, and report-availability records.
- Approved public account fields, source observations, account-association decisions,
  claims, and report revisions may be retained for a completed footprint job. The
  rendered brief excludes private contact details and fields outside the display
  policy.
- The legacy GitHub eligibility flow still encrypts its canonical input URL and indexes
  it with a versioned keyed HMAC. GitHub email, avatar, follower/following counts, bio,
  and other unapproved eligibility-response fields are not persisted as evidence.
- Logs and public errors use IDs and safe statuses, never profile content, bio text,
  challenge values, or suppression reasons.

## Reopening and refreshed searches

Submitting the same exact seed can reopen the latest unexpired active or usable run
when mode, selected model, and locale also match. Reopening reads the existing job; it
does not represent a new observation or make old evidence current.

An explicit refresh creates a separate job using the source run's user-selected seed,
mode, locale, and Deep model choice, but the current provider catalog, budgets, and
policy. Only an unexpired `ready` or `ready_partial` run with active report access and
at least one candidate can supply planning hints. Previously positive sites and
professional names/candidates may be prioritized, but every selected site and returned
profile is freshly retrieved and must pass the current association rules.

Refresh never copies old account nodes, observations, claims, reports, negative
results, anchor choices, or identity conclusions. Synthesis and finalization consume
only the new job's observations. Reuse events contain safe counts rather than profile
content. If the source is deleted while a refresh is running, its lineage reference is
removed and the refresh continues without later historical hints.

## Retention and deletion

Jobs, observations, reports, and their history views expire after 30 days under the
current local policy. Expiry is enforced on owner-facing footprint reads. A separately
timed hourly dispatcher sweep fences late worker writes and physically deletes expired
jobs in small locked batches, including anomalously active jobs. Sweep failures are
isolated from normal dispatch and watchdog maintenance and retry on the next interval.

Deleting an individual terminal run removes its observations, claims, report
revisions, provider records, events, idempotency state, and unreferenced source
documents. Clearing history is also permanent but bounded: each request deletes only a
small batch of terminal jobs, and the UI repeats requests until the batch response says
it is complete. Queued and discovering jobs are preserved. Deletion leaves a temporary
write-fence tombstone so late worker results cannot resurrect removed data; expired
tombstones and orphan source documents are also swept.

## Revocation and deletion

A keyed-HMAC suppression record in the legacy eligibility flow blocks new
verification/work, invalidates matching eligibility, fences in-flight writes, and
revokes matching report reads.

These local controls do not complete the plan's jurisdiction, provider terms, notice,
subject-rights, backup, key rotation, privacy, or security reviews. The automated
30-day sweep is a prototype control, not a complete production retention program. Real
profile processing must remain local and limited until those gates are independently
satisfied.
