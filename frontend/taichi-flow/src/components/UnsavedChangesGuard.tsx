import { useEffect, useState } from "react";
import { useBlocker } from "react-router-dom";
import { Button } from "./Button";
import { ConfirmDialog } from "./ConfirmDialog";

export function UnsavedChangesGuard({ dirty, save }: { dirty: boolean; save: () => Promise<void> }) {
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  if (blocker.state !== "blocked") return null;
  return <ConfirmDialog title="有未保存的修改" busy={busy} onClose={() => { setError(""); blocker.reset(); }}>
    <p className="tf-body tf-mb-4">离开前保存修改，或放弃本次修改。</p>
    {error && <p role="alert" className="tf-text-error">{error}</p>}
    <div className="tf-dialog-footer">
      <Button variant="secondary" disabled={busy} onClick={() => { setError(""); blocker.reset(); }}>取消</Button>
      <Button variant="secondary" disabled={busy} onClick={() => blocker.proceed()}>放弃修改</Button>
      <Button disabled={busy} onClick={async () => {
        setBusy(true); setError("");
        try { await save(); blocker.proceed(); }
        catch (reason) { setError(reason instanceof Error ? reason.message : "保存失败，请重试"); }
        finally { setBusy(false); }
      }}>{busy ? "保存中…" : "保存并继续"}</Button>
    </div>
  </ConfirmDialog>;
}
