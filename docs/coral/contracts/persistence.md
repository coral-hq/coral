# Contract K5 & K21: Coral Persistence, CAS Run Store & Leased Work Queue

## Seam Overview
- **Omnigent migration filter (`S30`)**: `omnigent/db/migrations/env.py` (`include_name` excludes `coral_*` and `coral_alembic_version`)
- **Multi-DB test truncation (`S31`)**: `tests/conftest.py` (preserves `alembic_version` and `coral_alembic_version` while truncating data tables)
- **Databricks Lakebase cold-start (`S57`)**: `deploy/databricks/src/app.py` (`run_coral_migrations_with_retry` runs immediately after Omnigent migrations)
- **Shared DB primitives (`S58`)**: `omnigent/db/pagination.py` (`keyset_after`), `omnigent/db/enum_codecs.py` (`encode_enum`, `decode_enum`), `omnigent/db/utils.py` (`SingletonThreadPool` guard for `:memory:` SQLite)

## Schema & Migration Isolation (`coral/db/`)
1. **Declarative Base**: All 19 Coral tables inherit from `CoralBase` (`coral/db/base.py`), keeping Coral `MetaData` isolated from `OmnigentBase` and `ConversationBase`.
2. **Alembic Lineage**: Coral tracks migrations in `coral_alembic_version` under `coral/db/migrations/` (`coral_0000_base` -> `coral_0001_core` -> `coral_0002_session_facade`).
3. **Migration Gatekeeper (`ensure_coral_schema`)**:
   - Rejects `cloudflare_d1` with `NotImplementedError`.
   - Verifies Omnigent's `alembic_version` is at head before touching any Coral table; raises `CoralSchemaOrderError` if Omnigent is unmigrated or behind head.
   - Verifies single Coral head revision and rejects database revisions newer than the running Coral build.
   - Applies Coral migrations via `alembic.command.upgrade(config, "head")` inside `query_name_scope("coral.database.run_migrations")` without ever calling `CoralBase.metadata.create_all()`.
   - Binds strictly to the operational database (`services.conversation_store.storage_location`), never `conversation_storage_location`.

## Table & Column Invariants (Contract K5)
- **Workspace Partitioning**: Every Coral table has `workspace_id` (`BigInteger`) as the leading primary-key column (`DEFAULT_WORKSPACE_ID = 0` for global singleton rows in `coral_worker_leases`).
- **Zero Foreign Keys**: Cross-entity integrity is enforced in application transactions and optimistic CAS transitions rather than database foreign keys.
- **Bounded Inline Columns**: Variable-length inline payloads use `CompressedText(16_383)` (`CAPPED_TEXT`); larger artifacts spill to `coral_blob_refs`.
- **Digests & Collation**: SHA-256 idempotency and content digests use `CHECKSUM32` (`LargeBinary(32)` / MySQL `BINARY(32)`). Case-sensitive lookup keys use `CaseSensitiveString` (`utf8mb4_bin` on MySQL).
- **Enum Storage**: Persisted enums use `SmallInteger` columns paired with explicit `CheckConstraint` definitions named `ck_coral_<table>_<column>` (a widened check may carry a `_vN` suffix, so CockroachDB can replace it in one transaction).

## Session Facade Tables (`coral_0002_session_facade`)
`coral_0002_session_facade` adds three tables and widens the run pause reasons. The stores below are synchronous; async callers use `asyncio.to_thread`. Each reserve or record is insert-if-absent: it returns the stored row, re-reads it after an `IntegrityError` from a concurrent insert, and raises a conflict when the stored row differs in any recorded field. Conflict messages name only the caller's own session, stable id or op key; the exception's `fields` lists what differs and `stored` holds the stored row for logs. Lookups that act on a session take a required `run_id` and return nothing for another run's row.

| Table | Key | Store (`coral/stores/`) | Holds |
|---|---|---|---|
| `coral_session_bindings` | `(workspace_id, session_id)`; unique `uq_coral_session_bindings_effect (workspace_id, run_id, effect_cksum)`; index `ix_coral_session_bindings_run (workspace_id, run_id, role, session_id)` | `SqlAlchemySessionBindingStore` (`session_bindings.py`, protocol `SessionBindings`, query names `coral.session_bindings.*`) | The Omnigent session of a run's anchor (`role` 1) or of one engine step slot (`role` 2): run, engine `slot_id` (`CaseSensitiveString(512)`), `slot_role` (`SLOT_ROLE` codes; decides who may commit), sha256 of the creating effect key, session generation, host, and create `progress` (`reserved` 1, `row_created` 2, `initialized` 3). Anchors have no slot id, slot role or host. |
| `coral_stable_ids` | `(workspace_id, stable_id)`; index `ix_coral_stable_ids_session (workspace_id, session_id, stable_id)` | `SqlAlchemyStableIdStore` (`stable_ids.py`, protocol `StableIds`, `coral.stable_ids.*`) | Message item ids the engine sent (`kind`: `brief` 1, `steer` 2, `nudge` 3) with `content_cksum`, the sha256 of the exact text sent (`CHECKSUM32`), recorded before the send so engine items can be told from user items. |
| `coral_workspace_op_intents` | `(workspace_id, op_key)`; index `ix_coral_workspace_op_intents_run (workspace_id, run_id, op_key)` | `SqlAlchemyWorkspaceOpIntentStore` (`workspace_op_intents.py`, protocol `WorkspaceOpIntents`, `coral.workspace_op_intents.*`) | A workspace write op (`op`: `commit` 1, `salvage` 2, `reset` 3) recorded before its first try with its host, root and the `expected_head` read then; retries get the stored HEAD back. |

- **Bindings.** An anchor's session id must be `anchor_session_id(workspace_id, run_id)` (`coral/model/ids.py`), else `reserve` raises `ValueError`; the primary key therefore holds one anchor per run on every lane. `reserve` returns the stored binding only when run, role, slot id, slot role, generation, host and, for a step, effect checksum all match; otherwise it raises `BindingConflict`. A re-keyed anchor effect for the same run adopts the stored anchor, which keeps its first effect checksum. An effect already bound to another session of the run raises `BindingConflict`. `get(workspace_id, session_id, run_id=…)` returns nothing for another run's session; a session without a binding for the run is not writable, so callers must not commit for it. `record_progress` never lowers the stored progress and raises `BindingNotFound` for an unknown session. `list_for_run` returns the anchor first.
- **Stable ids.** `record_send(…, content=…)` stores the content checksum and raises `StableIdConflict` when the id is recorded with a different run, session, effect, content checksum, kind or generation. `lookup` and `list_for_session` take `run_id` and return only that run's records; `list_for_session` returns exactly the session's ids. `content_checksum(text)` gives the digest to compare with an item found under the id before treating it as the engine's.
- **Op intents.** `reserve` raises `OpIntentConflict` when the op key is recorded for another run, op, host or root. `get(workspace_id, op_key, run_id=…)` returns nothing for another run's intent.
- **Drift pause.** `coral_runs.pause_reason` accepts `drift` (`12`, `RunPauseReason.DRIFT`). The upgrade replaces `ck_coral_runs_pause_reason` with `ck_coral_runs_pause_reason_v2` inside `batch_alter_table` (a distinct name lets CockroachDB replace the check in one transaction). The downgrade refuses offline and while any run is paused for drift, restores the old check first (the step that can still fail on data), then drops the three tables. Stop Coral servers before downgrading: it drops in-flight session state.

## Optimistic CAS Run Store (`coral/stores/`)
1. **`start_run`**: Supports unkeyed UUIDv4 run creation and idempotent `start_key` creation (`derived_id("coral-run", user_id, start_key)`). Re-submitting an existing `start_key` with a different `RunStartSpec` digest raises `StartKeyConflict`.
2. **`load_run_state` & `apply_transition`**:
   - Reducers load a frozen `RunState` snapshot outside write locks via `shared_read_scope()`.
   - `apply_transition` enforces batch caps (`<= 64` log entries and `<= 64` outbox work items, raising `TransitionTooLarge`), locks the `coral_runs` row with `FOR UPDATE`, verifies `row.version == expected_version` (raising `RunVersionConflict` on mismatch), increments `version` and `next_log_seq`, upserts modified child rows, appends `coral_run_log` entries, inserts `outbox_work` into `coral_work` with dialect-safe conflict ignore, and marks `consumed_work_ids` as `WorkStatus.SUCCEEDED`.
3. **`commit_with_retry`**: Checks `find_receipt` at the start of every attempt before loading state or invoking `reduce_fn`, retrying `RunVersionConflict` with jittered backoff up to `max_attempts` before raising `RunContended`.

## Leased Work Queue & Worker Supervision (`coral/queue/`, `coral/workers/`, `coral/reconcile/`)
1. **Unified `coral_work` Queue (`SqlAlchemyCoralQueueStore`)**:
   - Stores signals (`1`), timers (`2`), and effects (`3`) deduplicated by `uq_coral_work_idempotency (workspace_id, run_id, idempotency_cksum)`.
   - `claim_work` locks ready `PENDING` rows (`FOR UPDATE SKIP LOCKED` on PostgreSQL, CockroachDB, and MySQL) and reads the post-lock clock before setting `lease_expires_at` and incrementing `attempts`.
   - `renew_lease` locks the row first and rejects expired or mismatched claims so a late heartbeat never revives an expired lease.
   - `reclaim_expired_work` resets expired `CLAIMED` rows to `PENDING` without resetting `attempts` or `idempotency_cksum`.
2. **Effect Execution & Fencing (`WorkDrainer`)**:
   - Abandons work items (`WorkStatus.ABANDONED`) without invoking the executor when the target run is in a terminal status (`COMPLETED`, `FAILED`, `CANCELLED`) or when `slot_generation` does not match the current `coral_agent_slots.session_generation`.
   - Executors call `await ctx.ensure_lease()` before external side effects; lease loss raises `StartupLeaseLost`.
   - Transient failures (`EffectFailed(retryable=True)`) reschedule with jittered exponential backoff (`1s` to `300s`) up to 8 attempts before failing terminally with `error_code="infra.transient"`.
3. **Leader Lease & Startup Sweep (`WorkerSupervisor`, `startup_recovery_sweep`)**:
   - Acquires the singleton `coral.worker.primary` lease (`120s` TTL, `30s` renewal) in `coral_worker_leases` (`workspace_id = 0`).
   - On leadership acquisition, runs `startup_recovery_sweep` to reclaim expired work, keyset-scan open gates (`list_open_gates_all_workspaces`), and keyset-scan active runs (`list_active_runs_all_workspaces`), isolating per-gate and per-run callback errors.
   - Releases the replica lease immediately on shutdown (`stop()`).
