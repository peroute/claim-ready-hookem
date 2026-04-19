/**
 * Typed client for the Claim-ready FastAPI backend.
 *
 * All endpoints live under NEXT_PUBLIC_API_BASE (defaults to
 * http://localhost:8000 for local dev). Types here mirror the
 * dataclasses in backend/schemas.py exactly so the JSON wire format
 * round-trips without massaging.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types — kept 1:1 with backend/schemas.py
// ---------------------------------------------------------------------------

export type ItemCategory =
  | "electronics"
  | "furniture"
  | "textile"
  | "appliance"
  | "decor"
  | "clothing"
  | "other";

export type ValueSource = "web_lookup" | "user_input" | "unknown";

export interface InventoryItem {
  item_id: string;
  name: string;
  category: ItemCategory;
  description: string;
  damage_observed: string;
  confidence: number;
  source_frame_ids: string[];
  source_narration_ids: string[];
  first_seen_sec: number;
  last_seen_sec: number;
  brand_recognized: boolean;
  estimated_value: number | null;
  value_source: ValueSource;
  proof_attached: boolean;
  policy_citations: string[];
  /** Optional inline thumbnail; backend support lands in commit 9. */
  thumbnail_base64?: string;
}

export interface PolicySection {
  section_id: string;
  title: string;
  text: string;
  /** Backend currently leaks embeddings via dataclasses.asdict — frontend ignores. */
  embedding?: number[] | null;
}

export interface ClaimPacketJSON {
  claim_id: string;
  incident_summary: string;
  incident_date: string;
  items: InventoryItem[];
  total_estimated_value: number;
  verified_value: number;
  policy_sections_cited: PolicySection[];
  fnol_letter: string;
  video_source_path: string;
  policy_source_path: string;
  pdf_path: string | null;
  /**
   * Original intake (claimant_name, cause, location, incident_date) the
   * backend persists alongside the packet. Optional because old packets
   * created before this field existed won't have it on disk.
   */
  intake?: IntakePayload;
}

export interface PipelineStatus {
  claim_id: string;
  stage: string;
  percent: number;
  message: string;
}

export interface IntakePayload {
  incident_date: string;
  cause: string;
  location: string;
  claimant_name: string;
}

export interface CreateClaimResponse {
  claim_id: string;
}

export interface RegenerateResponse {
  pdf_url: string;
}

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function readJson(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function extractMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  if (body && typeof body === "object" && "message" in body) {
    const msg = (body as { message?: unknown }).message;
    if (typeof msg === "string") return msg;
  }
  return fallback;
}

// ---------------------------------------------------------------------------
// Endpoint wrappers
// ---------------------------------------------------------------------------

export async function createClaim(
  formData: FormData,
): Promise<CreateClaimResponse> {
  const res = await fetch(`${API_BASE}/claims`, {
    method: "POST",
    body: formData,
  });
  const body = await readJson(res);
  if (!res.ok) {
    throw new ApiError(
      res.status,
      body,
      extractMessage(body, `Failed to create claim (${res.status})`),
    );
  }
  return body as CreateClaimResponse;
}

/**
 * Poll pipeline progress.
 *
 * NOTE: backend returns HTTP 500 for stage="error" but the body is the
 * normal status shape (`{claim_id, stage, percent, message}`). We DO NOT
 * throw on that case — the processing screen needs to render the error
 * inline. We only throw on real network failures and 404s.
 */
export async function getStatus(id: string): Promise<PipelineStatus> {
  const res = await fetch(`${API_BASE}/claims/${id}/status`, {
    cache: "no-store",
  });
  const body = await readJson(res);

  if (res.status === 404) {
    throw new ApiError(404, body, "Claim not found");
  }
  if (!res.ok && res.status !== 500) {
    throw new ApiError(
      res.status,
      body,
      extractMessage(body, `Status check failed (${res.status})`),
    );
  }
  return body as PipelineStatus;
}

export async function getPacket(id: string): Promise<ClaimPacketJSON> {
  const res = await fetch(`${API_BASE}/claims/${id}/packet`, {
    cache: "no-store",
  });
  const body = await readJson(res);
  if (!res.ok) {
    throw new ApiError(
      res.status,
      body,
      extractMessage(body, `Failed to load packet (${res.status})`),
    );
  }
  return body as ClaimPacketJSON;
}

export async function regeneratePacket(
  id: string,
  items: InventoryItem[],
  intake: IntakePayload,
): Promise<RegenerateResponse> {
  const res = await fetch(`${API_BASE}/claims/${id}/regenerate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items, intake }),
  });
  const body = await readJson(res);
  if (!res.ok) {
    throw new ApiError(
      res.status,
      body,
      extractMessage(body, `Failed to regenerate packet (${res.status})`),
    );
  }
  return body as RegenerateResponse;
}

// ---------------------------------------------------------------------------
// URL helpers (no fetch — used directly by <iframe>, <video>, <a download>)
// ---------------------------------------------------------------------------

export function getPdfUrl(id: string): string {
  return `${API_BASE}/claims/${id}/pdf`;
}

export function getVideoUrl(id: string): string {
  return `${API_BASE}/claims/${id}/video`;
}

export function getFrameUrl(id: string, frameId: string): string {
  return `${API_BASE}/claims/${id}/frames/${frameId}`;
}
