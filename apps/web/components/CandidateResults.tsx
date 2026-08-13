import type {
  AccountCandidate,
  CandidateList,
} from "@public-profile-search/generated-api-client";

function safeProfileHref(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

function candidateTitle(candidate: AccountCandidate): string {
  return candidate.display_name?.trim() || `@${candidate.handle}`;
}

interface AnchorChoice {
  candidate: AccountCandidate;
  candidates: AccountCandidate[];
}

export function CandidateResults({
  candidates,
  running,
  stopped = false,
  awaitingAnchor = false,
  selectingCandidateId = null,
  anchorError = "",
  onSelectAnchor,
}: {
  candidates: CandidateList;
  running: boolean;
  stopped?: boolean;
  awaitingAnchor?: boolean;
  selectingCandidateId?: string | null;
  anchorError?: string;
  onSelectAnchor?: (candidateId: string) => void;
}) {
  if (candidates.items.length === 0) {
    return (
      <section className="candidateEmpty" aria-live="polite">
        <span
          className={
            running || awaitingAnchor ? "scanPulse" : "scanPulse scanPulseDone"
          }
        />
        <div>
          <h2>
            {awaitingAnchor
              ? "Loading starting-profile choices…"
              : running
                ? "Waiting for the first catalog match…"
                : stopped
                  ? "Search stopped."
                  : "No candidates found."}
          </h2>
          <p>
            {awaitingAnchor
              ? "The scan found competing identity signals. The matching profiles are being prepared so you can choose the one you recognize."
              : running
                ? "Profiles will appear here as Maigret scan shards finish."
                : stopped
                  ? "Search stopped before any candidates were saved."
                  : "The completed catalog checks did not return a claimed account."}
          </p>
        </div>
      </section>
    );
  }

  if (awaitingAnchor) {
    const eligible = candidates.items.filter((candidate) => candidate.anchor_eligible);
    const anchorPool = eligible.length ? eligible : candidates.items;
    const choiceMap = new Map<string, AnchorChoice>();

    for (const candidate of anchorPool) {
      const key = candidate.display_name?.trim().toLocaleLowerCase() || candidate.candidate_id;
      const current = choiceMap.get(key);
      if (current) {
        current.candidates.push(candidate);
      } else {
        choiceMap.set(key, { candidate, candidates: [candidate] });
      }
    }

    const anchorChoices = Array.from(choiceMap.values());

    return (
      <section
        className="traceCheckpoint"
        aria-labelledby="anchor-checkpoint-title"
        aria-describedby="anchor-checkpoint-instructions"
        aria-busy={selectingCandidateId !== null}
      >
        <div className="traceCheckpointStatus">
          <strong>Paused</strong>
          <span>professional enrichment is waiting on this answer</span>
        </div>
        <div className="anchorCheckpoint">
          <span className="traceSrOnly">Choose the known starting profile</span>
          <div className="eyebrow">One quick checkpoint</div>
          <h1 id="anchor-checkpoint-title">
            The same handle carries two public names.
          </h1>
          <p id="anchor-checkpoint-instructions">
            Pick the one you recognize and the search will prioritize it. The other
            accounts stay in the brief either way — this does not merge them.
          </p>
          {anchorError ? (
            <p className="anchorError" role="alert">
              {anchorError}
            </p>
          ) : null}
        </div>

        <div className="traceCheckpointGrid">
          {anchorChoices.map(({ candidate, candidates: groupedCandidates }) => {
            const isSelecting = selectingCandidateId === candidate.candidate_id;
            const isSelected = candidate.selection_state === "included";
            const platforms = groupedCandidates
              .map((item) => item.platform)
              .join(" · ");

            return (
              <article className="traceCheckpointChoice" key={candidate.candidate_id}>
                <div className="traceCheckpointChoiceMeta">
                  <strong>{platforms}</strong>
                  <span>
                    {groupedCandidates.length} {groupedCandidates.length === 1 ? "account" : "accounts"}
                  </span>
                </div>
                <h2>{candidateTitle(candidate)}</h2>
                <ul className="traceEvidenceSignals">
                  <li data-signal="support">
                    Full name stated on {groupedCandidates.length === 1 ? "the profile" : "these profiles"}
                  </li>
                  <li data-signal="support">
                    Exact handle on {groupedCandidates.length} public {groupedCandidates.length === 1 ? "account" : "accounts"}
                  </li>
                  <li data-signal="limit">
                    Handle reuse alone does not establish one person
                  </li>
                </ul>
                <button
                  className="candidateAnchorButton"
                  type="button"
                  onClick={() => onSelectAnchor?.(candidate.candidate_id)}
                  disabled={
                    selectingCandidateId !== null ||
                    isSelected ||
                    !candidate.anchor_eligible ||
                    !onSelectAnchor
                  }
                  aria-label={`Use ${candidateTitle(candidate)} on ${platforms}, @${candidate.handle}, as the known starting profile`}
                >
                  {isSelected
                    ? "Starting profile selected"
                    : isSelecting
                      ? "Using this profile…"
                      : "Use as starting profile"}
                </button>
              </article>
            );
          })}
        </div>

        <div className="traceCheckpointFallback">
          <span>Recognize neither?</span>
          <p>The search continues with both names open if the selection window expires.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="traceFound" aria-live="polite">
      <div className="traceFoundHeading">
        <strong>Found so far</strong>
        <span>
          {candidates.items.length} {candidates.items.length === 1 ? "candidate" : "candidates"} · Handle reuse alone is only a lead
        </span>
      </div>

      <div className="traceFoundList">
        {candidates.items.map((candidate) => {
          const profileHref = safeProfileHref(candidate.profile_url);
          return (
            <article
              className={`traceFoundRow ${candidate.identity_tier === "weak" ? "traceFoundRowWeak" : ""}`}
              key={candidate.candidate_id}
            >
              <div className="traceFoundIdentity">
                <strong>{candidate.platform}</strong>
                <span>@{candidate.handle}</span>
              </div>
              <div className="traceFoundDescription">
                <strong>{candidateTitle(candidate)}</strong>
                <span>
                  {candidate.evidence.length
                    ? `${candidate.evidence.length} public ${candidate.evidence.length === 1 ? "signal" : "signals"}`
                    : "No additional profile detail"}
                </span>
              </div>
              {profileHref ? (
                <a
                  className="traceFoundLink"
                  href={profileHref}
                  rel="noopener noreferrer"
                  referrerPolicy="no-referrer"
                  target="_blank"
                >
                  {candidate.is_similar ? "Similar handle" : "Exact handle"} ↗
                </a>
              ) : (
                <span className="traceFoundLink traceFoundLinkUnavailable">Link unavailable</span>
              )}
            </article>
          );
        })}
      </div>

      {candidates.extracted_identifier_count > 0 ? (
        <p className="identifierNote">
          {candidates.extracted_identifier_count} additional identifier
          {candidates.extracted_identifier_count === 1 ? "" : "s"} extracted for
          later graph expansion.
        </p>
      ) : null}
    </section>
  );
}
