import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { ArrowLeft, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

import Navbar from "@/components/shell/navbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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
import { ThanksScreen } from "./providers.new";

import {
  createSubmission,
  SubmissionType,
  useListSpecialties,
} from "@/lib/api";

interface FieldworkSearch {
  surveyor?: string;
}

export const Route = createFileRoute("/fieldwork")({
  validateSearch: (s: Record<string, unknown>): FieldworkSearch => ({
    surveyor: typeof s.surveyor === "string" ? s.surveyor : undefined,
  }),
  component: () => <FieldworkPage />,
});

const FACILITY_TYPES = [
  "hospital",
  "clinic",
  "diagnostic",
  "pharmacy",
  "rehabilitation",
  "other",
];

function FieldworkPage() {
  const navigate = useNavigate({ from: "/fieldwork" });
  const { data: specialties } = useListSpecialties();
  const suggestions = specialties?.data ?? [];

  const [surveyor, setSurveyor] = useState("");
  const [coords, setCoords] = useState<LatLng | null>(null);
  const [accuracy, setAccuracy] = useState<number | null>(null);
  const [autoLocateError, setAutoLocateError] = useState<string | null>(null);
  const [visited, setVisited] = useState(false);
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [address, setAddress] = useState<AddressValue>({ ...EMPTY_ADDRESS });
  const [phone, setPhone] = useState("");
  const [hours, setHours] = useState("");
  const [specialtiesPicked, setSpecialtiesPicked] = useState<string[]>([]);
  const [services, setServices] = useState<string[]>([]);
  const [equipment, setEquipment] = useState<string[]>([]);
  const [description, setDescription] = useState("");
  const [photo, setPhoto] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [submittedId, setSubmittedId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Auto-capture GPS on first mount.
  useEffect(() => {
    if (!("geolocation" in navigator)) {
      setAutoLocateError("Geolocation isn't available on this device.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setAccuracy(pos.coords.accuracy);
      },
      (err) => {
        setAutoLocateError(
          err.message ||
            "We need your location to attest this visit. Tap 'Re-capture' below."
        );
      },
      { enableHighAccuracy: true, timeout: 12000 }
    );
  }, []);

  const canSubmit =
    name.trim().length > 1 &&
    address.city.trim().length > 0 &&
    coords != null &&
    visited &&
    surveyor.trim().length > 1 &&
    !submitting;

  async function submit() {
    if (!coords) {
      toast.error("Capture the location before submitting.");
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        name: name.trim(),
        type: type || undefined,
        raw_description: description.trim() || undefined,
        specialties: specialtiesPicked,
        services,
        equipment,
        ...address,
        latitude: coords.lat,
        longitude: coords.lng,
        phone: phone || undefined,
        hours: hours || undefined,
        photo_url: photo ?? undefined,
        surveyor: surveyor.trim(),
        accuracy_meters: accuracy ?? undefined,
      };
      const resp = await createSubmission({
        submission_type: SubmissionType.fieldwork_surveyor,
        payload,
        captured_lat: coords.lat,
        captured_lng: coords.lng,
        captured_at: new Date().toISOString(),
        photo_url: photo ?? undefined,
        notes: notes.trim() || undefined,
      });
      setSubmittedId(resp.data.id);
      toast.success("Survey saved — great work.");
    } catch (err) {
      toast.error("Couldn't save survey. Try again — your work is preserved on this screen.");
      console.error(err);
    } finally {
      setSubmitting(false);
    }
  }

  if (submittedId) {
    return (
      <ThanksScreen
        submissionId={submittedId}
        title="Survey submitted"
        body="Thanks for being on the ground. Reviewers will merge this into the directory shortly."
      />
    );
  }

  return (
    <div className="flex min-h-screen w-full flex-col bg-background">
      <Navbar />
      <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-6 md:px-6 md:py-10">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              Fieldwork
            </span>
            <h1 className="mt-1 text-2xl font-bold tracking-tight">
              Survey a facility
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Tap through this form on-site. Your GPS pins the visit.
            </p>
          </div>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/">
              <ArrowLeft className="mr-1 size-4" /> Home
            </Link>
          </Button>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Your visit</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div>
              <Label htmlFor="surveyor">Surveyor ID / name</Label>
              <Input
                id="surveyor"
                value={surveyor}
                onChange={(e) => setSurveyor(e.target.value)}
                placeholder="e.g. SVR-014, Asha P."
              />
            </div>

            <LocationPicker
              value={coords}
              onChange={(v) => setCoords(v)}
              autoLocate
            />

            {accuracy != null && (
              <p className="text-[11px] text-muted-foreground">
                GPS accuracy: ±{Math.round(accuracy)} m
              </p>
            )}
            {autoLocateError && (
              <p className="flex items-start gap-1 text-[11px] text-[color:var(--brand-coral)]">
                <AlertTriangle className="mt-0.5 size-3" />
                {autoLocateError}
              </p>
            )}

            <div className="rounded-md border bg-[color:var(--brand-teal)]/5 p-3">
              <label className="flex items-start gap-2 text-sm">
                <Checkbox
                  checked={visited}
                  onCheckedChange={(c) => setVisited(Boolean(c))}
                  className="mt-0.5"
                />
                <span>
                  I attest that I am physically at this facility right now
                  and the information below reflects what I observed.
                </span>
              </label>
            </div>
          </CardContent>
        </Card>

        <Card className="mt-4">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Facility</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label htmlFor="name">Facility name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="As written on the signage"
              />
            </div>
            <div>
              <Label>Type</Label>
              <Select value={type} onValueChange={setType}>
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
            <AddressFields value={address} onChange={setAddress} />
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <Label htmlFor="phone">Phone</Label>
                <Input
                  id="phone"
                  inputMode="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="hours">Operating hours</Label>
                <Input
                  id="hours"
                  value={hours}
                  onChange={(e) => setHours(e.target.value)}
                  placeholder="Mon–Sat 8am–8pm"
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="mt-4">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">What they offer</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <ChipsInput
              label="Specialties (visible / signposted)"
              suggestions={suggestions}
              value={specialtiesPicked}
              onChange={setSpecialtiesPicked}
            />
            <ChipsInput
              label="Services / departments"
              value={services}
              onChange={setServices}
            />
            <ChipsInput
              label="Notable equipment seen"
              value={equipment}
              onChange={setEquipment}
            />
            <div>
              <Label htmlFor="description">Field notes</Label>
              <Textarea
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={4}
                placeholder="Anything else worth knowing — building condition, staff present, posted prices."
              />
            </div>
            <PhotoUpload value={photo} onChange={setPhoto} capture />
            <div>
              <Label htmlFor="notes">Reviewer notes (optional)</Label>
              <Textarea
                id="notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
              />
            </div>
          </CardContent>
        </Card>

        <div className="mt-5 flex items-center justify-end gap-2">
          <Button variant="outline" onClick={() => navigate({ to: "/" })}>
            Cancel
          </Button>
          <Button
            onClick={submit}
            disabled={!canSubmit}
            className="bg-[color:var(--brand-coral)] text-white hover:bg-[color:var(--brand-coral)]/90"
          >
            {submitting ? "Submitting…" : "Submit survey"}
          </Button>
        </div>
      </main>
    </div>
  );
}
