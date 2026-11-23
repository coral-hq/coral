import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageScroll } from "@/components/PageScroll";
import { CoralPageHeader } from "@/brand/CoralPageHeader";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useIsMobileViewport } from "@/hooks/useIsMobileViewport";
import { useParams } from "@/lib/routing";
import type { ProfileDetailOut, ProfileSpec } from "../api/generated/coralApi";
import { RosterChip } from "../shared/RosterChip";
import { CapabilityChips, UsedBy } from "./CapabilityChips";
import { ProfileForm, cleanSpec, errorLines, isStale } from "./ProfileForm";
import { PROFILES_QUERY_KEY, getProfile, profileQueryKey, saveRevision } from "./profilesApi";

/** Runs pinned to the revision an edit replaced, which they keep using. */
interface Notice {
  ref: string;
  kept: number;
  next: number;
}

export function ProfileDetailPage() {
  const { stance = "", slug = "" } = useParams<{ stance: string; slug: string }>();
  const ref = `${stance}/${slug}`;
  const [notice, setNotice] = useState<Notice | null>(null);
  const profile = useQuery({
    queryKey: profileQueryKey(ref),
    queryFn: ({ signal }) => getProfile(ref, signal),
  });

  if (profile.isPending) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <Spinner className="size-5 text-muted-foreground" aria-label="Loading profile" />
      </div>
    );
  }
  if (profile.isError) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="font-medium text-foreground text-lg">Couldn't open profile</h1>
        <p className="text-muted-foreground text-ui">{profile.error.message}</p>
        <Button variant="outline" onClick={() => void profile.refetch()}>
          Retry
        </Button>
      </div>
    );
  }
  return (
    <EditProfile
      // A new revision (saved here or reloaded) restarts the form from its spec.
      key={`${profile.data.profile_ref}@${profile.data.revision_no}`}
      detail={profile.data}
      notice={notice?.ref === ref ? notice : null}
      onSaved={setNotice}
      onReload={() => {
        setNotice(null);
        void profile.refetch();
      }}
    />
  );
}

function EditProfile({
  detail,
  notice,
  onSaved,
  onReload,
}: {
  detail: ProfileDetailOut;
  notice: Notice | null;
  onSaved: (notice: Notice | null) => void;
  onReload: () => void;
}) {
  const queryClient = useQueryClient();
  const [spec, setSpec] = useState<ProfileSpec>(detail.spec);
  // Phone width shows the profile but leaves editing to a wider screen.
  const readOnly = useIsMobileViewport();
  const base = detail.revision_no ?? 1;
  const save = useMutation({
    mutationFn: () => saveRevision(detail.profile_ref, base, cleanSpec(spec)),
    onSuccess: (saved) => {
      const replaced = saved.revisions.find((rev) => rev.revision_no === base);
      onSaved(
        saved.created && saved.revision_no !== null && (replaced?.running_runs ?? 0) > 0
          ? { ref: detail.profile_ref, kept: base, next: saved.revision_no }
          : null,
      );
      queryClient.setQueryData(profileQueryKey(detail.profile_ref), saved);
      void queryClient.invalidateQueries({ queryKey: PROFILES_QUERY_KEY });
    },
    onError: () => onSaved(null),
  });

  return (
    <PageScroll
      maxWidthClassName="max-w-[960px]"
      contentClassName="px-4 md:px-10"
      data-testid="profile-detail"
    >
      <CoralPageHeader
        title={detail.name}
        description={detail.profile_ref}
        titleAccessory={
          <span className="text-muted-foreground text-xs" data-testid="profile-revision">
            {`rev ${detail.revision_no}`}
          </span>
        }
        actions={
          !readOnly && (
            <Button
              componentId="coral.profiles.save"
              disabled={save.isPending || !spec.name.trim()}
              onClick={() => save.mutate()}
            >
              Save
            </Button>
          )
        }
      />
      {notice && (
        <p
          role="status"
          className="mb-4 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-ui"
        >
          {`Running runs keep rev ${notice.kept}; new runs use rev ${notice.next}`}
        </p>
      )}
      {save.error &&
        (isStale(save.error) ? (
          <div role="alert" className="mb-4 flex items-center gap-3 text-destructive text-ui">
            This profile changed.
            <Button variant="outline" size="sm" onClick={onReload}>
              Reload
            </Button>
          </div>
        ) : (
          <ul role="alert" className="mb-4 text-destructive text-ui">
            {errorLines(save.error).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ))}
      <div className="flex flex-col gap-6 md:flex-row">
        <div className="min-w-0 flex-1">
          <ProfileForm value={spec} onChange={setSpec} readOnly={readOnly} />
        </div>
        <aside className="flex flex-col gap-3 md:w-64">
          <RosterChip profile={detail.profile_ref} harness={detail.harness} />
          <CapabilityChips capabilities={detail.capabilities} />
          <UsedBy usedBy={detail.used_by} />
          <h2 className="font-medium text-foreground text-ui">Revisions</h2>
          <ul className="flex flex-col gap-1 text-ui" data-testid="revision-list">
            {detail.revisions.map((rev) => (
              <li key={rev.id} className="flex justify-between gap-2">
                <span>{`rev ${rev.revision_no}`}</span>
                <span className="text-muted-foreground text-xs">
                  {`${new Date(rev.created_at * 1000).toLocaleDateString()} · ${rev.running_runs} running`}
                </span>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </PageScroll>
  );
}
