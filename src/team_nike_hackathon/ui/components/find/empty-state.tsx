import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { Locate, MapPin, Search } from "lucide-react";
import { useState } from "react";

interface EmptyStateProps {
  defaultQuery?: string;
  defaultWhere?: string;
  onSubmit: (params: {
    q: string;
    where: string;
    lat?: number;
    lng?: number;
  }) => void;
  geolocating?: boolean;
  className?: string;
}

const QUICK_NEEDS = [
  "Dialysis",
  "Emergency surgery",
  "Cardiology",
  "Maternity",
  "Cancer care",
  "Mental health",
];

export function EmptyState({
  defaultQuery = "",
  defaultWhere = "",
  onSubmit,
  geolocating,
  className,
}: EmptyStateProps) {
  const [q, setQ] = useState(defaultQuery);
  const [where, setWhere] = useState(defaultWhere);
  const [locating, setLocating] = useState(false);

  function useMyLocation() {
    if (!("geolocation" in navigator)) {
      setWhere("Geolocation not supported");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        onSubmit({
          q,
          where: "my location",
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
        });
      },
      () => {
        setLocating(false);
        setWhere("Could not get location");
      },
      { timeout: 8000 }
    );
  }

  function submit(e?: React.FormEvent) {
    e?.preventDefault();
    onSubmit({ q: q.trim(), where: where.trim() });
  }

  return (
    <div className={cn("relative grid h-full w-full place-items-center px-6", className)}>
      {/* Soft brand backdrop */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-32 left-1/4 size-96 rounded-full bg-[color:var(--brand-teal)]/15 blur-3xl" />
        <div className="absolute -bottom-32 right-1/4 size-96 rounded-full bg-[color:var(--brand-coral)]/15 blur-3xl" />
      </div>

      <form
        onSubmit={submit}
        className="relative z-10 w-full max-w-2xl rounded-2xl border bg-card/80 p-8 shadow-2xl backdrop-blur-xl"
      >
        <div className="mb-6 text-center">
          <span className="inline-flex items-center gap-2 rounded-full border bg-background/60 px-3 py-1 text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
            <span className="size-1.5 rounded-full bg-[color:var(--brand-coral)]" />
            Find a provider
          </span>
          <h1 className="mt-4 text-3xl font-bold tracking-tight md:text-4xl">
            What care do you need, and where?
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            We rank facilities by distance, fit, and how strong the evidence
            is for each claim — never just a list.
          </p>
        </div>

        <div className="space-y-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="What care? e.g. dialysis, emergency surgery, cardiology"
              className="h-12 pl-10 text-base"
            />
          </div>

          <div className="flex gap-2">
            <div className="relative flex-1">
              <MapPin className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={where}
                onChange={(e) => setWhere(e.target.value)}
                placeholder="Where? e.g. Jaipur (leave blank for all India)"
                className="h-12 pl-10 text-base"
              />
            </div>
            <Button
              type="button"
              variant="outline"
              className="h-12 gap-2"
              onClick={useMyLocation}
              disabled={locating || geolocating}
            >
              <Locate className="size-4" />
              {locating ? "Locating…" : "Use my location"}
            </Button>
          </div>
        </div>

        <div className="mt-5">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Common needs
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {QUICK_NEEDS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setQ(s)}
                className="rounded-full border bg-background/60 px-2.5 py-1 text-[11px] hover:border-[color:var(--brand-teal)] hover:text-foreground"
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-6 flex justify-end">
          <Button
            type="submit"
            size="lg"
            className="h-11 gap-2 bg-[color:var(--brand-coral)] px-6 text-white hover:bg-[color:var(--brand-coral)]/90"
          >
            Find providers
          </Button>
        </div>
      </form>
    </div>
  );
}
