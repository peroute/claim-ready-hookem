"use client";

import { useCallback } from "react";
import { useDropzone, type Accept } from "react-dropzone";
import { UploadCloud, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface DropzoneProps {
  label: string;
  /** Hint shown under the label, e.g. ".mp4, .mov · max 500 MB". */
  hint: string;
  accept: Accept;
  file: File | null;
  onChange: (file: File | null) => void;
  disabled?: boolean;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function Dropzone({
  label,
  hint,
  accept,
  file,
  onChange,
  disabled = false,
}: DropzoneProps) {
  const onDrop = useCallback(
    (accepted: File[]) => {
      if (accepted[0]) onChange(accepted[0]);
    },
    [onChange],
  );

  const { getRootProps, getInputProps, isDragActive, isDragReject } =
    useDropzone({
      accept,
      maxFiles: 1,
      multiple: false,
      disabled: disabled || !!file,
      onDrop,
    });

  return (
    <div>
      <p className="mb-2 text-sm font-medium text-slate-900">{label}</p>

      {file ? (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-900">
              {file.name}
            </p>
            <p className="mt-0.5 text-xs text-slate-500">
              {formatBytes(file.size)}
            </p>
          </div>
          <button
            type="button"
            onClick={() => onChange(null)}
            disabled={disabled}
            aria-label={`Remove ${file.name}`}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-slate-500 transition-colors hover:bg-white hover:text-slate-900 disabled:opacity-50"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div
          {...getRootProps()}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors",
            isDragActive
              ? "border-navy-400 bg-navy-50/60"
              : "border-slate-200 hover:border-slate-300 hover:bg-slate-50",
            isDragReject && "border-red-300 bg-red-50",
            disabled && "pointer-events-none opacity-60",
          )}
        >
          <input {...getInputProps()} />
          <UploadCloud
            className={cn(
              "h-6 w-6",
              isDragActive ? "text-navy-600" : "text-slate-400",
            )}
            strokeWidth={2}
          />
          <p className="mt-3 text-sm font-medium text-slate-700">
            {isDragActive ? "Drop to attach" : "Drag and drop or click"}
          </p>
          <p className="mt-1 text-xs text-slate-500">{hint}</p>
        </div>
      )}
    </div>
  );
}
