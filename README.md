# Public Profile Search

A local, eligibility-gated prototype of the evidence-backed Fast Brief described in
[`public-profile-search-project-plan.md`](./public-profile-search-project-plan.md).

The app now supports two deliberately narrow paths:

- an editable direct `https://github.com/{login}` URL for a profile the local user
  controls; and
- the bundled synthetic fixture, which remains available as a no-network demo.

Username-only discovery, arbitrary URLs, recursive account search, private data,
credentials, external LLMs, sharing, and public deployment remain unavailable.

## Authorization boundary

`github_public_profile_v1` is marked `approved_for_limited_evaluation` only for this
project owner's single-user, local self-audit workflow. That repository status is not
GitHub endorsement, broad provider or legal approval, permission for bulk collection,
`approved_for_mvp`, or authorization for a shared or production service.

The API rejects `APP_ENV=production` while prototype authentication is in use. Keep the
service on localhost and do not expose either prototype token.

## Local setup

Prerequisites: Node 22+, npm 10+, Python 3.12–3.14, `uv`, and Docker.

```bash
cp .env.example .env
```

Generate a local URL-encryption key and place it in `.env` as
`PROFILE_URL_ENCRYPTION_KEY`:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Then install dependencies, start PostgreSQL and Redis, and migrate:

```bash
make bootstrap
make services
make migrate
```

Run these in separate terminals:

```bash
make api
make worker
make dispatcher
make web
```

Open `http://localhost:3417`.

`GITHUB_API_TOKEN` is optional and server-side only. It can be used for the fixed GitHub
REST request when local unauthenticated API quota is insufficient. Never expose it with
a `NEXT_PUBLIC_` prefix or enter a user token in the web UI.

## Real GitHub self-audit flow

1. Enter the full public GitHub profile URL you control.
2. The API returns a random `tracebrief-…` challenge. Temporarily place it in the public
   GitHub bio and choose **Verify control**. The challenge expires after 30 minutes and
   the default flow permits five checks with a short cooldown.
3. The service reads the bio only in memory. A match proves control of that account, not
   that the profile belongs to an adult or is in the approved public-professional scope.
4. A local operator independently reviews that scope and records a decision:

   ```bash
   uv run python scripts/approve_eligibility.py <verification-id>
   ```

   For a deliberate non-interactive local decision:

   ```bash
   uv run python scripts/approve_eligibility.py <verification-id> \
     --reviewer local-reviewer --decision approve --confirm
   ```

5. Refresh approval in the UI, remove the challenge from the bio, and build the brief.

Both the review window and an issued approval default to 24 hours. A job must reference
the same owner, canonical URL, provider, purpose, and policy version. The worker also
binds the control proof to GitHub's stable numeric account ID using a keyed HMAC and
blocks persistence if the handle resolves to a different account later.

The **Run synthetic demo** action skips real-profile verification and uses only bundled
`.test` fixtures.

## Safe Fetch and stored data

The live adapter cannot fetch a user-supplied destination. It maps the validated GitHub
handle to the fixed `https://api.github.com/users/{login}` endpoint and:

- requires global DNS answers and an observable global connected-peer IP;
- disables environment proxies and redirects;
- accepts JSON only with identity content encoding;
- caps both declared and streamed bodies at 256 KiB by default;
- applies 3-second connect, 5-second read, and 8-second total deadlines by default; and
- leaves the generic URL-fetch interface disabled.

Canonical submitted URLs are encrypted in eligibility and job records and separately
indexed by keyed HMAC. The control challenge and stable GitHub account ID are stored only
as keyed HMACs. GitHub's response body and bio are not persisted. After an eligible job
runs, the display-approved public profile URL and safe display name may be retained as
source-backed evidence; email, location, company, blog, avatar, follower counts, and bio
are excluded.

These application checks do not replace production network egress isolation, secret
management, session authentication, provider review, privacy review, or a complete
retention service.

## Kill switches

Set `GITHUB_PROVIDER_ENABLED=false` and restart the API and worker to stop new GitHub
verifications and provider runs. `PROTOTYPE_JOBS_ENABLED=false` rejects all new jobs;
`PROTOTYPE_REPORT_READS_ENABLED=false` blocks brief and evidence reads. See
[`docs/runbooks/kill-switch.md`](./docs/runbooks/kill-switch.md) for the local response
procedure.

## Verification

```bash
make contracts
make lint
make test
make build
```

The browser token is intentionally visible because this is a single-user local
prototype. Replace the entire authentication, authorization, provider-approval, and
deployment boundary before any shared use.
