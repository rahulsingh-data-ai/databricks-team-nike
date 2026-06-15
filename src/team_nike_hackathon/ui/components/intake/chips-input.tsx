import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

interface ChipsInputProps {
  id?: string;
  label: string;
  description?: string;
  placeholder?: string;
  suggestions?: string[];
  value: string[];
  onChange: (v: string[]) => void;
  className?: string;
}

export function ChipsInput({
  id,
  label,
  description,
  placeholder,
  suggestions,
  value,
  onChange,
  className,
}: ChipsInputProps) {
  const [draft, setDraft] = useState("");

  function commit(v?: string) {
    const next = (v ?? draft).trim();
    if (!next) return;
    if (value.some((x) => x.toLowerCase() === next.toLowerCase())) {
      setDraft("");
      return;
    }
    onChange([...value, next]);
    setDraft("");
  }

  function remove(s: string) {
    onChange(value.filter((x) => x !== s));
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && !draft && value.length) {
      e.preventDefault();
      onChange(value.slice(0, -1));
    }
  }

  const remaining =
    suggestions?.filter(
      (s) => !value.some((v) => v.toLowerCase() === s.toLowerCase())
    ) ?? [];

  return (
    <div className={cn("space-y-2", className)}>
      <div>
        <Label htmlFor={id}>{label}</Label>
        {description && (
          <p className="mt-0.5 text-[11px] text-muted-foreground">{description}</p>
        )}
      </div>
      <div className="rounded-md border bg-background/40 p-2">
        <div className="flex flex-wrap gap-1.5">
          {value.map((s) => (
            <span
              key={s}
              className="inline-flex items-center gap-1 rounded-full border border-[color:var(--brand-teal)]/30 bg-[color:var(--brand-teal)]/10 px-2 py-0.5 text-[11px] capitalize text-foreground"
            >
              {s}
              <button
                type="button"
                onClick={() => remove(s)}
                aria-label={`Remove ${s}`}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
          <Input
            id={id}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
            onBlur={() => commit()}
            placeholder={placeholder ?? "Type and press Enter…"}
            className="h-7 min-w-[140px] flex-1 border-0 bg-transparent p-0 text-sm focus-visible:ring-0"
          />
        </div>
      </div>
      {remaining.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {remaining.slice(0, 8).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => commit(s)}
              className="rounded-full border bg-background/50 px-2 py-0.5 text-[11px] text-muted-foreground hover:border-[color:var(--brand-teal)] hover:text-foreground"
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
