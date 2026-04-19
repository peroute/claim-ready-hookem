"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Download,
  Loader2,
} from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  getPacket,
  getPdfUrl,
  type ClaimPacketJSON,
} from "@/lib/api";
import { formatCurrency, shortClaimId } from "@/lib/format";

interface PageProps {
  params: { id: string };
}

export default function PacketPage({ params }: PageProps) {
  const router = useRouter();
  const [packet, setPacket] = useState<ClaimPacketJSON | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const p = await getPacket(params.id);
        if (cancelled) return;
        setPacket(p);
      } catch (err) {
        if (cancelled) return;
        const msg =
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Failed to load packet metadata.";
        setLoadError(msg);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="container flex h-16 items-center justify-between gap-6">
          <Logo />
          <div className="hidden text-sm text-slate-600 md:block">
            <span className="font-medium text-slate-900">
              Claim {shortClaimId(params.id)}
            </span>
            {packet?.incident_date && (
              <>
                <span className="mx-2 text-slate-300">•</span>
                <span>{packet.incident_date}</span>
              </>
            )}
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={() => router.push(`/claim/${params.id}/review`)}
          >
            <ArrowLeft className="h-4 w-4" />
            Back to edit
          </Button>
        </div>
      </header>

      <main className="container max-w-5xl py-12">
        {loadError ? (
          <LoadErrorPanel
            message={loadError}
            onBack={() => router.push(`/claim/${params.id}/review`)}
          />
        ) : !packet ? (
          <LoadingState />
        ) : (
          <>
            <SuccessHeader />

            <StatsRow
              itemCount={packet.items.length}
              estTotal={packet.total_estimated_value}
              verifiedTotal={packet.verified_value}
            />

            <PdfPreview claimId={params.id} />

            <ActionRow claimId={params.id} />

            <p className="mt-12 text-center text-sm text-slate-500">
              Ready to submit? Attach this packet when filing your claim with
              your insurer.
            </p>
          </>
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

function SuccessHeader() {
  return (
    <div className="flex flex-col items-center text-center">
      <span className="grid h-14 w-14 place-items-center rounded-full bg-teal-50 text-teal-600 ring-1 ring-inset ring-teal-100">
        <CheckCircle2 className="h-7 w-7" strokeWidth={2.25} />
      </span>
      <h1 className="mt-6 text-balance text-4xl font-extrabold tracking-tight text-slate-900 md:text-5xl">
        Your claim packet is ready
      </h1>
      <p className="mx-auto mt-4 max-w-xl text-base text-slate-600">
        Review the packet below. You can download it or return to edit items.
      </p>
    </div>
  );
}

function StatsRow({
  itemCount,
  estTotal,
  verifiedTotal,
}: {
  itemCount: number;
  estTotal: number;
  verifiedTotal: number;
}) {
  const stats = [
    { label: "Items documented", value: itemCount.toString() },
    { label: "Total estimated value", value: formatCurrency(estTotal) },
    {
      label: "Verified amount",
      value: formatCurrency(verifiedTotal),
      accent: true,
    },
  ];
  return (
    <dl className="mt-12 grid grid-cols-1 gap-3 sm:grid-cols-3">
      {stats.map((s) => (
        <div
          key={s.label}
          className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card"
        >
          <dt className="text-xs uppercase tracking-wide text-slate-500">
            {s.label}
          </dt>
          <dd
            className={
              s.accent
                ? "mt-1 text-2xl font-bold tabular-nums text-teal-600"
                : "mt-1 text-2xl font-bold tabular-nums text-slate-900"
            }
          >
            {s.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function PdfPreview({ claimId }: { claimId: string }) {
  return (
    <div className="mt-10 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-lg">
      <iframe
        src={getPdfUrl(claimId)}
        title="Claim packet PDF"
        className="aspect-[8.5/11] w-full bg-slate-100"
      />
    </div>
  );
}

function ActionRow({ claimId }: { claimId: string }) {
  return (
    <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
      <Button
        asChild
        size="lg"
        className="h-12 bg-navy-600 px-6 text-base text-white hover:bg-navy-700"
      >
        <a
          href={getPdfUrl(claimId)}
          download={`claim_${shortClaimId(claimId)}.pdf`}
        >
          <Download className="h-4 w-4" />
          Download PDF
        </a>
      </Button>
      <Button
        asChild
        variant="outline"
        size="lg"
        className="h-12 px-6 text-base"
      >
        <Link href={`/claim/${claimId}/review`}>
          <ArrowLeft className="h-4 w-4" />
          Back to edit
        </Link>
      </Button>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <div className="flex items-center gap-3 text-slate-500">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="text-sm">Loading packet…</span>
      </div>
    </div>
  );
}

function LoadErrorPanel({
  message,
  onBack,
}: {
  message: string;
  onBack: () => void;
}) {
  return (
    <div className="mx-auto mt-12 max-w-xl rounded-2xl border border-red-200 bg-red-50 p-6 shadow-card">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
        <div>
          <p className="font-semibold text-red-900">
            Couldn&rsquo;t load packet
          </p>
          <p className="mt-1 break-words text-sm text-red-800">{message}</p>
        </div>
      </div>
      <Button
        type="button"
        variant="outline"
        onClick={onBack}
        className="mt-6 border-red-200 bg-white text-red-700 hover:bg-red-100 hover:text-red-800"
      >
        Back to review
      </Button>
    </div>
  );
}
