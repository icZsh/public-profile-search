"use client";

import type {
  FootprintHistoryGroup,
  FootprintHistoryRun,
} from "@public-profile-search/generated-api-client";
import { ClockCounterClockwiseIcon } from "@phosphor-icons/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  clearFootprintHistory,
  createIdempotencyKey,
  deleteFootprintJob,
  getFootprintHistory,
  getFootprintHistoryRuns,
  refreshFootprintJob,
} from "@/lib/api";

const historyPageSize = 10;
const runPageSize = 10;
const terminalStatuses = new Set([
  "ready",
  "ready_partial",
  "no_candidates",
  "failed",
  "cancelled",
]);

interface GroupRunsState {
  items: FootprintHistoryRun[];
  nextCursor: string | null;
  loading: boolean;
  error: string;
}

type DrawerMode = "closed" | "peek" | "modal";

function messageFrom(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function isAbortError(reason: unknown): boolean {
  return (
    typeof reason === "object" &&
    reason !== null &&
    "name" in reason &&
    reason.name === "AbortError"
  );
}

function formattedDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function readableStatus(status: string): string {
  return status.replaceAll("_", " ");
}

function seedLabel(group: FootprintHistoryGroup): string {
  const { seed } = group;
  return seed.platform
    ? `${seed.platform} · @${seed.identifier}`
    : `@${seed.identifier}`;
}

function modelLabel(run: FootprintHistoryRun): string {
  if (run.search_mode !== "deep") return "Quick";
  if (!run.synthesis_model) return "Deep · default model";
  return `Deep · ${run.synthesis_model.split("/").at(-1)}`;
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => element.getAttribute("aria-hidden") !== "true");
}

export function FootprintHistoryDrawer() {
  const router = useRouter();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const hoverOpenTimerRef = useRef<number | null>(null);
  const hoverCloseTimerRef = useRef<number | null>(null);
  const restoreFocusFrameRef = useRef<number | null>(null);
  const drawerModeRef = useRef<DrawerMode>("closed");
  const focusSearchOnOpenRef = useRef(false);
  const refreshAttemptRef = useRef<{
    jobId: string;
    idempotencyKey: string;
  } | null>(null);
  const [drawerMode, setDrawerMode] = useState<DrawerMode>("closed");
  const open = drawerMode !== "closed";
  const [query, setQuery] = useState("");
  const [groups, setGroups] = useState<FootprintHistoryGroup[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    () => new Set(),
  );
  const [runsByGroup, setRunsByGroup] = useState<
    Record<string, GroupRunsState>
  >({});
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const [notice, setNotice] = useState("");
  const [reloadVersion, setReloadVersion] = useState(0);

  const cancelHoverOpen = useCallback(() => {
    if (hoverOpenTimerRef.current === null) return;
    window.clearTimeout(hoverOpenTimerRef.current);
    hoverOpenTimerRef.current = null;
  }, []);

  const cancelHoverClose = useCallback(() => {
    if (hoverCloseTimerRef.current === null) return;
    window.clearTimeout(hoverCloseTimerRef.current);
    hoverCloseTimerRef.current = null;
  }, []);

  const cancelFocusRestore = useCallback(() => {
    if (restoreFocusFrameRef.current === null) return;
    window.cancelAnimationFrame(restoreFocusFrameRef.current);
    restoreFocusFrameRef.current = null;
  }, []);

  const closeDrawer = useCallback(() => {
    cancelHoverOpen();
    cancelHoverClose();
    cancelFocusRestore();
    const shouldRestoreFocus = drawerModeRef.current === "modal";
    drawerModeRef.current = "closed";
    focusSearchOnOpenRef.current = false;
    setDrawerMode("closed");
    if (shouldRestoreFocus) {
      restoreFocusFrameRef.current = window.requestAnimationFrame(() => {
        restoreFocusFrameRef.current = null;
        if (drawerModeRef.current === "closed") {
          (restoreFocusRef.current ?? triggerRef.current)?.focus();
        }
      });
    }
  }, [cancelFocusRestore, cancelHoverClose, cancelHoverOpen]);

  function openModal() {
    cancelHoverOpen();
    cancelHoverClose();
    cancelFocusRestore();
    restoreFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : triggerRef.current;
    focusSearchOnOpenRef.current = true;
    drawerModeRef.current = "modal";
    setNotice("");
    setDrawerMode("modal");
  }

  function promotePeek() {
    if (drawerModeRef.current !== "peek") return;
    cancelHoverClose();
    cancelFocusRestore();
    focusSearchOnOpenRef.current = false;
    drawerModeRef.current = "modal";
    setDrawerMode("modal");
  }

  function scheduleHoverOpen(pointerType: string) {
    if (
      pointerType !== "mouse" ||
      drawerModeRef.current !== "closed" ||
      hoverOpenTimerRef.current !== null
    ) {
      return;
    }
    hoverOpenTimerRef.current = window.setTimeout(() => {
      hoverOpenTimerRef.current = null;
      restoreFocusRef.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : triggerRef.current;
      focusSearchOnOpenRef.current = false;
      drawerModeRef.current = "peek";
      setNotice("");
      setDrawerMode("peek");
    }, 160);
  }

  function scheduleHoverClose(pointerType: string) {
    cancelHoverOpen();
    if (
      pointerType !== "mouse" ||
      drawerModeRef.current !== "peek" ||
      hoverCloseTimerRef.current !== null
    ) {
      return;
    }
    hoverCloseTimerRef.current = window.setTimeout(() => {
      hoverCloseTimerRef.current = null;
      if (drawerModeRef.current === "peek") closeDrawer();
    }, 220);
  }

  useEffect(
    () => () => {
      cancelHoverOpen();
      cancelHoverClose();
      cancelFocusRestore();
    },
    [cancelFocusRestore, cancelHoverClose, cancelHoverOpen],
  );

  useEffect(() => {
    if (!open) return;

    const focusTimer = drawerMode === "modal" && focusSearchOnOpenRef.current
      ? window.setTimeout(() => searchInputRef.current?.focus(), 0)
      : null;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        if (drawerMode === "modal") event.preventDefault();
        closeDrawer();
        return;
      }
      if (
        drawerMode !== "modal" ||
        event.key !== "Tab" ||
        !drawerRef.current
      ) return;

      const focusable = focusableElements(drawerRef.current);
      if (focusable.length === 0) {
        event.preventDefault();
        drawerRef.current.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!drawerRef.current.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      if (focusTimer !== null) window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [closeDrawer, drawerMode, open]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);
    setLoadError("");
    const timer = window.setTimeout(async () => {
      try {
        const page = await getFootprintHistory({
          q: query.trim() || undefined,
          limit: historyPageSize,
          signal: controller.signal,
        });
        setGroups(page.items);
        setNextCursor(page.next_cursor);
      } catch (reason) {
        if (!isAbortError(reason)) {
          setGroups([]);
          setNextCursor(null);
          setLoadError(
            messageFrom(reason, "Search history could not be loaded."),
          );
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 220);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [open, query, reloadVersion]);

  async function loadMoreGroups() {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setLoadError("");
    try {
      const page = await getFootprintHistory({
        q: query.trim() || undefined,
        cursor: nextCursor,
        limit: historyPageSize,
      });
      setGroups((current) => [...current, ...page.items]);
      setNextCursor(page.next_cursor);
    } catch (reason) {
      setLoadError(messageFrom(reason, "More search history could not be loaded."));
    } finally {
      setLoadingMore(false);
    }
  }

  async function loadRuns(
    groupId: string,
    cursor?: string,
    append = false,
  ) {
    setRunsByGroup((current) => ({
      ...current,
      [groupId]: {
        items: append ? (current[groupId]?.items ?? []) : [],
        nextCursor: append ? (current[groupId]?.nextCursor ?? null) : null,
        loading: true,
        error: "",
      },
    }));
    try {
      const page = await getFootprintHistoryRuns(groupId, {
        cursor,
        limit: runPageSize,
      });
      setRunsByGroup((current) => ({
        ...current,
        [groupId]: {
          items: append
            ? [...(current[groupId]?.items ?? []), ...page.items]
            : page.items,
          nextCursor: page.next_cursor,
          loading: false,
          error: "",
        },
      }));
    } catch (reason) {
      setRunsByGroup((current) => ({
        ...current,
        [groupId]: {
          items: current[groupId]?.items ?? [],
          nextCursor: current[groupId]?.nextCursor ?? null,
          loading: false,
          error: messageFrom(reason, "Runs for this handle could not be loaded."),
        },
      }));
    }
  }

  function toggleGroup(groupId: string) {
    const opening = !expandedGroups.has(groupId);
    setExpandedGroups((current) => {
      const next = new Set(current);
      if (opening) next.add(groupId);
      else next.delete(groupId);
      return next;
    });
    if (opening && !runsByGroup[groupId]) void loadRuns(groupId);
  }

  async function refreshRun(run: FootprintHistoryRun) {
    if (refreshingId) return;
    setRefreshingId(run.job_id);
    setNotice("Starting a fresh search with the saved settings…");
    if (refreshAttemptRef.current?.jobId !== run.job_id) {
      refreshAttemptRef.current = {
        jobId: run.job_id,
        idempotencyKey: createIdempotencyKey(),
      };
    }
    try {
      const job = await refreshFootprintJob(
        run.job_id,
        refreshAttemptRef.current.idempotencyKey,
      );
      refreshAttemptRef.current = null;
      closeDrawer();
      router.push(`/footprint/${job.job_id}`);
    } catch (reason) {
      setNotice(messageFrom(reason, "The fresh search could not be started."));
      setRefreshingId(null);
    }
  }

  async function deleteRun(run: FootprintHistoryRun) {
    if (!terminalStatuses.has(run.status) || deletingId) return;
    const confirmed = window.confirm(
      "Permanently delete this completed search? Its saved result cannot be recovered.",
    );
    if (!confirmed) return;

    setDeletingId(run.job_id);
    setNotice("");
    try {
      await deleteFootprintJob(run.job_id);
      setNotice("The saved search was permanently deleted.");
      setRunsByGroup({});
      setReloadVersion((version) => version + 1);
    } catch (reason) {
      setNotice(messageFrom(reason, "The saved search could not be deleted."));
    } finally {
      setDeletingId(null);
    }
  }

  async function clearAll() {
    if (clearing) return;
    const confirmed = window.confirm(
      "Permanently delete all completed search history? This cannot be undone. Running searches will remain.",
    );
    if (!confirmed) return;

    setClearing(true);
    setNotice("Deleting completed search history…");
    let deletedCount = 0;
    try {
      for (let batch = 0; batch < 100; batch += 1) {
        const result = await clearFootprintHistory(50);
        deletedCount += result.deleted_count;
        if (!result.has_more) break;
        if (batch === 99 || result.deleted_count === 0) {
          throw new Error("Some completed searches could not be cleared.");
        }
      }
      setNotice(
        deletedCount === 1
          ? "1 completed search was permanently deleted. Running searches remain."
          : `${deletedCount} completed searches were permanently deleted. Running searches remain.`,
      );
      setRunsByGroup({});
      setExpandedGroups(new Set());
      setReloadVersion((version) => version + 1);
    } catch (reason) {
      setNotice(
        `${messageFrom(reason, "History could not be fully cleared.")} ${deletedCount} deleted so far.`,
      );
    } finally {
      setClearing(false);
    }
  }

  return (
    <>
      <button
        className="traceHistoryTrigger"
        type="button"
        ref={triggerRef}
        onClick={openModal}
        onPointerEnter={(event) => scheduleHoverOpen(event.pointerType)}
        onPointerLeave={(event) => scheduleHoverClose(event.pointerType)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls="footprint-history-drawer"
      >
        <ClockCounterClockwiseIcon
          className="traceHistoryTriggerIcon"
          aria-hidden="true"
          size={16}
          weight="regular"
        />
        History
      </button>

      {open ? (
        <div
          className={`traceHistoryLayer traceHistoryLayer-${drawerMode}`}
          onMouseDown={(event) => {
            if (
              drawerMode === "modal" &&
              event.target === event.currentTarget
            ) closeDrawer();
          }}
        >
          <aside
            className="traceHistoryDrawer"
            id="footprint-history-drawer"
            ref={drawerRef}
            onPointerEnter={(event) => {
              if (event.pointerType === "mouse") cancelHoverClose();
            }}
            onPointerLeave={(event) => scheduleHoverClose(event.pointerType)}
            onPointerDownCapture={promotePeek}
            onFocusCapture={promotePeek}
            role="dialog"
            aria-modal={drawerMode === "modal" ? "true" : undefined}
            aria-labelledby="footprint-history-title"
            tabIndex={-1}
          >
            <header className="traceHistoryHeader">
              <div>
                <span>Private · saved for 30 days</span>
                <h2 id="footprint-history-title">History</h2>
              </div>
              <button
                className="traceHistoryClose"
                type="button"
                onClick={closeDrawer}
                aria-label="Close search history"
              >
                Close
              </button>
            </header>

            <div className="traceHistorySearch">
              <label htmlFor="history-query">Find a past handle</label>
              <input
                id="history-query"
                ref={searchInputRef}
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search handles"
                autoComplete="off"
                spellCheck={false}
              />
            </div>

            <div className="traceHistoryToolbar">
              <span>{query.trim() ? "Matching searches" : "Recent searches"}</span>
              <button type="button" onClick={clearAll} disabled={clearing}>
                {clearing ? "Clearing…" : "Clear all"}
              </button>
            </div>

            <p className="traceHistoryNotice" role="status" aria-live="polite">
              {notice}
            </p>

            <div className="traceHistoryContent">
              {loading ? (
                <p className="traceHistoryState" role="status">
                  Loading search history…
                </p>
              ) : loadError && groups.length === 0 ? (
                <div className="traceHistoryState" role="alert">
                  <p>{loadError}</p>
                  <button
                    type="button"
                    onClick={() => setReloadVersion((version) => version + 1)}
                  >
                    Try again
                  </button>
                </div>
              ) : groups.length === 0 ? (
                <div className="traceHistoryState">
                  <strong>{query.trim() ? "No matching searches" : "No search history yet"}</strong>
                  <p>
                    {query.trim()
                      ? "Try another handle or platform."
                      : "Completed and running searches will appear here."}
                  </p>
                </div>
              ) : (
                <ul className="traceHistoryGroups">
                  {groups.map((group) => {
                    const groupId = group.representative_job_id;
                    const expanded = expandedGroups.has(groupId);
                    const runState = runsByGroup[groupId];
                    const panelId = `history-runs-${groupId}`;
                    return (
                      <li className="traceHistoryGroup" key={groupId}>
                        <button
                          className="traceHistoryGroupToggle"
                          type="button"
                          onClick={() => toggleGroup(groupId)}
                          aria-expanded={expanded}
                          aria-controls={panelId}
                        >
                          <span className="traceHistoryGroupIdentity">
                            <strong>{seedLabel(group)}</strong>
                            <small>
                              {modelLabel(group.latest_run)} · {group.run_count}{" "}
                              {group.run_count === 1 ? "run" : "runs"}
                            </small>
                          </span>
                          <span className="traceHistoryGroupLatest">
                            <time dateTime={group.latest_run.accepted_at}>
                              {formattedDate(group.latest_run.accepted_at)}
                            </time>
                          </span>
                        </button>

                        {expanded ? (
                          <div className="traceHistoryRuns" id={panelId}>
                            {!runState || (runState.loading && runState.items.length === 0) ? (
                              <p className="traceHistoryRunsState" role="status">
                                Loading runs…
                              </p>
                            ) : runState.error && runState.items.length === 0 ? (
                              <div className="traceHistoryRunsState" role="alert">
                                <span>{runState.error}</span>
                                <button type="button" onClick={() => void loadRuns(groupId)}>
                                  Retry
                                </button>
                              </div>
                            ) : (
                              <>
                                <ul>
                                  {runState.items.map((run) => (
                                    <li className="traceHistoryRun" key={run.job_id}>
                                      <div className="traceHistoryRunMeta">
                                        <span className={`traceHistoryStatus traceHistoryStatus-${run.status}`}>
                                          {readableStatus(run.status)}
                                        </span>
                                        <strong>{modelLabel(run)}</strong>
                                        <time dateTime={run.accepted_at}>
                                          {formattedDate(run.accepted_at)}
                                        </time>
                                        <small>
                                          {run.candidate_count}{" "}
                                          {run.candidate_count === 1 ? "candidate" : "candidates"}
                                          {" · "}
                                          {run.result_available ? "Result saved" : "No saved result"}
                                        </small>
                                      </div>
                                      <div className="traceHistoryRunActions">
                                        <Link
                                          href={`/footprint/${run.job_id}`}
                                          onClick={closeDrawer}
                                        >
                                          View
                                        </Link>
                                        <button
                                          type="button"
                                          onClick={() => void refreshRun(run)}
                                          disabled={refreshingId !== null}
                                        >
                                          {refreshingId === run.job_id ? "Starting…" : "Refresh"}
                                        </button>
                                        {terminalStatuses.has(run.status) ? (
                                          <button
                                            className="traceHistoryDelete"
                                            type="button"
                                            onClick={() => void deleteRun(run)}
                                            disabled={deletingId !== null}
                                          >
                                            {deletingId === run.job_id ? "Deleting…" : "Delete"}
                                          </button>
                                        ) : null}
                                      </div>
                                    </li>
                                  ))}
                                </ul>
                                {runState.nextCursor ? (
                                  <button
                                    className="traceHistoryMoreRuns"
                                    type="button"
                                    onClick={() =>
                                      void loadRuns(
                                        groupId,
                                        runState.nextCursor ?? undefined,
                                        true,
                                      )
                                    }
                                    disabled={runState.loading}
                                  >
                                    {runState.loading ? "Loading…" : "Show older runs"}
                                  </button>
                                ) : null}
                              </>
                            )}
                          </div>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              )}

              {loadError && groups.length > 0 ? (
                <p className="traceHistoryPaginationError" role="alert">
                  {loadError}
                </p>
              ) : null}
              {nextCursor ? (
                <button
                  className="traceHistoryLoadMore"
                  type="button"
                  onClick={() => void loadMoreGroups()}
                  disabled={loadingMore}
                >
                  {loadingMore ? "Loading…" : "Load more searches"}
                </button>
              ) : null}
            </div>
          </aside>
        </div>
      ) : null}
    </>
  );
}
