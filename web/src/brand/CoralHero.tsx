import { BrandLogo } from "@/components/BrandLogo";

/**
 * Desktop new-session hero: the brand mark beside the heading, locked to the
 * heading's 1em so the two scale together (UI§3.3, §4.3). An operator logo
 * replaces the mark through `BrandLogo`; an empty heading shows only the mark.
 */
export function CoralHero({ heading }: { heading: string }) {
  return (
    <div
      className="flex max-w-full min-w-0 items-center justify-center gap-[0.32em] text-[2.55em]"
      data-testid="coral-hero"
    >
      <BrandLogo variant="eyes" className="block h-[1em] w-auto shrink-0 object-contain" />
      {heading ? (
        <h1 className="line-clamp-2 min-w-0 font-display text-[1em] leading-[1.05] font-medium tracking-[-0.03em] break-words text-foreground">
          {heading}
        </h1>
      ) : null}
    </div>
  );
}
