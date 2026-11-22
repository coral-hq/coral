import { Link } from "@/lib/routing";
import type { PreflightItemOut } from "../api/generated/coralApi";
import { fixHref, fixLabel } from "./preflightFixes";

export interface PreflightListProps {
  items: readonly PreflightItemOut[];
}

/** One row per preflight check; failures name a fix when the server sent one. */
export function PreflightList({ items }: PreflightListProps) {
  return (
    <ul className="flex flex-col gap-2" data-testid="preflight">
      {items.map((item) => (
        <li
          key={item.check}
          className={
            item.status === "fail"
              ? "text-destructive text-ui"
              : item.status === "warn"
                ? "text-amber-700 text-ui dark:text-amber-400"
                : "text-muted-foreground text-ui"
          }
          data-status={item.status}
          data-check={item.check}
        >
          <span>{item.message}</span>
          {item.fix != null && (
            <>
              {" "}
              <FixLink target={item.fix.target} href={item.fix.href} />
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

function FixLink({
  target,
  href,
}: {
  target: NonNullable<PreflightItemOut["fix"]>["target"];
  href: string | null;
}) {
  const to = href ?? fixHref(target);
  const label = fixLabel(target);
  if (to == null) {
    return <span className="font-medium">{label}</span>;
  }
  return (
    <Link to={to} componentId={`coral.start_run.preflight_fix.${target}`} className="underline">
      {label}
    </Link>
  );
}
