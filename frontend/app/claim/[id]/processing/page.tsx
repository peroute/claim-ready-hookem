"use client";

import { useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2,
  Circle,
  Loader2,
  XCircle,
} from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { useClaimStatus } from "@/lib/use-claim-status";
import { cn } from "@/lib/utils";

interface PageProps {
  params: { id: string };
}

const STAGES = [
  { key: "ingesting_video", label: "Extracting frames and transcribing audio" },
  { key: "ingesting_policy", label: "Parsing policy document" },
  { key: "building_index", label: "Indexing for semantic search" },
  { key: "detecting_inventory", label: "Detecting damaged items" },
  { key: "searching_policy", label: "Matching policy coverage" },
  { key: "generating_packet", label: "Rendering claim packet" },
] as const;

type StageStatus = "done" | "current" | "pending" | "error";

function stageStatus(
  index: number,
  currentIndex: number,
  isComplete: boolean,
  isError: boolean,
): StageStatus {
  if (isComplete) return "done";
  if (isError) {
    if (index < currentIndex) return "done";
    if (index === currentIndex) return "error";
    return "pending";
  }
  if (index < currentIndex) return "done";
  if (index === currentIndex) return "current";
  return "pending";
}

export default function ProcessingPage({ params }: PageProps) {
  const router = useRouter();
  const { status, error } = useClaimStatus(params.id);

  const stage = status?.stage ?? "queued";
  const percent = Math.max(0, Math.min(100, status?.percent ?? 0));
  const isError = stage === "error";
  const isComplete = stage === "complete";
  const errorMessage = status?.message ?? error ?? null;

  const currentIndex = useMemo(() => {
    const idx = STAGES.findIndex((s) => s.key === stage);
    if (idx === -1) {
      // Stage we don't know about (queued, complete, error) — derive from %.
      if (percent >= 90) return STAGES.length - 1;
      if (percent <= 0) return 0;
      const ratio = percent / 100;
      return Math.min(STAGES.length - 1, Math.floor(ratio * STAGES.length));
    }
    return idx;
  }, [stage, percent]);

  // Auto-advance to review on completion. Tiny delay so the user sees 100%.
  useEffect(() => {
    if (!isComplete) return;
    const t = setTimeout(() => {
      router.push(`/claim/${params.id}/review`);
    }, 600);
    return () => clearTimeout(t);
  }, [isComplete, params.id, router]);

  return (
    <div className="min-h-screen">
      <header className="container flex items-center py-6">
        <Logo />
      </header>

      <main className="container flex justify-center pb-24 pt-8">
        <div className="w-full max-w-2xl">
          <div className="text-center">
            <h1 className="text-balance text-4xl font-extrabold tracking-tight text-slate-900 md:text-5xl">
              Processing your claim
            </h1>
            <p className="mx-auto mt-4 max-w-lg text-base text-slate-600">
              This usually takes 2–3 minutes. We&rsquo;re analyzing your video,
              matching coverage, and generating your packet.
            </p>
          </div>

          {isError ? (
            <ErrorPanel
              message={errorMessage ?? "An unknown error occurred."}
              onRetry={() => router.push("/")}
            />
          ) : (
            <>
              <ProgressBlock
                percent={percent}
                message={
                  status?.message ??
                  (error ? "Reconnecting to server…" : "Queued…")
                }
              />

              <ol className="mt-12 space-y-1 rounded-2xl border border-slate-200 bg-white p-3 shadow-card">
                {STAGES.map((s, i) => (
                  <StageRow
                    key={s.key}
                    label={s.label}
                    status={stageStatus(i, currentIndex, isComplete, false)}
                  />
                ))}
              </ol>

              {error && !isError && (
                <p className="mt-4 text-center text-xs text-slate-500">
                  Last status check failed — retrying automatically.
                </p>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

function ProgressBlock({
  percent,
  message,
}: {
  percent: number;
  message: string;
}) {
  return (
    <div className="mt-12">
      <div className="flex items-baseline justify-between">
        <p className="text-sm font-medium text-slate-700">{message}</p>
        <p className="text-sm font-semibold tabular-nums text-navy-700">
          {Math.round(percent)}%
        </p>
      </div>
      <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-navy-600 transition-[width] duration-700 ease-out"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function StageRow({
  label,
  status,
}: {
  label: string;
  status: StageStatus;
}) {
  return (
    <li
      className={cn(
        "flex items-center gap-3 rounded-xl px-4 py-3 transition-colors",
        status === "current" && "bg-navy-50/60",
        status === "error" && "bg-red-50",
      )}
    >
      <StageIcon status={status} />
      <span
        className={cn(
          "text-sm",
          status === "done" && "text-slate-700",
          status === "current" && "font-medium text-slate-900",
          status === "pending" && "text-slate-400",
          status === "error" && "font-medium text-red-700",
        )}
      >
        {label}
      </span>
    </li>
  );
}

function StageIcon({ status }: { status: StageStatus }) {
  if (status === "done") {
    return <CheckCircle2 className="h-5 w-5 shrink-0 text-teal-500" />;
  }
  if (status === "current") {
    return (
      <Loader2 className="h-5 w-5 shrink-0 animate-spin text-navy-600" />
    );
  }
  if (status === "error") {
    return <XCircle className="h-5 w-5 shrink-0 text-red-500" />;
  }
  return <Circle className="h-5 w-5 shrink-0 text-slate-300" />;
}

function ErrorPanel({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="mt-12 rounded-2xl border border-red-200 bg-red-50 p-6 shadow-card">
      <div className="flex items-start gap-3">
        <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-red-900">Pipeline failed</p>
          <p className="mt-1 break-words text-sm text-red-800">{message}</p>
        </div>
      </div>
      <Button
        type="button"
        variant="outline"
        onClick={onRetry}
        className="mt-6 border-red-200 bg-white text-red-700 hover:bg-red-100 hover:text-red-800"
      >
        Try again
      </Button>
    </div>
  );
}
