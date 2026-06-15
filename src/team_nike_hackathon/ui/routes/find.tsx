import {
  createFileRoute,
  useNavigate,
  useSearch,
} from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  ArrowLeft,
  MapPin,
  Search as SearchIcon,
  SlidersHorizontal,
} from "lucide-react";

import Navbar from "@/components/shell/navbar";
import Logo from "@/components/shell/logo";
import { ModeToggle } from "@/components/shell/mode-toggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

import { cn } from "@/lib/utils";

import { EmptyState } from "@/components/find/empty-state";
import { FilterSidebar, type FiltersState } from "@/components/find/filter-sidebar";
import { FacilityMap } from "@/components/find/facility-map";
import { RankedList } from "@/components/find/ranked-list";
import { EvidenceDrawer } from "@/components/find/evidence-drawer";
import { AgentTracePanel } from "@/components/find/agent-trace-panel";

import {
  search as searchApi,
  type SearchIn,
  type SearchResultItem,
  type SearchResults,
} from "@/lib/api";

interface FindSearch {
  q?: string;
  where?: string;
  lat?: number;
  lng?: number;
  specs?: string;
  radius?: number;
  minConf?: number;
  hideUnverified?: number;
}

export const Route = createFileRoute("/find")({
  validateSearch: (s: Record<string, unknown>): FindSearch => ({
    q: typeof s.q === "string" ? s.q : undefined,
    where: typeof s.where === "string" ? s.where : undefined,
    lat: typeof s.lat === "string" ? Number(s.lat) : typeof s.lat === "number" ? s.lat : undefined,
    lng: typeof s.lng === "string" ? Number(s.lng) : typeof s.lng === "number" ? s.lng : undefined,
    specs: typeof s.specs === "string" ? s.specs : undefined,
    radius: typeof s.radius === "string" ? Number(s.radius) : typeof s.radius === "number" ? s.radius : undefined,
    minConf: typeof s.minConf === "string" ? Number(s.minConf) : typeof s.minConf === "number" ? s.minConf : undefined,
    hideUnverified:
      typeof s.hideUnverified === "string"
        ? Number(s.hideUnverified)
        : typeof s.hideUnverified === "number"
        ? s.hideUnverified
        : undefined,
  }),
  component: () => <FindPage />,
});

function FindPage() {
  const search = useSearch({ from: "/find" });
  const navigate = useNavigate({ from: "/find" });

  const hasQuery = Boolean((search.q && search.q.trim()) || (search.where && search.where.trim()) || (search.lat != null && search.lng != null));

  const filters = useMemo<FiltersState>(
    () => ({
      specialties: search.specs
        ? search.specs.split(",").filter(Boolean)
        : [],
      radiusKm: search.radius ?? 100,
      minConfidence: search.minConf ?? 0,
      showUnverified: search.hideUnverified !== 1,
    }),
    [search]
  );

  function updateSearch(patch: Partial<FindSearch>) {
    navigate({ search: (prev) => ({ ...(prev as FindSearch), ...patch }) });
  }

  function applyFilters(next: FiltersState) {
    updateSearch({
      specs: next.specialties.length ? next.specialties.join(",") : undefined,
      radius: next.radiusKm,
      minConf: next.minConfidence,
      hideUnverified: next.showUnverified ? undefined : 1,
    });
  }

  // ---- search execution ----

  const [data, setData] = useState<SearchResults | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [evidenceItem, setEvidenceItem] = useState<SearchResultItem | null>(null);

  const runSearch = useMutation({
    mutationFn: async (body: SearchIn): Promise<SearchResults> => {
      const resp = await searchApi(body);
      return resp.data;
    },
    onSuccess: (resp) => {
      setData(resp);
      // Auto-select the top result so the map flies to something useful.
      if (resp.results.length > 0) {
        setSelectedId(resp.results[0].facility.id);
      } else {
        setSelectedId(null);
      }
    },
  });

  // Refire the search whenever URL params change (excluding showUnverified,
  // which is applied client-side as a filter).
  useEffect(() => {
    if (!hasQuery) return;
    const body: SearchIn = {
      query: search.q ?? undefined,
      location:
        search.lat != null && search.lng != null
          ? { lat: search.lat, lng: search.lng, label: search.where ?? null }
          : null,
      location_text: search.where ?? undefined,
      radius_km: filters.radiusKm,
      specialties: filters.specialties.length ? filters.specialties : undefined,
      min_confidence: filters.minConfidence,
      limit: 50,
    };
    runSearch.mutate(body);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    hasQuery,
    search.q,
    search.where,
    search.lat,
    search.lng,
    filters.radiusKm,
    filters.specialties.join(","),
    filters.minConfidence,
  ]);

  const filteredResults = useMemo(() => {
    if (!data) return [];
    if (filters.showUnverified) return data.results;
    return data.results.filter(
      (r) =>
        (r.top_evidence?.confidence ?? avgConfidence(r.facility.confidence)) >= 0.6
    );
  }, [data, filters.showUnverified]);

  if (!hasQuery) {
    return (
      <div className="flex h-screen w-full flex-col bg-background">
        <Navbar />
        <main className="relative flex-1 overflow-hidden">
          <EmptyState
            defaultQuery={search.q}
            defaultWhere={search.where}
            onSubmit={({ q, where, lat, lng }) => {
              updateSearch({
                q: q || undefined,
                where: where || undefined,
                lat,
                lng,
              });
            }}
          />
        </main>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full flex-col bg-background">
      <Navbar
        leftContent={
          <div className="flex min-w-0 items-center gap-4">
            <Logo size="sm" />
            <div className="hidden h-6 w-px bg-border md:block" />
            <SearchHeader
              q={search.q ?? ""}
              where={search.where ?? ""}
              onApply={(patch) => updateSearch(patch)}
              loading={runSearch.isPending}
            />
          </div>
        }
        rightContent={
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              className="hidden gap-1 md:inline-flex"
              onClick={() => navigate({ to: "/", search: {} as never })}
            >
              <ArrowLeft className="size-4" />
              Home
            </Button>
            <ModeToggle />
          </div>
        }
      />
      <div className="grid h-[calc(100vh-5rem)] w-full grid-cols-[1fr_420px]">
        <div className="relative h-full w-full">
          <FacilityMap
            results={filteredResults}
            origin={data?.origin ?? null}
            selectedId={selectedId}
            loading={runSearch.isPending}
            onSelect={(id) => {
              setSelectedId(id);
            }}
          />
          <FloatingFilters
            value={filters}
            onChange={applyFilters}
            activeCount={activeFilterCount(filters)}
          />
        </div>
        <div className="flex h-full min-h-0 flex-col border-l bg-card/40 backdrop-blur">
          <AgentTracePanel
            parsedQuery={data?.parsed_query}
            loading={runSearch.isPending}
          />
          <RankedList
            results={filteredResults}
            origin={data?.origin}
            selectedId={selectedId}
            loading={runSearch.isPending}
            onSelect={(id) => setSelectedId(id)}
            onViewEvidence={(item) => {
              setEvidenceItem(item);
              setSelectedId(item.facility.id);
              setEvidenceOpen(true);
            }}
            className="flex-1 border-l-0 bg-transparent backdrop-blur-none"
          />
        </div>
      </div>

      <EvidenceDrawer
        item={evidenceItem}
        open={evidenceOpen}
        onOpenChange={setEvidenceOpen}
      />
    </div>
  );
}

function activeFilterCount(f: FiltersState): number {
  let n = 0;
  if (f.specialties.length) n += 1;
  if (f.radiusKm !== 100) n += 1;
  if (f.minConfidence > 0) n += 1;
  if (!f.showUnverified) n += 1;
  return n;
}

function FloatingFilters({
  value,
  onChange,
  activeCount,
}: {
  value: FiltersState;
  onChange: (next: FiltersState) => void;
  activeCount: number;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn(
            "absolute left-4 top-4 z-10 h-9 gap-1.5 rounded-full px-3.5",
            "border border-white/40",
            "bg-gradient-to-b from-white/55 via-white/40 to-white/25",
            "text-[color:var(--brand-navy)]",
            "shadow-[0_10px_28px_-10px_rgba(15,23,42,0.35),inset_0_1px_0_rgba(255,255,255,0.9),inset_0_-1px_0_rgba(255,255,255,0.15)]",
            "backdrop-blur-2xl backdrop-saturate-200",
            "hover:from-white/70 hover:via-white/55 hover:to-white/35",
            "data-[state=open]:from-white/80 data-[state=open]:via-white/65 data-[state=open]:to-white/45",
            "dark:border-white/15",
            "dark:from-white/15 dark:via-white/10 dark:to-white/5",
            "dark:text-white",
            "dark:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.6),inset_0_1px_0_rgba(255,255,255,0.28),inset_0_-1px_0_rgba(255,255,255,0.04)]",
            "dark:hover:from-white/22 dark:hover:via-white/16 dark:hover:to-white/10",
            "dark:data-[state=open]:from-white/30 dark:data-[state=open]:via-white/22 dark:data-[state=open]:to-white/15",
          )}
        >
          <SlidersHorizontal className="size-4 text-[color:var(--brand-coral)] drop-shadow-[0_1px_1px_rgba(15,23,42,0.25)]" />
          <span className="glass-text text-[13px] font-semibold tracking-tight">
            Filters
          </span>
          {activeCount > 0 && (
            <Badge
              variant="secondary"
              className={cn(
                "ml-0.5 grid h-5 min-w-5 place-items-center rounded-full px-1.5",
                "text-[10px] font-semibold leading-none text-white",
                "bg-[color:var(--brand-coral)]",
                "ring-1 ring-white/50",
                "shadow-[0_1px_2px_rgba(15,23,42,0.25)]",
                "dark:ring-white/15",
              )}
            >
              {activeCount}
            </Badge>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="start"
        sideOffset={10}
        className={cn(
          "z-20 w-[300px] overflow-hidden rounded-2xl p-0",
          "border border-white/40",
          "bg-gradient-to-b from-white/65 via-white/50 to-white/35",
          "text-foreground",
          "shadow-[0_28px_72px_-20px_rgba(15,23,42,0.5),inset_0_1px_0_rgba(255,255,255,0.95),inset_0_-1px_0_rgba(255,255,255,0.2)]",
          "backdrop-blur-2xl backdrop-saturate-200",
          "dark:border-white/12",
          "dark:from-white/14 dark:via-white/8 dark:to-white/4",
          "dark:shadow-[0_28px_72px_-20px_rgba(0,0,0,0.75),inset_0_1px_0_rgba(255,255,255,0.22),inset_0_-1px_0_rgba(255,255,255,0.03)]",
        )}
      >
        <FilterSidebar
          value={value}
          onChange={onChange}
          className={cn(
            "h-auto max-h-[min(70vh,520px)] gap-5 border-r-0 bg-transparent px-4 py-4 backdrop-blur-none",
          )}
        />
      </PopoverContent>
    </Popover>
  );
}

function avgConfidence(c: Record<string, number> | null | undefined): number {
  if (!c) return 0.5;
  const vals = Object.values(c).filter((v): v is number => typeof v === "number");
  if (!vals.length) return 0.5;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function SearchHeader({
  q,
  where,
  onApply,
  loading,
}: {
  q: string;
  where: string;
  onApply: (patch: Partial<FindSearch>) => void;
  loading: boolean;
}) {
  const [qLocal, setQLocal] = useState(q);
  const [whereLocal, setWhereLocal] = useState(where);
  useEffect(() => setQLocal(q), [q]);
  useEffect(() => setWhereLocal(where), [where]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onApply({ q: qLocal || undefined, where: whereLocal || undefined });
      }}
      className="hidden items-center gap-2 md:flex"
    >
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={qLocal}
          onChange={(e) => setQLocal(e.target.value)}
          placeholder="What care?"
          className="h-9 w-[220px] pl-9"
        />
      </div>
      <div className="relative">
        <MapPin className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={whereLocal}
          onChange={(e) => setWhereLocal(e.target.value)}
          placeholder="Where?"
          className="h-9 w-[180px] pl-9"
        />
      </div>
      <Button type="submit" size="sm" className="h-9">
        {loading ? "Searching…" : "Search"}
      </Button>
    </form>
  );
}
