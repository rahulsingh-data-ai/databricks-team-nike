import { ConfidenceBadge } from "@/components/find/confidence-badge";
import { TrustSignalChip } from "@/components/find/agent-trace-panel";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import type { SearchResultItem } from "@/lib/api";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, Flag, MapPin } from "lucide-react";
import { Fragment, useMemo } from "react";

interface EvidenceDrawerProps {
  item: SearchResultItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function EvidenceDrawer({ item, open, onOpenChange }: EvidenceDrawerProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full overflow-y-auto p-0 sm:max-w-lg"
      >
        {item ? (
          <Body item={item} />
        ) : (
          <div className="p-6 text-sm text-muted-foreground">
            Select a facility to see its evidence.
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Body({ item }: { item: SearchResultItem }) {
  const f = item.facility;
  const allEvidence = useMemo(
    () => buildEvidenceList(item),
    [item]
  );

  return (
    <div className="flex flex-col">
      <SheetHeader className="border-b px-6 pb-4 pt-6">
        <SheetTitle className="text-xl font-bold tracking-tight">
          {f.name}
        </SheetTitle>
        <SheetDescription className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          {f.type && <span className="capitalize">{f.type}</span>}
          {(f.city || f.state) && (
            <span className="inline-flex items-center gap-1">
              <MapPin className="size-3" />
              {[f.city, f.state].filter(Boolean).join(", ")}
            </span>
          )}
          {typeof item.distance_km === "number" && (
            <span>
              {item.distance_km < 1
                ? `${Math.round(item.distance_km * 1000)} m`
                : `${item.distance_km.toFixed(1)} km`}{" "}
              away
            </span>
          )}
        </SheetDescription>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          {allEvidence.length > 0 && (
            <ConfidenceBadge value={allEvidence[0].confidence} />
          )}
          {item.trust_signal && (
            <TrustSignalChip signal={item.trust_signal} compact={false} />
          )}
        </div>

        {item.attributes && <AttributeRow attrs={item.attributes} />}
      </SheetHeader>

      {item.missing_evidence && item.missing_evidence.length > 0 && (
        <section className="border-b px-6 py-4">
          <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            <AlertTriangle className="size-3 text-[color:var(--brand-coral)]" />
            What's missing
          </h3>
          <ul className="mt-2 space-y-1 text-[12px] text-foreground/80">
            {item.missing_evidence.map((m) => (
              <li key={m} className="flex gap-2">
                <span className="text-muted-foreground">·</span>
                <span>{m}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="px-6 py-4">
        <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Evidence
        </h3>
        {allEvidence.length === 0 && (
          <p className="mt-2 text-sm text-muted-foreground">
            No supporting snippets were returned for this facility. The match
            was scored on metadata alone.
          </p>
        )}
        <ul className="mt-3 space-y-3">
          {allEvidence.map((e, i) => (
            <li
              key={`${e.field}-${i}`}
              className="rounded-lg border bg-card/40 p-3"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {e.field.replace(/_/g, " ")}
                </span>
                <ConfidenceBadge value={e.confidence} />
              </div>
              <p className="mt-2 text-sm italic leading-relaxed text-foreground/90">
                “{e.snippet}”
              </p>
            </li>
          ))}
        </ul>
      </section>

      {f.specialties && f.specialties.length > 0 && (
        <FactSection title="Specialties" items={f.specialties} />
      )}
      {f.services && f.services.length > 0 && (
        <FactSection title="Services" items={f.services} />
      )}
      {f.procedures && f.procedures.length > 0 && (
        <FactSection title="Procedures" items={f.procedures} />
      )}
      {f.equipment && f.equipment.length > 0 && (
        <FactSection title="Equipment" items={f.equipment} />
      )}

      {f.raw_description && (
        <section className="border-t px-6 py-4">
          <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Source text
          </h3>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-foreground/80">
            {f.raw_description}
          </p>
        </section>
      )}

      <Separator />
      <div className="flex items-center justify-between gap-3 px-6 py-4">
        <p className="text-[11px] text-muted-foreground">
          Spot a mistake? Help us improve the record.
        </p>
        <Button
          asChild
          variant="outline"
          size="sm"
          className="h-9 gap-2"
        >
          <Link
            to="/providers/new"
            search={{ facility_id: f.id, name: f.name } as never}
          >
            <Flag className="size-3.5" />
            Report this
          </Link>
        </Button>
      </div>
    </div>
  );
}

const ATTR_LABELS: { key: string; label: string }[] = [
  { key: "accepts_pmjay", label: "PM-JAY" },
  { key: "accepts_cghs", label: "CGHS" },
  { key: "accepts_esi", label: "ESI" },
  { key: "nabh_accredited", label: "NABH" },
  { key: "jci_accredited", label: "JCI" },
  { key: "is_24x7", label: "24×7" },
  { key: "has_ambulance", label: "Ambulance" },
  { key: "has_telemedicine", label: "Telemed" },
  { key: "has_blood_bank", label: "Blood bank" },
  { key: "has_icu", label: "ICU" },
  { key: "has_nicu", label: "NICU" },
  { key: "has_emergency", label: "Emergency" },
  { key: "is_government", label: "Government" },
  { key: "is_nonprofit", label: "Non-profit" },
  { key: "offers_charity_care", label: "Charity care" },
];

function AttributeRow({ attrs }: { attrs: Record<string, unknown> }) {
  const flags = ATTR_LABELS.filter((a) => Boolean(attrs[a.key]));
  const languages = Array.isArray(attrs.languages)
    ? (attrs.languages as string[])
    : [];
  if (flags.length === 0 && languages.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {flags.map((f) => (
        <span
          key={f.key}
          className="rounded-full border border-[color:var(--brand-teal)]/30 bg-[color:var(--brand-teal)]/8 px-2 py-0.5 text-[10px] font-medium text-[color:var(--brand-teal)]"
        >
          {f.label}
        </span>
      ))}
      {languages.length > 0 && (
        <span className="rounded-full border bg-background/40 px-2 py-0.5 text-[10px] text-muted-foreground">
          {languages.join(", ")}
        </span>
      )}
    </div>
  );
}

function FactSection({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="border-t px-6 py-4">
      <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        {title}
      </h3>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {items.map((s, i) => (
          <Fragment key={`${s}-${i}`}>
            <span className="rounded-full border bg-background/40 px-2.5 py-0.5 text-[11px] capitalize text-foreground/80">
              {s}
            </span>
          </Fragment>
        ))}
      </div>
    </section>
  );
}

/** Combine evidence + facility metadata into a single ranked list. */
function buildEvidenceList(item: SearchResultItem) {
  const merged: { field: string; snippet: string; confidence: number }[] = [];
  if (item.evidence && item.evidence.length > 0) {
    merged.push(...item.evidence);
  } else if (item.top_evidence) {
    merged.push(item.top_evidence);
  }
  // Dedupe (field+snippet) and sort by confidence desc.
  const seen = new Set<string>();
  const out: typeof merged = [];
  for (const e of merged) {
    const k = `${e.field}::${e.snippet}`;
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(e);
  }
  return out.sort((a, b) => b.confidence - a.confidence);
}
