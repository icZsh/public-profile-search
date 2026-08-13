"use client";

import type {
  EvidenceItem,
  FootprintBrief,
  FootprintCoverage,
  FootprintSynthesisModel,
} from "@public-profile-search/generated-api-client";
import { useId, useMemo, useState } from "react";

import {
  DEFAULT_SYNTHESIS_MODEL,
  SYNTHESIS_MODEL_OPTIONS,
} from "@/lib/synthesis-models";

type ReviewState = "open" | "verified" | "excluded";

export interface TraceFootprintBriefProps {
  brief: FootprintBrief;
  evidence: EvidenceItem[];
  coverage?: FootprintCoverage;
  seedLabel?: string;
  searchMode?: "quick" | "deep" | null;
  onRunDeep?: (model: FootprintSynthesisModel) => void;
  upgrading?: boolean;
}

interface PersonRow {
  key: string;
  label: string;
  value: string;
  detail: string | null;
  confidence: string | null;
  sourceIds: string[];
}

interface CompetingName {
  name: string;
  accountCount: number;
  reasons: string[];
  sourceIds: string[];
}

function words(value: string): string {
  return value.replaceAll("_", " ");
}

function sentenceCase(value: string): string {
  const readable = words(value).trim();
  return readable ? `${readable[0].toUpperCase()}${readable.slice(1)}` : readable;
}

function safeHttpsHref(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.valueOf())) return "Date unavailable";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function initialReviewState(
  account: FootprintBrief["accounts"][number],
): ReviewState {
  if (
    account.identity_status === "excluded" ||
    account.existence_status === "excluded"
  ) {
    return "excluded";
  }
  return account.existence_status === "exact_verified" ? "verified" : "open";
}

function deriveSeedLabel(brief: FootprintBrief, seedLabel?: string): string {
  const explicitSeed = seedLabel?.trim();
  if (explicitSeed) return explicitSeed;

  const handleCounts = new Map<string, number>();
  brief.accounts.forEach((account) => {
    const handle = account.handle.trim();
    if (!handle) return;
    handleCounts.set(handle, (handleCounts.get(handle) ?? 0) + 1);
  });
  const commonHandle = [...handleCounts.entries()].sort(
    ([leftHandle, leftCount], [rightHandle, rightCount]) =>
      rightCount - leftCount || leftHandle.localeCompare(rightHandle),
  )[0]?.[0];
  if (commonHandle) {
    return commonHandle.startsWith("@") ? commonHandle : `@${commonHandle}`;
  }
  return brief.subject;
}

function deriveWorkingSubject(brief: FootprintBrief): string {
  return (
    brief.deep_story?.subject_profile?.identity.value?.trim() ||
    brief.deep_story?.likely_public_identity?.trim() ||
    brief.subject
  );
}

function deriveCompetingName(brief: FootprintBrief): CompetingName | null {
  const workingNames = new Set(
    [
      brief.subject,
      brief.deep_story?.likely_public_identity ?? "",
      brief.deep_story?.subject_profile?.identity.value ?? "",
    ]
      .map((name) => name.trim().toLocaleLowerCase())
      .filter(Boolean),
  );
  const candidates = new Map<
    string,
    {
      name: string;
      accountCount: number;
      confidenceScore: number;
      reasons: string[];
      sourceIds: string[];
    }
  >();
  const confidenceScores: Record<
    FootprintBrief["accounts"][number]["confidence"],
    number
  > = {
    high: 4,
    medium_high: 3,
    medium: 2,
    low: 1,
  };

  brief.accounts.forEach((account) => {
    const name = account.display_name?.trim();
    if (
      !name ||
      workingNames.has(name.toLocaleLowerCase()) ||
      account.identity_status === "excluded" ||
      account.existence_status === "excluded"
    ) {
      return;
    }
    const key = name.toLocaleLowerCase();
    const candidate = candidates.get(key) ?? {
      name,
      accountCount: 0,
      confidenceScore: 0,
      reasons: [],
      sourceIds: [],
    };
    candidate.accountCount += 1;
    candidate.confidenceScore += confidenceScores[account.confidence];
    candidate.reasons.push(...account.reasons);
    candidate.sourceIds.push(...account.source_ids);
    candidates.set(key, candidate);
  });

  const winner = [...candidates.values()].sort(
    (left, right) =>
      right.accountCount - left.accountCount ||
      right.confidenceScore - left.confidenceScore ||
      left.name.localeCompare(right.name),
  )[0];
  if (!winner) return null;
  return {
    name: winner.name,
    accountCount: winner.accountCount,
    reasons: unique(winner.reasons),
    sourceIds: unique(winner.sourceIds),
  };
}

function buildSourceUses(brief: FootprintBrief): Map<string, string[]> {
  const uses = new Map<string, Set<string>>();
  const record = (label: string, sourceIds: string[]) => {
    sourceIds.forEach((sourceId) => {
      const labels = uses.get(sourceId) ?? new Set<string>();
      labels.add(label);
      uses.set(sourceId, labels);
    });
  };

  brief.accounts.forEach((account) =>
    record(`${sentenceCase(account.platform)} account`, account.source_ids),
  );
  brief.claims.forEach((claim) => record(claim.label, claim.source_ids));
  (brief.narrative_sections ?? []).forEach((section) => {
    record(section.title, section.source_ids);
    section.highlights.forEach((highlight) =>
      record(`${section.title} detail`, highlight.source_ids),
    );
  });

  const story = brief.deep_story;
  if (story) {
    record("Brief conclusion", story.conclusion_source_ids);
    record("Evidence overview", story.overview_source_ids);
    story.identity_facts.forEach((fact) =>
      record(fact.label, fact.source_ids),
    );
    story.account_insights.forEach((insight) => {
      record("Account assessment", insight.source_ids);
      insight.public_facts.forEach((fact) => record("Account fact", fact.source_ids));
      insight.association_reasons.forEach((reason) =>
        record("Account association", reason.source_ids),
      );
    });
    story.curated_claims.forEach((claim) => {
      record(claim.label, [...claim.source_ids, ...claim.contradicting_source_ids]);
      claim.supporting_evidence.forEach((item) =>
        record(claim.label, item.source_ids),
      );
      claim.limiting_evidence.forEach((item) =>
        record(`${claim.label} boundary`, item.source_ids),
      );
    });
    story.excluded_candidates.forEach((candidate) =>
      record(`Set aside: ${candidate.label}`, candidate.source_ids),
    );
    story.channel_coverage.forEach((channel) =>
      record(`${channel.channel} coverage`, channel.source_ids),
    );
    story.next_verification_steps.forEach((step) =>
      record("Reassessment condition", step.source_ids),
    );

    const profile = story.subject_profile;
    if (profile) {
      record("Identity", profile.identity.source_ids);
      record("Location", profile.location.source_ids);
      record("Occupation", profile.occupation.source_ids);
      record("Education", profile.education.source_ids);
      [...profile.interests, ...profile.likes, ...profile.dislikes].forEach((trait) =>
        record(trait.label, trait.source_ids),
      );
      profile.unknowns.forEach((item) =>
        record(`${sentenceCase(item.topic)} limit`, item.source_ids),
      );
      profile.career_timeline.forEach((entry) =>
        record(`${sentenceCase(entry.entry_type)} timeline`, entry.source_ids),
      );
    }
  }

  return new Map([...uses].map(([sourceId, labels]) => [sourceId, [...labels]]));
}

function buildPersonRows(brief: FootprintBrief): PersonRow[] {
  const story = brief.deep_story;
  const profile = story?.subject_profile;
  if (!profile) {
    const identityRows = (story?.identity_facts ?? []).map((fact, index) => ({
      key: `identity-fact-${index}`,
      label: fact.label,
      value: fact.value,
      detail: fact.qualification,
      confidence: fact.confidence,
      sourceIds: fact.source_ids,
    }));
    if (identityRows.length) return identityRows;
    return brief.claims.map((claim) => ({
      key: claim.claim_id,
      label: claim.label,
      value: claim.value,
      detail: claim.qualification,
      confidence: claim.confidence,
      sourceIds: claim.source_ids,
    }));
  }

  const rows: PersonRow[] = [
    {
      key: "location",
      label: "Location",
      value: profile.location.value ?? "Not established",
      detail: profile.location.explanation,
      confidence: profile.location.confidence,
      sourceIds: profile.location.source_ids,
    },
    {
      key: "occupation",
      label: "Occupation",
      value: profile.occupation.value ?? "Not established",
      detail: profile.occupation.explanation,
      confidence: profile.occupation.confidence,
      sourceIds: profile.occupation.source_ids,
    },
    {
      key: "education",
      label: "Education",
      value: profile.education.value ?? "Not established",
      detail: profile.education.explanation,
      confidence: profile.education.confidence,
      sourceIds: profile.education.source_ids,
    },
  ];

  const traitGroups = [
    { key: "interests", label: "Interests", items: profile.interests },
    { key: "likes", label: "Appears to like", items: profile.likes },
    { key: "dislikes", label: "Explicitly dislikes", items: profile.dislikes },
  ];
  traitGroups.forEach((group) => {
    if (!group.items.length) return;
    rows.push({
      key: group.key,
      label: group.label,
      value: group.items.map((item) => item.label).join(", "),
      detail: group.items.map((item) => item.explanation).join(" "),
      confidence: group.items[0].confidence,
      sourceIds: unique(group.items.flatMap((item) => item.source_ids)),
    });
  });

  profile.career_timeline.forEach((entry, index) => {
    const context = [entry.organization, entry.timeframe].filter(Boolean).join(" · ");
    rows.push({
      key: `timeline-${index}`,
      label: `${sentenceCase(entry.entry_type)} timeline`,
      value: context ? `${entry.title} · ${context}` : entry.title,
      detail: entry.explanation,
      confidence: entry.confidence,
      sourceIds: entry.source_ids,
    });
  });

  if (profile.unknowns.length) {
    rows.push({
      key: "not-found",
      label: "Not found",
      value: unique(profile.unknowns.map((item) => sentenceCase(item.topic))).join(", "),
      detail: unique(profile.unknowns.map((item) => item.explanation)).join(" "),
      confidence: null,
      sourceIds: unique(profile.unknowns.flatMap((item) => item.source_ids)),
    });
  }
  return rows;
}

function limitationLabel(limitation: string, index: number): string {
  const normalized = limitation.toLocaleLowerCase();
  if (normalized.includes("occupation") || normalized.includes("employ")) {
    return "Occupation";
  }
  if (normalized.includes("education") || normalized.includes("school")) {
    return "Education";
  }
  if (normalized.includes("person") || normalized.includes("identity")) {
    return "One person?";
  }
  if (normalized.includes("site") || normalized.includes("channel")) {
    return "Coverage";
  }
  return `Limit ${String(index + 1).padStart(2, "0")}`;
}

function CitationGroup({
  sourceIds,
  evidenceById,
  sourceNumbers,
  focusedId,
  onFocus,
  label,
}: {
  sourceIds: string[];
  evidenceById: Map<string, EvidenceItem>;
  sourceNumbers: Map<string, number>;
  focusedId: string | null;
  onFocus: (sourceId: string) => void;
  label: string;
}) {
  const sources = unique(sourceIds)
    .map((sourceId) => evidenceById.get(sourceId))
    .filter((item): item is EvidenceItem => Boolean(item));
  if (!sources.length) return null;

  return (
    <span className="traceSourceCitations" aria-label={label}>
      {sources.map((source) => {
        const sourceNumber = sourceNumbers.get(source.evidence_id);
        return (
          <button
            className={`traceSourceCitation${
              focusedId === source.evidence_id ? " traceSourceCitationActive" : ""
            }`}
            key={source.evidence_id}
            type="button"
            onClick={() => onFocus(source.evidence_id)}
            aria-label={`Focus source ${sourceNumber ?? source.evidence_id}: ${source.title}`}
            aria-pressed={focusedId === source.evidence_id}
          >
            {sourceNumber ?? "Source"}
          </button>
        );
      })}
    </span>
  );
}

function ReviewActions({
  account,
  state,
  onChange,
}: {
  account: FootprintBrief["accounts"][number];
  state: ReviewState;
  onChange: (nextState: ReviewState) => void;
}) {
  if (state === "excluded") {
    return (
      <div className="traceReviewActions">
        <button
          className="traceReviewButton"
          type="button"
          onClick={() => onChange("open")}
          aria-label={`Undo local exclusion of ${account.platform} @${account.handle}`}
        >
          Undo
        </button>
      </div>
    );
  }

  return (
    <div className="traceReviewActions">
      <button
        className={`traceReviewButton${
          state === "verified" ? " traceReviewButtonVerified" : ""
        }`}
        type="button"
        onClick={() => onChange("verified")}
        aria-pressed={state === "verified"}
      >
        {state === "verified" ? "Verified" : "Verify"}
      </button>
      <button
        className="traceReviewButton traceReviewButtonExclude"
        type="button"
        onClick={() => onChange("excluded")}
      >
        Exclude
      </button>
    </div>
  );
}

function SourceSidebar({
  evidence,
  focusedId,
  onFocus,
  sourceNumbers,
  sourceUses,
  coverage,
  quick,
}: {
  evidence: EvidenceItem[];
  focusedId: string | null;
  onFocus: (sourceId: string) => void;
  sourceNumbers: Map<string, number>;
  sourceUses: Map<string, string[]>;
  coverage?: FootprintCoverage;
  quick: boolean;
}) {
  const focusedSource =
    evidence.find((item) => item.evidence_id === focusedId) ?? evidence[0] ?? null;
  const sourceHref = focusedSource ? safeHttpsHref(focusedSource.url) : null;
  const focusedUses = focusedSource
    ? (sourceUses.get(focusedSource.evidence_id) ?? [])
    : [];

  return (
    <aside className="traceSourceSidebar" aria-label="Evidence sources">
      <div className="traceSourcePanel">
        {!quick ? (
          <>
            <div className="traceSourceEyebrow">Source in focus</div>
            {focusedSource ? (
              <article className="traceSourceFocus" aria-live="polite">
                <div className="traceSourceFocusHeading">
                  <strong>
                    {sourceNumbers.get(focusedSource.evidence_id)} · {focusedSource.title}
                  </strong>
                  <span>Focused</span>
                </div>
                <div className="traceSourceProvenance">
                  {sentenceCase(focusedSource.source_type)} · {focusedSource.publisher} · retrieved{" "}
                  {formatDate(focusedSource.retrieved_at)}
                </div>
                {focusedSource.excerpt ? (
                  <blockquote className="traceSourceExcerpt">
                    {focusedSource.excerpt}
                  </blockquote>
                ) : (
                  <p className="traceSourceUnavailable">No source excerpt is available.</p>
                )}
                {sourceHref ? (
                  <a
                    className="traceSourceOpenLink"
                    href={sourceHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    referrerPolicy="no-referrer"
                  >
                    Open source
                  </a>
                ) : (
                  <span className="traceSourceUnavailable">Source link unavailable</span>
                )}
              </article>
            ) : (
              <p className="traceSourceEmpty">This brief has no displayable source record.</p>
            )}

            {focusedUses.length ? (
              <div className="traceSourceUses">
                <div className="traceSourceSubheading">
                  Carries {focusedUses.length} claim{focusedUses.length === 1 ? "" : "s"}
                </div>
                <ul>
                  {focusedUses.map((use) => (
                    <li key={use}>{use}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        ) : null}

        <div className="traceSourceIndex">
          <div className="traceSourceIndexHeading">
            <div className="traceSourceSubheading">All sources</div>
            <span>{evidence.length}</span>
          </div>
          {evidence.length ? (
            <ol className="traceSourceList">
              {evidence.map((item) => {
                const isFocused = focusedSource?.evidence_id === item.evidence_id;
                return (
                  <li key={item.evidence_id}>
                    <button
                      className={`traceSourceRow${
                        isFocused ? " traceSourceRowActive" : ""
                      }`}
                      type="button"
                      onClick={() => onFocus(item.evidence_id)}
                      aria-pressed={isFocused}
                    >
                      <span className="traceSourceNumber">
                        {sourceNumbers.get(item.evidence_id)}
                      </span>
                      <span className="traceSourceTitle">{item.title}</span>
                      <span className="traceSourceClass">
                        {sentenceCase(item.trust_class)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          ) : null}
        </div>

        {coverage ? (
          <div className="traceSourceCoverage">
            <div className="traceSourceSubheading">Coverage</div>
            <p>
              {coverage.completed} of {coverage.selected || coverage.completed} sites checked.
              {coverage.unknown
                ? ` ${coverage.unknown} did not return a usable result in this window.`
                : ""}
              {coverage.illegal
                ? ` ${coverage.illegal} could not be queried under this scan policy.`
                : ""}
            </p>
            <dl>
              <div>
                <dt>Claimed</dt>
                <dd>{coverage.claimed}</dd>
              </div>
              <div>
                <dt>Available</dt>
                <dd>{coverage.available}</dd>
              </div>
            </dl>
          </div>
        ) : null}

        {quick ? (
          <div className="traceBriefPolicy traceBriefPolicyCompact">
            <strong>Policy</strong>
            <span>
              No private contact details, facial recognition, or avatar-based identity
              merging.
            </span>
          </div>
        ) : null}
      </div>
    </aside>
  );
}

export function TraceFootprintBrief({
  brief,
  evidence,
  coverage,
  seedLabel,
  searchMode,
  onRunDeep,
  upgrading = false,
}: TraceFootprintBriefProps) {
  const titleId = useId();
  const isQuick =
    searchMode === "quick" ||
    (searchMode == null && brief.report_type === "account_centric" && !brief.deep_story);
  const story = brief.deep_story ?? null;
  const workingSubject = deriveWorkingSubject(brief);
  const resolvedSeedLabel = deriveSeedLabel(brief, seedLabel);
  const competingName = isQuick ? null : deriveCompetingName(brief);
  const personRows = useMemo(() => buildPersonRows(brief), [brief]);
  const evidenceById = useMemo(
    () => new Map(evidence.map((item) => [item.evidence_id, item])),
    [evidence],
  );
  const sourceNumbers = useMemo(
    () => new Map(evidence.map((item, index) => [item.evidence_id, index + 1])),
    [evidence],
  );
  const sourceUses = useMemo(() => buildSourceUses(brief), [brief]);
  const preferredSourceId =
    story?.subject_profile?.occupation.source_ids.find((sourceId) =>
      evidenceById.has(sourceId),
    ) ??
    story?.conclusion_source_ids.find((sourceId) => evidenceById.has(sourceId)) ??
    brief.accounts
      .flatMap((account) => account.source_ids)
      .find((sourceId) => evidenceById.has(sourceId)) ??
    evidence[0]?.evidence_id ??
    null;
  const [focusedSourceId, setFocusedSourceId] = useState<string | null>(
    preferredSourceId,
  );
  const effectiveFocusedSourceId = evidenceById.has(focusedSourceId ?? "")
    ? focusedSourceId
    : preferredSourceId;
  const [reviewOverrides, setReviewOverrides] = useState<Record<string, ReviewState>>(
    {},
  );
  const [reviewRestoreStates, setReviewRestoreStates] = useState<
    Record<string, ReviewState>
  >({});
  const [selectedModel, setSelectedModel] =
    useState<FootprintSynthesisModel>(DEFAULT_SYNTHESIS_MODEL);
  const accountInsights = useMemo(
    () =>
      new Map(
        (story?.account_insights ?? []).map((insight) => [insight.account_id, insight]),
      ),
    [story],
  );

  const effectiveReviewState = (account: FootprintBrief["accounts"][number]) =>
    reviewOverrides[account.candidate_id] ?? initialReviewState(account);
  const changeReviewState = (
    account: FootprintBrief["accounts"][number],
    currentState: ReviewState,
    nextState: ReviewState,
  ) => {
    const accountId = account.candidate_id;
    if (nextState === "excluded") {
      setReviewRestoreStates((current) => ({
        ...current,
        [accountId]: currentState,
      }));
      setReviewOverrides((current) => ({
        ...current,
        [accountId]: "excluded",
      }));
      return;
    }

    const restoredState =
      currentState === "excluded" && nextState === "open"
        ? (reviewRestoreStates[accountId] ?? initialReviewState(account))
        : nextState;
    setReviewRestoreStates((current) => {
      const updated = { ...current };
      delete updated[accountId];
      return updated;
    });
    setReviewOverrides((current) => {
      const updated = { ...current };
      if (restoredState === initialReviewState(account)) {
        delete updated[accountId];
      } else {
        updated[accountId] = restoredState;
      }
      return updated;
    });
  };
  const verifiedCount = brief.accounts.filter(
    (account) => effectiveReviewState(account) === "verified",
  ).length;
  const excludedCount = brief.accounts.filter(
    (account) => effectiveReviewState(account) === "excluded",
  ).length;
  const openCount = Math.max(0, brief.accounts.length - verifiedCount - excludedCount);
  const confidenceLabel = isQuick
    ? "Accounts only"
    : sentenceCase(story?.overall_confidence ?? brief.overall_identity_status);
  const confidenceNote = isQuick
    ? "The accounts exist. Whether they belong to one person is not answered here."
    : story?.major_boundary ||
      brief.identity_reasons.limiting[0] ||
      "The conclusion remains bounded by the cited public evidence.";
  const quickLimitations = brief.limitations.length
    ? brief.limitations
    : [
        "Occupation was not established in this run.",
        "Education was not established in this run.",
        "The accounts were not reconciled to one person.",
      ];

  const focusSources = (
    sourceIds: string[],
    label: string,
  ) => (
    <CitationGroup
      sourceIds={sourceIds}
      evidenceById={evidenceById}
      sourceNumbers={sourceNumbers}
      focusedId={effectiveFocusedSourceId}
      onFocus={setFocusedSourceId}
      label={label}
    />
  );

  return (
    <section
      className={`traceBriefRoot ${isQuick ? "traceQuickRoot" : "traceBriefDeep"}`}
      aria-labelledby={titleId}
    >
      <div className="traceBriefLayout">
        <main className="traceBriefDocumentWrap">
          <article className="traceBriefPaper">
            <header className="traceBriefHeader">
              <div className="traceBriefTitleBlock">
                <div className="traceBriefEyebrow">
                  {isQuick ? "Quick brief" : "Public footprint brief"}
                </div>
                <h1 id={titleId}>{isQuick ? brief.subject : workingSubject}</h1>
                <div className="traceBriefSeed">
                  {isQuick
                    ? "no single person established"
                    : `seeded from ${resolvedSeedLabel}`}
                </div>
              </div>
              <dl className="traceBriefMetadata">
                <dt>Status</dt>
                <dd>
                  {isQuick
                    ? "Account-level"
                    : sentenceCase(brief.overall_identity_status)}
                </dd>
                <dt>Snapshot</dt>
                <dd>{formatDate(brief.generated_at)}</dd>
                <dt>Sources</dt>
                <dd>{evidence.length} cited</dd>
                {!isQuick ? (
                  <>
                    <dt>Accounts</dt>
                    <dd>
                      {brief.accounts.length} assessed, {excludedCount} set aside
                    </dd>
                  </>
                ) : null}
              </dl>
            </header>

            <div className="traceBriefLead">
              <div className="traceBriefLeadSummary">
                <p>{brief.summary}</p>
                {story
                  ? focusSources(story.conclusion_source_ids, "Brief summary sources")
                  : null}
              </div>
              <aside className="traceBriefConfidence">
                <div>Confidence</div>
                <strong>{confidenceLabel}</strong>
                <p>{confidenceNote}</p>
              </aside>
            </div>

            {competingName ? (
              <section className="traceBriefCompeting" aria-labelledby={`${titleId}-competing`}>
                <h2 id={`${titleId}-competing`}>Competing name in the cluster</h2>
                <div className="traceBriefCompetingGrid">
                  <article className="traceBriefSubjectCard">
                    <div className="traceBriefSubjectCardHeading">
                      <span>Working subject</span>
                      <strong>{sentenceCase(brief.overall_identity_status)}</strong>
                    </div>
                    <h3>{workingSubject}</h3>
                    {brief.identity_reasons.supporting.length ? (
                      <ul>
                        {unique(brief.identity_reasons.supporting)
                          .slice(0, 4)
                          .map((reason) => (
                            <li key={reason}>{reason}</li>
                          ))}
                      </ul>
                    ) : (
                      <p>The working subject is supported by the person-level synthesis.</p>
                    )}
                    {brief.identity_reasons.limiting[0] ? (
                      <p className="traceBriefSubjectBoundary">
                        {brief.identity_reasons.limiting[0]}
                      </p>
                    ) : null}
                  </article>
                  <article className="traceBriefSubjectCard traceBriefSubjectCardCompeting">
                    <div className="traceBriefSubjectCardHeading">
                      <span>Competing name</span>
                      <strong>Account-level</strong>
                    </div>
                    <h3>{competingName.name}</h3>
                    {competingName.reasons.length ? (
                      <ul>
                        {competingName.reasons.slice(0, 4).map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                    ) : (
                      <p>
                        This display name appears on {competingName.accountCount} public
                        account{competingName.accountCount === 1 ? "" : "s"}.
                      </p>
                    )}
                    {focusSources(
                      competingName.sourceIds,
                      `${competingName.name} sources`,
                    )}
                  </article>
                </div>
              </section>
            ) : null}

            {!isQuick ? (
              <section className="traceBriefSection" aria-labelledby={`${titleId}-person`}>
                <h2 id={`${titleId}-person`}>§1 · The person</h2>
                <div className="traceBriefPersonRows">
                  {personRows.length ? (
                    personRows.map((row) => (
                      <article
                        className={`traceBriefPersonRow${
                          row.confidence ? "" : " traceBriefPersonRowUnknown"
                        }`}
                        key={row.key}
                      >
                        <span className="traceBriefPersonLabel">{row.label}</span>
                        <div className="traceBriefPersonValue">
                          <strong>{row.value}</strong>
                          {focusSources(row.sourceIds, `${row.label} sources`)}
                          {row.detail ? <p>{row.detail}</p> : null}
                        </div>
                        <span className="traceBriefConfidenceText">
                          {row.confidence
                            ? `${sentenceCase(row.confidence)} confidence`
                            : "Not established"}
                        </span>
                      </article>
                    ))
                  ) : (
                    <p className="traceBriefEmpty">
                      No person-level detail met the evidence threshold.
                    </p>
                  )}
                </div>
              </section>
            ) : null}

            <section className="traceBriefSection" aria-labelledby={`${titleId}-accounts`}>
              <div className="traceBriefSectionHeading">
                <h2 id={`${titleId}-accounts`}>
                  {isQuick ? "§1 · The account cluster" : "§2 · The account cluster"}
                </h2>
                <span>
                  {verifiedCount} verified · {openCount} open · {excludedCount} set aside
                </span>
              </div>
              <div className="traceReviewNotice" role="note">
                <strong>View-only review</strong>
                <span>
                  Verify, exclude, and undo choices stay in this local view. They do not
                  change the saved evidence brief.
                </span>
              </div>
              <div className="traceBriefAccountRows">
                {brief.accounts.map((account) => {
                  const reviewState = effectiveReviewState(account);
                  const insight = accountInsights.get(account.candidate_id);
                  const profileHref = safeHttpsHref(account.profile_url);
                  const accountSources = unique([
                    ...account.source_ids,
                    ...(insight?.source_ids ?? []),
                  ]);
                  const detail =
                    insight?.rationale ||
                    account.reasons.join(" · ") ||
                    `${sentenceCase(account.existence_status)} · ${sentenceCase(
                      account.identity_status,
                    )}`;
                  return (
                    <article
                      className={`traceBriefAccountRow traceReviewState-${reviewState}${
                        reviewState === "excluded" ? " traceReviewExcluded" : ""
                      }`}
                      key={account.candidate_id}
                    >
                      <div className="traceBriefAccountIdentity">
                        <strong>{sentenceCase(account.platform)}</strong>
                        <span>@{account.handle.replace(/^@/, "")}</span>
                      </div>
                      <div className="traceBriefAccountDetail">
                        {account.display_name ? <strong>{account.display_name}</strong> : null}
                        <p>{detail}</p>
                        {focusSources(
                          accountSources,
                          `${account.platform} @${account.handle} sources`,
                        )}
                        {profileHref ? (
                          <a
                            className="traceBriefProfileLink"
                            href={profileHref}
                            target="_blank"
                            rel="noopener noreferrer"
                            referrerPolicy="no-referrer"
                          >
                            Open public profile
                          </a>
                        ) : null}
                      </div>
                      <ReviewActions
                        account={account}
                        state={reviewState}
                        onChange={(nextState) =>
                          changeReviewState(account, reviewState, nextState)
                        }
                      />
                    </article>
                  );
                })}
              </div>

              {!isQuick && story?.excluded_candidates.length ? (
                <div className="traceBriefSetAside">
                  <strong>Also kept outside the working cluster</strong>
                  <ul>
                    {story.excluded_candidates.map((candidate, index) => (
                      <li key={`${candidate.label}-${index}`}>
                        <span>
                          {candidate.label} · {sentenceCase(candidate.disposition)} —{" "}
                          {candidate.reason}
                        </span>
                        {focusSources(
                          candidate.source_ids,
                          `${candidate.label} exclusion sources`,
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>

            {isQuick ? (
              <>
                <section
                  className="traceBriefSection traceQuickLimits"
                  aria-labelledby={`${titleId}-limits`}
                >
                  <h2 id={`${titleId}-limits`}>§2 · What Quick could not answer</h2>
                  <div className="traceQuickLimitRows">
                    {quickLimitations.map((limitation, index) => (
                      <div className="traceQuickLimitRow" key={`${limitation}-${index}`}>
                        <span>{limitationLabel(limitation, index)}</span>
                        <p>{limitation}</p>
                      </div>
                    ))}
                  </div>
                </section>
                <div className="traceQuickCta">
                  <div>
                    <strong>Deep would search the professional record</strong>
                    <span>
                      Wider discovery, name-based people search, and an evidence-linked
                      person brief with a public career timeline.
                    </span>
                  </div>
                  <label className="traceQuickModelChoice">
                    <span>Story model</span>
                    <select
                      className="traceQuickModelSelect"
                      value={selectedModel}
                      onChange={(event) =>
                        setSelectedModel(
                          event.target.value as FootprintSynthesisModel,
                        )
                      }
                      disabled={upgrading}
                    >
                      {SYNTHESIS_MODEL_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    onClick={() => onRunDeep?.(selectedModel)}
                    disabled={!onRunDeep || upgrading}
                  >
                    {upgrading ? "Starting Deep…" : "Run Deep on this handle"}
                  </button>
                </div>
              </>
            ) : (
              <section
                className="traceBriefSection traceBriefConclusion"
                aria-labelledby={`${titleId}-conclusion`}
              >
                <h2 id={`${titleId}-conclusion`}>
                  §3 · Where it holds and where it stops
                </h2>
                <div className="traceBriefConclusionBody">
                  {story?.overview && story.overview !== story.conclusion ? (
                    <p>
                      {story.overview}
                      {focusSources(story.overview_source_ids, "Overview sources")}
                    </p>
                  ) : null}
                  <p>
                    {story?.conclusion ?? brief.summary}
                    {story
                      ? focusSources(
                          story.conclusion_source_ids,
                          "Conclusion sources",
                        )
                      : null}
                  </p>
                  {story?.major_boundary ? <p>{story.major_boundary}</p> : null}
                </div>

                {story?.next_verification_steps.length ? (
                  <div className="traceBriefNextSteps">
                    <strong>What would change this assessment</strong>
                    <ol>
                      {story.next_verification_steps.map((step, index) => (
                        <li key={`next-step-${index}`}>
                          <span>{step.text}</span>
                          {focusSources(
                            step.source_ids,
                            `Reassessment condition ${index + 1} sources`,
                          )}
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : null}

                <div className="traceBriefLimits">
                  <strong>Limits of this brief</strong>
                  {brief.limitations.length ? (
                    <ul>
                      {brief.limitations.map((limitation, index) => (
                        <li key={`${limitation}-${index}`}>{limitation}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>No additional limitation was recorded.</p>
                  )}
                </div>

                <div className="traceBriefPolicy">
                  <strong>Policy</strong>
                  <span>
                    No private contact details, facial recognition, or avatar-based
                    identity merging. This brief is for self-audit and must not be used
                    for employment, education, credit, or housing decisions.
                  </span>
                </div>
              </section>
            )}
          </article>
        </main>

        <SourceSidebar
          evidence={evidence}
          focusedId={effectiveFocusedSourceId}
          onFocus={setFocusedSourceId}
          sourceNumbers={sourceNumbers}
          sourceUses={sourceUses}
          coverage={coverage}
          quick={isQuick}
        />
      </div>
    </section>
  );
}
