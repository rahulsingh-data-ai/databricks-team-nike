import { createFileRoute, Link } from "@tanstack/react-router";
import Navbar from "@/components/shell/navbar";
import { Button } from "@/components/ui/button";
import { ClipboardCheck } from "lucide-react";
import { ModeToggle } from "@/components/shell/mode-toggle";

export const Route = createFileRoute("/")({
  component: () => <Index />,
});

function Index() {
  return (
    <div className="relative flex min-h-screen w-full flex-col overflow-hidden bg-background text-foreground">
      <Navbar
        rightContent={
          <div className="flex items-center gap-2">
            <Button
              asChild
              variant="ghost"
              size="sm"
              className="hidden gap-1.5 text-foreground/80 hover:text-foreground md:inline-flex"
            >
              <Link to="/fieldwork">
                <ClipboardCheck className="size-4" />
                Fieldwork
              </Link>
            </Button>
            <ModeToggle />
          </div>
        }
      />

      <main className="relative flex-1">
        <video
          className="absolute inset-0 h-full w-full object-cover"
          src="/hero.mp4"
          autoPlay
          loop
          muted
          playsInline
          preload="auto"
          aria-hidden="true"
        />
        <div className="absolute inset-0 bg-gradient-to-r from-[#0B2D48]/85 via-[#0B2D48]/60 to-transparent" />
        <div className="absolute inset-0 bg-gradient-to-t from-[#0B2D48]/40 via-transparent to-transparent" />

        <div className="relative mx-auto flex w-full max-w-7xl flex-col justify-center gap-8 px-6 py-20 md:px-10 md:py-32 lg:py-40">
          <span className="inline-flex w-fit items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-white backdrop-blur-md">
            <span className="size-1.5 rounded-full bg-[color:var(--brand-coral)]" />
            Patient × Provider
          </span>

          <h1 className="max-w-3xl text-5xl font-bold leading-[1.05] tracking-tight text-white md:text-6xl lg:text-7xl">
            Care that finally{" "}
            <span className="bg-gradient-to-r from-[color:var(--brand-coral)] to-[color:var(--brand-teal)] bg-clip-text text-transparent">
              matches
            </span>{" "}
            you.
          </h1>

          <p className="max-w-xl text-lg leading-relaxed text-white/85 md:text-xl">
            MatchCare pairs patients with the right provider in seconds — using
            preferences, specialty, availability, and the data already in your
            health record.
          </p>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Button
              asChild
              size="lg"
              className="h-12 bg-[color:var(--brand-coral)] px-6 text-base text-white hover:bg-[color:var(--brand-coral)]/90"
            >
              <Link to="/find" search={{} as never}>Find a provider</Link>
            </Button>
            <Button
              asChild
              size="lg"
              variant="outline"
              className="h-12 border-white/30 bg-white/10 px-6 text-base text-white backdrop-blur-md hover:bg-white/20 hover:text-white"
            >
              <Link to="/providers/new" search={{} as never}>I'm a provider</Link>
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-x-10 gap-y-4 pt-6">
            <Stat value="14k+" label="Providers" />
            <Stat value="92%" label="First-match success" />
            <Stat value="< 30s" label="Avg. match time" />
          </div>
        </div>
      </main>

      <footer className="w-full border-t bg-background/80 backdrop-blur-md">
        <div className="flex h-16 w-full items-center justify-between px-6 text-xs text-muted-foreground md:px-10">
          <span>© {new Date().getFullYear()} MatchCare</span>
          <span>Your provider, perfectly matched.</span>
        </div>
      </footer>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="text-xl font-semibold text-white">{value}</div>
      <div className="text-xs uppercase tracking-wider text-white/70">
        {label}
      </div>
    </div>
  );
}
