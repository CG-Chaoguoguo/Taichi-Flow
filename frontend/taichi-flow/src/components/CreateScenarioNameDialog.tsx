import { useEffect, useState } from "react";
import { Button } from "./Button";

type CreateScenarioNameDialogProps = {
  open: boolean;
  initialName?: string;
  busy?: boolean;
  onClose: () => void;
  onCreate: (name: string) => void | Promise<void>;
};

export function CreateScenarioNameDialog({
  open,
  initialName = "",
  busy = false,
  onClose,
  onCreate,
}: CreateScenarioNameDialogProps) {
  const [name, setName] = useState(initialName);

  useEffect(() => {
    if (open) setName(initialName);
  }, [open, initialName]);

  if (!open) return null;

  const trimmed = name.trim();

  return (
    <div className="tf-dialog-overlay" onClick={onClose}>
      <div className="tf-dialog tf-dialog-narrow" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="create-scenario-title">
        <h2 id="create-scenario-title" className="tf-title tf-mb-4">
          新建方案
        </h2>
        <div className="tf-form-stack">
          <label className="tf-caption tf-text-secondary" htmlFor="create-scenario-name">
            方案名称
          </label>
          <input
            id="create-scenario-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：高摩阻方案"
            className="tf-input tf-full-width"
            autoFocus
            onKeyDown={(event) => {
              if (event.key === "Enter" && trimmed && !busy) {
                void onCreate(trimmed);
              }
            }}
          />
        </div>
        <div className="tf-row tf-justify-end tf-gap-2">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button onClick={() => void onCreate(trimmed)} disabled={!trimmed || busy}>
            创建
          </Button>
        </div>
      </div>
    </div>
  );
}
