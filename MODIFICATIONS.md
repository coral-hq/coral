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
| `web/public/licenses/geist-mono-OFL-1.1.txt` | S77 | coral-specific | Added. Verbatim SIL OFL 1.1 text of Geist Mono (`@fontsource-variable/geist-mono`), shipped with the web UI. |
