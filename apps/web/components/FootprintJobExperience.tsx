"use client";

import type {
  CandidateList,
  EvidenceItem,
  FootprintBrief as FootprintBriefType,
  FootprintDeepProgressPhase,
  FootprintJob,
  FootprintJobStatus,
  FootprintSynthesisModel,
} from "@public-profile-search/generated-api-client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { CandidateResults } from "@/components/CandidateResults";
import { FootprintBrief } from "@/components/FootprintBrief";
import {
  ApiError,
  cancelFootprintJob,
  createFootprintJob,
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

function discoveryPhaseTitle(
  phase: FootprintDeepProgressPhase | null,
  deepMode: boolean,
): string {
  if (!deepMode) return "Checking the public record";
  switch (phase) {
    case "queued":
      return "Preparing the public scan";
    case "account_scan":
      return "Scanning public accounts";
    case "professional_enrichment":
      return "Expanding professional evidence";
    case "report_generation":
      return "Writing the evidence-backed story";
    case "finalizing":
      return "Checking every citation";
    case "complete":
      return "The brief is ready";
    case "awaiting_anchor":
      return "Waiting on one identity choice";
    default:
      return "Building the brief";
  }
}

function visibleProgressLabel(index: number, deepMode: boolean): string {
  if (!deepMode) {
    return ["Account scan", "People search and cited answers"][index];
  }
  return [
    "Account scan",
    "Professional enrichment",
    "Writing the story",
    "Checking every citation",
  ][index];
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
  const router = useRouter();
  const [job, setJob] = useState<FootprintJob | null>(null);
  const [candidates, setCandidates] =
    useState<CandidateList>(emptyCandidates);
  const [brief, setBrief] = useState<FootprintBriefType | null>(null);
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [briefPending, setBriefPending] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [pollingStopped, setPollingStopped] = useState(false);
  const [error, setError] = useState("");
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState("");
  const [selectingCandidateId, setSelectingCandidateId] = useState<
    string | null
  >(null);
  const [anchorError, setAnchorError] = useState("");
  const [pollGeneration, setPollGeneration] = useState(0);
  const [elapsedNow, setElapsedNow] = useState(() => Date.now());
  const [upgrading, setUpgrading] = useState(false);

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
        if (terminalStatuses.has(current.status)) setStopError("");
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
    if (selectingCandidateId || stopping) return;
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

  async function stopSearch() {
    if (!job || stopping || terminalStatuses.has(job.status)) return;
    setStopping(true);
    setStopError("");

    try {
      const stoppedJob = await cancelFootprintJob(jobId);
      setJob(stoppedJob);
      setPollingStopped(false);
      setPollGeneration((generation) => generation + 1);
    } catch (reason) {
      setStopError(
        reason instanceof Error
          ? reason.message
          : "The search could not be stopped. Please try again.",
      );
      setPollingStopped(false);
      setPollGeneration((generation) => generation + 1);
    } finally {
      setStopping(false);
    }
  }

  async function startDeepRun(model: FootprintSynthesisModel) {
    if (!job || upgrading) return;
    setUpgrading(true);
    setError("");

    try {
      const nextJob = await createFootprintJob(
        {
          seed: job.seed,
          search_mode: "deep",
          synthesis_model: model,
          locale: "en-US",
        },
        crypto.randomUUID(),
      );
      router.push(`/footprint/${nextJob.job_id}`);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The Deep brief could not be started. Please try again.",
      );
      setUpgrading(false);
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
  const terminal = Boolean(job && terminalStatuses.has(job.status));
  const awaitingAnchor =
    !terminal &&
    (job?.exploration_status === "awaiting_anchor" ||
      deepProgressPhase === "awaiting_anchor");
  const running =
    !awaitingAnchor &&
    !pollingStopped && (!job || !terminal);
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
  const progressPhase = deepProgressPhase ?? (terminal ? "complete" : "account_scan");
  const liveSourceCount = candidates.items.reduce(
    (total, candidate) => total + Math.max(1, candidate.evidence.length),
    0,
  );
  const stepsToRender = deepMode ? deepProgressSteps : deepProgressSteps.slice(0, 2);

  return (
    <main className="traceApp traceJob">
      <nav className={`traceTopbar ${brief ? "traceTopbarBrief" : ""}`}>
        <div className="traceTopbarIdentity">
          <Link className="traceBrand" href="/">
            tracebrief<span className="brandMark">/</span>
          </Link>
          <span>
            {seedLabel}
            {job ? ` · ${deepMode ? "deep" : "quick"}` : ""}
            {awaitingAnchor ? " · paused" : ""}
            {brief ? ` · ${evidence.length} sources` : ""}
          </span>
        </div>

        <div className="traceTopbarActions">
          <details className="traceOperatorDisclosure">
            <summary>Operator view</summary>
            <div>
              <strong>Discovery {jobId.slice(0, 8)}</strong>
              <span>{job ? `${job.catalog.engine} ${job.catalog.package_version ?? ""}` : "Connecting"}</span>
              <span>{searchModeLabel} mode · Adaptive discovery catalog</span>
              {job ? <span>Started {formattedDate(job.accepted_at)}</span> : null}
              {job ? <span>Retrieval cutoff {formattedDate(job.deadline_at)}</span> : null}
              {deepProgressComplete && job?.deep_progress?.finished_at ? (
                <>
                  <span>Status <strong>✓ Complete</strong></span>
                  <span>Completed in <strong>{deepTotalElapsed}</strong></span>
                  <span>Completed {formattedDate(job.deep_progress.finished_at)}</span>
                </>
              ) : (
                <span>Current stage <strong>{deepStageElapsed}</strong></span>
              )}
            </div>
          </details>

          {brief ? (
            <>
              <Link className="traceSecondaryButton" href="/">
                Re-run
              </Link>
              <button
                className="tracePrimaryButton traceTopbarPrimary"
                type="button"
                onClick={() => window.print()}
              >
                Export
              </button>
            </>
          ) : null}

          {job && !terminal ? (
            <button
              className="stopSearchButton"
              type="button"
              onClick={stopSearch}
              disabled={stopping || selectingCandidateId !== null}
              aria-busy={stopping}
            >
              {stopping ? "Stopping…" : "Stop search"}
            </button>
          ) : null}
        </div>
      </nav>

      <div
        className="traceSrOnly"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {currentStatusLabel}
      </div>

      {stopError ? (
        <p className="stopSearchError traceInlineError" role="alert">
          {stopError}
        </p>
      ) : null}

      {error ? (
        <p className="refreshNotice traceInlineError" role={retrying ? "status" : "alert"}>
          {error}
          {retrying ? " Retrying automatically." : ""}
        </p>
      ) : null}

      {job?.status === "ready_partial" ? (
        <p className="partialNotice traceInlineNotice">
          Some sites could not be checked. The report uses only completed checks.
        </p>
      ) : null}

      {briefPending && !brief ? (
        <p className="briefPendingNotice traceInlineNotice" role="status">
          {deepMode
            ? "The Deep story is complete. Loading its evidence-linked report…"
            : "Discovery is complete. Preparing the evidence-linked footprint brief…"}
        </p>
      ) : null}

      {brief ? (
        <>
          <FootprintBrief
            brief={brief}
            evidence={evidence}
            coverage={coverage}
            seedLabel={seedLabel}
            searchMode={job?.search_mode}
            onRunDeep={deepMode ? undefined : startDeepRun}
            upgrading={upgrading}
          />
          <footer className="traceJobFooter">
            <div>
              <strong>Finished with this brief?</strong>
              <span>Begin a separate search with another public identifier.</span>
            </div>
            <Link className="tracePrimaryButton" href="/">
              Start another search
            </Link>
          </footer>
        </>
      ) : null}

      {!brief && (job || !pollingStopped) ? (
        awaitingAnchor ? (
          <section className="traceCheckpointPage">
            <p className="traceSrOnly">
              <strong>Progress paused</strong> Choose a starting profile to continue.
            </p>
            <CandidateResults
              candidates={candidates}
              running={running}
              stopped={job?.status === "cancelled"}
              awaitingAnchor={awaitingAnchor}
              selectingCandidateId={stopping ? "search-stopping" : selectingCandidateId}
              anchorError={anchorError}
              onSelectAnchor={chooseAnchor}
            />
          </section>
        ) : (
          <section className="traceRunningPage">
            <div className="traceRunningGrid">
              <div className="traceRunningMain">
                <header className="traceRunningHeader">
                  <div className="traceRunningStatus">
                    <i className={running ? "scanPulse" : "scanPulse scanPulseDone"} />
                    <span>
                      {deepProgressStopped && job
                        ? readableStatus(job.status)
                        : running
                          ? "Building the brief"
                          : currentStatusLabel}
                    </span>
                  </div>
                  <h1>{discoveryPhaseTitle(deepProgressPhase, deepMode)}</h1>
                  <div className="traceRunningIntro">
                    <p>
                      {job?.status === "failed"
                        ? "Discovery stopped before the report could be completed. Candidates already found remain below."
                        : job?.status === "cancelled"
                          ? "Discovery was cancelled. Candidates already found remain below."
                          : deepMode && deepProgressPhase
                            ? deepProgressDescription(deepProgressPhase)
                            : "Public accounts are being checked, followed by a bounded people search and cited answers."}
                    </p>
                    <div className="traceTimer" aria-label={`Elapsed ${deepTotalElapsed}`}>
                      <strong>{deepTotalElapsed}</strong>
                      <span>Elapsed · stage {deepStageElapsed}</span>
                    </div>
                  </div>
                </header>

                <ol className="traceProgressList deepProgressSteps" aria-label="Brief progress">
                  {stepsToRender.map((step, index) => {
                    const state = deepProgressStepState(
                      progressPhase,
                      index,
                      Boolean(deepProgressStopped),
                    );
                    const paused = awaitingAnchor && index === 1;
                    const stepProgress =
                      state === "complete"
                        ? 100
                        : state === "running" && index === 0 && selected > 0
                          ? progress
                          : null;
                    const stepStatusLabel =
                      state === "complete"
                        ? "Complete"
                        : state === "running"
                          ? "Running"
                          : state === "stopped"
                            ? "Stopped"
                            : "Waiting";
                    return (
                      <li
                        className={`traceProgressStep deepProgressStep-${state} ${paused ? "deepProgressStep-paused" : ""}`}
                        key={step.phase}
                        aria-current={state === "running" ? "step" : undefined}
                      >
                        <div>
                          <strong>{visibleProgressLabel(index, deepMode)}</strong>
                          <small>
                            {index === 0
                              ? `${completed} of ${selected || "—"} sites checked · ${candidates.items.length} candidates kept`
                              : state === "running"
                                ? `Stage elapsed ${deepStageElapsed}`
                            : "Written only from retrieved public sources"}
                          </small>
                        </div>
                        <span
                          className={`traceStepStatusRing traceStepStatusRing-${state}`}
                          aria-hidden="true"
                        >
                          <svg
                            className="traceStepProgressRing"
                            viewBox="0 0 28 28"
                            focusable="false"
                          >
                            <circle
                              className="traceStepProgressRingTrack"
                              cx="14"
                              cy="14"
                              r="12"
                              pathLength="100"
                            />
                            {state === "running" || state === "complete" ? (
                              <circle
                                className={`traceStepProgressRingValue ${state === "running" && stepProgress === null ? "traceStepProgressRingIndeterminate" : ""}`}
                                cx="14"
                                cy="14"
                                r="12"
                                pathLength="100"
                                style={
                                  stepProgress === null
                                    ? undefined
                                    : { strokeDashoffset: 100 - stepProgress }
                                }
                              />
                            ) : null}
                          </svg>
                          {state === "complete" ? (
                            <svg
                              className="traceStepCompleteCheck"
                              viewBox="0 0 20 20"
                              focusable="false"
                            >
                              <path d="M4.5 10.5 8.25 14.25 15.75 6.75" />
                            </svg>
                          ) : null}
                        </span>
                        <span className="traceSrOnly">{stepStatusLabel}</span>
                      </li>
                    );
                  })}
                </ol>

                <CandidateResults
                  candidates={candidates}
                  running={running}
                  stopped={job?.status === "cancelled"}
                  awaitingAnchor={false}
                  selectingCandidateId={stopping ? "search-stopping" : selectingCandidateId}
                  anchorError={anchorError}
                  onSelectAnchor={chooseAnchor}
                />
              </div>

              <aside className="traceLiveSidebar" aria-label="Discovery coverage">
                <section>
                  <div className="traceSidebarHeading">Public signals collected</div>
                  <div className="traceSidebarCount">
                    <strong>{liveSourceCount}</strong>
                    <span>so far</span>
                  </div>
                  <div className="traceLiveSources">
                    {candidates.items.slice(0, 6).map((candidate, index) => (
                      <div key={candidate.candidate_id}>
                        <span>{index + 1}</span>
                        <strong>{candidate.platform} profile</strong>
                        <small>{candidate.is_similar ? "similar" : "exact"}</small>
                      </div>
                    ))}
                    {!candidates.items.length ? (
                      <p>Candidate sources will appear as catalog checks finish.</p>
                    ) : null}
                  </div>
                </section>

                <section className="traceCoveragePanel">
                  <div className="traceSidebarHeading">Coverage</div>
                  <div
                    className="traceCoverageTrack"
                    role="progressbar"
                    aria-label="Sites checked"
                    aria-valuemin={0}
                    aria-valuemax={selected || 100}
                    aria-valuenow={completed}
                  >
                    <span style={{ width: `${progress}%` }} />
                  </div>
                  <dl>
                    <div><dd>{coverage?.claimed ?? 0}</dd><dt>Claimed</dt></div>
                    <div><dd>{coverage?.available ?? 0}</dd><dt>Available</dt></div>
                    <div><dd>{coverage?.unknown ?? 0}</dd><dt>Unknown</dt></div>
                    <div><dd>{coverage?.illegal ?? 0}</dd><dt>Invalid</dt></div>
                  </dl>
                  <p>
                    Unknown and invalid checks stay outside the brief unless later
                    public evidence resolves them.
                  </p>
                </section>
              </aside>
            </div>
          </section>
        )
      ) : null}

    </main>
  );
}
