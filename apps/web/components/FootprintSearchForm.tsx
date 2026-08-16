"use client";

import type {
  CreateFootprintJobRequest,
  FootprintSearchMode,
  FootprintSeed,
  FootprintSynthesisModel,
} from "@public-profile-search/generated-api-client";
import { MagnifyingGlassIcon, SparkleIcon } from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import {
  type FocusEvent,
  type FormEvent,
  type PointerEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { createFootprintJob, createIdempotencyKey } from "@/lib/api";
import {
  DEFAULT_SYNTHESIS_MODEL,
  SYNTHESIS_MODEL_OPTIONS,
} from "@/lib/synthesis-models";

function errorMessage(reason: unknown): string {
  return reason instanceof Error
    ? reason.message
    : "The discovery job could not be started.";
}

function isHttpProfileUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

function hasFineHoverPointer(pointerType: string): boolean {
  if (pointerType !== "mouse") return false;
  return (
    typeof window.matchMedia !== "function" ||
    window.matchMedia("(hover: hover) and (pointer: fine)").matches
  );
}

export function FootprintSearchForm() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [searchMode, setSearchMode] = useState<FootprintSearchMode>("quick");
  const [synthesisModel, setSynthesisModel] =
    useState<FootprintSynthesisModel>(DEFAULT_SYNTHESIS_MODEL);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const modeControlRef = useRef<HTMLDivElement>(null);
  const tooltipCloseTimer = useRef<number | null>(null);
  const pointerFocusType = useRef<string | null>(null);
  const focusKeepsTooltipOpen = useRef(false);
  const creationAttempt = useRef<{
    payloadSignature: string;
    idempotencyKey: string;
  } | null>(null);

  function cancelTooltipClose() {
    if (tooltipCloseTimer.current !== null) {
      window.clearTimeout(tooltipCloseTimer.current);
      tooltipCloseTimer.current = null;
    }
  }

  function dismissTooltip() {
    cancelTooltipClose();
    setTooltipOpen(false);
  }

  function handleModePointerEnter(event: PointerEvent<HTMLDivElement>) {
    if (!hasFineHoverPointer(event.pointerType)) return;
    cancelTooltipClose();
    setTooltipOpen(true);
  }

  function handleModePointerLeave(event: PointerEvent<HTMLDivElement>) {
    if (!hasFineHoverPointer(event.pointerType)) return;
    if (
      event.relatedTarget instanceof Node &&
      event.currentTarget.contains(event.relatedTarget)
    ) {
      return;
    }
    cancelTooltipClose();
    tooltipCloseTimer.current = window.setTimeout(() => {
      tooltipCloseTimer.current = null;
      if (!focusKeepsTooltipOpen.current) {
        setTooltipOpen(false);
      }
    }, 160);
  }

  function handleModePointerDown(event: PointerEvent<HTMLButtonElement>) {
    pointerFocusType.current = event.pointerType;
    focusKeepsTooltipOpen.current = false;
    if (event.pointerType !== "mouse") dismissTooltip();
  }

  function handleModeFocus() {
    const pointerType = pointerFocusType.current;
    pointerFocusType.current = null;
    if (pointerType !== null) return;
    focusKeepsTooltipOpen.current = true;
    cancelTooltipClose();
    setTooltipOpen(true);
  }

  function handleModeBlur(event: FocusEvent<HTMLButtonElement>) {
    if (
      event.relatedTarget instanceof Node &&
      modeControlRef.current?.contains(event.relatedTarget)
    ) {
      return;
    }
    focusKeepsTooltipOpen.current = false;
    dismissTooltip();
  }

  useEffect(() => {
    return () => cancelTooltipClose();
  }, []);

  useEffect(() => {
    if (!tooltipOpen) return;
    function dismissOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (tooltipCloseTimer.current !== null) {
        window.clearTimeout(tooltipCloseTimer.current);
        tooltipCloseTimer.current = null;
      }
      focusKeepsTooltipOpen.current = false;
      setTooltipOpen(false);
    }
    document.addEventListener("keydown", dismissOnEscape);
    return () => document.removeEventListener("keydown", dismissOnEscape);
  }, [tooltipOpen]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    const normalizedIdentifier = identifier.trim();
    if (!normalizedIdentifier) return;

    const seed: FootprintSeed = isHttpProfileUrl(normalizedIdentifier)
      ? {
          kind: "profile_url",
          profile_url: normalizedIdentifier,
        }
      : {
          kind: "bare_handle",
          identifier_type: "handle",
          identifier: normalizedIdentifier.replace(/^@+/, ""),
        };

    if (seed.kind === "bare_handle" && !seed.identifier) {
      setError("Enter a handle or a complete public profile URL.");
      return;
    }
    if (seed.kind === "bare_handle" && seed.identifier.length > 64) {
      setError("Handles can be at most 64 characters.");
      return;
    }

    setBusy(true);
    setError("");
    const payload: CreateFootprintJobRequest = {
      seed,
      search_mode: searchMode,
      locale: "en-US",
      history_policy: "prefer_existing",
      ...(searchMode === "deep"
        ? { synthesis_model: synthesisModel }
        : {}),
    };
    const payloadSignature = JSON.stringify(payload);
    if (creationAttempt.current?.payloadSignature !== payloadSignature) {
      creationAttempt.current = {
        payloadSignature,
        idempotencyKey: createIdempotencyKey(),
      };
    }
    try {
      const job = await createFootprintJob(
        payload,
        creationAttempt.current.idempotencyKey,
      );
      creationAttempt.current = null;
      router.push(`/footprint/${job.job_id}`);
    } catch (reason) {
      setError(errorMessage(reason));
      setBusy(false);
    }
  }

  return (
    <form
      className="traceSearchCard"
      onSubmit={submit}
      role="search"
      aria-label="Public footprint search"
    >
      <div
        className={`traceUnifiedSearch ${
          searchMode === "deep" ? "traceUnifiedSearchDeep" : ""
        }`}
      >
        <label className="traceSrOnly" htmlFor="seed-identifier">
          Handle or public profile URL
        </label>
        <input
          id="seed-identifier"
          name="identifier"
          type="text"
          value={identifier}
          onChange={(event) => setIdentifier(event.target.value)}
          placeholder="Handle or public profile URL"
          autoCapitalize="none"
          autoComplete="off"
          spellCheck={false}
          maxLength={300}
          required
          disabled={busy}
        />

        {searchMode === "deep" ? (
          <div className="traceInlineModelPicker">
            <label className="traceSrOnly" htmlFor="synthesis-model">
              Deep story model
            </label>
            <select
              id="synthesis-model"
              name="synthesis_model"
              value={synthesisModel}
              onChange={(event) =>
                setSynthesisModel(event.target.value as FootprintSynthesisModel)
              }
              disabled={busy}
            >
              {SYNTHESIS_MODEL_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        <div
          className="traceDeepModeControl"
          ref={modeControlRef}
          onPointerEnter={handleModePointerEnter}
          onPointerLeave={handleModePointerLeave}
        >
          <button
            className="traceDeepModeToggle"
            type="button"
            onClick={() =>
              setSearchMode((current) => current === "deep" ? "quick" : "deep")
            }
            onPointerDown={handleModePointerDown}
            onFocus={handleModeFocus}
            onBlur={handleModeBlur}
            disabled={busy}
            aria-label="Deep search mode"
            aria-pressed={searchMode === "deep"}
            aria-describedby="search-depth-tooltip"
          >
            <SparkleIcon aria-hidden="true" size={17} weight="fill" />
            <span>Deep</span>
          </button>
          <div
            className={`traceSearchModeTooltip ${
              tooltipOpen ? "traceSearchModeTooltipOpen" : ""
            }`}
            id="search-depth-tooltip"
            role="tooltip"
            aria-hidden={!tooltipOpen}
          >
            <span>
              <strong>Quick</strong>
              Focused account and people search with cited answers.
            </span>
            <span>
              <strong>Deep</strong>
              Broader account and professional search with a cited narrative and timeline.
            </span>
          </div>
        </div>

        <button
          className="tracePrimaryButton traceSearchSubmit"
          type="submit"
          disabled={busy}
          aria-label={busy ? "Starting the brief" : "Build the brief"}
        >
          {busy ? (
            <span className="traceSearchBusySpinner" aria-hidden="true" />
          ) : (
            <MagnifyingGlassIcon aria-hidden="true" size={16} weight="bold" />
          )}
        </button>
      </div>

      <input type="hidden" name="search_mode" value={searchMode} />

      <p
        className="traceSrOnly"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {busy ? "Starting the brief." : ""}
      </p>

      {error ? (
        <p className="traceFormError" role="alert">
          {error}
        </p>
      ) : null}
      <p className="traceSrOnly">
        No account match is assumed to be the same person.
      </p>
    </form>
  );
}
