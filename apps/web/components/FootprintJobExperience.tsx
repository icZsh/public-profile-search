"use client";

import type {
  CandidateList,
  EvidenceItem,
  FootprintBrief as FootprintBriefType,
  FootprintDeepProgressPhase,
  FootprintJob,
  FootprintJobStatus,
} from "@public-profile-search/generated-api-client";
import Link from "next/link";
import { useEffect, useState } from "react";

import { CandidateResults } from "@/components/CandidateResults";
import { FootprintBrief } from "@/components/FootprintBrief";
import {
  ApiError,
  getFootprintBrief,
  getFootprintCandidates,
  getFootprintEvidence,
  getFootprintJob,
  selectFootprintAnchor,
} from "@/lib/api";

const terminalStatuses = new Set<FootprintJobStatus>([
  "ready",
  "ready_partial",
  "no_candidates",
  "failed",
  "cancelled",
]);
const reportStatuses = new Set<FootprintJobStatus>([
  "ready",
  "ready_partial",
  "no_candidates",
]);
const maxTransientRetries = 6;
const maxBriefWaits = 7;

const emptyCandidates: CandidateList = {
  items: [],
  extracted_identifier_count: 0,
};

type DeepProgressStepState = "pending" | "running" | "complete" | "stopped";

const deepProgressSteps = [
  { phase: "account_scan", label: "Account scan" },
  { phase: "professional_enrichment", label: "Professional enrichment" },
  { phase: "report_generation", label: "Deep report generation" },
  { phase: "finalizing", label: "Finalizing" },
] as const satisfies ReadonlyArray<{
  phase: Exclude<
    FootprintDeepProgressPhase,
    "queued" | "awaiting_anchor" | "complete"
  >;
  label: string;
}>;

const deepProgressPhaseIndex: Record<FootprintDeepProgressPhase, number> = {
  queued: -1,
  account_scan: 0,
  awaiting_anchor: 1,
  professional_enrichment: 1,
  report_generation: 2,
  finalizing: 3,
  complete: 4,
};

const deepProgressStatusLabels: Record<FootprintDeepProgressPhase, string> = {
  queued: "Queued",
  account_scan: "Scanning public accounts",
  awaiting_anchor: "Choose a starting profile",
  professional_enrichment: "Expanding professional evidence",
  report_generation: "Preparing Deep story",
  finalizing: "Finalizing Deep report",
  complete: "Deep report complete",
};

function deepProgressStepState(
  phase: FootprintDeepProgressPhase,
  stepIndex: number,
  stopped: boolean,
): DeepProgressStepState {
  if (phase === "complete") return "complete";
  const activeIndex = deepProgressPhaseIndex[phase];
  if (stepIndex < activeIndex) return "complete";
  if (stepIndex === activeIndex && phase !== "queued") {
    return stopped ? "stopped" : "running";
  }
  return "pending";
}

function formatElapsed(startValue: string, endTime: number): string {
  const startTime = new Date(startValue).valueOf();
  if (!Number.isFinite(startTime)) return "—";

  const totalSeconds = Math.max(0, Math.floor((endTime - startTime) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function parsedTime(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const parsed = new Date(value).valueOf();
  return Number.isFinite(parsed) ? parsed : fallback;
}

function deepProgressDescription(phase: FootprintDeepProgressPhase): string {
  switch (phase) {
    case "queued":
      return "Deep discovery is queued and will begin with a public account scan.";
    case "account_scan":
      return "Public accounts are being checked. Matching candidates appear below as scan shards complete.";
    case "awaiting_anchor":
      return "The handle produced competing public name signals. Choose the profile you recognize below so discovery can continue.";
    case "professional_enrichment":
      return "Account scanning is complete. Professional and biographical evidence is now being expanded.";
    case "report_generation":
      return "Professional evidence is ready. A source-grounded Deep story is now being composed.";
    case "finalizing":
      return "The Deep story has been assembled and its claims and evidence links are being finalized.";
    case "complete":
      return "Deep discovery is complete. The evidence-linked report is ready below.";
  }
}

function readableStatus(status: FootprintJobStatus): string {
  const labels: Record<FootprintJobStatus, string> = {
    queued: "Queued",
    discovering: "Scanning",
    ready: "Discovery complete",
    ready_partial: "Partial discovery complete",
    no_candidates: "No candidates",
    failed: "Discovery failed",
    cancelled: "Discovery cancelled",
  };
  return labels[status];
}

function formattedDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function requestError(reason: unknown): string {
  return reason instanceof Error
    ? reason.message
    : "Discovery progress could not be refreshed.";
}

function isTransientError(reason: unknown): boolean {
  if (!(reason instanceof ApiError)) return true;
  return reason.status === 408 || reason.status === 429 || reason.status >= 500;
}

function retryDelay(reason: unknown, attempt: number): number {
  if (reason instanceof ApiError && reason.retryAfter) {
    const seconds = Number(reason.retryAfter);
    if (Number.isFinite(seconds) && seconds >= 0) {
      return Math.min(10_000, Math.max(500, seconds * 1000));
    }
  }
  return Math.min(8_000, 850 * 2 ** attempt);
}

export function FootprintJobExperience({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<FootprintJob | null>(null);
  const [candidates, setCandidates] =
    useState<CandidateList>(emptyCandidates);
  const [brief, setBrief] = useState<FootprintBriefType | null>(null);
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [briefPending, setBriefPending] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [pollingStopped, setPollingStopped] = useState(false);
  const [error, setError] = useState("");
  const [selectingCandidateId, setSelectingCandidateId] = useState<
    string | null
  >(null);
  const [anchorError, setAnchorError] = useState("");
  const [pollGeneration, setPollGeneration] = useState(0);
  const [elapsedNow, setElapsedNow] = useState(() => Date.now());

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let transientRetries = 0;
    let briefWaits = 0;

    function schedule(delay: number) {
      if (active) timer = setTimeout(refresh, delay);
    }

    function stopOnNotFound(reason: ApiError) {
      if (!active) return;
      setRetrying(false);
      setPollingStopped(true);
      setBriefPending(false);
      setError(reason.message || "This footprint job is unavailable or was deleted.");
    }

    function stopReportOnNotFound() {
      if (!active) return;
      setRetrying(false);
      setBriefPending(false);
      setError(
        "Discovery results remain available, but the footprint report is unavailable.",
      );
    }

    function handleRefreshFailure(reason: unknown) {
      if (!active) return;
      if (reason instanceof ApiError && reason.status === 404) {
        stopOnNotFound(reason);
        return;
      }
      if (isTransientError(reason) && transientRetries < maxTransientRetries) {
        const delay = retryDelay(reason, transientRetries);
        transientRetries += 1;
        setRetrying(true);
        setPollingStopped(false);
        setError(requestError(reason));
        schedule(delay);
        return;
      }
      setRetrying(false);
      setPollingStopped(true);
      setError(requestError(reason));
    }

    async function refresh() {
      try {
        const current = await getFootprintJob(jobId);
        if (!active) return;
        setJob(current);
        setPollingStopped(false);

        const nextCandidates = await getFootprintCandidates(jobId);
        if (!active) return;
        setCandidates(nextCandidates);
        transientRetries = 0;
        setRetrying(false);
        setError("");

        const finished = terminalStatuses.has(current.status);
        if (!finished) {
          setBriefPending(false);
          schedule(850);
          return;
        }

        if (!reportStatuses.has(current.status)) {
          setBriefPending(false);
          return;
        }

        setBriefPending(true);
        try {
          const [nextBrief, nextEvidence] = await Promise.all([
            getFootprintBrief(jobId),
            getFootprintEvidence(jobId),
          ]);
          if (!active) return;
          setBrief(nextBrief);
          setEvidence(nextEvidence);
          setBriefPending(false);
          setRetrying(false);
          setError("");
        } catch (reason) {
          if (!active) return;
          if (reason instanceof ApiError && reason.status === 404) {
            stopReportOnNotFound();
            return;
          }
          if (reason instanceof ApiError && reason.status === 409) {
            if (briefWaits < maxBriefWaits) {
              const delay = retryDelay(reason, briefWaits);
              briefWaits += 1;
              setRetrying(true);
              setError("");
              schedule(delay);
            } else {
              setBriefPending(false);
              setRetrying(false);
              setError("Discovery finished, but the footprint brief is still unavailable.");
            }
            return;
          }
          handleRefreshFailure(reason);
        }
      } catch (reason) {
        handleRefreshFailure(reason);
      }
    }

    refresh();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, pollGeneration]);

  useEffect(() => {
    if (
      job?.search_mode !== "deep" ||
      job.deep_progress?.current_phase === "complete" ||
      job.status === "failed" ||
      job.status === "cancelled"
    ) {
      return;
    }

    const timer = window.setInterval(() => setElapsedNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [
    job?.deep_progress?.current_phase,
    job?.search_mode,
    job?.status,
  ]);

  async function chooseAnchor(candidateId: string) {
    if (selectingCandidateId) return;
    setSelectingCandidateId(candidateId);
    setAnchorError("");

    try {
      const response = await selectFootprintAnchor(jobId, candidateId);
      setJob(response.job);
      setPollingStopped(false);
      setPollGeneration((generation) => generation + 1);
      setCandidates((current) => ({
        ...current,
        items: current.items.map((candidate) => {
          if (candidate.candidate_id === response.selected_anchor.candidate_id) {
            return {
              ...candidate,
              selection_state: response.selected_anchor.selection_state,
            };
          }
          return candidate.selection_state === "included"
            ? { ...candidate, selection_state: "undecided" as const }
            : candidate;
        }),
      }));
    } catch (reason) {
      if (
        reason instanceof ApiError &&
        (reason.code === "anchor_selection_expired" ||
          reason.code === "anchor_selection_unavailable")
      ) {
        setJob((current) =>
          current?.exploration_status === "awaiting_anchor"
            ? { ...current, exploration_status: "running" }
            : current,
        );
        setAnchorError("");
        setPollingStopped(false);
        setPollGeneration((generation) => generation + 1);
        return;
      }
      setAnchorError(
        reason instanceof Error
          ? reason.message
          : "The starting profile could not be selected. Please try again.",
      );
    } finally {
      setSelectingCandidateId(null);
    }
  }

  const coverage = job?.coverage;
  const completed = coverage?.completed ?? 0;
  const selected = coverage?.selected ?? 0;
  const progress =
    selected > 0 ? Math.min(100, Math.round((completed / selected) * 100)) : 0;
  const deepMode = job?.search_mode === "deep";
  const deepProgressPhase: FootprintDeepProgressPhase | null = deepMode
    ? (job?.deep_progress?.current_phase ??
      (job?.exploration_status === "awaiting_anchor"
        ? "awaiting_anchor"
        : job?.status === "queued"
          ? "queued"
          : "account_scan"))
    : null;
  const awaitingAnchor =
    job?.exploration_status === "awaiting_anchor" ||
    deepProgressPhase === "awaiting_anchor";
  const running =
    !awaitingAnchor &&
    !pollingStopped && (!job || !terminalStatuses.has(job.status));
  const seedLabel = job
    ? job.seed.kind === "profile_url"
      ? job.seed.profile_url
      : `${job.seed.platform ? `${job.seed.platform} · ` : ""}@${job.seed.identifier}`
    : "Loading seed";
  const searchModeLabel = deepMode ? "Deep story" : "Quick evidence";
  const deepProgressStopped =
    deepMode && (job?.status === "failed" || job?.status === "cancelled");
  const deepProgressComplete = deepProgressPhase === "complete";
  const currentStatusLabel =
    job?.status === "failed" || job?.status === "cancelled"
      ? readableStatus(job.status)
      : awaitingAnchor
        ? "Choose a starting profile"
        : deepMode && deepProgressPhase && running
          ? deepProgressStatusLabels[deepProgressPhase]
          : job
        ? readableStatus(job.status)
        : pollingStopped
          ? "Unavailable"
          : "Connecting";
  const deepProgressEndTime = parsedTime(
    job?.deep_progress?.finished_at ?? undefined,
    elapsedNow,
  );
  const deepTotalElapsed = job
    ? formatElapsed(job.accepted_at, deepProgressEndTime)
    : "0:00";
  const deepStageElapsed = job
    ? formatElapsed(
        job.deep_progress?.phase_started_at ?? job.accepted_at,
        elapsedNow,
      )
    : "0:00";

  return (
    <main className="footprintShell">
      <nav className="topbar">
        <Link className="brand" href="/">
          tracebrief<span className="brandMark">/</span>
        </Link>
        <span className="prototypePill">Discovery {jobId.slice(0, 8)}</span>
      </nav>

      <header className="discoveryHeader">
        <div>
          <div className="eyebrow">Public account discovery</div>
          <h1>{seedLabel}</h1>
          <p>
            {job?.status === "failed"
              ? "Discovery stopped before the report could be completed. Any candidates already found remain available below."
              : job?.status === "cancelled"
                ? "Discovery was cancelled. Any candidates already found remain available below."
                : deepMode && deepProgressPhase
                  ? deepProgressDescription(deepProgressPhase)
                  : awaitingAnchor
                    ? "The handle produced competing public name signals. Choose the profile you recognize below so discovery can prioritize the next search."
                    : "Adaptive account and professional discovery is running within a bounded budget. Candidate accounts appear below as scan shards complete."}
          </p>
        </div>
        <div
          className={`discoveryStatus ${running ? "discoveryStatusRunning" : ""}`}
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          <span aria-hidden="true">
            {job?.status === "failed"
              ? "!"
              : job?.status === "cancelled"
                ? "×"
                : awaitingAnchor
                  ? "?"
                  : running
                    ? <i className="scanPulse" />
                    : "✓"}
          </span>
          {currentStatusLabel}
        </div>
      </header>

      {deepMode && deepProgressPhase ? (
        <section
          className={`deepProgressCard ${awaitingAnchor ? "deepProgressCardPaused" : ""}`}
          aria-label="Deep report progress"
        >
          <div className="deepProgressHeading">
            <div>
              <span>Deep workflow</span>
              <strong>{deepProgressStatusLabels[deepProgressPhase]}</strong>
            </div>
            <div className="deepProgressTiming">
              {deepProgressComplete ? (
                <>
                  <span className="deepProgressTimingComplete">
                    Status <strong>✓ Complete</strong>
                  </span>
                  <span>
                    Completed in <strong>{deepTotalElapsed}</strong>
                  </span>
                </>
              ) : (
                <span>
                  {deepProgressStopped ? "Stopped after" : "Elapsed"}{" "}
                  <strong>{deepTotalElapsed}</strong>
                </span>
              )}
              {!deepProgressComplete && !deepProgressStopped ? (
                <span>
                  {deepProgressPhase === "queued" ? "Queued" : "Current stage"}{" "}
                  <strong>{deepStageElapsed}</strong>
                </span>
              ) : null}
            </div>
          </div>

          {awaitingAnchor ? (
            <p className="deepProgressPauseNotice">
              <strong>Progress paused</strong>
              Choose a starting profile below to continue professional enrichment.
            </p>
          ) : null}

          <ol className="deepProgressSteps">
            {deepProgressSteps.map((step, index) => {
              const state = deepProgressStepState(
                deepProgressPhase,
                index,
                deepProgressStopped,
              );
              const paused = awaitingAnchor && index === 1;
              const statusLabel = paused
                ? "Waiting for selection"
                : state === "complete"
                  ? "Complete"
                  : state === "running"
                    ? "In progress"
                    : state === "stopped"
                      ? job?.status === "failed"
                        ? "Stopped after failure"
                        : "Cancelled"
                      : "Upcoming";

              return (
                <li
                  className={`deepProgressStep deepProgressStep-${state} ${paused ? "deepProgressStep-paused" : ""}`}
                  key={step.phase}
                  aria-current={state === "running" ? "step" : undefined}
                >
                  <div className="deepProgressStepTopline">
                    <span className="deepProgressStepNumber" aria-hidden="true">
                      {state === "complete" ? "✓" : index + 1}
                    </span>
                    <span className="deepProgressStepStatus">{statusLabel}</span>
                  </div>
                  <strong>{step.label}</strong>
                  {index === 0 ? (
                    <small>
                      {completed} / {selected || "—"} sites checked
                    </small>
                  ) : (
                    <small>
                      {state === "running"
                        ? `Stage elapsed ${deepStageElapsed}`
                        : "Evidence-grounded workflow"}
                    </small>
                  )}
                  <span className="deepProgressStepTrack" aria-hidden="true" />
                </li>
              );
            })}
          </ol>

          {job ? (
            <div className="catalogMeta">
              <span>{searchModeLabel} mode</span>
              <span>Started {formattedDate(job.accepted_at)}</span>
              {deepProgressComplete && job.deep_progress?.finished_at ? (
                <span>
                  Completed {formattedDate(job.deep_progress.finished_at)}
                </span>
              ) : (
                <span>
                  Current phase {deepProgressPhase.replaceAll("_", " ")}
                </span>
              )}
              <span>Retrieval cutoff {formattedDate(job.deadline_at)}</span>
            </div>
          ) : null}
        </section>
      ) : (
      <section className="coverageCard" aria-label="Catalog scan coverage">
        <div className="coverageHeading">
          <div>
            <span>Catalog coverage</span>
            <strong>
              {completed} / {selected || "—"} sites checked
            </strong>
          </div>
          <span>{progress}%</span>
        </div>
        <div
          className="coverageTrack"
          role="progressbar"
          aria-label="Sites checked"
          aria-valuemin={0}
          aria-valuemax={selected || 100}
          aria-valuenow={completed}
        >
          <span style={{ width: `${progress}%` }} />
        </div>
        <dl className="coverageStats">
          <div>
            <dt>Claimed</dt>
            <dd>{coverage?.claimed ?? 0}</dd>
          </div>
          <div>
            <dt>Available</dt>
            <dd>{coverage?.available ?? 0}</dd>
          </div>
          <div>
            <dt>Unknown</dt>
            <dd>{coverage?.unknown ?? 0}</dd>
          </div>
          <div>
            <dt>Invalid</dt>
            <dd>{coverage?.illegal ?? 0}</dd>
          </div>
        </dl>
        {job ? (
          <div className="catalogMeta">
            <span>
              {job.catalog.engine}
              {job.catalog.package_version
                ? ` ${job.catalog.package_version}`
                : ""}
            </span>
            <span>{searchModeLabel} mode</span>
            <span>Adaptive discovery catalog</span>
            <span>Retrieval cutoff {formattedDate(job.deadline_at)}</span>
          </div>
        ) : null}
      </section>
      )}

      {error ? (
        <p className="refreshNotice" role={retrying ? "status" : "alert"}>
          {error}
          {retrying ? " Retrying automatically." : ""}
        </p>
      ) : null}

      {job?.status === "ready_partial" ? (
        <p className="partialNotice">
          Some sites could not be checked. The candidates below come only from
          completed checks.
        </p>
      ) : null}
      {job?.status === "failed" ? (
        <p className="formError">
          The scan could not finish. Any candidates already shown remain inspectable.
        </p>
      ) : null}

      {briefPending && !brief ? (
        <p className="briefPendingNotice" role="status">
          {deepMode
            ? "The Deep story is complete. Loading its evidence-linked report…"
            : "Discovery is complete. Preparing the evidence-linked footprint brief…"}
        </p>
      ) : null}

      {brief ? <FootprintBrief brief={brief} evidence={evidence} /> : null}

      {!brief && (job || !pollingStopped) ? (
        <CandidateResults
          candidates={candidates}
          running={running}
          awaitingAnchor={awaitingAnchor}
          selectingCandidateId={selectingCandidateId}
          anchorError={anchorError}
          onSelectAnchor={chooseAnchor}
        />
      ) : null}

      <div className="footprintActions">
        <Link className="textLink" href="/">
          ← Search another identifier
        </Link>
      </div>
    </main>
  );
}
