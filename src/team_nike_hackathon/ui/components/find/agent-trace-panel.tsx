import { Sparkles, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ParsedQueryOut } from "@/lib/api";

interface AgentTracePanelProps {
  parsedQuery: ParsedQueryOut | null | undefined;
  loading: boolean;
  className?: string;
}

/**
 * One-liner showing the LLM's interpretation of the query so the
 * coordinator can see what the agent "heard" without surfacing the full
 * chain-of-thought (which is debugger-only).
 */
export function AgentTracePanel({
  parsedQuery,
  loading,
  className,
}: AgentTracePanelProps) {
  if (loading) {
    return (
      <div
        className={cn(
          "flex items-center gap-2 border-b bg-card/40 px-5 py-2.5 text-[11px] text-muted-foreground backdrop-blur",
          className,
        )}
      >
        <Loader2 className="size-3 animate-spin text-[color:var(--brand-coral)]" />
        Interpreting query…
      </div>
    );
  }

  if (!parsedQuery) return null;
  const chips: { label: string; value: string }[] = [];
  if (parsedQuery.capability_text)
    chips.push({ label: "need", value: parsedQuery.capability_text });
  if (parsedQuery.location_text)
    chips.push({ label: "near", value: parsedQuery.location_text });
  if (parsedQuery.urgency && parsedQuery.urgency !== "routine")
    chips.push({ label: "urgency", value: parsedQuery.urgency });
  if (parsedQuery.language && parsedQuery.language !== "en")
    chips.push({ label: "lang", value: parsedQuery.language });
  if (chips.length === 0) return null;

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-1.5 border-b bg-card/40 px-5 py-2.5 backdrop-blur",
        className,
      )}
    >
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        <Sparkles className="size-3 text-[color:var(--brand-coral)]" />
        Heard
      </span>
      {chips.map((c) => (
        <span
          key={c.label}
          className="inline-flex items-center gap-1 rounded-full border bg-background/40 px-2 py-0.5 text-[10px] capitalize text-foreground/80"
        >
          <span className="text-muted-foreground">{c.label}:</span>
          <span className="font-medium">{c.value}</span>
        </span>
      ))}
    </div>
  );
}

/**
 * Compact pill for a single facility's LLM trust signal. Rendered inside
 * the ranked-list row when ``trust_signal`` is set.
 */
export function TrustSignalChip({
  signal,
  compact = true,
}: {
  signal: string | null | undefined;
  compact?: boolean;
}) {
  if (!signal) return null;
  const style = TRUST_STYLE[signal] ?? TRUST_STYLE.no_evidence;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium uppercase tracking-wider",
        compact ? "text-[9px]" : "text-[10px]",
      )}
      style={{
        background: style.bg,
        color: style.fg,
        borderColor: style.border,
      }}
      title={style.title}
    >
      <span
        className="size-1.5 rounded-full"
        style={{ background: style.dot }}
      />
      {style.label}
    </span>
  );
}

const TRUST_STYLE: Record<
  string,
  { label: string; title: string; bg: string; fg: string; border: string; dot: string }
> = {
  strong_evidence: {
    label: "Strong",
    title: "Multiple structured signals corroborate the claim",
    bg: "color-mix(in oklab, var(--brand-teal) 15%, transparent)",
    fg: "var(--brand-teal)",
    border: "color-mix(in oklab, var(--brand-teal) 40%, transparent)",
    dot: "var(--brand-teal)",
  },
  partial_evidence: {
    label: "Partial",
    title: "Single source mentions the capability",
    bg: "color-mix(in oklab, var(--brand-navy) 12%, transparent)",
    fg: "var(--brand-navy)",
    border: "color-mix(in oklab, var(--brand-navy) 35%, transparent)",
    dot: "var(--brand-navy)",
  },
  weak_evidence: {
    label: "Weak",
    title: "Only free-text mention; verify directly",
    bg: "color-mix(in oklab, var(--muted-foreground) 12%, transparent)",
    fg: "var(--muted-foreground)",
    border: "color-mix(in oklab, var(--muted-foreground) 30%, transparent)",
    dot: "var(--muted-foreground)",
  },
  suspicious: {
    label: "Suspicious",
    title: "Conflicting signals (e.g. clinic claiming ICU)",
    bg: "color-mix(in oklab, var(--brand-coral) 15%, transparent)",
    fg: "var(--brand-coral)",
    border: "color-mix(in oklab, var(--brand-coral) 40%, transparent)",
    dot: "var(--brand-coral)",
  },
  no_evidence: {
    label: "None",
    title: "No evidence found for the requested capability",
    bg: "color-mix(in oklab, var(--muted-foreground) 8%, transparent)",
    fg: "var(--muted-foreground)",
    border: "color-mix(in oklab, var(--muted-foreground) 20%, transparent)",
    dot: "var(--muted-foreground)",
  },
};
