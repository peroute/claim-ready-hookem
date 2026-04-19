/**
 * Tiny formatting helpers shared across review/packet screens.
 * Kept currency/timestamp logic in one place so number rendering
 * stays consistent.
 */

export function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatTimestamp(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

export function shortClaimId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

export function sumValues(
  items: Array<{ estimated_value: number | null; proof_attached: boolean }>,
  opts: { verifiedOnly?: boolean } = {},
): number {
  return items.reduce((acc, it) => {
    if (it.estimated_value == null) return acc;
    if (opts.verifiedOnly && !it.proof_attached) return acc;
    return acc + it.estimated_value;
  }, 0);
}
