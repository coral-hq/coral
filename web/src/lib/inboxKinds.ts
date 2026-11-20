// CORAL(S37): Inbox extension kinds (new file). An extension registers a kind to
// render its own Inbox entries and claim the pending prompts it shows itself.
// With no kind registered every helper here is the identity; a kind that throws
// is left out where it failed, so the Inbox, badge and notifier keep working.

import { Component, createElement, useSyncExternalStore, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import type { Conversation } from "@/hooks/useConversations";
import type { InboxSource } from "./inbox";

/** A pending elicitation as the Inbox found it: the raw event and the row whose snapshot held it. */
export interface InboxRawElicitation {
  row: Conversation;
  event: Record<string, unknown>;
}

/** One entry a kind adds to the Inbox. */
export interface InboxKindEntry {
  /** Unique across the Inbox, e.g. `"workflow:gate:<id>"`. */
  key: string;
  /** Epoch seconds the entry sorts and groups by. */
  at: number;
  /** Listed under this tab and under "All". */
  tab: "awaiting" | "unread";
  /** Read only by the kind's renderer. */
  data: unknown;
}

export type InboxTileTone = "yellow" | "gray" | "red";

/** Props of the Inbox's shared card, so a kind's entries look like every other card. */
export interface InboxCardProps {
  testId: string;
  dataKind?: string;
  tile: ReactNode;
  kindLabel: string;
  title: string;
  preview: ReactNode;
  /** Epoch seconds. */
  at: number;
  unread: boolean;
  expanded: boolean;
  onToggle: () => void;
  children: ReactNode;
}

/** The Inbox's own card primitives, handed to a kind's renderer. */
export interface InboxKindUi {
  InboxCard: (props: InboxCardProps) => ReactNode;
  KindTile: (props: { icon: LucideIcon; tone: InboxTileTone }) => ReactNode;
  InboxActions: (props: { children: ReactNode }) => ReactNode;
  outlineAction: string;
  primaryAction: string;
}

export interface InboxKind {
  readonly id: string;
  /** This kind renders the elicitation itself; it then never shows as an approval card. */
  claims: (raw: InboxRawElicitation) => boolean;
  entries: (claimed: readonly InboxRawElicitation[]) => readonly InboxKindEntry[];
  /** Entries no session's pending count already counts (the sidebar badge adds these). */
  readonly badgeCount: number;
  /** More entries exist than the kind loaded (feeds `inboxCountIncomplete`). */
  readonly incomplete: boolean;
  readonly loading: boolean;
  readonly error: { message: string; retry: () => void } | null;
  summary: (count: number) => string;
  /** The generic idle notifier stays silent for this row (the kind notifies instead). */
  silences: (row: Conversation) => boolean;
  render: (
    entry: InboxKindEntry,
    expanded: boolean,
    onToggle: () => void,
    ui: InboxKindUi,
  ) => ReactNode;
}

const NO_KINDS: readonly InboxKind[] = Object.freeze([]);
const NO_ENTRIES: readonly InboxKindEntry[] = Object.freeze([]);
const NO_CLAIMS: ReadonlyMap<string, InboxRawElicitation[]> = new Map();

interface Registration {
  original: InboxKind;
  guarded: InboxKind;
}

// Replaced as a whole on every change, so a snapshot is stable until the next one.
let registrations: readonly Registration[] = [];
let kinds: readonly InboxKind[] = NO_KINDS;
const listeners = new Set<() => void>();
const warnedKindIds = new Set<string>();

function publish(next: readonly Registration[]): void {
  registrations = next;
  kinds = next.length === 0 ? NO_KINDS : next.map((registration) => registration.guarded);
  for (const listener of listeners) listener();
}

/** Warn once per kind; the failing call then answers as if the kind had nothing. */
function warnKindFailed(kindId: string, where: string, error: unknown): void {
  if (warnedKindIds.has(kindId)) return;
  warnedKindIds.add(kindId);
  console.warn(`Inbox kind "${kindId}" failed in ${where}; the Inbox leaves it out there.`, error);
}

/**
 * Wrap a kind so that none of its calls can throw into the Inbox, the badge or
 * the notifier. Fields are read once, here: a kind changes by registering again.
 * `render` is isolated by `InboxKindEntryView`'s error boundary.
 */
function guard(kind: InboxKind): InboxKind {
  function attempt<T>(where: string, call: () => T, fallback: T): T {
    try {
      return call();
    } catch (error) {
      warnKindFailed(kind.id, where, error);
      return fallback;
    }
  }
  const badgeCount = attempt("badgeCount", () => kind.badgeCount, 0);
  return {
    id: kind.id,
    claims: (raw) => attempt("claims", () => kind.claims(raw) === true, false),
    entries: (claimed) =>
      attempt(
        "entries",
        () => {
          const entries = kind.entries(claimed);
          return Array.isArray(entries) ? entries : NO_ENTRIES;
        },
        NO_ENTRIES,
      ),
    badgeCount: Number.isFinite(badgeCount) && badgeCount > 0 ? badgeCount : 0,
    incomplete: attempt("incomplete", () => kind.incomplete === true, false),
    loading: attempt("loading", () => kind.loading === true, false),
    error: attempt("error", () => kind.error ?? null, null),
    summary: (count) =>
      attempt(
        "summary",
        () => {
          const text = kind.summary(count);
          return typeof text === "string" ? text : "";
        },
        "",
      ),
    silences: (row) => attempt("silences", () => kind.silences(row) === true, false),
    render: (entry, expanded, onToggle, ui) => kind.render(entry, expanded, onToggle, ui),
  };
}

/**
 * Add a kind, or replace the registered kind with the same id in place.
 *
 * :returns: An unregister that removes this registration only, so the cleanup of
 *   a registration that was since replaced is harmless.
 */
export function registerInboxKind(kind: InboxKind): () => void {
  const registration: Registration = { original: kind, guarded: guard(kind) };
  const index = registrations.findIndex((candidate) => candidate.original.id === kind.id);
  publish(
    index === -1
      ? [...registrations, registration]
      : registrations.map((candidate, i) => (i === index ? registration : candidate)),
  );
  return () => {
    if (registrations.includes(registration)) {
      publish(registrations.filter((candidate) => candidate !== registration));
    }
  };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot(): readonly InboxKind[] {
  return kinds;
}

/**
 * The registered kinds, in registration order; the same array until a kind
 * changes. Each is wrapped so that a call that throws answers with nothing.
 */
export function useInboxKinds(): readonly InboxKind[] {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

/** Props of {@link InboxKindEntryView}: one kind entry and the page's card primitives. */
export interface InboxKindEntryViewProps {
  kind: InboxKind;
  entry: InboxKindEntry;
  expanded: boolean;
  onToggle: () => void;
  ui: InboxKindUi;
}

function KindEntryRender({ kind, entry, expanded, onToggle, ui }: InboxKindEntryViewProps) {
  return kind.render(entry, expanded, onToggle, ui);
}

interface InboxKindEntryViewState {
  failed: boolean;
  kind: InboxKind;
}

/** Render one kind entry; an entry whose kind throws while rendering shows nothing. */
export class InboxKindEntryView extends Component<
  InboxKindEntryViewProps,
  InboxKindEntryViewState
> {
  override state: InboxKindEntryViewState = { failed: false, kind: this.props.kind };

  static getDerivedStateFromProps(
    props: InboxKindEntryViewProps,
    state: InboxKindEntryViewState,
  ): Partial<InboxKindEntryViewState> | null {
    // A kind registered again gets another chance to render.
    return props.kind !== state.kind ? { failed: false, kind: props.kind } : null;
  }

  static getDerivedStateFromError(): Partial<InboxKindEntryViewState> {
    return { failed: true };
  }

  override componentDidCatch(error: unknown): void {
    warnKindFailed(this.props.kind.id, "render", error);
  }

  override render(): ReactNode {
    return this.state.failed ? null : createElement(KindEntryRender, this.props);
  }
}

/**
 * Split the sources' pending elicitations between the kinds and the approval list.
 *
 * Each event goes to the first kind that claims it; every other event stays in
 * its source. A source nothing was claimed from is passed through unchanged.
 */
export function partitionElicitations(
  registered: readonly InboxKind[],
  sources: InboxSource[],
): { unclaimed: InboxSource[]; claimed: ReadonlyMap<string, InboxRawElicitation[]> } {
  if (registered.length === 0) return { unclaimed: sources, claimed: NO_CLAIMS };
  const claimed = new Map<string, InboxRawElicitation[]>();
  const unclaimed = sources.map((source) => {
    const kept = source.pendingElicitations.filter((event) => {
      const raw = { row: source.row, event };
      const owner = registered.find((kind) => kind.claims(raw));
      if (owner === undefined) return true;
      const list = claimed.get(owner.id);
      if (list) list.push(raw);
      else claimed.set(owner.id, [raw]);
      return false;
    });
    return kept.length === source.pendingElicitations.length
      ? source
      : { ...source, pendingElicitations: kept };
  });
  return { unclaimed, claimed };
}

/** Badge items the kinds add beyond what session pending counts already count. */
export function inboxKindsBadgeCount(registered: readonly InboxKind[]): number {
  return registered.reduce((total, kind) => total + kind.badgeCount, 0);
}

/** Whether any kind loaded only part of its entries. */
export function inboxKindsIncomplete(registered: readonly InboxKind[]): boolean {
  return registered.some((kind) => kind.incomplete);
}

/** Drop every kind and the failure warnings already given. For test isolation only. */
export function resetInboxKindsForTests(): void {
  publish([]);
  warnedKindIds.clear();
}
