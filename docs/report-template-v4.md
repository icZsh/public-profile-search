# Deep person report template v4

Deep reports answer the reader's core questions first. Compared with v3, v4 adds one
structured, evidence-linked career and education timeline without turning weak signals
into facts.

## Reader order

1. One-sentence conclusion and identity confidence
2. Identity, probable location, occupation, and education answers
3. Career and education timeline
4. Public interests, likes, and explicitly expressed dislikes
5. Evidence-backed public story
6. Identity support, exclusions, coverage, unknowns, and evidence index

## v4 addition

### Career and education timeline

Each item contains a work-or-education type, title, optional organization and
source-faithful timeframe, currentness, confidence, basis, explanation, and citations.
Indexed entries presented as current without dates are normalized to `unclear` because
they may be stale. The report does not invent dates or infer career history from
interests.

## Validation behavior

- Every non-empty timeline item cites only source IDs in the frozen evidence snapshot.
- Unknown citations invalidate the synthesized story.
- Weak or semantically unsupported timeline items are omitted without discarding valid
  sibling items or the whole report.
- An empty timeline is valid and renders an explicit not-enough-evidence state.
- Persisted v2 and v3 reports remain readable; only `deep-story-v4` displays the new
  career and education timeline.

## Retrieval limitation

Professional records can often support a useful timeline. When providers return only
account-existence metadata or undated claims, the timeline will correctly remain sparse.
