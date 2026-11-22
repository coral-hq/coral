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

Run Coral steps only on content you trust. On macOS a step's shell can read
and write your clipboard (CRL-171). It can still connect to other programs'
local sockets, such as Docker Desktop's, a tmux server started with
`tmux -S <path>`, or a Claude Code session's message inbox, which, from the
CLI binary, lets it send your own Claude Code a message (CRL-174). Since
CRL-165 it can no longer read other processes' environments or command lines.
Since CRL-166 it can no longer connect to the harness sockets of other Omnigent
sessions under this host's socket root or the default `/tmp/omnigent-<uid>`, to
other Omnigent terminals' tmux servers, or to your own tmux server's default
socket (`tmux-<uid>`, with `-L` labels and `TMUX_TMPDIR`). Both were measured
on macOS 27.2.1 only, and no CI lane runs macOS (CRL-170). Your model API key
is still in those environments and command lines, where processes outside the
sandbox can read it (CRL-167). From the code, not measured: on either platform
a step with network on can still reach Omnigent's loopback TCP listeners
(CRL-177), on macOS also the codex-native harness's socket (CRL-177), and on
Linux other programs' abstract sockets (CRL-174). On a single-user server, on
any platform, a step can act as you, the owner, so neither a human gate nor
the sandbox is a security control there (CRL-159).

Since CRL-176 a Coral step's Claude CLI keeps its Claude Code state in a
private directory, a fresh one for each launch in the sandbox. While the CLI
runs in the sandbox, neither the CLI nor anything it starts can read or write
your real `~/.claude` or `~/.claude.json`, such as the plugins and hooks your
own Claude Code runs. That was measured on macOS 27.2.1, and a bwrap test
checks it on Linux in CI. It covers Coral steps only: other Omnigent agents
that run claude-sdk in a sandbox still share your `~/.claude` (CRL-178). On
macOS Coral's orchestrator and anchor run their CLIs outside the sandbox, as
does every Coral CLI when the operator sets `OMNIGENT_CLAUDE_SDK_NO_SANDBOX`.
On Linux the orchestrator and anchor do too when their sandbox cannot be
applied, a fault Coral tolerates. Those CLIs get a private config directory
too, but they and anything they start are not confined and can reach your
`~/.claude` (CRL-180). The step's CLI still receives the `env` block of your
`~/.claude/settings.json` (CRL-167). A step can add Claude Code project
settings, such as hooks, to its worktree, which, from the code, your own
Claude Code loads if you open and trust that worktree (CRL-181). A step can
still reach your `~/.claude` indirectly, through the channels above to code
outside the sandbox, such as your own Claude Code's inbox (CRL-174) or, on a
single-user server, the server itself (CRL-159). A step whose sandbox cannot
wrap its CLI does not start. Coral steps need a system `claude` CLI, or they
refuse to start: the SDK's bundled one cannot be wrapped in the sandbox. See
the ADR-05 addenda on
[harness sockets](docs/coral/decisions/ADR-05-topology.md#addendum-crl-166-harness-sockets-on-macos-2026-11-22)
and
[Claude config isolation](docs/coral/decisions/ADR-05-topology.md#addendum-crl-176-claude-config-isolation-2026-11-22).

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
  Work lands on the `development` branch; `main` holds releases.
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
