"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { VideoOff } from "lucide-react";

import { getVideoUrl, type InventoryItem } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";

export interface VideoPanelHandle {
  seek: (seconds: number) => void;
}

interface VideoPanelProps {
  claimId: string;
  selectedItem: InventoryItem | null;
}

/**
 * Source video panel + timeline-aware caption.
 *
 * Exposes seek(sec) via ref so the inventory table can jump to an
 * item's first_seen_sec when a row is clicked. Auto-detects when the
 * backend video endpoint isn't available and degrades to a typed
 * placeholder (matches the spec's fallback behavior).
 */
export const VideoPanel = forwardRef<VideoPanelHandle, VideoPanelProps>(
  function VideoPanel({ claimId, selectedItem }, ref) {
    const videoRef = useRef<HTMLVideoElement>(null);
    const [currentTime, setCurrentTime] = useState(0);
    const [unavailable, setUnavailable] = useState(false);

    useImperativeHandle(
      ref,
      () => ({
        seek(seconds: number) {
          const v = videoRef.current;
          if (!v || unavailable) return;
          v.currentTime = Math.max(0, seconds);
          v.play().catch(() => {
            /* user-gesture restrictions — ignore */
          });
        },
      }),
      [unavailable],
    );

    // Probe the endpoint once so we can hide the player gracefully
    // if the backend doesn't have the /video route deployed.
    useEffect(() => {
      let cancelled = false;
      fetch(getVideoUrl(claimId), { method: "HEAD" })
        .then((res) => {
          if (cancelled) return;
          if (!res.ok) setUnavailable(true);
        })
        .catch(() => {
          if (!cancelled) setUnavailable(true);
        });
      return () => {
        cancelled = true;
      };
    }, [claimId]);

    if (unavailable) {
      return (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Source video
          </p>
          <div className="mt-3 grid aspect-video w-full place-items-center rounded-xl bg-slate-100 text-slate-400">
            <div className="text-center">
              <VideoOff className="mx-auto h-6 w-6" />
              <p className="mt-2 text-xs">Video unavailable</p>
            </div>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            The walkthrough video isn&rsquo;t served by this backend. Items
            still link to their narration timestamps.
          </p>
        </div>
      );
    }

    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Source video
        </p>

        <video
          ref={videoRef}
          src={getVideoUrl(claimId)}
          controls
          preload="metadata"
          onTimeUpdate={(e) =>
            setCurrentTime((e.currentTarget as HTMLVideoElement).currentTime)
          }
          className="mt-3 aspect-video w-full rounded-xl bg-slate-900"
        />

        <div className="mt-3 flex items-baseline justify-between text-xs">
          <span className="font-mono tabular-nums text-slate-500">
            {formatTimestamp(currentTime)}
          </span>
          {selectedItem ? (
            <span className="truncate text-right text-slate-600">
              <span className="text-slate-400">Now reviewing:</span>{" "}
              <span className="font-medium text-slate-900">
                {selectedItem.name}
              </span>
            </span>
          ) : (
            <span className="text-slate-400">
              Click any row to jump to its moment
            </span>
          )}
        </div>
      </div>
    );
  },
);
