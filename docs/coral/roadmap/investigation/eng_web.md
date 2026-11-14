# Coral web frontend: current state, gaps, and build plan

Agent 3, Staff Engineer. Area: web SPA, the Electron, iOS and Android shells, brand skin, workflow canvas, run view and profiles UI.
Repo: `omnigent-ai/omnigent` at HEAD `2a9cbe2c2` (0.22.0.dev0). Every code claim below was checked at HEAD unless it is marked **UNVERIFIED**.
Notation: **Reuse** = use as-is. **Extend** = add to an upstream file without changing its behaviour. **Modify** = change upstream behaviour. **New** = Coral-owned file. **Replace** = swap an asset or default. **Remove** = delete.

---

## 0. Verdict in one screen

- **The SPA already has nearly every primitive Coral's UI needs.** It ships React Flow 12 (`web/package.json:67`, locked at 12.11.2), Monaco with Shiki (`web/src/shell/monacoSetup.ts`), a full-session agent transcript with a composer (`SideChatPane fullSession`, already wrapped as `SubagentTabPane` in `web/src/shell/SubagentTab.tsx:40-77`), and approval and elicitation cards with an injectable submitter (`ApprovalCard.tsx:134-145`). It also has the session-updates WebSocket with a child-session watch path, a precedent for the inbox feed (`useAutomationInbox`), a theme-palette generator and an operator-branding probe.
- **What is missing is Coral-specific:**
  - a YAML library (`yaml` is not a direct dependency);
  - a layout library choice;
  - the `web/src/workflows/` product code;
  - a run-log stream client;
  - the brand assets and tokens;
  - about 8–10 small seams in upstream files.
- **The biggest risk is merge churn in the files Coral must touch, not AppShell alone.** Over 30 days (2026-10-09 to 2026-11-08):
  - `Sidebar.tsx`: 51 commits, 7,772 lines;
  - `NewChatDialog.tsx`: 52 commits, 8,052 lines;
  - `AppShell.tsx`: 41 commits, 3,202 lines;
  - `capabilities.ts`: 31 commits;
  - `index.css`: 27 commits.

  Every edit to these files must be a one-line call into a Coral-owned component (§4.1).
- **Corrections to the source docs.** The 19 refinements in §2 change implementation details:
  - Repointing `--font-heading` makes every dialog and card title serif (N1).
  - The deep dive's `/workflows/runs/:runId/c/:conversationId` route puts AppShell into chat mode (N6).
  - The sidebar marks any unknown route as "New session" (N7).
  - The Electron auto-update feed still points at omnigent.ai (N13).
  - macOS 26 uses `Assets.car`, not just `icon.icns` (N3).
  - The run SSE must take a stream slot from the origin-wide budget, or the HTTP/1.1 cap deadlocks fetches (N11).
- **Sizing.** Production code is about 13–18k LOC across about 110 new files, plus tests. That is roughly 30–40 engineer-weeks for the full FE scope. The brand skin and shell wiring can start immediately and do not depend on the engine. The editor depends on new file-read and file-write endpoints. The run view depends on the run-log stream.

---

## 1. Verified current-state frontend architecture

### 1.1 Stack and dependencies (`web/package.json`)

| Concern | What exists | Evidence |
|---|---|---|
| Framework | React 18 (`^18.2.0`, catalog-pinned; the lock resolves 18.3.1), Vite 8.1.6, TypeScript ~6.0, Tailwind 4 (`@tailwindcss/vite`), shadcn/radix | `web/package.json:82,88`; `pnpm-workspace.yaml` catalog/overrides |
| Router | `react-router-dom` 7.18.4. Routing primitives must come from `@/lib/routing`, an IoC seam for the embed (lint rule) | `web/package.json:88`; `web/.oxlintrc.json` `no-restricted-imports`; `web/src/lib/routing.tsx:193-218` |
| Server state | TanStack Query 5 | `web/package.json:51` |
| Client state | zustand 5 (`useChatStore`, `useSessionImportStore`, `useTerminalActivityStore`) | `web/package.json:108`; `web/src/store/chatStore.ts:2184`; `web/src/store/sessionImport.ts:35`; `web/src/store/terminalActivity.ts:19` |
| Validation | zod 4, used only for localStorage caches, not API parsing | `web/package.json:107`; `lib/modelCatalogCache.ts`, `lib/newChatPickerCache.ts`, etc. |
| Graphs | `@xyflow/react ^12.11.1` (lock 12.11.2), `@xyflow/system 0.0.79` | `web/package.json:67`; `pnpm-lock.yaml:4745,4758` |
| Editor | `@monaco-editor/react ^4.7.0`, `monaco-editor ^0.55.1`, Shiki 4.5.0 via `@shikijs/monaco` | `web/package.json:33,76`; `web/src/shell/monacoSetup.ts:1-20` |
| YAML parser | **None as a direct dependency.** `yaml@2.9.0` is only transitive (through vite and `@earendil-works/pi-coding-agent`); `yaml@1.10.3` comes through cosmiconfig | `pnpm-lock.yaml:9502-9510, 10411, 19883` |
| Auto-layout | **None direct.** `elkjs@0.11.1` is transitive (`@lobehub/icons` → `@lobehub/ui` → `beautiful-mermaid` → `elkjs`); `dagre-d3-es@7.0.14` comes through mermaid; `@dagrejs/dagre` is absent | `pnpm-lock.yaml:4965, 5721, 11092, 14622-14624, 17114` |
| Fonts | Only `@fontsource-variable/geist-mono` (imported at `index.css:5`). No Newsreader | `web/package.json`; `web/src/index.css:5` |
| Lists | `@tanstack/react-virtual` (mocked in test-setup) | `web/src/test-setup.ts:93` |
| Dependency cooldown | pnpm `minimumReleaseAge: 10080` (7 days), so any new web dependency must be at least a week old | `pnpm-workspace.yaml` |
| Build output | The SPA builds into `omnigent/server/static/web-ui`, so it ships inside the server | `web/vite.config.ts` `build.outDir` |

### 1.2 Routing (`web/src/App.tsx`, 272 lines, 6 commits in 30 days)

- `withPageView(id, Component)` binds an analytics page-view id ("no route ships without one") (`App.tsx:16-29`). Settings and Tasks own their ids (`App.tsx:22-23, 60, 69`).
- `FeatureGatedPage({feature})` shows a spinner while `/v1/info` loads, then the page or `NotFoundPage` (`App.tsx:73-86`).
- Every page except auth renders inside `<Route element={<AppShell/>}>` (`App.tsx:181-257`). Paths are prefixed with `${prefix}` to support the embedded basename (`App.tsx:148-153`).
- Feature-gated precedents:
  - `/canvas` and `/canvas/c/:conversationId` → `FeatureGatedPage feature="canvas"` (`App.tsx:193-208`);
  - `/usage` (`App.tsx:222-229`);
  - `/tasks/:taskId` → `automations_v2` (`App.tsx:214-221`).
- `/workflows`, `/profiles` and `/schemas` are all free. `/canvas` is taken (CanvasPage, below).
- The server SPA fallback serves `index.html` for extensionless non-API paths only. A path with a file extension returns a static 404 (`omnigent/server/app.py:5348-5362`).

### 1.3 Shell

- **`AppShell.tsx`** (3,202 lines, 41 commits) is the layout route.
  - It reads `const { conversationId, extensionId, gridId } = useParams()` (`AppShell.tsx:321-324`). Because AppShell is the parent route and still sees the child route's `:conversationId`, any child route with a `:conversationId` param switches AppShell into chat mode: per-session workspace rail, ChatHeader for that session, and `useIdleNotifications(conversationId)` at `AppShell.tsx:668`.
  - It hosts the persistent Canvas board through `GridWorkspace` → `CanvasWorkspace` (`AppShell.tsx:2752-3050`; `web/src/grid/GridWorkspace.tsx:30`; `web/src/canvas/CanvasWorkspace.tsx:54-233`). `canvasMode` is computed inside AppShell (`AppShell.tsx:328-333`).
  - It renders `ChatHeader` as an absolute overlay above routed pages (`AppShell.tsx:2785-2800`). Pages clear it with `--omnigent-header-height` (`index.css:221`).
- **`Sidebar.tsx`** (7,772 lines, 51 commits):
  - Brand row (`Sidebar.tsx:1252-1277`): a `Link` home with `branding.app_name` as plain `text-[15px] font-semibold` text, or an `<img src={omnigentWordmark}>` with `dark:invert` (`Sidebar.tsx:132, 1266-1277`). **No mark is shown next to `app_name`.**
  - Primary nav cluster (`Sidebar.tsx:1299-1446`): New session, Automations (`/tasks`), Inbox (with count badge), Canvas (`PrimaryNavLink`, gated, `Sidebar.tsx:1412-1421`), `<ExtensionPrimaryNavigation>` (`Sidebar.tsx:1423-1426`), Usage (gated).
  - Active state is `SIDEBAR_ACTIVE_HIGHLIGHT` / `--sidebar-active` (`web/src/shell/sidebarStyles.ts:17`; `web/src/shell/PrimaryNavLink.tsx:8-10`).
  - `useActiveNavItem()` (`Sidebar.tsx:566-614`) treats **any** route without a conversation id that is not inbox, canvas, tasks, usage or an extension as the New-session route (`Sidebar.tsx:595-603`). So `/workflows` would light up "New session" unless this list is extended.
  - `PrimaryNavLink` (`web/src/shell/PrimaryNavLink.tsx`, 62 lines, 1 commit) is the reusable nav row. `ExtensionPrimaryNavigation` (`web/src/extensions/ExtensionPrimaryNavigation.tsx:19-54`) shows the pattern of a self-contained component injected into the nav slot.
- **`CommandPalette.tsx`** (597 lines, 9 commits): a static `actions` array with New chat, Inbox, Automations, Settings and the sidebar toggles (`CommandPalette.tsx:185-234`). A Coral entry is a 7-line insertion.
- **`NewChatDialog.tsx`** (8,052 lines, 52 commits): the landing hero `NewChatLandingScreen` (`:2165`).
  - It reads `useHeading()` and `usePoweredBy()` (`:2242-2243`).
  - It renders `<BrandLogo variant="eyes" className="h-14 w-auto">` beside an `<h1 class="text-[28px] md:text-[2.15em] font-normal tracking-[-0.05em]">` (`:7037-7046`).
  - It renders the `PoweredByOmnigent` footer (`:7959-7965`).

### 1.4 Feature flags, capabilities and branding

- **Server.** `Feature` StrEnum plus `FEATURE_DEFINITIONS` with owner, review release and `frontend_visible` (`omnigent/server/feature_flags.py:23-42, 46-60, 125-135`). `frontend_dict()` exports every frontend-visible flag (`feature_flags.py:190-196`). Flags are enabled through `OMNIGENT_FEATURES`.
- **Web.** `FeatureKey` union (`web/src/lib/capabilities.ts:59-74`), `parseFeatures` (`:461-474`), `isFeatureEnabled(info, key)` (`:476-478`). Seam S33 is a one-line addition to the union plus the server enum entry (and the exact-dict test `tests/server/test_feature_flags.py`).
- **Branding path.**
  1. The server config `branding:` block (`deploy/README.md:669-690`) is served unauthenticated on `GET /v1/info` and `GET /v1/branding/logo/<variant>`.
  2. `parseBranding` (`capabilities.ts:377-405`) feeds `useBranding / useAppName / useHeading / useLogoUrl / usePoweredBy` (`web/src/lib/branding.ts:1-41`).
  3. Built-in defaults: `DEFAULT_APP_NAME = "Omnigent"`, `DEFAULT_HEADING = "What should we build?"` (`branding.ts:4-5`).
  4. `main.tsx:143-157` sets `document.title` and the favicon from branding.
  5. `BrandLogo` falls back to the Otto mascot (`OttoEyes` / `OttoIcon`) when no operator logo is set (`web/src/components/BrandLogo.tsx:89-95, 164-198`).
  6. `usePoweredBy()` is true only when operator branding is set and not disabled, so a deployment that sets any branding gets the "Powered by Omnigent" credit unless `powered_by: false` (`branding.ts:36-41`).
  7. Operator logos accept PNG, JPEG, GIF, WebP and ICO, **not SVG** (`deploy/README.md:684-690`).

### 1.5 State and data flow

- **Chat and streaming.**
  - The module-scope zustand `useChatStore` (`store/chatStore.ts`, 9,924 lines) projects the active conversation.
  - Per-conversation state lives in `ConversationRegistry` entries, which are LRU with `retain()` exemptions (`store/conversationRegistry.ts:120-140, 300-310`).
  - `ensureConversationStreamed(id)` binds a non-active conversation's stream for side panes (`chatStore.ts:4458-4473`).
- **Server data.** TanStack Query owns the server data:
  - `["conversations"]` and `["project-sessions"]` infinite lists;
  - `["conversation", id, "child_sessions"]` (`web/src/hooks/useChildSessions.ts:99-104`);
  - `["automation-inbox", scope]` (`web/src/hooks/useAutomationInbox.ts:23-33`);
  - scheduled tasks;
  - `["settings-agents", scope]` (`web/src/hooks/useCustomAgents.ts:33-48`).
- **Sidebar data** is shared through `SidebarDataProvider` / `useSidebarData()`. `useLoadedConversations()` returns the loaded **top-level** rows (`web/src/hooks/useSidebarData.tsx:385-396`). The inbox count is `sumPendingApprovals(inboxRows) + comments + automationInbox.items` (`useSidebarData.tsx:240-241`).
- **Preferences** use localStorage with try/catch (for example `canvasStorage.ts:1-40`; `CanvasWorkspace.tsx:33-41`) and `createStoredPreference` (`lib/storedChoicePreference.ts:20, 79`).
- **Top-level sessions only.** `GET /v1/sessions` defaults to `kind=default`, which excludes sessions with a `parent_conversation_id` (`omnigent/server/routes/sessions/routes_core.py:2096`; `omnigent/stores/conversation_store/sqlalchemy_store.py:3707-3711`). Child (sub-agent) sessions therefore never enter the sidebar list, the idle-notification feed or the inbox rows.

### 1.6 API client conventions

- Hand-written `web/src/lib/*Api.ts` modules: `sessionsApi`, `scheduledTasksApi`, `agentsApi`, `projectsApi`, `usageApi` and others. Each has camelCase TypeScript types over a snake_case wire, `xFromWire()` mappers, and typed errors (`ScheduledTaskApiError`, `apiErrorFromResponse`). See the header comment at `web/src/lib/scheduledTasksApi.ts:1-10` and the cursor page at `:490-516` (`{data, next_cursor}`).
- **No generated OpenAPI types in web.** `openapi.json` is written by `scripts/dump_openapi.py` (`--check` mode; drift test `tests/server/test_openapi_drift.py`) and synced to the docs site (`.github/workflows/sync-openapi-to-site.yml`). Nothing under `web/src` imports it. Whether routes added through `create_app(extra_routers=…)` land in `openapi.json` is **UNVERIFIED**.
- **Lint rules** (`web/.oxlintrc.json`):
  - no bare `fetch()`: use `authenticatedFetch` from `@/lib/identity`;
  - no direct `hostFetch`;
  - routing hooks only from `@/lib/routing`;
  - `import/no-cycle`;
  - `typescript/no-explicit-any`.

  Repo lint `dev/lint/lint_session_list_visibility.py` requires an explicit `visibility=` on any session-list request.
- **`sdks/`** holds Python packages only (`sdks/README.md`). `sdks/web-extension` is the browser-extension SDK, which is not a fit (deep dive §14.1).

### 1.7 Real-time transports

| Channel | Behaviour | Evidence |
|---|---|---|
| `WS /v1/sessions/updates` | One socket per tab. The client sends a watch-set of ids; the server pushes `snapshot`, `changed`, `removed`, `access_changed`, `hosts_changed`, `projects_changed` and `heartbeat` frames. The server rescans every 4 s and sends a heartbeat every 30 s; the client watchdog fires at 70 s. **Watch-set capped at 500 ids** (truncated server-side) | `web/src/lib/sessionUpdatesSocket.ts:1-50`; `omnigent/server/routes/_sessions/common.py:725, 731`; `routes_core.py:2740-2752` |
| Watch-set derivation | Union of: sidebar ids, project-folder ids, the open session, and **every child id in any mounted `["conversation", id, "child_sessions"]` query**. A child's `changed` frame invalidates its parent's child list | `web/src/hooks/SessionUpdatesProvider.tsx:258-298` |
| Per-session SSE `/v1/sessions/{id}/stream` | One long-lived fetch stream per live conversation. Stall guard at 45 s; heartbeat every 15 s | `web/src/lib/sse.ts:95-200` |
| Stream budget | `maxLiveConversations()`: 30 when multiplexed (HTTP/2), otherwise 3 (4 with the grid flag) | `store/conversationRegistry.ts:64-84` |
| Origin-wide slot manager | `navigator.locks` slot-locks (`omnigent:stream-slot:0..N-1`) shared across tabs. `getStreamSlotManager().tryAcquire()` | `web/src/store/streamSlots.ts:1-60, 136-146` |
| Reconnect backoff | `nextReconnectDelay`, `awaitReconnectDelay` (250 ms to 5 s; 60 s while the tab is hidden) | `web/src/lib/reconnectBackoff.ts:5-41` |
| SSE parser | `parseSseStream` is bound to the session event vocabulary (`parseEvent`) and **ignores `id:` lines**. `withStallGuard` is generic | `web/src/lib/sse.ts:127-200, 204-271` |
| Dev proxy | `/v1` is proxied with `ws: true`; SSE headers are flushed (`text/event-stream`) | `web/vite.config.ts:63-95, 118-125` |

### 1.8 Notifications and inbox

- **`useIdleNotifications(activeConversationId)`** is mounted once in AppShell (`AppShell.tsx:668`).
  - It diffs `useLoadedConversations()` (top-level rows only) for turn-end edges (`running` → `idle`/`failed`) and new elicitations (`useIdleNotifications.ts:122-125, 289-386`).
  - Turn-end has a 10 s settle window (`:72, 329-363`). Elicitations notify immediately (`:365-385`).
  - `notify()` sends `navigatePath: /c/<id>` (`:424-441`). The Electron main process forwards any SPA path back on click (`web/electron/src/main.js:4978-4993`).
- **No push channel.** The service worker is "installability/update-only" (`web/src/lib/browserNotifications.ts:8-10`). iOS has "foreground local notifications … does not implement APNs" (`web/ios/README.md:17-22`); Android has foreground-only local notifications (`web/android/README.md:30-37`).
- **Inbox** (`web/src/pages/InboxPage.tsx`, 1,240 lines, 13 commits):
  - The `InboxEntry` union is closed: `approval | comment | unread | automation` (`:189-193`).
  - Approvals come from sidebar rows with `pending_elicitations_count > 0` (`:240`) and render `ApprovalCard` with an injected `onSubmit = makeSubmit(item)` (`:425, 529-590`).
  - The automation kind is wired at about ten sites (`:193, 211, 219, 328, 335, 341-353, 417, 487-524, 938-947, 999-1004`).
  - The plain header is `<h1 className="text-2xl font-normal">Inbox</h1>` inside `PageScroll` (`:872-874`).

### 1.9 Reusable components for Coral (verified)

| Purpose | Component (path:line) | Fit and caveats |
|---|---|---|
| Agent transcript plus composer inside another page | `SideChatPane({childId, fullSession, readOnly})` (`components/chat/SideChatPane.tsx:166-180`), already composed as `SubagentTabPane({sessionId,label})` with read-only logic and an "Open full screen" link (`shell/SubagentTab.tsx:40-77`) | **Reuse** `SubagentTabPane` almost verbatim for the run view's agent pane. It binds the stream through `ensureConversationStreamed` (`SideChatPane.tsx:205`), which uses one SSE slot. |
| Agent node with status tint, handles and zoom controls | `SubagentsGraphView` `AgentNodeComponent` + `ACTIVITY_TINT` + `ZoomControls` (`shell/SubagentsGraphView.tsx:25-126`). Layout is a hand-rolled tree (`shell/subagentGraphLayout.ts:43-50`) | **Copy the pattern, not the component.** It is read-only, tree-shaped and keyed to child sessions. |
| Session card on a canvas | `SessionCard` (`canvas/SessionCard.tsx:1-60`), `CanvasPage` controls and `proOptions={hideAttribution:true}` (`pages/CanvasPage.tsx:85-140`) | Use as a pattern only. CanvasPage is about sessions, not workflows. |
| Status of a child session | `childStatus(child)` → `AgentActivity` plus `activityDotClassName` (`shell/subagentStatus.ts:79-142`); `useChildSessions(id)` (`hooks/useChildSessions.ts`); `ChildSessionInfo` carries `labels`, `busy`, `pending_elicitations_count` (`useChildSessions.ts:28-60`) | **Reuse** for roster chips when step sessions are children. |
| Status of a top-level session | `getSessionState(conv)` (`hooks/useSessionState.ts:30-45`); `SessionStateBadge({state})` (`components/SessionStateBadge.tsx:103`) | **Reuse.** |
| Gates and `ask_user` | `ApprovalCard` (props `:207-305`, `onSubmit?: SubmitApprovalFn` `:134-145`); `ElicitationCard` is **exported from `ApprovalCard.tsx:1080`**, not a separate file; `ElicitationSchemaForm` (enum → select, boolean, number, text) (`components/blocks/ElicitationSchemaForm.tsx:1-60`); resolve API `POST /v1/sessions/{id}/elicitations/{eid}/resolve` (`lib/sessionsApi.ts:1651-1670`) | **Reuse.** |
| Monaco | `ensureMonacoReady`, `ensureLanguage`, `monacoLanguageId`, `resolvedThemeToMonaco` (`shell/monacoSetup.ts:75-152`); base editor worker only, so **no YAML language service** (`monacoSetup.ts:12-17`) | **Reuse the setup**, not `MonacoCodeEditor`. That component is tied to session files: `conversationId`, `useCanEdit(conversationId)`, comments, autosave (`shell/MonacoCodeEditor.tsx:124-175`). |
| Split view with a resizable divider | `CanvasWorkspace` divider and ratio persistence (`canvas/CanvasWorkspace.tsx:128-222`) | **Copy** into a Coral `SplitPane` rather than generalizing an upstream file. |
| Run-history page template | `TasksPage` (list, tabs, intro, header) (`pages/TasksPage.tsx:229-275`) and `TaskDetailPage` (`RunRow`, `RunStatusIcon`, `Section`, polling runs) (`pages/TaskDetailPage.tsx:72-860`) | Use as a pattern. |
| Inbox feed precedent | `useAutomationInbox` + `useSeenAutomationFailures` + `listAutomationFailures(after)` (`hooks/useAutomationInbox.ts:10-44`; `lib/scheduledTasksApi.ts:490-516`) | Clone it for the `workflow` kind. |
| Scroll and insets | `PageScroll` (header-height and safe-area insets) (`components/PageScroll.tsx:42-75`); `.canvas-page-heading` clearance (`index.css:1267-1274`; `CanvasPage.tsx:590`) | **Reuse.** |
| Host, workspace and agent pickers | `WorkspacePickerDialog`, `ProjectPicker`, `useHosts`, `useHostWorktrees`, `useAvailableAgents`, all used by `CreateScheduledTaskDialog` (`components/scheduled/CreateScheduledTaskDialog.tsx:55-66`). `AgentHarnessPicker` is exported from NewChatDialog, so do not import it from Coral (churn) | Reuse the hooks and `WorkspacePickerDialog`. |
| Custom (user) agents | `SettingsCustomAgentsSection` (`pages/settings/SettingsCustomAgentsSection.tsx:43-495`), `CreateAgentForm` (`shell/CreateAgentDialog.tsx:234`), `CustomAgentConfigForm` (`pages/settings/CustomAgentConfigForm.tsx:29`), `useCustomAgents`, `getAgentConfig`/`patchAgentConfig` with ETag/If-Match (`lib/agentsApi.ts:76-100`), `buildAgentBundle` (`lib/agentBundle.ts:45`). Gated by `custom_agents_settings_ui` + `agent_detail` | The base for **Profiles**. |
| Created-by chip in ChatHeader | `CreatedBySession` chip (`shell/ChatHeader.tsx:635-636`) | The precedent for a "Part of run …" chip. |
| Command list | `components/ui/command.tsx` (cmdk) | The basis for the profile picker. |

### 1.10 Theme and brand system

- **Two axes.** next-themes owns mode (`.dark`). `themePalette.ts` owns the palette (`data-theme` attribute; the default `omni` sets no attribute) (`web/src/lib/themePalette.ts:1-50`).
- **Palette tokens** (`PaletteTokens`, `:62-102`) map to CSS names (`:104-143`). They cover background, card, primary, ring, `brandAccent`, the sidebar tokens, and the **`sidebarBackground` / `shellBackground` tokens, which accept full CSS background values including gradients** (other palettes already use `linear-gradient` at `:327, 386, 445, 505, 636`). The Omni dark sidebar already uses a gradient (`:289-290`).
- **The `omni` palette** is `label: "Omnigent", blurb: "The signature pink brand look."` with `primary #df3c85` (`themePalette.ts:216-295`). The generator special-cases `palette.id === "omni"` to emit `:root:not(.dark):not([data-theme])` (`web/scripts/generate-theme-palettes.mjs:16-23`). The output is `src/themePalettes.generated.css`. It runs through `just generate-theme-palettes` (`justfile:108-109`) and is checked in pre-commit by `generate-theme-palettes.mjs --check` (`.pre-commit-config.yaml:82-83`).
- **Not palette tokens:** status, chart, tag and CTA tokens live in `index.css` `:root` and `.dark` and apply to **every** palette: `--success/--warning/--info` (`:259-261`), `--tag-pink` (`:270`), `--status-*` (`:272-276`), `--chart-1..5` (`:277-281`), `--primary-cta` (`:185-186`), and their dark versions (`:299-343`).
- **Fonts.**
  - `@theme inline { --font-heading: var(--font-sans); --font-sans: ui-sans-serif, system-ui, …; --font-mono: "Geist Mono Variable", "JetBrains Mono", … }` (`index.css:44-52`).
  - **`font-heading` is already used** by `CardTitle` (`components/ui/card.tsx:41`) and `DialogTitle` (`components/ui/dialog.tsx:146`).
  - `--ease-otto` is at `index.css:286`.
- **Shell background.**
  - `.app-shell { background: var(--shell-background, var(--background)) }` (`index.css:1007-1010`).
  - Dark `.app-shell` adds `omnigent-center-glow.svg` (`:1016-1023`). Its white stop colours and filter parameters are **pinned by `index.css.test.ts:205-220`**.
  - The light sidebar rule must not contain `radial-gradient` (`index.css.test.ts:849-853`), and generated palette CSS must not contain `.app-shell` or `.conversations-sidebar` (`:199-204`). Washes therefore have to be token values, which is allowed.
- **Mascot and assets.**
  - `OttoEyes` and `OttoIcon` are used only by `BrandLogo` (fallback) and `PoweredByOmnigent`.
  - The working indicator uses `<BrandLogo variant="icon" className="otto-working …">` (`components/chat/chatBubbleParts.tsx:603`; CSS `index.css:2329-2343`).
  - The starfish PNG is imported directly by `components/onboarding/AnimatedOmnigentPanel.tsx:13` and `pages/onboarding/AuthCardShell.tsx:8`.
  - Wordmark: `assets/omnigent-wordmark.svg`.
  - `web/index.html` has `<title>Omnigent</title>`, `theme-color #0d1218`, a boot-loading `#fff` background, `favicon.svg` and `apple-touch-icon.png`.

### 1.11 Native shells

- **All three shells load the server's SPA** (`web/electron/README.md:98-112`; `web/ios/README.md:1-5`), so Coral routes ship with the server.
- **Electron** (`web/electron/package.json`):
  - `"productName": "Omnigent"`, `appId ai.omnigent.desktop`, protocol `omnigent`;
  - **`publish.url https://omnigent.ai/_desktop/updates/`** (`:40-60`);
  - dev builds `-c.productName='Omnigent Dev'` (`:21-25`).
- **`main.js`** (6,234 lines, 36 commits):
  - about 37 user-facing "Omnigent" literals (for example `:1701-1705, 2445, 2677, 3453-3454, 3655-3668, 3679, 5862-5865`);
  - `app.setName(isDevBuild ? "Omnigent Dev" : "Omnigent")` and the userData path (`:6031-6033`).
- **Setup and connect pages:**
  - `setup/index.html` (964 lines, 0 commits): title "Omnigents — Connect" (`:6`), logo `../../platform-assets/logos/omnigents-logo.svg` (`:453`), copy "Run an Omnigent server…" (`:455`), and Omnigent CLI copy (`:425-926`);
  - `server-selector-v2.html` (title `:6`), backed by `src/server-selector-v2.tsx` and `pages/onboarding/ServerSelectorV2.tsx` / `AnimatedOmnigentPanel`.
- **Icons:** `web/electron/icons/{icon.icns, icon.png, icon.ico, icon.svg, Assets.car}`. **`Assets.car` (from `platform-assets/AppIcon.icon`, Apple Icon Composer) gives the dynamic icon on macOS 26+ through `CFBundleIconName=AppIcon`. Regenerating it needs Xcode 26** (`web/electron/icons/README.md`).
- **Deep links** accept only `omnigent://host/c/<id>`: Electron `parseOmnigentDeepLink` (`web/electron/src/deepLink.js:20-45`) and iOS `DeepLink.parse` (`web/ios/Omnigent/DeepLink.swift:100-133`). This is S38.
- **App names:** iOS `PRODUCT_NAME = $(TARGET_NAME)` with bundle id `ai.omnigent.ios` (`web/ios/Omnigent.xcodeproj/project.pbxproj:693-694`). Android `app_name` is "Omnigent" (`web/android/app/src/main/res/values/strings.xml:3`) with `applicationId "ai.omnigent.android"` (`web/android/app/build.gradle.kts:65`).

### 1.12 Testing and lint

- **Vitest** with jsdom, globals, `setupFiles: ./src/test-setup.ts`, and include `src/**/*.{test,spec}.*` (`web/vite.config.ts:255-292`). Test-setup mocks heavy icons, polyfills `ResizeObserver` and `matchMedia`, and mocks `@tanstack/react-virtual` (`web/src/test-setup.ts:1-140`).
- **"@xyflow/react OOMs in jsdom":** tests mock it (`web/src/shell/SubagentsGraphView.test.tsx:19-33`; `SubagentsGraphView.nodeClick.test.tsx:17-39`; `pages/CanvasPage.test.tsx:42-80`). Pure layout lives in xyflow-free modules and is tested directly. **Graph logic must therefore stay outside xyflow-importing files.**
- **Monaco tests** mock `@monaco-editor/react` (`shell/MonacoCodeEditor.*.test.tsx`).
- **Route tests:** `App.test.tsx` uses `renderRoute(path, features, info)` with feature-gated route suites (`:260-363`).
- **CSS contract tests:** `index.css.test.ts` (1,585 lines) asserts on token and surface rules (palette composition `:183-280`, sidebar canvas `:827-866`, selection colours `:1091-1101`).
- **Storybook 10:** stories tagged `visual-snapshot` become CI visual baselines (`tests/e2e_ui/visual/README.md`; `.github/workflows/ui-snapshot.yml:195`). The landing and sidebar snapshots pin the current brand (`tests/e2e_ui/visual/test_landing_snapshot.py`, `test_sidebar_snapshot.py`). `tests/e2e_ui/branding/test_branding.py:116-124` pins the unbranded defaults ("What should we build?" and the "Omnigent" link).
- **Per CLAUDE.md, no local browser runs.** Browser lanes (`tests/browser_ui/`, `tests/e2e_ui/`) run in CI only.

### 1.13 Churn of files Coral would touch (2026-10-09 to 2026-11-08)

| File | Commits | Lines | Coral edit type |
|---|---|---|---|
| `web/src/shell/NewChatDialog.tsx` | 52 | 8,052 | Hero: 1-line swap to `<CoralHero/>` |
| `web/src/shell/Sidebar.tsx` | 51 | 7,772 | Brand row 1-line swap; 1-line nav insert; `useActiveNavItem` 2-line exclusion |
| `web/src/shell/AppShell.tsx` | 41 | 3,202 | **Avoid entirely** (§4.1) |
| `web/electron/src/main.js` | 36 | 6,234 | Strings (prefer one `brand.js` constant module) |
| `web/src/lib/capabilities.ts` | 31 | 705 | 1-line `FeatureKey` |
| `web/src/index.css` | 27 | 2,983 | Font token, Coral block |
| `web/src/components/chat/SideChatPane.tsx` | 18 | 1,186 | None (reuse) |
| `web/src/components/blocks/ApprovalCard.tsx` | 14 | 1,125 | None (reuse) |
| `web/src/pages/InboxPage.tsx` | 13 | 1,240 | Workflow kind (~80 lines), header swap |
| `web/src/pages/TasksPage.tsx` | 13 | 475 | Header swap |
| `web/src/index.css.test.ts` | 11 | 1,585 | Update or extend assertions |
| `web/src/shell/ChatHeader.tsx` | 9 | 890 | Optional 1-line `<CoralRunChip/>` |
| `web/src/shell/CommandPalette.tsx` | 9 | 597 | 7-line action |
| `web/src/hooks/useSidebarData.tsx` | 7 | 405 | Inbox count (+3 lines) |
| `web/src/App.tsx` | 6 | 272 | Routes (+40 lines) |
| `web/src/hooks/SessionUpdatesProvider.tsx` | 5 | 551 | S35 only if needed (§3.6) |
| `web/src/lib/themePalette.ts` | 4 | 742 | `omni` slot tokens (data-only edit) |
| `web/src/main.tsx` | 3 | — | 1-line `<CoralRuntimeProvider>` |
| `web/src/hooks/useIdleNotifications.ts` | 1 | 458 | S36 (+3 lines) |
| `web/src/lib/branding.ts` | 0 | 41 | Defaults |
| `web/src/components/BrandLogo.tsx` | 0 | 198 | Fallback → Coral mark |
| `web/electron/setup/index.html` | 0 | 964 | Restyle and copy |

---

## 2. Discrepancies: D1–D4 confirmed or refined, plus new findings N1–N19

### D1 (Draft 4 versus the deep dive): frontend-relevant parts

| Draft 4 claim | Status at HEAD | Frontend implication |
|---|---|---|
| "Approvals on any device: Elicitations, inbox, **web push**, mobile apps" (`coral-design.md:83`, §13 "Approvals work in the browser, the desktop app and on the phone") | **False for push.** No VAPID, APNs or FCM. Notifications are page-scoped (`browserNotifications.ts:8-10`), and iOS and Android are foreground-only (`web/ios/README.md:17-22`; `web/android/README.md:30-37`) | The run view and inbox must say plainly that a waiting gate reaches you only when the app is open, or through Slack for Slack-originated sessions. Push is a separate large project, not FE scope here. |
| `cost_budget` "pauses the run and asks the user" (`coral-design.md:346`) | False (deep dive F42/finding 10): it ASKs at thresholds and DENYs at the cap, per session | The FE must show **two different things**: an engine run pause (`paused(budget)` in the run header) and per-session policy ASK cards inside a step session. Label the latter "Session budget check", or users will read it as the run gate. |
| "fail-closed sub-agent router", `PersistentTaskScheduler` for the signal queue, `sys_cancel_task` no-op, sandbox network on/off, 70% versus 80% refresh | Engine and harness facts; not FE | The only FE touch is the refresh threshold: the orchestrator "refresh marker" UI (§3.5) is the same whatever the threshold. |

**Refinement.** Draft 4 §13 says "**Approvals** work in the browser, the desktop app and on the phone". That is true for elicitation **rendering** in all three shells, because they load the same SPA. It is false for **delivery** while the app is closed.

### D2: `coral-requirements.md` is missing (confirmed)
`ls coral-requirements.md` fails, and `git ls-files | grep -i coral` returns nothing. FE requirements must be inferred from `coral-design.md` §5.2, §8, §12, §13 and the UI doc. Open questions are listed in §6.

### D3: UI doc versus design (confirmed and refined)
- **Prototype files absent:** `web/src/components/concerto/` does not exist, no `concerto` string exists in `web/src`, and `CoralLogo.tsx`, `/schemas` and `/profiles` are absent. All UI-doc §10 touchpoints are **New**.
- **Routes.** Recommendation in §3.2: `/workflows` (label **Workflows**) and `/profiles` (label **Agent Profiles**). Drop `/schemas`, which conflicts with Omnigent's "schema" meaning (`requestedSchema`); the design never uses it, and UI doc §5.3 says the words are provisional.
- **Node taxonomy.** Use the design's kinds: Start, End, Work step, Orchestrator node (IR kind `decision`, deep dive §5.1), Human gate and Group, plus hidden Wait and Sub-workflow. Map the UI doc's accent treatments onto them:
  - Phase → Work step (forest);
  - Gate → Human gate (mustard);
  - Orchestrator → Orchestrator node (clay).
  - **Note** has no engine meaning, so make it a **layout-only annotation** (sage) stored in the layout file, never in the workflow YAML.
- **Profiles.** The UI doc's "localStorage scaffolding" is incompatible with the design, which requires server or repo resources: V10 "roster profiles resolve to pinned revisions" (deep dive §5 V10). Profiles must be server-backed (§3.7).

### D4: Elephant-Goldfish step options (confirmed; FE part)
The inspector's roster editor needs two per-member options that Draft 4 lacks: "**keep this member's session across loop passes**" and "**inputs this member sees**" (a selector over incoming handoff parts and files). Build the roster-member row with an "Advanced" disclosure so these slot in once the engine supports them. Hide them until the schema has the fields.

### New findings

- **N1. `font-heading` is already in use.** `CardTitle` (`components/ui/card.tsx:41`) and `DialogTitle` (`components/ui/dialog.tsx:146`) use `font-heading`, and `index.css:45` maps it to sans. The UI doc's "`--font-heading` → Newsreader" would make **every dialog and card title serif**, which violates the doc's own "serif only on brand moments" rule (§3.2). **Fix:** add `--font-display` (utility `font-display`) for Newsreader and leave `--font-heading` alone.
- **N2. Status remap scope.** Status, chart, tag and CTA tokens sit in `index.css :root/.dark` and are not palette tokens (`index.css:185, 259-281, 299-343`). The UI doc's §2.4 remap done in `:root` would recolour the GitHub, Dracula and other palettes too. **Fix:** put the Coral remap under the default-palette selectors only (`:root:not(.dark):not([data-theme])` / `.dark:not([data-theme])`), or extend `PaletteTokens` with optional status tokens. Prefer the scoped block, which leaves the generator untouched.
- **N3. Dock icon is more than `icon.png` and `.icns`.** macOS 26+ reads `Assets.car` compiled from `platform-assets/AppIcon.icon` (Icon Composer), and regenerating it needs Xcode 26 (`web/electron/icons/README.md`). The UI doc (§4.4, §10) lists only `icon.png` and `.icns`. Without a new `Assets.car`, macOS 26 still shows Omnigent's icon. The full set also includes `icon.ico` (Windows), `icon.svg` (Linux) and the shared iOS AppIcon.
- **N4. Server `branding:` cannot produce the Coral look.**
  - The sidebar shows `app_name` as plain text with no mark (`Sidebar.tsx:1266-1270`).
  - SVG logos are rejected (`deploy/README.md:684-690`).
  - Setting any branding turns on "Powered by Omnigent" with the Otto mascot unless `powered_by: false` (`branding.ts:36-41`; `PoweredByOmnigent.tsx`).

  **Fix:** change the built-in defaults in code (`DEFAULT_APP_NAME`, `DEFAULT_HEADING`, the fallback mark, the wordmark row). Keep operator branding as an override that keeps the Coral layout. Whether the default "Powered by Omnigent" credit stays is a counsel question (deep dive §16.3).
- **N5. Default heading text.** The baseline is `"What should we build?"` (`branding.ts:5`), not "What should we do?" (UI doc §1). Coral's default becomes "Direct the run…".
- **N6. Deep dive route `/workflows/runs/:runId/c/:conversationId` (§14.1) puts AppShell into chat mode.** AppShell, the parent layout route, reads `useParams().conversationId` (`AppShell.tsx:321`). The proof that a parent sees child params is that this very line resolves `c/:conversationId`. With that param set, AppShell scopes its workspace rail, ChatHeader and idle-notification suppression to that id. Meanwhile `useActiveConversationId()` recognizes only `/c/` and `/canvas/c/` prefixes (`hooks/useActiveConversationId.ts:17`), so the two disagree. **Fix:** select the focused agent with a query param (`/workflows/runs/:runId?agent=<sessionId>&node=<nodeId>&scope=<scopeKey>`) and render the transcript inside the run view. Never name a Coral route param `conversationId`.
- **N7. `useActiveNavItem` lights "New session" on unknown routes** (`Sidebar.tsx:595-603`). **Fix:** a 2-line exclusion through a Coral `isCoralDeskPath(pathname)` helper.
- **N8. AppShell is not the only hot file.** `Sidebar.tsx` (51 commits) and `NewChatDialog.tsx` (52 commits) are hotter than AppShell (41); the deep dive's churn table lists only AppShell (§17). Every touch must be a delegate one-liner.
- **N9. S36 refined.** With the deep dive's recommended topology (step sessions are children of the orchestrator, §8.2), step sessions **never** reach `useIdleNotifications`. The feed is top-level rows (`routes_core.py:2096`; `useIdleNotifications.ts:125`). S36 therefore matters only for the **top-level orchestrator session**, whose every turn end would beep, and for any top-level step sessions. It must suppress **turn-end only**, not elicitations, because gates are elicitations on the orchestrator. The filter key is the session label (e.g. `coral.run_id`); `Conversation.labels` is on every row (`hooks/useConversations.ts:181`).
- **N10. S35 refined.**
  - For child step sessions, simply mounting `useChildSessions(orchestratorSessionId)` in the run view already adds every child to the watch-set (`SessionUpdatesProvider.tsx:283-293`). **No change to SessionUpdatesProvider is needed for the child topology.**
  - S35 is needed only for top-level step sessions (other hosts) or when an orchestrator refresh creates a new orchestrator session whose children differ. Whether children are re-parented after a refresh is **UNVERIFIED**.
  - The watch-set is capped at 500 ids and truncated server-side (`common.py:731`; `routes_core.py:2740-2752`). Any union must put run ids **first**.
- **N11. The run SSE must share the stream budget.** Over HTTP/1.1, which local Coral and the Vite dev server use, `maxLiveConversations()` is 3 (`conversationRegistry.ts:75-84`). It is enforced origin-wide by `streamSlots.ts`. The run-log SSE is one more long-lived connection the budget does not know about. With the focused agent pane (1), the orchestrator pane (1), another live conversation (1) and the run stream (1), the six-connection pool is nearly exhausted for ordinary fetches. **Fix:** the run-stream client calls `getStreamSlotManager().tryAcquire()`. On `null` it evicts through `conversationRegistry.evictLruEvictable()`, or falls back to polling `GET …/log?after_seq=`.
- **N12. URL params must be extensionless.** The SPA fallback returns a static 404 for any path with a file extension (`app.py:5358-5362`). Never put `review.yaml` in a route. Use the workflow `id` (a YAML key) or an opaque key.
- **N13. The Electron auto-updater still points at Omnigent.**
  - `publish.url https://omnigent.ai/_desktop/updates/` (`web/electron/package.json:55-60`): Coral desktop builds would update **into Omnigent builds**.
  - Also rename `appId ai.omnigent.desktop`, the `omnigent://` scheme (`package.json:47-53`; `deepLink.js:6-45`; iOS `DeepLink.swift:101`), and `app.setName("Omnigent")` (`main.js:6031-6033`), which sets the userData directory.

  The UI doc §10 lists only `productName`, setup and main strings.
- **N14. `ElicitationCard` lives in `ApprovalCard.tsx:1080`**, not a separate file (deep dive §14.3 lists it separately).
- **N15. `MonacoCodeEditor` is not reusable for the YAML pane.** It is tied to session files (`MonacoCodeEditor.tsx:124-175`: `conversationId`, `useCanEdit`, comments, autosave to the session filesystem). Use `@monaco-editor/react`'s `Editor` with `monacoSetup.ts` helpers. There is no YAML language worker (`monacoSetup.ts:12-17`), so validation markers come from Coral's validator through `monaco.editor.setModelMarkers`.
- **N16. Library availability.**
  - `yaml` (eemeli, ISC) must be added as a direct dependency. 2.9.0 is already in the lockfile transitively, so it passes the 7-day cooldown.
  - `elkjs` is present only transitively, through `@lobehub/ui` → `beautiful-mermaid`.
  - `@dagrejs/dagre` (MIT) is absent.
  - Newsreader must be added (`@fontsource-variable/newsreader` or `@fontsource/newsreader`, OFL-1.1). Pick a version at least 7 days old.
- **N17. Profiles have a ready base.** User-agent install, list, detail and patch-with-ETag are wired in web (`lib/agentsApi.ts:19-100`; `hooks/useCustomAgents.ts:33-70`; `pages/settings/SettingsCustomAgentsSection.tsx`), even though `designs/REUSABLE_USER_AGENTS.md` still reads "PROPOSED".
- **N18. Phase-1 gates will not appear in Inbox.** The inbox lists approvals only from session elicitations (`InboxPage.tsx:240`). Deep dive §19 says phase-1 gates are answered "through the Coral API" and the elicitation surface comes in phase 2. Until then, gates need the `workflow` inbox kind (S37) or must be answered only in the run view.
- **N19. A desk header cannot be a naive top band.** AppShell overlays `ChatHeader` on every routed page, and pages clear it with `PageScroll`'s `--omnigent-header-height` and inset maths (`PageScroll.tsx:54-64`; `index.css:221`). Full-bleed pages such as Canvas draw their own header with the `.canvas-page-heading` clearance (`CanvasPage.tsx:590`; `index.css:1267-1274`). `CoralPageHeader` must come in two variants (§3.1).

---

## 3. Plans per Coral UI capability

Each plan lists: files to **reuse, modify or create**; components; state and data flow; endpoints (proposed shapes); test approach; risks; size. Coral-owned web code lives under **`web/src/workflows/`** (product) and **`web/src/brand/`** (skin). Both paths go in the fork patch-ledger allowlist (deep dive §17 practice 3 lists only `web/src/workflows/`, so add `web/src/brand/` and `web/electron/src/brand.js`).

### 3.1 Brand skin and desk chrome

**Goal:** the UI doc's firm checklist (§8.1, §11).

| Touchpoint | Action | Detail |
|---|---|---|
| `web/src/lib/themePalette.ts:216-295` (`omni` entry) | **Modify (data only)** | Keep `id: "omni"`, because the generator special-cases it (`generate-theme-palettes.mjs:16-23`) and users' stored preference uses it. Change `label` to "Coral" and the blurb, swatches and light and dark tokens to the UI doc §2.2 and §2.3 values. Light: `background #FEF7F1`, `card #FFFDF9`, `cardSolid #FFFFFF`, `foreground #523E31`, `muted #EFE4D8`, `mutedForeground #8A7566`, `secondary/sidebar #F5EBE1`, `border #E0D2C4`, `borderStrong #C9B5A4`, `primary/ring/brandAccent #864A31`, `link #6F3C28`, `accent #F6EEE6`, selection `rgba(134,74,49,.12)`. Dark: `#2A211C` and so on; primary/ring `#C19A55`, brandAccent `#864A31`. Washes go in token values: `shellBackground: "radial-gradient(at 0% 0%, rgb(77 115 86 / 8%), transparent 55%), radial-gradient(at 100% 0%, rgb(193 154 85 / 10%), transparent 55%), radial-gradient(at 100% 100%, rgb(134 74 49 / 7%), transparent 55%), #FEF7F1"`. `sidebarBackground` gets a vertical forest wash plus a diagonal mustard wash on `#F5EBE1`; dark is `#241C18` plus clay and forest overlays. Then run `just generate-theme-palettes`; the pre-commit `--check` guards it. |
| `web/src/index.css` | **Extend** (small, near `:44-52` and after the `.dark` block) | (a) Add `--font-display: "Newsreader Variable", "Iowan Old Style", Palatino, Georgia, "Times New Roman", serif;` in `@theme inline`; **do not** touch `--font-heading` (N1). (b) Add `@import "@fontsource-variable/newsreader";` next to `:5`. (c) A Coral block scoped to the default palette for the status, chart, tag and CTA remap (N2): `:root:not(.dark):not([data-theme]) { --success:#4D7356; --warning:#C19A55; --info:#9EAB92; --chart-1..5: forest, sage, mustard, clay, ink; --tag-pink: rgba(134,74,49,.08); --primary-cta:#864A31; --primary-cta-foreground:#FEF7F1; }` plus a dark equivalent. **Keep `--status-red` / `--destructive` red for failures**, as the UI doc §2.4 allows. Alternatively, place the block in **new** `web/src/brand/coral.css` imported from `index.css` (a 1-line edit), which keeps future token edits out of the hot file. |
| `web/src/brand/tokens.css` (or `coral.css`) | **New** | `--coral-forest/sage/mustard/clay/ink` light and dark ramps plus `@theme` utilities (`bg-coral-forest`, …). Use the `coral-*` names, not `--concerto-*`. |
| `web/src/brand/CoralMark.tsx` | **New** | An inline SVG component for the circular leaf/mosaic mark on a transparent background (an asset is needed from design). Props `className`, `title`. SVG so it tints in dark mode. |
| `web/src/brand/CoralWordmark.tsx` | **New** | `inline-flex items-center gap-2.5` with `CoralMark` (`size-7 block object-contain`) and `<span class="font-display text-[20px] font-medium tracking-[-0.03em] leading-none">{appName}</span>` (UI doc §3.3, §4.2). |
| `web/src/brand/AccentRail.tsx` | **New** | Five 6 px dots: forest → sage → mustard → clay → ink, `aria-hidden`. |
| `web/src/brand/CoralPageHeader.tsx` | **New** | Two variants because of N19. **`list`** goes inside `PageScroll` and renders a header band: `AccentRail`, `<h1 class="font-display text-2xl font-medium tracking-[-0.03em]">`, a 13 px muted description, and right-aligned actions. **`fullBleed`** is for the editor and run view: `<header class="canvas-page-heading border-b px-6 py-4">` that respects `.canvas-page-heading` clearance and `--omnigent-header-height`. Props `{title, description?, actions?, leading?, variant}`. |
| `web/src/lib/branding.ts:4-5` | **Modify** | `DEFAULT_APP_NAME = "Coral"`, `DEFAULT_HEADING = "Direct the run…"`. |
| `web/src/components/BrandLogo.tsx:89-95` | **Modify** (3 lines) | `FallbackLogo` returns `<CoralMark/>` for both variants, with an optional subtle pulse for `icon` so `.otto-working` users keep a working indicator. This one change switches the hero, the working indicator (`chatBubbleParts.tsx:603`) and every `BrandLogo` site. |
| `web/src/shell/Sidebar.tsx:1266-1277` | **Modify (1 swap)** | Replace the ternary with `<CoralWordmark appName={branding.app_name ?? undefined} />`. Operator `app_name` keeps the layout (UI doc §4.2). Keep `data-testid="sidebar-brand"`. |
| `web/src/shell/NewChatDialog.tsx:7037-7046` | **Modify (1 swap)** | Replace the `BrandLogo` + `h1` pair with `<CoralHero heading={…}/>` (**New** `web/src/brand/CoralHero.tsx`): one flex row with the mark at `h-[1em] w-[1em]` beside the `font-display` heading at about 2.55em desktop and 34 px (UI doc §4.3). Keep the existing mobile, project and sibling branches outside or passed through. |
| `web/src/components/PoweredByOmnigent.tsx` | **Decision** | Keep as an upstream credit or hide by default. A counsel question (deep dive §16.3). |
| `pages/InboxPage.tsx:872-874`, `pages/TasksPage.tsx:238-258` | **Modify** | Swap the header blocks for `<CoralPageHeader variant="list" title="Inbox" …/>` and `title="Automations"` (UI doc §5.2 requires it). Keep the count pill and the intro button as `actions`/`trailing`. |
| `web/src/components/onboarding/AnimatedOmnigentPanel.tsx:13`, `pages/onboarding/AuthCardShell.tsx:8`, `components/onboarding/BlobGraphic.css` | **Replace / Modify** | Import `coral-mark.png`/`CoralMark` instead of `omnigent-starfish-icon.png`. Recolour the blobs to forest, mustard, terracotta and sage (UI doc §7). |
| `web/index.html` | **Modify** | `<title>Coral</title>`, `theme-color #FEF7F1`/dark, boot-loading background cream; **Replace** `web/public/favicon.svg` and `apple-touch-icon.png`. |
| `web/electron/setup/index.html`, `web/server-selector-v2.html` | **Modify** | Title "Coral — Connect"; cream plus forest, mustard and clay radials; brand row with mark and Newsreader "Coral" centred; accent rail; copy "Run a Coral server…"; clay or mustard primary buttons. These are standalone HTML, so **hex values are duplicated** (Tailwind tokens are not available); keep a comment pointing at `brand/tokens.css`. Newsreader must be bundled locally (`@font-face` from the fontsource files) because the connect page is offline-capable. |
| `web/platform-assets/logos/*`, `web/platform-assets/AppIcon.icon`, `web/electron/icons/{Assets.car,icon.icns,icon.png,icon.ico,icon.svg}` | **Replace** | Dock icon: cream rounded plate, mark at about 72% (UI doc §4.4), **plus `Assets.car`** (N3; needs Xcode 26). Linux `icon.svg` and Windows `.ico` too. |
| `web/electron/package.json` | **Modify** | `productName`, `build.productName`, the dev `-c.productName`, `appId`, protocol name and scheme (`coral`), **`publish.url`** (N13), `description`, `author`. |
| `web/electron/src/main.js` | **Modify** | Introduce **New** `web/electron/src/brand.js` (`PRODUCT_NAME`, `DEV_PRODUCT_NAME`, `URL_SCHEME`) and replace the ~37 literals plus `app.setName` (`:6031`). It is a one-time churn hit on a 36-commit file. Also `about/index.html` and `about/index.js` (4 and 2 strings) and `connection-loading/index.html` (2). |
| iOS / Android | **Modify** | Display name (`INFOPLIST_KEY_CFBundleDisplayName` or a target rename; the current Info.plist lacks `CFBundleDisplayName`, see `project.pbxproj:693-728`). Android `strings.xml:3` `app_name`. The bundle ids `ai.omnigent.*` are a store and legal decision. Deep-link schemes (S38). |

**State and data flow:** none. This is CSS tokens and static components, plus `useBranding()` for operator overrides.

**Tests:**
- Update `index.css.test.ts`: add assertions that `font-display` exists and that `--font-heading` stays sans (guards N1), and that the Coral status block is palette-scoped. Keep the existing glass and glow assertions.
- `themePalette` generator check (pre-commit).
- Unit tests: `CoralWordmark` (operator `app_name` replaces the word and keeps the mark), `BrandLogo` fallback (update `components/BrandLogo.test.tsx`), `CoralPageHeader` (renders the h1 and actions; rail `aria-hidden`).
- Storybook stories tagged `visual-snapshot` for `CoralPageHeader` (list and full-bleed), `CoralHero` and `CoralWordmark`.
- **CI-only updates:** `tests/e2e_ui/branding/test_branding.py:116-124` (new defaults); visual baselines `test_landing_snapshot.py` and `test_sidebar_snapshot.py`, regenerated through `.github/workflows/ui-snapshot-update.yml`; `NewChatDialog.test.tsx` and `Sidebar.subagentHighlight.test.tsx`, which reference `sidebar-wordmark` and "What should we build?". No local browser runs.

**Risks:**
- Hot-file merges: Sidebar, NewChatDialog and `index.css` (keep edits to 1-line delegates).
- The CSS contract tests are strict; read `index.css.test.ts:183-280, 827-866` before editing tokens.
- The Electron updater (N13).
- Brand asset production needs a designer (mark, `.icon` bundle).
- Legal: the Apache-2.0 NOTICE stays; the "Powered by Omnigent" choice.

**Size:**
- Web: about 600–900 LOC of production code (tokens 150, components 300, swaps 50, onboarding 100) plus about 400 test LOC.
- Electron, iOS and Android: about 300–500 LOC (mostly HTML, CSS and strings) plus assets.
- About **2–3 engineer-weeks plus design time**.
- **No engine dependency, so it can start immediately.**

### 3.2 Navigation, routes and feature flag (S33, S34)

**Route and label recommendation (resolves D3):**

| Route | Sidebar label (lucide icon) | Page h1 (`CoralPageHeader`) | `withPageView` id | Gate |
|---|---|---|---|---|
| `/workflows` | **Workflows** (`Workflow`) | Workflows | `workflows` | `workflows` |
| `/workflows/runs` (tab of `/workflows`, or a separate route) | — | Runs | `workflows.runs` | `workflows` |
| `/workflows/runs/:runId?node=&scope=&agent=&panel=` | — | run name (full-bleed) | `workflows.run` | `workflows` |
| `/workflows/:workflowKey` (editor; `?view=canvas\|yaml\|split`) | — | workflow name (full-bleed) | `workflows.editor` | `workflows` |
| `/profiles` and `/profiles/:profileId` | **Agent Profiles** (`UserRound`) | Agent Profiles | `profiles` / `profiles.detail` | `workflows` (one flag) |

- **Why `/workflows`, not `/schemas`:** the design and deep dive use it (`coral-design.md:356`; deep dive §14.1). UI doc §5.3 says the tab words are provisional. "Schema" collides with the existing `requestedSchema` vocabulary. Keep sidebar label = h1, as UI doc §5.1 requires.
- **Reserved ids:** `runs`, `templates`, `new` cannot be workflow ids (add to validator V13). `workflowKey` must be extensionless (N12).
- **Never** use `:conversationId` in a Coral route (N6).

**Files:**
- `omnigent/server/feature_flags.py`: **Extend** `Feature.WORKFLOWS = "workflows"` plus a `FeatureDefinition` (owner "coral"). Update the exact-dict test `tests/server/test_feature_flags.py` (S33). This belongs to the server engineer but blocks the FE.
- `web/src/lib/capabilities.ts:59-74`: **Extend** with `| "workflows"`.
- `web/src/App.tsx:181-256`: **Extend** with lazy routes:
  ```tsx
  const WorkflowsHomePage = withPageView("workflows", lazy(() => import("@/workflows/pages/WorkflowsHomePage").then(m => ({default: m.WorkflowsHomePage}))));
  // …WorkflowEditorPage ("workflows.editor"), RunViewPage ("workflows.run"), ProfilesPage ("profiles"), ProfileDetailPage
  <Route path={`${prefix}/workflows`} element={<FeatureGatedPage feature="workflows"><WorkflowsHomePage/></FeatureGatedPage>}/>
  <Route path={`${prefix}/workflows/runs`} …/>
  <Route path={`${prefix}/workflows/runs/:runId`} …/>
  <Route path={`${prefix}/workflows/:workflowKey`} …/>
  <Route path={`${prefix}/profiles`} …/>  <Route path={`${prefix}/profiles/:profileId`} …/>
  ```
  To keep App.tsx churn tiny, export a `coralRoutes(prefix)` fragment from **New** `web/src/workflows/routes.tsx` and insert `{coralRoutes(prefix)}` (one line). This works because `<Route>` elements can be returned from a function as a fragment. **UNVERIFIED** with RR 7.18 `<Routes>` children-as-fragment; the fallback is inline routes.
- **New** `web/src/workflows/nav/coralPaths.ts`: `workflowsPath()`, `runPath(runId, {node, scope, agent})`, `editorPath(key)`, `profilesPath(id?)`, `isCoralDeskPath(pathname, rebasePath)` (segment-from-end logic like `Sidebar.tsx:583-592`).
- **New** `web/src/workflows/nav/CoralPrimaryNavigation.tsx`: two `PrimaryNavLink`s (`shell/PrimaryNavLink.tsx`), gated by `isFeatureEnabled(info,"workflows")`. Active state comes from its own `useLocation()`. `componentId` values `sidebar.workflows` and `sidebar.profiles`. It follows the self-contained `ExtensionPrimaryNavigation` pattern (`extensions/ExtensionPrimaryNavigation.tsx:19-54`).
- `web/src/shell/Sidebar.tsx`: **Extend** by inserting `<CoralPrimaryNavigation onNavigate={onNavClick} />` after the Inbox button (near `:1411`). **Modify** `useActiveNavItem` (`:595-603`) to add `&& !isCoralDeskPath(location.pathname, rebasePath)` (N7).
- `web/src/shell/CommandPalette.tsx:185-234`: **Extend** by spreading `...coralPaletteActions(navigate, info)` from **New** `web/src/workflows/nav/coralPaletteActions.ts` ("Go to Workflows", "Go to Runs", "Go to Agent Profiles", keywords "flow, score, pipeline, graph").

**Tests:**
- Extend `App.test.tsx` with a "Workflows release feature route" suite mirroring `:338-363`: not registered when off; spinner while loading; renders when on; embedded basename.
- Unit-test `coralPaths.isCoralDeskPath`.
- `CoralPrimaryNavigation` test modelled on `extensions/ExtensionPrimaryNavigation.test.tsx`.
- A Sidebar test that `/workflows` does not set "New session" active.
- `CommandPalette` action test.

**Risks:**
- Sidebar churn (2 small edits).
- The `useActiveNavItem` bug (N7) if skipped.
- Mobile: on a phone the sidebar is an overlay, and nav rows close it through `onNavClick`; pass it through.

**Size:** about 250 LOC of production code plus about 250 test LOC; 2–4 engineer-days. **Depends on S33 only.**

### 3.3 Workflow editor canvas

**Architecture: three layers, so xyflow is confined to one layer (jsdom OOM, v13 prerelease):**

```
YAML text (canonical, Monaco model)  ─parse(yaml.parseDocument, keep ranges)→  WorkflowDoc view-model (+ ranges)
        ↑ minimal text edits (CST/Document patches)                              │ toGraphModel()
CanvasIntent (move/connect/add/delete/rename/inspector-edit) ← FlowCanvas (xyflow) ← GraphModel + Layout + Overlays
```

**New folders and files:**

`web/src/workflows/model/` (pure, no xyflow and no React; the unit-test target):
- `workflowSchema.ts`: TypeScript types for the authoring file (mirror the engine schema once the build spec fixes it; deep dive §5.2 is illustrative). Node kinds: `start | end | step | decision | gate | group | wait | subworkflow`.
- `yamlDocument.ts`: `parseWorkflow(text) → {doc: yaml.Document, model: WorkflowDoc, errors}` using `parseDocument(text, {keepSourceTokens: true})`; `rangeOf(path)`; `applyPatch(doc, patch) → {text, edits: TextEdit[]}`.
- `patches.ts`: `CanvasIntent → DocPatch` (for example `setIn(["steps", id, "name"], v)`, `addIn(["arrows"], {...})`, `deleteIn`). Id generation: slug of the name plus a de-duplication suffix; V13 uniqueness.
- `graphModel.ts`: `toGraphModel(model) → {nodes, edges, groups}` with edge kinds `handoff | labelled | loop | failure`, plus `fromCompiledGraph(api)` for runs and versions, so the run view never parses YAML.
- `layoutFile.ts`: the layout file type `{version: 1, nodes: Record<NodeId,{x,y,w?,h?}>, groups: Record<GroupId,{x,y,w,h,collapsed?}>, notes: Array<{id,x,y,w,h,text}>, viewport?: never}`. `mergeLayout(graph, layout) → {placed, unplaced}`. Key by **stable node ids** (deep dive §14.4). Prune ids that no longer exist.
- `diagnostics.ts`: `mapDiagnostics(serverDiagnostics, model) → {byNode, byEdge, markers: monaco.IMarkerData[]}` using `yaml_path` → range.
- `derived.ts`: renders the derived join kinds and checked parts **returned by the server validator**. Never re-derive engine semantics in TypeScript; keep one source of truth.

`web/src/workflows/layout/`:
- `autoLayout.ts` (`LayoutEngine` interface: `layout(graph, sizes, fixed) → positions`), `autoLayout.worker.ts` (Web Worker, created like `monacoSetup.ts:12-17`'s `new Worker(new URL(...), {type:"module"})`), `dagreEngine.ts` (default), `elkEngine.ts` (behind a build flag, pending legal).
- Auto-layout runs **only for unplaced nodes**, on `node.measured` sizes (deep dive §14.4).

`web/src/workflows/canvas/` (the **only** importers of `@xyflow/react`):
- `FlowCanvas.tsx`: the adapter. It maps `GraphModel + positions + overlay` to xyflow `nodes`/`edges` (groups use `parentId` + `extent: "parent"`), translates `onNodesChange`/`onConnect`/`onEdgesDelete`/selection into `CanvasIntent`, has snap grid, minimap optional, zoom controls (copy the `CanvasPage.tsx:107-140` pattern) and the `proOptions` decision.
- `xyflowAdapter.ts`: the isolated conversion functions (the v13 migration point).
- `nodes/StartEndNode.tsx` (ink pill), `nodes/StepNode.tsx` (forest; name, roster chips with profile icon, ×N / "up to N", rule badges Enforced/Requested, done-when shield, "changes code" icon, attempts), `nodes/DecisionNode.tsx` (clay; "Orchestrator decides"), `nodes/GateNode.tsx` (mustard; outcome chips), `nodes/GroupNode.tsx` (dashed container; name, rule badges, repeat badge "for each <list>"), `nodes/NoteNode.tsx` (sage; layout-only), `nodes/WaitNode.tsx` and `nodes/SubworkflowNode.tsx` (hidden behind "Advanced").
- `edges/HandoffEdge.tsx` (ink, label chip when labelled, handoff text on hover), `edges/LoopEdge.tsx` (dashed back edge with a "≤ 3 → at limit: Approve merge" badge), `edges/FailureEdge.tsx` (destructive dashed).
- `JoinBadge.tsx`: "waits for all" on derived AND-joins.
- `overlays.ts`: the `CanvasOverlay` type `{nodeStatus?, nodeBadges?, edgeEmphasis?, diagnostics?}`, shared by the editor (diagnostics), Simulate (trace) and the run view (live).

`web/src/workflows/editor/`:
- `WorkflowEditorPage.tsx`: route `/workflows/:workflowKey`. `CoralPageHeader fullBleed` with name, validity pill, Save, Simulate and Run. Split layout: left `NodePalette`, centre `FlowCanvas`, right `Inspector`, toggleable bottom/right `YamlPane`. Desktop only; at `md` and below show read-only plus a "Open on desktop to edit" note.
- `useWorkflowEditor.ts`: a zustand store per open workflow: `{text, baseContentHash, layout, baseLayoutHash, parsed, selection, diagnostics, dirty, undo}`. Text is the source of truth. A canvas edit becomes patch → new text → Monaco `pushEditOperations` (one undo stack in Monaco; the canvas undo button calls `editor.trigger('undo')`).
- `YamlPane.tsx`: `@monaco-editor/react` `Editor` with `ensureMonacoReady()` and `ensureLanguage("yaml")`, `resolvedThemeToMonaco` (`monacoSetup.ts`), markers from diagnostics, and reveal-range on canvas selection.
- `NodePalette.tsx`: drag to add. `ValidationPanel.tsx` lists diagnostics with V-codes; clicking focuses the node or arrow and the YAML range.
- `inspector/WorkflowInspector.tsx` (name, purpose, orchestrator profile, global rules), `StepInspector.tsx` (§5.1 fields: goal, roster, handoff, done when, attempts, failure path, repeat for each, rules, run mode, expected duration, changes code, Coral-run checks), `RosterEditor.tsx` (rows: `ProfilePicker` §3.7, count, exact/up-to, Advanced: persistent session and input scoping, D4), `RulesEditor.tsx` (text, Required/Guidance, **translation status**: unconfirmed, confirmed, stale; "Confirm translation" opens `TranslationConfirmDialog`), `DoneWhenEditor.tsx` (text, proposed evidence requirement in plain words, confirm), `ArrowInspector.tsx` (label, back, limit, at_limit target), `GroupInspector.tsx`, `GateInspector.tsx` (outcomes), `DecisionInspector.tsx` (shows the derived labels from outgoing arrows, watchdog override).
- `SaveConflictDialog.tsx`: when `PUT` returns 412 (the file changed on disk or in git), show the diff and reload or overwrite.

**Two-way sync rules:**
1. YAML text is canonical. Parse on every change (debounce about 150 ms). The canvas shows the last **successful** parse; on a parse error the canvas greys out and shows a banner, while YAML editing continues.
2. Canvas and inspector edits produce **Document AST patches** that preserve comments and the stored confirmed translations (deep dive §14.4). Prefer CST-level scalar edits (`yaml` `CST.setScalarValue`) for renames, and fall back to `Document.setIn` + `toString()` for structural edits. Diff old against new text into minimal Monaco edits so unrelated formatting does not churn. **Risk:** `yaml` warns that "comments may sometimes be associated with a different node". Build golden round-trip fixtures (comments, flow maps, anchors, confirmed-translation blocks).
3. Positions never touch YAML. They go to the layout file.
4. **Validation** is server-side (single engine implementation): `POST /v1/workflows/validate` debounced (about 600 ms) on parse success. Errors are drawn on boxes and arrows and as Monaco markers. Derived info (join kinds, checked parts, loop table) is drawn as badges.

**Proposed endpoints** (server work; the deep dive notes file writes are session-scoped today, `useWriteFileContent.ts:41-60`, and host FS cannot read file contents, `hosts.py:1599-1617`):

```http
GET  /v1/coral/workspaces                              -> {data:[{id, host_id, path, repo:{remote,branch,commit,dirty}}], next_cursor}
POST /v1/coral/workspaces {host_id, path}              -> workspace   (register a repo or folder; discovers .coral/)
GET  /v1/workflows?workspace_id=&after=&limit=         -> {data:[{key, id, name, purpose, path, valid, latest_version_id, updated_at}], next_cursor}
GET  /v1/workflows/{key}/source                         -> {yaml_text, layout:{...}|null, content_hash, layout_hash, path, layout_path, git:{branch, commit, dirty}}
PUT  /v1/workflows/{key}/source  If-Match: <content_hash>
     {yaml_text, layout, layout_hash_base}               -> 200 {content_hash, layout_hash, diagnostics[]} | 412 {current:{yaml_text, content_hash}}
POST /v1/workflows {workspace_id, id, name, template_id?} -> {key, ...}          (create from template)
POST /v1/workflows/validate {workspace_id, yaml_text}   -> {diagnostics:[{code:"V5", severity:"error"|"warning", message,
        node_id?, arrow_id?, yaml_path:(string|number)[]}], derived:{joins:[{node_id, kind:"and"|"merge", arrows:[...] }],
        checked_parts:[{node_id, label_set?:[...], list?:true}], loops:[{back_arrow_id, limit, at_limit}],
        activation_upper_bound, est_sessions}}
POST /v1/workflows/translate {workspace_id, target:{yaml_path}, text, kind:"rule"|"done_when"}
                                                          -> {proposal:{plain_words, translation}, enforceable_by:{profile_ref: bool}}
GET  /v1/workflows/templates                              -> [{id, name, description, yaml_text}]
```

**Layout file location:** `.coral/workflows/<id>.layout.json`, a sibling of `<id>.yaml`. The design says "The canvas layout is a separate file" (`coral-design.md:356`). JSON (not YAML) keeps diffs mechanical; git merge conflicts are possible but easy.

**Auto-layout recommendation:**
- **dagre (`@dagrejs/dagre`, MIT) by default.** Lay out each group's subgraph first, then the outer graph with each group as a sized node (two-pass compound layout).
- **elkjs only after legal sign-off.** It is EPL-2.0 OR GPL-3.0-or-later (deep dive §14.4) and handles compound nodes and orthogonal edge routing natively.
- Both sit behind `LayoutEngine`, so the choice is a one-file swap.

**Tests:**
- vitest units for `yamlDocument` (round-trip goldens, range lookup), `patches` (every intent, including id generation), `graphModel` (D§5.6 example to nodes and edges, loop and failure edges, group parents), `layoutFile.mergeLayout`, `diagnostics.mapDiagnostics`.
- `autoLayout` with a deterministic fixture, using dagre in node.
- Component tests with `@xyflow/react` mocked (pattern `SubagentsGraphView.nodeClick.test.tsx:17-39`): node components render badges per state; Inspector edits dispatch the expected patches; YamlPane with `@monaco-editor/react` mocked (pattern `MonacoCodeEditor.*.test.tsx`).
- `visual-snapshot` stories for every node kind and state (normal, selected, error, warning) and for edge kinds.

**Risks:**
- yaml round-trip fidelity.
- Two editors with one undo stack.
- Large graphs (React Flow handles hundreds of nodes; fine).
- Server dependency on file endpoints and on a host being online (a workflow in a repo on a laptop host is unreadable while the host is offline). Cache the last source in the server, or show read-only from the latest version.
- The derived-join display depends on the validator API.
- Mobile editing is out of scope.

**Size:**
- Model and layout: about 1,800 LOC.
- Canvas (nodes, edges, adapter): about 1,800 LOC.
- Editor, inspector and YAML pane: about 2,500 LOC.
- Total about **6,000 production LOC plus about 4,000 test LOC**, or **9–12 engineer-weeks**.
- Split for parallel work:
  - (a) model and graph renderer (read-only), 3 weeks;
  - (b) YAML pane, diagnostics and save, 2–3 weeks;
  - (c) canvas editing, inspector and patches, 4–5 weeks;
  - (d) layout engine and worker, 1 week.

### 3.4 Simulate UI

**Placement:** the editor's bottom drawer "Simulate". The same overlay renders in a read-only "simulation run" view.

**New:** `web/src/workflows/simulate/`
- `SimulatePanel.tsx`: scenario list (saved tests) and an editor.
- `ScenarioEditor.tsx`: a per-node scripted-input table, generated from the validator's derived info:
  - decisions: an ordered label sequence such as `changes requested, changes requested, approved` (choices from outgoing labels);
  - list-producing steps: list length;
  - steps with done-when: pass/fail per attempt;
  - gates: an outcome sequence;
  - repeat-for-each: per-item overrides (optional).
- `SimulationOverlay.ts`: trace to `CanvasOverlay` (visited nodes with visit counts, taken edges with counts, gates reached, limits hit, never-reached nodes dimmed).
- `SimulationSummary.tsx`: path, loop counts, gates, limits hit, **activation count and estimated sessions (Σ activations × roster size)** (deep dive §15.1; `coral-design.md:304`), with the cost estimate hint.
- `ExhaustiveResults.tsx`: deadlocked joins, dead boxes and unreachable `at_limit` targets as validation findings (V11), with "sampled N of M" when the enumeration is capped.
- `useSimulate.ts`: a TanStack mutation.

**Endpoints (proposed):**

```http
POST /v1/workflows/simulate {workspace_id, yaml_text | version_id, scenario:{inputs:[{node_id, scope?, kind:"label"|"list_len"|"done_when"|"gate", values:[...]}]}, mode:"scripted"|"exhaustive", cap?}
  -> {trace:[{step, node_id, scope_key, event:"activate"|"close"|"arrow"|"gate"|"limit", arrow_id?, label?, outcome?}],
      summary:{path:[node_id], loop_counts:{arrow_id:n}, gates_reached:[node_id], limits_hit:[arrow_id], activations, est_sessions},
      findings:[{code, message, node_id?, arrow_id?}], sampled?:{explored, total}}
GET/PUT /v1/workflows/{key}/tests   -> [{name, scenario, expect:{path?, gates?, limits_hit?}}]    (file: .coral/workflows/<id>.tests.yaml, proposed)
POST /v1/workflows/{key}/tests/run  -> [{name, passed, diff?}]
```

**Data flow:** stateless request and response. Results are cached per (text hash, scenario) in TanStack Query. The overlay is applied through the shared `CanvasOverlay` used by the run view (§3.5), so Simulate exercises the same rendering code.

**Tests:** units for scenario generation from derived info, trace-to-overlay mapping and summary formatting. Component tests with xyflow mocked. Fixtures from the D§5.6 example, including the literal-join deadlock regression (deep dive §15.1), surfaced as a finding.

**Risks:** the scenario UX for repeat-for-each with per-item scripts gets complex, so default to "same script for every item". Server Simulate is phase 1, so the API should exist early. **Recommended as the first engine-backed FE deliverable.**

**Size:** about 1,200–1,600 production LOC plus about 900 test LOC; **2–3 engineer-weeks**. It depends on the read-only renderer (§3.3a) and the Simulate API.

### 3.5 Run list and run view

**Run list** (`/workflows` "Runs" tab, or `/workflows/runs`):
- **New** `runs/RunsListPage.tsx`, `runs/RunRow.tsx` (pattern from `TaskDetailPage.tsx:639-760` `RunRow` / `RunStatusIcon`), `runs/RunStatusPill.tsx` (running; paused with reason chip gate/budget/plan limit/rejected calls/infra/user; completed; failed; cancelled), `runs/StartRunDialog.tsx` (request text, workspace picker reusing `WorkspacePickerDialog` + `useHosts`, version, budget, Simulate estimate, `start_key` = client UUID for idempotent "Run").
- Data: `useWorkflowRuns(filters)`, a TanStack infinite query with `refetchInterval` 15 s (like Tasks).

```http
POST /v1/workflow-runs {workflow_key, version_id?, request_text, workspace_id, budget?:{usd?, tokens?}, start_key}   -> run
GET  /v1/workflow-runs?workflow_key=&status=&after=&limit=  -> {data:[{id, workflow_key, workflow_name, version_id, status, pause_reason?,
        started_by, started_at, finished_at?, current:[{node_id, name, scope_key}], open_gates, est_cost_usd?}], next_cursor}
```

**Run view** (`/workflows/runs/:runId?node=&scope=&agent=&panel=`). New `web/src/workflows/runs/`:

| Component | Responsibility | Reuse |
|---|---|---|
| `RunViewPage.tsx` | Full-bleed `CoralPageHeader`: run name, `RunStatusPill`, `BudgetMeter`, actions Pause/Resume/Cancel, "Talk to orchestrator". Body is a split: `RunGraph` (left) and `RunInspector` (right), with a bottom `RunTimeline` | Copy the `SplitPane` pattern from `CanvasWorkspace.tsx:128-222` |
| `RunGraph.tsx` | `FlowCanvas` read-only with `RunOverlay`: per-node live status (waiting, running, evaluating, closed outcome, taken over, restarting), **loop badges** "pass 2/3", **repeat badges** "3 of 10" on groups, AND-join progress "2/3 arrived", gate open (pulsing mustard), evidence shield (met or missing) | §3.3 canvas layer; status tints copied from `SubagentsGraphView.tsx:25-34` |
| `RosterChips.tsx` | One chip per agent slot: profile name, harness icon, live status dot | `childStatus` + `activityDotClassName` (`shell/subagentStatus.ts:79-142`) for child step sessions; `getSessionState` + `SessionStateBadge` for top-level ones |
| `RunInspector.tsx` | Tabs: **Step** (activation details), **Agent** (embedded session), **Decision**, **Gate**, **Log** (filtered to the selection) | `components/ui/tabs.tsx` |
| `ActivationDetails.tsx` | Attempts list; each attempt's handoffs (per agent and profile, report summary, label or list, artifacts links); `EvidenceList`; Coral-run check results; merge status for parallel code changes (conflicting files, assigned resolver) | — |
| `EvidenceList.tsx` | Each requirement ("test ran after last change to `api/users.ts`") met or missing, with the matched command observation (command, cwd, exit code, timestamp) and a link to the session item | — |
| `DecisionCard.tsx` / `OrchestratorConversation.tsx` | At an orchestrator node: the incoming handoff collection (per agent) → the orchestrator's `choose_arrow` label plus **reason**, rejected calls (audit), watchdog reminders. "Open orchestrator session" switches the Agent tab to the orchestrator. **Refresh markers**: a segment list of orchestrator sessions (F46: stitched transcripts are new UI; v1 shows segments with "refreshed here" dividers rather than a merged transcript) | — |
| `RunAgentPane.tsx` | The selected agent's transcript and composer. **Take over / Hand back** controls: a banner "Coral is paused for this step; you are driving" while `taken_over`. Hand back explains that done-when is re-checked | **`SubagentTabPane`** (`shell/SubagentTab.tsx:40-77`) or `SideChatPane fullSession` directly (`SideChatPane.tsx:166-180`); read-only via `useCanEdit` |
| `GateCard.tsx` | **Phase 2+:** gate = elicitation on the orchestrator session, so render `ApprovalCard` with `onSubmit` → `POST /v1/sessions/{orch}/elicitations/{eid}/resolve` (`lib/sessionsApi.ts:1651-1670`). The same path covers the Inbox and phone. **Phase 1:** `ElicitationSchemaForm` (enum outcomes plus note) → Coral answer API with the visit token | `ApprovalCard`, `ElicitationSchemaForm` |
| `ArrowWhyPopover.tsx` | Clicking an edge shows why it was taken: decision plus reason, auto-advance, loop limit → `at_limit`, gate outcome. Built by filtering run-log entries by `arrow_id` and `scope_key` | — |
| `RunTimeline.tsx` | A virtualized run-log list (step start, handoff, evidence result, decision with reason, user answer, amendment, take-over, refresh, pause/resume), filters by node and kind, and "load older" (`before_seq`) | `@tanstack/react-virtual` |
| `BudgetMeter.tsx` | Run spend as an **estimate** (label "est."), plus plan-window utilization when available (deep dive §12). The pause reason shows a resume time for plan limits | — |
| `UnattendedGateNotice.tsx` | When paused on a gate: "Notifications reach you only while Coral is open" (D1 and finding 9) | — |

**Live data (refines deep dive §14.2):**

1. **Run state** comes from the run-log stream (§3.6), merged into TanStack Query `["workflow-run", runId]`.
2. **Step-session liveness:**
   - **Children topology (recommended default, deep dive §8.2):** mount `useChildSessions(orchestratorSessionId)` once in `RunViewPage`. The child ids join the WS watch-set automatically (`SessionUpdatesProvider.tsx:283-293`), and `changed` frames invalidate the list. **No upstream change.**
   - **Top-level steps (other hosts):** these need S35, a run-scoped query family (e.g. `["workflow-run-sessions", runId]`) unioned **first** in `pushWatched` (`SessionUpdatesProvider.tsx:262-298`). That is a 6-line Extend. Mind the 500-id cap (N10).
   - Map slot → session by `coral_agent_slots.session_id` from the run state, not by parsing labels.
3. **The focused agent transcript** is one per-session SSE through `ensureConversationStreamed` (`SideChatPane.tsx:205`). The run view shows **at most one** embedded transcript at a time. Switching agents releases the previous one, which relies on registry LRU eviction (`conversationRegistry.ts:300-310`).

**Endpoints (proposed):**

```http
GET  /v1/workflow-runs/{id}  -> {run:{id, status, pause_reason?, version:{id, workflow_key, content_hash}, orchestrator_session_ids:[...], budget, started_at, ...},
        graph:<compiled graph JSON>, layout:<layout at version>, activations:[{id, node_id, scope_key, status, attempt, taken_over_by?, started_at, closed_outcome?}],
        slots:[{id, activation_id, roster_index, profile_ref, session_id?, status}], gates:[{id, node_id, scope_key, status, token, elicitation_id?, outcomes:[...], answer?}],
        decisions:[{activation_id, status, label?, reason?}], loops:[{arrow_id, scope_key, count, limit}], last_seq}
GET  /v1/workflow-runs/{id}/log?after_seq=&before_seq=&limit=&node_id=&kind=   -> {data:[LogEntry], next_cursor}
POST /v1/workflow-runs/{id}/pause | /resume | /cancel                          {reason?}
POST /v1/workflow-runs/{id}/activations/{aid}/take-over | /hand-back | /retry
POST /v1/workflow-runs/{id}/gates/{gid}/answer {token, label, note?}            (phase 1; idempotent via token)
POST /v1/workflow-runs/{id}/message-orchestrator {text}                        (or use the orchestrator session's normal /events)
```

Permission: gate answers need edit level and amendments need manage level (deep dive §20.1 Q4). Hide controls when `useCanEdit(orchestratorSessionId)` is false.

**Tests:**
- Pure units: `runOverlay` (state → overlay for every activation state, loops, repeats, joins), `whyArrow` filtering, `RosterChips` status mapping, `RunStatusPill` reasons.
- Component tests with xyflow mocked; `RunAgentPane` with `SideChatPane` mocked; `GateCard` (phase 1 form, phase 2 ApprovalCard with an injected `onSubmit` spy).
- `visual-snapshot` stories for a run mid-flight (fixture graph D§5.6 with loop 2/3, repeat 3/10, open gate).
- Later, a `tests/browser_ui/` mocked-backend contract test for the run view in CI (no local run).

**Risks:**
- The HTTP/1.1 stream budget (N11).
- The AppShell param collision (N6).
- The refreshed-orchestrator transcript (F46).
- Child re-parenting after refresh is UNVERIFIED.
- Mobile: the graph is read-only and the inspector a bottom sheet; gates must stay answerable from the phone through Inbox and ApprovalCard.
- Large runs: repeat-for-each × roster can mean dozens of chips. Collapse groups by default and aggregate counts.

**Size:** run list about 700 LOC; run view about 3,500–4,500 LOC; tests about 3,000 LOC. **6–8 engineer-weeks.** Two engineers can split graph/overlay from inspector/agent pane and gates.

### 3.6 Run stream client (new run-log SSE with cursor resume)

**Server endpoint (proposed; reads the durable `coral_run_log` keyed `(workspace_id, run_id, seq)`, deep dive §7.2):**

```
GET /v1/workflow-runs/{id}/stream?after_seq=<n>      (also honour Last-Event-ID)
event: snapshot   id: 41   data: {"state":{...same as GET /v1/workflow-runs/{id}...}, "log_tail":[...], "last_seq":41}
event: entry      id: 42   data: {"seq":42, "kind":"decision", "node_id":"triage", "scope_key":"pr:17", "activation_id":"…",
                                  "arrow_id":"a4", "body":{"label":"changes requested","reason":"…"}, "refs":{...}, "at":1731300000,
                                  "patch":{"activations":[{…changed rows…}], "gates":[…], "slots":[…], "run":{…}}}
event: heartbeat           data: {}
data: [DONE]               (run reached a terminal status and the tail is drained)
```

- **The server sends row patches with each entry.** The client never re-implements the engine reducer, so there is one source of truth.
- If `after_seq` is older than any retention horizon, or the run version has changed (amendment), the server sends a fresh `snapshot`.
- The heartbeat is every 15 s, matching the session stream (`sse.ts:99-106`).

**New client modules:**
- `web/src/workflows/stream/sseFrames.ts`: a **generic** SSE line parser that handles `event:`, `id:`, `data:` and `[DONE]`. Do not modify `lib/sse.ts`, which is session-vocabulary-bound, ignores `id:` and has 10 commits in 30 days.
- `runStreamFrames.ts`: zod schemas for `snapshot`, `entry` and `heartbeat`, with camelCase mapping. Tolerate unknown `kind`s (forward compatibility).
- `runStreamClient.ts`: `openRunStream(runId, {afterSeq, onFrame, signal})`:
  - `authenticatedFetch` (lint requires it);
  - wraps the body in **`withStallGuard`** (`lib/sse.ts:127`, reused);
  - reconnect loop with `awaitReconnectDelay` (`lib/reconnectBackoff.ts:41`) resuming from `lastSeq`;
  - stop on `[DONE]`;
  - on tab hidden, rely on backoff's hidden mode;
  - **slot discipline (N11):** `await getStreamSlotManager().tryAcquire()` (`store/streamSlots.ts:136`). If null, try `conversationRegistry.evictLruEvictable()` then retry once. Otherwise fall back to **polling** `GET …/log?after_seq=` every 5 s (HTTP/1.1) and mark the UI "Live updates limited". Release the slot on unmount.
- `useWorkflowRunStream(runId)`: owns the client lifecycle. It writes `snapshot` with `queryClient.setQueryData(["workflow-run", runId], …)` and `entry.patch` as a by-id merge into the same cache entry (the SessionUpdatesProvider frames-into-cache pattern). It appends `entry` to a bounded log ring of about 2,000 (`["workflow-run-log", runId]`) and exposes `{connection: "live"|"polling"|"reconnecting"|"ended", lastSeq}`.

**Tests:**
- Parser units: split chunks, CRLF, `id:` handling, `[DONE]`, malformed JSON skipped.
- Client tests with a fake `ReadableStream` and fake timers: resume from `lastSeq` after a drop, stall → reconnect, slot unavailable → polling fallback, abort releases the slot (`setStreamSlotManagerForTest`, `streamSlots.ts:141`).
- Merge reducer: patch idempotence (a duplicate seq is ignored), out-of-order seq is not applied but triggers a snapshot refetch.

**Risks:**
- Proxies buffering SSE (the dev proxy already flushes, `vite.config.ts:89-95`).
- Duplicate entries across reconnects, handled by seq de-duplication.
- Server memory if many viewers live-tail. Back it with a DB tail plus a notify hook, not an in-memory fan-out only.

**Size:** about 500–700 production LOC plus about 600 test LOC; **1–1.5 engineer-weeks**. The server endpoint is a separate (engine) item.

### 3.7 Agent Profiles desk page and profile picker

**Model (from the design, not the UI doc):** a profile is agent YAML plus **description for the canvas**, **default rules** and **expected capabilities** (`coral-design.md:173-175`). Profiles must resolve to pinned revisions for validation (V10). localStorage is therefore out (D3).

**Recommended backing:**
- The agent part reuses Omnigent user agents: `POST /v1/agents` bundle install, `GET /v1/agents?scope=user`, `GET /v1/agents/{id}/config`, `PATCH /v1/agents/{id}` with `If-Match` (`lib/agentsApi.ts:19-100`; `hooks/useCustomAgents.ts:33-70`).
- The Coral part is a sidecar: `coral_profiles` table **or** repo files `.coral/profiles/<name>.yaml`, which travel with workflows in git and match "Sharing: Git repositories and templates now" (`coral-design.md:68`).
- **Open question:** repo-scoped versus user-scoped profiles. The FE codes against an abstraction API either way.

**Endpoints (proposed):**

```http
GET    /v1/coral/profiles?workspace_id=&after=&limit=   -> {data:[{id, ref:"coral/claude-reviewer", name, description, source:"repo"|"user",
          agent:{agent_id?, harness, model, inline_yaml?}, default_rules:[{text, kind:"required"|"guidance", translation_status}],
          expected_capabilities:[cap], capability_check:{cap: "ok"|"unsupported"|"unknown"}, revision, used_by:[workflow_key]}], next_cursor}
GET    /v1/coral/profiles/{id}       PUT/PATCH (If-Match: revision)       DELETE
GET    /v1/coral/capabilities         -> {modes:{"claude-sdk":{caps…}, "claude-native":{…}, …}}   (the deep dive §10.2 matrix, for chips and badges)
```

**New:** `web/src/workflows/profiles/`
- `ProfilesPage.tsx`: `CoralPageHeader list` "Agent Profiles" with a "New profile" action. Cards or rows: name, description, harness icon plus model, capability chips, default-rule badges (Enforced/Requested), "used by N workflows", source badge (repo or user).
- `ProfileDetailPage.tsx`: a two-part editor.
  - (1) The **agent** section reuses `CustomAgentConfigForm` (`pages/settings/CustomAgentConfigForm.tsx:29`) for an existing user agent, or `CreateAgentForm` (`shell/CreateAgentDialog.tsx:234`) for a new one. For repo-inline agents, a YAML pane with the same `YamlPane` component as §3.3.
  - (2) The **Coral** section: description, default rules (`RulesEditor` from §3.3), expected capabilities checklist with a live "this harness mode can or cannot enforce" check against `/v1/coral/capabilities`.
- `ProfilePicker.tsx`: a popover plus cmdk `Command` (`components/ui/command.tsx`) with search, harness icon (reuse the existing icon components such as `ClaudeIcon` / `CodexIcon`), description and capability warnings for the step's required rules. Name chips "Claude", never "Claude Code", for SDK-backed profiles (deep dive §16.1 naming).
- `CapabilityChips.tsx`, `useProfiles.ts` (TanStack infinite query `["coral-profiles", workspaceId]`).

**Modify (optional):** cross-link from Settings → Custom agents to "Use as Coral profile". Not required.

**Tests:** units for the capability check display mapping and picker filtering; component tests for the page and editor with API mocked; a `visual-snapshot` story for a profile card.

**Risks:**
- Unclear ownership between Omnigent agents and Coral profiles. Keep the sidecar thin and never fork the agent editor.
- `custom_agents_settings_ui` and `agent_detail` gating (`SettingsCustomAgentsSection.tsx:43-50`): Coral needs that capability on, so check `info.agent_detail`.

**Size:** about 1,300–1,800 production LOC plus about 1,000 test LOC; **2–3 engineer-weeks**. The picker (about 300 LOC) is needed by the editor (§3.3c).

### 3.8 Inbox workflow kind, notification suppression and a session chip

**Inbox `workflow` kind (S37):**
- **New** `web/src/workflows/inbox/workflowInboxApi.ts` with `listWorkflowAlerts(after)` → `GET /v1/workflow-runs/inbox?after=&limit=` → `{data:[{alert_id, run_id, workflow_name, kind:"paused"|"failed"|"watchdog"|"overdue"|"rejected_calls"|"plan_limit"|"budget"|"gate_open_phase1", node_id?, scope_key?, message, at}], next_cursor}`. Gates in phase 2+ are **not** duplicated here, because they are already approvals through orchestrator elicitations (N18).
- **New** `useWorkflowInbox.ts`, cloned from `useAutomationInbox.ts:10-44`, with `useSeenWorkflowAlerts.ts` (localStorage seen-set like `useSeenAutomationFailures`; or a server ack endpoint for multi-device).
- **New** `WorkflowInboxCard.tsx`: an `InboxCard` with `KindTile` (mustard for paused, red for failed), "Open run" link → `runPath(runId,{node})`, and "Mark as read".
- **Modify** `pages/InboxPage.tsx`: add `| { kind: "workflow"; … }` to the union (`:189-193`), merge into the sorted entries (next to `:352-353`), count and summary (`:335-344`), render branch (`:487`), error, retry and load-more rows (`:938-1004`). About 80 lines. To shrink the diff, move the per-kind render into `WorkflowInboxCard`, exported by Coral.
- **Modify** `hooks/useSidebarData.tsx:239-241`: `const workflowInbox = useWorkflowInbox(identityReady); inboxCount += workflowInbox.items.length`, and expose `workflowInbox` (+4 lines).

**Notification suppression (S36, refined by N9):**
- **Modify** `hooks/useIdleNotifications.ts:329` loop: `if (conversation.labels?.[CORAL_RUN_LABEL]) continue;` for **turn-end only**. Leave the elicitation loop (`:365`) untouched so gates still notify. `CORAL_RUN_LABEL` comes from **New** `web/src/workflows/session/coralLabels.ts` and must match the engine's label key (deep dive §8.2: `coral.run_id`).
- **New** `web/src/workflows/notifications/useWorkflowRunNotifications.ts`: an OS notification on new workflow-inbox alerts (diff by `alert_id`), `navigatePath: /workflows/runs/<id>` (Electron forwards any path, `main.js:4978-4993`).
- Mount it, and any other Coral-global hooks, in **New** `web/src/workflows/CoralRuntimeProvider.tsx`, inserted once in `main.tsx` inside `SessionUpdatesProvider` (3 commits in 30 days). Do **not** mount in AppShell.

**"Part of run" chip:**
- **New** `web/src/workflows/session/CoralRunChip.tsx`: for a session carrying `coral.run_id` / `coral.step_id` labels (from `useSession(conversationId)`), it shows "Run: <name> · <step>" linking to the run view.
- **Modify** `shell/ChatHeader.tsx` with one line next to `CreatedBySession` (`:635-636`). Optional, P2.

**Deep links (S38, later):**
- Electron `deepLink.js` `DEEP_LINK_PATH_RE` (`:22`) accepts `/workflows/runs/<id>`.
- iOS `DeepLink.parse` (`DeepLink.swift:100-133`) adds the same path with the same deny-list discipline.
- Android intent filter (**UNVERIFIED** location).
- Plus the scheme rename (N13).

**Tests:**
- `useWorkflowInbox` (pattern `useAutomationInbox.test` if present).
- InboxPage test with a workflow item: renders, sorts by time, mark-read, counts (extend `pages/InboxPage.test.tsx`).
- `useIdleNotifications` test: a labelled session's turn-end does not notify while its elicitation still does.
- `CoralRunChip` unit test.
- Deep-link parser tests (`web/electron/test/`, iOS `OmnigentTests`).

**Risks:** InboxPage churn (13 commits); the mark-read state is per-device unless the server acks; S36 requires the engine to label the orchestrator session at creation.

**Size:** about 450–650 production LOC plus about 500 test LOC; **1–1.5 engineer-weeks**.

---

## 4. Cross-cutting design

### 4.1 Rules for keeping the fork thin in web

1. **Never edit `AppShell.tsx`.** Every Coral surface is a routed page in `<Outlet/>`, and the run view composes its own split, inspector and agent pane. No `:conversationId` params (N6).
2. **Edits to hot files are delegates of at most a few lines**:
   - Sidebar: brand swap, nav insert, `useActiveNavItem`;
   - NewChatDialog: hero swap;
   - InboxPage: kind;
   - `index.css`: one `@import` of `brand/coral.css` plus the font token;
   - `capabilities.ts`: one union member;
   - App: one `coralRoutes(prefix)` call;
   - CommandPalette: one spread;
   - `useSidebarData`: count;
   - `useIdleNotifications`: one guard;
   - `main.tsx`: one provider;
   - ChatHeader: optional chip.
3. **Copy small patterns instead of generalizing upstream components** (split divider, zoom controls). Reuse upstream components only where they are stable APIs: `SubagentTabPane`, `SideChatPane`, `ApprovalCard`, `ElicitationSchemaForm`, `PrimaryNavLink`, `PageScroll`, `useChildSessions`, `streamSlots`, `withStallGuard`, `reconnectBackoff`, `monacoSetup`.
4. **One xyflow adapter folder** (`web/src/workflows/canvas/`). All logic lives in `model/`, `layout/`, `stream/` and `runs/*Overlay.ts`, unit-tested without xyflow.
5. **Web seam ledger.** Proposed additions to deep dive §4.3, which owns S33-S38:

| Id | Seam | File:line | Size |
|---|---|---|---|
| W1 | Brand defaults | `lib/branding.ts:4-5`; `components/BrandLogo.tsx:89-95` | XS |
| W2 | Sidebar brand row → `CoralWordmark` | `shell/Sidebar.tsx:1266-1277` | XS |
| W3 | Hero → `CoralHero` | `shell/NewChatDialog.tsx:7037-7046` | XS |
| W4 | Default palette tokens (data) | `lib/themePalette.ts:216-295` + regenerated CSS | S |
| W5 | Font and Coral token import | `index.css:5, 44-52` | XS |
| W6 | `useActiveNavItem` Coral exclusion | `shell/Sidebar.tsx:595-603` | XS |
| W7 | Desk headers on Inbox and Tasks | `pages/InboxPage.tsx:872-874`; `pages/TasksPage.tsx:238-258` | XS |
| W8 | `CoralRuntimeProvider` mount | `main.tsx:166-172` | XS |
| W9 | Inbox count includes workflow alerts | `hooks/useSidebarData.tsx:239-241` | XS |
| W10 | Optional run chip | `shell/ChatHeader.tsx:635` | XS |
| W11 | Electron brand constants, updater and scheme | `web/electron/package.json:2-60`; `src/main.js` (literals, `:6031`) | S |
| W12 | Shell display names and icons | iOS pbxproj, Android `strings.xml:3`, `electron/icons/*`, `platform-assets/*` | S (+assets) |

### 4.2 New dependencies (web)

| Package | Why | License | Notes |
|---|---|---|---|
| `yaml` (eemeli) ^2.9 | Document and CST round-trip editing | ISC | 2.9.0 already in the lockfile (cooldown-safe) |
| `@dagrejs/dagre` | Default auto-layout | MIT | Pick a release at least 7 days old |
| `elkjs` (optional) | Compound layout | EPL-2.0 OR GPL-3.0+ | Legal gate; 0.11.1 already transitive |
| `@fontsource-variable/newsreader` | Display font, bundled offline | OFL-1.1 | Also imported by the Electron connect pages |

zod (present) is used for the run-stream frames. No new state library is needed.

### 4.3 State and data-flow summary

- **TanStack Query** for all Coral server data. Keys: `["coral-workspaces"]`, `["workflows", workspaceId]`, `["workflow-source", key]`, `["workflow-validate", key, textHash]`, `["workflow-runs", filters]`, `["workflow-run", runId]` (written by the stream), `["workflow-run-log", runId]`, `["coral-profiles", workspaceId]`, `["workflow-inbox", scope]`.
- **zustand** only for the editor's live document (`useWorkflowEditor`): text, parsed doc, selection, undo bridge.
- **localStorage** (try/catch, per server and viewer like `canvasStorage.ts:31-37`) only for UI preferences: split ratio, YAML pane open, run-view tab, seen alerts.
- **WS session-updates** for step-session liveness, through the child-sessions path (no change) or S35 (top-level).
- **One run-log SSE per open run view**, slot-accounted. **At most one embedded agent transcript SSE** at a time.

### 4.4 Phasing and parallelization (dependency-aware)

| FE work item | Depends on | Can start | Engineers | Size |
|---|---|---|---|---|
| FE-A Brand skin (web) §3.1 | design assets (mark) | now | 1 | 1.5–2 wk |
| FE-B Shell rebrand (Electron/iOS/Android, icons, updater) §3.1 | assets; product/legal on ids and updater | now | 1 | 1–1.5 wk |
| FE-C Routes, nav, flag, palette, `CoralPageHeader` §3.2 | S33 (server flag) | now | 1 | 0.5 wk |
| FE-D Graph model + read-only renderer + layout engine §3.3a,d | engine IR shape (fixtures until the compile API exists) | after FE-C | 1 | 3–4 wk |
| FE-E Simulate UI §3.4 | FE-D; engine phase-1 Simulate and validate API | engine phase 1 | 1 | 2–3 wk |
| FE-F Run list + run view v1 (polling `GET /log`), phase-1 gates via the Coral API §3.5 | FE-D; run and log APIs | engine phase 1 | 1–2 | 4–5 wk |
| FE-G Run stream client §3.6 | stream endpoint | engine phase 1/2 | 1 | 1–1.5 wk |
| FE-H Agent pane, take-over/hand-back, orchestrator conversation, `ApprovalCard` gates §3.5 | engine phase 2 (sessions, elicitation gates S5/S6, take-over commands) | engine phase 2 | 1 | 2–3 wk |
| FE-I Profiles page + picker §3.7 | profiles API; capability matrix (phase 4 for full checks) | engine phase 2 | 1 | 2–3 wk |
| FE-J Inbox kind, S36, notifications, run chip §3.8 | inbox API; labels on orchestrator sessions | engine phase 2 | 1 | 1–1.5 wk |
| FE-K YAML pane, diagnostics and save §3.3b | source read/write and validate endpoints | engine phase 1 + file endpoints | 1 | 2–3 wk |
| FE-L Canvas editing, inspector and AST patches §3.3c | FE-D, FE-K, FE-I (picker); translate endpoint (phase 3/4) | after FE-K | 1–2 | 4–5 wk |
| FE-M Deep links S38 | FE-B scheme decision | later | 1 | 0.5 wk |

Critical path for the canvas (design phase 5): FE-D → FE-K → FE-L. The read-only renderer (FE-D) is useful from phase 1 (Simulate and the run view), so build it first.

### 4.5 Risk register (frontend)

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | Merge conflicts in Sidebar, NewChatDialog, `index.css` and `capabilities.ts` (27–52 commits per 30 days) | High / Medium | Delegate one-liners only (§4.1); `git rerere`; patch-ledger CI (deep dive §17) |
| R2 | The HTTP/1.1 connection budget deadlocks fetches when the run view adds an SSE | Medium / High | Slot-acquire plus polling fallback (§3.6); one embedded transcript at a time |
| R3 | A `:conversationId` route puts AppShell into chat mode (N6) | High if ignored / Medium | Query param `agent=`; route review checklist |
| R4 | `--font-heading` repoint makes every title serif (N1) | High if UI doc followed literally / Low | `--font-display`; `index.css.test.ts` guard |
| R5 | yaml round-trip moves comments or reformats files | Medium / Medium | CST edits, minimal-diff Monaco edits, golden fixtures |
| R6 | xyflow v13 breaking changes | Medium / Medium | Single adapter folder |
| R7 | elkjs licensing | Medium / Medium (business) | dagre default; ELK behind legal |
| R8 | React Flow attribution hidden (`CanvasPage.tsx:85`, `SubagentsGraphView.tsx:250`) | Low / Low (vendor relations) | Decision for counsel or product; show attribution in Coral canvases if undecided |
| R9 | Electron auto-update into Omnigent builds (N13) | High if missed / High | Change `publish.url`, `appId` and scheme before the first Coral desktop build |
| R10 | Unattended gates go unseen (no push) | High / Medium | Notice in the UI; workflow inbox; connector later (deep dive §11 options) |
| R11 | Brand CI baselines fail (e2e branding, visual snapshots) | Certain / Low | Plan the baseline regeneration PR through `ui-snapshot-update.yml` |
| R12 | Editor blocked by missing file read/write endpoints, or host offline | High / High | Engine team prioritizes the source endpoints; the read-only view from the latest version works offline |
| R13 | Watch-set cap of 500 drops run sessions for heavy sidebar users | Low / Medium | Children topology (no union); else run ids first |
| R14 | Mobile usability of the canvas | Medium / Low | Editor desktop-only; run view read-only plus gates through Inbox on mobile |
| R15 | Analytics: every route needs `withPageView`; every link a `componentId` | Low / Low | Checklist; tests |

---

## 5. Test approach summary

- **Unit (vitest, jsdom, colocated):** all pure modules: `model/*`, `layout/*`, `stream/*`, overlay builders, `coralPaths`, inbox mappers, capability display. The bulk of the new test LOC goes here, with no xyflow and no Monaco.
- **Component (vitest + RTL):**
  - `@xyflow/react` mocked (pattern `SubagentsGraphView.nodeClick.test.tsx:17-39`);
  - `@monaco-editor/react` mocked (pattern `MonacoCodeEditor.*.test.tsx`);
  - `SideChatPane` mocked in run-view tests;
  - `ApprovalCard` real, with an `onSubmit` spy.
- **Routing:** extend `App.test.tsx` (feature-gated suites at `:338-363`) and Sidebar active-state tests.
- **CSS contract:** extend `index.css.test.ts` for the Coral tokens and the font guard.
- **Visual:** stories tagged `visual-snapshot` for brand components, every node and edge kind and state, a run mid-flight, and a profile card. Baselines are generated in CI (`ui-snapshot.yml`, `ui-snapshot-update.yml`). **No local browser runs** (CLAUDE.md).
- **Contract (later, CI lane):** `tests/browser_ui/<workflows>/` with a mocked backend for the run-view stream and the editor save/412 flow.
- **Server-side tests the FE depends on:** `tests/server/test_feature_flags.py` (S33); API contract tests for the proposed endpoints (engine team).

---

## 6. Open questions (FE-blocking or FE-shaping)

1. **Workspace and repo registry.** How does the SPA name "the repo whose `.coral/workflows` I am editing"? Proposed: `/v1/coral/workspaces` (host plus path). This affects the URLs (`workflowKey` opaque, or `?workspace=`).
2. **Profiles scope.** Repo files (`.coral/profiles`) versus user agents plus a sidecar table versus both. This decides the Profiles page's source badge and save path.
3. **Session topology.** Children (recommended) versus top-level steps. This decides whether S35 is needed. Are step children re-parented after an orchestrator refresh?
4. **Phase-1 gate surface.** Run view only, or also the workflow inbox kind, before elicitation-backed gates land (N18)?
5. **Layout library and React Flow attribution** (legal).
6. **Default "Powered by Omnigent" credit:** keep, hide or move to About (legal and product).
7. **Distribution identifiers:** bundle ids, app ids, URL scheme (`coral://`), update feed host (N13).
8. **Naming:** "Workflows" and "Agent Profiles" versus the UI doc's provisional "State Schema" (needs product sign-off; recommendation §3.2).
9. **Saved simulations file format and location** (proposed `.coral/workflows/<id>.tests.yaml`).
10. **Multi-device "seen" state for workflow alerts:** localStorage (like automations) or a server ack?
11. **Requirements doc (D2):** `coral-requirements.md` is missing. Several UX defaults (empty states, onboarding to the first workflow, templates gallery) have no source.

---

## 7. Evidence index (opened at HEAD)

- **Web app:**
  - `web/src/App.tsx:16-29, 73-86, 148-153, 181-257`;
  - `web/src/shell/AppShell.tsx:321-333, 668, 2752-2800`;
  - `web/src/shell/Sidebar.tsx:132, 566-614, 1252-1277, 1299-1446`;
  - `web/src/shell/PrimaryNavLink.tsx:1-62`; `web/src/shell/sidebarStyles.ts:2-17`;
  - `web/src/shell/CommandPalette.tsx:185-234`;
  - `web/src/shell/NewChatDialog.tsx:2165, 2242-2243, 7037-7046, 7959-7965`;
  - `web/src/extensions/ExtensionPrimaryNavigation.tsx:19-54`.
- **Flags and branding:**
  - `web/src/lib/capabilities.ts:47-74, 377-405, 461-478`;
  - `omnigent/server/feature_flags.py:23-42, 46-60, 125-135, 181-196`;
  - `web/src/lib/branding.ts:1-41`; `web/src/main.tsx:143-172`;
  - `web/src/components/BrandLogo.tsx:89-198`; `web/src/components/PoweredByOmnigent.tsx`;
  - `deploy/README.md:669-690`.
- **Theme:**
  - `web/src/lib/themePalette.ts:1-50, 62-143, 145-215, 216-295`;
  - `web/scripts/generate-theme-palettes.mjs:1-60`; `justfile:108-109`; `.pre-commit-config.yaml:82-83`;
  - `web/src/index.css:1-6, 44-52, 185-186, 221, 259-343, 1007-1023, 1267-1274, 2329-2343`;
  - `web/src/index.css.test.ts:40-50, 183-280, 827-866, 1091-1101`;
  - `web/src/components/ui/card.tsx:41`; `web/src/components/ui/dialog.tsx:146`.
- **Real-time:**
  - `web/src/lib/sessionUpdatesSocket.ts:1-50`; `web/src/hooks/SessionUpdatesProvider.tsx:258-298`;
  - `web/src/store/conversationRegistry.ts:64-84, 120-140, 300-310`; `web/src/store/streamSlots.ts:1-60, 136-146`;
  - `web/src/lib/sse.ts:95-271`; `web/src/lib/reconnectBackoff.ts:5-41`;
  - `omnigent/server/routes/_sessions/common.py:725, 731`; `omnigent/server/routes/sessions/routes_core.py:2096, 2740-2752`;
  - `omnigent/stores/conversation_store/sqlalchemy_store.py:3707-3711`; `web/vite.config.ts:63-125, 255-292`.
- **Notifications and inbox:**
  - `web/src/hooks/useIdleNotifications.ts:1-30, 72, 122-125, 289-386, 424-441`;
  - `web/src/lib/browserNotifications.ts:1-14`;
  - `web/src/pages/InboxPage.tsx:189-193, 205-260, 425, 487-590, 872-874, 938-1004`;
  - `web/src/hooks/useAutomationInbox.ts:10-44`; `web/src/hooks/useSidebarData.tsx:223-241, 385-396`;
  - `web/src/lib/scheduledTasksApi.ts:1-10, 490-516`;
  - `web/electron/src/main.js:4978-4993`; `web/ios/README.md:15-22`; `web/android/README.md:30-37`.
- **Reuse candidates:**
  - `web/src/components/chat/SideChatPane.tsx:166-260`; `web/src/shell/SubagentTab.tsx:40-77`;
  - `web/src/store/chatStore.ts:4458-4473`;
  - `web/src/shell/SubagentsGraphView.tsx:25-268`; `web/src/shell/subagentGraphLayout.ts:1-50`; `web/src/shell/subagentStatus.ts:14-142`;
  - `web/src/hooks/useChildSessions.ts:28-104`; `web/src/hooks/useSessionState.ts:16-45`; `web/src/components/SessionStateBadge.tsx:14, 103`;
  - `web/src/components/blocks/ApprovalCard.tsx:134-145, 207-330, 1080`; `web/src/components/blocks/ElicitationSchemaForm.tsx:1-60`; `web/src/lib/sessionsApi.ts:1651-1670`;
  - `web/src/shell/monacoSetup.ts:1-152`; `web/src/shell/MonacoCodeEditor.tsx:1-175`;
  - `web/src/pages/CanvasPage.tsx:1-140, 590`; `web/src/canvas/CanvasWorkspace.tsx:23-233`; `web/src/canvas/canvasStorage.ts:1-40`; `web/src/canvas/canvasNavigation.ts`; `web/src/canvas/SessionCard.tsx:1-60`;
  - `web/src/pages/TasksPage.tsx:1-60, 229-275`; `web/src/pages/TaskDetailPage.tsx:1-40, 72-860`;
  - `web/src/components/PageScroll.tsx:1-75`; `web/src/hooks/useActiveConversationId.ts:13-28`;
  - `web/src/lib/agentsApi.ts:1-100`; `web/src/hooks/useCustomAgents.ts:1-70`; `web/src/hooks/useAgents.ts:37-120`;
  - `web/src/pages/settings/SettingsCustomAgentsSection.tsx:1-50`; `web/src/lib/agentBundle.ts:1-45`;
  - `web/src/components/scheduled/CreateScheduledTaskDialog.tsx:55-66`; `web/src/shell/ChatHeader.tsx:151, 635-636`.
- **Shells:**
  - `web/electron/package.json:2-60`; `web/electron/src/main.js:1701-1705, 2445, 2677, 3453-3454, 3655-3706, 5862-5865, 6031-6033`;
  - `web/electron/setup/index.html:6, 425-455, 499-926`; `web/server-selector-v2.html:6`;
  - `web/electron/icons/README.md`; `web/electron/README.md:98-112`;
  - `web/electron/src/deepLink.js:1-45`; `web/ios/Omnigent/DeepLink.swift:95-133`;
  - `web/ios/Omnigent.xcodeproj/project.pbxproj:693-728`; `web/android/app/src/main/res/values/strings.xml:3`; `web/android/app/build.gradle.kts:65`;
  - `web/index.html:1-40`; `web/src/components/onboarding/AnimatedOmnigentPanel.tsx:13`; `web/src/pages/onboarding/AuthCardShell.tsx:8`.
- **Tests and lint:**
  - `web/.oxlintrc.json`; `web/src/test-setup.ts:1-140`;
  - `web/src/App.test.tsx:260-363`; `web/src/shell/SubagentsGraphView.test.tsx:15-35`; `web/src/pages/CanvasPage.test.tsx:42-80`;
  - `tests/e2e_ui/visual/README.md`; `tests/e2e_ui/branding/test_branding.py:11-14, 57-124`;
  - `.github/workflows/ui-snapshot.yml:195`; `tests/README.md:1-40`; `dev/lint/lint_session_list_visibility.py:1-30`.
- **OpenAPI and packages:**
  - `scripts/dump_openapi.py:15-76`; `.github/workflows/sync-openapi-to-site.yml:4-20`; `sdks/README.md`;
  - `web/package.json:33, 51, 67, 76, 82, 88, 107-108`;
  - `pnpm-lock.yaml:4745, 4758, 4965, 5497, 5721, 9502-9510, 11092, 14622-14624, 17114`; `pnpm-workspace.yaml`.
- **Server SPA fallback:** `omnigent/server/app.py:5348-5378`.
- **Missing files (D2, D3):** `coral-requirements.md`; `web/src/components/concerto/`; `CoralLogo.tsx`; `/schemas` and `/profiles` routes.
- **UNVERIFIED items:**
  - whether `create_app(extra_routers)` routes appear in `openapi.json`;
  - Android deep-link intent-filter location;
  - RR 7.18 `<Routes>` accepting a function-returned fragment of `<Route>`s;
  - re-parenting of step children after an orchestrator refresh;
  - Chrome's WebSocket connection accounting against the HTTP/1.1 per-origin pool;
  - whether elkjs ends up in the production web bundle today, since it is transitive only.
