import { useTaichiFlowStore, type DockTab } from "../../stores/taichiFlowStore";
import type { InputFile } from "../../types";
import { AssetContentBrowser } from "./AssetContentBrowser";
import { QueueDockPanel } from "./QueueDockPanel";
import { TerminalDockPanel } from "./TerminalDockPanel";
import { ExportDockPanel } from "./ExportDockPanel";
import { PanelCollapseButton } from "../../components/layout/ResizablePaneGroup";

const tabs: { id: Exclude<DockTab, null>; label: string }[] = [
  { id: "assets", label: "资产" },
  { id: "queue", label: "队列" },
  { id: "terminal", label: "终端" },
  { id: "export", label: "导出" },
];

type BottomDockProps = {
  focusedAssetId?: string | null;
  onFocusAsset: (file: InputFile) => void;
  onToggleCollapse?: () => void;
  assetFamiliesCollapsed?: boolean;
  onToggleAssetFamilies?: () => void;
  assetFamilyPx?: number;
  onAssetLayoutChanged?: (familyPx: number, isUserInteraction: boolean) => void;
};

export function BottomDock({
  focusedAssetId = null,
  onFocusAsset,
  onToggleCollapse,
  assetFamiliesCollapsed = false,
  onToggleAssetFamilies,
  assetFamilyPx = 160,
  onAssetLayoutChanged,
}: BottomDockProps) {
  const dockTab = useTaichiFlowStore((state) => state.dockTab);
  const setDockTab = useTaichiFlowStore((state) => state.setDockTab);
  const activeTab = dockTab || "assets";

  return (
    <section className="tf-dock" aria-label="底部面板">
      <div className="tf-dock-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`tf-dock-tab${activeTab === tab.id ? " active" : ""}`}
            aria-current={activeTab === tab.id ? "page" : undefined}
            onClick={() => setDockTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
        {onToggleCollapse ? <PanelCollapseButton label="底部资产坞" collapsed={false} direction="bottom" onToggle={onToggleCollapse} /> : null}
      </div>
      <div className={`tf-dock-body${activeTab === "assets" ? " is-assets" : ""}`}>
        {activeTab === "assets" ? (
          <AssetContentBrowser
            focusedAssetId={focusedAssetId}
            onFocusAsset={onFocusAsset}
            assetFamiliesCollapsed={assetFamiliesCollapsed}
            onToggleAssetFamilies={onToggleAssetFamilies}
            assetFamilyPx={assetFamilyPx}
            onAssetLayoutChanged={onAssetLayoutChanged}
          />
        ) : null}
        {activeTab === "queue" ? <QueueDockPanel /> : null}
        {activeTab === "terminal" ? <TerminalDockPanel /> : null}
        {activeTab === "export" ? <ExportDockPanel /> : null}
      </div>
    </section>
  );
}
