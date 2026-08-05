import type { ButtonHTMLAttributes, ReactNode } from "react";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: ReactNode;
  label: string;
  active?: boolean;
  size?: "small" | "medium";
}

export function IconButton({ icon, label, active, size = "medium", className = "", ...props }: IconButtonProps) {
  const classes = [
    "tf-icon-button",
    "tf-focus-ring",
    `tf-icon-button--${size}`,
    active ? "active" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button type="button" className={classes} aria-label={label} title={label} {...props}>
      {icon}
    </button>
  );
}
