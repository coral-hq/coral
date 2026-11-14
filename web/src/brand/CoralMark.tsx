import type { ImgHTMLAttributes } from "react";
import { cn } from "@/lib/utils";
// Generated from docs/coral/design/coral.png by .coral/tools/brand_assets.py.
import coralLogo from "./assets/coral-logo.png";

/**
 * Coral's logo, the circular leaf mosaic on a transparent background (UI§4.1).
 * Decorative by default: the adjacent wordmark or heading carries the name.
 * Pass `otto-working` in `className` for the working-indicator pulse (see
 * `coral.css`).
 */
export function CoralMark({ className, ...props }: ImgHTMLAttributes<HTMLImageElement>) {
  return (
    <img
      src={coralLogo}
      alt=""
      aria-hidden="true"
      draggable={false}
      data-coral-mark=""
      className={cn("coral-mark aspect-square object-contain", className)}
      {...props}
    />
  );
}
