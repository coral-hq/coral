import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageScroll } from "@/components/PageScroll";
import { CoralPageHeader } from "@/brand/CoralPageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Link, useNavigate } from "@/lib/routing";
import type { ProfileRowOut, ProfileSpec } from "../api/generated/coralApi";
import { CORAL_LABELS } from "../nav/labels";
import { profilePath } from "../nav/coralPaths";
import { RosterChip } from "../shared/RosterChip";
import { CapabilityChips, UsedBy } from "./CapabilityChips";
import { EMPTY_SPEC, ProfileForm, cleanSpec, errorLines } from "./ProfileForm";
import { PROFILES_QUERY_KEY, createProfile, listProfiles, profileQueryKey } from "./profilesApi";

const STANCES = ["implementer", "reviewer"] as const;

export function ProfilesPage() {
  const [creating, setCreating] = useState(false);
  const profiles = useQuery({
    queryKey: PROFILES_QUERY_KEY,
    queryFn: ({ signal }) => listProfiles(signal),
  });
  return (
    <PageScroll
      maxWidthClassName="max-w-[960px]"
      contentClassName="px-4 md:px-10"
      data-testid="profiles-desk"
    >
      <CoralPageHeader
        title={CORAL_LABELS.profiles}
        description="The agents a workflow step can use, and the rules they work under."
        actions={
          !creating && (
            <Button componentId="coral.profiles.new" onClick={() => setCreating(true)}>
              New profile
            </Button>
          )
        }
      />
      {creating && <CreateProfile onCancel={() => setCreating(false)} />}
      {profiles.isPending ? (
        <div className="flex justify-center py-16">
          <Spinner className="size-5 text-muted-foreground" aria-label="Loading profiles" />
        </div>
      ) : profiles.isError ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-muted-foreground text-ui">Couldn't load profiles.</p>
          <Button variant="outline" onClick={() => void profiles.refetch()}>
            Retry
          </Button>
        </div>
      ) : (
        <ul className="flex flex-col divide-y divide-border" data-testid="profile-list">
          {profiles.data.map((row) => (
            <ProfileRow key={row.profile_ref} row={row} />
          ))}
        </ul>
      )}
    </PageScroll>
  );
}

function ProfileRow({ row }: { row: ProfileRowOut }) {
  return (
    <li className="flex flex-col gap-2 py-3" data-testid="profile-row">
      <div className="flex flex-wrap items-center gap-2">
        {row.source === "user" ? (
          <Link
            to={profilePath(row.profile_ref)}
            className="font-medium text-foreground text-ui hover:underline"
          >
            {row.name}
          </Link>
        ) : (
          <span className="font-medium text-foreground text-ui">{row.name}</span>
        )}
        <Badge variant="secondary">{row.source === "seeded" ? "Seeded" : "Yours"}</Badge>
        {row.revision_no !== null && (
          <span className="text-muted-foreground text-xs">{`rev ${row.revision_no}`}</span>
        )}
        <RosterChip profile={row.profile_ref} harness={row.harness} />
        {row.model && <span className="text-muted-foreground text-xs">{row.model}</span>}
      </div>
      {row.description && <p className="text-muted-foreground text-ui">{row.description}</p>}
      <CapabilityChips capabilities={row.capabilities} />
      {row.rules.length > 0 && (
        <ul className="flex flex-col gap-0.5 text-ui">
          {row.rules.map((rule) => (
            <li key={rule.template}>
              <Badge variant={rule.strength === "required" ? "default" : "secondary"}>
                {rule.strength === "required" ? "Required" : "Guidance"}
              </Badge>{" "}
              {rule.statement}
            </li>
          ))}
        </ul>
      )}
      <UsedBy usedBy={row.used_by} />
    </li>
  );
}

function CreateProfile({ onCancel }: { onCancel: () => void }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [stance, setStance] = useState<(typeof STANCES)[number]>("reviewer");
  const [slug, setSlug] = useState("");
  const [spec, setSpec] = useState<ProfileSpec>(EMPTY_SPEC);
  const create = useMutation({
    mutationFn: () => createProfile(`${stance}/${slug.trim()}`, cleanSpec(spec)),
    onSuccess: (detail) => {
      queryClient.setQueryData(profileQueryKey(detail.profile_ref), detail);
      void queryClient.invalidateQueries({ queryKey: PROFILES_QUERY_KEY });
      navigate(profilePath(detail.profile_ref));
    },
  });
  return (
    <section
      className="mb-6 flex flex-col gap-4 rounded-lg border border-border p-4"
      aria-label="New profile"
    >
      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col gap-1 text-ui">
          Stance
          <select
            value={stance}
            onChange={(e) => setStance(e.target.value as (typeof STANCES)[number])}
            className="h-8 rounded-md border border-border bg-background px-2 text-ui"
          >
            {STANCES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-1 flex-col gap-1 text-ui">
          Slug
          <Input
            value={slug}
            placeholder="strict-review"
            maxLength={64}
            onChange={(e) => setSlug(e.target.value)}
          />
        </label>
      </div>
      <ProfileForm value={spec} onChange={setSpec} />
      {create.error && (
        <ul className="text-destructive text-ui" role="alert">
          {errorLines(create.error).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      <div className="flex gap-2">
        <Button
          componentId="coral.profiles.create"
          disabled={!slug.trim() || !spec.name.trim() || create.isPending}
          onClick={() => create.mutate()}
        >
          Create
        </Button>
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </section>
  );
}
