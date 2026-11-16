# Contract K5 & K21: Coral Persistence, CAS Run Store & Leased Work Queue

## Seam Overview
- **Omnigent migration filter (`S30`)**: `omnigent/db/migrations/env.py` (`include_name` excludes `coral_*` and `coral_alembic_version`)
- **Multi-DB test truncation (`S31`)**: `tests/conftest.py` (preserves `alembic_version` and `coral_alembic_version` while truncating data tables)
- **Databricks Lakebase cold-start (`S57`)**: `deploy/databricks/src/app.py` (`run_coral_migrations_with_retry` runs immediately after Omnigent migrations)
- **Shared DB primitives (`S58`)**: `omnigent/db/pagination.py` (`keyset_after`), `omnigent/db/enum_codecs.py` (`encode_enum`, `decode_enum`), `omnigent/db/utils.py` (`SingletonThreadPool` guard for `:memory:` SQLite)

## Schema & Migration Isolation (`coral/db/`)
1. **Declarative Base**: All 16 Coral tables inherit from `CoralBase` (`coral/db/base.py`), keeping Coral `MetaData` isolated from `OmnigentBase` and `ConversationBase`.
2. **Alembic Lineage**: Coral tracks migrations in `coral_alembic_version` under `coral/db/migrations/` (`coral_0000_base` -> `coral_0001_core`).
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
- **Enum Storage**: Persisted enums use `SmallInteger` columns paired with explicit `CheckConstraint` definitions named `ck_coral_<table>_<column>`.

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
