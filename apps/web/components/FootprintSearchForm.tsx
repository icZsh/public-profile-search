"use client";

import type {
  CreateFootprintJobRequest,
  FootprintSearchMode,
  FootprintSeed,
} from "@public-profile-search/generated-api-client";
import { useRouter } from "next/navigation";
import { type FormEvent, useRef, useState } from "react";

import { createFootprintJob } from "@/lib/api";

const searchModeOptions: {
  value: FootprintSearchMode;
  label: string;
  eyebrow: string;
  description: string;
}[] = [
  {
    value: "quick",
    label: "Quick",
    eyebrow: "Focused retrieval",
    description:
      "A focused 20-site account scan and short people search with a concise evidence brief.",
  },
  {
    value: "deep",
    label: "Deep",
    eyebrow: "Expanded retrieval + story",
    description:
      "A broader 56-site scan and full professional search, followed by a source-grounded story.",
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
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
    <form className="discoverySearchCard" onSubmit={submit}>
      <div className="discoveryFormHeading">
        <div>
          <span className="formKicker">Start with one public clue</span>
          <h2>Search a handle or profile URL.</h2>
        </div>
        <span className="providerBadge">Maigret core</span>
      </div>

      <fieldset className="searchModePicker" disabled={busy}>
        <legend>Search depth</legend>
        <div className="searchModeOptions">
          {searchModeOptions.map((option) => (
            <label
              className={`searchModeOption ${
                searchMode === option.value ? "searchModeOptionSelected" : ""
              }`}
              key={option.value}
            >
              <input
                type="radio"
                name="search_mode"
                value={option.value}
                checked={searchMode === option.value}
                onChange={() => setSearchMode(option.value)}
              />
              <span>
                <span className="searchModeOptionHeading">
                  <strong>{option.label}</strong>
                  <small>{option.eyebrow}</small>
                </span>
                <span className="searchModeOptionDescription">
                  {option.description}
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="discoveryInputGrid">
        <label className="discoveryField" htmlFor="seed-identifier">
          <span>Handle or public profile URL</span>
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
        </label>

        <button className="discoverySubmit" type="submit" disabled={busy}>
          {busy
            ? "Starting search…"
            : searchMode === "deep"
              ? "Build deep story"
              : "Find profiles"}
        </button>
      </div>

      <div className="discoveryFormMeta">
        <span>
          <i className="statusDot" />{" "}
          {searchMode === "deep"
            ? "Deep story workflow"
            : "Adaptive evidence workflow"}
        </span>
        <span>
          {searchMode === "deep"
            ? "56-site scan, full retrieval, then grounded LLM composition"
            : "20-site scan with up to 40 seconds for people search"}
        </span>
        <span>No account match is assumed to be the same person</span>
      </div>

      {error ? (
        <p className="formError" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
