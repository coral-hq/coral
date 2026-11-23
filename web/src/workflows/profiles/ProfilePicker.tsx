import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { harnessLabel } from "../shared/harnessLabel";
import { CapabilityChips, UsedBy } from "./CapabilityChips";
import { PROFILES_QUERY_KEY, isPickableProfile, listProfiles } from "./profilesApi";

/** A searchable list of profiles (seeded first); picking one hands its ref to `onPick`. */
export function ProfilePicker({
  onPick,
  label = "Insert profile",
}: {
  onPick: (ref: string) => void;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const profiles = useQuery({
    queryKey: PROFILES_QUERY_KEY,
    queryFn: ({ signal }) => listProfiles(signal),
    enabled: open,
  });
  const rows = (profiles.data ?? [])
    .filter((row) => isPickableProfile(row.profile_ref))
    .sort((a, b) => Number(a.source === "user") - Number(b.source === "user"));
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" componentId="coral.profiles.picker">
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 max-w-[calc(100vw-2rem)] p-0">
        <Command label="Profiles">
          <CommandInput aria-label="Search profiles" placeholder="Search profiles…" />
          <CommandList aria-label="Profiles" className="max-h-80">
            {profiles.isPending && (
              <p role="status" className="p-3 text-muted-foreground text-xs">
                Loading profiles…
              </p>
            )}
            {profiles.isError && (
              <p role="status" className="p-3 text-muted-foreground text-xs">
                Couldn't load profiles.
              </p>
            )}
            {profiles.isSuccess && <CommandEmpty>No matching profiles.</CommandEmpty>}
            {rows.map((row) => (
              <CommandItem
                key={row.profile_ref}
                value={row.profile_ref}
                keywords={[row.name]}
                onSelect={() => {
                  onPick(row.profile_ref);
                  setOpen(false);
                }}
              >
                <span className="flex min-w-0 flex-col gap-1">
                  <span className="flex items-baseline gap-2">
                    <span className="truncate font-medium">{row.name}</span>
                    <span className="text-muted-foreground text-xs">
                      {harnessLabel(row.harness)}
                    </span>
                  </span>
                  {row.description && (
                    <span className="line-clamp-2 text-muted-foreground text-xs">
                      {row.description}
                    </span>
                  )}
                  <CapabilityChips capabilities={row.capabilities} />
                  <UsedBy usedBy={row.used_by} />
                </span>
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
