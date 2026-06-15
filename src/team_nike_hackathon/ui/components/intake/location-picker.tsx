import { useCallback, useRef, useState } from "react";

import {
  Map as MapView,
  MapMarker,
  MarkerContent,
  MapControls,
  type MapRef,
} from "@/components/map/map";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { Locate, Loader2 } from "lucide-react";

const WORLD_CENTER: [number, number] = [80, 22];
const WORLD_ZOOM = 4.6;

const MAP_STYLES = {
  light: "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
  dark: "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
};

export interface LatLng {
  lat: number;
  lng: number;
}

interface LocationPickerProps {
  value: LatLng | null;
  onChange: (v: LatLng) => void;
  /** Show the auto-locate button (default false; on for fieldwork). */
  autoLocate?: boolean;
  className?: string;
}

export function LocationPicker({
  value,
  onChange,
  autoLocate,
  className,
}: LocationPickerProps) {
  const mapRef = useRef<MapRef | null>(null);
  const setMapRef = useCallback((m: MapRef | null) => {
    mapRef.current = m;
  }, []);
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function locate() {
    if (!("geolocation" in navigator)) {
      setError("Geolocation not supported in this browser");
      return;
    }
    setLocating(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        const next = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        onChange(next);
        mapRef.current?.flyTo({
          center: [next.lng, next.lat],
          zoom: 14,
          duration: 800,
          essential: true,
        });
      },
      (err) => {
        setLocating(false);
        setError(err.message || "Could not get location");
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  }

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center justify-between">
        <Label>Location</Label>
        {value && (
          <span className="font-mono text-[11px] text-muted-foreground">
            {value.lat.toFixed(5)}, {value.lng.toFixed(5)}
          </span>
        )}
      </div>

      <div className="relative h-64 w-full overflow-hidden rounded-lg border">
        <MapView
          ref={setMapRef}
          center={WORLD_CENTER}
          zoom={WORLD_ZOOM}
          minZoom={1}
          maxZoom={20}
          styles={MAP_STYLES}
          className="absolute inset-0"
        >
          <MapControls position="bottom-right" showZoom />
          {value && (
            <MapMarker longitude={value.lng} latitude={value.lat}>
              <MarkerContent>
                <div
                  className="size-4 rounded-full ring-4"
                  style={{
                    backgroundColor: "var(--brand-coral)",
                    boxShadow:
                      "0 0 0 8px color-mix(in srgb, var(--brand-coral) 25%, transparent)",
                  }}
                />
              </MarkerContent>
            </MapMarker>
          )}
        </MapView>
      </div>

      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={locate}
          disabled={locating}
          className="gap-1"
        >
          {locating ? (
            <Loader2 className="size-3 animate-spin" />
          ) : (
            <Locate className="size-3" />
          )}
          {autoLocate ? "Re-capture location" : "Use my location"}
        </Button>
        {error && <p className="text-[11px] text-[color:var(--brand-coral)]">{error}</p>}
        {!value && !error && (
          <p className="text-[11px] text-muted-foreground">
            We use your GPS so reviewers can verify the visit.
          </p>
        )}
      </div>
    </div>
  );
}
