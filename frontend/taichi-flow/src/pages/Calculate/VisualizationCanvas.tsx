import type { Dispatch, SetStateAction } from "react";
import { RasterMapViewport, type RasterViewportLayer } from "./RasterMapViewport";

export type CanvasState = {
  zoom: number;
  offsetX: number;
  offsetY: number;
  selectedLayer: string;
};

type VisualizationCanvasProps = {
  projectId?: string;
  state: CanvasState;
  setState: Dispatch<SetStateAction<CanvasState>>;
  activeModule: string;
  visibleLayers?: RasterViewportLayer[];
};

/**
 * Compatibility wrapper for the existing workbench layout.  The actual
 * viewport is now RasterMapViewport; no numerical value is derived from a
 * mouse position or from a colourized preview image.
 */
export function VisualizationCanvas({ projectId, state, setState, activeModule, visibleLayers = [] }: VisualizationCanvasProps) {
  return (
    <RasterMapViewport
      projectId={projectId}
      visibleLayers={visibleLayers}
      selectedLayerId={state.selectedLayer}
      activeModule={activeModule}
      onSelectedLayerChange={(selectedLayer) => setState((current) => ({ ...current, selectedLayer }))}
    />
  );
}
