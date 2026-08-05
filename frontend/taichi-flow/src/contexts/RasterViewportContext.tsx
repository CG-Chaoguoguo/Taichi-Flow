import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { RasterSymbology } from "../components/RasterSymbologyPanel";
import type { RasterIdentifyResponse, RasterProfile } from "../types";

export const DEFAULT_RASTER_SYMBOLOGY: RasterSymbology = {
  stretch: "minmax",
  resampling: "bilinear",
  opacity: 1,
};

export type RasterViewportContextValue = {
  profiles: Record<string, RasterProfile>;
  setProfiles: React.Dispatch<React.SetStateAction<Record<string, RasterProfile>>>;
  activeLayerId: string;
  setActiveLayerId: (id: string) => void;
  symbology: Record<string, RasterSymbology>;
  setSymbologyForAsset: (assetId: string, next: RasterSymbology) => void;
  setSymbology: React.Dispatch<React.SetStateAction<Record<string, RasterSymbology>>>;
  identify: RasterIdentifyResponse | null;
  setIdentify: React.Dispatch<React.SetStateAction<RasterIdentifyResponse | null>>;
  identifyLoading: boolean;
  setIdentifyLoading: React.Dispatch<React.SetStateAction<boolean>>;
};

const RasterViewportContext = createContext<RasterViewportContextValue | null>(null);

export function RasterViewportProvider({ children }: { children: ReactNode }) {
  const [profiles, setProfiles] = useState<Record<string, RasterProfile>>({});
  const [activeLayerId, setActiveLayerIdState] = useState("");
  const [symbology, setSymbology] = useState<Record<string, RasterSymbology>>({});
  const [identify, setIdentify] = useState<RasterIdentifyResponse | null>(null);
  const [identifyLoading, setIdentifyLoading] = useState(false);

  const setActiveLayerId = useCallback((id: string) => {
    setActiveLayerIdState(id);
  }, []);

  const setSymbologyForAsset = useCallback((assetId: string, next: RasterSymbology) => {
    setSymbology((current) => ({ ...current, [assetId]: next }));
  }, []);

  const value = useMemo(
    () => ({
      profiles,
      setProfiles,
      activeLayerId,
      setActiveLayerId,
      symbology,
      setSymbologyForAsset,
      setSymbology,
      identify,
      setIdentify,
      identifyLoading,
      setIdentifyLoading,
    }),
    [
      profiles,
      activeLayerId,
      setActiveLayerId,
      symbology,
      setSymbologyForAsset,
      identify,
      identifyLoading,
    ],
  );

  return <RasterViewportContext.Provider value={value}>{children}</RasterViewportContext.Provider>;
}

export function useRasterViewport(): RasterViewportContextValue {
  const value = useContext(RasterViewportContext);
  if (!value) {
    throw new Error("useRasterViewport must be used within RasterViewportProvider");
  }
  return value;
}

export function useRasterViewportOptional(): RasterViewportContextValue | null {
  return useContext(RasterViewportContext);
}
