<!-- CORAL(S77): Coral's summary of its changes to Omnigent files -->
# Coral modifications

This file supplements the `CORAL(<seam id>)` notices that the Apache License,
Version 2.0, section 4(b), requires in each file Coral modifies: every changed
Omnigent file carries a one-line `CORAL(<seam id>)` comment at the change, and
this table lists each such file with its seams and what changed. For files that
cannot carry a comment (JSON, lockfiles, images and other binaries, generated
files) this table is the only record, which is a question for counsel (OPS-05).
The seams are defined in [`.coral/seams.yaml`](.coral/seams.yaml).
OPS-01's generator will maintain this file later.

| File | Seams | Category | Change |
|---|---|---|---|
| `.gitignore` | S77 | coral-specific | Tracks `.coral/` despite the `.*/` rule. |
| `.pre-commit-config.yaml` | S93 | coral-specific | Exempts the committed 1.2 MB Coral roadmap from `check-added-large-files`. |
| `MODIFICATIONS.md` | S77 | coral-specific | Added. This file. |
| `NOTICE` | S77 | coral-specific | Appends the Coral addendum after Omnigent's unchanged NOTICE: Coral's copyright, the attribution to Omnigent, the CORAL anchor rule, and notices for fonts Coral adds or newly documents. |
| `README.md` | S91 | coral-specific | Adds a four-line Coral banner (attribution and a pointer to `docs/coral/README.md`) above the unchanged Omnigent README. |
| `pnpm-lock.yaml` | S83 | coral-specific | Locks `@fontsource-variable/newsreader` 5.3.0 (S83). |
| `tests/browser_ui/chat/test_color_theme.py` | S82 | coral-specific | The default palette is labelled "Coral" with Coral's selection washes (S82). |
| `tests/browser_ui/chat/test_status_indicators.py` | S79 | coral-specific | The working indicator's Coral mark holds still while its opacity pulses, replacing the Otto blink check (S79). |
| `tests/e2e_ui/branding/test_branding.py` | S79, S80 | coral-specific | The default hero heading is "Direct the run…" (S79) and the default sidebar link reads "Coral" (S80). |
| `tests/e2e_ui/sessions/test_sidebar_view_options.py` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `tests/e2e_ui/visual/test_landing_snapshot.py` | S79 | coral-specific | Docstring names the new hero (S79); CI regenerates the baseline. |
| `web/electron/e2e/desktop_connect.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/e2e/desktop_cookie_isolation.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/e2e/desktop_navigation_policy.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/e2e/desktop_oidc_browser_sign_in.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/e2e/desktop_recording_shows_views.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/e2e/desktop_session_expiry_browser_view.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/e2e/desktop_update_window.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/index.html` | S89 | coral-specific | Coral favicon, apple-touch icon, theme colour and tab title, and a cream "Loading Coral…" boot screen (S89). |
| `web/package.json` | S83 | coral-specific | Adds the `@fontsource-variable/newsreader` dependency (S83). |
| `web/public/coral-apple-touch-icon.png` | S89 | coral-specific | Added. Placeholder Coral apple-touch icon: the mark on a cream plate (S89). |
| `web/public/coral-mark.svg` | S89 | coral-specific | Added. Placeholder Coral mark served as the favicon; a byte-identical copy of `web/src/brand/assets/coral-mark.svg` (S89). |
| `web/public/licenses/geist-mono-OFL-1.1.txt` | S77 | coral-specific | Added. Verbatim SIL OFL 1.1 text of Geist Mono (`@fontsource-variable/geist-mono`), shipped with the web UI. |
| `web/public/licenses/newsreader-OFL-1.1.txt` | S77 | coral-specific | Added. Verbatim SIL OFL 1.1 text of Newsreader (`@fontsource-variable/newsreader`), shipped with the web UI. |
| `web/src/components/BrandLogo.test.tsx` | S79 | coral-specific | Fallback cases expect the Coral mark (S79). |
| `web/src/components/BrandLogo.tsx` | S79 | coral-specific | The no-logo and failed-logo fallback is `CoralMark` instead of the Otto mascot (S79). |
| `web/src/components/onboarding/AnimatedOmnigentPanel.tsx` | S89 | coral-specific | Shows the Coral mark; its `alt` and the card's `aria-label` follow `useAppName()` (S89). |
| `web/src/components/onboarding/BlobGraphic.tsx` | S89 | coral-specific | Blob colours become forest, mustard and terracotta (S89). |
| `web/src/components/onboarding/ImportContextModal.tsx` | S89 | coral-specific | Shows the Coral mark instead of the Omnigent starfish (S89). |
| `web/src/index.css` | S83 | coral-specific | Imports Newsreader and `./brand/coral.css`, and adds `--font-display` (S83). |
| `web/src/index.css.test.ts` | S83 | coral-specific | Asserts the Newsreader import and `--font-display`, and that `--font-heading` stays sans (S83). |
| `web/src/lib/branding.ts` | S79 | coral-specific | Built-in defaults become "Coral" and "Direct the run…"; operator branding still overrides them (S79). |
| `web/src/lib/customTheme.test.ts` | S82 | coral-specific | Rebaselines the default palette's selection tint to Coral's washes (S82). |
| `web/src/lib/themePalette.test.ts` | S82 | coral-specific | Replaces the Omnigent pink/magenta pins with Coral rules and adds stored-`omni`, storage-failure and readable-text checks (S82). |
| `web/src/lib/themePalette.ts` | S82 | coral-specific | The default `omni` palette carries Coral's Clay Score tokens and the label "Coral"; its id and `DEFAULT_PALETTE` are unchanged (S82). |
| `web/src/pages/RegisterPage.tsx` | S89 | coral-specific | "this Omnigent server" follows `useAppName()` (S89). |
| `web/src/pages/onboarding/AuthCardShell.tsx` | S89 | coral-specific | Shows the Coral mark with `alt` from `useAppName()` (S89). |
| `web/src/pages/onboarding/JoinTeamStep.tsx` | S89 | coral-specific | "their Omnigent server" follows `useAppName()` (S89). |
| `web/src/shell/NewChatDialog.test.tsx` | S81 | coral-specific | The default-heading case expects Coral's display heading in the hero (S81). |
| `web/src/shell/NewChatDialog.tsx` | S81 | coral-specific | The desktop default hero renders `CoralHero` (mark beside the heading); sibling, project and mobile branches are unchanged (S81). |
| `web/src/shell/Sidebar.subagentHighlight.test.tsx` | S80 | coral-specific | Expects the Coral wordmark in the default sidebar brand (S80). |
| `web/src/shell/Sidebar.tsx` | S80 | coral-specific | With no operator app name, the sidebar brand renders `CoralWordmark` instead of the Omnigent wordmark image; test ids unchanged (S80). |
| `web/src/themePalettes.generated.css` | S82 | coral-specific | Regenerated: the two `omni` blocks carry Coral's tokens; every other palette is byte-identical (S82). |
