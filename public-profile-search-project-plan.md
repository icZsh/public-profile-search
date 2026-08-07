---
title: Digital Footprint Finder — Project Plan
aliases:
  - Public Profile Search
  - Cross-platform Identity Explorer
status: proposed
owner: Isaac
created: 2026-07-22
updated: 2026-08-06
version: "3.5"
tags:
  - project
  - identity-resolution
  - social-discovery
  - digital-footprint
  - osint
---

# Digital Footprint Finder — Project Plan

> **v3.5 mode-specific retrieval + multi-gateway Deep story plan:** Given a user ID, use Maigret as the primary
> cross-platform account-discovery engine, explain which discovered accounts may
> represent the same person, adaptively retrieve professional context, and build either
> a concise evidence report or a source-grounded LLM story.

The existing codebase is a useful technical starting point, but its current
GitHub-URL-and-ownership-verification flow is not the product described here. This plan
supersedes the earlier eligibility-gated, direct-URL-only MVP plan.

---

## 1. Product definition

### 1.1 Core promise

A user supplies a platform-scoped ID such as `github:icZsh`, a full profile URL, or a
bare handle. The product then:

1. resolves the seed account;
2. discovers profiles, websites, feeds, and authored pages that may be related;
3. builds an explorable identity graph;
4. shows the evidence for and against every proposed relationship;
5. lets the user steer the graph by accepting, rejecting, merging, splitting, or
   expanding candidates; and
6. generates a sourced digital-footprint summary from the chosen graph revision.

The first implementation uses
[Maigret](https://github.com/soxoj/maigret) as the **core username and identifier
discovery substrate**. Maigret supplies broad, catalog-driven account checks and
extracts linked usernames, profile URLs, and provider IDs. This application remains
responsible for seed resolution, durable orchestration, provenance, identity
correlation, contradictions, user decisions, and footprint synthesis. A Maigret
`CLAIMED` result means “this account appears to exist,” not “this is the same person.”

The primary output is not just a report. It is:

- a **profile map** showing where the person may have a presence;
- an **evidence map** explaining how each candidate was found and related; and
- a **digital footprint** synthesizing public activity, projects, work, publications,
  topics, and timeline signals across the selected profiles.

### 1.2 Prototype stance

The local prototype may search for any person or account. It does not require the
searcher to prove ownership of the seed profile, and it does not require a public-figure
allowlist or target eligibility approval.

The prototype is exploratory:

- provisional and conflicting candidates remain visible;
- low-confidence leads are not hidden merely because they cannot be auto-confirmed;
- the user can continue a promising branch or include it in a report;
- uncertainty travels with the branch and is shown in the resulting footprint; and
- benchmark results inform ranking and labels but do not block experimentation.

The source boundary is broader than anonymous public pages. A provider may use:

- publicly accessible pages and APIs;
- search indexes and licensed data providers;
- data visible through an account the requester is authorized to use;
- user-connected APIs or OAuth scopes;
- user-supplied URLs and exported archives; and
- local fixtures and synthetic datasets.

The prototype must not defeat authentication, paywalls, CAPTCHA, private-account
controls, or other access restrictions. This is an access boundary, not a target
eligibility gate.

In this plan, **open-ended** means broad target selection, broad but authorized source
access, visible provisional results, recursive pivots, and user-controlled graph scope.
It does not mean unlimited collection. The first prototype deliberately retains four
constraints: no access-control bypass, no face/reverse-face recognition, no bulk or
continuous monitoring, and no direct-contact or precise-home-address synthesis in the
default report.

### 1.3 Product principles

1. **A user ID is a seed, not a universal identity.**
   `alex` on one platform does not prove that `alex` elsewhere is the same person.
   In the UI, “user ID” is convenient shorthand; the API distinguishes a mutable
   `handle` from a provider's stable account ID.

2. **Discovery and identity association are separate.**
   A provider can find a candidate without asserting that it belongs to the person.

3. **Relationships are evidence-bearing graph edges.**
   Every edge records how it was discovered, which observations support or contradict
   it, when those observations were collected, and which rule/model version evaluated
   them.

4. **Exploration is open-ended but budgeted.**
   The user may expand any branch, while default depth, fan-out, time, and provider-cost
   limits prevent accidental graph explosion.

5. **User choices alter scope, not source history.**
   Accepting or rejecting a candidate creates a new graph revision; it never rewrites
   the original observations.

6. **The footprint remains account-scoped.**
   Facts retain the account and source they came from. A provisional account cannot
   silently become a certain fact about the seed person.

7. **A model may propose; the application records and explains.**
   Models can help classify links, extract signals, and summarize selected evidence,
   but URLs, source observations, graph edges, scores, revisions, and access limits are
   controlled by the host application.

8. **Maigret finds candidates; the identity graph decides their meaning.**
   The product reuses Maigret's maintained site catalog, asynchronous checks, identifier
   extraction, and parsing. It does not treat Maigret's existence status, built-in
   reports, or recursive CLI output as identity proof.

### 1.4 Quick and Deep modes

Quick and Deep share the same evidence, identity, and orchestration rules, but spend
different retrieval budgets:

- Quick scans the promoted 20-site catalog and caps Exa-only professional retrieval at
  two public-name hypotheses, six queries/requests, ten unique profiles, and 40 seconds.
- Deep scans the promoted 56-site catalog in eight shards and uses the full configured
  Exa + GitHub adaptive envelope (four names, 20 queries, 32 requests, 30 profiles, and
  120 seconds by default).
- Both derive professional queries from public name, handle, broad location, employer,
  education, and project signals and preserve the same evidence lineage.

Deep also differs at composition time:

| Mode | Retrieval | Deliverable |
|---|---|---|
| `quick` | Focused 20-site + capped Exa workflow | Concise deterministic brief with accounts, qualified facts, evidence, and limitations |
| `deep` | Expanded 56-site + full Exa/GitHub workflow | A source-grounded LLM story with a calibrated conclusion, identity snapshot, account narrative, curated findings, exclusions, coverage, evidence index, and reassessment conditions |

The LLM may select, connect, and narrate only the collected evidence. The host remains
authoritative for account existence, person-association status, confidence ceilings,
canonical source records, and citation validity. If the Deep composer is unavailable or
its output fails validation, the product labels the result as a **partial Quick-grade
fallback** rather than a completed Deep story.

The composer is gateway-configurable. The local prototype supports direct OpenAI or
OpenRouter's stateless Responses API through a fixed host-selected endpoint. The chosen
gateway and model are frozen into the provider run before dispatch; there is no
cross-gateway retry or automatic paid fallback. OpenRouter routing must require support
for the structured-output parameters and deny data-collection routes, while model web
search stays disabled until its citations can enter the same evidence ledger.

### 1.5 Initial non-goals

The first prototype does not need:

- bulk person lists or a public API;
- continuous monitoring or alerts about a person;
- access-control bypass or collection of another person's credentials;
- face recognition or reverse-face search;
- reimplementing Maigret's catalog/check engines or using its generated reports as the
  product footprint;
- a claim that an inferred graph is a legally verified identity;
- automated employment, credit, housing, insurance, education, immigration, or law
  enforcement decisions;
- a polished PDF or deep dossier; or
- production-scale multi-tenant deployment.

These are product-scope choices, not reasons to restrict single-person exploratory
search.

---

## 2. Inputs and seed resolution

### 2.1 Canonical input

The preferred input is:

```json
{
  "seed": {
    "kind": "platform_identifier",
    "platform": "github",
    "identifier_type": "handle",
    "identifier": "icZsh"
  },
  "hints": {
    "display_name": null,
    "known_handles": [],
    "known_domains": [],
    "keywords": []
  },
  "search_mode": "quick",
  "platform_scope": {
    "catalog_profile": "quick",
    "include_sites": [],
    "include_tags": [],
    "exclude_tags": []
  },
  "max_depth": 2,
  "frontier_scan_budget": 4,
  "site_probe_budget": 200,
  "native_provider_budget": 20,
  "network_request_budget": 300,
  "locale": "en-US"
}
```

Supported seed forms:

- `platform + identifier`, such as `github + handle + icZsh`;
- a canonical or non-canonical profile URL;
- `@handle` with no platform;
- a handle-like string; and
- a previously discovered profile node selected as a new seed.

The API represents them as a discriminated union:

```json
[
  {
    "kind": "platform_identifier",
    "platform": "github",
    "identifier_type": "handle",
    "identifier": "icZsh"
  },
  {
    "kind": "profile_url",
    "url": "https://github.com/icZsh"
  },
  {
    "kind": "bare_handle",
    "handle": "icZsh"
  },
  {
    "kind": "account_node",
    "account_node_id": "uuid"
  }
]
```

Optional hints are query context supplied by the user, not pre-validated facts. They
may improve ranking but must remain identifiable as user input.

### 2.2 Platform-scoped identifiers

An identifier is stored as:

```text
provider_namespace
+ identifier_type
+ normalized_identifier
+ canonical_profile_url?
+ provider_stable_account_id?
```

Where available, the provider's stable numeric or opaque account ID is stored separately
from the mutable handle. This allows the graph to represent:

- handle changes by the same account;
- the same handle being reused by a different account;
- multiple handles or accounts on the same platform; and
- redirects or profile migrations.

Canonicalization is provider-specific and versioned. It covers case rules, Unicode,
leading `@`, URL encoding, trailing slashes, mobile hosts, accepted aliases, and known
redirect patterns.

Identifier types are typed end to end. `handle` is the default, while provider IDs such
as `steam_id`, `vk_id`, `ok_id`, `yelp_userid`, `bilibili_id`, or another Maigret
catalog type are routed only to sites that declare support for that `id_type`. The
runtime reads this mapping from the pinned catalog rather than hard-coding a promise
that every identifier works on every site. The adapter maps the product's `handle`
type to Maigret's `username` `id_type`; it does not pass `handle` through verbatim.

### 2.3 Profile-existence outcomes

A provider lookup returns one of:

```text
resolved
redirected
renamed
not_found
private_or_limited
suspended
login_wall
soft_404
ambiguous
unavailable
invalid_response
```

Rules:

- `resolved`, `redirected`, and `renamed` create canonical account nodes after provider
  identity checks pass;
- `private_or_limited` or `suspended` may create an existence-only node only when an
  authoritative provider response confirms the account;
- a generic login page, search snippet, or soft-404 page does not establish account
  existence;
- redirects are revalidated against provider canonicalization rules;
- handle reassignment creates a new account node rather than inheriting the old node's
  evidence; and
- unavailable or inaccessible means “not checked,” not “no account.”

Maigret's four-state result is normalized into this richer existence vocabulary as
defined in §6.2.2. In particular, `CLAIMED` normally yields a provisional `resolved`
candidate, `AVAILABLE` yields `not_found`, `UNKNOWN` yields an unavailable/error
outcome, and `ILLEGAL` is site-specific inapplicability. Redirect, rename,
private/limited, suspension, and stable-account continuity require native enrichment;
the Maigret adapter does not invent those distinctions.

### 2.4 Bare-handle behavior

A bare handle is intentionally ambiguous. The system does not silently choose a single
platform or person.

Instead it:

1. probes the supported platform catalog for exact-handle profiles;
2. resolves every successful result into a possible seed node;
3. groups obvious duplicates and preserves distinct hypotheses;
4. ranks the seed hypotheses using available hints; and
5. lets the user choose one or search from several in parallel.

The UI should make this ambiguity useful: “We found this ID on six platforms” is a
starting map, not an error.

### 2.5 Routing seeds into Maigret

Seed resolution and catalog discovery are complementary:

- `platform_identifier + handle`: resolve the named platform with its native adapter,
  then start a Maigret exact-handle scan;
- `platform_identifier + stable ID`: use the native adapter and only the Maigret sites
  declaring that identifier type;
- `profile_url`: canonicalize the URL, map it to a catalog site when possible, extract
  the handle or typed ID with host/native rules, then follow the appropriate route
  above; arbitrary URLs are not handed to Maigret's CLI `--parse` path;
- `bare_handle`: start a Maigret exact-handle scan immediately and keep each claimed
  result as a possible seed hypothesis; and
- `account_node`: schedule a child Maigret scan from identifiers observed on that node,
  with the node and discovery edge recorded as its parent.

A native seed lookup can fail while Maigret still returns useful candidates, and the
reverse can also happen. Those outcomes remain separate in the job record.

---

## 3. Intended user experience

### 3.1 Core flow

1. **Enter a user ID**
   Choose a known platform or search a bare handle across the provider catalog.

2. **Resolve the seed**
   Show the profile that was found, its canonical ID, and any alternative seed
   hypotheses.

3. **Discover related presence**
   Stream Maigret catalog matches, explicit links, web results, personal sites, and
   contextual candidates into a graph.

4. **Compare candidates**
   For every profile, show supporting signals, contradictions, discovery path, source
   recency, semantic relationship, and identity-confidence tier.

5. **Steer the search**
   The user can include, exclude, merge, split, or expand any node, add a hint, search
   another platform, or increase depth/budget.

6. **Build the footprint**
   Generate the report from the current selected graph revision. Regenerate it whenever
   the selection changes.

### 3.2 Primary screens

1. `/` — seed input, recent searches, and quick/explore mode.
2. `/search/:job_id` — live discovery timeline plus candidate graph.
3. `/search/:job_id/candidates` — sortable candidate comparison and evidence.
4. `/search/:job_id/footprint` — sourced footprint generated from the selected graph.
5. `/history` — local search history and deletion.
6. `/settings/sources` — provider access, connected accounts, budgets, and platform
   scope.

The graph and candidate list are two views of the same data. The product must remain
usable without a force-directed visualization.

### 3.3 Progressive results

Suggested progress:

```text
00:02  Resolving github:icZsh…
00:08  Reading self-declared links and identifiers…
00:17  Maigret checked 64 of 100 selected sites; 7 accounts found…
00:31  Comparing profile names, domains, projects, and profile text…
00:45  Found 9 candidates: 2 strong, 3 plausible, 4 weak leads…
01:02  Expanding two promising branches…
01:18  Building the first footprint revision…
```

Candidates may appear before the final footprint is ready. The user should not have to
wait for terminalization before inspecting or steering them.

The discovery view shows the Maigret scan profile, catalog snapshot, selected/completed
site count, and claimed/available/unknown/illegal totals. Candidate cards say how they
were found—for example, “exact-handle catalog probe via Maigret”—without wording that
implies an identity confirmation.

### 3.4 State vocabularies

Four independent vocabularies must not be collapsed into one field.

Job status:

```text
queued
resolving_seed
discovering
correlating
building_footprint
ready
ready_partial
seed_not_found
no_candidates
cancelled
failed
```

Exploration status:

```text
idle
running
paused
budget_reached
completed
cancelled
```

A quick footprint may be `ready` while background exploration remains `running`.
Additional observations then publish new graph revisions without moving the job back
from `ready`.

Semantic relationship type:

```text
same_person
personal_site
owned_project
employer_or_organization
authored_content
reference_or_mention
unknown
```

Identity-confidence tier:

```text
direct
strong
likely
possible
weak
conflicting
```

User-selection state:

```text
undecided
included
excluded
```

Discovery method is a fifth, provenance-only vocabulary defined in §8.3. A user
selection changes report scope; it does not change the semantic relationship or
identity-confidence tier.

---

## 4. How a user ID is related to social-media presence

This is the central product capability.

### 4.1 Identity graph

The engine builds a versioned graph:

```text
SeedIdentifier
  └── resolves_to ──> AccountNode
                         ├── explicit_profile_link ──> AccountNode
                         ├── username_catalog_probe [Maigret] ──> AccountNode
                         ├── catalog_extracted_id [Maigret] ─────> SeedIdentifier
                         ├── search_result ──────────> AccountNode
                         ├── shared_domain ──────────> WebsiteNode
                         └── authored_content ───────> ContentNode
```

Nodes represent observed objects:

- social or creator accounts;
- personal or professional websites;
- link-in-bio pages;
- repositories and project pages;
- publications and author IDs;
- feeds, newsletters, and content channels; and
- organizations or products that may explain a link without being the same person.

Edges represent observed or inferred relationships:

- `resolves_to`
- `links_to`
- `links_back_to`
- `same_handle_as`
- `shares_identifier_with`
- `shares_domain_with`
- `shares_profile_context_with`
- `authored`
- `affiliated_with`
- `possible_same_person`
- `contradicts_same_person`

An account may be related to the seed without representing the same person. The graph
therefore stores semantic `relationship_type`, `identity_confidence_tier`, discovery
method, and user-selection state in separate fields.

### 4.2 Discovery channels

The discovery planner uses several channels in parallel.

#### A. Direct seed resolution

Resolve the exact platform/user-ID pair or URL. Capture:

- canonical handle and profile URL;
- stable provider account ID when exposed;
- display name and aliases;
- profile text and structured profile fields;
- public or authorized outbound links;
- provider-native verification or domain fields;
- timestamps and activity range; and
- source-access scope.

#### B. Explicit link extraction

Extract possible self-links from:

- website/profile fields;
- bio and about sections;
- link-in-bio pages;
- pinned profile posts;
- repository or profile README files;
- `rel="me"` and other verified-link mechanisms;
- creator channel descriptions; and
- personal-site headers, footers, and contact/about pages.

Each link is classified before it becomes a same-person candidate:

```text
self_social_profile
personal_site
owned_project
employer_or_organization
authored_content
reference_or_mention
unknown
```

For example, a GitHub profile linking to an employer's X account is a relationship but
not another social profile for the same person.

#### C. Maigret catalog scans

Maigret is the default cross-platform fan-out for exact handles and supported typed
identifiers. The adapter selects sites from a pinned catalog snapshot, calls Maigret's
asynchronous Python API with parsing enabled, and records each site check before
normalizing it into the graph.

The adapter reuses:

- catalog-ranked site selection and site/tag/country filters;
- username and typed-ID checks;
- site-specific existence/error detectors;
- parsed profile fields;
- `ids_usernames`, `ids_links`, and structured `ids_data`; and
- per-site rank, tags, response status, and canonical result URL.

The planner may generate a bounded set of variants when useful:

- case and punctuation normalization;
- leading/trailing underscore differences;
- documented previous handles;
- transliteration or spacing variants suggested by profile text; and
- user-supplied aliases.

The engine does not generate an unbounded mutation list. Every variant is a separate
query with a parent identifier and reason. Exact handle reuse—or a Maigret `CLAIMED`
status—is a candidate-generation signal, not sufficient proof by itself.

#### D. Search and index discovery

When available, use web search, platform search, licensed indexes, and local scanners
with focused queries derived from the seed:

- exact handle;
- display name plus a distinctive domain, project, organization, or publication;
- known personal domain plus platform name;
- exact profile phrases;
- author identifiers such as ORCID or DOI metadata; and
- links that mention or point back to the seed.

Name-only search is allowed in exploratory mode, but its results start with low
association weight.

#### E. Shared-anchor pivots

Extract and compare identity anchors:

- personal domains and subdomains;
- exact self-published email or cryptographic identifiers;
- ORCID, DOI author IDs, package registries, or developer IDs;
- distinctive project, repository, publication, or creator-brand names;
- declared organizations and roles;
- aliases and display names;
- characteristic profile phrases;
- languages and broad location/time-zone context;
- exact reused media asset URL or binary hash; and
- content-topic and writing-style similarity.

Opaque or model-derived signals such as style similarity are weak supporting evidence.
Exact image reuse may be used as a media signal; face recognition or biometric matching
is not part of the initial design.

#### F. Recursive pivots

A discovered node can become a new frontier node. The planner extracts identifiers and
links from it, then repeats the same channels within configured limits.

Maigret's built-in CLI recursion is not used as the orchestration layer. After each
low-level scan, the application persists `ids_usernames`, `ids_links`, and `ids_data`,
creates provenance-bearing child identifiers or URL candidates, and lets the
`DiscoveryPlanner` schedule the next scan. This preserves the exact parent node,
parent observation, depth, budget, query fingerprint, and inherited uncertainty for
every hop. It also lets cancellation persist already completed site checks.

Default expansion policy:

| Root-association tier | Quick mode | Explore mode |
|---|---|---|
| direct | expand automatically | expand automatically |
| strong | expand automatically | expand automatically |
| likely | expand if budget remains | expand automatically |
| possible | show, do not auto-expand | expand if budget remains |
| weak | show only | expand only when user asks |
| conflicting | preserve for comparison | expand only when user asks |

The user can override this policy for any branch.

### 4.3 Evidence signals

Every signal has:

- a feature family;
- supporting, contradicting, or neutral polarity;
- strength;
- source observation IDs;
- discovery path;
- observed/asserted time;
- independence/lineage group;
- extractor/rule/model version; and
- access scope.

Initial signal families:

| Signal | Default interpretation |
|---|---|
| Reciprocal self-profile links | Very strong same-person evidence |
| Seed profile says “my [platform]” and links the candidate | Strong same-person evidence |
| Provider-native verified personal domain shared by both | Strong evidence |
| Same stable provider ID across a handle rename | Strong continuity evidence |
| Exact public ORCID, PGP key, or other unique identifier | Strong evidence |
| Same personal domain with compatible profile context | Strong contextual evidence |
| Exact uncommon handle | Moderate evidence |
| Exact common handle | Weak evidence |
| Same display name or alias | Weak to moderate evidence |
| Distinctive project/publication overlap | Moderate evidence |
| Organization/role overlap | Contextual evidence |
| Exact profile phrase or uncommon bio detail | Contextual evidence |
| Same languages or broad location | Weak evidence |
| Exact reused avatar/media asset | Weak supporting evidence |
| Topic or writing-style similarity | Weak experimental evidence |
| Explicitly different identity or account type | Strong contradiction |
| Incompatible stable provider IDs or reassigned handle | Strong contradiction |
| Candidate links to a different person's canonical site | Strong contradiction |
| Timeline or affiliation mismatch | Contextual contradiction |

Two signals derived from the same upstream page, search snippet, mirror, or syndicated
profile share one lineage group and do not gain extra weight by repetition.

A Maigret detector firing establishes only a catalog-probe observation. Association
weight comes from the exact/common-handle feature and independently extracted anchors,
not from `CLAIMED`, site traffic rank, catalog order, or the number of mirrors that
repeat the same detector lineage. The exact Maigret site entry, detector method,
`is_similar`, status, and source/mirror lineage remain attached to the observation.

### 4.4 Initial ranking model

The prototype uses a transparent heuristic score for ordering candidates, not a claim of
mathematical identity certainty.

Starting contributions:

| Feature family | Indicative contribution |
|---|---:|
| Reciprocal explicit self-links | set tier to `direct` |
| One-way explicit “my profile” link | +70 |
| Shared verified personal domain | up to +35 |
| Exact unique identifier | up to +40 |
| Exact uncommon handle | up to +20 |
| Exact common handle | up to +8 |
| Display-name/alias agreement | up to +10 |
| Project/publication overlap | up to +15 |
| Organization/role overlap | up to +12 |
| Distinctive profile-text overlap | up to +10 |
| Topic/language/time consistency | up to +8 |
| Exact media reuse | up to +5 |
| Strong contradiction | −60 to −100 |
| Weaker contradiction | −10 to −40 |

Rules:

- contributions are capped by feature family;
- duplicate lineage does not stack;
- one strong contradiction may override several weak matches;
- missing or unavailable signals contribute zero rather than negative evidence;
- the final score is clamped to `[-100, 100]`;
- a score is attached to a specific candidate, person hypothesis, and graph revision;
- score thresholds are calibrated by provider and handle-rarity cohort; and
- the UI shows the evidence breakdown alongside any numeric rank.

Initial tiers:

```text
direct      reciprocal explicit self-link or user-authenticated relation
strong      score >= 90 and no unresolved strong contradiction
likely      score 65–89
possible    score 35–64
weak        score 1–34
conflicting score <= 0 or a strong unresolved contradiction
```

These are starting rules for the prototype. Phase 1 benchmarking may change weights and
thresholds without changing the evidence schema.

`SignalEvaluatorConfig` is versioned and defines:

- normalization/comparison rules for every feature family;
- the exact contribution and family cap;
- missing-value handling;
- contradiction precedence;
- score clamp and tier thresholds;
- provider/cohort overrides;
- handle-rarity source and snapshot date; and
- evaluator version and checksum.

Handle rarity comes from a versioned provider sample, licensed/index statistics, or a
curated bucket. When rarity is unknown, exact-handle evidence uses the common-handle cap
of `+8`.

Worked examples:

```text
one-way “my profile” link (+70)
+ shared verified domain (+35)
+ matching alias (+10)
= 100 after clamp → strong

common handle (+8)
+ matching display name (+10)
+ topic/language consistency (+8)
= 26 → weak

uncommon handle (+20)
+ project overlap (+15)
+ matching alias (+10)
+ strong contradiction (−80)
= −35 → conflicting
```

### 4.5 Path uncertainty and transitivity

Association is not blindly transitive. The engine maintains three values:

```text
local_edge_score         evidence relating a child to its immediate parent
direct_root_score        independent evidence relating the candidate to the selected
                         person hypothesis
inherited_path_score     min(parent_root_score, local_edge_score)
```

The candidate's effective root score is:

```text
max(direct_root_score, inherited_path_score)
```

followed by contradiction rules and the active evaluator configuration. Independent
direct-root evidence may raise a child above its inherited ceiling; evidence that only
repeats the parent-child path may not.

For example, if:

```text
seed --likely--> A --possible--> B
```

then `B` does not become likely merely because it is two hops away.

Each candidate records:

- its local parent-child score;
- its independent direct-root score;
- its effective root score and tier;
- the path through which it was discovered;
- the weakest edge on that path;
- whether the candidate has independent evidence linking directly back to the seed.

The effective root tier—not the local edge tier—controls automatic expansion in §4.2.F.
This permits deeper discovery without manufacturing confidence through graph depth.

### 4.6 Competing hypotheses

When the same handle maps to several plausible people, the graph keeps separate
hypothesis clusters. It does not force a single winner.

The user may:

- choose one seed hypothesis;
- compare two clusters side by side;
- merge nodes into one selected person;
- split an incorrectly merged cluster;
- keep several branches unresolved; or
- build separate footprints for each hypothesis.

### 4.7 User decisions

User actions are stored as append-only `UserResolutionDecision` records:

```text
include
exclude
confirm_same_person
mark_different_person
merge
split
expand
stop_expansion
add_hint
```

A decision creates a new `IdentityGraphRevision` and, when requested, a new
`FootprintRevision`. It does not delete or mutate the underlying discovery and evidence
records.

---

## 5. Digital-footprint construction

### 5.1 Selected graph scope

Every footprint references one immutable graph revision and one explicit selection
policy:

```text
suggested: direct + strong + likely
expanded: suggested + possible
manual: exact user-selected node set
```

The system may preselect the `suggested` set so a first footprint can be generated
without extra clicks, but it must label that scope as `system_suggested`, show the
selected nodes, and let the user change them. A user-confirmed set records
`selection_origin = user`. The user may regenerate the footprint after changing the
graph; no tier silently becomes a user choice.

### 5.2 Account-scoped extraction

Each selected account produces structured observations such as:

- profile identity and aliases;
- profile URLs and outbound links;
- work and organization statements;
- projects and repositories;
- publications and author records;
- creator channels and authored content;
- public topics and recurring themes;
- activity date ranges;
- notable timeline events; and
- contradictions or stale information.

Every extracted item keeps:

- account node ID;
- source URL or provider record;
- excerpt/span or structured field;
- retrieved and asserted time;
- source/access type;
- lineage group; and
- extraction version.

Recognized fields from Maigret/`socid-extractor` may enter this account-scoped pipeline,
but the original site check and source page remain the evidence. Maigret's generated
dossier, report prose, and optional AI summary are never ingested as observations or
citations.

### 5.3 Cross-account synthesis

The footprint builder:

1. groups equivalent claims while preserving their account origins;
2. separates supporting and contradicting observations;
3. distinguishes a retrieval date from the date a statement was true;
4. labels claims inherited from provisional branches;
5. avoids double-counting mirrors and syndicated content; and
6. writes limitations for missing, inaccessible, stale, or unresolved sources.

Facts from a provisional account can appear when the user includes that account, but
they retain a visible qualifier such as:

> From a profile currently marked “possible match.”

### 5.4 Footprint sections

The initial report contains:

1. **Identity overview** — seed, aliases, selected accounts, and unresolved branches.
2. **Presence map** — platforms, personal sites, creator channels, and relationship
   types.
3. **Professional footprint** — roles, organizations, projects, repositories, and
   publications.
4. **Content footprint** — public topics, recurring themes, and representative authored
   items.
5. **Timeline** — dated profile, work, project, publication, and activity observations.
6. **Contradictions and uncertainty** — conflicting names, dates, affiliations, or
   identity signals.
7. **Sources and discovery paths** — how each account and claim entered the graph.
8. **Coverage gaps** — providers not searched, inaccessible sources, and weak branches.

### 5.5 Field policy

The explorer can retain broad source metadata for local research. The default synthesized
report should mask direct contact details, authentication material, precise home
addresses, and secrets even if a source exposes them. Source links and account-level
evidence remain available.

Sensitive or highly inferential attributes should not be invented from proxies. If
future versions expose such fields, they require an explicit field-policy decision and
clear source attribution rather than silent model inference.

---

## 6. Provider and search strategy

### 6.1 Provider capabilities

Each provider declares:

```text
resolve_profile
scan_identifier_catalog
search_handle
search_name
extract_links
extract_profile
extract_content
resolve_stable_id
check_backlink
```

It also declares:

- access mode: `public_api | public_page | connected_account | licensed | upload`;
- supported input formats;
- canonicalization rules;
- rate limits, cost, and concurrency;
- whether results may be cached;
- supported fields and content types;
- status/error mapping;
- extraction/schema version; and
- feature flags and kill switch.

`scan_identifier_catalog` is implemented first by Maigret. Native provider adapters do
not need to duplicate its broad username fan-out; they complement it with authoritative
seed resolution, richer enrichment, stable-ID checks, backlinks, authenticated access,
or provider-specific search.

### 6.2 Maigret as the core discovery engine

The prototype embeds the Maigret Python library in a dedicated worker. It does not
shell out to the CLI and does not embed Maigret's web UI. The initial dependency is
exactly pinned to the reviewed `0.6.3` release
(`88f291e0b081c6914be3c9627d9f75da6b344afe`) and upgraded only through the catalog
and fixture review process in §10.5. The reviewed bundled catalog contains 3,187 sites;
its baseline `data.json` SHA-256 is
`4eeed3b475a1ff4dce558bbca926d50adcb6b8e5372770f330e25baa4a252df0`.
These values identify the starting snapshot, not an instruction to enable every site.

Reviewed upstream references:
[repository and feature overview](https://github.com/soxoj/maigret),
[v0.6.3 source](https://github.com/soxoj/maigret/tree/v0.6.3),
[Python library usage](https://maigret.readthedocs.io/en/latest/library-usage.html), and
[database/network settings](https://maigret.readthedocs.io/en/latest/settings.html).

#### 6.2.1 Adapter contract

The adapter calls the low-level asynchronous API once per normalized identifier:

```python
partial_results = {}
results = await maigret_search(
    username=normalized_identifier,
    site_dict=selected_sites,
    logger=scan_logger,
    query_notify=notifier,
    timeout=scan_config.site_timeout_seconds,
    is_parsing_enabled=True,
    is_enrich_enabled=False,
    id_type=maigret_id_type,
    forced=False,
    max_connections=scan_config.max_connections,
    no_progressbar=True,
    retries=0,
    check_domains=False,
    proxy=None,
    tor_proxy=None,
    i2p_proxy=None,
    cloudflare_bypass=None,
    cookies=None,
    output_container=partial_results,
)
```

The exact call is wrapped behind `MaigretDiscoveryAdapter`; product code does not import
Maigret directly. A custom notification sink emits aggregate progress, and Maigret's
mutable output container is used to persist completed site results if the job is
cancelled or reaches its cutoff.

Parsing is enabled because it produces structured fields and pivots. Maigret enrichment,
domain checks, internal retries, forced checks, and disabled/protocol-specific sites are
off initially: the host owns secondary requests, retry policy, and catalog admission.

The adapter contract returns normalized site checks and extracted pivots, not a final
identity report:

```text
MaigretScanResult
  scan_run
  site_checks[]
  account_candidates[]
  extracted_identifiers[]
  extracted_links[]
  structured_observations[]
  coverage_summary
```

#### 6.2.2 Status normalization

Maigret and product statuses remain distinct:

| Maigret site status | Product meaning | Graph effect |
|---|---|---|
| `CLAIMED` | A site-specific check indicates that the identifier exists | Create or update a candidate plus a discovery observation; `is_similar=true` stays a weak/ambiguous lead; never assert same person |
| `AVAILABLE` | The site-specific detector indicates no account for that identifier | Record `not_found` for that site and catalog snapshot |
| `UNKNOWN` | The check was inconclusive or errored | Map the detailed error to timeout, rate limit, CAPTCHA, auth, or provider error; never treat as not found |
| `ILLEGAL` | The identifier is invalid or inapplicable for that site | Record `inapplicable`; a disabled/protocol/type mismatch is `skipped_configuration` and should normally be filtered before execution |

`is_similar`, site rank, and tags can affect display order or scan selection, but not
identity truth. A scan-level `no_candidates` outcome is allowed only when the chosen
catalog checks completed without a claimed result; incomplete coverage is reported
separately. A broad run can be `partial_success` when it yields useful conclusive
checks alongside timeouts or errors. `is_similar=true` produces a
`similar_handle_result` lead rather than an exact-handle relationship.

#### 6.2.3 Catalog governance

Discovery must be reproducible. Each runtime scan references a
`MaigretCatalogSnapshot` containing:

- Maigret package version and upstream commit/release;
- exact `socid-extractor` version, site database checksum, and import time;
- enabled site IDs, identifier types, ranks, tags, and any local overrides;
- disabled or quarantined detectors and the reason;
- selected mirror behavior; and
- catalog self-check and fixture results.

Maigret's automatic site-database update is disabled in application workers. A separate
maintenance command may download a candidate snapshot, run schema validation,
detector/self-check tests, collision fixtures, and a diff review, then explicitly
promote it. Every scan records the actual selected site IDs because catalog mirrors or
filters can alter the effective set.

#### 6.2.4 Scan profiles

Initial profiles are configuration starting points to benchmark in Phase 1:

| Profile | Initial site selection | Recursion behavior | Intended use |
|---|---|---|---|
| `quick` | Reviewed high-signal subset, approximately top 100 | One automatic child scan only for strong/direct pivots | First useful candidate map |
| `explore` | Ranked/tag-filtered set, approximately top 500 | Budgeted host-controlled recursion | Normal background exploration |
| `deep` | User-selected broad or full catalog | Explicitly requested branches only | Slow exhaustive investigation |

Per-site timeout, internal concurrency, total site checks, child scans, and wall-clock
limits are host configuration, measured independently, and constrained by provider
rate/error behavior. “3,000+ sites supported” describes Maigret's catalog breadth; it
is not a promise that every site will be checked or will work in every run.
After applying identifier type, enabled-site, protocol, profile, site, and tag filters,
selection is deterministic by catalog rank plus stable site key and is truncated to the
remaining site-probe budget. The selected-site manifest is stored before dispatch.

#### 6.2.5 Recursive extraction and identity boundary

For each completed site result:

1. persist the raw status metadata and normalized source observation;
2. turn `CLAIMED` into an account candidate using `url_user`;
3. turn `ids_usernames` into typed child `SeedIdentifier` records;
4. turn `ids_links` into URL candidates for canonicalization and Safe Fetch;
5. turn allowed `ids_data` fields into account-scoped observations;
6. add a `DiscoveryEdge` from the exact parent scan/node to every child;
7. deduplicate by normalized identifier, canonical account key, and query fingerprint;
8. score association evidence independently; and
9. schedule eligible children through the host planner.

`ids_usernames` values whose type is unknown remain visible unscheduled leads.
`ids_links` are canonicalized and may be mapped back to typed identifiers with the
pinned catalog's URL matcher before any child scan. Link-derived identifiers normally
carry stronger discovery provenance than catalog-wide handle hits, but neither is
same-person proof. Catalog mirrors share a lineage family with their source so they do
not stack identity evidence.

The product does not use Maigret's optional AI summary, generated dossier/reports,
Neo4j export, or CLI recursive loop as product output. Those features solve presentation
or traversal concerns that this application's revisioned evidence graph must own.

### 6.3 Discovery waves

#### Wave 0 — seed

- resolve the seed;
- fetch canonical profile metadata;
- extract explicit links and identifiers;
- create the root graph revision; and
- route the normalized handle or typed ID into the selected Maigret scan profile.

#### Wave 1 — obvious presence

- resolve explicit profile links;
- run the Maigret exact-handle or typed-ID catalog scan;
- persist Maigret site checks and extracted identifiers;
- resolve the personal website and link-in-bio pages;
- check backlinks and provider-native verified fields.

#### Wave 2 — contextual search

- platform and web search;
- handle variants;
- name plus distinctive anchors;
- organization, project, publication, and author-ID pivots;
- candidate-to-seed comparison.

The first implemented Wave 2 slice is a bounded professional-search provider. It starts
only after all root Maigret shards are terminal, derives mode-bounded plausible public
full-name hypotheses from exact first-party root profiles (two in Quick and four by
default in Deep), and schedules:

- Exa people search with at most five indexed LinkedIn `/in/` results per hypothesis;
- in Deep, GitHub user search/direct profile lookup with at most three fetched profiles
  per hypothesis; and
- no recursive professional-to-professional fan-out.

Every result is persisted as a source document, observation, account node, and
observation-backed discovery edge. Missing credentials, rate limits, timeouts, and
invalid responses are terminal provider outcomes rather than job-wide failures.
Search-index presence is labeled `indexed_profile`, while GitHub's first-party public
API can establish account existence. Neither establishes person identity on its own.

A brief becomes `person_centric / likely` only when exactly one root-derived full-name
hypothesis has an independent professional anchor: an exact normalized-name match plus
a compatible public contextual field, an exact public cross-link/social handle, or the
same name across a third independent first-party family. Name alone, surname overlap,
query rank, a derived GitHub login, and duplicate index hits remain unverified.

#### Wave 3 — recursive exploration

- expand strong or user-selected branches;
- discover child identifiers and content nodes;
- revisit unresolved candidates with newly learned anchors;
- continue until time, depth, fan-out, provider, or user budget is reached.

Quick mode targets Waves 0–2 and a shallow Wave 3. Explore mode can continue in the
background and publish new graph revisions as evidence arrives.

### 6.4 Provider-run status

Canonical provider status:

```text
pending
leased
running
retry_scheduled
success
partial_success
no_result
timeout
rate_limited
captcha_blocked
auth_required
invalid_response
provider_error
skipped_budget
skipped_circuit_open
skipped_invalid_identifier
closed_at_cutoff
cancelled
```

Provider execution status and candidate identity tier remain separate. A timeout is
not “no account,” and a successful handle lookup is not “same person.”
For an aggregate Maigret run, `success` means every scheduled probe reached a
conclusive terminal state, `no_result` means conclusive completion with no `found`
probe, and `partial_success` means useful completed probes coexist with errors or
cutoff. An explicit cancellation remains `cancelled` while retaining a separate
partial-result disposition.

### 6.5 Native, web, and connected sources

Open-ended discovery requires a fetch boundary that supports:

- native adapters that resolve or enrich high-value Maigret candidates;
- provider-owned fixed API endpoints;
- normalized URLs extracted from source pages;
- focused search-result navigation;
- user-supplied URLs;
- requester-authorized authenticated connectors; and
- isolated browser tasks where ordinary HTTP is insufficient.

Every fetched artifact records `access_scope`:

```text
public
requester_authorized
licensed
user_uploaded
synthetic
```

The system does not store or reuse requester session credentials outside the connector
designed for that source.

Requester cookies are not passed into broad Maigret scans. Authenticated or
requester-authorized data stays behind a provider-specific connector with an explicit
scope. Maigret's proxy, Tor, I2P, and Cloudflare-bypass options are disabled in the core
adapter; introducing any alternative network route requires a separate reviewed
provider capability and is not implied by “deep” mode.

---

## 7. System architecture

### 7.1 High-level design

```text
Next.js Web
    │
    ▼
FastAPI ──> PostgreSQL control plane and immutable revisions
    │
    ├──> Outbox ──> Redis/Celery queues
    │                  ├── Seed resolver
    │                  ├── Discovery planner
    │                  ├── Maigret scan workers
    │                  │      └── pinned site catalog
    │                  ├── Native/search provider adapters
    │                  ├── Identity correlator
    │                  └── Footprint builder
    │
    └──> SSE/polling <── Job events and progressive graph revisions
```

PostgreSQL is the source of truth for jobs, runs, observations, graph revisions,
decisions, claims, and reports. Redis is disposable delivery infrastructure.

Maigret runs on a dedicated `maigret_scan` queue with worker, concurrency, and
rate-limit settings independent from native provider and browser queues. A logical
`MaigretScanRun` is divided into deterministic 25–50-site shards; one Celery task owns
one shard. Start with one or two concurrent shards per worker and at most 20 Maigret
connections per shard, then tune from Phase 1 measurements. Global outbound concurrency
is the product of queue concurrency and per-shard connections, so both are capped.
Completed shards persist independently, and host retries target only transient probes
instead of restarting the whole catalog. This prevents a large scan from starving seed
resolution, user decisions, or footprint building.

Cancellation increments the job's existing graph-generation/acceptance fence and
cancels active async searches. A worker persists partial results only while its lease
and generation remain current; late results are discarded.

### 7.2 Pipeline

```text
intake
  → normalize seed
  → resolve seed hypotheses
  → plan discovery frontier
  → select pinned Maigret catalog sites and native providers
  → run a Maigret identifier scan plus complementary provider checks
  → record every site check, extracted pivot, observation, and candidate
  → evaluate association edges
  → publish graph revision
  → accept user decisions or continue exploration
  → freeze selected graph revision
  → build footprint claims
  → publish footprint revision
```

The planner may add provider runs dynamically. Each run records its parent node,
discovery method, depth, searched identifier, deadline, and graph-generation token.
For a Maigret run it also records the exact catalog snapshot, selected site set, scan
profile, timeout/concurrency configuration, and aggregate status counts.

### 7.3 Quick and explore budgets

Initial quick-mode targets:

| Stage | Target |
|---|---:|
| Intake and seed normalization | 0–3 seconds |
| Seed resolution | 3–15 seconds |
| Explicit links and exact-handle probes | 5–40 seconds |
| Contextual discovery | 15–75 seconds |
| First graph revision | by 45 seconds |
| Quick collection cutoff | 80 seconds |
| Correlation and footprint build | 80–105 seconds |
| User-visible terminal state | by 120 seconds |

Explore mode is not bound to the quick cutoff. It publishes incremental graph revisions
until its configured wall-clock, branch, call, or cost budget is exhausted or the user
stops it.

Budget units are explicit:

- `frontier_scan_budget`: distinct identifiers that may enter Maigret;
- `site_probe_budget`: Maigret site checks across all scans and shards;
- `native_provider_budget`: native/search adapter runs;
- `network_request_budget`: total attempted HTTP requests, including retries and
  redirects where measurable; and
- `max_depth`, per-node fan-out, wall-clock, browser-second, and monetary caps.

Native calls do not consume the site-probe budget, and Maigret probes do not consume the
native-provider budget. Both consume the shared network and time budgets.

### 7.4 Deterministic and model responsibilities

Deterministic host code controls:

- identifier and URL canonicalization;
- provider routing and access mode;
- deadlines, retries, budgets, and rate limits;
- source storage and lineage;
- graph revisions and user decisions;
- score calculation and feature-family caps;
- field filtering and final output schema; and
- durable job and event state.

Models may assist with:

- classifying link semantics;
- extracting aliases, projects, organizations, topics, and dates;
- comparing bounded profile text;
- proposing supporting or contradicting signals;
- clustering similar observations; and
- summarizing the selected evidence graph.

Model output is a proposal tied to source observation IDs. It cannot invent a URL,
provider result, account node, or citation that the host has not recorded.

---

## 8. Core data model

### 8.1 SearchJob and JobAttempt

`SearchJob` stores:

```json
{
  "id": "uuid",
  "requester_id": "uuid",
  "seed_kind": "platform_identifier",
  "seed_platform": "github",
  "seed_identifier_type": "handle",
  "seed_identifier": "icZsh",
  "normalized_seed": "github:handle:iczsh",
  "hints": {},
  "search_mode": "quick",
  "maigret_catalog_snapshot_id": "uuid",
  "platform_scope": {
    "catalog_profile": "quick",
    "include_sites": [],
    "include_tags": [],
    "exclude_tags": []
  },
  "max_depth": 2,
  "frontier_scan_budget": 4,
  "site_probe_budget": 200,
  "native_provider_budget": 20,
  "network_request_budget": 300,
  "status": "discovering",
  "exploration_status": "running",
  "current_graph_revision_id": "uuid",
  "current_footprint_revision_id": null,
  "accepted_at": "...",
  "deadline_at": "...",
  "expires_at": "..."
}
```

`JobAttempt` owns queue lifecycle, leases, retry lineage, deadlines, and terminalization.

### 8.2 SeedIdentifier and AccountNode

`SeedIdentifier` stores the normalized query and its source form.

`AccountNode` stores:

- provider/platform namespace;
- canonical handle and URL;
- stable provider account ID when available;
- display label and account type;
- observed aliases and outbound identifiers;
- first/last observed time;
- access scope; and
- source observation references.

The same real account may appear in multiple graph revisions, but a node's source
identity is immutable.

### 8.3 DiscoveryEdge

`DiscoveryEdge` records how one node or identifier produced another:

```text
parent_node_id
child_node_id
discovery_method
discovery_engine
provider_run_id
source_observation_ids
depth
query_fingerprint
created_at
```

Discovery methods include:

```text
explicit_link
backlink
username_catalog_probe
similar_handle_result
catalog_extracted_identifier
catalog_extracted_link
handle_variant
platform_search
web_search
shared_domain
shared_identifier
content_anchor
user_added
```

The method names describe graph semantics; `discovery_engine="maigret"` records the
implementation. This keeps downstream graph contracts stable without making Maigret
optional in the v3.1 execution plan.

### 8.4 Maigret catalog and scan records

`MaigretCatalogSnapshot` makes the external discovery knowledge base reproducible:

```text
id
package_version
upstream_revision
database_checksum
enabled_site_ids
catalog_metadata
local_overrides
validation_status
promoted_at
```

`MaigretScanRun` stores:

- parent job, node/identifier, and discovery edge;
- normalized product identifier/type and the mapped Maigret `id_type`;
- catalog snapshot, selected site IDs, selected-site manifest checksum, filters, and
  scan profile;
- depth, timeout, internal concurrency, parsing/enrichment/retry/domain-check flags,
  and remaining branch budget;
- started/finished/cancelled time;
- `claimed`, `available`, `unknown`, `illegal`, and completed/selected counts;
- partial-result disposition and terminal provider status; and
- adapter/package/schema versions.

`MaigretScanShard` stores a deterministic subset of site IDs, lease/attempt lineage,
generation fence, internal connection cap, partial-output disposition, and aggregate
counts. Its idempotency key derives from:

```text
job_id
+ normalized identifier type/value
+ catalog snapshot
+ selected site-set fingerprint
+ graph generation
```

Retries create a new attempt for the same shard identity and include only probes whose
previous outcome is transient.

`MaigretSiteCheck` stores one normalized result per selected site:

- scan run and stable catalog site ID;
- site name/domain, source-or-mirror lineage, queried identifier, `url_main`,
  rendered `url_user`, and `url_probe`;
- Maigret status, detailed error/context, HTTP status, rank, tags, and `is_similar`;
- normalized product status;
- candidate account node and observation IDs when created;
- extracted identifier/link/field counts;
- response/result checksum, started/finished time, and duration; and
- raw artifact reference only when retention policy permits.

Normalized site-check status is one of:

```text
found
not_found
timeout
rate_limited
captcha_blocked
auth_required
provider_error
inapplicable
skipped_configuration
cancelled
```

The uniqueness key is `(scan_run_id, catalog_site_id)`. Retries update attempt lineage
but do not create duplicate candidate nodes or evidence. `ids_data` is read from the
library status object with a compatibility fallback for supported upstream schemas;
unrecognized fields remain versioned, untrusted extraction data rather than footprint
claims.

### 8.5 EvidenceSignal and AssociationEdge

`EvidenceSignal` stores a single supporting or contradicting feature with provenance.

`AssociationEdge` stores:

- candidate and person-hypothesis references;
- semantic relationship type;
- identity-confidence tier and ranking score;
- feature-family contribution breakdown;
- supporting and contradicting signal IDs;
- local-edge, direct-root, inherited-path, and effective-root scores;
- correlator and rules version; and
- graph revision ID.

### 8.6 PersonHypothesis and ClusterMembership

`PersonHypothesis` represents one working theory about which account nodes belong to the
same person. It is not a global person record and does not claim legal identity.

`ClusterMembership` stores:

- person hypothesis and account node;
- membership tier and effective root score;
- user-selection state;
- supporting association-edge IDs;
- valid graph revision range; and
- predecessor membership when created by merge or split.

Merge creates a new hypothesis with lineage to both parent hypotheses. Split creates two
or more child hypotheses and records the membership partition. Older hypotheses and
memberships remain addressable through their original graph revisions.

### 8.7 IdentityGraphRevision

An `IdentityGraphRevision` is immutable and contains:

- `parent_revision_id`;
- monotonically increasing revision number;
- selected seed hypothesis;
- node and edge membership;
- person hypotheses and cluster memberships;
- association evaluations;
- unresolved competing clusters;
- user-decision overlay;
- discovery frontier state;
- provider/rule/model versions; and
- checksum.

Provider observations are batched into a revision at a bounded cadence, initially every
two seconds or ten accepted evidence changes, whichever comes first. User mutations send
`base_revision_id` and use optimistic concurrency:

- if referenced nodes/edges are unchanged, the server rebases the decision onto the
  latest revision and returns both revision IDs;
- if a merge, split, deletion, or reassignment changed the referenced identity, the
  server returns `409 revision_conflict` with the latest revision;
- a footprint build always pins one exact graph revision; and
- background exploration may publish later graph revisions without changing an already
  published footprint revision.

### 8.8 Source artifacts and observations

`RetrievalArtifact` stores access metadata and, when policy permits, a short-lived raw
response.

`SourceObservation` stores:

- provider and canonical source;
- structured field or bounded excerpt/span;
- retrieved/asserted time;
- content hash;
- lineage group;
- access scope;
- extraction/schema version; and
- disposition.

### 8.9 FootprintClaim and FootprintRevision

`FootprintClaim` stores:

- predicate and value;
- originating account node IDs;
- person-hypothesis membership and identity-confidence tiers at build time;
- supporting and contradicting observation IDs;
- time semantics;
- confidence/qualification;
- display state; and
- builder version.

`FootprintRevision` references exactly one graph revision, person hypothesis, selection
policy, and selection origin.

### 8.10 UserResolutionDecision

User decisions are append-only and contain:

- action;
- target node(s) or edge(s);
- source graph revision;
- optional user note/hint;
- actor;
- timestamp; and
- resulting graph revision.

They are never stored as provider evidence.

---

## 9. API and event contract

### 9.1 Create a search

```http
POST /v1/footprint-jobs
Content-Type: application/json
Idempotency-Key: opaque-client-key

{
  "seed": {
    "kind": "platform_identifier",
    "platform": "github",
    "identifier_type": "handle",
    "identifier": "icZsh"
  },
  "hints": {},
  "search_mode": "quick",
  "platform_scope": {
    "catalog_profile": "quick",
    "include_sites": [],
    "include_tags": [],
    "exclude_tags": []
  },
  "max_depth": 2,
  "frontier_scan_budget": 4,
  "site_probe_budget": 200,
  "native_provider_budget": 20,
  "network_request_budget": 300,
  "locale": "en-US"
}
```

The `seed` field accepts exactly one discriminated-union shape from §2.1. URL,
bare-handle, and existing-account-node searches do not overload the platform-identifier
fields. At acceptance time the server resolves `catalog_profile` to the current
promoted immutable snapshot and stores that snapshot ID on the job; the client does not
silently float to later catalog updates.

Response:

```json
{
  "job_id": "uuid",
  "status": "resolving_seed",
  "exploration_status": "idle",
  "events_url": "/v1/footprint-jobs/uuid/events",
  "graph_url": "/v1/footprint-jobs/uuid/graph",
  "deadline_at": "..."
}
```

### 9.2 Read results

```http
GET /v1/footprint-jobs?cursor=...&limit=...
GET /v1/footprint-jobs/{job_id}
GET /v1/footprint-jobs/{job_id}/events
GET /v1/footprint-jobs/{job_id}/graph
GET /v1/footprint-jobs/{job_id}/candidates
GET /v1/footprint-jobs/{job_id}/candidates/{candidate_id}
GET /v1/footprint-jobs/{job_id}/discovery-runs
GET /v1/footprint-jobs/{job_id}/footprint
GET /v1/footprint-jobs/{job_id}/sources?cursor=...
```

### 9.3 Steer discovery

```http
POST /v1/footprint-jobs/{job_id}/decisions
POST /v1/footprint-jobs/{job_id}/expand
POST /v1/footprint-jobs/{job_id}/search-platform
POST /v1/footprint-jobs/{job_id}/add-hint
POST /v1/footprint-jobs/{job_id}/rebuild-footprint
POST /v1/footprint-jobs/{job_id}/cancel
POST /v1/footprint-jobs/{job_id}/retry
DELETE /v1/footprint-jobs/{job_id}
```

Every mutation accepts an idempotency key and `base_revision_id`. Graph-changing actions
return the applied base, previous latest, and new revision IDs. A stale but safely
rebasable decision succeeds explicitly; an unsafe stale decision returns
`409 revision_conflict`.

### 9.4 SSE events

Events are durable and replayable by `Last-Event-ID`.

```text
job.accepted
seed.resolving
seed.resolved
seed.ambiguous
discovery.wave_started
discovery.catalog_scan_started
discovery.catalog_progress
discovery.identifier_extracted
discovery.catalog_scan_finished
provider.started
provider.finished
candidate.discovered
graph.revision_published
candidate.score_changed
discovery.budget_reached
user.decision_applied
footprint.build_started
footprint.revision_published
job.ready
exploration.completed
job.failed
```

Candidate events expose normalized candidate metadata, relationship type, identity tier,
and user-selection state once stored; they do not wait for the final footprint.
Catalog progress events are aggregate and rate-limited; the durable internal event log
may contain one `maigret.site_checked` record per completed site without flooding the
browser stream.

---

## 10. Access, storage, and operational boundaries

### 10.1 Access rules

- A local user can search any person or account.
- Providers may use public, requester-authorized, licensed, uploaded, or synthetic data.
- The system never asks for or stores the target person's credentials.
- It does not automate access-control, CAPTCHA, or paywall bypass.
- Connected-account tokens remain in the connector/secret boundary and are never copied
  into jobs, logs, prompts, or evidence.
- Every artifact records its access scope so a report can explain where data came from.

### 10.2 Fetch safety

User-supplied and discovered URLs pass through a Safe Fetch boundary that:

- blocks local, private, link-local, metadata, and reserved destinations;
- rechecks redirects and resolved peer addresses;
- limits response size, content type, decompression ratio, and time;
- isolates browser navigation and downloads;
- strips active content before storage or model use; and
- prevents arbitrary provider workers from bypassing the network gateway.

Open-ended discovery broadens destinations; it does not relax network isolation.

Maigret currently owns its own asynchronous HTTP transport, so its catalog probes do
not automatically traverse the application's per-URL Safe Fetch client. Maigret
workers therefore run in an isolated egress-controlled process/container that may
connect only to the reviewed public hosts in the promoted catalog snapshot, with
private/reserved address blocking enforced at DNS/egress boundaries and redirects
logged. URLs extracted from Maigret results re-enter the ordinary Safe Fetch boundary
before any separate enrichment. Adapting Maigret to the shared transport can replace
this isolation later, but the plan must not claim that it already does.

### 10.3 Retention

Prototype defaults:

| Data | Default retention |
|---|---:|
| Raw response/HTML | memory only; debug copy up to 24 hours |
| Weak/rejected candidates and comparison excerpts | 7 days |
| Graph revisions, structured observations, and footprint | 30 days |
| Search/provider cache | 7–30 days by source volatility |
| Job events and operational logs | 30 days |
| Connected-source credentials | external secret store; not copied |

Every job can be deleted locally. A future shared service needs a separate subject
removal, suppression, retention, and governance design; those are not blockers for
learning from the local prototype.

### 10.4 Local prototype controls

- single-user or trusted local access;
- per-job time, branch, depth, provider-call, browser-second, and cost limits;
- separate frontier-scan, Maigret site-probe, native-provider, and network-request
  budgets;
- no bulk endpoint;
- provider and global kill switches;
- cancellation and deletion;
- redacted logs;
- provider-specific rate limiting and circuit breakers; and
- a clear “exploratory, not verified identity” label in the UI.

### 10.5 Maigret dependency and network controls

- Pin the reviewed Maigret package version and the resolved `socid-extractor`
  dependency in the lockfile.
- Include Maigret's MIT license and attribution in third-party notices.
- Package the promoted site-database snapshot with a checksum; disable runtime
  auto-update.
- Run without requester cookies and with proxy, Tor, I2P, and Cloudflare-bypass
  features disabled.
- Keep response bodies out of normal logs and apply the source field/retention policy
  before persisting parsed values.
- Use a small frozen catalog and local fake endpoints in CI. Live checks belong in a
  separate, rate-limited maintenance or smoke-test workflow.
- Expose package, catalog, and adapter versions on every scan for rollback.

---

## 11. Quality, benchmarks, and observability

### 11.1 What to measure

Discovery:

- seed resolution success rate;
- known-account recall at top 5/top 10;
- candidate yield by platform and discovery channel;
- explicit-link extraction recall;
- provider success, latency, and access-failure rates;
- selected/completed Maigret site coverage;
- Maigret `CLAIMED`/`AVAILABLE`/`UNKNOWN`/`ILLEGAL` distribution by catalog snapshot;
- candidate and extracted-identifier yield per 100 completed site checks;
- conclusive-check rate and useful recursive-pivot yield by site/tag/profile;
- catalog detector regression, false-positive, and quarantined-site rates;
- site checks per second, cancellation lag, and partial-result recovery;
- branch depth, fan-out, cycle count, and deduplication rate.

Association:

- precision and recall by identity-confidence tier;
- score calibration by platform and handle-rarity cohort;
- false-merge and false-split counts;
- contradiction detection rate;
- user accept/reject rate by initial label;
- user merge/split correction rate; and
- uncertainty inherited across recursive paths.

Footprint:

- selected-account coverage;
- claim/source attachment rate;
- claim conflict rate;
- stale/unknown-time rate;
- account-attribution accuracy;
- unsupported-summary count; and
- user-rated usefulness.

Operations:

- first-candidate latency;
- first-graph latency;
- quick-footprint latency;
- site probes, native-provider calls, network requests, and cost per job;
- queue delay and terminalization;
- cancellation/deletion completion; and
- model fallback rate.

### 11.2 Benchmark corpus

Use synthetic and explicitly reviewed cases covering:

- unique and common handles;
- same handle used by unrelated people;
- handle rename and reassignment;
- multilingual and transliterated handles;
- individual, organization, bot, parody, and project accounts;
- mutual and one-way profile links;
- personal sites and link-in-bio hubs;
- stale profiles;
- conflicting names or affiliations;
- multiple accounts on the same platform;
- missing or blocked providers;
- search-result pollution and copied profile text;
- recursive cycles;
- weak leads that become strong after a pivot; and
- strong-looking leads disproved by a stable contradiction.

The prototype reports metrics by association tier. It does not hide exploratory results
just because a statistical launch threshold has not been met.

### 11.3 Explanation evaluation

For sampled candidates, reviewers should be able to answer:

- How was this profile discovered?
- What directly supports the relationship?
- What contradicts it?
- Is the evidence independent or duplicated?
- Did uncertainty increase along a recursive path?
- Which user decision caused the profile to enter the report?
- Which footprint claims came from this account?

If the system cannot answer those questions from stored data, the graph schema is
incomplete.

---

## 12. Implementation plan

### Phase 0 — Intent and contract reset

Deliver:

- this v3.1 project plan and a Maigret-core ADR;
- revised product language and wireframes;
- new OpenAPI/event contracts for seed IDs, candidates, graph revisions, decisions, and
  footprints;
- provider capability catalog;
- a reviewed, exactly pinned Maigret dependency, MIT notice, and promoted site-catalog
  snapshot;
- normalized Maigret scan/site-check contracts and status mapping;
- identity-evidence schema and initial scoring table;
- ADR superseding the direct-URL/eligibility prototype boundary; and
- a fixture corpus for identity linking.

Exit criteria:

- one canonical definition of seed, candidate, discovery edge, association edge, graph
  revision, person hypothesis, cluster membership, user decision, and footprint claim;
- separate enums for discovery method, semantic relationship, identity-confidence tier,
  and user-selection state;
- platform + user ID is the primary input;
- ownership verification is optional evidence, not an admission gate;
- Maigret is the default broad username/identifier discovery engine;
- Maigret `CLAIMED` is explicitly defined as candidate existence, not same-person
  evidence;
- host-controlled recursion and reproducible catalog selection are frozen;
- candidate discovery and recursive pivots are MVP behavior; and
- all current contracts that require eligibility references are identified for
  migration.

### Phase 1 — Maigret-backed identity-discovery spike

Implement a benchmarkable library that:

1. normalizes a seed;
2. resolves it with one native seed adapter;
3. loads a pinned, small Maigret catalog snapshot;
4. scans the normalized handle through the async Maigret library;
5. normalizes all four Maigret statuses and streams aggregate progress;
6. persists per-site checks, claimed candidates, and `ids_usernames`/`ids_links`/
   allowed `ids_data`;
7. schedules one host-controlled recursive pivot;
8. calculates evidence signals and identity-confidence tiers; and
9. emits a graph revision.

Start with a tiny frozen catalog and local HTTP fixtures, then a low-volume live smoke
test against the promoted snapshot. Tune catalog scope, timeouts, internal concurrency,
and the score table from measured behavior.

Exit criteria:

- Maigret package, adapter, site-catalog checksum, selected sites, and scan configuration
  are recorded on every run;
- `CLAIMED`, `AVAILABLE`, `UNKNOWN`, and `ILLEGAL` map correctly and remain auditable;
- cancellation persists completed site results and stops child scheduling;
- automatic catalog update and bypass/proxy/cookie options are disabled;
- explicit links, catalog-probe leads, shared-domain evidence, and contradictions are
  all represented;
- copied or mirrored evidence does not stack;
- handle-collision cases remain separate;
- every candidate has a discovery path; and
- recursive expansion terminates under cycle/depth/fan-out budgets.

### Phase 2 — End-to-end discovery vertical slice

Deliver:

- platform + user-ID search UI;
- seed resolver;
- Maigret scan worker/normalizer plus discovery planner and dynamic native-provider
  runs;
- progressive candidate list and identity graph;
- candidate evidence drawer;
- include/exclude/merge/split/expand decisions;
- immutable graph revisions;
- first footprint builder;
- SSE replay and polling fallback; and
- local Docker/PostgreSQL/Redis/Celery workflow.

Exit criteria:

- one command starts the stack;
- a fixture seed discovers profiles across at least three platform types through the
  Maigret-backed catalog;
- the live vertical slice resolves one seed, runs a real bounded Maigret sweep, and
  demonstrates at least two additional live candidate profiles;
- searched/completed and claimed/available/unknown/illegal coverage is visible;
- the user can inspect and change the selected graph;
- rebuilding the footprint changes only the new revision;
- provider failures remain visible without blocking other branches; and
- browser-to-worker E2E passes.

### Phase 3 — Catalog expansion and native enrichment

Improve Maigret breadth and add complementary providers by measured discovery value:

- curated quick/explore/deep catalog profiles;
- catalog snapshot diff, validation, quarantine, promotion, and rollback tooling;
- site health checks and detector-regression dashboards;
- broader typed-ID and extracted-identifier recursion;
- social/profile platforms;
- personal-site and link-in-bio parsing;
- creator/video/community platforms;
- developer/package/research identity sources;
- web/platform search;
- connected accounts or user uploads; and
- native enrichment for high-value Maigret candidates.

Each adapter needs canonicalization, fixtures, status mapping, rate/cost limits,
provenance, access scope, and a kill switch.

Exit criteria:

- provider additions improve measured candidate recall or footprint coverage;
- catalog changes improve yield or health without unreviewed runtime drift;
- schema drift and access failures degrade gracefully;
- no provider can bypass source/access metadata; and
- branching remains within configured budgets.

### Phase 4 — Open-ended exploration UX

Deliver:

- alternate seed hypotheses for bare handles;
- graph and list views;
- score/evidence comparison;
- “why this match?” and “why conflicting?” explanations;
- manual hints and platform search;
- background explore mode;
- graph revision history; and
- separate footprints for competing hypotheses.

Evaluate whether users correctly understand identity tiers, branch inheritance, and
the difference between “related account” and “same person.”

### Phase 5 — Footprint quality

Expand structured extraction and synthesis for:

- identity and aliases;
- work and organizations;
- projects and repositories;
- publications and creator content;
- topics and activity ranges;
- timeline events;
- stale and contradictory information; and
- account-specific qualifications.

Add deterministic templates first. Models may improve extraction and prose only when
their output remains source-bound.

### Phase 6 — Optional shared alpha

Only if the prototype is worth sharing:

- replace fixed local authentication;
- define provider, privacy, retention, removal, and acceptable-use policies;
- add infrastructure egress controls;
- add quotas, dashboards, incident runbooks, and secrets management;
- review connected-source permissions;
- decide which fields may be shown or exported; and
- run a controlled alpha.

This phase is a deployment decision, not a prerequisite for local discovery work.

---

## 13. Migration from the current implementation

### 13.1 Keep

The existing project already provides useful foundations:

- FastAPI + Next.js structure;
- PostgreSQL models and migrations;
- Celery/Redis orchestration;
- outbox/event flow;
- provider-run status taxonomy;
- Safe Fetch controls;
- immutable collection/analysis/report concepts;
- evidence and source lineage;
- deterministic report generation;
- SSE/polling patterns;
- deletion and retention helpers; and
- tests for lifecycle and fetch boundaries.

### 13.2 Replace or repurpose

| Current behavior | v3 direction |
|---|---|
| Direct GitHub URL only | Platform + user ID, URL, or bare handle |
| Profile ownership required | Optional control-proof `EvidenceSignal` |
| Manual eligibility approval | Removed from local search admission |
| GitHub adapter emits only display name/URL | Emit structured identifiers, links, and profile signals |
| Fixed two-provider fixture fan-out | Maigret core sweep plus dynamic native enrichers |
| Candidate correlation hidden behind report | Progressive visible identity graph |
| Confirmed-only account aggregation | User-selectable graph scope with qualification |
| Fast Brief as primary artifact | Candidate graph plus digital footprint |
| `/v1/search-jobs` eligibility payload | `/v1/footprint-jobs` seed/search options |

Eligibility code may remain temporarily behind a feature flag only during the contract
migration. It is removed from the user-facing API, UI, job admission path, and default
worker flow before Phase 2 exits. A future control proof is an optional `EvidenceSignal`
on an association edge, not a separate eligibility workflow or search-admission path.

### 13.3 Suggested implementation order

1. Record the Maigret-core ADR, exact dependency pin, and third-party notice.
2. Add a reviewed catalog snapshot and a tiny deterministic test catalog.
3. Add v3 graph/evidence and Maigret scan/site-check schema alongside existing tables.
4. Implement the Maigret library wrapper, notifier, status normalizer, and cancellation.
5. Add the new API contract and generated client.
6. Implement seed normalization, native seed resolution, and explicit-link extraction.
7. Implement host-controlled discovery planning from Maigret-extracted pivots.
8. Persist candidate nodes, discovery edges, and evidence signals.
9. Publish graph revisions, scan coverage, and SSE events.
10. Replace the landing form with platform + user-ID input.
11. Add candidate decisions and graph rebuilding.
12. Build the first graph-scoped footprint.
13. Remove eligibility routes, UI, admission checks, and worker dependencies from the
    v3 flow; retain only reusable control-proof code behind an evidence adapter if
    needed.
14. Expand catalog profiles and add native enrichment/search providers.

---

## 14. Test strategy

### 14.1 Unit tests

- platform/user-ID parsing and canonicalization;
- URL-to-provider detection;
- bare-handle seed hypotheses;
- product identifier type to Maigret `id_type` routing;
- Maigret four-status normalization and detailed error mapping;
- catalog selection by profile, site, tag, exclusion, and identifier type;
- catalog and selected-site fingerprinting;
- handle variants and rarity buckets;
- link-semantic classification;
- evidence-family caps and score calculation;
- positive and negative signal handling;
- lineage deduplication;
- path uncertainty;
- graph cycle detection;
- depth/fan-out/cost budgets;
- graph merge and split;
- user-decision overlays;
- account-scoped claim extraction; and
- footprint qualification.

### 14.2 Provider contract tests

For every adapter:

- successful resolution;
- no result;
- soft 404, private/limited, suspended, redirect, rename, and reassignment;
- timeout, rate limit, CAPTCHA, auth wall, and provider error;
- schema drift and malformed response;
- stable account ID behavior;
- outbound-link extraction;
- access-scope tagging;
- canonical URL rules; and
- deterministic fixtures.

The Maigret contract suite additionally covers:

- `CLAIMED`, `AVAILABLE`, `UNKNOWN`, and `ILLEGAL`;
- `is_similar` without promotion to same-person evidence;
- parsed `ids_usernames`, `ids_links`, and allowed `ids_data`;
- progress notifications and result ordering independence;
- partial output on cancellation or cutoff;
- automatic catalog update disabled;
- no cookies, proxy, Tor, I2P, or Cloudflare-bypass options;
- a stale-detector/soft-404 false positive;
- mirror/site selection and exact selected-site recording; and
- package/catalog/schema version provenance.

CI uses a tiny catalog whose hosts resolve to local fixtures. It does not rely on the
availability or behavior of live third-party sites.

### 14.3 Integration tests

- API → outbox → queue → provider → graph revision;
- API → outbox → `maigret_scan` queue → site checks → progressive candidates;
- dynamic child runs from a discovery edge;
- extracted Maigret ID → host-planned child scan with exact parent lineage;
- catalogue cutoff/cancellation → persisted partial checks and no orphan child work;
- duplicate delivery and retry;
- concurrent candidate updates;
- cutoff versus late evidence;
- SSE disconnect and replay;
- user decision during active discovery;
- footprint rebuild from a new graph revision;
- deletion during provider work;
- provider kill switch; and
- connected-source credential isolation.

### 14.4 Golden cases

- explicit reciprocal links;
- one-way “my account” link;
- common-handle false match;
- personal-domain match;
- organization link misclassified as personal;
- copied bio across unrelated profiles;
- handle reassignment;
- multilingual aliases;
- recursive branch with decreasing confidence;
- user-forced inclusion of a weak lead;
- competing identity clusters; and
- a footprint with qualified claims from a possible match.

### 14.5 Browser E2E

1. Enter a platform + user ID.
2. Watch the seed resolve and Maigret scan coverage advance.
3. Watch claimed candidates and extracted-ID pivots appear progressively.
4. Open a candidate's exact catalog-probe and association evidence.
5. Include one candidate and reject another.
6. Expand a possible branch.
7. Build the footprint.
8. Change the graph and rebuild.
9. Refresh and replay the same state.
10. Delete the job.

---

## 15. Acceptance criteria for the first useful prototype

### Product

- A user can search using a supported platform + ID, profile URL, or bare handle.
- A bare handle produces visible seed hypotheses rather than a forced identity.
- The default discovery path runs a real Maigret library scan, not a hand-built
  three-site fan-out or CLI subprocess.
- The system finds explicit links and catalog-probe candidates across at least three
  platform types in deterministic fixtures.
- The live prototype demonstrates a bounded Maigret scan with at least two candidate
  profiles beyond the seed.
- The UI reports selected/completed sites plus
  claimed/available/unknown/illegal coverage and catalog version.
- Candidates appear progressively with evidence and discovery paths.
- The user can include, exclude, merge, split, and expand candidates.
- The footprint is generated from the selected graph revision and can be rebuilt.

### Identity graph

- Candidate discovery is distinct from same-person association.
- Every association displays supporting and contradicting signals.
- Recursive child nodes preserve their path and inherited uncertainty.
- Every Maigret candidate cites the exact scan run and site check that produced it.
- Every extracted identifier/link cites its parent result; recursive scans are scheduled
  by the host rather than Maigret's CLI loop.
- Duplicate lineage does not inflate a match.
- Conflicting candidates remain inspectable.
- User decisions are overlays and do not rewrite source evidence.

### Footprint

- Every claim points to its source account and observation.
- Claims from provisional accounts are visibly qualified.
- Conflicts and stale information are not silently flattened.
- Coverage gaps and inaccessible providers are listed.
- The report never fabricates a profile, source, or citation.

### Reliability

- Provider failures do not erase other branches.
- Jobs, graph revisions, decisions, and footprint revisions are durable.
- SSE replay and polling converge on the same state.
- Duplicate/retried tasks do not create duplicate nodes or claims.
- Exploration stops cleanly at configured budgets.
- A repeated run against the same fixtures and catalog snapshot selects the same sites
  and normalizes the same results.
- Cancellation preserves completed Maigret site checks and prevents new recursive work.
- The full synthetic E2E runs through PostgreSQL, Redis, Celery, API, and browser.

---

## 16. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Same handle belongs to unrelated people | Treat handle match as a lead; compare independent signals and show alternatives |
| Maigret `CLAIMED` or site detector is a false positive | Treat it as candidate existence only; retain detector provenance, benchmark per site, enrich important candidates, and quarantine regressions |
| Site catalog changes alter results silently | Pin and checksum snapshots; disable auto-update; validate, diff, promote, and roll back explicitly |
| Large scans trigger rate limits or excessive traffic | Curated scan profiles, separate site/network budgets, bounded concurrency, backoff, circuit breakers, and user-triggered deep mode |
| Maigret's independent HTTP stack bypasses application fetch controls | Isolate the worker with allowlisted catalog egress and private/reserved address blocking; Safe Fetch all extracted URLs before enrichment |
| Upstream dependency or parser compromise | Exact lock, release/checksum review, dependency scanning, minimal worker permissions, and rapid adapter/catalog rollback |
| Cancellation loses in-memory scan progress | Consume notifications and persist bounded batches from the partial-output container |
| Recursive error amplification | Preserve path uncertainty; do not increase confidence through transitivity |
| Graph explosion | Depth, fan-out, provider-call, time, and cost budgets plus user steering |
| Search-result pollution or copied profiles | Preserve lineage, compare canonical sources, and add contradictions |
| A link points to an employer/project, not the person | Classify relationship type before same-person association |
| User confirms the wrong profile | Keep the decision as an overlay; enable split/revert and preserve evidence |
| Handle rename or reassignment | Store stable provider IDs and observation time separately from handles |
| Provider access changes | Capability registry, status mapping, fixtures, circuit breakers, and graceful gaps |
| Model invents relationships | Require source observation IDs and host-created nodes for every model proposal |
| Private/authorized data leaks into another job | Record access scope, isolate credentials and caches, and keep local owner boundaries |
| Footprint becomes an unsourced dossier | Account-scoped claims, citations, graph revision reference, and visible uncertainty |

---

## 17. Frozen v3.1 prototype decisions

1. The core input is a platform + user ID; URLs and bare handles are also accepted.
2. The local prototype may search any person or account.
3. Ownership verification is optional evidence, not a gate.
4. Maigret is the core broad username/identifier discovery engine, initially pinned to
   the reviewed `0.6.3` release.
5. Maigret's site catalog is pinned per scan; runtime auto-update is disabled.
6. Maigret finds candidates but never decides that accounts represent the same person.
7. Recursive pivots are scheduled by the host from Maigret's extracted IDs and links;
   the Maigret CLI recursive loop is not the product orchestrator.
8. Maigret's AI summary, reports, UI, and graph exports are not inputs to the product
   footprint.
9. Native provider adapters resolve the seed and enrich or verify high-value candidates.
10. Cross-platform candidate discovery is MVP functionality.
11. Recursive pivots are supported within configurable budgets.
12. Strong, weak, ambiguous, and conflicting candidates are visible.
13. The user can steer and override graph inclusion.
14. Every relationship retains evidence, contradictions, discovery path, time, and
   version.
15. The footprint is built from an explicit graph revision and node selection.
16. Sources may be public, requester-authorized, licensed, uploaded, or synthetic.
17. Access-control bypass is outside the product; Maigret's cookie, proxy, Tor, I2P,
    and Cloudflare-bypass options are disabled in the core adapter.
18. The current GitHub self-audit implementation is a starting slice, not the intended
    product boundary.

---

## 18. Immediate next steps

1. Write the Maigret-core ADR and add the exact `0.6.3` dependency pin, resolved lock,
   and MIT third-party notice.
2. Promote a reviewed Maigret catalog snapshot and create a tiny local test catalog.
3. Define `MaigretCatalogSnapshot`, `MaigretScanRun`, `MaigretSiteCheck`, identity-graph,
   and evidence JSON Schemas.
4. Implement the async `MaigretDiscoveryAdapter`, result normalizer, progress notifier,
   partial-result cancellation, and dedicated queue.
5. Build local fixtures for all four statuses, false positives, extracted IDs/links,
   collisions, contradictions, recursive pivots, and user decisions.
6. Replace the OpenAPI create-job payload with seed, scan-profile, and separate budget
   options.
7. Implement seed normalization and extend the GitHub adapter to resolve the root and
   emit structured links/identifiers for the Maigret frontier.
8. Implement host-controlled discovery planning, graph revision writing, and initial
   score breakdown.
9. Run one bounded, low-volume live Maigret smoke test and tune the quick catalog.
10. Replace the landing page with platform + user-ID search plus catalog progress.
11. Add candidate comparison, exact discovery evidence, and
    include/exclude/expand controls.
12. Build the first graph-scoped digital footprint and browser-to-worker E2E test.

The first milestone is successful when:

> `platform + user ID → seed account → candidate profiles → evidence graph → user
> selection → sourced digital footprint`

works end to end with fixtures, one low-volume live seed provider, and the live
Maigret-backed cross-platform discovery requirement in §15.
