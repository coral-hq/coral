# Coral

Start here for everything Coral-specific in this repository.

## What Coral is

Coral is an open-source workflow product built on a clone of Omnigent. It lives
in its own repository and keeps Omnigent's full git history so upstream merges
stay cheap. It changes Omnigent's own files through small, ledgered seams, plus
one scripted brand transform that each upstream sync re-applies.

Coral is built on Omnigent (https://github.com/omnigent-ai/omnigent), Copyright (2026) Databricks, Inc., used under the Apache License, Version 2.0. Coral is not affiliated with or endorsed by Databricks, Inc.

## Design documents

- [Coral design](roadmap/coral-design.md)
- [Workflow engine deep dive](roadmap/CORAL_WORKFLOW_ENGINE_DEEP_DIVE.md)
- [UI design language](roadmap/coral_UI_DESIGN_LANGUAGE.md)

## Plan

- [Roadmap package README](roadmap/README.md): start here.
- [Engineering roadmap](roadmap/CORAL_ENGINEERING_ROADMAP.md): the authoritative
  plan (sections A-K). Every `path:line` reference points at Omnigent commit
  `2a9cbe2c2`.

## Compliance

- [`/NOTICE`](../../NOTICE): Omnigent's NOTICE, kept byte for byte, followed by
  the Coral addendum (seam S77).
- [`/MODIFICATIONS.md`](../../MODIFICATIONS.md): every Omnigent file Coral
  changes, with its seam ids. Each changed file also carries a
  `CORAL(<seam id>)` comment at the change.
- [`/.coral/`](../../.coral/): the change ledger: `upstream.yaml` (the Omnigent
  commit Coral is based on), `seams.yaml` (seams, their files and budgets) and
  `licences.yaml` (dependencies Coral adds or documents).

## Rebrand

- [Rebrand inventory](rebrand-inventory.md): every `omnigent`/`databricks` hit
  in the rebranded areas, with its class and reason.
- [Rebrand report](REBRAND_REPORT.md): commits, release blockers, checks, design
  decisions pending and questions for counsel.
- [`.coral/tools/rebrand.py`](../../.coral/tools/rebrand.py): the brand
  transform (seam S95). It rewrites "Omnigent" to "Coral" in user-visible
  Python strings and CLI help, and lists what it keeps with `report`.

## Upstream sync

- [Syncing with Omnigent](UPSTREAM_SYNC.md): how Coral merges new Omnigent
  commits, applying the brand transform to each snapshot first.

## Skills

Each Coral skill for Claude Code is its own folder directly under
`.claude/skills/`, named `coral-<name>`, with a `SKILL.md`. Claude Code does not
document loading skills nested inside another folder, so never put skills inside
`.claude/skills/coral-workflows/`. That folder is an empty placeholder: replace
it with the first real skill.

## Other artifacts

Anything that is not in the roadmap package goes in `docs/coral/design/`.
[`design/coral.png`](design/coral.png) is the Coral logo: run
`.venv/bin/python -I .coral/tools/brand_assets.py generate` after changing it,
and every icon and in-app copy is regenerated from it.
