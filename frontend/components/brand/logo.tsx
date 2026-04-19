import { Shield } from "lucide-react";
import { cn } from "@/lib/utils";

interface LogoProps {
  className?: string;
  /** Hide the wordmark and show only the icon. */
  iconOnly?: boolean;
}

/**
 * Brand mark — navy shield + "Claim-ready" wordmark.
 * Single source of truth so every header reads identically.
 */
export function Logo({ className, iconOnly = false }: LogoProps) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-navy-600 text-white shadow-sm">
        <Shield className="h-4 w-4" strokeWidth={2.5} />
      </span>
      {!iconOnly && (
        <span className="text-base font-bold tracking-tight text-navy-700">
          Claim-ready
        </span>
      )}
    </div>
  );
}
