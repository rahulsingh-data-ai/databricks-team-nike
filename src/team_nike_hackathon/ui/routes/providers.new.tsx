import {
  createFileRoute,
  Link,
  useNavigate,
  useSearch,
} from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

import Navbar from "@/components/shell/navbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  AddressFields,
  EMPTY_ADDRESS,
  type AddressValue,
} from "@/components/intake/address-fields";
import { ChipsInput } from "@/components/intake/chips-input";
import {
  LocationPicker,
  type LatLng,
} from "@/components/intake/location-picker";
import { PhotoUpload } from "@/components/intake/photo-upload";

import {
  createSubmission,
  SubmissionType,
  useListSpecialties,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface ProvidersNewSearch {
  facility_id?: string;
  name?: string;
  step?: number;
}

export const Route = createFileRoute("/providers/new")({
  validateSearch: (s: Record<string, unknown>): ProvidersNewSearch => ({
    facility_id: typeof s.facility_id === "string" ? s.facility_id : undefined,
    name: typeof s.name === "string" ? s.name : undefined,
    step:
      typeof s.step === "string"
        ? Number(s.step)
        : typeof s.step === "number"
        ? s.step
        : undefined,
  }),
  component: () => <ProvidersNewPage />,
});

const STEPS = [
  { id: "facility", title: "Facility" },
  { id: "services", title: "Services" },
  { id: "location", title: "Location" },
  { id: "contact", title: "Contact" },
  { id: "review", title: "Review" },
] as const;

interface FormState {
  // Step 1
  name: string;
  type: string;
  description: string;
  // Step 2
  specialties: string[];
  services: string[];
  procedures: string[];
  equipment: string[];
  // Step 3
  address: AddressValue;
  coords: LatLng | null;
  photo: string | null;
  // Step 4
  submitter_name: string;
  submitter_email: string;
  submitter_role: string;
  notes: string;
  // Optional report context
  facility_id?: string;
}

const FACILITY_TYPES = [
  "hospital",
  "clinic",
  "diagnostic",
  "pharmacy",
  "rehabilitation",
  "other",
];

function ProvidersNewPage() {
  const navigate = useNavigate({ from: "/providers/new" });
  const search = useSearch({ from: "/providers/new" });
  const step = Math.max(0, Math.min(STEPS.length - 1, search.step ?? 0));

  const { data: specialties } = useListSpecialties();
  const suggestions = specialties?.data ?? [];

  const [form, setForm] = useState<FormState>(() => ({
    name: search.name ?? "",
    type: "",
    description: "",
    specialties: [],
    services: [],
    procedures: [],
    equipment: [],
    address: { ...EMPTY_ADDRESS },
    coords: null,
    photo: null,
    submitter_name: "",
    submitter_email: "",
    submitter_role: "Owner",
    notes: search.facility_id
      ? `Reporting a correction for facility ${search.facility_id}`
      : "",
    facility_id: search.facility_id,
  }));
  const [submitted, setSubmitted] = useState<{ id: string } | null>(null);

  function update<K extends keyof FormState>(k: K, v: FormState[K]) {
    setForm((prev) => ({ ...prev, [k]: v }));
  }

  function goto(n: number) {
    navigate({
      search: (prev) => ({ ...(prev as ProvidersNewSearch), step: n }),
    });
  }

  const canAdvance = useMemo(() => {
    switch (step) {
      case 0:
        return form.name.trim().length > 1;
      case 1:
        return (
          form.specialties.length > 0 ||
          form.services.length > 0 ||
          form.procedures.length > 0
        );
      case 2:
        return form.address.city.trim().length > 0;
      case 3:
        return form.submitter_email.trim().length > 3;
      default:
        return true;
    }
  }, [step, form]);

  async function submit() {
    try {
      const payload = {
        name: form.name.trim(),
        type: form.type || undefined,
        raw_description: form.description.trim() || undefined,
        specialties: form.specialties,
        services: form.services,
        procedures: form.procedures,
        equipment: form.equipment,
        ...form.address,
        latitude: form.coords?.lat ?? undefined,
        longitude: form.coords?.lng ?? undefined,
        photo_url: form.photo ?? undefined,
        submitter_name: form.submitter_name,
        submitter_email: form.submitter_email,
        submitter_role: form.submitter_role,
        facility_id: form.facility_id,
      };
      const resp = await createSubmission({
        submission_type: SubmissionType.provider_self_attest,
        payload,
        captured_lat: form.coords?.lat ?? undefined,
        captured_lng: form.coords?.lng ?? undefined,
        captured_at: form.coords ? new Date().toISOString() : undefined,
        photo_url: form.photo ?? undefined,
        notes: form.notes.trim() || undefined,
      });
      setSubmitted({ id: resp.data.id });
      toast.success("Submission received — thanks!");
    } catch (err) {
      toast.error("We couldn't save your submission. Please try again.");
      console.error(err);
    }
  }

  if (submitted) {
    return (
      <ThanksScreen
        submissionId={submitted.id}
        title="Submission queued for review"
        body="Our team will review your information and merge it into MatchCare's directory. We'll email you if we need clarification."
      />
    );
  }

  return (
    <div className="flex min-h-screen w-full flex-col bg-background">
      <Navbar />
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8 md:py-12">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              I'm a provider
            </span>
            <h1 className="mt-1 text-2xl font-bold tracking-tight md:text-3xl">
              Submit your facility
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Step {step + 1} of {STEPS.length} · {STEPS[step].title}
            </p>
          </div>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/">
              <ArrowLeft className="mr-1 size-4" /> Home
            </Link>
          </Button>
        </div>

        <Progress current={step} />

        <Card className="mt-4">
          <CardHeader>
            <CardTitle>{STEPS[step].title}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {step === 0 && (
              <>
                <div>
                  <Label htmlFor="name">Facility name</Label>
                  <Input
                    id="name"
                    value={form.name}
                    onChange={(e) => update("name", e.target.value)}
                    placeholder="Apollo Clinic, Jaipur"
                  />
                </div>
                <div>
                  <Label htmlFor="type">Type</Label>
                  <Select
                    value={form.type}
                    onValueChange={(v) => update("type", v)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Choose a type" />
                    </SelectTrigger>
                    <SelectContent>
                      {FACILITY_TYPES.map((t) => (
                        <SelectItem key={t} value={t} className="capitalize">
                          {t}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label htmlFor="description">Description</Label>
                  <Textarea
                    id="description"
                    value={form.description}
                    onChange={(e) => update("description", e.target.value)}
                    placeholder="A short paragraph describing the facility, hours, and notable equipment."
                    rows={5}
                  />
                </div>
              </>
            )}

            {step === 1 && (
              <>
                <ChipsInput
                  id="specialties"
                  label="Specialties"
                  description="Clinical areas you cover."
                  placeholder="dialysis, cardiology…"
                  suggestions={suggestions}
                  value={form.specialties}
                  onChange={(v) => update("specialties", v)}
                />
                <ChipsInput
                  id="services"
                  label="Services"
                  description="Day-to-day services patients can book."
                  placeholder="hemodialysis, MRI, vaccination…"
                  value={form.services}
                  onChange={(v) => update("services", v)}
                />
                <ChipsInput
                  id="procedures"
                  label="Procedures"
                  description="Surgeries and interventions performed on-site."
                  placeholder="angioplasty, cataract surgery…"
                  value={form.procedures}
                  onChange={(v) => update("procedures", v)}
                />
                <ChipsInput
                  id="equipment"
                  label="Equipment"
                  description="Notable diagnostic or treatment equipment."
                  placeholder="CT scanner, hemodialysis machine…"
                  value={form.equipment}
                  onChange={(v) => update("equipment", v)}
                />
              </>
            )}

            {step === 2 && (
              <>
                <AddressFields
                  value={form.address}
                  onChange={(v) => update("address", v)}
                />
                <LocationPicker
                  value={form.coords}
                  onChange={(v) => update("coords", v)}
                />
                <PhotoUpload
                  value={form.photo}
                  onChange={(v) => update("photo", v)}
                />
              </>
            )}

            {step === 3 && (
              <>
                <div>
                  <Label htmlFor="submitter_name">Your name</Label>
                  <Input
                    id="submitter_name"
                    value={form.submitter_name}
                    onChange={(e) => update("submitter_name", e.target.value)}
                  />
                </div>
                <div>
                  <Label htmlFor="submitter_email">Your email</Label>
                  <Input
                    id="submitter_email"
                    type="email"
                    value={form.submitter_email}
                    onChange={(e) => update("submitter_email", e.target.value)}
                  />
                </div>
                <div>
                  <Label htmlFor="submitter_role">Your role</Label>
                  <Input
                    id="submitter_role"
                    value={form.submitter_role}
                    onChange={(e) => update("submitter_role", e.target.value)}
                    placeholder="Owner, administrator, doctor…"
                  />
                </div>
                <div>
                  <Label htmlFor="notes">Notes for the reviewer</Label>
                  <Textarea
                    id="notes"
                    value={form.notes}
                    onChange={(e) => update("notes", e.target.value)}
                    rows={3}
                  />
                </div>
              </>
            )}

            {step === 4 && <ReviewSummary form={form} />}
          </CardContent>
        </Card>

        <div className="mt-6 flex items-center justify-between gap-3">
          <Button
            variant="outline"
            disabled={step === 0}
            onClick={() => goto(step - 1)}
          >
            <ArrowLeft className="mr-1 size-4" /> Back
          </Button>
          {step < STEPS.length - 1 ? (
            <Button
              disabled={!canAdvance}
              onClick={() => goto(step + 1)}
              className="bg-[color:var(--brand-coral)] text-white hover:bg-[color:var(--brand-coral)]/90"
            >
              Next <ArrowRight className="ml-1 size-4" />
            </Button>
          ) : (
            <Button
              onClick={submit}
              className="bg-[color:var(--brand-coral)] text-white hover:bg-[color:var(--brand-coral)]/90"
            >
              Submit for review
            </Button>
          )}
        </div>
      </main>
    </div>
  );
}

function Progress({ current }: { current: number }) {
  return (
    <ol className="flex items-center gap-2 overflow-x-auto">
      {STEPS.map((s, i) => {
        const active = i === current;
        const done = i < current;
        return (
          <li
            key={s.id}
            className={cn(
              "flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-medium",
              active && "border-[color:var(--brand-coral)] text-foreground",
              done && "border-[color:var(--brand-teal)] text-foreground",
              !active && !done && "border-border text-muted-foreground"
            )}
          >
            <span
              className={cn(
                "grid size-5 place-items-center rounded-full text-[10px] font-bold",
                done
                  ? "bg-[color:var(--brand-teal)] text-white"
                  : active
                  ? "bg-[color:var(--brand-coral)] text-white"
                  : "bg-muted text-muted-foreground"
              )}
            >
              {done ? "✓" : i + 1}
            </span>
            {s.title}
          </li>
        );
      })}
    </ol>
  );
}

function ReviewSummary({ form }: { form: FormState }) {
  const items: { label: string; value: string }[] = [
    { label: "Name", value: form.name || "—" },
    { label: "Type", value: form.type || "—" },
    {
      label: "Address",
      value:
        [
          form.address.address,
          form.address.city,
          form.address.state,
          form.address.pincode,
        ]
          .filter(Boolean)
          .join(", ") || "—",
    },
    {
      label: "Coordinates",
      value: form.coords
        ? `${form.coords.lat.toFixed(5)}, ${form.coords.lng.toFixed(5)}`
        : "—",
    },
    { label: "Specialties", value: form.specialties.join(", ") || "—" },
    { label: "Services", value: form.services.join(", ") || "—" },
    { label: "Procedures", value: form.procedures.join(", ") || "—" },
    { label: "Equipment", value: form.equipment.join(", ") || "—" },
    { label: "Submitter", value: form.submitter_email || "—" },
  ];
  return (
    <dl className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
      {items.map((i) => (
        <div key={i.label}>
          <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {i.label}
          </dt>
          <dd className="mt-0.5 break-words text-foreground/90">{i.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ThanksScreen({
  submissionId,
  title,
  body,
}: {
  submissionId: string;
  title: string;
  body: string;
}) {
  return (
    <div className="flex min-h-screen w-full flex-col bg-background">
      <Navbar />
      <main className="grid flex-1 place-items-center px-6 py-12">
        <Card className="w-full max-w-lg">
          <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
            <CheckCircle2 className="size-12 text-[color:var(--brand-teal)]" />
            <h1 className="text-xl font-bold">{title}</h1>
            <p className="text-sm text-muted-foreground">{body}</p>
            <p className="mt-2 font-mono text-[11px] text-muted-foreground">
              Submission ID: {submissionId}
            </p>
            <div className="mt-4 flex gap-2">
              <Button variant="outline" asChild>
                <Link to="/">Back home</Link>
              </Button>
              <Button asChild className="bg-[color:var(--brand-coral)] text-white hover:bg-[color:var(--brand-coral)]/90">
                <Link to="/find" search={{} as never}>Find providers</Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
