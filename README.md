# Public Profile Search

A local prototype that starts with a social-media handle, checks a promoted subset of
the [Maigret](https://github.com/soxoj/maigret) username catalog, and progressively
builds a map of possible accounts and identifiers.

The Maigret-backed discovery flow supports:

- a handle with an optional source platform;
- two explicit modes:
  - **Quick** runs the reproducible 20-site catalog, then gives Exa-only professional
    retrieval a focused envelope of at most two name hypotheses, six queries/requests,
    ten unique profiles, and 40 seconds;
  - **Deep** runs a reproducible 56-site catalog across eight shards and the full
    configured Exa + GitHub adaptive-retrieval envelope, then adds the richer
    source-grounded narrative pass;
- progressive candidate results while the remaining shards are still running;
- distinct found, not-found, unknown, and inapplicable outcomes;
- extracted public usernames and links with their discovery lineage; and
- bounded first-party metadata verification for supported profile pages;
- a name-derived professional-search wave backed by optional Exa people search and
  GitHub's public profile API;
- a deterministic account-association pass that keeps account existence separate from
  real-world identity; and
- an evidence-linked account- or person-centric brief with explicit qualifications and
  coverage limitations;
- optional Deep-mode source-grounded narrative synthesis through either OpenRouter's
  stateless Responses API or the direct OpenAI Responses API, with strict structured
  output, citation validation, contact redaction, and a deterministic fallback. New
  Deep reports follow the fixed
  [person report template](./docs/report-template-v4.md), answering identity, probable
  location, occupation, education, interests, likes, dislikes, and unknowns, with v4
  adding only an evidence-linked career and education timeline before the underlying
  account detail; and
- idempotent creation, owner-scoped reads, cancellation/deletion fences, and catalog
  provenance.

Matching handles and name-search hits are candidates, not assertions that every account
belongs to the same person. A brief becomes person-centric only when exactly one public
full-name hypothesis also has an independent professional anchor such as a compatible
broad location or an exact public social-handle link. The earlier eligibility-gated
Fast Brief remains
available at `/search/{jobId}` for regression coverage, but the homepage now opens the
cross-platform discovery flow.

## Local setup

Prerequisites: Node 22+, npm 10+, Python 3.12–3.14, `uv`, and Docker.

```bash
cp .env.example .env
make bootstrap
make services
make migrate
```

Run these in separate terminals:

```bash
make api
make worker-maigret
make worker-professional
make worker-synthesis
make dispatcher
make web
```

Open `http://localhost:3417` and enter a public handle or supported public profile URL.
The browser polls the owner-scoped job and candidate endpoints while
the Maigret worker checks each shard, then renders the frozen evidence-linked brief.
The outbox dispatcher also reclaims expired worker leases and closes jobs at their
retrieval cutoff, so a lost task cannot leave discovery permanently in progress.
After the root shards finish, the professional worker processes the mode-specific
adaptive second wave. Exa is optional: set the server-only `EXA_API_KEY` to enable indexed
LinkedIn people results. Quick intentionally skips professional retrieval when Exa is
unavailable; Deep can still use the GitHub public-profile path without it.

To keep the complete local stack running after terminal closure and restart it at
login, install the macOS LaunchAgent:

```bash
./scripts/install-tracebrief-service.sh
```

The persistent service is available at
`http://isaaczhus-mac-mini.local:3500`. It uses a same-origin `/api` proxy so the
page works from another device on the same trusted LAN while the API remains bound
to loopback. See [the persistent service runbook](./docs/persistent-local-service.md)
for status, logs, and removal commands.

Deep story composition is gateway-configurable. The checked-in example selects
`GROUNDED_SYNTHESIS_PROVIDER=openrouter`; add a server-only `OPENROUTER_API_KEY` and
choose an OpenRouter model slug with `OPENROUTER_SYNTHESIS_MODEL` (default:
`~deepseek/deepseek-v4-flash-latest`, OpenRouter's rolling DeepSeek V4 Flash
alias). The browser's Deep-mode picker instead snapshots one curated OpenRouter model
per job. It includes GPT-5.6 Luna, GPT-5.4 Nano, and GPT-5.4 Mini, plus the
open-weight GPT-OSS 120B, DeepSeek V4 Flash, Qwen3.5 35B-A3B, and GLM 5.2.
The selection remains stable while retrieval runs. API clients that omit
`synthesis_model` continue to use the configured gateway and model. Direct OpenAI
remains available with
`GROUNDED_SYNTHESIS_PROVIDER=openai`, `OPENAI_API_KEY`, and
`OPENAI_SYNTHESIS_MODEL`. OpenRouter requests use its fixed
[`/api/v1/responses`](https://openrouter.ai/docs/api/reference/responses/overview)
endpoint and require a route that supports the requested structured-output parameters.
The optional `OPENROUTER_HTTP_REFERER` and `OPENROUTER_APP_TITLE` values provide
[app attribution](https://openrouter.ai/docs/app-attribution).

Without the selected gateway's key, retrieval still completes, but the result is
explicitly labeled as a partial, Quick-grade deterministic fallback rather than a
completed Deep story. The gateway never controls account association or source
identity—the host revalidates every cited source before rendering its narrative.

The scan intentionally uses Maigret as a Python library rather than shelling out to its
CLI. Runtime settings are fixed by the host application: catalog updates, enrichment,
internal retries, domain checks, cookies, proxies, Tor/I2P, and Cloudflare bypass are
disabled. The package version and embedded catalog SHA-256 must match
[`config/maigret-catalog-v0.6.3.json`](./config/maigret-catalog-v0.6.3.json) before a
scan starts.

## Services and controls

- `PROTOTYPE_JOBS_ENABLED=false` rejects all new jobs.
- `MAIGRET_ENABLED=false` stops new Maigret jobs and prevents queued scans from running.
- `MAIGRET_RUN_LEASE_SECONDS` controls the worker lease.
- `MAIGRET_MAX_SHARDS_PER_JOB` caps the number of catalog shards a request can create;
  the promoted Quick and Deep profiles require three and eight shards, respectively.
- `PROFESSIONAL_SEARCH_ENABLED=false` disables the second wave.
- `PROFESSIONAL_SEARCH_MAX_RESULTS_PER_QUERY` and
  `PROFESSIONAL_SEARCH_MAX_GITHUB_PROFILES` are hard-capped at 5 and 3.
- `ADAPTIVE_PROFESSIONAL_SEARCH_MAX_NAMES`,
  `ADAPTIVE_PROFESSIONAL_SEARCH_MAX_QUERIES`,
  `ADAPTIVE_PROFESSIONAL_SEARCH_MAX_REQUESTS`,
  `ADAPTIVE_PROFESSIONAL_SEARCH_MAX_PROFILES`, and
  `ADAPTIVE_PROFESSIONAL_SEARCH_BUDGET_SECONDS` define Deep's aggregate retrieval
  envelope and upper-bound Quick. Quick also applies product caps of 2 names, 6
  queries/requests, 10 profiles, and 40 seconds and uses Exa only. Expired adaptive
  leases terminate instead of replaying a possibly consumed request envelope.
- `EXA_PEOPLE_SEARCH_ENABLED` and `GITHUB_PEOPLE_SEARCH_ENABLED` are independent
  provider kill switches; `EXA_API_KEY` and `GITHUB_API_TOKEN` remain server-only.
- `GROUNDED_SYNTHESIS_ENABLED=false` disables the optional LLM pass.
  Retrieval remains bounded by the job deadline, while Deep story composition has no
  wall-clock cutoff. Evidence limits, model, reasoning effort, and output-token limit
  remain server-side and bounded. Transient provider failures are retried according to
  `GROUNDED_SYNTHESIS_MAX_ATTEMPTS` with cancellation-aware exponential backoff.
- `PROTOTYPE_REPORT_READS_ENABLED=false` disables both legacy and footprint brief
  reads without stopping collection.

The local browser token is intentionally visible because this is a single-user
prototype. The API still rejects `APP_ENV=production` while prototype authentication is
enabled. Replace authentication, authorization, rate limits, provider review, privacy
review, and network egress controls before shared or production use.

Maigret performs live requests to third-party sites. Results can be stale or ambiguous,
and site behavior can change independently of this application. Use the prototype
responsibly and follow applicable site rules and law. See
[`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md) for license attribution.

## Verification

```bash
make contracts
make lint
make test
make build
```

`make worker` remains available for the legacy Fast Brief provider queue.
