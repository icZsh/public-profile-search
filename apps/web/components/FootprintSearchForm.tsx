"use client";

import type {
  CreateFootprintJobRequest,
  FootprintSearchMode,
  FootprintSeed,
  FootprintSynthesisModel,
} from "@public-profile-search/generated-api-client";
import { useRouter } from "next/navigation";
import { type FormEvent, useRef, useState } from "react";

import { createFootprintJob } from "@/lib/api";
import {
  DEFAULT_SYNTHESIS_MODEL,
  SYNTHESIS_MODEL_OPTIONS,
} from "@/lib/synthesis-models";

const searchModeOptions: {
  value: FootprintSearchMode;
  label: string;
  eyebrow: string;
  description: string;
  time: string;
  features: string[];
  unavailable: string[];
}[] = [
  {
    value: "quick",
    label: "Quick",
    eyebrow: "Focused retrieval",
    description:
      "20 sites and a short people search. You get the account cluster and what the evidence directly supports.",
    time: "about 1 minute",
    features: ["Accounts", "Cited answers"],
    unavailable: ["No narrative", "No timeline"],
  },
  {
    value: "deep",
    label: "Deep",
    eyebrow: "Expanded retrieval + story",
    description:
      "A broader 56-site scan and full professional search, followed by a source-grounded story.",
    time: "varies by model",
    features: ["Accounts", "Cited answers", "Narrative", "Timeline"],
    unavailable: [],
  },
];

function errorMessage(reason: unknown): string {
  return reason instanceof Error
    ? reason.message
    : "The discovery job could not be started.";
}

function isHttpProfileUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

export function FootprintSearchForm() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [searchMode, setSearchMode] = useState<FootprintSearchMode>("quick");
  const [synthesisModel, setSynthesisModel] =
    useState<FootprintSynthesisModel>(DEFAULT_SYNTHESIS_MODEL);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selectedSynthesisOption =
    SYNTHESIS_MODEL_OPTIONS.find(
      (option) => option.value === synthesisModel,
    ) ?? SYNTHESIS_MODEL_OPTIONS[0];
  const creationAttempt = useRef<{
    payloadSignature: string;
    idempotencyKey: string;
  } | null>(null);

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
      ...(searchMode === "deep"
        ? { synthesis_model: synthesisModel }
        : {}),
    };
    const payloadSignature = JSON.stringify(payload);
    if (creationAttempt.current?.payloadSignature !== payloadSignature) {
      creationAttempt.current = {
        payloadSignature,
        idempotencyKey: crypto.randomUUID(),
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
    <form className="traceSearchCard" onSubmit={submit}>
      <div className="traceSearchInputRow">
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
        <button className="tracePrimaryButton" type="submit" disabled={busy}>
          {busy ? "Starting brief…" : "Build the brief"}
        </button>
      </div>

      <fieldset className="traceModePicker" disabled={busy}>
        <legend>Search depth</legend>
        <div className="traceModeOptions">
          {searchModeOptions.map((option) => (
            <label
              className={`traceModeOption ${
                searchMode === option.value ? "traceModeOptionSelected" : ""
              }`}
              key={option.value}
              onClick={() => setSearchMode(option.value)}
            >
              <input
                type="radio"
                name="search_mode"
                value={option.value}
                checked={searchMode === option.value}
                onChange={() => setSearchMode(option.value)}
              />
              <span className="traceModeOptionBody">
                <span className="traceModeOptionHeading">
                  <strong>
                    {option.label}
                    {searchMode === option.value ? (
                      <small className="traceSelectedBadge">Selected</small>
                    ) : null}
                  </strong>
                  <small>{option.time}</small>
                </span>
                <span className="traceSrOnly">{option.eyebrow}. </span>
                <span className="traceModeOptionDescription">{option.description}</span>
                <span className="traceModeFeatures" aria-hidden="true">
                  {option.features.map((feature) => (
                    <span
                      className={
                        feature === "Narrative" || feature === "Timeline"
                          ? "traceModeFeature traceModeFeatureAccent"
                          : "traceModeFeature"
                      }
                      key={feature}
                    >
                      {feature}
                    </span>
                  ))}
                  {option.unavailable.map((feature) => (
                    <span className="traceModeFeature traceModeFeatureUnavailable" key={feature}>
                      {feature}
                    </span>
                  ))}
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {searchMode === "deep" ? (
        <div className="traceModelPicker">
          <label className="traceModelPickerLabel" htmlFor="synthesis-model">
            <strong>Story model</strong>
            <span>Choose how the source-grounded story is composed.</span>
          </label>
          <div className="traceModelControl">
            <select
              id="synthesis-model"
              name="synthesis_model"
              value={synthesisModel}
              onChange={(event) =>
                setSynthesisModel(event.target.value as FootprintSynthesisModel)
              }
              disabled={busy}
              aria-describedby="synthesis-model-note"
            >
              {SYNTHESIS_MODEL_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <p className="traceModelSummary" id="synthesis-model-note">
              <span>
                <strong>{selectedSynthesisOption.speedLabel}</strong>
                {selectedSynthesisOption.inputPrice} input ·{" "}
                {selectedSynthesisOption.outputPrice} output per 1M tokens
              </span>
              <small>Prices and relative latency estimates can change.</small>
            </p>
          </div>
        </div>
      ) : null}

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
