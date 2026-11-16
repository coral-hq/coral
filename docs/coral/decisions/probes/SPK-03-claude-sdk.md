# SPK-03 claude-sdk probe verdicts

This memo records what the real `ClaudeSDKExecutor` and `claude` CLI did when
`mock_llm_server` was the only model endpoint. Each spike has a script in this
directory that prints one JSON verdict. Nothing imports these scripts.

| Spike | Verdict | Decides | Consumer |
| --- | --- | --- | --- |
| 4, mock `ANTHROPIC_BASE_URL` | pass | Tier B harness is claude-sdk | FND-04 |
| 1, `can_use_tool` gate under `bypassPermissions` and `auto` | fail | S21 is needed | HRN-02 |
| 7, CLI MCP tool timeout | partial | Bounds for long tool calls | TLS-02, EVD-02 |
| 2, Agent and Task unreachable | not run | Outside this change | K9 attribution |
| 16, watchdog against a long turn | not run | Outside this change | S27 retest placement |
| 19, local `CredentialStore` | not run | Outside this change | K12 auth refs |
| 20, plain routing pin | not run | Outside this change | SES-03 create defaults |

Spikes 2, 16, 19 and 20 have no verdict yet. Their pre-read pointers are in the
SPK-03 section of `docs/coral/roadmap/CORAL_ENGINEERING_ROADMAP.md`.

## Versions probed

- `claude` CLI 2.1.185, at `/opt/homebrew/bin/claude` (the path that
  `_find_system_claude` resolved).
- `claude-agent-sdk` 0.2.121. It bundles CLI 2.1.212, which the executor uses
  only when it finds no system `claude`. The probes print `blocked` in that
  case, so a verdict always names the CLI that produced it.
- macOS, Python 3.12, probes run on 2026-11-15.

Every script prints `cli_path`, `cli_version` and `sdk_version`. Rerun the
probes after a CLI or SDK upgrade and compare.

## How the probes isolate the CLI

`tests/e2e/coral/_claude_sdk_kit.py` holds the shared mechanics. Each case:

1. Starts its own `tests/server/integration/mock_llm_server.py`, so the request
   ledger holds only that case's calls.
2. Creates a fresh `HOME` whose `.claude.json` declares one stdio MCP server,
   `probe` (`tests/e2e/coral/_probe_mcp_server.py`). Its `touch` tool writes a
   marker file. Its `nap` tool sleeps first.
3. Builds the CLI environment from an allowlist (`PATH`, locale, `TMPDIR` and a
   few others) and unsets every other inherited name, including credentials and
   provider switches. It sets `HOME` and `CLAUDE_CONFIG_DIR` to the fresh home,
   `ANTHROPIC_BASE_URL` to the mock root URL with no `/v1` suffix, and
   `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`.
4. Points `HTTPS_PROXY`, `HTTP_PROXY` and `ALL_PROXY`, in upper and lower case,
   at `EgressRecorder`, a local proxy that refuses and records every request.
   `NO_PROXY` and `no_proxy` are `127.0.0.1,localhost`.
5. Builds the executor with `api_key_helper="printf %s mock-key"` and runs one
   turn whose user text carries a unique token. The mock routes on that token.

The CLI hides MCP tools behind `ToolSearch`. The mock therefore answers
`ToolSearch` with `select:mcp__probe__<tool>` first, then the tool call, then
`done <token>`.

The first runs of spikes 4 and 1 used an earlier scrub that unset only the API
key and token variables. Both spikes were rerun with the allowlist on
2026-11-15 and gave the same results.

The recorder sees only clients that honor the proxy variables. It does not see
raw sockets, DNS, or child processes that ignore those variables. So the
verdicts below show no proxied HTTP(S) egress, not that nothing left the
machine.

## Spike 4: mock `ANTHROPIC_BASE_URL`

Verdict: pass.

```bash
uv run --no-sync python docs/coral/decisions/probes/spike_04.py
```

Both runs returned `pass`. Each run has three cases in `bypassPermissions`
with the model id `mock-spk03-probe`:

| Case | Mock `/v1/messages` calls | Egress recorder | Result |
| --- | --- | --- | --- |
| Text only | 1 | 0 requests | `done <token>` |
| Stdio MCP `touch` | 3 | 0 requests | tool ran once, the model got `TOUCHED-spike-04`, `done <token>` |
| Control: `ANTHROPIC_BASE_URL=https://api.example.invalid` | 0 | `CONNECT api.example.invalid:443 HTTP/1.1` | turn failed with `API Error: 403` |

The CLI sent every model call to the mock root URL and made no proxied HTTP(S)
request. The control case proves the recorder sees the CLI's non-local model
traffic, so an empty recorder means the CLI made no proxied request. The probe
unset the API key and token variables. Non-`claude-*` model ids work.

Tier B therefore uses claude-sdk. The openai-agents fallback is not needed.
`register_dir_agent_with_mock_llm` builds a URL that ends in `/v1`. The
claude-sdk form is the mock root, as `register_inline_agent` passes it.

## Spike 1: `_can_use_tool_gate` with a DENY-all TOOL_CALL policy

Verdict: fail. S21 is needed.

```bash
uv run --no-sync python docs/coral/decisions/probes/spike_01.py
uv run --no-sync python docs/coral/decisions/probes/spike_01.py --model claude-sonnet-4-6
```

The probe sets `executor._policy_evaluator`, the attribute that
`omnigent/runtime/harnesses/_executor_adapter.py:302` sets in production. The
evaluator answers `POLICY_ACTION_DENY` for `PHASE_TOOL_CALL` and
`POLICY_ACTION_ALLOW` for every other phase. The mock then scripts a call to
the connector tool `mcp__probe__touch`.

Results with `mock-spk03-probe` (two runs, identical) and `claude-sonnet-4-6`
(one run, identical):

| Mode | Gate called | Tool ran | Mock calls | What the model got back |
| --- | --- | --- | --- | --- |
| `bypassPermissions` | no | yes | 3 | `TOUCHED-spike-01` |
| `default` | yes | no | 3 | `probe deny` |
| `auto` | no | no | 13 | denied by the Claude Code auto mode classifier |
| `auto`, classifier answers `<block>no</block>` | no | yes | 4 | `TOUCHED-spike-01` |

With `claude-sonnet-4-20250514` (one run) the classifier did not run. In `auto`
the gate was called and the tool did not run, as in `default`.

What this shows:

- Under `bypassPermissions`, the CLI approves the tool before it asks the SDK
  callback. The SDK says so in a `CanUseToolShadowedWarning` on every run
  (`claude_agent_sdk/types.py:1662-1673`, and the `can_use_tool` docstring at
  `:1895-1910`).
- Under `auto`, the CLI first runs its auto-mode classifier for some model ids.
  The classifier sends its own `/v1/messages` calls through the same base URL:
  10 extra calls when the mock's answer did not match its `<block>` contract,
  1 when the mock answered `<block>no</block>`. When it allows the call, the
  tool runs and `_can_use_tool_gate` is never called. When it blocks, the tool
  does not run, but the Omnigent policy still did not decide.
- Under `default`, the gate is called and the DENY holds.
- `mcp__omnigent__*` tools do not go through this gate. `_evaluate_tool_call_policy`
  returns early for them (`omnigent/inner/claude_sdk_executor.py:2784`) because
  the server gates them on the dispatch path.

The harness default is `auto` (`omnigent/inner/claude_sdk_harness.py:135`). In
that default configuration an Omnigent TOOL_CALL DENY on a connector MCP tool
is not enforced. With `mock-spk03-probe` and `claude-sonnet-4-6`, the gate was
not called in `auto` at all, whether the classifier blocked or allowed. A
connector MCP tool runs whenever the classifier allows it, for example after a
prompt injection. This is a product-level policy gap, not only a test limit.
The S21 `PreToolUse` hook work fixes it. Until then, run connector-heavy
sessions in `default` permission mode, where the DENY holds.

The comments at `omnigent/inner/claude_sdk_executor.py:2833-2843` and
`:3132-3148` say the gate runs in every permission mode. These results show it
does not. The fix is S21, a gate on a `PreToolUse` hook, and it belongs to
HRN-02. This change does not touch the executor or those comments.

The classifier transcript that the CLI sends to the base URL includes the
local OS user name.

## Spike 7: MCP tool timeout

Verdict: partial.

```bash
uv run --no-sync python docs/coral/decisions/probes/spike_07.py --seconds 30
uv run --no-sync python docs/coral/decisions/probes/spike_07.py --seconds 10 \
  --mcp-tool-timeout-ms 3000
```

Run these by hand. Each takes two to ten minutes:

```bash
uv run --no-sync python docs/coral/decisions/probes/spike_07.py --seconds 120
uv run --no-sync python docs/coral/decisions/probes/spike_07.py --seconds 600
```

The probe calls the stdio tool `nap` in `bypassPermissions` with no policy
evaluator. It unsets `MCP_TOOL_TIMEOUT` unless `--mcp-tool-timeout-ms` is
given.

| Nap | `MCP_TOOL_TIMEOUT` | Elapsed | Outcome |
| --- | --- | --- | --- |
| 30 s | unset | about 33 s | the model got `NAPPED-30.0`, turn completed |
| 10 s | 3000 | 5.7 s | the model got `MCP server "probe" tool "nap" timed out after 3s`, turn completed |
| 120 s | unset | 123.7 s | the model got `NAPPED-120.0`, turn completed |
| 600 s | unset | 603.7 s | the model got `NAPPED-600.0`, turn completed |

During the 600 s run the executor logged `Claude SDK response stream has been
idle for 600s ...; still waiting`. That line is a log only. It did not end the
turn. Spike 16 owns that watchdog question.

Bounds:

- With `MCP_TOOL_TIMEOUT` unset, CLI 2.1.185 waits at least 600 s for a stdio
  MCP tool.
- With `MCP_TOOL_TIMEOUT` set, the CLI enforces it in milliseconds and returns
  the timeout to the model as a tool result. The turn continues.
- Nothing under `omnigent/` sets `MCP_TOOL_TIMEOUT`.
- The server hops wait 7230 s (`MCP_PROXY_FORWARD_TIMEOUT_S`) and 7260 s
  (`MCP_PROXY_CALL_TIMEOUT_S`), over `_RUNNER_EXECUTION_TIMEOUT_S = 7200.0`
  (`omnigent/runner/tool_dispatch.py:209, 229-230`). These values come from
  reading the code, not from a run.

Not measured: the in-process `mcp__omnigent__*` path. It uses the SDK control
protocol and needs the runner dispatch bridge, so this probe cannot reach it.
That gap is why the verdict is partial.

## Prerequisite check

A probe that cannot run prints `blocked` and the missing prerequisite. It never
prints `pass`. It uses the same check as the Tier B skip
(`tests/e2e/_harness_probes.py`, `cli_unavailable_reason("claude")`):

```bash
env PATH=/usr/bin:/bin "$(command -v uv)" run --no-sync python docs/coral/decisions/probes/spike_04.py
```

prints `{"spike": 4, "verdict": "blocked", "missing": "'claude' CLI is not on PATH", ...}`.
Spikes 1 and 7 print the same shape.
