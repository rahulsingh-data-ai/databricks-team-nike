import { ConfidenceBadge, bandFor } from "@/components/find/confidence-badge";
import { TrustSignalChip } from "@/components/find/agent-trace-panel";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { SearchResultItem } from "@/lib/api";
import { AnimatePresence, motion } from "motion/react";
import { Building2, Loader2, MapPin, Quote } from "lucide-react";

interface RankedListProps {
  results: SearchResultItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onViewEvidence: (item: SearchResultItem) => void;
  className?: string;
  origin?: { label?: string | null; lat?: number | null; lng?: number | null };
  loading?: boolean;
}

export function RankedList({
  results,
  selectedId,
  onSelect,
  onViewEvidence,
  className,
  origin,
  loading,
}: RankedListProps) {
  return (
    <div
      className={cn(
        "flex h-full w-full flex-col border-l bg-card/40 backdrop-blur",
        className
      )}
    >
      <header className="relative border-b px-5 py-4">
        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Ranked shortlist
        </div>
        <div className="mt-1 flex items-baseline justify-between gap-3">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
            {loading ? (
              <>
                <Loader2 className="size-4 animate-spin text-[color:var(--brand-coral)]" />
                <span>Searching…</span>
              </>
            ) : (
              <span>
                {results.length} facilit{results.length === 1 ? "y" : "ies"}
              </span>
            )}
          </h2>
          {origin?.label && (
            <span className="truncate text-xs text-muted-foreground">
              near {origin.label}
            </span>
          )}
        </div>
        {loading && (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 block h-0.5 overflow-hidden"
          >
            <span className="block h-full w-1/3 animate-[indeterminate_1.2s_ease-in-out_infinite] bg-[color:var(--brand-coral)]" />
          </span>
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {loading && results.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 py-12 text-center">
            <Loader2 className="size-6 animate-spin text-[color:var(--brand-coral)]" />
            <p className="text-sm font-medium text-foreground">
              Searching for facilities…
            </p>
            <p className="text-xs text-muted-foreground">
              Parsing your query and ranking matches.
            </p>
            <SkeletonRow />
          </div>
        )}
        {!loading && results.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-6 py-12 text-center text-sm text-muted-foreground">
            <Building2 className="size-6 opacity-50" />
            <p>No matches yet.</p>
            <p className="text-xs">
              Try widening the radius or lowering the minimum confidence.
            </p>
          </div>
        )}

        <AnimatePresence initial={false}>
          {results.map((item, idx) => {
            const active = item.facility.id === selectedId;
            const band = bandFor(item.top_evidence?.confidence ?? avgConf(item));
            return (
              <motion.button
                key={item.facility.id}
                type="button"
                layout
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.18, delay: idx < 8 ? idx * 0.02 : 0 }}
                onClick={() => onSelect(item.facility.id)}
                className={cn(
                  "group mb-2 block w-full rounded-xl border bg-background/40 px-4 py-3 text-left transition-colors",
                  active
                    ? "border-[color:var(--brand-coral)] bg-[color:var(--brand-coral)]/5 shadow-md"
                    : "hover:border-border hover:bg-background/70"
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="grid size-6 shrink-0 place-items-center rounded-md bg-[color:var(--brand-navy)] text-[11px] font-bold text-white">
                        {idx + 1}
                      </span>
                      <h3 className="truncate text-sm font-semibold text-foreground">
                        {item.facility.name}
                      </h3>
                    </div>

                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                      {item.facility.type && (
                        <span className="capitalize">{item.facility.type}</span>
                      )}
                      {item.facility.city && (
                        <span className="inline-flex items-center gap-1">
                          <MapPin className="size-3" />
                          {item.facility.city}
                          {item.facility.state ? `, ${item.facility.state}` : ""}
                        </span>
                      )}
                      {typeof item.distance_km === "number" && (
                        <span className="tabular-nums">
                          {item.distance_km < 1
                            ? `${Math.round(item.distance_km * 1000)} m`
                            : `${item.distance_km.toFixed(1)} km`}{" "}
                          away
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-col items-end gap-1">
                    <ConfidenceBadge
                      value={item.top_evidence?.confidence ?? avgConf(item)}
                      compact
                    />
                    {item.trust_signal && (
                      <TrustSignalChip signal={item.trust_signal} />
                    )}
                  </div>
                </div>

                {item.top_evidence?.snippet && (
                  <p className="mt-2 flex items-start gap-1.5 text-[12px] italic text-muted-foreground">
                    <Quote className="mt-0.5 size-3 shrink-0 opacity-60" />
                    <span className="line-clamp-2">{item.top_evidence.snippet}</span>
                  </p>
                )}

                <div className="mt-2 flex items-center justify-between gap-2">
                  <SpecialtyChips specialties={item.facility.specialties ?? null} />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-[11px] text-[color:var(--brand-coral)] hover:bg-[color:var(--brand-coral)]/10 hover:text-[color:var(--brand-coral)]"
                    onClick={(e) => {
                      e.stopPropagation();
                      onViewEvidence(item);
                    }}
                  >
                    View evidence
                  </Button>
                </div>

                {/* hairline band indicator */}
                <div
                  className="mt-3 h-0.5 w-full rounded-full"
                  style={{
                    background:
                      band === "verified"
                        ? "var(--brand-teal)"
                        : band === "likely"
                        ? "var(--brand-navy)"
                        : "var(--brand-coral)",
                    opacity: 0.45,
                  }}
                />
              </motion.button>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}

function avgConf(item: SearchResultItem): number {
  const c = item.facility.confidence;
  if (!c) return 0.5;
  const vals = Object.values(c).filter((v): v is number => typeof v === "number");
  if (!vals.length) return 0.5;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function SpecialtyChips({ specialties }: { specialties: string[] | null }) {
  if (!specialties || specialties.length === 0) return <span />;
  const top = specialties.slice(0, 2);
  const extra = specialties.length - top.length;
  return (
    <div className="flex flex-wrap gap-1">
      {top.map((s) => (
        <span
          key={s}
          className="rounded-full border border-border bg-background/40 px-2 py-0.5 text-[10px] capitalize text-muted-foreground"
        >
          {s}
        </span>
      ))}
      {extra > 0 && (
        <span className="rounded-full border border-border bg-background/40 px-2 py-0.5 text-[10px] text-muted-foreground">
          +{extra}
        </span>
      )}
    </div>
  );
}

function SkeletonRow() {
  return (
    <div className="mt-2 w-full space-y-2">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="h-20 w-full animate-pulse rounded-xl border bg-background/30"
        />
      ))}
    </div>
  );
}
