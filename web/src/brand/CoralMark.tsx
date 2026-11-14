import type { SVGProps } from "react";
import { cn } from "@/lib/utils";

// Placeholder Coral mark (UI§4.1): Clay mosaic ring around a leaf; replace with final artwork (PKG-02).
export const CORAL_MARK_VIEWBOX = "0 0 64 64";

/** Mark geometry, kept identical to `assets/coral-mark.svg` (the brand test checks both). */
export const CORAL_MARK_PATHS: readonly { d: string; fill: string }[] = [
  {
    d: "M33.83 2.06A30 30 0 0 1 57.02 15.44L47.03 21.21A18.5 18.5 0 0 0 33.83 13.59Z",
    fill: "#4D7356",
  },
  {
    d: "M58.85 18.61A30 30 0 0 1 58.85 45.39L48.86 39.62A18.5 18.5 0 0 0 48.86 24.38Z",
    fill: "#9EAB92",
  },
  {
    d: "M57.02 48.56A30 30 0 0 1 33.83 61.94L33.83 50.41A18.5 18.5 0 0 0 47.03 42.79Z",
    fill: "#B9CDB0",
  },
  {
    d: "M30.17 61.94A30 30 0 0 1 6.98 48.56L16.97 42.79A18.5 18.5 0 0 0 30.17 50.41Z",
    fill: "#C19A55",
  },
  {
    d: "M5.15 45.39A30 30 0 0 1 5.15 18.61L15.14 24.38A18.5 18.5 0 0 0 15.14 39.62Z",
    fill: "#864A31",
  },
  {
    d: "M6.98 15.44A30 30 0 0 1 30.17 2.06L30.17 13.59A18.5 18.5 0 0 0 16.97 21.21Z",
    fill: "#6E2B22",
  },
  { d: "M23.16 40.84A16 16 0 0 1 40.84 23.16A16 16 0 0 1 23.16 40.84Z", fill: "#4D7356" },
];

/**
 * Coral's circular mark on a transparent background. Decorative by default:
 * the adjacent wordmark or heading carries the name. Pass `otto-working` in
 * `className` for the working-indicator pulse (see `coral.css`).
 */
export function CoralMark({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox={CORAL_MARK_VIEWBOX}
      fill="none"
      aria-hidden="true"
      focusable="false"
      data-coral-mark=""
      className={cn("coral-mark aspect-square", className)}
      {...props}
    >
      {CORAL_MARK_PATHS.map((path) => (
        <path key={path.d} d={path.d} fill={path.fill} />
      ))}
    </svg>
  );
}
