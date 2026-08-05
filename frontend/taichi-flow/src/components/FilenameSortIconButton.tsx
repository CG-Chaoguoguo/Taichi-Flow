import { ArrowDownAZ } from "lucide-react";
import { IconButton } from "./IconButton";

type FilenameSortIconButtonProps = {
  active: boolean;
  onToggle: () => void;
};

export function FilenameSortIconButton({ active, onToggle }: FilenameSortIconButtonProps) {
  return (
    <IconButton
      size="small"
      icon={<ArrowDownAZ size={14} />}
      label={active ? "取消按文件名排序" : "按文件名排序"}
      active={active}
      aria-pressed={active}
      onClick={onToggle}
    />
  );
}
