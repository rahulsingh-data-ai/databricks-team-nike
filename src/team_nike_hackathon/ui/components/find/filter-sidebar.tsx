import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { useListSpecialties } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

export interface FiltersState {
  specialties: string[];
  radiusKm: number;
  minConfidence: number;
  showUnverified: boolean;
}

interface FilterSidebarProps {
  value: FiltersState;
  onChange: (next: FiltersState) => void;
  className?: string;
}

export function FilterSidebar({ value, onChange, className }: FilterSidebarProps) {
  const { data: specialties } = useListSpecialties();
  const allSpecialties = specialties?.data ?? [];

  function toggleSpecialty(name: string) {
    const next = value.specialties.includes(name)
      ? value.specialties.filter((s) => s !== name)
      : [...value.specialties, name];
    onChange({ ...value, specialties: next });
  }

  return (
    <aside
      className={cn(
        "flex h-full w-full flex-col gap-6 overflow-y-auto border-r bg-card/50 px-5 py-6 backdrop-blur",
        className
      )}
    >
      <section>
        <div className="flex items-baseline justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Distance
          </h3>
          <span className="text-sm tabular-nums text-foreground">
            {value.radiusKm} km
          </span>
        </div>
        <Slider
          className="mt-3"
          min={5}
          max={500}
          step={5}
          value={[value.radiusKm]}
          onValueChange={([v]) => onChange({ ...value, radiusKm: v })}
        />
      </section>

      <section>
        <div className="flex items-baseline justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Minimum confidence
          </h3>
          <span className="text-sm tabular-nums text-foreground">
            {Math.round(value.minConfidence * 100)}%
          </span>
        </div>
        <Slider
          className="mt-3"
          min={0}
          max={1}
          step={0.05}
          value={[value.minConfidence]}
          onValueChange={([v]) => onChange({ ...value, minConfidence: v })}
        />
      </section>

      <section className="flex items-center justify-between gap-3">
        <div>
          <Label htmlFor="unverified" className="text-sm">
            Show unverified
          </Label>
          <p className="text-[11px] text-muted-foreground">
            Include claim-only facilities (lower confidence).
          </p>
        </div>
        <Switch
          id="unverified"
          checked={value.showUnverified}
          onCheckedChange={(c) => onChange({ ...value, showUnverified: c })}
        />
      </section>

      <Separator />

      <section>
        <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Specialties
        </h3>
        {!specialties && (
          <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" /> Loading…
          </div>
        )}
        {allSpecialties.length === 0 && specialties && (
          <p className="mt-3 text-[11px] text-muted-foreground">
            Filter values will appear once facilities are loaded.
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-1.5">
          {allSpecialties.map((s) => {
            const active = value.specialties.includes(s);
            return (
              <button
                key={s}
                type="button"
                onClick={() => toggleSpecialty(s)}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-[11px] font-medium capitalize transition-colors",
                  active
                    ? "border-[color:var(--brand-teal)] bg-[color:var(--brand-teal)]/15 text-foreground"
                    : "border-border bg-background/40 text-muted-foreground hover:bg-accent"
                )}
              >
                {s}
              </button>
            );
          })}
        </div>
        {value.specialties.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="mt-3 h-7 px-2 text-xs"
            onClick={() => onChange({ ...value, specialties: [] })}
          >
            Clear specialties
          </Button>
        )}
      </section>
    </aside>
  );
}
