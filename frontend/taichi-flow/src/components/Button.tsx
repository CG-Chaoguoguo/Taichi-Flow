import type { ButtonHTMLAttributes, ReactNode } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "small" | "medium" | "large";
  icon?: ReactNode;
  children: ReactNode;
  fullWidth?: boolean;
}

export function Button({
  variant = "secondary",
  size = "medium",
  icon,
  children,
  fullWidth,
  className = "",
  style,
  ...props
}: ButtonProps) {
  const sizeStyles: Record<string, { padding: string; height: string; fontSize: string }> = {
    small: { padding: "0 10px", height: "28px", fontSize: "12px" },
    medium: { padding: "0 14px", height: "34px", fontSize: "13px" },
    large: { padding: "0 18px", height: "40px", fontSize: "14px" },
  };

  const variantStyles: Record<string, { background: string; color: string; border: string; hover: string }> = {
    primary: {
      background: "var(--color-brand)",
      color: "#ffffff",
      border: "1px solid var(--color-brand)",
      hover: "var(--color-brand-hover)",
    },
    secondary: {
      background: "rgba(255, 255, 255, 0.04)",
      color: "var(--color-foreground-secondary)",
      border: "1px solid rgba(255, 255, 255, 0.08)",
      hover: "rgba(255, 255, 255, 0.08)",
    },
    ghost: {
      background: "transparent",
      color: "var(--color-foreground-secondary)",
      border: "1px solid transparent",
      hover: "rgba(255, 255, 255, 0.04)",
    },
    danger: {
      background: "var(--color-error)",
      color: "#ffffff",
      border: "1px solid var(--color-error)",
      hover: "#b32505",
    },
  };

  const { background, color, border } = variantStyles[variant];
  const { padding, height, fontSize } = sizeStyles[size];

  return (
    <button
      className={`tf-button ${className}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "6px",
        padding,
        height,
        fontSize,
        fontWeight: 510,
        borderRadius: "var(--radius-medium)",
        background,
        color,
        border,
        width: fullWidth ? "100%" : undefined,
        transition: "background-color 120ms ease, border-color 120ms ease, box-shadow 120ms ease",
        whiteSpace: "nowrap",
        ...style,
      }}
      {...props}
    >
      {icon && <span style={{ display: "inline-flex", alignItems: "center" }}>{icon}</span>}
      {children}
    </button>
  );
}
