import { useCallback, useEffect, useRef } from "react";
import {
  Map as MapView,
  MapMarker,
  MarkerContent,
  MapControls,
  type MapRef,
} from "@/components/map/map";
import { BAND_COLOR, bandFor } from "@/components/find/confidence-badge";
import type { SearchResultItem, SearchOrigin } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Database, Loader2, MapPin } from "lucide-react";

// India-centered framing on first load. We sit ~80°E / 22°N (a bit south
// of the geographic centroid for visual balance against the navbar) and
// zoom to 4.6 so the whole subcontinent reads cleanly even on smaller
// laptop screens.
const WORLD_CENTER: [number, number] = [80, 22];
const WORLD_ZOOM = 4.6;

// Carto Voyager is road- and label-rich and supports zoom up to ~20
// (building-level), so users can keep scrolling in for street detail.
// We use the same style for both light and dark themes — modern map UX
// (Uber/Lyft style) treats the map as information, not chrome.
const MAP_STYLES = {
  light: "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
  dark: "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
};

interface FacilityMapProps {
  results: SearchResultItem[];
  origin: SearchOrigin | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  loading?: boolean;
  className?: string;
}

export function FacilityMap({
  results,
  origin,
  selectedId,
  onSelect,
  loading,
  className,
}: FacilityMapProps) {
  const mapRef = useRef<MapRef | null>(null);
  const setMapRef = useCallback((m: MapRef | null) => {
    mapRef.current = m;
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const pts: [number, number][] = [];
    if (origin?.lat != null && origin?.lng != null) pts.push([origin.lng, origin.lat]);
    for (const r of results) {
      if (r.facility.latitude != null && r.facility.longitude != null) {
        pts.push([r.facility.longitude, r.facility.latitude]);
      }
    }
    if (pts.length === 0) return;
    if (pts.length === 1) {
      map.flyTo({ center: pts[0], zoom: 14.5, duration: 800, essential: true });
      return;
    }
    const lngs = pts.map((p) => p[0]);
    const lats = pts.map((p) => p[1]);
    map.fitBounds(
      [
        [Math.min(...lngs), Math.min(...lats)],
        [Math.max(...lngs), Math.max(...lats)],
      ],
      { padding: 80, duration: 700, maxZoom: 14.5, essential: true }
    );
  }, [results, origin]);

  useEffect(() => {
    if (!selectedId) return;
    const map = mapRef.current;
    if (!map) return;
    const item = results.find((r) => r.facility.id === selectedId);
    if (!item) return;
    if (item.facility.latitude != null && item.facility.longitude != null) {
      map.flyTo({
        center: [item.facility.longitude, item.facility.latitude],
        zoom: Math.max(map.getZoom(), 15.5),
        duration: 700,
        essential: true,
      });
    }
  }, [selectedId, results]);

  const noOriginCoords = origin == null || origin.lat == null || origin.lng == null;
  const hasOriginLabel = !!origin?.label;
  const showEmptyOverlay = !loading && results.length === 0;

  return (
    <div className={cn("relative h-full w-full", className)}>
      <MapView
        ref={setMapRef}
        center={WORLD_CENTER}
        zoom={WORLD_ZOOM}
        minZoom={1}
        maxZoom={20}
        styles={MAP_STYLES}
        className="absolute inset-0"
      >
        <MapControls
          position="bottom-right"
          showZoom
          showHome
          onHome={() => {
            mapRef.current?.flyTo({
              center: WORLD_CENTER,
              zoom: WORLD_ZOOM,
              duration: 700,
              essential: true,
            });
          }}
        />

        {origin?.lat != null && origin?.lng != null && (
          <MapMarker longitude={origin.lng} latitude={origin.lat}>
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

        {results.map((item, idx) => {
          const lat = item.facility.latitude;
          const lng = item.facility.longitude;
          if (lat == null || lng == null) return null;
          const isSelected = item.facility.id === selectedId;
          const band = bandFor(item.top_evidence?.confidence);
          const color = BAND_COLOR[band];
          return (
            <MapMarker
              key={item.facility.id}
              longitude={lng}
              latitude={lat}
              onClick={() => onSelect(item.facility.id)}
            >
              <MarkerContent>
                <div
                  className="relative cursor-pointer"
                  style={{ transform: "translate(-50%, -100%)" }}
                >
                  <div
                    className={cn(
                      "flex items-center gap-1 rounded-full border-2 px-2.5 py-1 text-[11px] font-semibold shadow-lg transition-transform",
                      isSelected ? "scale-110" : "scale-100",
                      band === "unverified" ? "bg-background" : "text-white"
                    )}
                    style={{
                      backgroundColor:
                        band === "unverified" ? undefined : color,
                      borderColor: color,
                      color: band === "unverified" ? color : "#fff",
                    }}
                  >
                    <span>#{idx + 1}</span>
                  </div>
                  <div
                    className="mx-auto h-2 w-0.5"
                    style={{ backgroundColor: color }}
                  />
                </div>
              </MarkerContent>
            </MapMarker>
          );
        })}
      </MapView>

      {loading && (
        <>
          <div className="pointer-events-none absolute inset-x-0 top-0 z-20 h-1 overflow-hidden bg-[color:var(--brand-coral)]/15">
            <span className="block h-full w-1/3 animate-[indeterminate_1.2s_ease-in-out_infinite] bg-[color:var(--brand-coral)]" />
          </div>
          <div className="pointer-events-none absolute top-3 left-1/2 z-10 -translate-x-1/2 inline-flex items-center gap-2 rounded-full border border-[color:var(--brand-coral)]/30 bg-card/95 px-3.5 py-1.5 text-xs font-medium text-foreground shadow-md backdrop-blur">
            <Loader2 className="size-3.5 animate-spin text-[color:var(--brand-coral)]" />
            Searching for facilities…
          </div>
          {results.length === 0 && (
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center px-6">
              <div className="pointer-events-auto max-w-md rounded-2xl border bg-card/95 px-6 py-5 text-center shadow-xl backdrop-blur">
                <div className="mx-auto grid size-10 place-items-center rounded-full bg-[color:var(--brand-coral)]/15 text-[color:var(--brand-coral)]">
                  <Loader2 className="size-5 animate-spin" />
                </div>
                <p className="mt-3 text-sm font-semibold text-foreground">
                  Searching for facilities…
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Parsing your query and ranking matches.
                </p>
              </div>
            </div>
          )}
        </>
      )}

      {showEmptyOverlay && (
        <div className="pointer-events-none absolute inset-x-0 bottom-6 z-10 flex justify-center px-6">
          <div className="pointer-events-auto max-w-md rounded-2xl border bg-card/95 px-5 py-4 text-center shadow-xl backdrop-blur">
            <div className="mx-auto grid size-9 place-items-center rounded-full bg-[color:var(--brand-coral)]/15 text-[color:var(--brand-coral)]">
              {noOriginCoords ? (
                <MapPin className="size-4" />
              ) : (
                <Database className="size-4" />
              )}
            </div>
            <h3 className="mt-2 text-sm font-semibold">
              {noOriginCoords
                ? hasOriginLabel
                  ? `We couldn't pinpoint “${origin?.label}”`
                  : "Add a location to see facilities on the map"
                : "No facilities match these filters"}
            </h3>
            <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
              {noOriginCoords
                ? "Try a major city name (e.g. Jaipur, Mumbai, Delhi) or use 'Use my location'."
                : "Try widening the radius, lowering the minimum confidence, or removing specialty filters. If the directory hasn't been loaded yet, the team is still ingesting data."}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
