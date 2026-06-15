import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { CheckCircle2, ShieldAlert, ShieldQuestion } from "lucide-react";

export type ConfidenceBand = "verified" | "likely" | "unverified";

export function bandFor(value: number | null | undefined): ConfidenceBand {
  const v = typeof value === "number" ? value : 0;
  if (v >= 0.8) return "verified";
  if (v >= 0.6) return "likely";
  return "unverified";
}

/** The brand colour for each confidence band — used by map markers too. */
export const BAND_COLOR: Record<ConfidenceBand, string> = {
  verified: "var(--brand-teal)",
  likely: "var(--brand-navy)",
  unverified: "var(--brand-coral)",
};

const COPY: Record<
  ConfidenceBand,
  { label: string; tooltip: string; classes: string; Icon: React.ComponentType<{ className?: string }> }
> = {
  verified: {
    label: "Verified",
    tooltip: "Confirmed against multiple structured sources.",
    classes:
      "bg-[color:var(--brand-teal)]/15 text-[color:var(--brand-teal)] border-[color:var(--brand-teal)]/30",
    Icon: CheckCircle2,
  },
  likely: {
    label: "Likely",
    tooltip:
      "Stated in the facility's record but not independently verified. Treat as a strong lead.",
    classes:
      "bg-[color:var(--brand-navy)]/15 text-[color:var(--brand-navy)] border-[color:var(--brand-navy)]/30 dark:text-white dark:bg-white/10 dark:border-white/20",
    Icon: ShieldQuestion,
  },
  unverified: {
    label: "Unverified — claim only",
    tooltip:
      "This service was extracted from the facility's free-text description. We have not confirmed it. Open the evidence drawer for the source quote.",
    classes:
      "border-[color:var(--brand-coral)]/50 text-[color:var(--brand-coral)] bg-transparent",
    Icon: ShieldAlert,
  },
};

export interface ConfidenceBadgeProps {
  value: number | null | undefined;
  /** Show just the icon (compact, for list rows). */
  compact?: boolean;
  className?: string;
}

export function ConfidenceBadge({ value, compact, className }: ConfidenceBadgeProps) {
  const band = bandFor(value);
  const c = COPY[band];
  const Icon = c.Icon;
  // Compact (list rows): drop the % number so the per-claim confidence
  // doesn't get read as a rank score. Color + tooltip carry the signal;
  // the precise number lives in the evidence drawer.
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider",
              c.classes,
              className
            )}
          >
            <Icon className="size-3" />
            {!compact && <span>{c.label}</span>}
            {!compact && typeof value === "number" && (
              <span className="font-mono opacity-70">
                {Math.round(value * 100)}%
              </span>
            )}
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs text-xs">
          {c.tooltip}
          {typeof value === "number" && (
            <span className="ml-1 font-mono opacity-80">
              ({Math.round(value * 100)}%)
            </span>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
