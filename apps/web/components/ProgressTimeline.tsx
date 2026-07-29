import type { JobStatus } from "@public-profile-search/generated-api-client";

const steps: { status: JobStatus[]; label: string }[] = [
  { status: ["queued"], label: "Job accepted" },
  { status: ["running"], label: "Collecting approved public evidence" },
  { status: ["finalizing"], label: "Freezing and evaluating evidence" },
  {
    status: ["complete", "partial", "insufficient_evidence"],
    label: "Deterministic outcome",
  },
];

const ranks: Record<JobStatus, number> = {
  queued: 0,
  running: 1,
  finalizing: 2,
  complete: 3,
  partial: 3,
  insufficient_evidence: 3,
  result_unavailable: 3,
  service_error: 3,
  cancelled: 3,
};

export function ProgressTimeline({ status }: { status: JobStatus }) {
  const current = ranks[status];
  return (
    <ol className="timeline" aria-label="Job progress">
      {steps.map((step, index) => (
        <li
          className={index < current ? "done" : index === current ? "current" : ""}
          key={step.label}
        >
          <span>{index < current ? "✓" : index + 1}</span>
          {step.label}
        </li>
      ))}
    </ol>
  );
}
