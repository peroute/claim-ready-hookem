/**
 * Persists the upload-time intake (claimant name, cause, location, date)
 * in localStorage so the review screen can replay it to the regenerate
 * endpoint. The backend's POST /claims/{id}/regenerate requires the
 * full intake dict, but the packet JSON only carries `incident_date`.
 *
 * Keyed per claim_id. Falls back gracefully when localStorage is
 * unavailable (SSR, private mode).
 */

import type { IntakePayload } from "@/lib/api";

const PREFIX = "claim-ready:intake:";

export function saveIntake(claimId: string, intake: IntakePayload): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(PREFIX + claimId, JSON.stringify(intake));
  } catch {
    // Storage quota or disabled — silently degrade.
  }
}

export function loadIntake(claimId: string): IntakePayload | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(PREFIX + claimId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as IntakePayload;
    if (
      typeof parsed?.incident_date === "string" &&
      typeof parsed?.cause === "string" &&
      typeof parsed?.location === "string" &&
      typeof parsed?.claimant_name === "string"
    ) {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Best-effort fallback when the original intake isn't in storage
 * (user opened the review URL on a different machine, cleared storage,
 * etc.). Keeps the regenerate endpoint happy with sane defaults.
 */
export function fallbackIntake(incidentDate: string): IntakePayload {
  return {
    incident_date: incidentDate || "Unspecified",
    cause: "Unspecified",
    location: "Unspecified",
    claimant_name: "Policyholder",
  };
}
