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
  const classes = [
    "tf-button",
    "tf-focus-ring",
    `tf-button--${variant}`,
    `tf-button--${size}`,
    fullWidth ? "tf-full-width" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button className={classes} style={style} {...props}>
      {icon && <span className="tf-button-icon">{icon}</span>}
      {children}
    </button>
  );
}
