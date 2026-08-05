import { useEffect, useMemo, useRef, useState } from "react";
import { Crosshair, Maximize2, Move, ZoomIn, ZoomOut } from "lucide-react";
import Map from "ol/Map.js";
import View from "ol/View.js";
import WebGLTileLayer from "ol/layer/WebGLTile.js";
import GeoTIFF from "ol/source/GeoTIFF.js";
import Projection from "ol/proj/Projection.js";
import { createEmpty, extend, getCenter, type Extent } from "ol/extent.js";
import { defaults as defaultInteractions } from "ol/interaction/defaults.js";
import DragPan from "ol/interaction/DragPan.js";
import { unByKey } from "ol/Observable.js";
import type BaseEvent from "ol/events/Event.js";
import "ol/ol.css";
import { inputApi, mapStateApi } from "../../api/taichiFlowAdapter";
import { IconButton } from "../../components/IconButton";
import { RasterLegend } from "../../components/RasterLegend";
import { RasterPreparationState } from "../../components/RasterPreparationState";
import type { RasterSymbology } from "../../components/RasterSymbologyPanel";
import {
  DEFAULT_RASTER_SYMBOLOGY,
  useRasterViewportOptional,
} from "../../contexts/RasterViewportContext";
import type { MapLayerState, RasterIdentifyResponse, RasterProfile } from "../../types";

export type RasterViewportLayer = { fileId: string; name: string; family: string };

type RasterMapViewportProps = {
  projectId?: string;
  visibleLayers?: RasterViewportLayer[];
  selectedLayerId?: string;
  onSelectedLayerChange?: (assetId: string) => void;
  activeModule?: string;
};

type RasterTool = "pan" | "identify";

const VIEW_PADDING: [number, number, number, number] = [48, 24, 96, 240];
const RAMP: Array<[number, string]> = [
  [0, "#2563eb"],
  [0.25, "#22d3ee"],
  [0.5, "#22c55e"],
  [0.75, "#facc15"],
  [1, "#ef4444"],
];

function profileExtent(profile: RasterProfile): Extent | null {
  if (!profile.bounds) return null;
  return [profile.bounds.xmin, profile.bounds.ymin, profile.bounds.xmax, profile.bounds.ymax];
}

function compatibleGrid(base: RasterProfile | undefined, candidate: RasterProfile) {
  if (!base || !base.bounds || !candidate.bounds || !base.transform || !candidate.transform) return true;
  if (base.crs || candidate.crs) return base.crs === candidate.crs;
  const sameShape = base.width === candidate.width && base.height === candidate.height;
  const keys = ["a", "b", "c", "d", "e", "f"] as const;
  const sameTransform = keys.every((key) => {
    const left = Number(base.transform?.[key]);
    const right = Number(candidate.transform?.[key]);
    const tolerance = Math.max(1e-9, Math.max(Math.abs(left), Math.abs(right)) * 1e-9);
    return Math.abs(left - right) <= tolerance;
  });
  return sameShape && sameTransform;
}

function colourExpression(profile: RasterProfile, symbology: RasterSymbology): unknown {
  const statistics = profile.statistics || {};
  const sourceMin = Number.isFinite(Number(statistics.min)) ? Number(statistics.min) : 0;
  const sourceMax = Number.isFinite(Number(statistics.max)) && Number(statistics.max) > sourceMin ? Number(statistics.max) : sourceMin + 1;
  let min = sourceMin;
  let max = sourceMax;
  if (symbology.stretch === "stddev" && statistics.mean != null && statistics.stddev != null) {
    min = Number(statistics.mean) - 2 * Number(statistics.stddev);
    max = Number(statistics.mean) + 2 * Number(statistics.stddev);
  }
  if (symbology.stretch === "percent_clip" && statistics.histogram?.edges?.length === 257) {
    const counts = statistics.histogram.counts;
    const total = counts.reduce((sum, count) => sum + count, 0);
    const quantile = (fraction: number) => {
      if (!total) return sourceMin;
      const target = total * fraction;
      let running = 0;
      for (let index = 0; index < counts.length; index += 1) {
        running += counts[index];
        if (running >= target) return Number(statistics.histogram?.edges[index] ?? sourceMin);
      }
      return sourceMax;
    };
    min = quantile(0.02);
    max = quantile(0.98);
  }
  if (!(max > min)) max = min + 1;
  const continuous = profile.data_kind !== "categorical";
  const colors = RAMP.map(([, color]) => color);
  let expression: unknown;
  if (!continuous && statistics.unique_values?.length) {
    const match: unknown[] = ["match", ["band", 1]];
    statistics.unique_values.slice(0, 256).forEach((item, index) => {
      const numeric = typeof item.value === "number" ? item.value : Number(item.value);
      if (!Number.isFinite(numeric)) return;
      match.push(numeric, colors[index % colors.length]);
    });
    match.push([0, 0, 0, 0]);
    expression = match;
  } else {
    const interpolate: unknown[] = ["interpolate", ["linear"], ["band", 1]];
    RAMP.forEach(([position, color]) => interpolate.push(min + (max - min) * position, color));
    expression = interpolate;
  }
  if (profile.nodata == null || typeof profile.nodata !== "number") return expression;
  return ["case", ["==", ["band", 1], profile.nodata], [0, 0, 0, 0], expression];
}

function sourceProfileSignature(profiles: Record<string, RasterProfile>) {
  return Object.entries(profiles).map(([id, profile]) => `${id}:${profile.status}:${profile.cog_url || ""}`).sort().join("|");
}

export function RasterMapViewport({
  projectId,
  visibleLayers = [],
  selectedLayerId,
  onSelectedLayerChange,
}: RasterMapViewportProps) {
  const viewport = useRasterViewportOptional();
  const targetRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const dragPanRef = useRef<DragPan | null>(null);
  const projectionRef = useRef<Projection | null>(null);
  const fittedProjectRef = useRef<string | null>(null);
  const mapExtentRef = useRef<Extent | null>(null);
  const profilesRef = useRef<Record<string, RasterProfile>>({});
  const toolRef = useRef<RasterTool>("pan");
  const activeLayerRef = useRef<string>(selectedLayerId || visibleLayers[0]?.fileId || "");
  const identifyRequestRef = useRef(0);

  const [localProfiles, setLocalProfiles] = useState<Record<string, RasterProfile>>({});
  const [tool, setTool] = useState<RasterTool>("pan");
  const [localActiveLayer, setLocalActiveLayer] = useState(selectedLayerId || visibleLayers[0]?.fileId || "");
  const [localSymbology] = useState<Record<string, RasterSymbology>>({});
  const [, setLocalIdentify] = useState<RasterIdentifyResponse | null>(null);
  const [, setLocalIdentifyLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mapStateVersion, setMapStateVersion] = useState<number | undefined>();

  const profiles = viewport?.profiles ?? localProfiles;
  const setProfiles = viewport?.setProfiles ?? setLocalProfiles;
  const activeLayer = viewport?.activeLayerId || localActiveLayer;
  const setActiveLayer = (id: string) => {
    if (viewport) viewport.setActiveLayerId(id);
    else setLocalActiveLayer(id);
  };
  const symbology = viewport?.symbology ?? localSymbology;
  const setIdentify = viewport?.setIdentify ?? setLocalIdentify;
  const setIdentifyLoading = viewport?.setIdentifyLoading ?? setLocalIdentifyLoading;

  const visibleIds = useMemo(() => visibleLayers.map((layer) => layer.fileId).join(","), [visibleLayers]);
  const readyProfiles = useMemo(
    () => visibleLayers.map((layer) => profiles[layer.fileId]).filter((profile): profile is RasterProfile => profile?.status === "ready"),
    [profiles, visibleLayers],
  );

  useEffect(() => {
    profilesRef.current = profiles;
  }, [profiles]);

  useEffect(() => {
    activeLayerRef.current = activeLayer;
  }, [activeLayer]);

  useEffect(() => {
    if (selectedLayerId && visibleLayers.some((layer) => layer.fileId === selectedLayerId)) {
      setActiveLayer(selectedLayerId);
      return;
    }
    if (!visibleLayers.some((layer) => layer.fileId === activeLayerRef.current)) {
      const fallbackLayerId = visibleLayers[0]?.fileId;
      if (fallbackLayerId) setActiveLayer(fallbackLayerId);
    }
  }, [selectedLayerId, visibleIds, visibleLayers]);

  useEffect(() => {
    if (!projectId) {
      setProfiles({});
      return;
    }
    let cancelled = false;
    const loadProfiles = async () => {
      for (const layer of visibleLayers) {
        try {
          let profile = await inputApi.getRasterProfile(projectId, layer.fileId);
          if (profile.status !== "ready" || !profile.cog_url) {
            profile = await inputApi.prepareRaster(projectId, layer.fileId);
          }
          if (!cancelled) setProfiles((current) => ({ ...current, [layer.fileId]: profile }));
        } catch (loadError) {
          if (!cancelled) {
            setProfiles((current) => ({
              ...current,
              [layer.fileId]: {
                asset_id: layer.fileId,
                name: layer.name,
                source_sha256: "",
                profile_version: "1",
                status: "error",
                error: loadError instanceof Error ? loadError.message : "栅格档案准备失败",
              },
            }));
          }
        }
      }
    };
    void loadProfiles();
    return () => { cancelled = true; };
  }, [projectId, visibleIds, visibleLayers]);

  useEffect(() => {
    if (!targetRef.current || !projectId || !readyProfiles.length || mapRef.current) return;
    const extent = createEmpty();
    readyProfiles.forEach((profile) => {
      const itemExtent = profileExtent(profile);
      if (itemExtent) extend(extent, itemExtent);
    });
    if (!Number.isFinite(extent[0]) || !Number.isFinite(extent[2])) return;
    mapExtentRef.current = extent;
    const projection = new Projection({
      code: `TAICHI-FLOW:${projectId}`,
      units: "pixels",
      extent,
      metersPerUnit: 1,
    });
    projectionRef.current = projection;
    const dragPan = new DragPan();
    const map = new Map({
      target: targetRef.current,
      controls: [],
      interactions: defaultInteractions({ dragPan: false }),
      layers: [],
      view: new View({ projection, center: getCenter(extent), resolution: Math.max((extent[2] - extent[0]) / 900, 1) }),
    });
    dragPan.setActive(true);
    map.addInteraction(dragPan);
    mapRef.current = map;
    dragPanRef.current = dragPan;
    void mapStateApi.get(projectId).then((saved) => {
      setMapStateVersion(saved.version);
      const view = saved.state.view;
      if (view?.center && view.resolution) {
        map.getView().setCenter(view.center);
        map.getView().setResolution(view.resolution);
      } else {
        map.getView().fit(extent, { padding: VIEW_PADDING, duration: 0 });
      }
    }).catch(() => map.getView().fit(extent, { padding: VIEW_PADDING, duration: 0 }));
    return () => {
      map.setTarget(undefined);
      mapRef.current = null;
      dragPanRef.current = null;
      projectionRef.current = null;
    };
  }, [projectId, readyProfiles.length]);

  useEffect(() => {
    const map = mapRef.current;
    const target = targetRef.current;
    if (!map || !target || typeof ResizeObserver === "undefined") return;

    let frame: number | undefined;
    const scheduleUpdateSize = () => {
      if (frame !== undefined) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        frame = undefined;
        map.updateSize();
      });
    };
    const observer = new ResizeObserver(scheduleUpdateSize);
    observer.observe(target);
    scheduleUpdateSize();

    return () => {
      observer.disconnect();
      if (frame !== undefined) window.cancelAnimationFrame(frame);
    };
  }, [projectId, readyProfiles.length]);

  useEffect(() => {
    const map = mapRef.current;
    const projection = projectionRef.current;
    if (!map || !projection) return;
    const layers = map.getLayers();
    layers.clear();
    const base = readyProfiles[0];
    const displayExtent = createEmpty();
    // visibleLayers[0] is the topmost UI/legend layer. OpenLayers paints the last
    // pushed layer on top, so walk bottom → top (reverse of visibleLayers).
    const paintOrder = [...readyProfiles].reverse();
    paintOrder.forEach((profile) => {
      const itemExtent = profileExtent(profile);
      if (!itemExtent || !compatibleGrid(base, profile)) return;
      extend(displayExtent, itemExtent);
      const layer = visibleLayers.find((candidate) => candidate.fileId === profile.asset_id);
      if (!layer || !profile.cog_url) return;
      const value = symbology[profile.asset_id] || DEFAULT_RASTER_SYMBOLOGY;
      const source = new GeoTIFF({
        sources: [{ url: inputApi.rasterCogUrl(projectId || "", profile.asset_id), nodata: typeof profile.nodata === "number" ? profile.nodata : undefined }],
        normalize: false,
        interpolate: value.resampling !== "nearest" && profile.data_kind !== "categorical",
        projection,
      });
      layers.push(new WebGLTileLayer({
        source,
        opacity: value.opacity,
        visible: true,
        style: { color: colourExpression(profile, value) as any } as any,
        properties: { assetId: profile.asset_id },
      }));
    });
    if (fittedProjectRef.current !== projectId && Number.isFinite(displayExtent[0]) && Number.isFinite(displayExtent[2])) {
      map.getView().fit(displayExtent, { padding: VIEW_PADDING, duration: 0 });
      fittedProjectRef.current = projectId || null;
    }
  }, [projectId, readyProfiles, sourceProfileSignature(profiles), symbology, visibleLayers]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !projectId) return;
    dragPanRef.current?.setActive(tool === "pan");
    toolRef.current = tool;
    const key = map.on("singleclick", (event: BaseEvent & { coordinate: number[] }) => {
      if (toolRef.current !== "identify") return;
      const assetIds = visibleLayers.filter((layer) => profilesRef.current[layer.fileId]?.status === "ready").map((layer) => layer.fileId);
      if (!assetIds.length) return;
      // assetIds follows visibleLayers order: index 0 is the topmost layer.
      const selected = activeLayerRef.current && assetIds.includes(activeLayerRef.current) ? activeLayerRef.current : assetIds[0];
      const requestId = identifyRequestRef.current + 1;
      identifyRequestRef.current = requestId;
      setIdentifyLoading(true);
      setError(null);
      void inputApi.identifyRasters(projectId, {
        coordinate: { x: event.coordinate[0], y: event.coordinate[1] },
        asset_ids: assetIds,
        active_asset_id: selected,
        neighborhood_size: 3,
      }).then((result) => {
        if (requestId === identifyRequestRef.current) setIdentify(result);
      }).catch((identifyError) => {
        if (requestId === identifyRequestRef.current) {
          setError(identifyError instanceof Error ? identifyError.message : "像元识别失败");
        }
      }).finally(() => {
        if (requestId === identifyRequestRef.current) setIdentifyLoading(false);
      });
    });
    return () => unByKey(key);
  }, [projectId, tool, visibleIds]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !projectId) return;
    let timer: number | undefined;
    const key = map.on("moveend", () => {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const view = map.getView();
        const state = {
          layers: visibleLayers.map((layer, order): MapLayerState => ({
            asset_id: layer.fileId,
            visible: true,
            order,
            opacity: (symbology[layer.fileId] || DEFAULT_RASTER_SYMBOLOGY).opacity,
            renderer: { kind: profilesRef.current[layer.fileId]?.data_kind === "categorical" ? "categorical" : "continuous", stretch: (symbology[layer.fileId] || DEFAULT_RASTER_SYMBOLOGY).stretch, resampling: (symbology[layer.fileId] || DEFAULT_RASTER_SYMBOLOGY).resampling },
          })),
          active_layer_id: activeLayerRef.current || null,
          view: { center: view.getCenter() as [number, number] | undefined, resolution: view.getResolution() || null, rotation: view.getRotation() },
        };
        void mapStateApi.update(projectId, state, mapStateVersion).then((saved) => setMapStateVersion(saved.version)).catch(() => undefined);
      }, 450);
    });
    return () => {
      if (timer) window.clearTimeout(timer);
      unByKey(key);
    };
  }, [projectId, visibleIds, symbology, mapStateVersion]);

  return (
    <div className="tf-raster-viewport tf-canvas-root">
      <div ref={targetRef} className="tf-raster-map" aria-label="栅格地图视图" />
      <div className="tf-float-panel tf-float-panel--top-left tf-float-panel--toolbar tf-raster-toolbar" role="toolbar" aria-label="栅格地图工具">
        <IconButton icon={<Move size={16} />} label="平移" active={tool === "pan"} aria-pressed={tool === "pan"} onClick={() => setTool("pan")} size="small" />
        <IconButton icon={<Crosshair size={16} />} label="识别原始像元" active={tool === "identify"} aria-pressed={tool === "identify"} onClick={() => setTool("identify")} size="small" />
        <IconButton icon={<ZoomIn size={16} />} label="放大" onClick={() => mapRef.current?.getView().setZoom((mapRef.current?.getView().getZoom() || 0) + 1)} size="small" />
        <IconButton icon={<ZoomOut size={16} />} label="缩小" onClick={() => mapRef.current?.getView().setZoom((mapRef.current?.getView().getZoom() || 0) - 1)} size="small" />
        <IconButton icon={<Maximize2 size={16} />} label="适配范围" onClick={() => { if (mapExtentRef.current) mapRef.current?.getView().fit(mapExtentRef.current, { padding: VIEW_PADDING, duration: 250 }); }} size="small" />
      </div>
      <RasterLegend
        layers={visibleLayers}
        profiles={profiles}
        activeLayerId={activeLayer}
        onSelect={(assetId) => {
          setActiveLayer(assetId);
          onSelectedLayerChange?.(assetId);
        }}
      />
      <RasterPreparationState profiles={Object.values(profiles)} error={error} />
    </div>
  );
}
