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
on macOS 27.2.1; a macOS CI lane (CRL-170) now runs the sandbox tests and
probe 15 on changes to the files they depend on and weekly, and is not a
required check. Since CRL-167, on
Linux and macOS a Coral step's Claude CLI no longer holds your model API key,
in its environment or on its command line. The key stays in a proxy on
loopback inside the step's own harness process, and the CLI holds a
per-session token that only that proxy accepts, for model requests only. The
credentials the host forwards to its runners are removed from a Coral
harness's environment before it starts the CLI. The runners and harnesses the
host forks no longer expose the host's whole environment to other processes,
and a runner's own tokens are no longer in its environment. That was measured
on macOS 27.2.1; the `coral-e2e` lane checks it on Linux, with its expected
results set by reasoning until that lane has run. Still open (CRL-197): other
Omnigent agents' CLIs keep their key on the command line; a runner the host
starts directly, without forking, and the runner of `omnigent run` still
start with credentials in their environment; claude-native steps; and
Windows, where none of this changes. A step with network on can still connect
to loopback TCP listeners. Since CRL-177 the codex-native app-server refuses a
caller without a per-spawn token, which a sandboxed step cannot read;
claude-native's relays, the runner's direct-attach listener and OpenCode's
server already required their own secrets. That was measured on macOS 26.3.1
only. A Codex without `--ws-auth` still runs its app-server with no token,
which only the runner log reports (noted on CRL-177). Other loopback
listeners, including other programs' services (CRL-174), and UDP are not
covered. On Linux a step can also reach other programs' abstract sockets
(CRL-174), measured in `coral-e2e` lane run 45187294423. On a single-user
server, on any platform, a step can act as you, the owner, so neither a human
gate nor the sandbox is a security control there. That is accepted: such a
server never labels a gate Enforced. On a server that signs users in with
accounts, a sandboxed step could not get your sign-in token (measured on macOS
27.2.1, and on Linux in that lane run). Six open issues still keep every gate
labelled not Enforced: other programs' sockets (CRL-174), files a step leaves
for your own tools (CRL-181), macOS Mach services, the clipboard and Spotlight
(CRL-171), macOS and CLI updates that no CI lane checks (CRL-170), an owner
credential that a step of another or an earlier run obtained (CRL-193), and
password guessing at sign-in (CRL-195). A run's detail says why in
`gate_integrity`.

Since CRL-176 a Coral step's Claude CLI keeps its Claude Code state in a
private directory, a fresh one for each launch in the sandbox. While the CLI
runs in the sandbox, neither the CLI nor anything it starts can read or write
your real `~/.claude` or `~/.claude.json`, such as the plugins and hooks your
own Claude Code runs. That was measured on macOS 27.2.1, and a bwrap test
checks it on Linux in CI.

Since CRL-178 the same holds for other Omnigent agents whose claude-sdk CLI
runs in a sandbox on Linux or macOS. Their CLI gets a private directory for
each launch. For an agent that loads your settings, the default, that directory
holds a filtered copy of your `~/.claude.json`: the MCP servers it defines for
you, with any you turned off for a project still off, your user ID, any legacy
top-level `env` values, and the paths of projects where you set trust or MCP
keys. Code in that sandbox can still read what was copied, including any
secrets in the MCP servers' `env`, arguments or headers (CRL-197). Since
CRL-179, the copies that a stopped or killed CLI, or a killed runner, leaves in
the temp dir are removed only when one of your claude-sdk agents on this host
next connects a CLI or closes with the same temp dir, a large one over several
of those, and stay if none does. Copies from before CRL-179 or from a build
without it, or in a dir a sandboxed CLI changed so the cleanup keeps it, stay
until you delete your `omnigent-osenv-*`, `omnigent-claude-seed-*` and
`omnigent-claude-config-*` dirs there, with every Omnigent server, runner and
agent stopped; so do scratches under a `TMPDIR` set in your Claude settings
`env`, in that dir. A Claude subscription login stored on the host no longer
reaches these agents. On Linux
this is a breaking change: an agent that used it now needs an API key, a
gateway or `CLAUDE_CODE_OAUTH_TOKEN`. Its HTTP MCP servers also lose the OAuth
sign-ins the CLI stored, so they may need a new sign-in or be missing their
tools (from the CLI binary, not measured). On macOS both live in the keychain,
which the sandbox could not open before either, so they very likely did not
work there. Give such an agent an API key or a gateway with
`uv run coral setup`, or set `CLAUDE_CODE_OAUTH_TOKEN` (from
`claude setup-token`) in the environment that starts Coral. The host passes
that token to every runner it starts, and code in an agent's sandbox may be
able to read whichever credential the agent gets (CRL-197). Only CLIs that run
in a sandbox on Linux or macOS are covered. A working directory or a
`read_paths` or `write_paths` entry above your home, such as `/` or `/Users`,
exposes `~/.claude` too, because the sandbox hides dotfiles only at the top
level of each directory it grants (from the code; CRL-184). On Windows nothing changes,
because its sandbox does not confine files. An agent with `sandbox: none` or
without `os_env`, which includes most of Omnigent's example agents, runs its
CLI as you, with your `~/.claude`. So does any other agent's claude-sdk CLI
when the operator sets `OMNIGENT_CLAUDE_SDK_NO_SANDBOX`, when its sandbox
denies the network, when only the SDK's bundled `claude` is available, or when
its sandbox cannot be applied, which only the runner log reports (CRL-183).

Coral's orchestrator and anchor have no `os_env`, so, from the code, their CLIs
run outside the sandbox on every platform, as does every Coral CLI when the
operator sets `OMNIGENT_CLAUDE_SDK_NO_SANDBOX`. Those CLIs get a private config
directory too, but they and anything they start are not confined and can reach
your `~/.claude` (CRL-180). Since CRL-167, on Linux and macOS a step's CLI
takes only a few names from the `env` block of your `~/.claude/settings.json`:
model names, the telemetry, error-reporting, auto-update and
non-essential-traffic opt-outs when they are switched on, and proxy and
CA-file settings that hold no credential. The model endpoint named there, and
a proxy with a user name or password, go to the step's key proxy instead.
These endpoint and network settings count only from a settings file outside
the step's working directory, under the default or an absolute
`CLAUDE_CONFIG_DIR`; an endpoint in any other settings file stops the step.
Everything else in the block is dropped, so a provider switch there, such as
Bedrock or Vertex, no longer applies to steps: a step runs on the key or
provider from `uv run coral setup`. With a gateway provider the block never
reached a step's CLI. A sandboxed agent's CLI with `skills: none` and no
gateway still receives the whole block (CRL-197). A step in its worktree, or a sandboxed
agent in its working directory, can add Claude Code project settings, such as
hooks, which, from the code, your own Claude Code loads if you open and trust
that directory (CRL-181). A step or a sandboxed agent can still reach your
`~/.claude` indirectly, through the channels above to code outside the sandbox,
such as your own Claude Code's inbox (CRL-174) or, on a single-user server, the
server itself (accepted, above). A step whose sandbox cannot wrap its CLI does
not start. Coral steps need a system `claude` CLI, or they refuse to start: the
SDK's bundled one cannot be wrapped in the sandbox. See the ADR-05 addenda on
[harness sockets](docs/coral/decisions/ADR-05-topology.md#addendum-crl-166-harness-sockets-on-macos-2026-11-22),
[Claude config isolation](docs/coral/decisions/ADR-05-topology.md#addendum-crl-176-claude-config-isolation-2026-11-22),
[sandboxed agents' Claude config](docs/coral/decisions/ADR-05-topology.md#addendum-crl-178-claude-config-isolation-for-every-sandboxed-agent-2026-11-22),
[launch temp dir cleanup](docs/coral/decisions/ADR-05-topology.md#addendum-crl-179-launch-temp-dir-cleanup-2026-11-22),
[identity-requiring servers and gate labels](docs/coral/decisions/ADR-05-topology.md#addendum-crl-159-probe-15-on-identity-requiring-servers-2026-11-23)
and
[secrets out of exec-time environments](docs/coral/decisions/ADR-05-topology.md#addendum-crl-167-secrets-out-of-exec-time-environments-2026-11-24).

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
