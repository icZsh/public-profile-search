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
  trust_class: string;
  publisher: string;
  title: string;
  url: string;
  excerpt: string;
  retrieved_at: string;
}

export type FootprintPlatform =
  | "github"
  | "instagram"
  | "linkedin"
  | "reddit"
  | "tiktok"
  | "twitter"
  | "x"
  | "youtube"
  | "other";

export type FootprintSearchMode = "quick" | "deep";

export type FootprintHistoryPolicy = "new_job" | "prefer_existing";

export type FootprintSynthesisModel =
  | "openai/gpt-5.6-luna"
  | "openai/gpt-5.4-nano"
  | "openai/gpt-5.4-mini"
  | "openai/gpt-oss-120b"
  | "deepseek/deepseek-v4-flash-0731"
  | "qwen/qwen3.5-35b-a3b"
  | "z-ai/glm-5.2";

export type FootprintSeed =
  | {
      kind: "platform_identifier";
      platform: FootprintPlatform;
      identifier_type: "handle";
      identifier: string;
    }
  | {
      kind: "bare_handle";
      platform?: null;
      identifier_type: "handle";
      identifier: string;
    }
  | {
      kind: "profile_url";
      profile_url: string;
      platform?: FootprintPlatform;
      identifier_type?: "handle";
      identifier?: string;
    };

export type FootprintSeedResponse =
  | {
      kind: "platform_identifier";
      platform: FootprintPlatform;
      identifier_type: "handle";
      identifier: string;
    }
  | {
      kind: "bare_handle";
      platform: null;
      identifier_type: "handle";
      identifier: string;
    }
  | {
      kind: "profile_url";
      profile_url: string;
      platform: FootprintPlatform;
      identifier_type: "handle";
      identifier: string;
    };

export interface CreateFootprintJobRequest {
  seed: FootprintSeed;
  search_mode?: FootprintSearchMode;
  synthesis_model?: FootprintSynthesisModel;
  locale?: "en-US" | "zh-CN";
  history_policy?: FootprintHistoryPolicy;
}

export type FootprintJobStatus =
  | "queued"
  | "discovering"
  | "ready"
  | "ready_partial"
  | "no_candidates"
  | "failed"
  | "cancelled";

export type FootprintExplorationStatus =
  | "idle"
  | "running"
  | "awaiting_anchor"
  | "completed"
  | "cancelled";

export interface FootprintCoverage {
  selected: number;
  completed: number;
  claimed: number;
  available: number;
  unknown: number;
  illegal: number;
}

export interface FootprintCatalog {
  engine: "maigret";
  package_version: string | null;
  database_checksum: string | null;
  profile: string | null;
}

export type FootprintDeepProgressPhase =
  | "queued"
  | "account_scan"
  | "awaiting_anchor"
  | "professional_enrichment"
  | "report_generation"
  | "finalizing"
  | "complete";

export interface FootprintDeepProgress {
  current_phase: FootprintDeepProgressPhase;
  phase_started_at: string;
  finished_at: string | null;
}

export interface FootprintJob {
  job_id: string;
  status: FootprintJobStatus;
  exploration_status: FootprintExplorationStatus;
  deep_progress: FootprintDeepProgress | null;
  seed: FootprintSeedResponse;
  search_mode: FootprintSearchMode | null;
  synthesis_model: FootprintSynthesisModel | null;
  coverage: FootprintCoverage;
  catalog: FootprintCatalog;
  events_url: string;
  candidates_url: string;
  accepted_at: string;
  deadline_at: string;
  expires_at: string;
  refresh_of_job_id: string | null;
}

export interface FootprintHistorySeed {
  kind: "platform_identifier" | "bare_handle";
  platform: FootprintPlatform | null;
  identifier: string;
}

export interface FootprintHistoryRun {
  job_id: string;
  status: FootprintJobStatus;
  search_mode: FootprintSearchMode;
  synthesis_model: FootprintSynthesisModel | null;
  accepted_at: string;
  finished_at: string | null;
  expires_at: string;
  candidate_count: number;
  result_available: boolean;
  refresh_of_job_id: string | null;
}

export interface FootprintHistoryGroup {
  representative_job_id: string;
  seed: FootprintHistorySeed;
  latest_run: FootprintHistoryRun;
  run_count: number;
}

export interface FootprintHistoryGroupPage {
  items: FootprintHistoryGroup[];
  next_cursor: string | null;
}

export interface FootprintHistoryRunPage {
  items: FootprintHistoryRun[];
  next_cursor: string | null;
}

export interface ClearFootprintHistoryResponse {
  deleted_count: number;
  has_more: boolean;
}

export interface SelectFootprintAnchorRequest {
  candidate_id: string;
}

export interface SelectedFootprintAnchor {
  candidate_id: string;
  platform: string;
  handle: string;
  profile_url: string;
  display_name: string | null;
  selection_state: "included";
}

export interface SelectFootprintAnchorResponse {
  job: FootprintJob;
  selected_anchor: SelectedFootprintAnchor;
}

export interface CandidateEvidence {
  site_check_id: string;
  site_name: string;
  status: "CLAIMED" | "AVAILABLE" | "UNKNOWN" | "ILLEGAL";
  discovery_method: "username_catalog_probe" | "similar_handle_result";
  observed_at: string;
}

export interface AccountCandidate {
  candidate_id: string;
  platform: string;
  handle: string;
  profile_url: string;
  display_name: string | null;
  relationship: "unresolved";
  identity_tier: "possible" | "weak";
  selection_state: "undecided" | "included" | "excluded";
  anchor_eligible: boolean;
  is_similar: boolean;
  profile_data: Record<string, unknown>;
  discovered_at: string;
  evidence: CandidateEvidence[];
}

export interface CandidateList {
  items: AccountCandidate[];
  extracted_identifier_count: number;
}

export type FootprintConfidence = "high" | "medium_high" | "medium" | "low";

export interface FootprintBriefAccount {
  candidate_id: string;
  platform: string;
  handle: string;
  profile_url: string;
  display_name: string | null;
  existence_status:
    | "exact_verified"
    | "indexed_profile"
    | "claimed_unverified"
    | "channel_limited"
    | "excluded";
  identity_status:
    | "confirmed"
    | "likely"
    | "unverified"
    | "conflicting"
    | "excluded";
  confidence: FootprintConfidence;
  source_ids: string[];
  reasons: string[];
}

export interface FootprintBriefClaim {
  claim_id: string;
  predicate: string;
  label: string;
  value: string;
  confidence: FootprintConfidence;
  source_ids: string[];
  qualification: string | null;
}

export interface FootprintIdentityReasons {
  supporting: string[];
  limiting: string[];
}

export interface FootprintCitedText {
  text: string;
  source_ids: string[];
}

export interface FootprintNarrativeSection {
  key: string;
  title: string;
  body: string;
  source_ids: string[];
  highlights: FootprintCitedText[];
}

export interface FootprintDeepIdentityFact {
  label: string;
  value: string;
  confidence: FootprintConfidence;
  status:
    | "observed"
    | "self_described"
    | "indexed"
    | "likely"
    | "independently_unverified"
    | "unknown";
  qualification: string | null;
  source_ids: string[];
}

export interface FootprintDeepAccountInsight {
  account_id: string;
  rationale: string;
  source_ids: string[];
  public_facts: FootprintCitedText[];
  association_reasons: FootprintCitedText[];
}

export interface FootprintDeepCuratedClaim {
  claim_id: string;
  predicate: string;
  label: string;
  value: string;
  confidence: "high" | "medium_high" | "medium" | "low";
  status:
    | "confirmed"
    | "likely"
    | "possible"
    | "independently_unverified"
    | "contradicted"
    | "unknown";
  source_ids: string[];
  contradicting_source_ids: string[];
  qualification: string | null;
  supporting_evidence: FootprintCitedText[];
  limiting_evidence: FootprintCitedText[];
}

export interface FootprintDeepExcludedCandidate {
  account_id: string | null;
  label: string;
  disposition:
    | "excluded"
    | "unverified"
    | "derivative"
    | "no_exact_hit"
    | "separate_cluster";
  reason: string;
  source_ids: string[];
}

export interface FootprintDeepChannelCoverage {
  channel: string;
  status:
    | "confirmed"
    | "likely"
    | "candidate"
    | "unverified"
    | "no_exact_hit"
    | "channel_limited"
    | "excluded"
    | "not_checked";
  detail: string;
  source_ids: string[];
}

export type FootprintDeepProfileBasis =
  | "observed"
  | "self_described"
  | "indexed"
  | "inferred"
  | "mixed"
  | "unknown";

export interface FootprintDeepProfileAnswer {
  value: string | null;
  confidence: FootprintConfidence | null;
  basis: FootprintDeepProfileBasis;
  explanation: string;
  source_ids: string[];
}

export interface FootprintDeepProfileTrait {
  label: string;
  confidence: FootprintConfidence;
  basis: Exclude<FootprintDeepProfileBasis, "unknown">;
  explanation: string;
  source_ids: string[];
}

export interface FootprintDeepProfileUnknown {
  topic:
    | "identity"
    | "location"
    | "occupation"
    | "education"
    | "interests"
    | "likes"
    | "dislikes"
    | "projects"
    | "other";
  explanation: string;
  source_ids: string[];
}

export interface FootprintDeepTimelineEntry {
  entry_type: "work" | "education";
  title: string;
  organization: string | null;
  timeframe: string | null;
  currentness: "current" | "recent" | "historical" | "unclear";
  confidence: FootprintConfidence;
  basis: Exclude<FootprintDeepProfileBasis, "unknown">;
  explanation: string;
  source_ids: string[];
}

export interface FootprintDeepSubjectProfile {
  identity: FootprintDeepProfileAnswer;
  location: FootprintDeepProfileAnswer;
  occupation: FootprintDeepProfileAnswer;
  education: FootprintDeepProfileAnswer;
  interests: FootprintDeepProfileTrait[];
  likes: FootprintDeepProfileTrait[];
  dislikes: FootprintDeepProfileTrait[];
  unknowns: FootprintDeepProfileUnknown[];
  career_timeline: FootprintDeepTimelineEntry[];
}

export interface FootprintDeepStory {
  version: "deep-story-v2" | "deep-story-v3" | "deep-story-v4";
  overview: string;
  overview_source_ids: string[];
  conclusion: string;
  conclusion_source_ids: string[];
  overall_confidence: FootprintConfidence;
  likely_public_identity: string | null;
  broad_location: string | null;
  major_boundary: string;
  identity_facts: FootprintDeepIdentityFact[];
  account_insights: FootprintDeepAccountInsight[];
  curated_claims: FootprintDeepCuratedClaim[];
  excluded_candidates: FootprintDeepExcludedCandidate[];
  channel_coverage: FootprintDeepChannelCoverage[];
  next_verification_steps: FootprintCitedText[];
  subject_profile?: FootprintDeepSubjectProfile | null;
}

export interface FootprintSynthesis {
  mode: "deterministic" | "llm_grounded";
  status: "complete" | "fallback";
  provider?: "openai" | "openrouter" | null;
  model: string | null;
  prompt_version: string;
  fallback_reason: string | null;
}

export interface FootprintBrief {
  job_id: string;
  report_type: "account_centric" | "person_centric";
  subject: string;
  summary: string;
  overall_identity_status: "confirmed" | "likely" | "unverified";
  accounts: FootprintBriefAccount[];
  claims: FootprintBriefClaim[];
  identity_reasons: FootprintIdentityReasons;
  narrative_sections?: FootprintNarrativeSection[];
  deep_story?: FootprintDeepStory | null;
  synthesis?: FootprintSynthesis | null;
  limitations: string[];
  generated_at: string;
}

export type JobEventType =
  | "job_queued"
  | "collection_started"
  | "source_completed"
  | "finalization_started"
  | "brief_ready"
  | "insufficient_evidence"
  | "job_cancelled"
  | "result_unavailable"
  | "job_deleted"
  | "job.accepted"
  | "discovery.catalog_scan_started"
  | "discovery.catalog_progress"
  | "discovery.anchor_required"
  | "discovery.anchor_selected"
  | "discovery.anchor_window_expired"
  | "discovery.professional_search_started"
  | "discovery.professional_search_progress"
  | "discovery.synthesis_started"
  | "discovery.synthesis_progress"
  | "candidate.discovered"
  | "job.ready";

export interface JobEvent {
  job_id: string;
  sequence: number;
  type: JobEventType;
  message: string;
  terminal?: boolean;
  created_at: string;
}
