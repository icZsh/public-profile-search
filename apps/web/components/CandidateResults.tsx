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

function words(value: string): string {
  return value.replaceAll("_", " ").replaceAll(".", " ");
}

function candidateTitle(candidate: AccountCandidate): string {
  return candidate.display_name?.trim() || `@${candidate.handle}`;
}

export function CandidateResults({
  candidates,
  running,
  awaitingAnchor = false,
  selectingCandidateId = null,
  anchorError = "",
  onSelectAnchor,
}: {
  candidates: CandidateList;
  running: boolean;
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
                : "No candidates found."}
          </h2>
          <p>
            {awaitingAnchor
              ? "The scan found competing identity signals. The matching profiles are being prepared so you can choose the one you recognize."
              : running
              ? "Profiles will appear here as Maigret scan shards finish."
              : "The completed catalog checks did not return a claimed account."}
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="candidateSection" aria-live="polite">
      <div className="candidateSectionHeading">
        <div>
          <div className="eyebrow">Progressive account map</div>
          <h2>Possible profiles</h2>
        </div>
        <div className="candidateCount">
          <strong>{candidates.items.length}</strong>
          <span>{candidates.items.length === 1 ? "candidate" : "candidates"}</span>
        </div>
      </div>

      {awaitingAnchor ? (
        <section
          className="anchorCheckpoint"
          aria-labelledby="anchor-checkpoint-title"
          aria-describedby="anchor-checkpoint-instructions"
          aria-busy={selectingCandidateId !== null}
        >
          <div className="eyebrow">One quick checkpoint</div>
          <h3 id="anchor-checkpoint-title">
            Choose the known starting profile
          </h3>
          <p id="anchor-checkpoint-instructions">
            The same handle appears with more than one public name. Select the
            exact-handle profile you recognize, and discovery will use it to
            prioritize the rest of the search. This does not automatically merge
            the other accounts.
          </p>
          {anchorError ? (
            <p className="anchorError" role="alert">
              {anchorError}
            </p>
          ) : null}
        </section>
      ) : null}

      <p className="candidateCaution">
        These are accounts where the identifier appears to exist. Handle reuse alone
        does not show that the accounts belong to the same person.
      </p>

      <div className="candidateGrid">
        {candidates.items.map((candidate) => {
          const profileHref = safeProfileHref(candidate.profile_url);
          const canBeAnchor = Boolean(
            awaitingAnchor &&
              candidate.anchor_eligible &&
              onSelectAnchor,
          );
          const isSelecting = selectingCandidateId === candidate.candidate_id;
          const isSelected = candidate.selection_state === "included";
          return (
            <article
              className={[
                "candidateCard",
                canBeAnchor ? "candidateCardSelectable" : "",
                isSelected ? "candidateCardSelected" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              key={candidate.candidate_id}
            >
              <div className="candidateCardTop">
                <span className="candidatePlatform">{candidate.platform}</span>
                <span
                  className={`candidateTier candidateTier-${candidate.identity_tier}`}
                >
                  {candidate.identity_tier === "possible"
                    ? "Possible account"
                    : "Weak lead"}
                </span>
              </div>

              <h3>{candidateTitle(candidate)}</h3>
              {candidate.display_name ? (
                <p className="candidateHandle">@{candidate.handle}</p>
              ) : null}

              <div className="candidateSignals">
                <span>{words(candidate.relationship)}</span>
                {candidate.is_similar ? <span>Similar handle</span> : <span>Exact handle</span>}
                <span>{candidate.evidence.length} evidence record(s)</span>
              </div>

              {candidate.evidence.length ? (
                <details className="candidateEvidence">
                  <summary>Why this appeared</summary>
                  <ul>
                    {candidate.evidence.map((item) => (
                      <li key={item.site_check_id}>
                        <strong>{item.site_name}</strong>
                        <span>
                          {words(item.discovery_method)} · {words(item.status)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}

              {profileHref ? (
                <a
                  className="candidateLink"
                  href={profileHref}
                  rel="noopener noreferrer"
                  referrerPolicy="no-referrer"
                  target="_blank"
                >
                  Open public profile ↗
                </a>
              ) : (
                <span className="candidateLinkUnavailable">
                  Secure profile link unavailable
                </span>
              )}

              {canBeAnchor ? (
                <button
                  className="candidateAnchorButton"
                  type="button"
                  onClick={() => onSelectAnchor?.(candidate.candidate_id)}
                  disabled={selectingCandidateId !== null || isSelected}
                  aria-label={`Use ${candidate.display_name} on ${candidate.platform}, @${candidate.handle}, as the known starting profile`}
                >
                  {isSelected
                    ? "Starting profile selected"
                    : isSelecting
                      ? "Using this profile…"
                      : "Use as starting profile"}
                </button>
              ) : null}
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
