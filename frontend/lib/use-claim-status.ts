"use client";

import { useEffect, useState } from "react";
import { ApiError, getStatus, type PipelineStatus } from "@/lib/api";

interface UseClaimStatusResult {
  status: PipelineStatus | null;
  error: string | null;
}

/**
 * Polls /claims/{id}/status every 2s until the pipeline reaches a
 * terminal stage ("complete" or "error"). Backs off to 4s on transient
 * fetch failures so a flapping network doesn't spin the loop.
 */
export function useClaimStatus(id: string): UseClaimStatusResult {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function tick() {
      try {
        const s = await getStatus(id);
        if (cancelled) return;
        setStatus(s);
        setError(null);
        if (s.stage !== "complete" && s.stage !== "error") {
          timer = setTimeout(tick, 2000);
        }
      } catch (err) {
        if (cancelled) return;
        const msg =
          err instanceof ApiError && err.status === 404
            ? "Claim not found. The server may have restarted."
            : err instanceof Error
              ? err.message
              : "Status check failed";
        setError(msg);
        timer = setTimeout(tick, 4000);
      }
    }

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [id]);

  return { status, error };
}
