# Contract K17: Coral Server Plugin Seam

## Seam Overview
- **Omnigent module**: `omnigent/server/server_plugins.py` (`CORAL(S32)`)
- **Plugin entrypoint**: `coral.server_plugin:register` (also configurable via `server_plugins` in server config or `create_app(server_plugins=...)`)

## Registration Contract
1. `create_app(...)` resolves `server_plugins` in order:
   - explicit `server_plugins` argument (when not `None`)
   - `server_config["server_plugins"]` (when key is present)
   - `OMNIGENT_SERVER_PLUGINS` comma-separated env var (set by `coral` CLI before importing `omnigent`)
2. `load_server_plugins(plugin_specs, services)` runs synchronously during `create_app(...)` after `runner_router` is constructed:
   - imports each module, invokes `register(services) -> ServerPluginRegistration`
   - eagerly imports every module in `registration.policy_modules` and verifies `POLICY_REGISTRY` is a `list`
   - raises `ServerPluginError` on any import, attribute, validation, or registration failure (aborting boot instead of running half-enabled)
3. `registration.policy_modules` are merged into `load_registry(extra_modules=...)` so agent bundle uploads accept plugin-registered policy handlers without duplicating `policy_modules` in server config.
4. `registration.routers` are appended to `all_extra_routers` and mounted **before** `_SPAStaticFiles` mounts `/`.
5. `registration.lifespan_hooks` enter inside `lifespan` after scheduler and sandbox reaper startup, and exit in reverse order before `pull_request_refresher`, scheduler, reaper, `startup_inputs`, and `runner_router` shut down.
6. `coral_lifespan` wires Coral's session engine before the worker supervisor starts, and on exit stops the supervisor before it unregisters the engine's effect executors and status-edge observers ([`session-facade.md`](session-facade.md), "Wiring").

## Coral Capability Probe & Process Tokens
- `GET /v1/coral/info` returns `200` with `{enabled, version, sub_features}` (13 keys defaulting to `false`; overrides validated against `coral_sub_features` in server config) when the Coral plugin is active, and `404` when absent.
- Coral refuses `host_sharded=True` during registration and lifespan startup.
- Hosts advertise `coral_runner:1` in their hello through Coral's tool provider (below); it is left out when `CORAL_DISABLE_HOST_ENTRY_POINTS=1`. The session facade refuses a step on a host whose live hello lacks it (`session.host_unsupported`, [`session-facade.md`](session-facade.md)). The token is self-reported: a compatibility gate, not an authorization boundary.

## Host Entry Points
- **`omnigent.host_workspace_ops`** (`CORAL(S40b)` in `pyproject.toml`): `coral = "coral.omni.host.ops:workspace_op_handlers"`. The host loads the group on its first `host.workspace_op` frame (`omnigent/host/workspace_ops.py`, `default_workspace_op_handlers`), never at import. Each entry point is a zero-argument callable returning `{op name: handler}`; Coral's serves `head`, `diff_stat`, `read`, `fingerprint`, `commit`, `salvage` and `reset` ([`workspace-ops.md`](workspace-ops.md)). A broken contribution is skipped with a warning, and an op offered by two contributions is served by neither. Installed metadata changes only after `uv sync`.
- **`omnigent.tool_providers`** (`CORAL(S50)` in `pyproject.toml`): `coral = "coral.omni.runner.tool_provider:tool_provider"`. Omnigent loads the group once per process on first use (`omnigent/tools/extensions.py`): the host for its hello tokens, a runner for each spec's tools and prompt text. Coral's provider offers a generated bundle the engine tools of its `params.coral.generated.stance` (`coral/tools/catalog.py`): `coral_submit_handoff` to implementers and reviewers, `coral_choose_arrow` to orchestrators, nothing to the anchor, other specs or native harnesses. The production catalog is empty, so no tool or prompt text is offered yet, and it lists no server-dispatched names. The provider imports only the standard library, the catalog, the process map and Omnigent's extension types, never server, database or engine modules. `CORAL_DISABLE_HOST_ENTRY_POINTS` removes only the host token: the host does not forward it to runners, whose provider stays loaded, which is harmless.
- **`CORAL_DISABLE_HOST_ENTRY_POINTS=1`** makes Coral's contribution return no handlers (checked before the handler modules are imported), so every Coral op gets `unknown_op`, which the server maps to permanent `workspace.capability_unavailable`. It does not withdraw the host's `workspace_ops:1` capability: that token belongs to the Omnigent channel (S40), not to Coral.
