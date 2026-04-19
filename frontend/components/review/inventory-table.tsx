"use client";

import { useState } from "react";
import { BadgeCheck, ImageIcon, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DeleteItemDialog } from "@/components/review/delete-item-dialog";
import { formatTimestamp } from "@/lib/format";
import { getFrameUrl, type InventoryItem } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface InventoryTableProps {
  claimId: string;
  items: InventoryItem[];
  selectedItemId: string | null;
  onSelect: (item: InventoryItem) => void;
  onUpdate: (itemId: string, patch: Partial<InventoryItem>) => void;
  onRemove: (itemId: string) => void;
}

export function InventoryTable({
  claimId,
  items,
  selectedItemId,
  onSelect,
  onUpdate,
  onRemove,
}: InventoryTableProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [pendingDelete, setPendingDelete] = useState<InventoryItem | null>(
    null,
  );

  function toggleExpand(itemId: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }

  return (
    <>
      <div className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card">
        <Table className="min-w-[820px]">
          <TableHeader>
            <TableRow className="bg-slate-50 hover:bg-slate-50">
              <TableHead className="w-14 text-xs font-semibold uppercase tracking-wide text-slate-500">
                #
              </TableHead>
              <TableHead className="w-[110px] text-xs font-semibold uppercase tracking-wide text-slate-500">
                Frame
              </TableHead>
              <TableHead className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Item
              </TableHead>
              <TableHead className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Damage
              </TableHead>
              <TableHead className="w-[150px] text-xs font-semibold uppercase tracking-wide text-slate-500">
                Value
              </TableHead>
              <TableHead className="w-[100px] text-center text-xs font-semibold uppercase tracking-wide text-slate-500">
                Receipt
              </TableHead>
              <TableHead className="w-[140px] text-xs font-semibold uppercase tracking-wide text-slate-500">
                Policy
              </TableHead>
              <TableHead className="w-[60px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item, i) => {
              const isSelected = item.item_id === selectedItemId;
              const isExpanded = expanded.has(item.item_id);
              return (
                <TableRow
                  key={item.item_id}
                  onClick={() => onSelect(item)}
                  className={cn(
                    "cursor-pointer border-t border-slate-100 align-top transition-colors",
                    isSelected
                      ? "border-l-2 border-l-teal-500 bg-teal-50/40 hover:bg-teal-50/60"
                      : "hover:bg-slate-50/70",
                  )}
                >
                  <TableCell className="pt-5 text-sm font-medium tabular-nums text-slate-400">
                    {(i + 1).toString().padStart(2, "0")}
                  </TableCell>

                  <TableCell className="py-4">
                    <Thumbnail claimId={claimId} item={item} />
                    <p className="mt-1.5 text-[11px] tabular-nums text-slate-400">
                      {formatTimestamp(item.first_seen_sec)}
                    </p>
                  </TableCell>

                  <TableCell className="py-4">
                    <div className="flex items-start gap-1.5">
                      <p className="font-semibold text-slate-900">
                        {item.name}
                      </p>
                      {item.brand_recognized && (
                        <BadgeCheck
                          className="mt-0.5 h-4 w-4 shrink-0 text-teal-500"
                          aria-label="Brand recognized"
                        />
                      )}
                    </div>
                    <Badge
                      variant="secondary"
                      className="mt-1.5 bg-slate-100 font-medium capitalize text-slate-700 hover:bg-slate-100"
                    >
                      {item.category}
                    </Badge>
                  </TableCell>

                  <TableCell
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleExpand(item.item_id);
                    }}
                    className="max-w-xs cursor-text py-4 text-sm text-slate-600"
                  >
                    {item.damage_observed ? (
                      <p className={cn(!isExpanded && "line-clamp-2")}>
                        {item.damage_observed}
                      </p>
                    ) : (
                      <p className="italic text-slate-400">No damage noted</p>
                    )}
                    {item.damage_observed &&
                      item.damage_observed.length > 100 && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleExpand(item.item_id);
                          }}
                          className="mt-1 text-xs font-medium text-navy-600 hover:underline"
                        >
                          {isExpanded ? "Show less" : "Show more"}
                        </button>
                      )}
                  </TableCell>

                  <TableCell
                    onClick={(e) => e.stopPropagation()}
                    className="py-4"
                  >
                    <ValueInput
                      value={item.estimated_value}
                      onChange={(v) =>
                        onUpdate(item.item_id, {
                          estimated_value: v,
                          value_source: v == null ? "unknown" : "user_input",
                        })
                      }
                    />
                  </TableCell>

                  <TableCell
                    onClick={(e) => e.stopPropagation()}
                    className="py-4 text-center"
                  >
                    <div className="inline-flex">
                      <Checkbox
                        checked={item.proof_attached}
                        onCheckedChange={(v) =>
                          onUpdate(item.item_id, {
                            proof_attached: v === true,
                          })
                        }
                        aria-label={`Mark receipt for ${item.name}`}
                      />
                    </div>
                  </TableCell>

                  <TableCell className="py-4 text-xs text-slate-500">
                    {item.policy_citations.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {item.policy_citations.map((sid) => (
                          <span
                            key={sid}
                            className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600"
                          >
                            §{sid}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="italic text-slate-400">none</span>
                    )}
                  </TableCell>

                  <TableCell
                    onClick={(e) => e.stopPropagation()}
                    className="py-4"
                  >
                    <button
                      type="button"
                      onClick={() => setPendingDelete(item)}
                      aria-label={`Remove ${item.name}`}
                      className="grid h-8 w-8 place-items-center rounded-lg text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <DeleteItemDialog
        open={pendingDelete !== null}
        itemName={pendingDelete?.name ?? null}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) onRemove(pendingDelete.item_id);
          setPendingDelete(null);
        }}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Cell subcomponents
// ---------------------------------------------------------------------------

function ValueInput({
  value,
  onChange,
}: {
  value: number | null;
  onChange: (v: number | null) => void;
}) {
  // Local string state lets the user type "1" before "12" without React
  // truncating to 1 mid-keystroke. We coerce on every change.
  const display = value == null || Number.isNaN(value) ? "" : String(value);

  function handle(e: React.ChangeEvent<HTMLInputElement>) {
    const raw = e.target.value;
    if (raw === "") {
      onChange(null);
      return;
    }
    const parsed = Number(raw);
    if (Number.isNaN(parsed) || parsed < 0) return;
    onChange(parsed);
  }

  return (
    <div className="relative">
      <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-slate-500">
        $
      </span>
      <Input
        type="number"
        inputMode="decimal"
        min="0"
        step="0.01"
        value={display}
        onChange={handle}
        placeholder="0.00"
        className="h-9 pl-7 tabular-nums"
      />
    </div>
  );
}

function Thumbnail({ claimId, item }: { claimId: string; item: InventoryItem }) {
  // Pick the middle source frame — same heuristic the PDF template uses.
  const frameId =
    item.source_frame_ids.length > 0
      ? item.source_frame_ids[Math.floor(item.source_frame_ids.length / 2)]
      : null;

  const [errored, setErrored] = useState(false);

  if (frameId && !errored) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={getFrameUrl(claimId, frameId)}
        alt={item.name}
        loading="lazy"
        onError={() => setErrored(true)}
        className="h-[60px] w-20 rounded-lg object-cover ring-1 ring-slate-200"
      />
    );
  }
  return (
    <div className="grid h-[60px] w-20 place-items-center rounded-lg bg-slate-100 text-slate-400 ring-1 ring-slate-200">
      <ImageIcon className="h-5 w-5" />
    </div>
  );
}
