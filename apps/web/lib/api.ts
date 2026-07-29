import type {
  CreateSearchJobRequest,
  EligibilityVerification,
  EvidenceItem,
  FastBrief,
  PrototypeConfig,
  SearchJob,
} from "@public-profile-search/generated-api-client";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8800";
const API_TOKEN =
  process.env.NEXT_PUBLIC_PROTOTYPE_API_TOKEN ?? "local-prototype-token";
const USER_ID =
  process.env.NEXT_PUBLIC_PROTOTYPE_USER_ID ??
  "11111111-1111-4111-8111-111111111111";

interface ApiErrorBody {
  error_code?: string;
  message?: string;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryAfter: string | null;

  constructor(
    message: string,
    {
      code,
      status,
      retryAfter,
    }: { code: string; status: number; retryAfter: string | null },
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

function headers(extra: Record<string, string> = {}): HeadersInit {
  return {
    "Content-Type": "application/json",
    "X-Prototype-Token": API_TOKEN,
    "X-Prototype-User": USER_ID,
    ...extra,
  };
}

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = (await response.json().catch(() => ({}))) as ApiErrorBody;
    throw new ApiError(error.message ?? `Request failed (${response.status})`, {
      code: error.error_code ?? "request_failed",
      status: response.status,
      retryAfter: response.headers.get("Retry-After"),
    });
  }
  return (await response.json()) as T;
}

export async function getPrototypeConfig(): Promise<PrototypeConfig> {
  return unwrap(
    await fetch(`${API_BASE_URL}/v1/prototype-config`, {
      headers: headers(),
      cache: "no-store",
    }),
  );
}

export async function createEligibilityVerification(
  profileUrl: string,
): Promise<EligibilityVerification> {
  return unwrap(
    await fetch(`${API_BASE_URL}/v1/eligibility-verifications`, {
      method: "POST",
      headers: headers({ "Idempotency-Key": crypto.randomUUID() }),
      body: JSON.stringify({
        profile_url: profileUrl,
        purpose: "self_audit",
      }),
    }),
  );
}

export async function getEligibilityVerification(
  verificationId: string,
): Promise<EligibilityVerification> {
  return unwrap(
    await fetch(
      `${API_BASE_URL}/v1/eligibility-verifications/${encodeURIComponent(verificationId)}`,
      {
        headers: headers(),
        cache: "no-store",
      },
    ),
  );
}

export async function completeEligibilityVerification(
  verificationId: string,
): Promise<EligibilityVerification> {
  return unwrap(
    await fetch(
      `${API_BASE_URL}/v1/eligibility-verifications/${encodeURIComponent(verificationId)}/complete`,
      {
        method: "POST",
        headers: headers({ "Idempotency-Key": crypto.randomUUID() }),
      },
    ),
  );
}

export async function createSearchJob(
  payload: CreateSearchJobRequest,
): Promise<SearchJob> {
  return unwrap(
    await fetch(`${API_BASE_URL}/v1/search-jobs`, {
      method: "POST",
      headers: headers({ "Idempotency-Key": crypto.randomUUID() }),
      body: JSON.stringify(payload),
    }),
  );
}

export async function createSyntheticSearchJob(): Promise<SearchJob> {
  const config = await getPrototypeConfig();
  return createSearchJob({
    profile_url: config.fixture_url,
    purpose: config.purpose,
    target_relationship: "self",
    eligibility_reference_id: config.eligibility_reference_id,
    attestation_policy_version: config.attestation_policy_version,
    locale: "en",
  });
}

export async function getSearchJob(jobId: string): Promise<SearchJob> {
  return unwrap(
    await fetch(`${API_BASE_URL}/v1/search-jobs/${jobId}`, {
      headers: headers(),
      cache: "no-store",
    }),
  );
}

export async function getFastBrief(jobId: string): Promise<FastBrief> {
  return unwrap(
    await fetch(`${API_BASE_URL}/v1/search-jobs/${jobId}/brief`, {
      headers: headers(),
      cache: "no-store",
    }),
  );
}

export async function getEvidence(jobId: string): Promise<EvidenceItem[]> {
  const response = await unwrap<{ items: EvidenceItem[] }>(
    await fetch(`${API_BASE_URL}/v1/search-jobs/${jobId}/evidence`, {
      headers: headers(),
      cache: "no-store",
    }),
  );
  return response.items;
}

export async function deleteSearchJob(jobId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/v1/search-jobs/${jobId}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!response.ok) {
    throw new Error("The job could not be deleted.");
  }
}
