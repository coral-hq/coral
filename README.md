<!-- CORAL(S91): Coral's README; Omnigent's README is at https://github.com/omnigent-ai/omnigent#readme -->
<div align="center">

# <img src="web/src/brand/assets/coral-logo.png" alt="" height="38" valign="middle" /> Coral

### Workflows for your coding agents.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange.svg)

Built on [Omnigent](https://github.com/omnigent-ai/omnigent)

</div>

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

Coral runs Claude Code, Codex, Cursor, OpenCode and other agents on your
machine or in the cloud. It has tool-call policies, saved conversations, and
live sessions you can follow from the terminal, browser, desktop app or phone.
That foundation comes from Omnigent, the open-source meta-harness Coral is
built on. Coral adds the workflow layer on top.

## Status

Coral is early. You can run it today and work with agents from every surface.
The workflow engine is designed and is next on the
[roadmap](docs/coral/roadmap/CORAL_ENGINEERING_ROADMAP.md); see the
[design](docs/coral/roadmap/coral-design.md). There are no releases yet, so
run Coral from source.

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

Then start Coral with one command:

```bash
uv run coral start
```

`coral start` runs a local server in the background, registers this machine so
sessions can run on it, and opens the web UI at http://localhost:6767.
`uv run coral stop` turns it off. To chat in the terminal instead, run
`uv run coral run --harness claude` (or `codex`, `cursor`, and so on).
`uv run coral setup` configures your agents and credentials. For the desktop
app, run `just electron-dev`.

`coral` wraps Omnigent's command-line tool, so every `omnigent` command also
runs as `coral`: `coral server`, `coral host`, `coral claude` and the rest work
exactly as Omnigent documents them. `uv run coral --help` lists them all.

## Documentation

- [docs/coral/](docs/coral/README.md): Coral's design, roadmap, and how Coral
  builds on Omnigent and stays current with it.
- [Omnigent's documentation](https://omnigent.ai) covers the agents, harnesses,
  policies and deployment options Coral builds on. Its `omnigent` commands also
  run as `coral`.

## Contributing

- [CONTRIBUTING.md](CONTRIBUTING.md): development setup, tests and pull requests.
- [Discussions](https://github.com/coral-hq/coral/discussions): questions and ideas.
- [SECURITY.md](SECURITY.md): report a vulnerability privately.

## License and credits

Coral is licensed under the [Apache License, Version 2.0](LICENSE).

Coral is built on Omnigent (https://github.com/omnigent-ai/omnigent), Copyright (2026) Databricks, Inc., used under the Apache License, Version 2.0. Coral is not affiliated with or endorsed by Databricks, Inc.

Thank you to Omnigent's authors and contributors, whose work Coral is built on.
Omnigent's NOTICE is kept in [NOTICE](NOTICE), followed by Coral's addendum,
and [MODIFICATIONS.md](MODIFICATIONS.md) lists the Omnigent files Coral
changes. The bundled fonts Geist Mono and Newsreader are licensed under the SIL
Open Font License 1.1 (see [`web/public/licenses/`](web/public/licenses/)).
