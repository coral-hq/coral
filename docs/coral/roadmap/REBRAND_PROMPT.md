# Coral rebrand and attribution: agent prompt

**How to use.**
1. Clone either the empty `https://github.com/coral-hq/coral.git` or `https://github.com/omnigent-ai/omnigent.git`, and put `coral-roadmap-workpapers.zip` at the top of the clone. Step 0 handles both.
2. Start Claude Code in the clone and say:

   > Run `unzip -p coral-roadmap-workpapers.zip coral-roadmap-workpapers/REBRAND_PROMPT.md`, read the output, and carry it out.

   Every setting is filled in in section 0.
3. Before the agent reaches step 8 (publish), create `coral-hq/coral` on GitHub as an **empty** repository: no README, licence or .gitignore, because the clone already has them. Then turn GitHub Actions off for it (Settings → Actions → General → Disable actions). The agent pauses at step 8 if either is missing.
4. If you edit section 0 in this file, rebuild the zip from the folder's parent afterwards with `zip -rX coral-roadmap-workpapers.zip coral-roadmap-workpapers -x '*.DS_Store'`. Don't use Finder's Compress, which adds a `__MACOSX/` folder.

Everything after section 0 is addressed to the agent.

---

## 0. Settings

| Setting | Value | Notes |
|---|---|---|
| `CORAL_COPYRIGHT_HOLDER` | `The Coral Authors` | Coral is open source and has no company behind it. Contributors keep copyright in their own work, and this name credits them collectively, the usual convention for such projects. |
| `CORAL_SUPPORT_EMAIL` | `coralai.team@gmail.com` | Used for package metadata, the Linux maintainer field and support links. |
| `CORAL_GIT_URL` | `https://github.com/coral-hq/coral.git` | Coral's own GitHub repository: a fresh repository, not a GitHub fork. It may not exist yet when you start; you need it only in step 8. |
| `CORAL_HOMEPAGE` | `https://github.com/coral-hq/coral` | |
| `CORAL_PRIVACY_URL` | `https://github.com/coral-hq/coral/blob/main/PRIVACY.md` | The file doesn't exist yet, and a human must write it. Do not write a privacy policy. It is a release blocker for the mobile apps. |
| `DESKTOP_APP_ID` | `io.github.coral-hq.coral` | The reverse-DNS id that macOS and Windows use to tell apps apart, based on the GitHub org because Coral owns no domain. The dev build uses `io.github.coral-hq.coral-dev`. Apple ids allow hyphens but not underscores. Android ids (OQ-31, out of scope) allow underscores but not hyphens, so they will need `io.github.coral_hq.coral`. Never use `ai.omnigent.*`. Settle it before the first public desktop release: changing it later makes the OS treat Coral as a different app, and settings, notification permissions and updates reset. |
| `UPDATE_FEED_URL` | `https://github.com/coral-hq/coral/releases/latest/download/` | Desktop updates come from Coral's GitHub release assets. |
| `BASE_COMMIT` | `2a9cbe2c2` | The commit every roadmap code reference points at. |

Coral's own files, and Coral's changes inside Omnigent files, are licensed under Apache-2.0, the existing `LICENSE`, so Coral is open source on the same terms as Omnigent. If the human asks for any other licence, stop and ask before step 1.

---

## 1. Role, goal and sources of truth

You are a senior staff engineer on Coral, a new open-source project built on a clone of Omnigent. It lives in its own repository, not a GitHub fork. Legally it is still a derivative work of Omnigent, so the Apache License 2.0 obligations below apply in full. Keep the full Omnigent git history in Coral's repository: upstream merges depend on it, and it preserves the authorship of Omnigent's contributors. Never squash it, re-initialise it or rewrite it.

You have four goals:
- put the Coral design and planning artifacts in the repository;
- give Coral its own name and look on every user-visible surface that can change today;
- credit Omnigent correctly under the Apache License 2.0;
- keep upstream merges cheap.

This is a long task, so keep a todo list.

Sources of truth, in this order:
1. This prompt.
2. `docs/coral/roadmap/CORAL_ENGINEERING_ROADMAP.md` (after step 0):
   - F.0: conventions and the standard definition of done;
   - the specs `#### BRD-01 · Coral brand skin` and `#### BRD-03 · Native shell identity`, including their Risks;
   - `#### OPS-01 · Seam ledger and coral-fork-guard`, for the K16 ledger format;
   - the licence part of `#### OPS-02`, and the counsel questions in `#### OPS-05`;
   - J.3.2 rows OQ-30 and OQ-31, and J.6 row PKG-02.
3. In `docs/coral/roadmap/`:
   - `coral_UI_DESIGN_LANGUAGE.md` (UI§2 tokens, §3 type, §4 marks, §7 connect pages, §8.1 firm rules, §11 checklist);
   - `CORAL_WORKFLOW_ENGINE_DEEP_DIVE.md` §16.3;
   - `coral-design.md` §16.
4. The repository's `CLAUDE.md`, in full, except for the one exception in rule L4.

If two sources conflict and this prompt does not settle it, stop and ask. If the code differs from a spec, find the right place by symbol and record the drift in the report.

## 2. Licence and trademark rules (never break these)

- **L1 Licence texts (§4a).** Never modify `LICENSE`, `editors/vscode/LICENSE` or any third-party licence text.
- **L2 NOTICE (§4d).** Keep every existing byte of `NOTICE`. Add the Coral addendum only after the existing content (seam S77).
- **L3 Existing notices (§4c).** Never remove or alter copyright, licence or attribution notices in any file. One example is the dateutil header in `omnigent/server/scheduled/_bounded_rrule.py`.
- **L4 Mark every change (§4b).** Every upstream file you change carries a one-line `CORAL(<seam id>): <what changed>` comment at the change, in that file's comment syntax:
  - `//` or `/* */` in JS, TS, CSS, Swift and Kotlin;
  - `#` in Python, YAML and shell;
  - `<!-- -->` in HTML, SVG, XML, Markdown and plist;
  - `/* */` in `.pbxproj`.

  Rules for the anchors:
  - Only files that cannot hold a comment are `anchor_exempt`: JSON, lockfiles, raster images and other binaries. Generated files are `anchor_exempt` too, and are never edited by hand. One is `web/src/themePalettes.generated.css`: regenerate it with `cd web && node --experimental-strip-types scripts/generate-theme-palettes.mjs` after editing `themePalette.ts`.
  - The seam id is Coral's change marker, which the roadmap's ledger (K16) requires. This is a deliberate exception to CLAUDE.md's rule against ticket ids in comments. Keep the comment to one line that says what changed.
- **L5 No deletions or renames of upstream files.** Add Coral files beside them and repoint references; replaced assets stay in place, unused.
- **L6 Trademarks (§6).** "Omnigent" may appear only in these cases:
  - (a) saying where Coral comes from ("Built on Omnigent");
  - (b) in NOTICE, the attribution text and copyright credits;
  - (c) naming the upstream project, its `omnigent` command, package or documentation as facts;
  - (d) in code identifiers, comments and tests;
  - (e) the unchanged `PoweredByOmnigent` credit (L7).

  Never use "Omnigent" as Coral's name. Never use Omnigent's logos, wordmark, starfish, Otto mascot, app icons or DMG artwork as Coral branding. Never imply that Databricks endorses, maintains, publishes or supports Coral.
- **L7 "Powered by Omnigent".**
  - Leave `web/src/components/PoweredByOmnigent.tsx` and `usePoweredBy()` exactly as they are at `BASE_COMMIT`. The credit shows only with operator branding and renders the Otto mascot.
  - It is the only Omnigent mark Coral shows, and it stays until counsel answers OQ-30. It blocks any external release. Here "release" means building and distributing app builds or packages; publishing the source to Coral's repository in step 8 is fine.
  - If counsel declines logo use, the fallback is a text-only "Built on Omnigent".
- **L8 Publisher identity.**
  - In the Electron package metadata this run changes, Databricks must not appear as Coral's author, maintainer, support contact, homepage, signer or update source. No user-visible copy may say Databricks maintains, publishes or supports Coral.
  - A copyright credit to Databricks is required, not forbidden: in NOTICE, in the attribution text and in `build.copyright`.
  - The Python, SDK, integration and editor metadata still names Omnigent and Databricks. Do not build, tag, attach or publish a wheel, sdist, container image or editor extension from this branch.
- **L9 Dependencies and bundled third-party code.**
  - Follow CLAUDE.md's dependency rules. For npm, use a release older than `minimumReleaseAge` (`pnpm-workspace.yaml`), and never add a temporary index.
  - Every added dependency gets a row in `.coral/licences.yaml`: name, version, SPDX id, class, `counsel_status: pending`. Inherited ones you touch get `inherited: true`.
  - When a licence requires its notice and text to travel with the software, ship the full text, not just a NOTICE line. For SIL OFL-1.1 fonts:
    - this covers Newsreader, which is new, and Geist Mono, which `web/src/index.css` already bundles, including in the Electron `server-selector-v2` bundle;
    - copy each package's licence file verbatim from `web/node_modules/@fontsource-variable/<font>/` to `web/public/licenses/<font>-OFL-1.1.txt` (Vite copies `public/` into the built web UI);
    - add the copyright line to the NOTICE addendum;
    - never subset, rename or modify font files.
  - Stop and ask before adding anything GPL, LGPL, AGPL, EPL, MPL, SSPL, BUSL, non-commercial or of unknown licence.
  - Never vendor, patch or statically bundle the inherited LGPL-3.0 packages `pyte` and `psycopg`.
- **L10 Git.**
  - Never push to the upstream remote. Push only in step 8, to `origin` (Coral's repository), exactly as step 8 describes. Never force-push, mirror or push tags.
  - Commit locally with hooks on; never use `--no-verify` or `SKIP=`.
  - DCO sign-off is only for pull requests to upstream.

These rules are engineering practice, not legal advice. The report ends with the questions for counsel.

## 3. Scope

**In scope:**
1. **Artifacts.**
   - Commit the whole roadmap package under `docs/coral/roadmap/`: the roadmap, the three design documents, the workpapers and this prompt.
   - Write `docs/coral/README.md` as the index.
   - Add an empty skills placeholder, `.claude/skills/coral-workflows/` (step 1).
2. **Compliance scaffolding:**
   - the S77 NOTICE addendum, the `.gitignore` exception for `.coral/`, `.coral/{upstream,seams,licences}.yaml` and `MODIFICATIONS.md`;
   - the OFL licence texts;
   - LICENSE, NOTICE and MODIFICATIONS.md shipped inside the desktop app;
   - the README banner (new seam S91);
   - the large-file hook exemption for the roadmap (new seam S93).
3. **BRD-01 in full,** plus the default branch of S80 (step 3).
4. **BRD-03's identity parts:**
   - S87 Electron identity;
   - the scheme half of S38, including the code that generates links;
   - S88 display names, icons and connect-screen artwork;
   - S89b connect and setup pages.
5. **A sweep of remaining user-visible branding** in:
   - `web/src`, `web/electron`, `web/ios`, `web/android` and `web/*.html`;
   - the HTML the server renders for browsers (new seam S92): `omnigent/server/static/api_only_landing.html`, `_cli_consent_html` in `omnigent/server/routes/auth.py`, and the consent page in `omnigent/server/routes/device_auth.py`.
6. **Support, bug-report, website and privacy links** go to Coral destinations.

**Out of scope.** Leave these unchanged and count them in the report:
- **Internal identifiers.** These would conflict on every upstream merge (DD§16.3, layer 2):
  - the `omnigent` Python package and imports, `OMNIGENT_*`, `~/.omnigent`, and config keys including `branding:`;
  - API paths, database names, storage keys (`omnigent:*`) and IPC channels;
  - iOS and Android project, folder, package and type names, and npm package names;
  - JS identifiers such as `useOmnigentPageView`;
  - the internal URI `omnigent://internal` (`omnigent/runner/identity.py`, `omnigent/server/routes/_origin.py`);
  - the OAuth redirect schemes `ai.omnigent.ios:/oauth/callback` and `ai.omnigent.android`, which the server allowlists in `omnigent/server/routes/auth.py`.
- **The Python distribution, the `omnigent` CLI and its output, and any `coral` command** (FND-01, OPS-03). The one exception is the deep-link scheme change in `omnigent/conversation_browser.py` (step 4). Install commands and `omnigent.ai` documentation links stay until Coral has its own distribution (OPS-09).
- **Server-generated messages** in `omnigent/server/**`, other than the S92 pages, that the web UI displays: error and reason strings, and `FastAPI(title=…)`. Count them with `git grep -n -E '"[^"]*Omnigent' -- omnigent/server`. Where the web keeps its own copy of the same message (the sharing-disabled reason in `AppShell.tsx`, `Sidebar.tsx` and `PermissionsModal.tsx`), change the web copy and note that the server copy still says Omnigent.
- **The rest of BRD-02:** the Workflows entry, the Coral gate and desk headers. They need the Coral backend (FND-02).
- **The S38 run-link paths** (`/workflows/runs/<id>`), which wait for BRD-02.
- **Mobile bundle ids, store listings, signing and push** (OQ-31).
- **Other distributables:** `editors/`, `sdks/`, `integrations/` and `examples/`.
- **Upstream documentation:** `docs/` outside `docs/coral/`, `feature-map/`, and the rest of `README.md`.
- **Telemetry and update checks that contact Omnigent services.** Do not change their behaviour; list each one.

## 4. Steps

### Step 0: set up (no commits)
1. Check the starting state with `git remote -v` and `git status --porcelain`. Two starting points are valid:
   - **(a)** a clone of `omnigent-ai/omnigent`, with `origin` pointing at it;
   - **(b)** a clone of the empty `coral-hq/coral` repository: `origin` is `https://github.com/coral-hq/coral.git`, and `git log` reports no commits.

   In both cases the only untracked entries may be `coral-roadmap-workpapers.zip` and possibly an unzipped `coral-roadmap-workpapers/`. If anything else is present, modified or untracked, stop and ask.
2. Set up the remotes, so that `upstream` is Omnigent (fetch only) and `origin` is Coral:
   - **(a):** `git remote rename origin upstream`, then `git remote add origin https://github.com/coral-hq/coral.git`;
   - **(b):** `git remote add upstream https://github.com/omnigent-ai/omnigent.git`;
   - **both:** `git remote set-url --push upstream DISABLED`.

   Don't fetch from `origin`. Step 8 pushes the `coral` branch there with its history.
3. Create the branch: `git fetch upstream`, then `git switch -c coral <BASE_COMMIT>`. In case (b) this works from the unborn `main`; leave `main` unborn locally. If `BASE_COMMIT` is not `2a9cbe2c2`, locate each roadmap `path:line` by symbol.
4. Unpack the roadmap:
   - run `mkdir -p docs/coral && unzip -q coral-roadmap-workpapers.zip -d docs/coral && mv docs/coral/coral-roadmap-workpapers docs/coral/roadmap`. If the human already unzipped the folder, move it instead;
   - delete any `docs/coral/__MACOSX/` or `.DS_Store` files;
   - add `/coral-roadmap-workpapers.zip` to `.git/info/exclude`. Use a leading `/`: git ignores patterns starting with `./`;
   - confirm that `git status --porcelain` no longer lists the zip.
5. Echo the final settings table (section 0, with the human's values applied).
6. Install exactly what the hooks and checks need:
   - `just hooks`, which runs `uv sync --extra all --group dev` first;
   - `pnpm install --frozen-lockfile --filter web`;
   - `ELECTRON_SKIP_BINARY_DOWNLOAD=1 PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 pnpm install --frozen-lockfile --filter ./editors/vscode --filter ./sdks/web-extension --filter ./examples/extensions/hello-page/web --filter ./web/electron`. These are CI's two installs (`.github/workflows/web-tests.yml`). The second provides `js-yaml` for the Electron tests, and `tsc` for the `vscode-tsc` hook, which runs whenever `pnpm-lock.yaml` is staged.

   Do not run `just ensure`.
7. Read the sources in section 1, and BRD-01 and BRD-03 in full.
8. **Inventory.** Run `git grep -n -i -E 'omnigent|databricks'` over the in-scope areas of section 3, including the S92 server files. Then write `docs/coral/rebrand-inventory.md` with one row per hit: file:line, text, class and reason. The classes:
   - **change**: product-name text shown to users;
   - **change-identity**: lowercase ids that must follow `DESKTOP_APP_ID` or `URL_SCHEME`;
   - **change-asset**: images or drawables that show Omnigent artwork. Find these by opening every file from `git ls-files -- <areas> | grep -iE '\.(png|jpe?g|svg|tiff|icns|ico|car)$|/res/drawable/'`. Look at raster images; read SVG and vector XML as text;
   - **keep-origin**: L6 (a) to (c);
   - **keep-internal**: the identifiers in section 3, plus comments and tests that do not assert visible text;
   - **keep-deferred**: install commands, Omnigent documentation links and `omnigent` CLI references, with the feature that will change each one;
   - **keep-L7**: the Powered-by credit.

### Step 1: artifacts commit
Commit subject: `CORAL: S93: add the Coral roadmap, design documents and skills placeholder`.
- **Stage `docs/coral/roadmap/`.** `CORAL_ENGINEERING_ROADMAP.md` (about 1.2 MB) is over the `check-added-large-files --maxkb=1000` hook. In the same commit, add `exclude: ^docs/coral/roadmap/CORAL_ENGINEERING_ROADMAP\.md$` to that hook in `.pre-commit-config.yaml`, with `# CORAL(S93): the committed Coral roadmap is over 1000 KB` on the line above.
- **Skills placeholder.** Create the empty folder `.claude/skills/coral-workflows/`, holding only `.gitkeep`. `.gitignore` already tracks `.claude/skills/`. Engineers will add Coral skills by hand later.
- **`docs/coral/README.md`**, the index, with these sections:
  - **What Coral is**, with the attribution text (step 2).
  - **Design documents:** links to `roadmap/coral-design.md`, `roadmap/CORAL_WORKFLOW_ENGINE_DEEP_DIVE.md` and `roadmap/coral_UI_DESIGN_LANGUAGE.md`.
  - **Plan:** `roadmap/README.md` (start here) and `roadmap/CORAL_ENGINEERING_ROADMAP.md`.
  - **Compliance:** `/NOTICE`, `/MODIFICATIONS.md` and `/.coral/`.
  - **Rebrand:** `rebrand-inventory.md` and `REBRAND_REPORT.md`.
  - **Skills:** each Coral skill is its own folder directly under `.claude/skills/`, named `coral-<name>`, with a `SKILL.md`. Claude Code does not document loading skills nested inside another folder, so never put skills inside `coral-workflows/`. Replace the placeholder with the first real skill.
  - **Other artifacts:** anything not in the zip, such as the UI prototype the UI document mentions or final logo artwork, goes in `docs/coral/design/` when someone adds it.

  Write the sections whose targets don't exist yet as links; later steps create them.

### Step 2: compliance scaffolding
Commit subject: `CORAL: S77, S91: NOTICE addendum, change ledger and attribution`.
- **Attribution text.** Use it verbatim everywhere attribution appears:
  > Coral is built on Omnigent (https://github.com/omnigent-ai/omnigent), Copyright (2026) Databricks, Inc., used under the Apache License, Version 2.0. Coral is not affiliated with or endorsed by Databricks, Inc.
- **Track `.coral/`.** `.gitignore` ignores every dot-directory (`.*/`). After the existing `!.oss-scanner/` line, add `# CORAL(S77): track Coral's change ledger despite the .*/ rule above.` and `!.coral/`. Afterwards, `git check-ignore -v .coral/seams.yaml` must print nothing.
- **NOTICE addendum (S77).** Append it after the existing text, separated by the file's `________________` line:
  - `Coral`, then `Copyright (2026) The Coral Authors`;
  - one line: "The Coral Authors are the people who have contributed to Coral, as recorded in its git history.";
  - the attribution text;
  - one sentence: Coral's changes to Omnigent files are marked `CORAL(<seam id>)` in each changed file and summarised in `MODIFICATIONS.md`, and Coral's own files and changes are licensed under the Apache License, Version 2.0;
  - then the notices for third-party components Coral adds or newly documents (L9).
- **`.coral/upstream.yaml`** (K16): `repo: omnigent-ai/omnigent`, `merged_sha: <full sha of BASE_COMMIT>`, `source: main`, `merged_at: <commit date>`, `history: []`, `prs: {}`.
- **`.coral/seams.yaml`**, using the OPS-01 field names. OPS-01 later seeds the rest of S1-S90 around these entries, and may reshape `allowed_roots`.
  - `allowed_roots` is a list of `{path, new_files_only}`:
    - `.coral/`, `coral/`, `docs/coral/`, `tests/coral/` and `web/src/brand/`, with `new_files_only: false`;
    - `.claude/skills/`, with `new_files_only: true`.
  - One entry per seam you land, with: `id`, `title`, `owner` (WS-BRAND, or WS-OPS for S77 and S93), `status: landed`, `category: coral-specific`, `files`, `tests`, `budget_lines` (XS 10, S 40, M 120, by the roadmap's size) and `anchor_exempt`. Set `upstream_first: false` and `upstream_candidate: false`.
  - Add `budget_exception {lines, reason, approver: pending}` where a file exceeds its budget.
  - Use a `note` field for partial seams: S80 is the default branch only, and S38 is the scheme half.
  - New files outside `allowed_roots` go in their seam's `files`.
- **`.coral/licences.yaml`**: a header comment and a `dependencies:` list.
- **`MODIFICATIONS.md`**:
  - one paragraph saying it supplements the `CORAL(<seam id>)` notices that Apache-2.0 §4(b) requires in each modified file. For files that cannot carry a comment it is the only record, which is a question for counsel. OPS-01's generator will maintain it later;
  - then a table `File | Seams | Category | Change`.

  Keep it current after every step.
- **`README.md` banner (S91).** At most four lines at the very top, starting with `<!-- CORAL(S91): Coral banner -->`. Content: the attribution text, a pointer to `docs/coral/README.md`, and "The rest of this README describes upstream Omnigent." Change nothing else.

### Step 3: BRD-01 web skin, plus S80's default branch
Follow BRD-01's spec: implementation steps 1-5, one commit each, for example `CORAL: S83: Newsreader and --font-display`. Meet its acceptance criteria and definition of done. In addition:
- **Placeholder mark.** No final mark artwork exists (J.6 PKG-02). Draw a simple, original SVG from UI§4.1: circular leaf or mosaic segments in the Clay colours, on a transparent background. Mark it as a placeholder in a one-line comment. It must not resemble Omnigent's starfish or Otto.
- **S80, default branch only.** `web/src/shell/Sidebar.tsx` shows `omnigent-wordmark.svg` whenever operator `branding.app_name` is unset. Render `<CoralWordmark/>` there instead. Keep `data-testid="sidebar-wordmark"` and the surrounding test ids. The operator branch, the Workflows entry and the desk headers stay in BRD-02.
- **Selection colour.** UI§2.2's `selectionBackground` alpha of 0.12 fails `themePalette.test.ts:261-275` (BRD-01 Risks). Use the lowest alpha of at least 0.14 that passes, keep the test as it is, and flag the value for design.
- **Muted text.** `mutedForeground` `#8A7566` measures 4.11:1 on the cream ground. Keep the UI doc's value, do not weaken any test, and list it for design.
- **Fonts.** L9 applies to `@fontsource-variable/newsreader`, and to Geist Mono's licence text.
- **Palette CSS.** Regenerate it per L4.

### Step 4: BRD-03 identity subset
Commit S87, S38 (scheme half), S88 and S89b separately.
- **`web/electron/src/brand.js`**, tested by `web/electron/test/brand.test.js` (tests live in `test/`, never `src/`). It exports:
  - `PRODUCT_NAME` ("Coral") and `DEV_PRODUCT_NAME` ("Coral Dev");
  - `APP_ID` (`DESKTOP_APP_ID`) and `DEV_APP_ID` (`<DESKTOP_APP_ID>-dev`);
  - `URL_SCHEME` (`coral`);
  - `CLI_NAMES` (the existing names plus `coral`);
  - `INSTALL_COMMAND`, which keeps the current Omnigent command until OPS-09;
  - `UPDATE_FEED_URL`, `SUPPORT_EMAIL`, `HOMEPAGE` and `PRIVACY_URL`.
- **`web/electron/package.json`.** List it as `anchor_exempt`, and keep the npm `name`.
  - `productName` "Coral"; the four `-c.productName` dev overrides in `scripts` become "Coral Dev". `description`: "Coral desktop shell, built on Omnigent".
  - `build.appId` becomes `DESKTOP_APP_ID`, and every `-c.appId=` dev override becomes `<DESKTOP_APP_ID>-dev`.
  - `build.protocols[0]`: `name` "Coral session link", `schemes` `["coral"]`.
  - All four `publish` URLs (`build.publish`, `build.mac.publish`, `build.linux.publish`, `build.win.publish`) become `UPDATE_FEED_URL`.
  - `build.mac.extendInfo.NSMicrophoneUsageDescription`: "Coral uses the microphone for voice dictation in the message composer."
  - `homepage` becomes `CORAL_HOMEPAGE`; `author.name` becomes `CORAL_COPYRIGHT_HOLDER`; `author.email` becomes `CORAL_SUPPORT_EMAIL`; the Linux `maintainer` becomes `<CORAL_COPYRIGHT_HOLDER> <CORAL_SUPPORT_EMAIL>`; `repository.url` becomes `CORAL_GIT_URL` if it is set.
  - `build.copyright`: `Copyright © 2026 <CORAL_COPYRIGHT_HOLDER>. Portions Copyright (2026) Databricks, Inc. (Omnigent, Apache-2.0).`
  - `build.mac.identity` becomes `null` (unsigned builds). Coral's own Developer ID is a release blocker. Do not edit `build:mac:release`.
  - `build.extraResources` gains `legal/LICENSE`, `legal/NOTICE` and `legal/MODIFICATIONS.md` from the repo root (`"from": "../../LICENSE"` and so on), plus each OFL text from `web/public/licenses/` as `legal/<font>-OFL-1.1.txt`. This is how §4(a) and §4(d) are met in every DMG, zip, NSIS, AppImage and deb.
  - `build.dmg.background` becomes a new Coral `web/electron/dmg/coral-background.tiff`. If you cannot make one, set it to `null` and list it as a release blocker.
- **`brand.test.js`** fails on any of these:
  - a value under `author`, `homepage`, `build.appId`, `build.mac.identity`, `build.linux.maintainer` or any `publish` URL that matches `/databricks|omnigent\.ai|ai\.omnigent/i`;
  - `build.extraResources` missing `legal/LICENSE`, `legal/NOTICE` or `legal/MODIFICATIONS.md`;
  - a non-comment line in `web/electron/src/*.js` containing `ai.omnigent.desktop`.
- **Remaining S87 items:**
  - the literals in `main.js`, `desktop_updater.js`, `quitConfirmation.js` and `ssh_connect.js`, all read from `brand.js`;
  - `app.setName`, the dev `userData` path, and `app.setAppUserModelId(isDevBuild ? DEV_APP_ID : APP_ID)` (`main.js`);
  - `DEV_DOMAIN = DEV_APP_ID` (`dev_preferences.js`);
  - in `dev-app-update.yml`, the feed and `updaterCacheDirName: coral-desktop-updater-dev`, and the test that pins it;
  - `about/` and `connection-loading/`.
- **About page.**
  - Show the attribution text inline, plus two buttons, *Licence* and *Notices*.
  - The buttons call a new about-window IPC handler that opens `path.join(process.resourcesPath, 'legal', name)` with `shell.openPath`, using the repo-root files in dev.
  - Plain links won't work: `about_window.js` denies new windows and navigation.
  - Cover the handler in the About window's tests.
- **Scheme (S38, scheme half).** The scheme becomes `coral` everywhere a link is registered, checked or generated. Accepted paths stay unchanged:
  - **registered or checked:** the Electron scheme checks and `deepLink.js`, and iOS `Info-{Debug,Release}.plist` and `DeepLink.swift`;
  - **generated:** `getDeepLink` in `web/src/components/PermissionsModal.tsx` (the share QR code; take the scheme from a small `web/src/brand/` constant), and `deep_link_url` in `omnigent/conversation_browser.py` (CLI `--open-in-desktop`, one `# CORAL(S38)` anchor);
  - update their tests: `PermissionsModal.test.tsx`, the Electron and iOS deep-link tests, `tests/test_conversation_browser.py` and `tests/e2e/omnigent/test_host_no_open.py`.

  Do not touch `omnigent://internal` or the OAuth redirect schemes (section 3).
- **S88:**
  - iOS `APP_DISPLAY_NAME` and the Android `strings.xml` app names;
  - launcher icons, which you replace only if you can generate them from the placeholder mark with tools already installed (`Assets.car` needs Xcode 26);
  - connect-screen artwork: new `CoralLogo` and `CoralLogoReverse` imagesets for `web/ios/Omnigent/ConnectView.swift`, and a new `res/drawable/coral_logo.xml` used by `activity_connect.xml`;
  - a Coral `ic_notification` silhouette for Android.

  Every asset you cannot make is a release blocker.
- **S89b:**
  - `web/electron/setup/` (repoint its `omnigents-logo.svg` image to the Coral mark), `web/server-selector-v2.html` and the onboarding copy BRD-03 names;
  - `web/src/pages/onboarding/LandingFooter.tsx`:
    - the maintained-by line becomes "Built on Omnigent";
    - GitHub points at `CORAL_HOMEPAGE`;
    - remove the iOS App, Android App and Discord buttons until Coral has its own, and list them;
  - in the `ConnectView.swift` info links, Website becomes `CORAL_HOMEPAGE` and Privacy Policy becomes `CORAL_PRIVACY_URL`; Docs stays keep-deferred.

### Step 5: sweep the rest
Change every inventory row in the **change**, **change-identity** and **change-asset** classes:
- React text uses `useAppName()`;
- Electron uses `brand.js`;
- the S92 server pages change `<title>` and "this Omnigent server" to Coral, keep `omnigent login` and upgrade-command text, and update the `tests/server` assertions on what you change;
- everything else uses "Coral".

Attach each file to a seam: S89 for web, S87 for Electron, S88 for mobile, S92 for server pages. Point support, feedback and bug-report links at `<CORAL_HOMEPAGE>/issues`.

Strings that are stored and matched later need a compatibility path, not a plain swap. Before changing any string, grep for code that compares against it:
- **`OMNIGENT_ATTRIBUTION`** (`web/src/components/scheduled/triggerTemplates.ts`) becomes "Sent with Coral". `splitTriggerPrompt` must still accept the legacy suffix built from "Sent with Omnigent". Add a vitest showing that a saved Omnigent-era prompt still splits.
- **`DEFAULT_AUTOMATION_PROJECT`** ("Omnigent Automation") is resolved by name. Classify it keep-deferred and list it.

For every string you change in steps 3-5, run `git grep -n -F '<old string>' -- tests/e2e_ui tests/browser_ui web/electron/e2e` and update each test source that pins it. This includes at least:
- `tests/e2e_ui/branding/test_branding.py`;
- `tests/e2e_ui/visual/test_landing_snapshot.py`;
- `tests/e2e_ui/sessions/test_sidebar_view_options.py`;
- `tests/browser_ui/chat/test_color_theme.py`;
- `tests/e2e_ui/desktop/test_about_dialog.py`;
- `tests/e2e_ui/collaboration/test_sharing_mode_off.py`;
- `tests/e2e_ui/sessions/test_settings_export_import.py`;
- `web/electron/e2e/desktopHarness.js` (the "Coral Dev" profile path).

Do not run these; CLAUDE.md forbids browser runs. CI regenerates snapshots through `.github/workflows/ui-snapshot-update.yml`.

Commit subject: `CORAL: S87, S88, S89, S92: remaining user-visible brand text`.

### Step 6: verify
Run the smallest relevant checks; CLAUDE.md forbids browser runs. Report every result, and say plainly what you could not run.
- **Web:** run `pnpm exec vitest run <files>` inside `web/`, over every test file you changed or added, including `src/lib/themePalette.test.ts`, `src/index.css.test.ts`, `src/brand/coral.css.test.ts`, `src/components/BrandLogo.test.tsx`, `src/shell/NewChatDialog.test.tsx`, `src/server-selector-v2.test.tsx`, `src/components/PermissionsModal.test.tsx` and the trigger-template test. Then run `pnpm --dir web run type-check`, and `node --experimental-strip-types scripts/generate-theme-palettes.mjs --check` inside `web/`.
- **Electron:** `node --test web/electron/test/*.test.js`.
- **Python:** `uv run --no-sync pytest tests/test_conversation_browser.py` and the `tests/server` files you changed.
- **iOS:** if `xcodebuild -version` succeeds, run `xcodebuild test -project web/ios/Omnigent.xcodeproj -scheme Omnigent -configuration Debug -destination 'platform=iOS Simulator,name=<an available iPhone>' -only-testing:OmnigentTests/DeepLinkTests`. Otherwise say that Xcode is missing. Do not use fastlane.
- **Audits.** All of these must pass:
  - `git diff --quiet <BASE_COMMIT> -- LICENSE editors/vscode/LICENSE`;
  - NOTICE starts with the original bytes: `git show <BASE_COMMIT>:NOTICE | cmp - <(head -c "$(git show <BASE_COMMIT>:NOTICE | wc -c)" NOTICE)`;
  - `git ls-files .coral` lists `upstream.yaml`, `seams.yaml` and `licences.yaml`; `git ls-files .claude/skills/coral-workflows` lists `.gitkeep`; `git ls-files docs/coral/roadmap` includes `CORAL_ENGINEERING_ROADMAP.md`;
  - for each file in `git diff --name-only --diff-filter=M <BASE_COMMIT>..HEAD`: it appears in `MODIFICATIONS.md`, and it contains `CORAL(` unless it is in some seam's `anchor_exempt`;
  - `git diff --name-only --diff-filter=DR <BASE_COMMIT>..HEAD` prints nothing (L5);
  - `node --test web/electron/test/brand.test.js` passes; it holds the metadata, `extraResources` and app-id checks;
  - `git grep -nE 'omnigents-logo|omnigents_logo|"OmnigentLogo' -- web/electron/setup web/electron/src 'web/ios/Omnigent/*.swift' web/android/app/src/main/res/layout` prints nothing;
  - no web source imports `omnigent-starfish-icon`, `omnigent-wordmark`, `otto-no-padding`, `OttoEyes` or `OttoIcon`. The exceptions are those components themselves, tests, and `PoweredByOmnigent.tsx` (L7).

### Step 7: report
Write `docs/coral/REBRAND_REPORT.md`, commit it, and print it, then go to step 8. It contains:
1. **Commits:** each commit and what it changed.
2. **Release blockers:**
   - `PRIVACY.md` at `CORAL_PRIVACY_URL`, which a human must write before any mobile release;
   - GitHub Actions on `coral-hq/coral`, which stay off until OPS-02 reviews the inherited workflows;
   - the placeholder mark, plus every icon, DMG background or connect artwork not replaced, including `Assets.car`;
   - code signing: Electron `mac.identity`, and iOS `DEVELOPMENT_TEAM` `8RMX4WU6F8`, which is Databricks' Apple team;
   - the updater cache name inside a packaged build's `app-update.yml`, which comes from the npm `name`;
   - the iOS and Android apps, which bundle no LICENSE or NOTICE and have no licence screen; they must not be distributed until they do;
   - the Python and other package metadata (`pyproject.toml`, `editors/vscode/package.json`), which still identifies Omnigent and Databricks, so the only Coral deliverables today are the source tree and the Electron app;
   - the Powered-by credit with the Otto mascot (OQ-30).
3. **What still says Omnigent and why:** counts per inventory class, each out-of-scope area from section 3 with its count, and the server copies of web messages.
4. **Checks:** those run, with results; those not run, with the reason (CI-only browser lanes, iOS without Xcode, the packaged desktop check in `web/electron/RELEASING.md`).
5. **Design decisions pending:** selection alpha, muted-text contrast, final mark, icons and artwork.
6. **Questions for counsel** (OQ-30, OPS-05):
   - the Powered-by credit and mascot;
   - clearing the "Coral" name;
   - whether in-file `CORAL(...)` anchors plus `MODIFICATIONS.md` satisfy §4(b), including for files that cannot carry comments;
   - the inherited third-party notices in Coral's binaries: Geist Mono (OFL), transitive `elkjs` (EPL-2.0), and MIT/BSD notices for npm code minified into the web and Electron bundles;
   - the Apache-2.0 licence for Coral's additions.
7. **Skills:** where the placeholder is, and the naming rule from `docs/coral/README.md`.
8. **Manual checks for the human:**
   - If `.venv` is missing, run `uv sync --extra all --group dev`; a plain `uv sync` removes the git hooks' tools.
   - Start the server with `uv run --no-sync omnigent server --database-uri "sqlite:///$HOME/.omnigent/chat.db"` and the web dev server with `pnpm --dir web dev`.
   - Confirm the cream background, the Coral mark beside "Direct the run…", the Coral wordmark in the sidebar, the tab title and favicon, dark mode, and no starfish, Otto or pink. The Powered-by credit should still appear only with operator branding.
   - In the Electron dev app, confirm "Coral Dev" in the menu, the About page's attribution text and its Licence and Notices buttons, and that a `coral://` link opens the app.

### Step 8: publish to Coral's repository
Publish only when every step 6 check passes (or the human has accepted each listed failure), and nothing is waiting on a stop-and-ask.
1. **The repository must exist and be empty.** Run `git ls-remote origin`.
   - If it fails ("Repository not found"), stop. Ask the human to create `coral-hq/coral` on GitHub as an empty repository, with no README, licence or .gitignore, then retry.
   - If `git ls-remote --heads origin` lists any branch, stop and ask. Never merge into or force-push over an existing history.
2. **GitHub Actions must be off.** Coral inherits Omnigent's 94 workflows: 12 run on push and 19 on a schedule, including nightly releases and image publishing. They stay off until OPS-02 reviews them.
   - If `gh` is installed and signed in, `gh api repos/coral-hq/coral/actions/permissions --jq .enabled` must print `false`.
   - Otherwise, ask the human to confirm that Settings → Actions → General → "Disable actions" is set.

   Do not change repository settings yourself.
3. **Push only the Coral branch, as `main`:** `git push -u origin coral:main`. No tags, no other branches, no `--force`, no `--mirror`. Omnigent's full history goes with it, as intended. If authentication fails, stop and ask the human to sign in (for example `gh auth login`), then retry.
4. **Confirm the push.** `git ls-remote --heads origin main` must show the same sha as `git rev-parse coral`. Print `https://github.com/coral-hq/coral` and the pushed sha.
5. **Tell the human what comes next:**
   - add branch protection on `main` (OPS-02);
   - write `PRIVACY.md`;
   - keep Actions off until OPS-02 has reviewed and trimmed the inherited workflows;
   - work through the release blockers in `docs/coral/REBRAND_REPORT.md`.
