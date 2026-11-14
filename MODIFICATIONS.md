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
| `web/package.json` | S83 | coral-specific | Adds the `@fontsource-variable/newsreader` dependency (S83). |
| `web/public/licenses/geist-mono-OFL-1.1.txt` | S77 | coral-specific | Added. Verbatim SIL OFL 1.1 text of Geist Mono (`@fontsource-variable/geist-mono`), shipped with the web UI. |
| `web/public/licenses/newsreader-OFL-1.1.txt` | S77 | coral-specific | Added. Verbatim SIL OFL 1.1 text of Newsreader (`@fontsource-variable/newsreader`), shipped with the web UI. |
| `web/src/index.css` | S83 | coral-specific | Imports Newsreader and `./brand/coral.css`, and adds `--font-display` (S83). |
| `web/src/index.css.test.ts` | S83 | coral-specific | Asserts the Newsreader import and `--font-display`, and that `--font-heading` stays sans (S83). |
| `web/src/lib/customTheme.test.ts` | S82 | coral-specific | Rebaselines the default palette's selection tint to Coral's washes (S82). |
| `web/src/lib/themePalette.test.ts` | S82 | coral-specific | Replaces the Omnigent pink/magenta pins with Coral rules and adds stored-`omni` and readable-text checks (S82). |
| `web/src/lib/themePalette.ts` | S82 | coral-specific | The default `omni` palette carries Coral's Clay Score tokens and the label "Coral"; its id and `DEFAULT_PALETTE` are unchanged (S82). |
| `web/src/themePalettes.generated.css` | S82 | coral-specific | Regenerated: the two `omni` blocks carry Coral's tokens; every other palette is byte-identical (S82). |
