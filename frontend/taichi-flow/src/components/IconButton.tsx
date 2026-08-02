import type { ButtonHTMLAttributes, ReactNode } from "react";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: ReactNode;
  label: string;
  active?: boolean;
  size?: "small" | "medium";
}

export function IconButton({ icon, label, active, size = "medium", className = "", ...props }: IconButtonProps) {
  const sizeStyles = size === "small" ? { width: 28, height: 28 } : { width: 34, height: 34 };
  return (
    <button
      type="button"
      className={`tf-icon-button ${className}`}
      aria-label={label}
      title={label}
      style={{
        ...sizeStyles,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: "var(--radius-medium)",
        background: active ? "var(--color-brand-bg-subtle)" : "rgba(255, 255, 255, 0.03)",
        color: active ? "var(--color-brand)" : "var(--color-foreground-secondary)",
        border: "1px solid rgba(255, 255, 255, 0.08)",
        transition: "background-color 120ms ease, color 120ms ease",
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.06)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = active ? "var(--color-brand-bg-subtle)" : "rgba(255, 255, 255, 0.03)";
      }}
      {...props}
    >
      {icon}
    </button>
  );
}
