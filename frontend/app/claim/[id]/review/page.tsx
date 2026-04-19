"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  ArrowRight,
  Loader2,
  Receipt,
} from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { InventoryTable } from "@/components/review/inventory-table";
import {
  VideoPanel,
  type VideoPanelHandle,
} from "@/components/review/video-panel";
import {
  ApiError,
  getPacket,
  regeneratePacket,
  type ClaimPacketJSON,
  type InventoryItem,
} from "@/lib/api";
import { formatCurrency, shortClaimId, sumValues } from "@/lib/format";
import { fallbackIntake, loadIntake } from "@/lib/intake-storage";

interface PageProps {
  params: { id: string };
}

export default function ReviewPage({ params }: PageProps) {
  const router = useRouter();
  const [packet, setPacket] = useState<ClaimPacketJSON | null>(null);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const videoRef = useRef<VideoPanelHandle>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const p = await getPacket(params.id);
        if (cancelled) return;
        setPacket(p);
        setItems(p.items);
        if (p.items.length > 0) setSelectedItemId(p.items[0].item_id);
      } catch (err) {
        if (cancelled) return;
        const msg =
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Failed to load claim packet.";
        setLoadError(msg);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  // ---- mutations -----------------------------------------------------------

  function updateItem(itemId: string, patch: Partial<InventoryItem>) {
    setItems((prev) =>
      prev.map((it) => (it.item_id === itemId ? { ...it, ...patch } : it)),
    );
  }

  function removeItem(itemId: string) {
    setItems((prev) => prev.filter((it) => it.item_id !== itemId));
    setSelectedItemId((prev) => (prev === itemId ? null : prev));
  }

  function selectItem(item: InventoryItem) {
    setSelectedItemId(item.item_id);
    videoRef.current?.seek(item.first_seen_sec);
  }

  // ---- submit --------------------------------------------------------------

  async function handleRegenerate() {
    if (!packet || submitting) return;
    setSubmitting(true);
    setSubmitError(null);

    // Prefer the server-side intake (persisted on upload); fall back to
    // the localStorage stash, then to a minimal placeholder so the
    // backend's required-fields check still passes.
    const intake =
      packet.intake ??
      loadIntake(params.id) ??
      fallbackIntake(packet.incident_date);

    try {
      await regeneratePacket(params.id, items, intake);
      router.push(`/claim/${params.id}/packet`);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to regenerate packet.";
      setSubmitError(msg);
      setSubmitting(false);
    }
  }

  // ---- derived stats -------------------------------------------------------

  const receiptCount = items.filter((i) => i.proof_attached).length;
  const estTotal = sumValues(items);
  const verifiedTotal = sumValues(items, { verifiedOnly: true });

  return (
    <div className="min-h-screen">
      <ReviewHeader
        claimId={params.id}
        incidentDate={packet?.incident_date}
        canSubmit={!!packet && !submitting}
        submitting={submitting}
        onSubmit={handleRegenerate}
      />

      <main className="container py-10">
        {loadError ? (
          <LoadErrorPanel
            message={loadError}
            onRetry={() => router.push("/")}
          />
        ) : !packet ? (
          <LoadingState />
        ) : (
          <div className="grid gap-8 lg:grid-cols-[2fr_1fr]">
            <section>
              <header>
                <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">
                  Review detected items
                </h1>
                <p className="mt-2 max-w-2xl text-slate-600">
                  Delete duplicates, fill in values, and mark which items you
                  have receipts for. The final packet regenerates from your
                  edits.
                </p>
              </header>

              <SummaryStats
                itemCount={items.length}
                receiptCount={receiptCount}
                estTotal={estTotal}
                verifiedTotal={verifiedTotal}
              />

              {items.length === 0 ? (
                <EmptyState />
              ) : (
                <InventoryTable
                  claimId={params.id}
                  items={items}
                  selectedItemId={selectedItemId}
                  onSelect={selectItem}
                  onUpdate={updateItem}
                  onRemove={removeItem}
                />
              )}

              {submitError && (
                <p
                  role="alert"
                  className="mt-6 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
                >
                  {submitError}
                </p>
              )}
            </section>

            <aside className="lg:sticky lg:top-24 lg:h-fit">
              <VideoPanel
                ref={videoRef}
                claimId={params.id}
                selectedItem={
                  items.find((i) => i.item_id === selectedItemId) ?? null
                }
              />
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header bar
// ---------------------------------------------------------------------------

function ReviewHeader({
  claimId,
  incidentDate,
  canSubmit,
  submitting,
  onSubmit,
}: {
  claimId: string;
  incidentDate: string | undefined;
  canSubmit: boolean;
  submitting: boolean;
  onSubmit: () => void;
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="container flex h-16 items-center justify-between gap-6">
        <Logo />
        <div className="hidden text-sm text-slate-600 md:block">
          <span className="font-medium text-slate-900">
            Claim {shortClaimId(claimId)}
          </span>
          {incidentDate && (
            <>
              <span className="mx-2 text-slate-300">•</span>
              <span>{incidentDate}</span>
            </>
          )}
        </div>
        <Button
          type="button"
          onClick={onSubmit}
          disabled={!canSubmit}
          className="bg-navy-600 text-white hover:bg-navy-700 disabled:bg-navy-600/40"
        >
          {submitting ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Regenerating…
            </>
          ) : (
            <>
              Generate final packet
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </Button>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Summary stats
// ---------------------------------------------------------------------------

function SummaryStats({
  itemCount,
  receiptCount,
  estTotal,
  verifiedTotal,
}: {
  itemCount: number;
  receiptCount: number;
  estTotal: number;
  verifiedTotal: number;
}) {
  const stats = [
    {
      label: itemCount === 1 ? "item detected" : "items detected",
      value: itemCount.toString(),
    },
    { label: "with receipts", value: receiptCount.toString() },
    { label: "Est. total", value: formatCurrency(estTotal) },
    { label: "Verified", value: formatCurrency(verifiedTotal), accent: true },
  ];
  return (
    <dl className="mt-8 grid grid-cols-2 gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-card md:grid-cols-4">
      {stats.map((s) => (
        <div key={s.label} className="px-3 py-2">
          <dt className="text-xs uppercase tracking-wide text-slate-500">
            {s.label}
          </dt>
          <dd
            className={
              s.accent
                ? "mt-1 text-xl font-bold tabular-nums text-teal-600"
                : "mt-1 text-xl font-bold tabular-nums text-slate-900"
            }
          >
            {s.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

// ---------------------------------------------------------------------------
// Empty / loading / error / video placeholder
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="mt-6 flex flex-col items-center rounded-2xl border border-dashed border-slate-200 bg-white px-6 py-16 text-center">
      <Receipt className="h-8 w-8 text-slate-300" />
      <p className="mt-4 font-semibold text-slate-900">No items detected</p>
      <p className="mt-1 max-w-sm text-sm text-slate-600">
        This usually means the video had no clear narration of damaged items.
        You can still generate a packet, or upload a new video.
      </p>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <div className="flex items-center gap-3 text-slate-500">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="text-sm">Loading claim packet…</span>
      </div>
    </div>
  );
}

function LoadErrorPanel({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="mx-auto mt-12 max-w-xl rounded-2xl border border-red-200 bg-red-50 p-6 shadow-card">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
        <div>
          <p className="font-semibold text-red-900">
            Couldn&rsquo;t load claim
          </p>
          <p className="mt-1 break-words text-sm text-red-800">{message}</p>
        </div>
      </div>
      <Button
        type="button"
        variant="outline"
        onClick={onRetry}
        className="mt-6 border-red-200 bg-white text-red-700 hover:bg-red-100 hover:text-red-800"
      >
        Back to upload
      </Button>
    </div>
  );
}
