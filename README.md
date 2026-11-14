<!-- CORAL(S91): Coral's README; Omnigent's README is at https://github.com/omnigent-ai/omnigent#readme -->
<div align="center">

# <img src="web/src/brand/assets/coral-mark.svg" alt="" height="38" valign="middle" /> Coral

### Workflows for your coding agents.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange.svg)

</div>

Coral is built on Omnigent (https://github.com/omnigent-ai/omnigent), Copyright (2026) Databricks, Inc., used under the Apache License, Version 2.0. Coral is not affiliated with or endorsed by Databricks, Inc.

---

## What Coral is

Coral turns multi-step agent work into **workflows**. A workflow is a diagram
of steps. Each step has a goal in plain language, a roster of agents and a
handoff. One orchestrator agent conducts the run, and Coral's engine keeps it
on the rails:

- the run follows only arrows that exist;
- each step uses exactly its roster;
- each step hands over what it must;
- "done" is backed by evidence;
- human approvals are never skipped.

Underneath, Coral runs on Omnigent's meta-harness. Omnigent drives Claude Code,
Codex, Cursor, OpenCode and other agents on local or cloud machines, with
tool-call policies, stored conversations and live sessions in the terminal,
browser, desktop app and phone. Coral keeps all of that.

## Status

Coral is at the start of its roadmap. Today this repository is Omnigent with
Coral's brand:

- the web UI and desktop app look and read as Coral;
- the CLI and server messages say Coral;
- `coral` is the command.

The workflow engine is designed but not built yet. See the
[design](docs/coral/roadmap/coral-design.md) and the
[engineering roadmap](docs/coral/roadmap/CORAL_ENGINEERING_ROADMAP.md).

There are no Coral releases yet: no packages, app builds or container images.
Run it from source.

## Run Coral from source

You need Python 3.12 and [uv](https://docs.astral.sh/uv/). The web UI also
needs Node.js 22 or newer with `pnpm`.

```bash
git clone https://github.com/coral-hq/coral.git
cd coral
uv python install
uv venv --python "$(cat .python-version)"
uv sync --extra all --group dev
```

`uv sync` builds the web UI into the package. After pulling web changes,
rebuild it with `OMNIGENT_BUILD_WEB_UI=1 uv sync --extra all --group dev --reinstall-package omnigent`.

Start a local server, then register this machine as a host so the web UI can
start sessions on it:

```bash
uv run coral server                                # terminal 1: http://localhost:6767
uv run coral host --server http://localhost:6767   # terminal 2
```

Open http://localhost:6767. From a terminal, `uv run coral claude` or
`uv run coral codex` starts that agent with Coral, and `uv run coral --help`
lists every command. For the desktop app, run `just electron-dev`.

For development setup, tests and the pull-request checklist, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Telemetry and update checks

Coral inherits Omnigent's anonymous usage telemetry and update check. Both
contact Omnigent's services and are on by default. To turn them off, set:

```bash
export OMNIGENT_DISABLE_TELEMETRY=1   # or DO_NOT_TRACK=1
export OMNIGENT_NO_UPDATE_CHECK=1
```

## What still says Omnigent, and why

Coral keeps Omnigent's code layout so it can keep merging Omnigent's
improvements. These keep their Omnigent names:

- **Code and configuration:**
  - the `omnigent` Python package, its imports and its distribution name;
  - the `omnigent` and `omni` commands, which are the same CLI as `coral`;
  - `OMNIGENT_*` environment variables and the `~/.omnigent` data folder;
  - API paths, HTTP header names and other internal identifiers.
- **Credits:**
  - the "Powered by Omnigent" credit, which appears only with operator branding;
  - the attribution above, in [NOTICE](NOTICE) and in the desktop app's About window.
- **Omnigent itself:**
  - links to Omnigent's documentation at omnigent.ai, which still describes
    the features Coral inherits;
  - the installer scripts in `scripts/`, which install upstream Omnigent, not Coral.

## Staying in sync with Omnigent

Coral keeps Omnigent's full git history. Coral's brand changes to Omnigent's
files are either small, marked edits (`CORAL(<seam id>)` comments, listed in
[MODIFICATIONS.md](MODIFICATIONS.md) and [`.coral/seams.yaml`](.coral/seams.yaml))
or the output of a script, [`.coral/tools/rebrand.py`](.coral/tools/rebrand.py).
Each upstream sync applies the script to Omnigent's new code before merging it,
so those lines merge without conflicts. The procedure is in
[docs/coral/UPSTREAM_SYNC.md](docs/coral/UPSTREAM_SYNC.md).

## Documentation

- [docs/coral/](docs/coral/README.md): Coral's design, roadmap, compliance and
  rebrand records.
- Omnigent's documentation at https://omnigent.ai covers the agents, harnesses,
  policies and deployment that Coral inherits. Where it says `omnigent`, the
  `coral` command works the same way.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) to contribute, and
[SECURITY.md](SECURITY.md) to report a vulnerability privately.

## License and credits

Coral is licensed under the [Apache License, Version 2.0](LICENSE). Omnigent's
NOTICE is kept unchanged in [NOTICE](NOTICE), followed by Coral's addendum, and
[MODIFICATIONS.md](MODIFICATIONS.md) lists every Omnigent file Coral changes.
The bundled fonts Geist Mono and Newsreader are licensed under the SIL Open Font
License 1.1 (see [`web/public/licenses/`](web/public/licenses/)).

Coral is built on Omnigent (https://github.com/omnigent-ai/omnigent), Copyright (2026) Databricks, Inc., used under the Apache License, Version 2.0. Coral is not affiliated with or endorsed by Databricks, Inc.
