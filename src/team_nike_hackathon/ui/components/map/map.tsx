"use client";

import MapLibreGL, { type PopupOptions, type MarkerOptions } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useId,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { X, Minus, Plus, Locate, Maximize, Loader2, Home } from "lucide-react";

import { cn } from "@/lib/utils";

const defaultStyles = {
  dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  light: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
};

type Theme = "light" | "dark";

// Check document class for theme (works with next-themes, etc.)
function getDocumentTheme(): Theme | null {
  if (typeof document === "undefined") return null;
  if (document.documentElement.classList.contains("dark")) return "dark";
  if (document.documentElement.classList.contains("light")) return "light";
  return null;
}

// Get system preference
function getSystemTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function useResolvedTheme(themeProp?: "light" | "dark"): Theme {
  const [detectedTheme, setDetectedTheme] = useState<Theme>(
    () => getDocumentTheme() ?? getSystemTheme()
  );

  useEffect(() => {
    if (themeProp) return; // Skip detection if theme is provided via prop

    // Watch for document class changes (e.g., next-themes toggling dark class)
    const observer = new MutationObserver(() => {
      const docTheme = getDocumentTheme();
      if (docTheme) {
        setDetectedTheme(docTheme);
      }
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    // Also watch for system preference changes
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleSystemChange = (e: MediaQueryListEvent) => {
      // Only use system preference if no document class is set
      if (!getDocumentTheme()) {
        setDetectedTheme(e.matches ? "dark" : "light");
      }
    };
    mediaQuery.addEventListener("change", handleSystemChange);

    return () => {
      observer.disconnect();
      mediaQuery.removeEventListener("change", handleSystemChange);
    };
  }, [themeProp]);

  return themeProp ?? detectedTheme;
}

type MapContextValue = {
  map: MapLibreGL.Map | null;
  isLoaded: boolean;
};

const MapContext = createContext<MapContextValue | null>(null);

function useMap() {
  const context = useContext(MapContext);
  if (!context) {
    throw new Error("useMap must be used within a Map component");
  }
  return context;
}

/** Map viewport state */
type MapViewport = {
  /** Center coordinates [longitude, latitude] */
  center: [number, number];
  /** Zoom level */
  zoom: number;
  /** Bearing (rotation) in degrees */
  bearing: number;
  /** Pitch (tilt) in degrees */
  pitch: number;
};

type MapStyleOption = string | MapLibreGL.StyleSpecification;

type MapRef = MapLibreGL.Map;

type MapProps = {
  children?: ReactNode;
  /** Additional CSS classes for the map container */
  className?: string;
  /**
   * Theme for the map. If not provided, automatically detects system preference.
   * Pass your theme value here.
   */
  theme?: Theme;
  /** Custom map styles for light and dark themes. Overrides the default Carto styles. */
  styles?: {
    light?: MapStyleOption;
    dark?: MapStyleOption;
  };
  /** Map projection type. Use `{ type: "globe" }` for 3D globe view. */
  projection?: MapLibreGL.ProjectionSpecification;
  /**
   * Controlled viewport. When provided with onViewportChange,
   * the map becomes controlled and viewport is driven by this prop.
   */
  viewport?: Partial<MapViewport>;
  /**
   * Callback fired continuously as the viewport changes (pan, zoom, rotate, pitch).
   * Can be used standalone to observe changes, or with `viewport` prop
   * to enable controlled mode where the map viewport is driven by your state.
   */
  onViewportChange?: (viewport: MapViewport) => void;
} & Omit<MapLibreGL.MapOptions, "container" | "style">;

function DefaultLoader() {
  return (
    <div className="absolute inset-0 flex items-center justify-center">
      <div className="flex gap-1">
        <span className="size-1.5 rounded-full bg-muted-foreground/60 animate-pulse" />
        <span className="size-1.5 rounded-full bg-muted-foreground/60 animate-pulse [animation-delay:150ms]" />
        <span className="size-1.5 rounded-full bg-muted-foreground/60 animate-pulse [animation-delay:300ms]" />
      </div>
    </div>
  );
}

function getViewport(map: MapLibreGL.Map): MapViewport {
  const center = map.getCenter();
  return {
    center: [center.lng, center.lat],
    zoom: map.getZoom(),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  };
}

const Map = forwardRef<MapRef, MapProps>(function Map(
  {
    children,
    className,
    theme: themeProp,
    styles,
    projection,
    viewport,
    onViewportChange,
    ...props
  },
  ref
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [mapInstance, setMapInstance] = useState<MapLibreGL.Map | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  const [isStyleLoaded, setIsStyleLoaded] = useState(false);
  const currentStyleRef = useRef<MapStyleOption | null>(null);
  const internalUpdateRef = useRef(false);
  const resolvedTheme = useResolvedTheme(themeProp);

  const isControlled = viewport !== undefined && onViewportChange !== undefined;

  const onViewportChangeRef = useRef(onViewportChange);
  onViewportChangeRef.current = onViewportChange;

  const mapStyles = useMemo(
    () => ({
      dark: styles?.dark ?? defaultStyles.dark,
      light: styles?.light ?? defaultStyles.light,
    }),
    [styles]
  );

  // Expose the map instance to the parent component
  useImperativeHandle(ref, () => mapInstance as MapLibreGL.Map, [mapInstance]);

  // Initialize the map
  useEffect(() => {
    if (!containerRef.current) return;

    const initialStyle =
      resolvedTheme === "dark" ? mapStyles.dark : mapStyles.light;
    currentStyleRef.current = initialStyle;

    const map = new MapLibreGL.Map({
      container: containerRef.current,
      style: initialStyle,
      renderWorldCopies: true,
      attributionControl: {
        compact: true,
      },
      ...props,
      ...viewport,
    });

    const loadHandler = () => setIsLoaded(true);
    const styleLoadHandler = () => {
      setIsStyleLoaded(true);
      if (projection) {
        map.setProjection(projection);
      }
    };

    // Viewport change handler - skip if triggered by internal update
    const handleMove = () => {
      if (internalUpdateRef.current) return;
      onViewportChangeRef.current?.(getViewport(map));
    };

    map.on("load", loadHandler);
    map.on("style.load", styleLoadHandler);
    map.on("move", handleMove);
    setMapInstance(map);

    return () => {
      map.off("load", loadHandler);
      map.off("style.load", styleLoadHandler);
      map.off("move", handleMove);
      map.remove();
      setIsLoaded(false);
      setIsStyleLoaded(false);
      setMapInstance(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync controlled viewport to map
  useEffect(() => {
    if (!mapInstance || !isControlled || !viewport) return;
    if (mapInstance.isMoving()) return;

    const current = getViewport(mapInstance);
    const next = {
      center: viewport.center ?? current.center,
      zoom: viewport.zoom ?? current.zoom,
      bearing: viewport.bearing ?? current.bearing,
      pitch: viewport.pitch ?? current.pitch,
    };

    if (
      next.center[0] === current.center[0] &&
      next.center[1] === current.center[1] &&
      next.zoom === current.zoom &&
      next.bearing === current.bearing &&
      next.pitch === current.pitch
    ) {
      return;
    }

    internalUpdateRef.current = true;
    mapInstance.jumpTo(next);
    internalUpdateRef.current = false;
  }, [mapInstance, isControlled, viewport]);

  // Handle style change
  useEffect(() => {
    if (!mapInstance || !resolvedTheme) return;

    const newStyle =
      resolvedTheme === "dark" ? mapStyles.dark : mapStyles.light;

    if (currentStyleRef.current === newStyle) return;

    currentStyleRef.current = newStyle;
    setIsStyleLoaded(false);

    mapInstance.setStyle(newStyle, { diff: true });
  }, [mapInstance, resolvedTheme, mapStyles]);

  const contextValue = useMemo(
    () => ({
      map: mapInstance,
      isLoaded: isLoaded && isStyleLoaded,
    }),
    [mapInstance, isLoaded, isStyleLoaded]
  );

  return (
    <MapContext.Provider value={contextValue}>
      <div
        ref={containerRef}
        className={cn("relative w-full h-full", className)}
      >
        {!isLoaded && <DefaultLoader />}
        {/* SSR-safe: children render only when map is loaded on client */}
        {mapInstance && children}
      </div>
    </MapContext.Provider>
  );
});

type MarkerContextValue = {
  marker: MapLibreGL.Marker;
  map: MapLibreGL.Map | null;
};

const MarkerContext = createContext<MarkerContextValue | null>(null);

function useMarkerContext() {
  const context = useContext(MarkerContext);
  if (!context) {
    throw new Error("Marker components must be used within MapMarker");
  }
  return context;
}

type MapMarkerProps = {
  /** Longitude coordinate for marker position */
  longitude: number;
  /** Latitude coordinate for marker position */
  latitude: number;
  /** Marker subcomponents (MarkerContent, MarkerPopup, MarkerTooltip, MarkerLabel) */
  children: ReactNode;
  /** Callback when marker is clicked */
  onClick?: (e: MouseEvent) => void;
  /** Callback when mouse enters marker */
  onMouseEnter?: (e: MouseEvent) => void;
  /** Callback when mouse leaves marker */
  onMouseLeave?: (e: MouseEvent) => void;
  /** Callback when marker drag starts (requires draggable: true) */
  onDragStart?: (lngLat: { lng: number; lat: number }) => void;
  /** Callback during marker drag (requires draggable: true) */
  onDrag?: (lngLat: { lng: number; lat: number }) => void;
  /** Callback when marker drag ends (requires draggable: true) */
  onDragEnd?: (lngLat: { lng: number; lat: number }) => void;
} & Omit<MarkerOptions, "element">;

function MapMarker({
  longitude,
  latitude,
  children,
  onClick,
  onMouseEnter,
  onMouseLeave,
  onDragStart,
  onDrag,
  onDragEnd,
  draggable = false,
  ...markerOptions
}: MapMarkerProps) {
  const { map } = useMap();

  const callbacksRef = useRef({
    onClick,
    onMouseEnter,
    onMouseLeave,
    onDragStart,
    onDrag,
    onDragEnd,
  });
  callbacksRef.current = {
    onClick,
    onMouseEnter,
    onMouseLeave,
    onDragStart,
    onDrag,
    onDragEnd,
  };

  const marker = useMemo(() => {
    const markerInstance = new MapLibreGL.Marker({
      ...markerOptions,
      element: document.createElement("div"),
      draggable,
    }).setLngLat([longitude, latitude]);

    const handleClick = (e: MouseEvent) => callbacksRef.current.onClick?.(e);
    const handleMouseEnter = (e: MouseEvent) =>
      callbacksRef.current.onMouseEnter?.(e);
    const handleMouseLeave = (e: MouseEvent) =>
      callbacksRef.current.onMouseLeave?.(e);

    markerInstance.getElement()?.addEventListener("click", handleClick);
    markerInstance
      .getElement()
      ?.addEventListener("mouseenter", handleMouseEnter);
    markerInstance
      .getElement()
      ?.addEventListener("mouseleave", handleMouseLeave);

    const handleDragStart = () => {
      const lngLat = markerInstance.getLngLat();
      callbacksRef.current.onDragStart?.({ lng: lngLat.lng, lat: lngLat.lat });
    };
    const handleDrag = () => {
      const lngLat = markerInstance.getLngLat();
      callbacksRef.current.onDrag?.({ lng: lngLat.lng, lat: lngLat.lat });
    };
    const handleDragEnd = () => {
      const lngLat = markerInstance.getLngLat();
      callbacksRef.current.onDragEnd?.({ lng: lngLat.lng, lat: lngLat.lat });
    };

    markerInstance.on("dragstart", handleDragStart);
    markerInstance.on("drag", handleDrag);
    markerInstance.on("dragend", handleDragEnd);

    return markerInstance;

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!map) return;

    marker.addTo(map);

    return () => {
      marker.remove();
    };

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  if (
    marker.getLngLat().lng !== longitude ||
    marker.getLngLat().lat !== latitude
  ) {
    marker.setLngLat([longitude, latitude]);
  }
  if (marker.isDraggable() !== draggable) {
    marker.setDraggable(draggable);
  }

  const currentOffset = marker.getOffset();
  const newOffset = markerOptions.offset ?? [0, 0];
  const [newOffsetX, newOffsetY] = Array.isArray(newOffset)
    ? newOffset
    : [newOffset.x, newOffset.y];
  if (currentOffset.x !== newOffsetX || currentOffset.y !== newOffsetY) {
    marker.setOffset(newOffset);
  }

  if (marker.getRotation() !== markerOptions.rotation) {
    marker.setRotation(markerOptions.rotation ?? 0);
  }
  if (marker.getRotationAlignment() !== markerOptions.rotationAlignment) {
    marker.setRotationAlignment(markerOptions.rotationAlignment ?? "auto");
  }
  if (marker.getPitchAlignment() !== markerOptions.pitchAlignment) {
    marker.setPitchAlignment(markerOptions.pitchAlignment ?? "auto");
  }

  return (
    <MarkerContext.Provider value={{ marker, map }}>
      {children}
    </MarkerContext.Provider>
  );
}

type MarkerContentProps = {
  /** Custom marker content. Defaults to a blue dot if not provided */
  children?: ReactNode;
  /** Additional CSS classes for the marker container */
  className?: string;
};

function MarkerContent({ children, className }: MarkerContentProps) {
  const { marker } = useMarkerContext();

  return createPortal(
    <div className={cn("relative cursor-pointer", className)}>
      {children || <DefaultMarkerIcon />}
    </div>,
    marker.getElement()
  );
}

function DefaultMarkerIcon() {
  return (
    <div className="relative h-4 w-4 rounded-full border-2 border-white bg-blue-500 shadow-lg" />
  );
}

type MarkerPopupProps = {
  /** Popup content */
  children: ReactNode;
  /** Additional CSS classes for the popup container */
  className?: string;
  /** Show a close button in the popup (default: false) */
  closeButton?: boolean;
} & Omit<PopupOptions, "className" | "closeButton">;

function MarkerPopup({
  children,
  className,
  closeButton = false,
  ...popupOptions
}: MarkerPopupProps) {
  const { marker, map } = useMarkerContext();
  const container = useMemo(() => document.createElement("div"), []);
  const prevPopupOptions = useRef(popupOptions);

  const popup = useMemo(() => {
    const popupInstance = new MapLibreGL.Popup({
      offset: 16,
      ...popupOptions,
      closeButton: false,
    })
      .setMaxWidth("none")
      .setDOMContent(container);

    return popupInstance;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!map) return;

    popup.setDOMContent(container);
    marker.setPopup(popup);

    return () => {
      marker.setPopup(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  if (popup.isOpen()) {
    const prev = prevPopupOptions.current;

    if (prev.offset !== popupOptions.offset) {
      popup.setOffset(popupOptions.offset ?? 16);
    }
    if (prev.maxWidth !== popupOptions.maxWidth && popupOptions.maxWidth) {
      popup.setMaxWidth(popupOptions.maxWidth ?? "none");
    }

    prevPopupOptions.current = popupOptions;
  }

  const handleClose = () => popup.remove();

  return createPortal(
    <div
      className={cn(
        "relative rounded-md border bg-popover p-3 text-popover-foreground shadow-md",
        "animate-in fade-in-0 slide-in-from-bottom-1 duration-200 ease-out",
        className
      )}
    >
      {closeButton && (
        <button
          type="button"
          onClick={handleClose}
          className="absolute top-1 right-1 z-10 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
          aria-label="Close popup"
        >
          <X className="h-4 w-4" />
          <span className="sr-only">Close</span>
        </button>
      )}
      {children}
    </div>,
    container
  );
}

type MarkerTooltipProps = {
  /** Tooltip content */
  children: ReactNode;
  /** Additional CSS classes for the tooltip container */
  className?: string;
} & Omit<PopupOptions, "className" | "closeButton" | "closeOnClick">;

function MarkerTooltip({
  children,
  className,
  ...popupOptions
}: MarkerTooltipProps) {
  const { marker, map } = useMarkerContext();
  const container = useMemo(() => document.createElement("div"), []);
  const prevTooltipOptions = useRef(popupOptions);

  const tooltip = useMemo(() => {
    const tooltipInstance = new MapLibreGL.Popup({
      offset: 16,
      ...popupOptions,
      closeOnClick: true,
      closeButton: false,
    }).setMaxWidth("none");

    return tooltipInstance;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!map) return;

    tooltip.setDOMContent(container);

    const handleMouseEnter = () => {
      tooltip.setLngLat(marker.getLngLat()).addTo(map);
    };
    const handleMouseLeave = () => tooltip.remove();

    marker.getElement()?.addEventListener("mouseenter", handleMouseEnter);
    marker.getElement()?.addEventListener("mouseleave", handleMouseLeave);

    return () => {
      marker.getElement()?.removeEventListener("mouseenter", handleMouseEnter);
      marker.getElement()?.removeEventListener("mouseleave", handleMouseLeave);
      tooltip.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  if (tooltip.isOpen()) {
    const prev = prevTooltipOptions.current;

    if (prev.offset !== popupOptions.offset) {
      tooltip.setOffset(popupOptions.offset ?? 16);
    }
    if (prev.maxWidth !== popupOptions.maxWidth && popupOptions.maxWidth) {
      tooltip.setMaxWidth(popupOptions.maxWidth ?? "none");
    }

    prevTooltipOptions.current = popupOptions;
  }

  return createPortal(
    <div
      className={cn(
        "rounded-md bg-foreground px-2 py-1 text-xs text-background shadow-md",
        "animate-in fade-in-0 duration-150 ease-out",
        className
      )}
    >
      {children}
    </div>,
    container
  );
}

type MarkerLabelProps = {
  /** Label text content */
  children: ReactNode;
  /** Additional CSS classes for the label */
  className?: string;
  /** Position of the label relative to the marker (default: "top") */
  position?: "top" | "bottom";
};

function MarkerLabel({
  children,
  className,
  position = "top",
}: MarkerLabelProps) {
  const positionClasses = {
    top: "bottom-full mb-1",
    bottom: "top-full mt-1",
  };

  return (
    <div
      className={cn(
        "absolute left-1/2 -translate-x-1/2 whitespace-nowrap",
        "text-[10px] font-medium text-foreground",
        positionClasses[position],
        className
      )}
    >
      {children}
    </div>
  );
}

type MapControlsProps = {
  /** Position of the controls on the map (default: "bottom-right") */
  position?: "top-left" | "top-right" | "bottom-left" | "bottom-right";
  /** Show zoom in/out buttons (default: true) */
  showZoom?: boolean;
  /** Show compass button to reset bearing (default: false) */
  showCompass?: boolean;
  /** Show locate button to find user's location (default: false) */
  showLocate?: boolean;
  /** Show fullscreen toggle button (default: false) */
  showFullscreen?: boolean;
  /** Show home button to return to initial view (default: false) */
  showHome?: boolean;
  /** Additional CSS classes for the controls container */
  className?: string;
  /** Callback with user coordinates when located */
  onLocate?: (coords: { longitude: number; latitude: number }) => void;
  /** Callback when home button is clicked */
  onHome?: () => void;
  /** Ref to the element to fullscreen instead of the map container */
  fullscreenRef?: React.RefObject<HTMLElement | null>;
};

const positionClasses = {
  "top-left": "top-2 left-2",
  "top-right": "top-2 right-2",
  "bottom-left": "bottom-2 left-2",
  "bottom-right": "bottom-10 right-2",
};

function ControlGroup({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col rounded-md border border-border bg-background shadow-sm overflow-hidden [&>button:not(:last-child)]:border-b [&>button:not(:last-child)]:border-border">
      {children}
    </div>
  );
}

function ControlButton({
  onClick,
  label,
  children,
  disabled = false,
}: {
  onClick: () => void;
  label: string;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      type="button"
      className={cn(
        "flex items-center justify-center size-8 hover:bg-accent dark:hover:bg-accent/40 transition-colors",
        disabled && "opacity-50 pointer-events-none cursor-not-allowed"
      )}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

function MapControls({
  position = "bottom-right",
  showZoom = true,
  showCompass = false,
  showLocate = false,
  showFullscreen = false,
  showHome = false,
  className,
  onLocate,
  onHome,
  fullscreenRef,
}: MapControlsProps) {
  const { map } = useMap();
  const [waitingForLocation, setWaitingForLocation] = useState(false);

  const handleZoomIn = useCallback(() => {
    map?.zoomTo(map.getZoom() + 1, { duration: 300 });
  }, [map]);

  const handleZoomOut = useCallback(() => {
    map?.zoomTo(map.getZoom() - 1, { duration: 300 });
  }, [map]);

  const handleResetBearing = useCallback(() => {
    map?.resetNorthPitch({ duration: 300 });
  }, [map]);

  const handleLocate = useCallback(() => {
    setWaitingForLocation(true);
    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const coords = {
            longitude: pos.coords.longitude,
            latitude: pos.coords.latitude,
          };
          map?.flyTo({
            center: [coords.longitude, coords.latitude],
            zoom: 14,
            duration: 1500,
          });
          onLocate?.(coords);
          setWaitingForLocation(false);
        },
        (error) => {
          console.error("Error getting location:", error);
          setWaitingForLocation(false);
        }
      );
    }
  }, [map, onLocate]);

  const handleFullscreen = useCallback(() => {
    const container = fullscreenRef?.current ?? map?.getContainer();
    if (!container) return;
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      container.requestFullscreen();
    }
  }, [map, fullscreenRef]);

  return (
    <div
      className={cn(
        "absolute z-10 flex flex-col gap-1.5",
        positionClasses[position],
        className
      )}
    >
      {showZoom && (
        <ControlGroup>
          <ControlButton onClick={handleZoomIn} label="Zoom in">
            <Plus className="size-4" />
          </ControlButton>
          <ControlButton onClick={handleZoomOut} label="Zoom out">
            <Minus className="size-4" />
          </ControlButton>
        </ControlGroup>
      )}
      {showCompass && (
        <ControlGroup>
          <CompassButton onClick={handleResetBearing} />
        </ControlGroup>
      )}
      {showHome && onHome && (
        <ControlGroup>
          <ControlButton onClick={onHome} label="Return to home view">
            <Home className="size-4" />
          </ControlButton>
        </ControlGroup>
      )}
      {showLocate && (
        <ControlGroup>
          <ControlButton
            onClick={handleLocate}
            label="Find my location"
            disabled={waitingForLocation}
          >
            {waitingForLocation ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Locate className="size-4" />
            )}
          </ControlButton>
        </ControlGroup>
      )}
      {showFullscreen && (
        <ControlGroup>
          <ControlButton onClick={handleFullscreen} label="Toggle fullscreen">
            <Maximize className="size-4" />
          </ControlButton>
        </ControlGroup>
      )}
    </div>
  );
}

function CompassButton({ onClick }: { onClick: () => void }) {
  const { map } = useMap();
  const compassRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!map || !compassRef.current) return;

    const compass = compassRef.current;

    const updateRotation = () => {
      const bearing = map.getBearing();
      const pitch = map.getPitch();
      compass.style.transform = `rotateX(${pitch}deg) rotateZ(${-bearing}deg)`;
    };

    map.on("rotate", updateRotation);
    map.on("pitch", updateRotation);
    updateRotation();

    return () => {
      map.off("rotate", updateRotation);
      map.off("pitch", updateRotation);
    };
  }, [map]);

  return (
    <ControlButton onClick={onClick} label="Reset bearing to north">
      <svg
        ref={compassRef}
        viewBox="0 0 24 24"
        className="size-5"
        style={{ transformStyle: "preserve-3d" }}
      >
        <path d="M12 2L16 12H12V2Z" className="fill-red-500" />
        <path d="M12 2L8 12H12V2Z" className="fill-red-300" />
        <path d="M12 22L16 12H12V22Z" className="fill-muted-foreground/60" />
        <path d="M12 22L8 12H12V22Z" className="fill-muted-foreground/30" />
      </svg>
    </ControlButton>
  );
}

type MapPopupProps = {
  /** Longitude coordinate for popup position */
  longitude: number;
  /** Latitude coordinate for popup position */
  latitude: number;
  /** Callback when popup is closed */
  onClose?: () => void;
  /** Popup content */
  children: ReactNode;
  /** Additional CSS classes for the popup container */
  className?: string;
  /** Show a close button in the popup (default: false) */
  closeButton?: boolean;
} & Omit<PopupOptions, "className" | "closeButton">;

function MapPopup({
  longitude,
  latitude,
  onClose,
  children,
  className,
  closeButton = false,
  ...popupOptions
}: MapPopupProps) {
  const { map } = useMap();
  const popupOptionsRef = useRef(popupOptions);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const container = useMemo(() => document.createElement("div"), []);

  const popup = useMemo(() => {
    const popupInstance = new MapLibreGL.Popup({
      offset: 16,
      ...popupOptions,
      closeButton: false,
    })
      .setMaxWidth("none")
      .setLngLat([longitude, latitude]);

    return popupInstance;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!map) return;

    const onCloseProp = () => onCloseRef.current?.();

    popup.on("close", onCloseProp);

    popup.setDOMContent(container);
    popup.addTo(map);

    return () => {
      popup.off("close", onCloseProp);
      if (popup.isOpen()) {
        popup.remove();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  if (popup.isOpen()) {
    const prev = popupOptionsRef.current;

    if (
      popup.getLngLat().lng !== longitude ||
      popup.getLngLat().lat !== latitude
    ) {
      popup.setLngLat([longitude, latitude]);
    }

    if (prev.offset !== popupOptions.offset) {
      popup.setOffset(popupOptions.offset ?? 16);
    }
    if (prev.maxWidth !== popupOptions.maxWidth && popupOptions.maxWidth) {
      popup.setMaxWidth(popupOptions.maxWidth ?? "none");
    }
    popupOptionsRef.current = popupOptions;
  }

  const handleClose = () => {
    popup.remove();
  };

  return createPortal(
    <div
      className={cn(
        "relative rounded-md border bg-popover p-3 text-popover-foreground shadow-md",
        "animate-in fade-in-0 slide-in-from-bottom-1 duration-200 ease-out",
        className
      )}
    >
      {closeButton && (
        <button
          type="button"
          onClick={handleClose}
          className="absolute top-1 right-1 z-10 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
          aria-label="Close popup"
        >
          <X className="h-4 w-4" />
          <span className="sr-only">Close</span>
        </button>
      )}
      {children}
    </div>,
    container
  );
}

type MapRouteProps = {
  /** Optional unique identifier for the route layer */
  id?: string;
  /** Array of [longitude, latitude] coordinate pairs defining the route */
  coordinates: [number, number][];
  /** Line color as CSS color value (default: "#4285F4") */
  color?: string;
  /** Line width in pixels (default: 3) */
  width?: number;
  /** Line opacity from 0 to 1 (default: 0.8) */
  opacity?: number;
  /** Dash pattern [dash length, gap length] for dashed lines */
  dashArray?: [number, number];
  /** Callback when the route line is clicked */
  onClick?: () => void;
  /** Callback when mouse enters the route line */
  onMouseEnter?: () => void;
  /** Callback when mouse leaves the route line */
  onMouseLeave?: () => void;
  /** Whether the route is interactive - shows pointer cursor on hover (default: true) */
  interactive?: boolean;
};

function MapRoute({
  id: propId,
  coordinates,
  color = "#4285F4",
  width = 3,
  opacity = 0.8,
  dashArray,
  onClick,
  onMouseEnter,
  onMouseLeave,
  interactive = true,
}: MapRouteProps) {
  const { map, isLoaded } = useMap();
  const autoId = useId();
  const id = propId ?? autoId;
  const sourceId = `route-source-${id}`;
  const layerId = `route-layer-${id}`;

  // Add source and layer on mount
  useEffect(() => {
    if (!isLoaded || !map) return;

    map.addSource(sourceId, {
      type: "geojson",
      data: {
        type: "Feature",
        properties: {},
        geometry: { type: "LineString", coordinates: [] },
      },
    });

    map.addLayer({
      id: layerId,
      type: "line",
      source: sourceId,
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": color,
        "line-width": width,
        "line-opacity": opacity,
        ...(dashArray && { "line-dasharray": dashArray }),
      },
    });

    return () => {
      try {
        if (map.getLayer(layerId)) map.removeLayer(layerId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
      } catch {
        // ignore
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, map]);

  // When coordinates change, update the source data
  useEffect(() => {
    if (!isLoaded || !map || coordinates.length < 2) return;

    const source = map.getSource(sourceId) as MapLibreGL.GeoJSONSource;
    if (source) {
      source.setData({
        type: "Feature",
        properties: {},
        geometry: { type: "LineString", coordinates },
      });
    }
  }, [isLoaded, map, coordinates, sourceId]);

  useEffect(() => {
    if (!isLoaded || !map || !map.getLayer(layerId)) return;

    map.setPaintProperty(layerId, "line-color", color);
    map.setPaintProperty(layerId, "line-width", width);
    map.setPaintProperty(layerId, "line-opacity", opacity);
    if (dashArray) {
      map.setPaintProperty(layerId, "line-dasharray", dashArray);
    }
  }, [isLoaded, map, layerId, color, width, opacity, dashArray]);

  // Handle click and hover events
  useEffect(() => {
    if (!isLoaded || !map || !interactive) return;

    const handleClick = () => {
      onClick?.();
    };
    const handleMouseEnter = () => {
      map.getCanvas().style.cursor = "pointer";
      onMouseEnter?.();
    };
    const handleMouseLeave = () => {
      map.getCanvas().style.cursor = "";
      onMouseLeave?.();
    };

    map.on("click", layerId, handleClick);
    map.on("mouseenter", layerId, handleMouseEnter);
    map.on("mouseleave", layerId, handleMouseLeave);

    return () => {
      map.off("click", layerId, handleClick);
      map.off("mouseenter", layerId, handleMouseEnter);
      map.off("mouseleave", layerId, handleMouseLeave);
    };
  }, [
    isLoaded,
    map,
    layerId,
    onClick,
    onMouseEnter,
    onMouseLeave,
    interactive,
  ]);

  return null;
}

type MapClusterLayerProps<
  P extends GeoJSON.GeoJsonProperties = GeoJSON.GeoJsonProperties
> = {
  /** GeoJSON FeatureCollection data or URL to fetch GeoJSON from */
  data: string | GeoJSON.FeatureCollection<GeoJSON.Point, P>;
  /** Maximum zoom level to cluster points on (default: 14) */
  clusterMaxZoom?: number;
  /** Radius of each cluster when clustering points in pixels (default: 50) */
  clusterRadius?: number;
  /** Colors for cluster circles: [small, medium, large] based on point count (default: ["#22c55e", "#eab308", "#ef4444"]) */
  clusterColors?: [string, string, string];
  /** Point count thresholds for color/size steps: [medium, large] (default: [100, 750]) */
  clusterThresholds?: [number, number];
  /** Color for unclustered individual points (default: "#3b82f6") */
  pointColor?: string;
  /** Callback when an unclustered point is clicked */
  onPointClick?: (
    feature: GeoJSON.Feature<GeoJSON.Point, P>,
    coordinates: [number, number]
  ) => void;
  /** Callback when a cluster is clicked. If not provided, zooms into the cluster */
  onClusterClick?: (
    clusterId: number,
    coordinates: [number, number],
    pointCount: number
  ) => void;
};

function MapClusterLayer<
  P extends GeoJSON.GeoJsonProperties = GeoJSON.GeoJsonProperties
>({
  data,
  clusterMaxZoom = 14,
  clusterRadius = 50,
  clusterColors = ["#22c55e", "#eab308", "#ef4444"],
  clusterThresholds = [100, 750],
  pointColor = "#3b82f6",
  onPointClick,
  onClusterClick,
}: MapClusterLayerProps<P>) {
  const { map, isLoaded } = useMap();
  const id = useId();
  const sourceId = `cluster-source-${id}`;
  const clusterLayerId = `clusters-${id}`;
  const clusterCountLayerId = `cluster-count-${id}`;
  const unclusteredLayerId = `unclustered-point-${id}`;

  const stylePropsRef = useRef({
    clusterColors,
    clusterThresholds,
    pointColor,
  });

  // Add source and layers on mount
  useEffect(() => {
    if (!isLoaded || !map) return;

    // Add clustered GeoJSON source
    map.addSource(sourceId, {
      type: "geojson",
      data,
      cluster: true,
      clusterMaxZoom,
      clusterRadius,
    });

    // Add cluster circles layer
    map.addLayer({
      id: clusterLayerId,
      type: "circle",
      source: sourceId,
      filter: ["has", "point_count"],
      paint: {
        "circle-color": [
          "step",
          ["get", "point_count"],
          clusterColors[0],
          clusterThresholds[0],
          clusterColors[1],
          clusterThresholds[1],
          clusterColors[2],
        ],
        "circle-radius": [
          "step",
          ["get", "point_count"],
          20,
          clusterThresholds[0],
          30,
          clusterThresholds[1],
          40,
        ],
        "circle-stroke-width": 1,
        "circle-stroke-color": "#fff",
        "circle-opacity": 0.85,
      },
    });

    // Add cluster count text layer
    map.addLayer({
      id: clusterCountLayerId,
      type: "symbol",
      source: sourceId,
      filter: ["has", "point_count"],
      layout: {
        "text-field": "{point_count_abbreviated}",
        "text-font": ["Open Sans Regular", "Arial Unicode MS Regular"],
        "text-size": 12,
      },
      paint: {
        "text-color": "#fff",
      },
    });

    // Add unclustered point layer
    map.addLayer({
      id: unclusteredLayerId,
      type: "circle",
      source: sourceId,
      filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-color": pointColor,
        "circle-radius": 5,
        "circle-stroke-width": 2,
        "circle-stroke-color": "#fff",
      },
    });

    return () => {
      try {
        if (map.getLayer(clusterCountLayerId))
          map.removeLayer(clusterCountLayerId);
        if (map.getLayer(unclusteredLayerId))
          map.removeLayer(unclusteredLayerId);
        if (map.getLayer(clusterLayerId)) map.removeLayer(clusterLayerId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
      } catch {
        // ignore
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, map, sourceId]);

  // Update source data when data prop changes (only for non-URL data)
  useEffect(() => {
    if (!isLoaded || !map || typeof data === "string") return;

    const source = map.getSource(sourceId) as MapLibreGL.GeoJSONSource;
    if (source) {
      source.setData(data);
    }
  }, [isLoaded, map, data, sourceId]);

  // Update layer styles when props change
  useEffect(() => {
    if (!isLoaded || !map) return;

    const prev = stylePropsRef.current;
    const colorsChanged =
      prev.clusterColors !== clusterColors ||
      prev.clusterThresholds !== clusterThresholds;

    // Update cluster layer colors and sizes
    if (map.getLayer(clusterLayerId) && colorsChanged) {
      map.setPaintProperty(clusterLayerId, "circle-color", [
        "step",
        ["get", "point_count"],
        clusterColors[0],
        clusterThresholds[0],
        clusterColors[1],
        clusterThresholds[1],
        clusterColors[2],
      ]);
      map.setPaintProperty(clusterLayerId, "circle-radius", [
        "step",
        ["get", "point_count"],
        20,
        clusterThresholds[0],
        30,
        clusterThresholds[1],
        40,
      ]);
    }

    // Update unclustered point layer color
    if (map.getLayer(unclusteredLayerId) && prev.pointColor !== pointColor) {
      map.setPaintProperty(unclusteredLayerId, "circle-color", pointColor);
    }

    stylePropsRef.current = { clusterColors, clusterThresholds, pointColor };
  }, [
    isLoaded,
    map,
    clusterLayerId,
    unclusteredLayerId,
    clusterColors,
    clusterThresholds,
    pointColor,
  ]);

  // Handle click events
  useEffect(() => {
    if (!isLoaded || !map) return;

    // Cluster click handler - zoom into cluster
    const handleClusterClick = async (
      e: MapLibreGL.MapMouseEvent & {
        features?: MapLibreGL.MapGeoJSONFeature[];
      }
    ) => {
      const features = map.queryRenderedFeatures(e.point, {
        layers: [clusterLayerId],
      });
      if (!features.length) return;

      const feature = features[0];
      const clusterId = feature.properties?.cluster_id as number;
      const pointCount = feature.properties?.point_count as number;
      const coordinates = (feature.geometry as GeoJSON.Point).coordinates as [
        number,
        number
      ];

      if (onClusterClick) {
        onClusterClick(clusterId, coordinates, pointCount);
      } else {
        // Default behavior: zoom to cluster expansion zoom
        const source = map.getSource(sourceId) as MapLibreGL.GeoJSONSource;
        const zoom = await source.getClusterExpansionZoom(clusterId);
        map.easeTo({
          center: coordinates,
          zoom,
        });
      }
    };

    // Unclustered point click handler
    const handlePointClick = (
      e: MapLibreGL.MapMouseEvent & {
        features?: MapLibreGL.MapGeoJSONFeature[];
      }
    ) => {
      if (!onPointClick || !e.features?.length) return;

      const feature = e.features[0];
      const coordinates = (
        feature.geometry as GeoJSON.Point
      ).coordinates.slice() as [number, number];

      // Handle world copies
      while (Math.abs(e.lngLat.lng - coordinates[0]) > 180) {
        coordinates[0] += e.lngLat.lng > coordinates[0] ? 360 : -360;
      }

      e.preventDefault();
      onPointClick(
        feature as unknown as GeoJSON.Feature<GeoJSON.Point, P>,
        coordinates
      );
    };

    // Cursor style handlers
    const handleMouseEnterCluster = () => {
      map.getCanvas().style.cursor = "pointer";
    };
    const handleMouseLeaveCluster = () => {
      map.getCanvas().style.cursor = "";
    };
    const handleMouseEnterPoint = () => {
      if (onPointClick) {
        map.getCanvas().style.cursor = "pointer";
      }
    };
    const handleMouseLeavePoint = () => {
      map.getCanvas().style.cursor = "";
    };

    map.on("click", clusterLayerId, handleClusterClick);
    map.on("click", unclusteredLayerId, handlePointClick);
    map.on("mouseenter", clusterLayerId, handleMouseEnterCluster);
    map.on("mouseleave", clusterLayerId, handleMouseLeaveCluster);
    map.on("mouseenter", unclusteredLayerId, handleMouseEnterPoint);
    map.on("mouseleave", unclusteredLayerId, handleMouseLeavePoint);

    return () => {
      map.off("click", clusterLayerId, handleClusterClick);
      map.off("click", unclusteredLayerId, handlePointClick);
      map.off("mouseenter", clusterLayerId, handleMouseEnterCluster);
      map.off("mouseleave", clusterLayerId, handleMouseLeaveCluster);
      map.off("mouseenter", unclusteredLayerId, handleMouseEnterPoint);
      map.off("mouseleave", unclusteredLayerId, handleMouseLeavePoint);
    };
  }, [
    isLoaded,
    map,
    clusterLayerId,
    unclusteredLayerId,
    sourceId,
    onClusterClick,
    onPointClick,
  ]);

  return null;
}

type MapPointLayerProps<
  P extends GeoJSON.GeoJsonProperties = GeoJSON.GeoJsonProperties
> = {
  data: string | GeoJSON.FeatureCollection<GeoJSON.Point, P>;
  pointColor?: string;
  pointRadius?: number;
  strokeColor?: string;
  strokeWidth?: number;
  /**
   * Optional icon image rendered as the marker (e.g. a brand mark or pin).
   * When present, the underlying circle layer is kept for click/hover
   * hit-testing (icons can be lossy at very low zooms) but painted
   * transparent so the icon stands alone. The image is loaded once and
   * re-registered on every style change (MapLibre wipes custom images when
   * the style is swapped, e.g. light↔dark theme toggle).
   */
  iconImage?: string;
  /**
   * Optional alternate icon swapped in per-feature when the feature's
   * ``selectedProperty`` is truthy. Both icons are registered up front so
   * the swap is a pure data-driven style change with no extra network or
   * decode hop. Has no effect without ``iconImage``.
   */
  iconImageSelected?: string;
  /**
   * Feature-property key (boolean) that flips a marker to its selected
   * icon. Defaults to ``"selected"``. The feature property must be present
   * on every feature for the data-driven expression to evaluate cleanly.
   */
  selectedProperty?: string;
  /**
   * Scale factor passed to MapLibre `icon-size`.
   *
   * Accepts a plain number for a fixed size, or a MapLibre expression
   * (e.g. `["interpolate", ["linear"], ["zoom"], 8, 0.6, 18, 0.3]`) for
   * zoom-dependent sizing. The latter is useful when a marker needs to
   * pop at low zoom (where many points stack) and shrink at high zoom
   * (to avoid covering building footprints). The type is intentionally
   * loose (`number | unknown[]`) because MapLibre's
   * `DataDrivenPropertyValueSpecification` types collide noisily with
   * inline literal expressions; the layer passes the value straight to
   * `setLayoutProperty("icon-size", ...)` which handles both.
   */
  iconSize?: number | unknown[];
  /**
   * Anchor point of the icon relative to its geographic coordinate.
   * Defaults to ``"center"`` (a brand mark sits centered on the point).
   * Use ``"bottom"`` for pins where the tip is the geographic anchor.
   */
  iconAnchor?:
    | "center"
    | "left"
    | "right"
    | "top"
    | "bottom"
    | "top-left"
    | "top-right"
    | "bottom-left"
    | "bottom-right";
  /**
   * Pixel ratio for the registered image. Higher values yield crisper
   * rendering on HiDPI displays but require larger source PNGs.
   */
  iconPixelRatio?: number;
  /**
   * Feature-property key whose value is shown in a lightweight hover label
   * popup. Driven directly off MapLibre events (no React state) so cursor
   * tracking stays smooth across hundreds of markers.
   */
  hoverLabelProperty?: keyof P & string;
  /**
   * Opt-in clustering. When ``true``, the underlying GeoJSON source enables
   * MapLibre's built-in supercluster (``cluster: true``), and two extra
   * layers are added on top of the existing pin/circle stack:
   *
   *   1. A "cluster bubble" circle layer (filtered to features that have
   *      ``point_count``) sized by count.
   *   2. A count-label symbol layer on top of the bubble.
   *
   * The original circle and symbol layers are filtered to
   * ``["!", ["has", "point_count"]]`` so individual pins only render when
   * a feature is NOT inside a cluster. Clicking a cluster eases the map
   * to the cluster's expansion zoom (``source.getClusterExpansionZoom``).
   *
   * Defaults are tuned for "tens of markers within a campus" — see
   * ``clusterMaxZoom`` and ``clusterRadius``. Off by default; turning it
   * on doesn't affect non-clustered consumers of the layer.
   */
  cluster?: boolean;
  /**
   * Maximum zoom at which clustering is active. At this zoom and below,
   * nearby features collapse into a count bubble; above this zoom,
   * everything renders as individual pins. Default ``13`` — neighborhood
   * scale, the zoom where individual buildings start to be distinguishable.
   */
  clusterMaxZoom?: number;
  /**
   * Pixel radius within which two features merge into the same cluster at
   * the current zoom. Default ``50`` — empirically tight enough that a
   * campus collapses but two distinct campuses 10 km apart stay separate
   * at city zoom.
   */
  clusterRadius?: number;
  /**
   * Fill color for cluster bubbles. Defaults to ``pointColor`` so clusters
   * feel like "more of the same thing" rather than a different category.
   */
  clusterColor?: string;
  /**
   * Color of the count text drawn on top of the cluster bubble. Default
   * ``"#ffffff"`` — high contrast against any colored bubble.
   */
  clusterTextColor?: string;
  onPointClick?: (
    feature: GeoJSON.Feature<GeoJSON.Point, P>,
    coordinates: [number, number]
  ) => void;
  /**
   * Fires once per "hover session" when the cursor enters a non-clustered
   * marker. Deduped by feature identity, so dragging the cursor across a
   * single pin fires this exactly once (not once per ``mousemove`` pixel),
   * and re-entering the same pin while still listed as "current" does not
   * re-fire. Re-fires after the cursor leaves any pin.
   *
   * Intended for opt-in prefetch: a click on a marker typically follows
   * an intentional hover by ~200–500ms, which is enough head start to
   * fully hide a one-hop backend fetch behind the user's own gesture.
   * Routing this through ``mouseenter`` would also work but fires
   * unreliably when icons overlap; deduping off ``mousemove`` is robust.
   */
  onPointHover?: (feature: GeoJSON.Feature<GeoJSON.Point, P>) => void;
};

function MapPointLayer<
  P extends GeoJSON.GeoJsonProperties = GeoJSON.GeoJsonProperties
>({
  data,
  pointColor = "#3b82f6",
  pointRadius = 5,
  strokeColor = "#fff",
  strokeWidth = 2,
  iconImage,
  iconImageSelected,
  selectedProperty = "selected",
  iconSize = 0.1,
  iconAnchor = "center",
  iconPixelRatio = 2,
  hoverLabelProperty,
  cluster = false,
  clusterMaxZoom = 13,
  clusterRadius = 50,
  clusterColor,
  clusterTextColor = "#ffffff",
  onPointClick,
  onPointHover,
}: MapPointLayerProps<P>) {
  const { map, isLoaded } = useMap();
  const id = useId();
  const sourceId = `point-source-${id}`;
  const layerId = `point-layer-${id}`;
  const iconLayerId = `point-icon-layer-${id}`;
  const clusterLayerId = `point-cluster-${id}`;
  const clusterCountLayerId = `point-cluster-count-${id}`;
  // MapLibre image registry is global per-map; namespace by the layer id so
  // multiple MapPointLayer instances on the same map can each register their
  // own icon without collision.
  const iconImageId = `point-icon-${id}`;
  const iconImageSelectedId = `point-icon-selected-${id}`;

  const stylePropsRef = useRef({ pointColor, pointRadius, strokeColor, strokeWidth, iconSize });
  // Effective cluster bubble color: prefer explicit clusterColor, otherwise
  // inherit pointColor so the bubble reads as "many of these pins".
  const effectiveClusterColor = clusterColor ?? pointColor;

  useEffect(() => {
    if (!isLoaded || !map) return;

    map.addSource(sourceId, {
      type: "geojson",
      data: typeof data === "string" ? data : { type: "FeatureCollection", features: [] },
      // Supercluster wiring is opt-in. With cluster=true, MapLibre groups
      // features whose screen centroids fall within ``clusterRadius`` px at
      // the current zoom (up to ``clusterMaxZoom``). Clustered features
      // gain ``point_count`` / ``cluster_id`` properties and lose their
      // original properties — which is why the icon/circle layers below
      // filter to ``["!", ["has", "point_count"]]``.
      ...(cluster ? { cluster: true, clusterMaxZoom, clusterRadius } : {}),
    });

    // Filter the per-pin layers to non-cluster features when clustering is
    // on. Without the filter, MapLibre would try to render a pin icon at
    // each cluster's centroid (with no ``selected`` property), which both
    // looks wrong and steals the click from the cluster bubble.
    const nonClusterFilter = cluster
      ? (["!", ["has", "point_count"]] as never)
      : undefined;

    map.addLayer({
      id: layerId,
      type: "circle",
      source: sourceId,
      ...(nonClusterFilter ? { filter: nonClusterFilter } : {}),
      paint: {
        "circle-color": pointColor,
        "circle-radius": pointRadius,
        "circle-stroke-width": strokeWidth,
        "circle-stroke-color": strokeColor,
        // When an icon will be stacked on top, hide the circle paint but
        // keep the layer alive for click/hover hit-testing — the invisible
        // disc is also a forgiving target if the user clicks just outside
        // the icon's silhouette.
        "circle-opacity": iconImage ? 0 : 1,
        "circle-stroke-opacity": iconImage ? 0 : 1,
      },
    });

    if (cluster) {
      // Cluster bubble. Sized by count via a ``step`` expression — keeps
      // small clusters compact (a 2-pin cluster shouldn't dominate the
      // map) while large clusters get visually weightier so dense
      // metropolitan regions stand out. The thresholds are tuned for the
      // PHK use case (tens, not thousands) but step expressions degrade
      // gracefully if a consumer drops in 10000 features.
      map.addLayer({
        id: clusterLayerId,
        type: "circle",
        source: sourceId,
        filter: ["has", "point_count"],
        paint: {
          "circle-color": effectiveClusterColor,
          "circle-stroke-color": strokeColor,
          "circle-stroke-width": 2,
          "circle-radius": [
            "step",
            ["get", "point_count"],
            14,
            10, 18,
            50, 22,
            200, 28,
          ],
        },
      });

      // Count label on top of the bubble. ``text-allow-overlap`` mirrors
      // ``icon-allow-overlap`` on the pin layer so labels don't pop in/out
      // as the cursor moves.
      map.addLayer({
        id: clusterCountLayerId,
        type: "symbol",
        source: sourceId,
        filter: ["has", "point_count"],
        layout: {
          "text-field": ["get", "point_count_abbreviated"],
          "text-font": ["Open Sans Semibold", "Arial Unicode MS Bold"],
          "text-size": 12,
          "text-allow-overlap": true,
          "text-ignore-placement": true,
        },
        paint: {
          "text-color": clusterTextColor,
        },
      });
    }

    let cancelled = false;
    if (iconImage) {
      // Register both variants (default and optional selected) up front, then
      // add the symbol layer once with a data-driven `icon-image` expression.
      // `loadImage` returns a Promise; we `Promise.all` so the layer is added
      // exactly once and the per-feature selected swap is a free GPU-side
      // change rather than a layer re-render. `addImage` throws if the id
      // already exists, so guard with `hasImage` — common on hot reload and
      // style swap.
      const targets: { src: string; id: string }[] = [
        { src: iconImage, id: iconImageId },
      ];
      if (iconImageSelected) {
        targets.push({ src: iconImageSelected, id: iconImageSelectedId });
      }

      Promise.all(
        targets.map(({ src, id: imgId }) =>
          map.loadImage(src).then((response) => ({ id: imgId, data: response?.data })),
        ),
      )
        .then((results) => {
          if (cancelled) return;
          for (const { id: imgId, data } of results) {
            if (!data) continue;
            if (!map.hasImage(imgId)) {
              map.addImage(imgId, data, { pixelRatio: iconPixelRatio });
            }
          }
          if (!map.getLayer(iconLayerId)) {
            // Data-driven expression: per-feature pick the selected icon
            // when the feature property flips to true. Inline-typed via the
            // `as never` cast — maplibre-gl's TypeScript surface doesn't
            // export `ExpressionSpecification`, but the runtime accepts any
            // valid expression here.
            const iconImageExpr = (
              iconImageSelected
                ? [
                    "case",
                    ["==", ["get", selectedProperty], true],
                    iconImageSelectedId,
                    iconImageId,
                  ]
                : iconImageId
            ) as never;
            map.addLayer({
              id: iconLayerId,
              type: "symbol",
              source: sourceId,
              // When clustering is enabled, only render pin icons for
              // features that escaped clustering (no ``point_count``
              // property). Inside a cluster, the bubble layer above is
              // doing the visual work.
              ...(cluster ? { filter: ["!", ["has", "point_count"]] as never } : {}),
              layout: {
                "icon-image": iconImageExpr,
                // ``iconSize`` is widened to ``number | unknown[]`` so callers
                // can pass a zoom-interpolated expression; MapLibre's
                // ``DataDrivenPropertyValueSpecification`` overload set is
                // strict about inline literal tuples, so we cast the same
                // way we do for ``icon-image`` just above.
                "icon-size": iconSize as never,
                "icon-allow-overlap": true,
                "icon-ignore-placement": true,
                "icon-anchor": iconAnchor,
              },
            });
          }
        })
        .catch(() => {
          // image fetch failed — the colored circle alone is still a valid
          // fallback marker, so swallow rather than throwing.
        });
    }

    return () => {
      cancelled = true;
      try {
        if (map.getLayer(clusterCountLayerId)) map.removeLayer(clusterCountLayerId);
        if (map.getLayer(clusterLayerId)) map.removeLayer(clusterLayerId);
        if (map.getLayer(iconLayerId)) map.removeLayer(iconLayerId);
        if (map.getLayer(layerId)) map.removeLayer(layerId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
        if (map.hasImage(iconImageId)) map.removeImage(iconImageId);
        if (map.hasImage(iconImageSelectedId)) map.removeImage(iconImageSelectedId);
      } catch {
        // ignore
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    isLoaded,
    map,
    sourceId,
    iconImage,
    iconImageSelected,
    // Cluster props are in deps so toggling clustering at runtime tears
    // down and rebuilds the source + layers cleanly. In practice most
    // consumers set these once; this is just for safety.
    cluster,
    clusterMaxZoom,
    clusterRadius,
  ]);

  useEffect(() => {
    if (!isLoaded || !map || typeof data === "string") return;

    const source = map.getSource(sourceId) as MapLibreGL.GeoJSONSource;
    if (source) {
      source.setData(data);
    }
  }, [isLoaded, map, data, sourceId]);

  useEffect(() => {
    if (!isLoaded || !map || !map.getLayer(layerId)) return;

    const prev = stylePropsRef.current;
    if (prev.pointColor !== pointColor)
      map.setPaintProperty(layerId, "circle-color", pointColor);
    if (prev.pointRadius !== pointRadius)
      map.setPaintProperty(layerId, "circle-radius", pointRadius);
    if (prev.strokeColor !== strokeColor)
      map.setPaintProperty(layerId, "circle-stroke-color", strokeColor);
    if (prev.strokeWidth !== strokeWidth)
      map.setPaintProperty(layerId, "circle-stroke-width", strokeWidth);
    if (prev.iconSize !== iconSize && map.getLayer(iconLayerId)) {
      map.setLayoutProperty(iconLayerId, "icon-size", iconSize as never);
    }

    stylePropsRef.current = { pointColor, pointRadius, strokeColor, strokeWidth, iconSize };
  }, [isLoaded, map, layerId, iconLayerId, pointColor, pointRadius, strokeColor, strokeWidth, iconSize]);

  useEffect(() => {
    if (!isLoaded || !map) return;

    // Dedupe across the two layer-scoped listeners. The icon layer sits
    // directly on top of the invisible circle hit area, so a single user
    // click resolves to ``click`` events on BOTH layers. Without dedupe
    // ``onPointClick`` fires twice per click, which (a) double-calls the
    // consumer's ``setState`` + ``panTo`` and (b) makes the second
    // ``flyTo`` cancel the first mid-arc — extremely visible from a
    // fully zoomed-out view where the long Van Wijk flight gets
    // hijacked partway and restarts from a random intermediate camera
    // pose. The fix is a per-click WeakSet keyed on the underlying
    // ``originalEvent`` so each browser click only fires our callback
    // once regardless of how many layer listeners observe it.
    const seenEvents = new WeakSet<Event>();

    const handleClick = (
      e: MapLibreGL.MapMouseEvent & {
        features?: MapLibreGL.MapGeoJSONFeature[];
      }
    ) => {
      if (!onPointClick || !e.features?.length) return;
      if (e.originalEvent && seenEvents.has(e.originalEvent)) return;
      if (e.originalEvent) seenEvents.add(e.originalEvent);

      const feature = e.features[0];
      const coordinates = (
        feature.geometry as GeoJSON.Point
      ).coordinates.slice() as [number, number];

      while (Math.abs(e.lngLat.lng - coordinates[0]) > 180) {
        coordinates[0] += e.lngLat.lng > coordinates[0] ? 360 : -360;
      }

      e.preventDefault();
      onPointClick(
        feature as unknown as GeoJSON.Feature<GeoJSON.Point, P>,
        coordinates
      );
    };

    const handleMouseEnter = () => {
      if (onPointClick) map.getCanvas().style.cursor = "pointer";
    };
    const handleMouseLeave = () => {
      map.getCanvas().style.cursor = "";
    };

    // Listen on both layers so a click on the icon (which sits on top of the
    // circle) counts the same as a click on the circle backdrop. The
    // ``seenEvents`` dedupe above ensures only one fires per browser click.
    map.on("click", layerId, handleClick);
    map.on("click", iconLayerId, handleClick);
    map.on("mouseenter", layerId, handleMouseEnter);
    map.on("mouseenter", iconLayerId, handleMouseEnter);
    map.on("mouseleave", layerId, handleMouseLeave);
    map.on("mouseleave", iconLayerId, handleMouseLeave);

    return () => {
      map.off("click", layerId, handleClick);
      map.off("click", iconLayerId, handleClick);
      map.off("mouseenter", layerId, handleMouseEnter);
      map.off("mouseenter", iconLayerId, handleMouseEnter);
      map.off("mouseleave", layerId, handleMouseLeave);
      map.off("mouseleave", iconLayerId, handleMouseLeave);
    };
  }, [isLoaded, map, layerId, iconLayerId, onPointClick]);

  useEffect(() => {
    if (!isLoaded || !map || !hoverLabelProperty) return;

    // Reusable popup driven by mouse events directly — avoids a React
    // re-render per cursor move on a 100+ marker map.
    const popup = new MapLibreGL.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 12,
      className: "map-point-label",
    });

    const handleMove = (
      e: MapLibreGL.MapMouseEvent & { features?: MapLibreGL.MapGeoJSONFeature[] }
    ) => {
      const feature = e.features?.[0];
      if (!feature) return;
      const props = feature.properties as Record<string, unknown> | null;
      const label = props?.[hoverLabelProperty];
      if (typeof label !== "string" || !label) return;
      const coords = (feature.geometry as GeoJSON.Point).coordinates as [number, number];
      const lng = coords[0];
      const lat = coords[1];
      // World-copies safety: keep the popup near the cursor's hemisphere.
      let displayLng = lng;
      while (Math.abs(e.lngLat.lng - displayLng) > 180) {
        displayLng += e.lngLat.lng > displayLng ? 360 : -360;
      }
      // Globals.css makes the popup chrome transparent (so popups can carry
      // their own styled content), so the inline div has to render its own
      // background, border, and shadow. Tokens come from shadcn theme so the
      // pill follows light/dark mode automatically.
      popup
        .setLngLat([displayLng, lat])
        .setHTML(
          `<div style="font-size:11px;font-weight:500;white-space:nowrap;padding:4px 8px;background:var(--popover);color:var(--popover-foreground);border:1px solid var(--border);border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.12);">${escapeHtml(label)}</div>`
        )
        .addTo(map);
    };

    const handleLeave = () => {
      popup.remove();
    };

    map.on("mousemove", layerId, handleMove);
    map.on("mousemove", iconLayerId, handleMove);
    map.on("mouseleave", layerId, handleLeave);
    map.on("mouseleave", iconLayerId, handleLeave);

    return () => {
      map.off("mousemove", layerId, handleMove);
      map.off("mousemove", iconLayerId, handleMove);
      map.off("mouseleave", layerId, handleLeave);
      map.off("mouseleave", iconLayerId, handleLeave);
      popup.remove();
    };
  }, [isLoaded, map, layerId, iconLayerId, hoverLabelProperty]);

  // Hover-prefetch hook. Fires ``onPointHover`` once per "hover session" so
  // a consumer can call ``queryClient.prefetchQuery(...)`` and have the
  // request in flight (or done) by the time the user clicks. Deduped by
  // a feature-identity key on a ref so dragging the cursor across a single
  // pin doesn't fire the callback every ``mousemove`` pixel; the key
  // resets when the cursor leaves all pins.
  //
  // The handlers run alongside the hover-label effect on purpose — they
  // share the same layers, but the hover-label effect is gated on
  // ``hoverLabelProperty`` and we want this one to be independent. A
  // ``cluster=true`` source still gets its non-cluster filter applied to
  // ``layerId`` / ``iconLayerId``, so cluster bubbles never reach here.
  useEffect(() => {
    if (!isLoaded || !map || !onPointHover) return;

    // Key the dedupe by the feature's own ``id`` if available (set by
    // ``promoteId`` on the source), otherwise fall back to the layer id
    // + the stringified geometry coords — stable enough for our needs
    // since two pins on the same point would prefetch the same data
    // anyway.
    const featureKey = (
      f: MapLibreGL.MapGeoJSONFeature,
    ): string => {
      if (f.id != null) return String(f.id);
      const coords = (f.geometry as GeoJSON.Point).coordinates;
      return `${coords[0]},${coords[1]}`;
    };

    let currentKey: string | null = null;

    const handleMove = (
      e: MapLibreGL.MapMouseEvent & { features?: MapLibreGL.MapGeoJSONFeature[] },
    ) => {
      const feature = e.features?.[0];
      if (!feature) return;
      const key = featureKey(feature);
      if (key === currentKey) return;
      currentKey = key;
      onPointHover(feature as unknown as GeoJSON.Feature<GeoJSON.Point, P>);
    };

    const handleLeave = () => {
      currentKey = null;
    };

    map.on("mousemove", layerId, handleMove);
    map.on("mousemove", iconLayerId, handleMove);
    map.on("mouseleave", layerId, handleLeave);
    map.on("mouseleave", iconLayerId, handleLeave);

    return () => {
      map.off("mousemove", layerId, handleMove);
      map.off("mousemove", iconLayerId, handleMove);
      map.off("mouseleave", layerId, handleLeave);
      map.off("mouseleave", iconLayerId, handleLeave);
    };
  }, [isLoaded, map, layerId, iconLayerId, onPointHover]);

  // Cluster click + hover. Clicking a cluster bubble zooms the map to the
  // expansion zoom for that cluster, which is the lowest zoom at which the
  // cluster breaks apart. We use ``getClusterExpansionZoom`` (asynchronous)
  // and ``easeTo`` for a smooth transition; a bare ``setZoom`` is jarring
  // when the user came in from a global view.
  useEffect(() => {
    if (!isLoaded || !map || !cluster) return;

    const handleClusterClick = async (
      e: MapLibreGL.MapMouseEvent & { features?: MapLibreGL.MapGeoJSONFeature[] },
    ) => {
      const feature = e.features?.[0];
      if (!feature) return;
      const clusterId = feature.properties?.cluster_id as number | undefined;
      if (clusterId == null) return;
      const coordinates = (feature.geometry as GeoJSON.Point).coordinates as [number, number];
      e.preventDefault();
      const source = map.getSource(sourceId) as MapLibreGL.GeoJSONSource | undefined;
      if (!source) return;
      try {
        const zoom = await source.getClusterExpansionZoom(clusterId);
        map.easeTo({ center: coordinates, zoom, duration: 500 });
      } catch {
        // Supercluster occasionally rejects mid-pan; ignore — the user can
        // click again or zoom manually.
      }
    };

    const handleEnter = () => {
      map.getCanvas().style.cursor = "pointer";
    };
    const handleLeave = () => {
      map.getCanvas().style.cursor = "";
    };

    map.on("click", clusterLayerId, handleClusterClick);
    map.on("mouseenter", clusterLayerId, handleEnter);
    map.on("mouseleave", clusterLayerId, handleLeave);

    return () => {
      map.off("click", clusterLayerId, handleClusterClick);
      map.off("mouseenter", clusterLayerId, handleEnter);
      map.off("mouseleave", clusterLayerId, handleLeave);
    };
  }, [isLoaded, map, cluster, clusterLayerId, sourceId]);

  return null;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export {
  Map,
  useMap,
  MapMarker,
  MarkerContent,
  MarkerPopup,
  MarkerTooltip,
  MarkerLabel,
  MapPopup,
  MapControls,
  MapRoute,
  MapClusterLayer,
  MapPointLayer,
};

export type { MapRef, MapViewport };
