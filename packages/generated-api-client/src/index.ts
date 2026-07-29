// Generated client types will replace this boundary once contract generation is wired.
// Keeping the package present prevents frontend code from inventing a second DTO package.
export type JobStatus =
  | "queued"
  | "running"
  | "finalizing"
  | "complete"
  | "partial"
  | "insufficient_evidence"
  | "result_unavailable"
  | "service_error"
  | "cancelled";

export interface SearchJob {
  job_id: string;
  status: JobStatus;
  collection_cutoff_at: string;
  fallback_at: string;
  deadline_at: string;
  events_url: string;
}

export interface PrototypeConfig {
  fixture_url: string;
  eligibility_reference_id: string;
  purpose: "self_audit";
  attestation_policy_version: string;
  allowed_profile_hosts: string[];
  github_provider_enabled: boolean;
}

export type EligibilityVerificationStatus =
  | "verification_pending"
  | "pending_control"
  | "control_verified_review_pending"
  | "review_pending"
  | "eligible_verified_self"
  | "eligible"
  | "expired"
  | "denied"
  | "unavailable";

export interface EligibilityVerification {
  verification_id: string;
  status: EligibilityVerificationStatus;
  purpose: "self_audit";
  provider_id: string;
  canonical_profile_url: string;
  policy_version: string;
  challenge_value?: string | null;
  challenge_expires_at?: string | null;
  review_expires_at?: string | null;
  eligibility_reference_id?: string | null;
  eligibility_expires_at?: string | null;
  attempts_remaining: number;
  message?: string | null;
}

export interface CreateSearchJobRequest {
  profile_url: string;
  purpose: "self_audit";
  target_relationship: "self";
  eligibility_reference_id: string;
  attestation_policy_version: string;
  locale: "en" | "zh-CN";
}

export interface Claim {
  claim_id: string;
  predicate: string;
  label: string;
  value: string;
  confidence: "high" | "medium_high" | "medium" | "low" | "unknown";
  evidence_ids: string[];
}

export interface FastBrief {
  job_id: string;
  subject: string;
  summary: string;
  claims: Claim[];
  limitations: string[];
  generated_at: string;
}

export interface EvidenceItem {
  evidence_id: string;
  source_type: string;
  title: string;
  url: string;
  excerpt: string;
  retrieved_at: string;
}
