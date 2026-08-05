import { LoaderCircle, TriangleAlert } from "lucide-react";
import type { RasterProfile } from "../types";

type RasterPreparationStateProps = {
  profiles: RasterProfile[];
  error?: string | null;
};

export function RasterPreparationState({ profiles, error }: RasterPreparationStateProps) {
  const preparing = profiles.filter((profile) => profile.status === "pending" || profile.status === "preparing").length;
  const unsupported = profiles.filter((profile) => profile.status === "unsupported").length;
  if (!preparing && !unsupported && !error) return null;
  if (error) {
    return (
      <div className="tf-raster-state is-error" role="alert">
        <TriangleAlert size={16} />
        <span>{error}</span>
      </div>
    );
  }
  if (preparing) {
    return (
      <div className="tf-raster-state" role="status" aria-live="polite">
        <LoaderCircle size={16} className="tf-spin" />
        <span>正在建立栅格浏览档案（{preparing} 个图层）…</span>
      </div>
    );
  }
  return (
    <div className="tf-raster-state is-warning" role="status">
      <TriangleAlert size={16} />
      <span>{unsupported} 个图层不满足单波段北向上浏览条件，已明确标记为不支持。</span>
    </div>
  );
}
