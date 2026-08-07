# Deep person report template v3

This persisted-report format remains supported. New reports use the additive
[v4 template](./report-template-v4.md).

Deep reports answer the reader's practical questions before exposing account-resolution and
retrieval detail. The deterministic identity decision remains authoritative; the model supplies
an evidence-grounded portrait within that boundary.

## Reader-facing order

1. **Conclusion** — one plain-language sentence stating who the profile appears to represent and
   the most important uncertainty.
2. **Person profile** — fixed answers for identity, probable location, occupation, and education.
3. **Interests and preferences** — public interests, supported likes, and explicitly expressed
   dislikes. Empty categories render an explicit “not enough evidence” state.
4. **Public story** — a concise portrait covering identity, place, work, education, interests,
   online activity, and meaningful unknowns without repeating retrieval mechanics.
5. **Identity support** — the signals that connect or separate the assessed accounts.
6. **Account cluster and key findings** — account-level evidence and qualified claims.
7. **Unknowns, exclusions, and coverage** — gaps, isolated candidates, and unavailable channels.
8. **Evidence index** — source provenance, collapsed behind the report.

## Required profile fields

Every v3 synthesis returns these four answer objects:

- `identity`
- `location`
- `occupation`
- `education`

A supported answer includes a value, confidence, evidence basis, explanation, and at least one
source. An unsupported answer is explicit: `value: null`, `confidence: null`, `basis: unknown`, an
empty source list, and a useful explanation. The report must never replace a missing answer with a
plausible guess.

The profile also returns arrays for `interests`, `likes`, `dislikes`, and `unknowns`.

## Preference rules

- An **interest** requires an explicit self-description or a repeated public activity pattern.
- A **like** requires an explicit positive statement or repeated voluntary engagement.
- A **dislike** requires an explicit first-person negative statement. Silence, absence, follows,
  unfollows, emojis, or a single negative interaction are not sufficient.
- Sparse or missing evidence produces an empty array and a reader-facing unknown, not filler.

## Writing rules

- Write natural prose for a general reader, not a retrieval log.
- Do not mention packets, schemas, trust-class names, scanners, providers, raw field names, or
  source identifiers in the prose.
- Distinguish current/recent facts from historical or potentially stale indexed information.
- Keep account existence separate from same-person association.
- Do not infer sensitive traits, private relationships, competence, seniority, or character.
- Every supported field and narrative claim must cite only evidence included in the run.

## Backward compatibility

Persisted v1 and v2 synthesis outputs remain readable. New provider requests produce v3. The API's
`subject_profile` field is optional only so older saved reports can still render.

## Candidate extensions

The following are intentionally outside the required v3 core and should be added only when the
retrieval layer can support them consistently:

- aliases and name variants;
- languages used publicly;
- career and education timeline with freshness dates;
- notable projects, publications, and creative work;
- public communities and recurring topics;
- online activity style and platform purpose;
- contradictions or material changes over time;
- last-seen freshness for each major fact;
- a compact “why this matters” or self-audit risk section.
