import type { HTMLAttributes, ReactNode } from "react";

type SurfaceVariant = "glass" | "solid" | "elevated" | "inset" | "mica" | "layer" | "acrylic" | "card";

interface SurfaceProps extends HTMLAttributes<HTMLDivElement> {
  variant?: SurfaceVariant;
  children: ReactNode;
  padding?: boolean;
}

const variantClass: Record<SurfaceVariant, string> = {
  glass: "tf-glass",
  solid: "tf-surface-solid",
  elevated: "tf-layer tf-elevation-16",
  inset: "tf-inset",
  mica: "tf-mica",
  layer: "tf-layer",
  acrylic: "tf-acrylic",
  card: "tf-card",
};

export function Surface({
  variant = "layer",
  children,
  padding = false,
  className = "",
  ...props
}: SurfaceProps) {
  const classes = [variantClass[variant], padding ? "tf-panel" : "", className].filter(Boolean).join(" ");
  return (
    <div className={classes} {...props}>
      {children}
    </div>
  );
}
