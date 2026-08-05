import { Lock } from "lucide-react";
import { StatusBadge } from "./StatusBadge";
import type { RuntimeLock } from "../types";

export function RuntimeLockBadge({ runtimeLock }: { runtimeLock?: RuntimeLock }) {
  if (!runtimeLock?.locked) return null;
  const detail = runtimeLock.statuses.length
    ? `计算引用中：${runtimeLock.statuses.join(" / ")}`
    : "计算引用中";
  return (
    <StatusBadge variant="info" ariaLabel={detail} className="tf-runtime-lock-badge">
      <Lock size={12} aria-hidden="true" />
      计算引用中
    </StatusBadge>
  );
}
