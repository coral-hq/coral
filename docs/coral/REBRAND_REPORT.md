# Coral rebrand report

What the rebrand run (`docs/coral/roadmap/REBRAND_PROMPT.md`, steps 0-7) changed
on branch `coral`, what still names Omnigent and why, what was checked, and what
blocks a release. Base commit: Omnigent `2a9cbe2c2`
(`2a9cbe2c205e49f6fe2b676f2a61bdeb25d57896`, 2026-11-08). Ledger:
[`.coral/seams.yaml`](../../.coral/seams.yaml), summary:
[`MODIFICATIONS.md`](../../MODIFICATIONS.md), hit-by-hit inventory:
[`rebrand-inventory.md`](rebrand-inventory.md).

Coral is built on Omnigent (https://github.com/omnigent-ai/omnigent), Copyright (2026) Databricks, Inc., used under the Apache License, Version 2.0. Coral is not affiliated with or endorsed by Databricks, Inc.

## 0. Second pass: Coral branding with the `omnigent` package kept (2026-11-14)

After the run, the owner asked for Coral branding throughout. The `omnigent`
Python package, its imports and its distribution stay, as FND-01 and OPS-03
plan. This pass supersedes these rows of section 3:

- `README.md` below the banner;
- the `omnigent` CLI and its output;
- server-generated messages and `FastAPI(title=…)`;
- the server copy of the sharing-off reason.

| Commit | Subject | What changed |
|---|---|---|
| `0788f36b5` | CORAL: S95: brand transform script and upstream sync procedure | `.coral/tools/rebrand.py`, its 27 tests in `tests/coral/test_rebrand.py`, and `docs/coral/UPSTREAM_SYNC.md`. |
| `93d9e2c88` | CORAL: S95: brand transform of Omnigent 2a9cbe2c2 | Omnigent's base tree after the script: 217 Python files and a regenerated `openapi.json`. Its only parent is the base. It starts the transformed upstream line (`transformed_sha` in `.coral/upstream.yaml`). |
| `39203877c` | CORAL: S95: merge the brand transform of Omnigent 2a9cbe2c2 | Merges that line into `main`. Where a hand seam had changed a file, the merge keeps the seam's text with the transform applied on top. Adds the S95 ledger entry (212 files). |
| `84b6b9d11` | CORAL: S29, S96: coral command, and hints, crash reports and /bug name Coral | The `coral` console script (same CLI). Run as `coral`, the CLI names `coral` in every `cli_invocation()` hint, in its own process and in the daemons it starts. The crash handler and `/bug` file issues on `coral-hq/coral`. |
| `f3fabb9b0` | CORAL: S91, S94: Coral's README and GitHub community files | Coral's own README; `SECURITY.md`, `CONTRIBUTING.md` and the issue templates point to Coral. |
| `b5f877cfb` | CORAL: S93: rebrand report update and inventory | This section and the regenerated inventory: 4 server-page rows now count as changed. |
| `0b8eee004` | CORAL: S93, S94: link Coral's private advisories and Discussions | After the owner turned both on: `SECURITY.md` links Coral's private advisories, and the issue chooser links Discussions. |
| `dd08858f4` | CORAL: S91, S93: README focuses on Coral and credits Omnigent | The README drops its inventory of what still says Omnigent and its sync procedure; this report keeps both. |
| `65c928246` | CORAL: S79, S88, S89, S89b, S91: the Coral logo replaces the placeholder mark | `docs/coral/design/coral.png` and `.coral/tools/brand_assets.py`, which generates every icon and in-app copy from it. |
| `5e58872a6` | CORAL: S95: brand transform of Omnigent 2a9cbe2c2, commands kept | The base snapshot rebuilt with the revised rule; its parent is `93d9e2c88`. |
| `2b0442bf1` | CORAL: S95: keep the original omnigent commands; coral wraps the same CLI | The owner's decision: every `omnigent` command stays as written and `coral` runs the same CLI. Merging the rebuilt snapshot returned the CLI help examples to `omnigent ...`. |
| (this commit) | CORAL: S29, S91, S93, S96: hints keep the omnigent commands | Removes the hint renaming from `84b6b9d11` (crash reports and `/bug` still go to Coral); the README leads with `coral start` and explains that `coral` wraps the CLI. |

**What the transform changes.** In `omnigent/` and `tests/` Python files:

- "Omnigent" in prose string literals becomes "Coral", and "an Omnigent" becomes "a Coral";
- in click command help and `help=` text, the product name changes the same way; the `omnigent <command>` examples stay, because `coral` runs the same CLI.

Each rewritten file gets one `CORAL(S95)` line at the top. The script checks
that only string literals changed before it writes.

**What it keeps** (`rebrand.py report` lists 163 literals with their reasons):

- identifiers, comments and other docstrings;
- single-word values, `X-Omnigent-*` header names, paths and file names;
- upstream facts: omnigent.ai links, install commands, credits, and the upstream installer's text;
- text shared with code outside its scope: the `sdks/ui` config header;
- text the web UI matches exactly: the automation note, the pane-snapshot status, trigger prompts and the default automation project.

**Still says Omnigent after this pass:**

- `coral --version` prints `omnigent 0.22.0.dev0`. OPS-03 owns the Coral version line.
- `coral upgrade` upgrades a wheel install to Omnigent's release on PyPI. Its help says so. OPS-03 blocks it for `coral`.
- The `sandbox` and `upgrade` command summaries. Their help mixes Coral steps with upstream install commands, so the script keeps them whole.
- Every `omnigent` command, by the owner's decision: in help, hints and docs. `coral` wraps the same CLI, so each one also runs as `coral <command>`.
- Internal names, kept so Omnigent's changes keep merging cleanly:
  - the `omnigent` package, its imports and its distribution name;
  - the `omnigent` and `omni` commands, which are the same CLI as `coral`;
  - `OMNIGENT_*` variables and `~/.omnigent`;
  - API paths and header names.
- The "Powered by Omnigent" credit, omnigent.ai documentation links, and the
  installer scripts in `scripts/`, which install upstream Omnigent.
- The other areas in section 3 are unchanged: `editors/`, `sdks/`, `integrations/`, `examples/`, `docs/`, `feature-map/`, mobile ids, and the deferred web rows.

**Checks for this pass:**

| Check | Result |
|---|---|
| Full default pytest lanes (`-n 8 -m "not databricks"`) on the rebranded tree, before the final rule and hint changes | 49,838 passed, 194 failed, 5 errors. Rerun alone, 53 of those failed identically on the base tree: no ripgrep, no PyYAML in the system `python3`, Linux-only `os.waitid`, macOS socket-path limits, tmux sockets. The rest passed alone, except 32 caused by a first hint design (changing the default name), which was replaced. |
| The same 197 tests on the final tree | Identical to the base tree's failures, except one load-flaky zygote test that passes alone (its files are unchanged). |
| The 72 changed test files, `tests/server/test_openapi_drift.py` and `tests/cli/test_cli_invocation.py` on the committed tree | 6,858 passed; 3 failed, all of which fail on the base tree too (`test_claude_native_bridge.py` relay timing). |
| `tests/coral/` (transform tests) | 36 passed at the time; 27 transform tests and 4 asset tests after the commands decision |
| `rebrand.py check` on `main` | clean |
| Ledger check (roots, anchors, budgets, no deletions or renames) | 0 problems, 387 ledgered files |
| Audits: LICENSE files, NOTICE prefix, `PoweredByOmnigent.tsx`, every modified file in `MODIFICATIONS.md` with an anchor | passed |
| Hooks | Passed on every commit. `93d9e2c88` was recorded with `git commit-tree` from a scratch worktree, where every hook passed except pyrefly: it could not resolve `sdks/python-client` imports, because the editable install points at the main checkout. The merge commit then ran every hook, pyrefly included, on the same files in the real checkout, and they passed. |
| Smoke | `coral --help` reads "Coral CLI." with Coral command help. An unreachable server says "run `coral stop`" under `coral` and "run `omnigent stop`" under `omnigent`. The rebuilt web UI's title is Coral. |

Not run: the browser lanes, `tests/e2e`, `tests/integration`, and the Slack
integration tests, which cannot import their optional dependencies here.

**For the owner:**

- The owner turned on private vulnerability reporting and Discussions:
  `SECURITY.md` links Coral's private advisories (the support address stays
  as a fallback), and the issue chooser links Discussions and the docs.
- A local web UI built before this pass still says Omnigent. Rebuild it with
  `OMNIGENT_BUILD_WEB_UI=1 uv sync --extra all --group dev --reinstall-package omnigent`.
  That also installs the `coral` script.

## 1. Commits

| Commit | Subject | What changed |
|---|---|---|
| `bd340797d` | CORAL: S93: add the Coral roadmap, design documents and skills placeholder | The roadmap package under `docs/coral/roadmap/`, the `docs/coral/README.md` index, `.claude/skills/coral-workflows/.gitkeep`, and the `check-added-large-files` exclude for the 1.2 MB roadmap. |
| `39fe15195` | CORAL: S77, S91: NOTICE addendum, change ledger and attribution | NOTICE addendum after the unchanged Omnigent text; `.coral/{upstream,seams,licences}.yaml`; the `.gitignore` exception; `MODIFICATIONS.md`; Geist Mono's OFL text in `web/public/licenses/`; the four-line README banner. |
| `fa276e05b` | CORAL: S83: Newsreader and --font-display | `@fontsource-variable/newsreader` 5.3.0 (OFL-1.1, published 2026-07-19), bundled offline; `--font-display`; its OFL text, NOTICE line and licence row. `--font-heading` unchanged. |
| `059efd7db` | CORAL: S79, S80, S81: Coral mark, wordmark and hero components | `web/src/brand/`: `CoralMark` (placeholder mark, also `assets/coral-mark.svg`), `CoralWordmark`, `CoralHero`, visual-snapshot stories, tests. Nothing upstream imported them yet. |
| `f0a2ed5a1` | CORAL: S82: Coral Clay Score palette and default-palette remaps | The `omni` palette's data becomes Coral (label "Coral"; id and `DEFAULT_PALETTE` unchanged); `coral.css` (ramps, default-palette status/chart/tag/CTA/Share-button remaps, working-mark pulse); regenerated palette CSS (non-`omni` blocks byte-identical); Omnigent-only palette pins replaced by Coral rules. |
| `10b7b3e6a` | CORAL: S79, S81: Coral defaults, mark fallback and desktop hero | Defaults "Coral" and "Direct the run…"; `BrandLogo` falls back to `CoralMark`; the desktop hero renders `CoralHero`; vitest, e2e_ui and Electron e2e heading pins. |
| `4def7949d` | CORAL: S80: Coral wordmark in the sidebar's default branch | Default sidebar brand renders `CoralWordmark` (test ids kept). |
| `8177ae7a8` | CORAL: S79: the working indicator's Coral mark pulses in place | Opacity-only pulse so the working row never shifts; browser-lane indicator test follows. |
| `4f84e642b` | CORAL: S89: Coral art, favicon and boot screen in the web UI | Onboarding, auth cards and import dialog show the Coral mark with `useAppName()` text; Clay blobs; Coral favicon, apple-touch icon, title and cream boot screen. |
| `9468163a4` | CORAL: S87: Coral desktop identity, feed and attribution | `web/electron/src/brand.js` and `test/brand.test.js`; `package.json` identity (Coral names, `io.github.coral-hq.coral`, Coral feed, The Coral Authors, unsigned mac, copyright with the Databricks credit, `legal/` resources); shell copy from `brand.js`; dev "Coral Dev" userData and updater cache; CLI detection accepts `coral`; About page attribution with Licence and Notices buttons (new IPC handler); Coral DMG background; `justfile` and e2e harness follow "Coral Dev". |
| `db201d1b7` | CORAL: S38: coral:// session links on desktop, web and CLI | Electron registers, scans and parses only `coral://`; the share QR and `--open-in-desktop` generate `coral://`. |
| `1a4ea9390` | CORAL: S88: Coral display names, icons and connect artwork | iOS display name, permission prompts, Coral Icon Composer source and logo imagesets; Android strings, adaptive/monochrome launcher, notification silhouette, connect artwork; Electron `coral-icon.{png,icns,ico,svg}`. |
| `276049e74` | CORAL: S89b: Coral connect pages and onboarding copy | Electron setup page per UI§7; "Coral — Connect"; onboarding copy; landing footer (Coral GitHub, store and Discord buttons removed, "Built on Omnigent"). |
| `d29c988f2` | CORAL: S89, S92: remaining user-visible brand text | The remaining web copy via `useAppName()`/`DEFAULT_APP_NAME`; "Sent with Coral" with a legacy-prompt compatibility path; the S92 server pages; `docs/coral/rebrand-inventory.md`. |
| `cfc0aa218` | CORAL: S38: coral:// session links on iOS | iOS `CFBundleURLSchemes`, `DeepLink.parse` and the consent alert; iOS deep-link tests. |
| `17f58af9f` | CORAL: S88, S89b: Coral iOS connect screen | ConnectView shows the Coral mark and copy; Website and Privacy Policy open Coral's pages. |
| `4d0061e9e` | CORAL: S87, S89: Coral app ids in electron-mdm and a clay skill wand | Review fixes: `just electron-mdm` uses the Coral app-id preference domains; the composer skill wand is clay in the default palette; two budget-exception reasons corrected. |
| `2e55d913e` | CORAL: S93: rebrand report and final inventory | This report and the inventory regenerated against the final tree. |

The two iOS commits ran every hook except `web-ios-swift-format` and
`web-ios-swift-lint`, which the maintainer approved skipping: this Mac's
swift-format (Swift 6.1, Command Line Tools and Xcode 16.4) cannot read
`web/ios/.swift-format` and fails on every Swift file, changed or not. The six
Swift files were checked with swift-format 604.0.0 against that config instead
(`lint --strict` clean; `format` leaves them unchanged). Re-run both hooks once
Xcode 26 or later is installed (section 8).

BRD-01 step 4 took two commits: `8177ae7a8` amends the working-mark pulse that
the palette flip (`f0a2ed5a1`) added to `coral.css`, and `10b7b3e6a` adds a test
next to the flip's palette test. Reverting the palette flip therefore also
needs those two, or a revert of the three together; history was not rewritten
(L10).

Drift from the roadmap's `path:line` references, found by symbol: the main.js
literals sit about 10 lines later than BRD-03 cites; BRD-03's ~37 main.js
"Omnigent" literals include comments, CLI names and internal ids, and 21 were
user-visible; `RunnerStep.tsx` (BRD-03 S89b) had no Omnigent copy at the base;
BRD-01's index.css lines held. The iOS AppRootView consent copy is ledgered
under S38, as BRD-03 assigns it.

## 2. Release blockers

Nothing below blocks publishing the source to `coral-hq/coral`; each blocks
building or distributing app builds or packages.

1. **`PRIVACY.md`** at https://github.com/coral-hq/coral/blob/main/PRIVACY.md
   does not exist. A human must write it before any mobile release; the iOS
   connect screen and `brand.js` already link to it.
2. **GitHub Actions on `coral-hq/coral`** stay off until OPS-02 reviews the 94
   inherited workflows (12 run on push, 19 on a schedule, including nightly
   releases and image publishing).
3. **Mark and artwork (PKG-02).** The final Coral logo is
   `docs/coral/design/coral.png` (added 2026-11-14). `.coral/tools/brand_assets.py`
   generates every copy from it: the web mark, favicon, apple-touch icon,
   Electron `coral-icon.*` and Linux icon sizes, the Android launcher,
   monochrome, notification and connect bitmaps, the iOS imagesets and the iOS
   Icon Composer layer. The logo is a raster; a vector (SVG) export would keep
   the smallest sizes sharper. Not replaced at all: `web/electron/icons/Assets.car`,
   the macOS 26 dynamic icon, still holds the Omnigent starfish (rebuilding it
   needs Xcode 26; `afterPack` copies it into every packaged mac build). The
   hand-authored `web/platform-assets/coral/AppIcon.icon` mirrors the upstream
   bundle's schema but has not been compiled (Xcode 26).
4. **Code signing.** Electron `build.mac.identity` is `null` (unsigned builds);
   Coral needs its own Developer ID. iOS `DEVELOPMENT_TEAM` is still
   `8RMX4WU6F8`, Databricks' Apple team; mobile bundle ids stay `ai.omnigent.*`
   (OQ-31).
5. **Updater cache name.** A packaged build's `app-update.yml` gets its
   `updaterCacheDirName` from the npm `name` (`omnigent-desktop-electron`),
   which this run keeps; it would share Omnigent desktop's updater cache.
6. **Mobile licences.** The iOS and Android apps bundle no LICENSE or NOTICE
   and have no licence screen; they must not be distributed until they do.
7. **Package metadata.** `pyproject.toml`, `editors/vscode/package.json` and the
   SDK, integration and example manifests still identify Omnigent and
   Databricks. The only Coral deliverables today are the source tree and the
   Electron app.
8. **Powered-by credit (OQ-30).** `PoweredByOmnigent` still renders the Otto
   mascot when operator branding is set, unchanged until counsel answers.

## 3. What still says Omnigent, and why

Section 0 supersedes some rows below: the README, CLI output and server messages now say Coral.

Inventory classes (`rebrand-inventory.md`, 8,997 rows, 1 pending):

| Class | Rows | Meaning |
|---|---|---|
| change | 395 | Product-name text shown to users (now Coral), plus the tests and copies that pinned it. |
| change-identity | 19 | App ids and the URL scheme, now `io.github.coral-hq.coral` and `coral`. |
| change-asset | 33 | Omnigent artwork with a Coral replacement beside it; one still pending (`Assets.car`). |
| keep-origin | 405 | Origin facts (upstream project, docs, attribution) and the Databricks platform as an integration target. |
| keep-internal | 8027 | Internal identifiers, comments, and tests that do not assert visible text. |
| keep-deferred | 111 | Install commands, omnigent.ai docs links, the `omnigent` CLI, server messages, store metadata and mobile ids, each with the feature that changes it. |
| keep-L7 | 7 | The Powered-by-Omnigent credit. |

Out of scope (section 3 of the prompt), left unchanged:

| Area | Count | Why |
|---|---|---|
| Internal identifiers in the rebranded areas (package, imports, `OMNIGENT_*`, `~/.omnigent`, `branding:` keys, API paths, storage keys `omnigent:*`, IPC channels, mobile project/package/type names, npm names, JS identifiers, `omnigent://internal`, OAuth redirect schemes `ai.omnigent.ios`/`ai.omnigent.android`) | keep-internal rows above | Renaming them would conflict on every upstream merge (DD§16.3 layer 2). |
| `omnigent/` Python package outside the S92 pages, the `omnigent` CLI and its output | 21,673 hits in 872 files | FND-01 and OPS-03; Coral has no distribution or `coral` command yet. Install commands and omnigent.ai docs links stay until OPS-09. |
| Server-generated messages (`git grep -n -E '"[^"]*Omnigent' -- omnigent/server`) | 34 lines | Not S92 pages; includes `FastAPI(title=…)`. |
| Server copies of messages the web rebrands | 4 | The sharing-off reason (`omnigent/server/routes/sessions/routes_permissions.py:126`) still says "this Omnigent server" while the web copies (AppShell, Sidebar, PermissionsModal) say Coral; the tmux hint the server returns still says "the Omnigent app"; the CLI consent page's upgrade notice still says "Update Omnigent to sign in" under a "— Coral" title; automation prompts still open "starts one Omnigent session", which `omnigent/server/scheduled/fire.py` matches. |
| `DEFAULT_AUTOMATION_PROJECT` ("Omnigent Automation") | 1 | Resolved by name on the server; keep-deferred. Saved automations also keep "Sent with Omnigent" until their posting instructions are re-rendered. |
| BRD-02 (Workflows entry, Coral gate, desk headers) and the S38 run-link paths | not started | Need the Coral backend (FND-02). |
| Mobile bundle ids, store listings (`web/ios/fastlane/metadata`), signing, push | see inventory keep-deferred | OQ-31. |
| `editors/` | 115 hits, 16 files | Other distributables. |
| `sdks/` | 274 hits, 32 files | Other distributables. |
| `integrations/` | 1,773 hits, 61 files | Other distributables. |
| `examples/` | 251 hits, 51 files | Other distributables. |
| `docs/` outside `docs/coral/` | 957 hits, 54 files | Upstream documentation. |
| `feature-map/` | 253 hits, 23 files | Upstream documentation. |
| `README.md` below the banner | 138 lines (plus the two banner lines) | Upstream documentation. |

Telemetry and update checks that contact Omnigent services (behaviour unchanged):

- **Server usage telemetry** (`omnigent/telemetry/client.py`, started in
  `omnigent/server/app.py`): fetches its config from
  `https://config.omnigent-telemetry.io/<version>.json` (staging:
  `config-staging.omnigent-telemetry.io`) and sends events to the ingestion URL
  that config names. Off with `OMNIGENT_DISABLE_TELEMETRY`, `OMNIGENT_ANALYTICS=0`,
  `DO_NOT_TRACK=1` or in CI.
- **CLI update reminder** (`omnigent/update_check.py`): for wheel installs it
  looks up the `omnigent` package on the configured index (default pypi.org)
  and points at `omni upgrade`; for git clones it runs `git fetch` on
  `origin`, which in a Coral clone is Coral's repository.
- macOS managed preferences (MDM) now come from the Coral app-id preference domains (`io.github.coral-hq.coral`, dev `io.github.coral-hq.coral-dev`); the
  admin docs in `web/electron/docs/managed-preferences.md` and two code
  comments still name `ai.omnigent.desktop`.
- Not Omnigent services: the Electron updater now reads Coral's GitHub release
  assets; web analytics (`useOmnigentPageView`) go only to a sink an embedding
  host provides; browser tracing is opt-in (`VITE_OTEL_EXPORTER_OTLP_ENDPOINT`).

## 4. Checks

Run (all on this branch unless noted):

| Check | Result |
|---|---|
| `pnpm exec vitest run` (in `web/`) over the 26 test files changed or added, including `src/lib/themePalette.test.ts`, `src/index.css.test.ts`, `src/brand/coral.css.test.ts`, `src/components/BrandLogo.test.tsx`, `src/shell/NewChatDialog.test.tsx`, `src/server-selector-v2.test.tsx`, `src/components/PermissionsModal.test.tsx` and `src/components/scheduled/triggerTemplates.test.ts` (with the new legacy "Sent with Omnigent" split test) | 26 files, 2119 tests passed |
| Full `pnpm exec vitest run` in `web/` (to catch default-name pins) | 16451 passed, 2 failed: `NewChatDialog.projectCreate.test.tsx` ("submits the clicked source…", bundle false/true) asserts a host label; it fails identically at the base commit `2a9cbe2c2`, so it is not from this run |
| After the review fixes (`4d0061e9e`): `src/brand` and `src/components/SlashCommandMenu.test.tsx` | 3 files, 43 passed |
| `pnpm --dir web run type-check` (`tsc -b`) | passed |
| `node --experimental-strip-types scripts/generate-theme-palettes.mjs --check` (in `web/`) | passed; non-`omni` palette blocks are byte-identical to the base |
| `oxlint --deny-warnings` (web) | passed (also run by the commit hooks) |
| `node --test web/electron/test/*.test.js` | 1437 tests: 1436 passed, 0 failed, 1 skipped (pre-existing skip); includes `brand.test.js` (metadata, `extraResources`, app id, protocol checks) and the About window's licence-file handler tests |
| `uv run --no-sync pytest tests/test_conversation_browser.py` | 44 passed |
| `tests/server/test_device_auth.py`, `tests/server/test_oidc_cli_ticket.py`, and the web-UI/landing cases of `tests/server/test_app.py` (no `tests/server` file changed: none pinned the S92 strings) | 117 passed; 3 passed |
| swift-format 604.0.0 `lint --strict` and `format` with `web/ios/.swift-format` on the six changed Swift files | clean, no reformatting |
| Pre-commit hooks on every commit (ruff, pyrefly, prettier, oxlint, `tsc -b`, palette check, custom lint, file hygiene, large files) | passed; the two Swift hooks were skipped on the two iOS commits with approval (section 1) |
| Audit: `git diff --quiet 2a9cbe2c2 -- LICENSE editors/vscode/LICENSE` | passed |
| Audit: NOTICE starts with the base NOTICE's bytes (`cmp`) | passed |
| Audit: `git ls-files` lists `.coral/{upstream,seams,licences}.yaml`, `.claude/skills/coral-workflows/.gitkeep`, `docs/coral/roadmap/CORAL_ENGINEERING_ROADMAP.md` | passed |
| Audit: every file in `git diff --name-only --diff-filter=M 2a9cbe2c2..HEAD` is in `MODIFICATIONS.md` and contains `CORAL(` unless `anchor_exempt` | passed (145 modified files, 78 added) |
| Audit: `git diff --name-only --diff-filter=DR 2a9cbe2c2..HEAD` prints nothing | passed |
| Audit: `node --test web/electron/test/brand.test.js` | passed (9 tests) |
| Audit: `git grep -nE 'omnigents-logo\|omnigents_logo\|"OmnigentLogo' -- web/electron/setup web/electron/src 'web/ios/Omnigent/*.swift' web/android/app/src/main/res/layout` prints nothing | passed |
| Audit: no web source imports `omnigent-starfish-icon`, `omnigent-wordmark`, `otto-no-padding`, `OttoEyes` or `OttoIcon` outside those components, tests and `PoweredByOmnigent.tsx` | passed |
| `PoweredByOmnigent.tsx` and `usePoweredBy()` byte-identical to the base (L7) | passed |

Not run:

- The CI-only browser lanes (`tests/e2e_ui`, `tests/browser_ui`) and the
  Electron e2e suite (`web/electron/e2e`): CLAUDE.md forbids local browser
  runs. Their sources were updated wherever they pinned changed text; CI
  regenerates the landing and story snapshots through
  `.github/workflows/ui-snapshot-update.yml` (Actions are off for now).
- iOS `DeepLinkTests`: `xcodebuild -version` fails with the Command Line Tools
  selected; with Xcode 16.4 (`DEVELOPER_DIR`) the build finds no destination
  because the project targets iOS 26.0 and Xcode 16.4 has only the iOS 18.5
  runtime. Needs Xcode 26. Fastlane was not used.
- Android: no Gradle build or unit tests (no Android toolchain here); ktlint is
  not installed, so its hooks skipped as designed (CI enforces them).
- The packaged desktop check in `web/electron/RELEASING.md` (needs a signed,
  packaged build and the Coral feed).

## 5. Design decisions pending

- **Selection wash.** UI§2.2's `rgba(134, 74, 49, 0.12)` fails the
  highlight-visibility check (deltaE 7.33 < 8 on cream). 0.14 passes the vitest
  check on the page canvas but fails the CI browser check on the `muted`
  surface (deltaE 7.80), so the light palette uses **0.15**, the lowest alpha of
  at least 0.14 that passes both. Dark uses mustard at 0.2 (UI§2.3 gives none).
- **Muted text.** `mutedForeground` `#8A7566` is 4.11:1 on the cream canvas and
  4.36:1 on white cards, below 4.5:1 AA. Kept as UI§2.2 specifies; no test was
  weakened. Needs a design decision (OQ-1).
- **Dark palette values** UI§2.3 does not give (muted text `#bba796`, borders,
  sidebar accent, popover, code background) were chosen to pass the palette
  contrast checks; `brandAccent` stays clay `#864A31` on the dark canvas, which
  is decorative-only contrast.
- **Final mark, favicon, apple-touch icon, app icons, DMG background and
  connect artwork** (PKG-02). The iOS connect screen shows the mark without a
  wordmark; the Electron setup page sets "Coral" in Newsreader's fallbacks
  (Iowan Old Style, Palatino, Georgia) because the page bundles no font.
- The default-palette Share button became glassy clay instead of pink.

## 6. Questions for counsel (OQ-30, OPS-05)

1. **Powered-by credit and mascot.** May Coral keep "Powered by Omnigent" with
   the Otto mascot (shown only with operator branding)? If not, the fallback is
   text-only "Built on Omnigent".
2. **The "Coral" name.** Is it clear to use?
3. **Apache-2.0 §4(b).** Do in-file `CORAL(<seam id>)` anchors plus
   `MODIFICATIONS.md` satisfy "prominent notices stating that You changed the
   files", including for files that cannot carry comments (JSON, lockfiles,
   images, generated CSS), where `MODIFICATIONS.md` is the only record?
4. **Inherited third-party notices in Coral's binaries.** Geist Mono (OFL-1.1,
   now shipped with its text), the transitive `elkjs` (EPL-2.0, via
   `beautiful-mermaid`), and the MIT/BSD notices for npm code minified into the
   web and Electron bundles.
5. **Licence for Coral's additions.** Coral's own files and changes are under
   Apache-2.0 (the existing `LICENSE`); confirm.
6. Is it acceptable to keep Databricks platform feature names (Databricks
   workspace sign-in, Unity Gateway) in Coral's UI, given that no copy names
   Databricks as Coral's publisher?

## 7. Skills

The placeholder is `.claude/skills/coral-workflows/.gitkeep`. Each Coral skill
goes in its own folder directly under `.claude/skills/`, named `coral-<name>`,
with a `SKILL.md`; never nest skills inside `coral-workflows/`. Replace the
placeholder with the first real skill (rule recorded in
[`docs/coral/README.md`](README.md)).

## 8. Manual checks for the human

1. If `.venv` is missing, run `uv sync --extra all --group dev`; a plain
   `uv sync` removes the git hooks' tools.
2. Start the server and web UI:
   `uv run --no-sync omnigent server --database-uri "sqlite:///$HOME/.omnigent/chat.db"`
   and, in another terminal, `pnpm --dir web dev`.
3. Open the web UI and confirm: the cream background; the Coral mark beside
   "Direct the run…"; the Coral wordmark (mark plus serif "Coral") in the
   sidebar; the tab title "Coral" and the mosaic favicon; dark mode (mustard
   primary, warm dark canvas); no starfish, Otto or pink anywhere. Then set an
   operator `branding:` block and confirm the "Powered by Omnigent" credit
   appears only then.
4. In Settings → Appearance, confirm the colour theme lists "Coral" first and
   that GitHub still shows its own green success colour.
5. Run the Electron dev app (`just electron-dev`, or `pnpm --dir web/electron
   start`). Confirm "Coral Dev" in the menu bar, the About window's attribution
   text, and that **Licence** and **Notices** open the repo's `LICENSE` and
   `NOTICE`. Confirm a `coral://localhost:6767/` link opens the app
   (`open 'coral://localhost:6767/'`, or pass it as an argument to the dev app
   on macOS) and that an `omnigent://` link does not.
6. On the Electron setup page (Connect), confirm the cream ground, the mark
   beside "Coral", the five-dot rail and "Run a Coral server on this machine…".
7. After installing Xcode 26 or later, run the two skipped Swift hooks and the
   iOS deep-link tests:
   `uv run --no-sync pre-commit run web-ios-swift-format --files $(git diff --name-only 2a9cbe2c2 -- 'web/ios/*.swift')`,
   the same with `web-ios-swift-lint`, then
   `xcodebuild test -project web/ios/Omnigent.xcodeproj -scheme Omnigent -configuration Debug -destination 'platform=iOS Simulator,name=<an available iPhone>' -only-testing:OmnigentTests/DeepLinkTests`.
   Also build the app once to confirm the Coral `AppIcon.icon` compiles, and
   regenerate `web/electron/icons/Assets.car` from it (`web/electron/icons/README.md`).
