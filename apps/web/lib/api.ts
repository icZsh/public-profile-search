import type {
  CandidateList,
  CreateSearchJobRequest,
  CreateFootprintJobRequest,
  EligibilityVerification,
  EvidenceItem,
  FastBrief,
  FootprintBrief,
  FootprintHistoryGroupPage,
  FootprintHistoryRunPage,
  FootprintJob,
  ClearFootprintHistoryResponse,
  PrototypeConfig,
  SearchJob,
  SelectFootprintAnchorRequest,
  SelectFootprintAnchorResponse,
} from "@public-profile-search/generated-api-client";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";
const API_TOKEN =
  process.env.NEXT_PUBLIC_PROTOTYPE_API_TOKEN ?? "local-prototype-token";
const USER_ID =
  process.env.NEXT_PUBLIC_PROTOTYPE_USER_ID ??
  "11111111-1111-4111-8111-111111111111";

export function createIdempotencyKey(): string {
  const cryptoProvider = globalThis.crypto;
  if (typeof cryptoProvider?.randomUUID === "function") {
    return cryptoProvider.randomUUID();
  }

  const bytes = new Uint8Array(16);
  if (typeof cryptoProvider?.getRandomValues === "function") {
    cryptoProvider.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  const hex = Array.from(bytes, (value) =>
    value.toString(16).padStart(2, "0"),
  );
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex
    .slice(6, 8)
    .join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

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
      headers: headers({ "Idempotency-Key": createIdempotencyKey() }),
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
        headers: headers({ "Idempotency-Key": createIdempotencyKey() }),
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
      headers: headers({ "Idempotency-Key": createIdempotencyKey() }),
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

export async function createFootprintJob(
  payload: CreateFootprintJobRequest,
  idempotencyKey = createIdempotencyKey(),
): Promise<FootprintJob> {
  return unwrap(
    await fetch(`${API_BASE_URL}/v1/footprint-jobs`, {
      method: "POST",
      headers: headers({ "Idempotency-Key": idempotencyKey }),
      body: JSON.stringify(payload),
    }),
  );
}

export interface FootprintHistoryQuery {
  q?: string;
  cursor?: string;
  limit?: number;
  signal?: AbortSignal;
}

function historyQueryString({
  q,
  cursor,
  limit,
}: Omit<FootprintHistoryQuery, "signal">): string {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (cursor) params.set("cursor", cursor);
  if (limit !== undefined) params.set("limit", String(limit));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export async function getFootprintHistory({
  signal,
  ...query
}: FootprintHistoryQuery = {}): Promise<FootprintHistoryGroupPage> {
  return unwrap(
    await fetch(
      `${API_BASE_URL}/v1/footprint-jobs${historyQueryString(query)}`,
      {
        headers: headers(),
        cache: "no-store",
        signal,
      },
    ),
  );
}

export async function getFootprintHistoryRuns(
  jobId: string,
  {
    signal,
    ...query
  }: Omit<FootprintHistoryQuery, "q"> = {},
): Promise<FootprintHistoryRunPage> {
  return unwrap(
    await fetch(
      `${API_BASE_URL}/v1/footprint-jobs/${encodeURIComponent(jobId)}/history${historyQueryString(query)}`,
      {
        headers: headers(),
        cache: "no-store",
        signal,
      },
    ),
  );
}

export async function refreshFootprintJob(
  jobId: string,
  idempotencyKey = createIdempotencyKey(),
): Promise<FootprintJob> {
  return unwrap(
    await fetch(
      `${API_BASE_URL}/v1/footprint-jobs/${encodeURIComponent(jobId)}/refresh`,
      {
        method: "POST",
        headers: headers({ "Idempotency-Key": idempotencyKey }),
      },
    ),
  );
}

async function unwrapEmpty(response: Response): Promise<void> {
  if (!response.ok) {
    await unwrap<never>(response);
  }
}

export async function deleteFootprintJob(jobId: string): Promise<void> {
  return unwrapEmpty(
    await fetch(
      `${API_BASE_URL}/v1/footprint-jobs/${encodeURIComponent(jobId)}`,
      {
        method: "DELETE",
        headers: headers(),
      },
    ),
  );
}

export async function clearFootprintHistory(
  limit = 50,
): Promise<ClearFootprintHistoryResponse> {
  const query = new URLSearchParams({ limit: String(limit) });
  return unwrap(
    await fetch(`${API_BASE_URL}/v1/footprint-jobs?${query.toString()}`, {
      method: "DELETE",
      headers: headers(),
    }),
  );
}

export async function getFootprintJob(jobId: string): Promise<FootprintJob> {
  return unwrap(
    await fetch(
      `${API_BASE_URL}/v1/footprint-jobs/${encodeURIComponent(jobId)}`,
      {
        headers: headers(),
        cache: "no-store",
      },
    ),
  );
}

export async function cancelFootprintJob(jobId: string): Promise<FootprintJob> {
  return unwrap(
    await fetch(
      `${API_BASE_URL}/v1/footprint-jobs/${encodeURIComponent(jobId)}/cancel`,
      {
        method: "POST",
        headers: headers(),
      },
    ),
  );
}

export async function getFootprintCandidates(
  jobId: string,
): Promise<CandidateList> {
  return unwrap(
    await fetch(
      `${API_BASE_URL}/v1/footprint-jobs/${encodeURIComponent(jobId)}/candidates`,
      {
        headers: headers(),
        cache: "no-store",
      },
    ),
  );
}

export async function selectFootprintAnchor(
  jobId: string,
  candidateId: string,
): Promise<SelectFootprintAnchorResponse> {
  const payload: SelectFootprintAnchorRequest = {
    candidate_id: candidateId,
  };
  return unwrap(
    await fetch(
      `${API_BASE_URL}/v1/footprint-jobs/${encodeURIComponent(jobId)}/anchor`,
      {
        method: "POST",
        headers: headers(),
        body: JSON.stringify(payload),
      },
    ),
  );
}

export async function getFootprintBrief(
  jobId: string,
): Promise<FootprintBrief> {
  return unwrap(
    await fetch(
      `${API_BASE_URL}/v1/footprint-jobs/${encodeURIComponent(jobId)}/brief`,
      {
        headers: headers(),
        cache: "no-store",
      },
    ),
  );
}

export async function getFootprintEvidence(
  jobId: string,
): Promise<EvidenceItem[]> {
  const response = await unwrap<{ items: EvidenceItem[] }>(
    await fetch(
      `${API_BASE_URL}/v1/footprint-jobs/${encodeURIComponent(jobId)}/evidence`,
      {
        headers: headers(),
        cache: "no-store",
      },
    ),
  );
  return response.items;
}
