"use client";

import type {
  EvidenceItem,
  FastBrief as FastBriefType,
  JobStatus,
  SearchJob,
} from "@public-profile-search/generated-api-client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { EvidenceDrawer } from "@/components/EvidenceDrawer";
import { FastBrief } from "@/components/FastBrief";
import { ProgressTimeline } from "@/components/ProgressTimeline";
import {
  deleteSearchJob,
  getEvidence,
  getFastBrief,
  getSearchJob,
} from "@/lib/api";

const terminalStatuses: JobStatus[] = [
  "complete",
  "partial",
  "insufficient_evidence",
  "result_unavailable",
  "service_error",
  "cancelled",
];

export function JobExperience({ jobId }: { jobId: string }) {
  const router = useRouter();
  const [job, setJob] = useState<SearchJob | null>(null);
  const [brief, setBrief] = useState<FastBriefType | null>(null);
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function refresh() {
      try {
        const current = await getSearchJob(jobId);
        if (!active) return;
        setJob(current);
        if (current.status === "complete" || current.status === "partial") {
          const [nextBrief, nextEvidence] = await Promise.all([
            getFastBrief(jobId),
            getEvidence(jobId),
          ]);
          if (active) {
            setBrief(nextBrief);
            setEvidence(nextEvidence);
          }
          return;
        }
        if (!terminalStatuses.includes(current.status)) {
          timer = setTimeout(refresh, 700);
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : "The job could not be loaded.");
        }
      }
    }

    refresh();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  async function removeJob() {
    setDeleting(true);
    try {
      await deleteSearchJob(jobId);
      router.push("/");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The job could not be deleted.");
      setDeleting(false);
    }
  }

  return (
    <main className="resultShell">
      <nav className="topbar">
        <Link className="brand" href="/">
          tracebrief<span className="brandMark">/</span>
        </Link>
        <span className="prototypePill">Job {jobId.slice(0, 8)}</span>
      </nav>

      {!brief ? (
        <section className="processingCard">
          <div className="eyebrow">Local processing</div>
          <h1>{error ? "The prototype stopped." : "Building the evidence trail…"}</h1>
          <p>
            {error ||
              "Approved sources are completing through the durable job pipeline."}
          </p>
          <ProgressTimeline status={job?.status ?? "queued"} />
          {job?.status === "insufficient_evidence" ? (
            <p className="formError">The accepted evidence did not meet minimum utility.</p>
          ) : null}
          <Link className="textLink" href="/">
            ← Return to profile verification
          </Link>
        </section>
      ) : (
        <div className="resultGrid">
          <FastBrief brief={brief} />
          <EvidenceDrawer items={evidence} />
          <div className="resultActions">
            <Link className="textLink" href="/">
              ← Run another brief
            </Link>
            <button className="deleteButton" onClick={removeJob} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete local job"}
            </button>
          </div>
          {error ? <p className="formError">{error}</p> : null}
        </div>
      )}
    </main>
  );
}
