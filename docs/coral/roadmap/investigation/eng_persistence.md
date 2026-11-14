# Coral: persistence, migrations, stores, packaging and artifact storage

Staff Engineer (Agent 3). Repository: `omnigent-ai/omnigent`, HEAD `2a9cbe2c2`, version `0.22.0.dev0`.
Sources: `coral-design.md` (Draft 4, "D§"), `CORAL_WORKFLOW_ENGINE_DEEP_DIVE.md` ("DD§"), `coral_UI_DESIGN_LANGUAGE.md` ("UI§").
Every Omnigent claim below was opened at HEAD unless it is marked **UNVERIFIED**.
Legend for change type: **Reuse** (as-is), **Extend**, **Modify**, **New**, **Replace**, **Remove**.

---

## 0. Summary of decisions

1. **Package placement.** Use a **new top-level `coral/` package** in the same wheel as `omnigent`, with its own declarative base (`CoralBase`) and its **own Alembic environment** (`coral/db/alembic.ini`, `coral/db/migrations/`, `version_table="coral_alembic_version"`). I rejected putting Coral tables in Omnigent's migration chain: every upstream merge would need a merge revision in an upstream-owned directory, and a Coral database could no longer be opened by vanilla Omnigent. A sub-package (`omnigent/coral/`) is an acceptable fallback, but it contradicts D§16 ("standalone Python package") (§4).
2. **Two hard constraints from the code.** `CoralBase` must **not** subclass or share metadata with `OmnigentBase` or `ConversationBase`, because Omnigent runs `create_all` on both bases after every upgrade (`omnigent/db/utils.py:611-618`), and the CockroachDB bootstrap creates exactly those metadata objects (`omnigent/db/cockroachdb.py:289-300`). Coral's schema step must run **after** `get_or_create_engine` has brought Omnigent to head, because CockroachDB bootstrap refuses a fresh database that already holds tables (`cockroachdb.py:139-145`).
3. **Schema.** There are **26 proposed `coral_*` tables**: 16 in phase 1, 6 in phase 2, 3 in phase 3 and 1 in phase 7. The deep dive proposed 13 (§6). The additions come from rules the deep dive did not apply: child tables for repeated values (`docs/DATABASE_BEST_PRACTICES.md:306`), a hot/cold vertical split (`BP:115-121`), an artifact ledger (the `ArtifactStore` ABC has no list operation), a session-binding table for the hot observer path, and profile pinning (R13).
4. **Uniqueness without variable-length unique strings.** Use **derived ids** (sha256-truncated, as in `installed_agent_id`, `omnigent/db/utils.py:1134-1146`) so the primary key enforces identity. Use **32-byte digests** (as in `policies.name_cksum`, `db_models.py:1271-1274`, typed `_CKSUM32` at `db_models.py:48`) for idempotency keys. This avoids three problems: MySQL's case-insensitive test collation (`tests/conftest.py:670-671`), NULL owners in single-user mode, and index-length limits.
5. **Idempotent session creation needs a seam.** It cannot use a label lookup: `conversation_labels` has no `(key, value)` index (`db_models.py:1102-1118`). `ConversationStore.create_conversation` already accepts a caller-supplied id "for flows that require database-enforced idempotency" (`omnigent/stores/conversation_store/__init__.py:553, 616-618`), but the server's session-create path never passes one (`omnigent/server/routes/_sessions/orchestration.py:12326-12344`). This is new seam **P-S5** (§10).
6. **No `PersistentTaskScheduler` for timers or signals.** Draft 4 (coral-design.md:284) still says to use it, but the code contradicts it. It has a 16-method protocol typed on scheduled-task entities (`omnigent/stores/scheduled_task_store/dispatch.py:18-138`). It is off by default (`omnigent/server/feature_flags.py:54, 98-104`). Its recovery is at-most-once ("Recovery never sends the prompt again", `omnigent/server/scheduled/README.md:147`). The app builds exactly one instance, bound to `scheduled_task_store` (`omnigent/server/app.py:2124-2140`). Copy its **patterns** into Coral tables instead: lock-and-recheck claim, lease plus heartbeat, cross-workspace keyset discovery.
7. **CI coverage is mostly free.** Coral store tests under `tests/stores/coral/` and migration tests under `tests/db/coral/` run automatically:
   - on SQLite, in the `stores` and `db` matrix groups (`.github/scripts/ci/python-matrix.json`);
   - on Postgres 16, CockroachDB 23.2.28 and MySQL 8, because those lanes run `pytest tests/stores tests/db` (`.github/workflows/ci.yml:264, 315, 363`).

   Required test-infrastructure seam: S31. Recommended: P-S8 (cost control on per-test truncation).

---

## 1. Scope and method

- I read deep-dive §6.1-6.6, §7, §4.2-4.3 (S29-S31, S39), §9, §12-15, §17, §19-20 and App. B, and all of Draft 4. From the UI doc I grepped the persistence-relevant parts (UI§8.3, UI§8.4, the route table).
- I opened and verified, at HEAD:
  - `omnigent/db/*`, the migrations env and its 121 versions (head computed by parsing);
  - `omnigent/stores/{project_store,scheduled_task_store,artifact_store,conversation_store}`;
  - `omnigent/server/scheduled/{dispatch_scheduler.py,config.py,README.md}`;
  - the store wiring in `omnigent/server/app.py` and `omnigent/cli.py`;
  - `omnigent/server/accounts_store.py`, `omnigent/server/identity_migration.py`;
  - `pyproject.toml`, `pyrefly.toml`, `.pre-commit-config.yaml`, `.github/CODEOWNERS`, `dev/lint/*`;
  - the test fixtures `tests/conftest.py`, `tests/db/conftest.py`, `tests/stores/conftest.py`, `tests/server/conftest.py`;
  - the CI workflow and its scope scripts.
- I ran nothing beyond read-only `grep`/`sed`/`git` and one isolated Python parse of the migration files to compute heads.

---

## 2. Verified Omnigent conventions

### 2.1 Declarative bases: two, both reserved by Omnigent

| Fact | Evidence |
|---|---|
| `OmnigentBase(DeclarativeBase)` holds the operational tables | `omnigent/db/db_models.py:93-101` |
| `ConversationBase(DeclarativeBase)` holds `conversations`, `conversation_items` and `conversation_labels`. It may sit on a separate physical DB (`conversation_storage_location`). | `db_models.py:104-113`; `utils.py:489-529`; CLI `conv_db_uri` at `omnigent/cli.py:4888` |
| 19 tables, all defined in `db_models.py` | `grep -c __tablename__` = 19 |
| After every `alembic upgrade head`, Omnigent runs `create_all` for **both** bases as a safety net | `utils.py:611-618` |
| CockroachDB bootstrap builds the schema from both bases' metadata and stamps head | `cockroachdb.py:269-320` (`expected` at 289; `create_all` at 296-299) |
| The CockroachDB index repair iterates both metadatas | `cockroachdb.py:200-212` |
| The migration env's `target_metadata` is the union of both bases. There is no `include_name` filter. | `omnigent/db/migrations/env.py:37, 51-56, 85-89` |

**Implication.** Coral tables must live on a third, separate `DeclarativeBase`. Coral tables must live in the **Omnigent operational DB** (`db_uri`), never in the optional conversation DB. Coral must therefore never join Coral rows to `conversations` in SQL: session ids are plain columns, reconciled in code.

### 2.2 Column and key conventions

| Convention | Evidence | Coral usage |
|---|---|---|
| `workspace_id BigInteger` is the leading PK member, with `default=current_workspace_id`. **Every existing table also sets `server_default="0"`.** | `db_models.py:198-205` (`agents`), `790-797` (`projects`); context var at `116-157` | Reuse the leading-PK convention. **Omit `server_default`** on new tables, per `DATABASE_BEST_PRACTICES.md:247-252` (see correction C2). |
| `Uuid16` stores 16 raw bytes (`BINARY(16)` on MySQL) and returns bare 32-hex strings | `db_models.py:51-90` | Reuse for every id and every reference to an Omnigent id (session, host, agent) |
| Enums are `SmallInteger` with a CHECK, converted by codecs. Codes are append-only. | `omnigent/db/enum_codecs.py:1-20`; helpers `_encode`/`_decode` at `172-205` (private) | New `coral/db/enum_codecs.py`. Either import the private helpers or lift them (P-S9). |
| `CompressedText` is zstd-framed `LargeBinary`. It is **uncapped unless `max_stored_bytes` is set.** | `omnigent/db/compression.py:112-145` (cap at `127-145`). The precedent for a capped variant is `_MYSQL_BLOB_TEXT` at `db_models.py:628`. | Always `CompressedText(max_stored_bytes=16_383)` (C4) |
| 32-byte digest column: `LargeBinary(32)`, or `BINARY(32)` on MySQL | `db_models.py:45-48`; `policies.name_cksum` at `1202-1209, 1271-1274` | Idempotency keys and content hashes |
| Case-sensitive strings on MySQL: `String(n).with_variant(MySQLVarchar(n, charset="utf8mb4", collation="utf8mb4_bin"), "mysql")` | `scheduled_task_runs.trigger_key`, `db_models.py:1691-1697` | Every identifier column (node ids, arrow ids, keys) |
| SQLite and D1 ignore declared types and lengths, so byte caps need a CHECK with `.ddl_if(callable_=_on_sqlite_family)` | `db_models.py:631-652, 731-747` | Free-text columns, plus app-level validation |
| Owner: `user_id String(128)`, NULL in single-user mode, plus `account_generation String(32)`. Owners sit on **root** resources only. | `db_models.py:1568, 1588-1593` (scheduled tasks), `800-802` (projects); `require_active_account` at `omnigent/db/account_authority.py:145-197` | Owners go on root aggregates only (C10) |
| Timestamps: newer tables use `BigInteger` epoch seconds. Microseconds where ordering within one second matters. | `db_models.py:1639-1640, 1700, 1718-1720`; `now_epoch`/`now_epoch_us` at `utils.py:1523-1548` | `BigInteger` throughout. Use the `_us` suffix for µs. |
| Ids derived for PK-enforced idempotency | `builtin_agent_id`, `installed_agent_id`, `uploaded_agent_id` at `utils.py:1117-1166` | `coral/db/ids.py: derived_id(namespace, *parts)` |
| No database foreign keys (Rule R032). Cleanup is application-owned. | `omnigent/server/DBSPEC.md:109-126`; comments throughout `db_models.py` (e.g. `1594, 1611-1622`) | No FKs, including between `coral_*` tables |
| Explicit names on indexes and CHECKs; indexes end with the PK | `DATABASE_BEST_PRACTICES.md:160-171`; for example `db_models.py:1646-1655` | Same |
| **Cross-workspace worker scans lead with `status`/`state`, not `workspace_id`** | `ix_scheduled_tasks_due` (`state, next_run_at, workspace_id, id`) at `db_models.py:1646`; `ix_scheduled_task_runs_expired_claims` at `1739-1745`; `ix_hosts_sandbox_scan` at `1428` | Coral queue indexes do the same (C1) |

### 2.3 Rules that govern new tables (`docs/DATABASE_BEST_PRACTICES.md`)

The guide applies to new tables only (BP:15-19); existing exceptions are grandfathered. The blocking ("Required") rules Coral must meet:

- Reuse the stores, named managed sessions and Alembic. A separate persistence path needs a documented reason and design review (BP:50-62). A separate Alembic **environment** still uses Alembic and the managed layer, but call it out in the design review.
- Every read and write is bounded. Every list is paginated from its first release, with `numRowsScanned = O(limit)` (BP:75-101). **A configurable product quota is not a bound** (BP:79-81), so "activation cap" alone does not bound a scan. Use indexes that filter.
- Hard delete (BP:105-107). Explicit, stable PK. No auto-increment (BP:125-156).
- Every value is **at most 16,383 bytes** on every write path (BP:212-234). `String(4096)` without a byte cap is blocking on its own, so Coral strings stay ≤ 4095 characters, or are compressed and capped.
- No SQL `DEFAULT` on new tables, except `CURRENT_TIMESTAMP` (BP:247-252).
- No descending indexes (BP:203-206). The historical `idx_conversations_parent` uses DESC (`db_models.py:941-947`).
- Forbidden: generated columns, FKs, FLOAT/DOUBLE, native ENUM, LONGBLOB/TEXT, native JSON, TEXT, string UUIDs (BP:266-277).
- Do not filter on BLOB payloads (BP:300-304). Repeated or list values go in child tables (BP:306).
- **Schema changes ship in a standalone PR**, separate from business logic (BP:356-363). The roadmap must schedule migration PRs as their own items.
- Migration review: changes under `omnigent/db/migrations/` need approval from one of four upstream owners (`CONTRIBUTING.md:469-484`; `.github/CODEOWNERS:1-6`). The fork must decide its own owners for `coral/db/migrations/` (S39).

The existing schema deviates from the guide in places Coral **must not** copy:
- `Text` columns (`db_models.py:288, 476-477, 1020-1021`);
- `Float` columns (`1487-1488, 1606`);
- DESC indexes (`945-946`);
- `server_default` on new-table columns (`z6a2b3c4d5e6_add_scheduled_tasks_tables.py:40-71`).

`omnigent/server/DBSPEC.md:156-160` still recommends "TEXT for JSON", and `DBSPEC.md:8-9` names a stale `alembic/` path. Both are outdated relative to the best-practices guide.

### 2.4 Engine, migration and transaction mechanics

| Mechanism | Evidence | Notes for Coral |
|---|---|---|
| `get_or_create_engine(db_uri)`: on first creation, runs `_initialize_or_verify_schema` under `_engine_lock` and caches the engine per normalized URI | `utils.py:462-486` | Coral stores call it first, then `ensure_coral_schema` |
| Fresh DB → `_run_migrations`. Behind head → warn and auto-upgrade. Newer than build → refuse. | `utils.py:768-834` | Mirror all three cases for Coral |
| "Database newer than this build" guard | `_verify_db_revision_is_supported`, `utils.py:745-765` | Copy it for `coral_alembic_version` |
| **Single-head assumption**: `script.get_current_head()` raises on multiple heads; `MigrationContext.get_current_revision()` likewise | `utils.py:719-742, 695-716`; guard test at `tests/db/test_migration_connections.py:34-37` | Kills the "Alembic branch in `alembic_version`" option (F30 confirmed) |
| Head = `f1c7a9e2b406` (`add_conversation_family_id`), 121 revisions, one root `43fb65b29464`, **one merge revision** `b2e4f6a8c013` | Parsed `omnigent/db/migrations/versions/*.py` | C15 |
| Alembic config is built in code; `script_location` resolves relative to the package | `_build_alembic_config`, `utils.py:537-558`; `omnigent/db/alembic.ini:1-5` | Coral copies the pattern |
| Migrations import ORM types (`Uuid16`) from `db_models` | `f1c7a9e2b406_add_conversation_family_id.py:12`; `z6a2b3c4d5e6...:28` | Coral migrations import `Uuid16`/`CompressedText` from `omnigent.db`, accepting that coupling |
| SQLite: WAL, `busy_timeout=20000`, `synchronous=NORMAL`, `foreign_keys=ON` on every connection; pool 15+25 | `utils.py:290-331` | Single-writer contention (R10). Keep transactions short. |
| Non-SQLite: pool 200+20, `pool_pre_ping`, recycle 1800 s (600 s for Lakebase). **CockroachDB engines are forced to READ COMMITTED.** | `utils.py:337-396` | CAS and lock-and-recheck work under RC |
| `make_managed_session_maker(immediate=True)` issues `BEGIN IMMEDIATE` on SQLite after the PRAGMAs; commits on exit, rolls back on exception | `utils.py:901-979` (BEGIN IMMEDIATE at `969-972`) | Every Coral write maker uses `immediate=True` |
| `make_named_managed_session_maker(engine, query_name_prefix=…)` | `utils.py:982-1020` | Prefix `coral.<store>`; semantic suffixes (CLAUDE.md rule) |
| `run_write_transaction` retries **only CockroachDB 40001 and MySQL 1213** with jittered backoff (max 3). It does **not** retry Postgres, does not catch `IntegrityError`, and does not know about optimistic-version conflicts. | `utils.py:1023-1082` (predicate at `1058-1060`) | Coral needs its own reduce-and-retry loop on version conflict (C14) |
| `shared_read_scope()` collapses several reads into one checkout; write makers never participate | `utils.py:853-898` | Use for run-view snapshots |
| CockroachDB: version gate ≥ 23.2.28, READ COMMITTED required, SERIALIZABLE prepare per schema change, baseline revision `gf1b2c3d4e5f`, resumable bootstrap marker | `cockroachdb.py:25-38, 72-109, 112-123, 126-197` | Coral replays its own chain on CockroachDB using `_prepare_crdb_schema_transaction` (private) |
| Manual upgrade CLI: `omnigent debug db-upgrade URL` | `cli.py:12770-12795` | Add a Coral equivalent |
| Deploy-time migration with retry | `run_migrations_with_retry` at `utils.py:621-692`; caller at `deploy/databricks/src/app.py:222-228` | Add Coral to deploy entrypoints (P-S7) |

### 2.5 Supported backends

| Backend | Status at HEAD | Evidence | Coral position |
|---|---|---|---|
| SQLite (default, local `chat.db`) | Primary | `utils.py:290-331` | Supported. Single replica only. |
| PostgreSQL (incl. Databricks Lakebase OAuth) | Supported (`postgres` extra) | `pyproject.toml:299`; `utils.py:73-196, 332-396` | Supported. Recommended for multi-replica. |
| CockroachDB ≥ 23.2.28 | Supported (`cockroachdb` extra) | `pyproject.toml:146-148`; `cockroachdb.py:33-36` | Supported; Coral chain replayed with SERIALIZABLE prepare |
| MySQL 8 | Exercised in CI | `ci.yml:328-375` | Supported. Watch collation, BLOB and row-value comparisons. |
| Cloudflare D1 | Partial: FTS dialect test, CHECK `ddl_if`. The scheduler **refuses** it. | `utils.py:1229`; `db_models.py:652`; `scheduled_task_store/sqlalchemy_store.py:1186-1194`; test-only dependency `pyproject.toml:400-402` | **Refuse** in `ensure_coral_schema`, with the same message pattern |

### 2.6 Store patterns to copy

| Pattern | Evidence | Coral use |
|---|---|---|
| ABC holding `storage_location`, plus a SQLAlchemy implementation building `_session` and `_session_immediate` makers | `omnigent/stores/project_store/__init__.py:28-43`; `project_store/sqlalchemy_store.py:143-172` | Skeleton for every Coral store |
| `write(session)` closure inside `run_write_transaction(self._session_immediate, "<intent>", write)`; `require_active_account` first | `project_store/sqlalchemy_store.py:221-240`; `scheduled_task_store/sqlalchemy_store.py:259-293` (captures `generation` into `account_generation`) | Every mutating Coral method |
| Lock-and-recheck: `session.get(Model, pk, with_for_update=True)`, compare the snapshot, then mutate | `scheduled_task_store/sqlalchemy_store.py:1304-1335` (claim), `1393-1425` (claim pending), `1442-1457` (renew lease), `1518-1544` (transition only a matching lease) | Run CAS, effect and slot claims, lease renewal |
| Cross-workspace keyset discovery: `ORDER BY (time, workspace_id, id)`, limit ≥ 1, `_cursor_after` with a MySQL scalar-range fallback | `sqlalchemy_store.py:1245-1268, 1363-1379, 1459-1485`; `_cursor_after` at `1040-1063` | Due timers, ready effects, expired leases, active-run resync |
| `StartupLease`: attach the session before dispatch, renew under a lock, stop when the lease is lost | `omnigent/server/scheduled/dispatch_scheduler.py:152-347`; heartbeat at `1020-1053`; defaults poll 30 s, renewal 30 s, lease 120 s (`omnigent/server/scheduled/config.py:14-16`) | Slot startup and effect execution |
| Host-ownership sharding (`owned_hosts`); on failure the replica owns none | `dispatch_scheduler.py:374-375, 924-941`; contract at `scheduled/README.md:447-465` | `coral_effects.owner_key` |
| Dialect-specific upsert (MySQL `on_duplicate_key_update`, SQLite and Postgres `on_conflict_do_update`) | `project_store/sqlalchemy_store.py:393-419`; `preference_store/sqlalchemy_store.py:348` | Insert-or-ignore for signals and receipts, without poisoning the transaction with `IntegrityError` |
| Ambient scopes in workers: `workspace_scope(ws)` and `account_authority_scope(user, gen)` | `db_models.py:145-157`; `account_authority.py:79-91`; usage at `fire.py:581-585` and `dispatch_scheduler.py:563` | Every Coral worker iteration |
| Workspace-scoped in-process caches; the lint enforces this under server and runtime code | `omnigent/db/workspace_cache.py:1-53`; `dev/lint/lint_workspace_scoped_cache.py:40` | Compiled-graph cache keyed by version id |
| A best-effort, ordered single-worker executor for writes from status edges | `omnigent/server/session_live_state.py:120-160, 251-301` | The S1 observer path inserting `coral_signals` is **best-effort**, so the periodic reconcile is mandatory |

### 2.7 How stores are constructed and wired today

- The CLI resolves `db_uri = database_uri or cfg.get("database_uri", _default_db_uri())` (`cli.py:4887`). It constructs every store from it, `SqlAlchemyProjectStore(db_uri)` among them (`cli.py:4901-4919`), and builds the artifact store from `artifact_location` (`cli.py:4889, 4920`).
- `create_app(...)` receives stores as parameters (`omnigent/server/app.py:1563-1611`) and puts a few on `app.state`: `permission_store`, `host_store`, `agent_store` and others (`app.py:2277-2348`).
- `extra_routers` are mounted before the SPA catch-all (`app.py:5308-5311`). **The CLI's `create_app` call passes no `extra_routers`** (`cli.py:5118-5147`), only `debug_router_modules` from config.
- A second store can be derived inside app code from an existing store's `storage_location`, as `DeviceGrantStore(permission_store.storage_location)` does (`app.py:5110`). That pattern lets a Coral startup hook build its stores without a CLI change.
- `_lifespan` is internal (`app.py:1933`). There is no generic startup hook, which is seam S32.
- Conclusion: wiring Coral needs **S32** (lifespan hook), plus either a CLI change or a `create_app` hook that builds the Coral stores from `permission_store.storage_location` or `scheduled_task_store.storage_location`, and the routers (P-S4).

### 2.8 Artifact store (large blobs)

- ABC: `put(key, bytes)`, `get(key)`, `delete(key)`, `exists(key)` and `storage_location`. **There is no list or prefix enumeration** (`omnigent/stores/artifact_store/__init__.py:6-79`).
- Implementations:
  - `LocalArtifactStore`: atomic temp-file and `os.replace`; rejects keys with `..`, backslashes or absolute paths (`local.py:44-97`).
  - `S3ArtifactStore` (`s3.py:129`).
  - `DatabricksVolumesArtifactStore`.
- The CLI factory wires only local and `dbfs:/Volumes/` (`cli.py:1513-1536`). S3 exists but has no CLI wiring there.
- Runtime getter: `omnigent.runtime.get_artifact_store()` (`omnigent/runtime/__init__.py:96-106`).
- Key conventions:
  - content-addressed agent bundles `"{agent_id}/{sha256}"` (`omnigent/server/bundles.py:228-238, 281-290`; `app.py:982-1015`);
  - file blobs keyed by file id, with `blob_key` sharing for forks (`db_models.py:282-286`).
- Deletions observed at HEAD: session-scoped agent bundles (`omnigent/server/routes/_sessions/helpers.py:11227`) and uploaded files (`routes/sessions/routes_resources.py:2090, 2444`). I found no deletion of installed-agent bundle blobs on reinstall: **UNVERIFIED whether old revisions are retained**, so Coral must not rely on them (§7).

### 2.9 Packaging and tooling roots

| Item | Evidence | Impact of a top-level `coral/` |
|---|---|---|
| Package discovery `[tool.setuptools.packages.find] where=["."], include=["omnigent*"]`. pyproject-style discovery includes namespace packages (`omnigent/db/migrations` and `versions` have no `__init__.py` and still ship). | `pyproject.toml:453-460`; `ls omnigent/db/migrations` | Add `"coral*"` |
| Package data `"omnigent.db" = ["alembic.ini"]`, `"omnigent.db.migrations" = ["script.py.mako"]` | `pyproject.toml:462-464` | Add `"coral.db" = ["alembic.ini"]` and `"coral.db.migrations" = ["script.py.mako"]` |
| `setup.py` only adds build-info and web-UI steps | `setup.py:1-60` | No change |
| pyrefly `project-includes = ["omnigent/**/*.py", "omnigent/**/*.pyi", "sdks/python-client/**/*.py"]` | `pyrefly.toml:1-5` | Add `"coral/**/*.py"` |
| Pre-commit pyrefly hook `files: ^(omnigent/.*\.pyi?|sdks/python-client/.*\.py|pyproject\.toml|pyrefly\.toml|uv\.lock)$` | `.pre-commit-config.yaml:27-32` | Add `coral/` |
| Ruff isort `known-first-party = ["omnigent"]` | `pyproject.toml:618-625` | Add `"coral"` |
| Coverage `source = ["omnigent"]` | `pyproject.toml:537-545` | Add `"coral"` |
| Workspace-scoped-cache lint `SCANNED_ROOTS = ("omnigent/server/", "omnigent/runtime/")` | `dev/lint/lint_workspace_scoped_cache.py:40` | Add `"coral/"` (S39) |
| CODEOWNERS covers only `omnigent/db/migrations/`, `alembic.ini` and itself | `.github/CODEOWNERS:1-6` | Add the Coral migration paths and owners (S39) |
| uv workspace member `.github/triage_v2`; path deps for SDKs | `pyproject.toml:441-451` | No change: `coral` ships in the same distribution |
| Ruff runs on all `*.py`; custom-lint rules scope themselves | `.pre-commit-config.yaml:15-25, 58-67`; `dev/lint/custom_lint.py:1-20` | No change |
| CI path filters ignore only `web/`, `docs/`, `designs/`, `CHANGELOG.md` and some UI tests. An unmapped path is scoped `full` and turns on the backend and database lanes. | `ci.yml:16-36`; `.github/scripts/ci/dependency_scope.py:114-140, 159-183` | Any `coral/` change runs all DB lanes |

### 2.10 Test and CI infrastructure

| Item | Evidence |
|---|---|
| `db_uri` fixture, SQLite: a fresh file per test (optionally copied from a suite template), then `get_or_create_engine`; the engine is evicted after the test | `tests/conftest.py:706-732` |
| `db_uri` fixture, Postgres/MySQL/CockroachDB: reuses the per-worker DB and **truncates every table except `alembic_version`** (`DELETE FROM` on CockroachDB) | `tests/conftest.py:734-746` (filter at **736**) |
| `_worker_db_uri`: one DB per xdist worker (`omnigent_test_w0` and so on), created and migrated once per session; MySQL DB created as `utf8mb4_unicode_ci` | `tests/conftest.py:638-697` (collation at `670-671`) |
| The server suite migrates a SQLite template once per worker | `tests/server/conftest.py:519-547` |
| A CockroachDB DDL file lock serializes `test_migration*` and `test_cockroachdb.py` modules in `tests/db` and subdirectories | `tests/db/conftest.py:26-46` |
| Store fixtures and a `LocalArtifactStore` fixture | `tests/stores/conftest.py:18-57` |
| Static "SQLite-unsafe raw DDL" guard and a full-chain round trip | `tests/db/test_migrations_sqlite_safe.py:1-84` (`_raw_unsafe_op_calls`, `_VERSIONS_DIR`) |
| The single-head guard | `tests/db/test_migration_connections.py:34-37` |
| CI lanes `stores-postgres` (pg16), `stores-cockroachdb` (23.2.28) and `stores-mysql` (8.0) run `pytest tests/stores tests/db -m "not databricks" -n 4 --dist=loadfile` | `ci.yml:231-276, 279-326, 328-375` |
| SQLite groups `stores` and `db`. The `misc` catch-all picks up any new `tests/<dir>/`. | `.github/scripts/ci/python-matrix.json` |
| The full local CockroachDB matrix | `justfile:63-77`; `scripts/test_crdb_matrix.sh:16-17` |
| Pytest uses `testpaths=["tests"]` and package-style test dirs (`tests/__init__.py`, `tests/db/__init__.py`, `tests/stores/__init__.py`) | `pyproject.toml:474-490` |

---

## 3. Corrections and refinements to the deep dive and Draft 4

| # | Claim (source) | Finding | Evidence |
|---|---|---|---|
| C1 | "Indexes are named, start with `workspace_id` and end with the PK" (DD§7.1) | True for owner-scoped indexes. **Cross-workspace worker scans lead with status or time** ("Some cross-owner workloads need a different leading column"). Coral queue indexes must follow that. | `db_models.py:1428, 1646, 1739-1745`; `BP:178-180` |
| C2 | `workspace_id … default=current_workspace_id` (DD§7.1) | Every existing table **also** has `server_default="0"`. For **new** tables the guide forbids SQL defaults. Recommendation: Python default only. Decide this explicitly, because it departs from the house style. | `db_models.py:198-205`; `BP:247-252` |
| C3 | "No JSON, TEXT, FLOAT" (DD§7.1) | Correct for new tables, but the existing schema has all three, and `DBSPEC.md:156-160` recommends TEXT. Money must be integer micros or cents; percentages in basis points. | `db_models.py:288, 1020, 1487, 1606`; `BP:272-286` |
| C4 | "Opaque capped payloads use `CompressedText`" (DD§7.1) | `CompressedText()` is **uncapped** unless constructed with `max_stored_bytes`. Coral must use `CompressedText(max_stored_bytes=16_383)`. | `compression.py:127-145`; `BP:212-216` |
| C5 | Session creation is idempotent through a `coral.effect_id` label lookup (DD§6.1) | `conversation_labels` has PK `(workspace_id, conversation_id, key)` and **no index on value**, so a reverse lookup is an unbounded scan. Use a caller-supplied derived conversation id instead. The store supports it; the server path does not pass it (P-S5). | `db_models.py:1102-1118`; `conversation_store/__init__.py:553, 616-618`; `orchestration.py:12326-12344`; `helpers.py:11181-11193` |
| C6 | Draft 4 D§7.6 (coral-design.md:284): "The engine uses Omnigent's `PersistentTaskScheduler` … for timers and for the signal queue" | Reconfirmed **unsuitable** as the queue. Its patterns can be reused. | `dispatch.py:18-138` (16 methods); `feature_flags.py:54, 98-104`; `scheduled/README.md:147`; `app.py:2124-2140`; `sqlalchemy_store.py:1186-1194` |
| C7 | Unique keys on variable strings: `coral_signals.idempotency_key`, `coral_activations (…, node_id, scope_key)`, `coral_runs.start_key` unique per user (DD§7.2) | These clash with MySQL's case-insensitive test collation, NULL owners in single-user mode (NULLs are distinct) and index-length limits. Use derived-id PKs and 32-byte digests. | `tests/conftest.py:670-671`; `db_models.py:824-832` (projects' NULL-owner note); `utils.py:1134-1146` |
| C8 | `start_key` as a unique column (DD§7.2) | Replace it with a derived run id: `sha256("coral-run:" + (owner or "") + "\0" + start_key)[:32]`. A duplicate "Run" then collides on the PK. | Precedent `installed_agent_id`, `utils.py:1134-1146` |
| C9 | F30 evidence `tests/db/test_migration_connections.py:34-37` | Correct, but that file tests the **`connections` table** migration (GitHub App credentials). Its first test is the single-head guard. It is not about DB connections. | `tests/db/test_migration_connections.py:1-37` |
| C10 | Draft 4 D§7.6 (coral-design.md:290): "Every row carries an owner" | Owners belong on root aggregates (workflows, runs, profiles, repositories) per 3NF. Denormalize the owner only where an index needs it (gate inbox, alerts). | `db_models.py:775-777`; `BP:109-113` |
| C11 | D1 says Draft 4 "adopted … a decision log" | The decision log is a **document section** (coral-design.md:425-436), not a product feature. It has no persistence impact. The product's "decisions with reasons" live in `coral_run_log`. | coral-design.md:9-19, 282, 425-436 |
| C12 | Draft 4 D§7.6: "a small set of new tables: workflow versions, runs, step attempts and handoffs" | Understated. About 26 tables are needed to satisfy BP and the engine semantics (§6). | — |
| C13 | DD§7.4 cites `project_store/sqlalchemy_store.py:162-248` | `__init__` is at **152-172**; `create` is at 204-240 | file |
| C14 | DD§6.5: "optimistic `coral_runs.version` … inside `run_write_transaction`, which retries" | That function retries only CockroachDB 40001 and MySQL 1213, never version conflicts or Postgres. Coral needs its own outer reduce-and-retry loop. | `utils.py:1058-1060` |
| C15 | F31: "one base and one head" | True, but the chain is not linear: one merge revision exists (`b2e4f6a8c013_merge_completed_state_and_pull_requests.py`). The single head is what matters. | parse of `versions/` |
| C16 | `DBSPEC.md:8-9`: "Alembic migrations in `alembic/`" | Stale. The real location is `omnigent/db/migrations` (`omnigent/db/alembic.ini:2`). | — |
| C17 | UI§8.3: profiles possibly backed by localStorage | Cannot satisfy pinning (R13; `designs/REUSABLE_USER_AGENTS.md:112, 421-439`). Profiles must be server-side, with immutable revisions. | §6, T19-T21 |
| C18 | DD§7.3 says nothing about `create_all` for Coral | Coral should **not** run `create_all` after upgrade. Omnigent's safety net (`utils.py:614-618`) masks a forgotten migration; Coral should instead test that models match migrations (§11). | — |
| C19 | DD§7.3.3: "ensure_coral_schema after get_or_create_engine" | Correct. Also refuse D1, add a per-URI process cache, and require SERIALIZABLE prepare on CockroachDB (private helpers `cockroachdb.py:41-45, 101-109`). | — |
| C20 | DD§4.2: Postgres/CockroachDB/MySQL lanes "run only tests/stores and tests/db" | Confirmed (`ci.yml:264, 315, 363`). Engine fault-injection tests that need Postgres contention ("race two workers on Postgres", DD§19) must therefore live under `tests/stores/coral/`, not `tests/coral/`. | — |

---

## 4. Packaging and migration placement: options and recommendation

| Option | Merge cost with upstream | CI lanes | Single-head and `create_all` hazards | Reversibility and design fit | Verdict |
|---|---|---|---|---|---|
| **A. Top-level `coral/` package plus a separate Alembic env (`coral_alembic_version`)** | Config seams only, all in low-churn files and lines: `pyproject.toml:460, 462-464, 537-545, 618-625`; `pyrefly.toml:1-5`; `.pre-commit-config.yaml:32`; `lint_workspace_scoped_cache.py:40`; `CODEOWNERS`; `tests/conftest.py:736`; optional `env.py` filter. Upstream migrations never conflict. | Free: `tests/stores/coral` and `tests/db/coral` ride the existing lanes | None, if `CoralBase` is separate and Coral runs after Omnigent. Omnigent's single head and `alembic_version` stay pure upstream. | A Coral DB stays readable by vanilla Omnigent, which ignores unknown tables. Matches D§16 ("standalone Python package"). Can later become its own distribution without import renames. | **Recommended** |
| B. Sub-package `omnigent/coral/` plus a separate env | Fewer config seams: packaging, pyrefly, isort and coverage are automatic. Needs `package-data` for `omnigent.coral.db`. | Free | Same as A | Blurs the "engine is standalone" boundary. Moving out later is an import rename across the codebase. Upstream-wide lints and codemods over `omnigent/**` would also run on Coral (often a plus). | Acceptable fallback |
| C. Coral tables in Omnigent's chain (models on `OmnigentBase`, revisions in `omnigent/db/migrations/versions`) | **Every** upstream sync that adds a migration creates two heads, so the fork must add a merge revision in an upstream-owned, code-owned directory. Re-parenting instead of merging would silently skip upstream migrations on databases already at a Coral revision. | Free | `create_all` and CockroachDB bootstrap handle Coral tables automatically, but a missing migration is masked | A Coral DB can **no longer** be opened by vanilla Omnigent: "newer than this build" (`utils.py:745-765`). Rolling back means downgrading through merge revisions. | Reject |
| D. A separate distribution (uv workspace member) | Needs optional `omnigent → coral` imports at seams, two wheels and release coordination | Requires lane changes | Same as A | The cleanest separation, but heavy for v1 | Defer. A keeps D possible. |

Additional notes for option A:
- Import name collision: check that no third-party distribution in the dependency set ships a top-level `coral` module. **UNVERIFIED**; I did not check PyPI.
- Enforce the D§16 boundary with a custom-lint rule: only `coral/omni/**` and `coral/db/**` may import `omnigent.server.*` or underscore names from `omnigent.*`. That turns the `coral.omni` contract (DD§4.2) into a mechanical check.

---

## 5. Migration environment setup (concrete)

### 5.1 Files (all New)

```
coral/__init__.py
coral/db/__init__.py            # exports CoralBase, models, ensure_coral_schema
coral/db/base.py                # class CoralBase(DeclarativeBase): metadata = MetaData(naming_convention={"pk": "pk_%(table_name)s"})
coral/db/types.py               # CAPPED_BLOB, CKSUM32, ident(n), workspace_pk() — reusing omnigent.db types
coral/db/ids.py                 # derived_id(namespace, *parts) -> 32-hex (pattern of utils.py:1117-1166)
coral/db/enum_codecs.py         # CORAL_* code tables + encode_/decode_ functions
coral/db/models.py              # Sql* classes for coral_* tables (§6)
coral/db/bounds.py              # app-level byte-cap validation for strings (SQLite does not enforce)
coral/db/migrate.py             # ensure_coral_schema, run_coral_migrations[_with_retry], guards
coral/db/alembic.ini            # [alembic] script_location = coral/db/migrations ; loggers like omnigent/db/alembic.ini
coral/db/migrations/env.py
coral/db/migrations/script.py.mako   # copy of omnigent/db/migrations/script.py.mako
coral/db/migrations/versions/coral_0001_core.py      # phase-1 tables (standalone PR)
coral/db/migrations/versions/coral_0002_agents.py    # phase-2 tables
coral/db/migrations/versions/coral_0003_evidence.py  # phase-3 tables
coral/db/migrations/versions/coral_0004_amend.py     # phase-7 table
```

Revision ids must be **≤ 32 characters**, because Alembic's `version_num` is `VARCHAR(32)`. Prefix them `coral_` so they are distinguishable at a glance in a mixed DB.

### 5.2 `coral/db/migrations/env.py` (sketch; mirrors `omnigent/db/migrations/env.py`)

```python
from alembic import context
from coral.db import CoralBase
from omnigent.db.utils import _set_alembic_database_url   # same private helper Omnigent's env uses

CORAL_VERSION_TABLE = "coral_alembic_version"
target_metadata = CoralBase.metadata

def _coral_only(name, type_, parent_names):
    # Autogenerate must never see (and propose dropping) Omnigent's tables.
    if type_ == "table":
        return bool(name) and name.startswith("coral_")
    return True

def _run_with_connection(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=CORAL_VERSION_TABLE,
        include_name=_coral_only,
        render_as_batch=True,          # SQLite ALTER support, as in Omnigent's env.py:85-89
    )
    with context.begin_transaction():
        context.run_migrations()
# offline/online plumbing identical to omnigent/db/migrations/env.py:44-104, honouring an env URL override
```

### 5.3 `ensure_coral_schema(engine, db_uri)` (sketch)

```python
_ensured: set[str] = set()            # custom-lint: disable-next=workspace-scoped-cache -- keyed by database URI
_lock = threading.Lock()

def ensure_coral_schema(engine: Engine, db_uri: str) -> None:
    uri = normalize_database_url(db_uri)                       # utils.py:202
    if uri in _ensured:
        return
    with _lock:
        if uri in _ensured:
            return
        if engine.dialect.name == "cloudflare_d1":             # same refusal as sqlalchemy_store.py:1186-1194
            raise NotImplementedError("Coral needs multi-statement transactions; D1 is unsupported.")
        head = _coral_head(uri)                                # ScriptDirectory.get_current_head(); raises on >1 head
        current = _current_coral_revision(engine)             # None if coral_alembic_version absent
        _verify_coral_revision_supported(uri, current, head)  # copy of utils.py:745-765 ("newer than this build")
        if current != head:
            _run_coral_migrations(engine, uri)                 # CRDB: _crdb_server_version + _prepare_crdb_schema_transaction
            if _current_coral_revision(engine) != head:        # first; never create_all afterwards (C18)
                raise RuntimeError("Coral migration did not reach head …")
        _ensured.add(uri)

def _current_coral_revision(engine):
    if "coral_alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as c:
        return MigrationContext.configure(c, opts={"version_table": "coral_alembic_version"}).get_current_revision()
```

Ordering contract:
1. `engine = get_or_create_engine(db_uri)` brings Omnigent to head (`utils.py:462-486`).
2. `ensure_coral_schema(engine, db_uri)`.

Every Coral store constructor does both, as Omnigent stores do step 1 (`project_store/sqlalchemy_store.py:163`).

On CockroachDB, Coral **replays** its own chain. Unlike Omnigent, it has no historical Postgres-only chain to bootstrap around. Every Coral migration must be CockroachDB-safe:
- no `CREATE INDEX CONCURRENTLY`;
- no partial indexes (MySQL lacks them too);
- no `server_default` functions.

Run the upgrade on one connection after `_prepare_crdb_schema_transaction(connection, version)`, exactly as `utils.py:598-613` does.

### 5.4 CLI and deploy

- Add a `coral db-upgrade URL` command, or `omnigent debug coral-db-upgrade URL`, mirroring `cli.py:12770-12795`.
- Add `run_coral_migrations_with_retry` to deploy entrypoints next to `deploy/databricks/src/app.py:222-228` (P-S7).

### 5.5 Seams S30 and S31, and the upstream merge rehearsal

- **S30** (authoring safety only). Add an `include_name` callback to Omnigent's `env.py` (`omnigent/db/migrations/env.py:51-56, 85-89`) that returns `False` for `coral_*` tables and for `coral_alembic_version`. Without it, `alembic revision --autogenerate` in the Omnigent lineage would propose dropping the Coral tables. Runtime `upgrade` is unaffected, because `command.upgrade` never diffs metadata.
- **S31.** Change `tests/conftest.py:736` from `t != "alembic_version"` to `not t.endswith("alembic_version")`, so per-test truncation keeps Coral's version row. Recommended extension (P-S8): exclude `coral_*` from the root truncation and let `tests/stores/coral/conftest.py` and `tests/db/coral/conftest.py` clean Coral tables. Otherwise every non-Coral test on the Postgres and MySQL lanes truncates about 26 more tables once a worker has created them (MySQL `TRUNCATE` is DDL-like; **UNVERIFIED** magnitude).
- **Upstream merge rehearsal** (DD§7.3.6, endorsed). This is a fork-only workflow. For each new upstream tag:
  1. trial-merge into a scratch branch;
  2. on SQLite, Postgres and CockroachDB, create a DB at the previous fork release (Omnigent head plus Coral head) with seeded Coral rows;
  3. boot through `get_or_create_engine` and then `ensure_coral_schema`;
  4. assert that Coral rows survive;
  5. run `tests/db/coral`, `tests/stores/coral` and the `coral.omni` contract tests.

  This catches future upstream migrations that might touch unknown tables. None do today: I found no migration that iterates `inspector.get_table_names()` generically.

---

## 6. Proposed `coral_*` schema (DDL-level)

### 6.1 Shared Coral column conventions

```python
# coral/db/types.py — Proposed
from sqlalchemy import BigInteger, LargeBinary, String
from sqlalchemy.dialects.mysql import BINARY as MySQLBinary, VARCHAR as MySQLVarchar
from omnigent.db.compression import CompressedText
from omnigent.db.db_models import Uuid16, current_workspace_id      # Reuse

CAPPED_BLOB = CompressedText(max_stored_bytes=16_383)                 # BP:212-216 (C4)
CKSUM32 = LargeBinary(32).with_variant(MySQLBinary(32), "mysql")      # as db_models.py:48
def ident(n: int):                                                    # case-sensitive ids on MySQL (db_models.py:1692-1697)
    return String(n).with_variant(MySQLVarchar(n, charset="utf8mb4", collation="utf8mb4_bin"), "mysql")
# workspace_id: mapped_column(BigInteger, primary_key=True, nullable=False, default=current_workspace_id)  # no server_default (C2)
```

- **Types.**
  - All ids are `Uuid16`.
  - All times are `BigInteger` epoch seconds; `*_us` columns are microseconds.
  - Money is `*_usd_micros BigInteger`; ratios are `*_bp SmallInteger` (0-10,000).
  - Enums are `SmallInteger` with a `CHECK (col IN (…))` named `ck_<table>_<col>`.
- **Identifiers** (node, arrow, profile and workflow keys) are validated slugs `[a-z0-9][a-z0-9_.-]*`. That avoids MySQL PAD-SPACE and case problems; columns use `ident(n)`.
- **Free-text** user input uses app validation in `coral/db/bounds.py`, plus a SQLite-family byte CHECK (pattern at `db_models.py:731-736`).
- **Paths** use `String(2048)` (≤ 8,192 bytes), as Omnigent does for `workspace` (`db_models.py:690, 1607`).
- **Large or unbounded content** (reports, YAML, compiled graphs, structured test results, request text) goes to the artifact store. Rows keep `*_ref String(512)` and are recorded in `coral_blob_refs` (T15).
- **Derived ids** (`coral/db/ids.py`): `derived_id(ns, *parts) = sha256(f"{ns}:" + "\0".join(parts))[:32]`, the same shape as `utils.py:1144-1146`. The derivation of each table's id is listed below.

### 6.2 Table catalogue by phase

| # | Table | Phase | Why it exists (beyond DD§7.2) |
|---|---|---|---|
| T1 | `coral_workflows` | 1 | Library row for the `/workflows` list (server cannot scan host files, DD§14.4); mutable pointer to the latest version |
| T2 | `coral_workflow_versions` | 1 | DD§7.2; content-addressed, immutable |
| T3 | `coral_runs` | 1 | DD§7.2, kept **narrow and hot** (CAS row) |
| T4 | `coral_run_specs` | 1 | Vertical split of cold start-time config (BP:115-121); keeps T3 under 20 columns |
| T5 | `coral_activations` | 1 | DD§7.2, with the derived id replacing the string unique key |
| T6 | `coral_join_arrivals` | 1 | DD§7.2, natural PK per (target activation, arrow) |
| T7 | `coral_run_counters` | 1 | Loop-pass and repeat counters per scope (DD§5.3.3-5); carried over by stable id on amendment. **Optional**: counters could be derived from scope keys. |
| T8 | `coral_handoffs` | 1 | DD§7.2 |
| T9 | `coral_handoff_items` | 1 | Repeated values belong in a child table (BP:306); stable item ids drive repeat-for-each scope keys |
| T10 | `coral_gate_visits` | 1 | DD§7.2, with a denormalized owner for an inbox index |
| T11 | `coral_timers` | 1 | DD§6.6 |
| T12 | `coral_effects` | 1 | DD§6.1 outbox |
| T13 | `coral_run_log` | 1 | DD§7.2 |
| T14 | `coral_simulation_cases` | 1 | D§8: saved simulations run on every workflow change |
| T15 | `coral_blob_refs` | 1 | Artifact ledger: the `ArtifactStore` has no list (§2.8), so GC and purge need one |
| T16 | `coral_agent_slots` | 1 (rows without sessions) / 2 | DD§7.2. In phase 1 the rows exist without sessions, because handoffs are submitted through the API or Simulate. |
| T17 | `coral_session_bindings` | 2 | O(1) "is this session run-owned?" on the S1 hot path; refresh lineage; Elephant-Goldfish persistent sessions (D4) |
| T18 | `coral_signals` | 2 | DD§7.2, revised (deleted on apply, digest-keyed) |
| T19 | `coral_profiles` | 2 | Profiles desk library (UI§8.3), **if** profiles are server objects (open question Q1) |
| T20 | `coral_profile_revisions` | 2 | Immutable pinned revision with a Coral-owned bundle copy (R13, F40) |
| T21 | `coral_version_profile_pins` | 2 | Version-to-revision child table; reverse lookup for GC |
| T22 | `coral_alerts` | 2 / 5 | Paginated per-user alert list for the inbox `workflow` kind (S37). Optional. |
| T23 | `coral_repositories` | 3 | Per-repository identity, setup command and pattern confirmation (D§6.1, DD§13) |
| T24 | `coral_repo_command_patterns` | 3 | D§6.1 command patterns, one row per pattern |
| T25 | `coral_command_observations` | 3 | DD§7.2, DD§9.2 |
| T26 | `coral_amendments` | 7 | DD§7.2, DD§6.8 |

The decision-request state machine (DD§6.2) is folded into T5, T11 and T13; it gets no table. Rule translations live in the YAML and are covered by the version's content hash (DD§10, line 1118); they get no table either.

### 6.3 Table specifications

All tables:
- belong to `CoralBase`;
- have `workspace_id BigInteger NOT NULL` as the first PK column, Python default only;
- have no FKs;
- get all enum CHECKs named;
- get index names prefixed `ix_coral_` and unique names prefixed `uq_coral_`.

Abbreviations: **NN** = NOT NULL, **N** = nullable.

#### T1 `coral_workflows`
- **PK** `(workspace_id, id Uuid16)`. `id = derived_id("coral-workflow", owner or "", workflow_key)`. The PK enforces one workflow per owner and key, with no NULL-owner hole.
- **Columns**:
  - `user_id String(128) N`, `account_generation String(32) N`
  - `workflow_key ident(128) NN`, `name String(256) NN`, `description CAPPED_BLOB N`
  - `source_kind SmallInteger NN` (repo_file=1, uploaded=2, template=3)
  - `source_host_id Uuid16 N`, `source_repo_path String(2048) N`, `source_file_path String(1024) N`
  - `latest_version_id Uuid16 N`, `layout_ref String(512) N` (current canvas layout; layout is not part of the semantic content hash)
  - `created_at BigInteger NN`, `updated_at BigInteger N`
- **Indexes**: `ix_coral_workflows_owner (workspace_id, user_id, created_at, id)`, for listing with backward traversal for newest first.
- **Writes**: upsert on save or import; set `latest_version_id`. Hard delete only when no non-terminal runs reference the workflow (check through T3's `ix_coral_runs_workflow`).

#### T2 `coral_workflow_versions` (immutable)
- **PK** `(workspace_id, id)`. `id = derived_id("coral-version", workflow_id, content_hash.hex())`, so the same content yields the same row (idempotent save).
- **Columns**:
  - `workflow_id Uuid16 NN`
  - `content_hash CKSUM32 NN` (sha256 of the canonical YAML, including confirmed translations and inlined blocks)
  - `yaml_ref String(512) NN`, `yaml_bytes Integer NN`
  - `compiled_ref String(512) NN`, `compiler_version SmallInteger NN`
  - `origin SmallInteger NN` (saved=1, amendment=2, imported=3, template=4)
  - `parent_version_id Uuid16 N` (first-seen lineage, informational)
  - `source_commit String(64) N`, `source_dirty Boolean N`
  - `validation_state SmallInteger NN` (valid=1, invalid=2), `diagnostics_ref String(512) N`
  - `command_patterns_hash CKSUM32 N` (phase 3: snapshot of T24 used for evidence)
  - `created_by String(128) N`, `created_at BigInteger NN`
- **Indexes**: `ix_coral_workflow_versions_workflow (workspace_id, workflow_id, created_at, id)`.
- **Writes**: insert-or-ignore only. The store exposes **no update method**.

#### T3 `coral_runs` (hot)
- **PK** `(workspace_id, id)`. `id = derived_id("coral-run", owner or "", start_key)` when the caller gives a `start_key` (idempotent "Run", C8); otherwise `uuid4().hex`.
- **Columns** (17):
  - `workflow_id Uuid16 NN`, `version_id Uuid16 NN` (pinned; changes only through T26)
  - `user_id String(128) N`, `account_generation String(32) N`
  - `status SmallInteger NN` (starting=1, running=2, paused=3, completed=4, failed=5, cancelled=6)
  - `pause_reason SmallInteger N` (gate=1, budget=2, plan_limit=3, rejected_calls=4, infra=5, liveness=6, user=7, authority_revoked=8, merge_conflict=9, failure_path=10)
  - `version BigInteger NN` (CAS), `next_log_seq BigInteger NN`
  - `activation_count Integer NN` (cap check, DD§5.3.3b)
  - `orchestrator_session_id Uuid16 N` (for display)
  - `title String(256) NN`
  - `spent_usd_micros BigInteger N`, `spent_tokens BigInteger N` (last engine-computed tree spend, DD§12)
  - `created_at BigInteger NN`, `updated_at BigInteger NN`, `finished_at BigInteger N`
- **Indexes**:
  - `ix_coral_runs_owner (workspace_id, user_id, created_at, id)`: "my runs"
  - `ix_coral_runs_workflow (workspace_id, workflow_id, created_at, id)`: history per workflow, and the delete guard
  - `ix_coral_runs_active (status, workspace_id, id)`: cross-workspace periodic resync of running and paused runs (C1)
  - `ix_coral_runs_version (workspace_id, version_id, id)`: amendment and GC checks
- **Writes**: only `apply_transition` (CAS) and `start_run`.

#### T4 `coral_run_specs` (cold)
- **PK** `(workspace_id, run_id)`.
- **Columns**:
  - `start_key ident(256) N`
  - `request_preview String(512) NN`, `request_ref String(512) N`
  - `trigger_kind SmallInteger NN` (manual=1, api=2, schedule=3, webhook=4)
  - `execution_target SmallInteger NN` (connected_host=1, managed_sandbox=2; same codes as `enum_codecs.py` `SCHEDULED_TASK_EXECUTION_TARGET`)
  - `host_id Uuid16 N`, `repository_id Uuid16 N`
  - `repo_path String(2048) N`, `worktree_path String(2048) N`
  - `base_ref String(255) N`, `base_commit String(64) N`, `run_branch String(255) N` (scheme `coral/<run>/base`, DD§13)
  - `auth_mode SmallInteger NN` (subscription=1, api_key=2, mixed=3)
  - `credential_ref String(256) N`: an **opaque reference only**. Secrets stay in Omnigent's `CredentialStore` (`omnigent/stores/credential_store/__init__.py:1-25`) or in the host environment. Whether that store works without KMS or Vault in local mode is **UNVERIFIED**.
  - `budget_usd_micros BigInteger N`, `budget_tokens BigInteger N`
  - `max_activations Integer NN`
  - `refresh_threshold_bp SmallInteger NN` (Draft 4 default 7000, D§7.5)
  - `rejected_call_limit SmallInteger NN` (default 3, D§7.3)
  - `created_at BigInteger NN`
- **Writes**: insert at start; rare updates (worktree path after creation).

#### T5 `coral_activations`
- **PK** `(workspace_id, run_id, id)`. `id = derived_id("coral-activation", run_id, node_id, scope_key)`, which makes uniqueness per scope a PK invariant (C7).
- **Columns**:
  - `node_id ident(64) NN`
  - `scope_key ident(512) NN`: canonical `item_path/iteration_path` (DD§5.3.4); `""` at the root. Depth is bounded by the validator.
  - `parent_activation_id Uuid16 N`
  - `status SmallInteger NN` (waiting_join=1, ready=2, starting=3, running=4, evaluating=5, closed=6, restarting=7, taken_over=8, paused=9)
  - `outcome SmallInteger N` (done=1, blocked=2, failed=3, skipped=4, cancelled=5, superseded=6, at_limit=7)
  - `attempt SmallInteger NN`, `max_attempts SmallInteger NN`
  - `chosen_label ident(128) N`
  - `taken_over_by String(128) N`
  - `start_commit String(64) N`, `start_fingerprint CKSUM32 N`
  - `items_total Integer N`, `items_closed Integer N` (the "3 of 10" badge)
  - `created_at BigInteger NN`, `started_at BigInteger N`, `closed_at BigInteger N`, `updated_at BigInteger NN`
- **Indexes**:
  - `ix_coral_activations_status (workspace_id, run_id, status, id)`: load the open activations for reducer state. This is bounded by the open count, not by the configurable cap (BP:79-81).
  - `ix_coral_activations_created (workspace_id, run_id, created_at, id)`: paginated run-view listing.
- **Do not store the node kind.** The taxonomy debate (D3) stays in the compiled graph.

#### T6 `coral_join_arrivals`
- **PK** `(workspace_id, run_id, activation_id, arrow_id ident(64))`: exactly one arrival per incoming arrow per target scope.
- **Columns**: `source_activation_id Uuid16 NN`, `handoff_id Uuid16 N`, `outcome SmallInteger NN` (delivered=1, failed=2, skipped=3; the last two cover in-region failure and dead-path elimination, DD§5.3.6), `arrived_at BigInteger NN`.
- **Reads**: PK prefix per target activation, for the arity check.

#### T7 `coral_run_counters` (optional)
- **PK** `(workspace_id, run_id, id)`. `id = derived_id("coral-counter", run_id, kind, subject_id, scope_key)`.
- **Columns**: `kind SmallInteger NN` (loop_pass=1, repeat_started=2, repeat_closed=3), `subject_id ident(64) NN` (back-arrow or group id), `scope_key ident(512) NN`, `value Integer NN`, `updated_at BigInteger NN`.
- **Reads**: point gets by derived id, inside the transition.

#### T8 `coral_handoffs`
- **PK** `(workspace_id, run_id, id)`, random.
- **Columns** (19):
  - `activation_id Uuid16 NN`, `slot_id Uuid16 N` (N = API, Simulate or user hand-back)
  - `attempt SmallInteger NN`
  - `status SmallInteger NN` (accepted=1, rejected=2, superseded=3), `submit_status SmallInteger NN` (done=1, blocked=2)
  - `label ident(128) N`, `item_count Integer N`
  - `summary CAPPED_BLOB N`, `report_ref String(512) N`, `report_bytes Integer N`
  - `blocked_reason CAPPED_BLOB N`
  - `evidence_outcome SmallInteger N` (passed=1, failed=2, unknown=3, not_required=4), `evidence_ref String(512) N`
  - `rejection_code SmallInteger N` (missing_report=1, missing_label=2, invalid_label=3, missing_items=4, not_active=5, evidence_missing=6), `rejection_message CAPPED_BLOB N`
  - `idempotency_cksum CKSUM32 NN` (sha256 of `tool:{session}:{call}` or a client key, DD§7.2)
  - `submitted_by_session_id Uuid16 N`, `submitted_at_us BigInteger NN`
- **Unique**: `uq_coral_handoffs_idempotency (workspace_id, run_id, idempotency_cksum)`. This is **run-scoped**, so a duplicate submitted after a session refresh is still caught (DD§6.3).
- **Indexes**: `ix_coral_handoffs_activation (workspace_id, run_id, activation_id, submitted_at_us, id)`.

#### T9 `coral_handoff_items`
- **PK** `(workspace_id, run_id, handoff_id, item_index Integer)`. Paginate by `item_index`.
- **Columns**: `item_key ident(128) NN` (stable item id, DD§5.3.5), `title String(512) NN`, `payload CAPPED_BLOB N`, `payload_ref String(512) N`.
- **Bound**: the validator and the tool schema cap the list length; reads always page.

#### T10 `coral_gate_visits`
- **PK** `(workspace_id, run_id, id)`. `id = derived_id("coral-gate", activation_id, str(visit_no))`.
- **Columns**:
  - `activation_id Uuid16 NN`, `node_id ident(64) NN`, `visit_no Integer NN`
  - `owner_user_id String(128) N`: denormalized, immutable copy of the run owner
  - `token Uuid16 NN` (random; answers must echo it, DD§6.2)
  - `elicitation_id String(64) N` (Omnigent format `elicit_<32hex>`, `orchestration.py:529`), `elicitation_session_id Uuid16 N`
  - `status SmallInteger NN` (open=1, resolved=2, superseded=3, cancelled=4)
  - `prompt_ref String(512) N`
  - `answer_label ident(128) N`, `answered_by String(128) N`, `note CAPPED_BLOB N`
  - `opened_at BigInteger NN`, `reminded_at BigInteger N`, `resolved_at BigInteger N`
- **Indexes**:
  - `ix_coral_gate_visits_inbox (workspace_id, owner_user_id, status, opened_at, id)`
  - `ix_coral_gate_visits_open (status, workspace_id, run_id, id)`: cross-workspace re-publish after a restart

#### T11 `coral_timers`
- **PK** `(workspace_id, run_id, id)`. `id = derived_id("coral-timer", run_id, kind, subject, scope_key, generation)`.
- **Columns**:
  - `kind SmallInteger NN` (watchdog_remind=1, watchdog_escalate=2, gate_remind=3, overdue_alert=4, plan_limit_resume=5, wait_node=6, deferred_refresh=7, effect_retry=8, liveness_check=9)
  - `subject_id Uuid16 N` (activation, slot or gate)
  - `state SmallInteger NN` (armed=1, fired=2, cancelled=3)
  - `due_at BigInteger NN`, `fired_at BigInteger N`, `created_at BigInteger NN`
- **Indexes**: `ix_coral_timers_due (state, due_at, workspace_id, run_id, id)`.
- **Firing**: no lease. The scanner hands `timer_due` to `reconcile(run)`, which marks it fired inside the same CAS transaction. Fired and cancelled rows are deleted in that transition; the audit lives in T13.

#### T12 `coral_effects` (outbox)
- **PK** `(workspace_id, run_id, id)`. `id = derived_id("coral-effect", run_id, effect_key)`.
- **Columns**:
  - `kind SmallInteger NN` (create_session=1, send_input=2, interrupt=3, stop_session=4, attach_policies=5, publish_gate=6, withdraw_gate=7, create_worktree=8, merge_branches=9, run_check=10, notify=11, refresh_session=12, fingerprint=13, push_checkpoint=14)
  - `status SmallInteger NN` (pending=1, claimed=2, succeeded=3, failed=4, abandoned=5)
  - `owner_key String(64) N`: the `owned_hosts` routing key, either host-id hex or the workspace id in decimal (`scheduled/README.md:449-458`)
  - `payload CAPPED_BLOB NN` (versioned JSON envelope, BP:312-316)
  - `attempts SmallInteger NN`, `available_at BigInteger NN`
  - `lease_expires_at BigInteger N`, `lease_holder String(64) N`
  - `result CAPPED_BLOB N`, `result_ref String(512) N`, `error_code String(64) N`
  - `created_at_us BigInteger NN`, `finished_at BigInteger N`
- **Indexes**:
  - `ix_coral_effects_ready (status, available_at, workspace_id, run_id, id)`
  - `ix_coral_effects_expired (status, lease_expires_at, workspace_id, run_id, id)`: same shape as `db_models.py:1739-1745`
- **Idempotency of external calls**:
  - `create_session` uses a derived conversation id, `derived_id("coral-session", slot_id, generation)`, through P-S5. Recovery is then a PK get on `conversations` (C5).
  - `send_input` and the brief use a stable uuid5 item id, following the startup-input precedent (`omnigent/server/startup_inputs.py:13`, imports `uuid5`).

#### T13 `coral_run_log` (append-only)
- **PK** `(workspace_id, run_id, seq BigInteger)`. `seq` comes from `coral_runs.next_log_seq` under the run lock.
- **Columns**:
  - `run_version BigInteger NN`
  - `kind SmallInteger NN` (run_started, activation_started, handoff_submitted, handoff_rejected, evidence_result, decision, gate_opened, gate_answered, arrow_taken, timer_fired, effect_succeeded, effect_failed, paused, resumed, amendment_applied, signal_ignored, take_over, hand_back, alert, run_finished, command_rejected, …; codes append-only)
  - `audit_only Boolean NN`
  - `actor_kind SmallInteger NN` (engine=1, orchestrator=2, step_agent=3, user=4, simulator=5), `actor_ref String(128) N`
  - `activation_id Uuid16 N`
  - `idempotency_cksum CKSUM32 N`
  - `body CAPPED_BLOB NN` (versioned envelope; never filtered in SQL), `body_ref String(512) N`
  - `created_at_us BigInteger NN`
- **Unique**: `uq_coral_run_log_idempotency (workspace_id, run_id, idempotency_cksum)`. The column is nullable, so only keyed rows are constrained; NULLs are distinct on all four backends.
- **Indexes**: `ix_coral_run_log_activation (workspace_id, run_id, activation_id, seq)`, for "why was this arrow taken".
- **Stream**: `GET /v1/workflow-runs/{id}/stream` resumes from a `seq` cursor (DD§14.2) using a PK range scan.

#### T14 `coral_simulation_cases`
- **PK** `(workspace_id, id)`, random.
- **Columns**:
  - `workflow_id Uuid16 NN`, `name String(256) NN`
  - `script CAPPED_BLOB NN` (scripted inputs), `expectation CAPPED_BLOB N`
  - `last_version_id Uuid16 N`, `last_result SmallInteger N` (passed=1, failed=2, error=3), `last_run_at BigInteger N`, `last_report_ref String(512) N`
  - `created_by String(128) N`, `created_at BigInteger NN`, `updated_at BigInteger N`
- **Indexes**: `ix_coral_simulation_cases_workflow (workspace_id, workflow_id, created_at, id)`.
- Open question Q2: should cases also export to the repository as files?

#### T15 `coral_blob_refs` (artifact ledger)
- **PK** `(workspace_id, scope_id Uuid16, key_cksum CKSUM32)`. The scope is a run, workflow or profile id.
- **Columns**: `scope_kind SmallInteger NN` (run=1, workflow=2, profile=3, simulation=4), `artifact_key String(512) NN`, `bytes BigInteger NN`, `content_sha256 CKSUM32 NN`, `created_at BigInteger NN`.
- **Purpose**: bounded GC and purge without listing the artifact store (§7).

#### T16 `coral_agent_slots`
- **PK** `(workspace_id, run_id, id)`. `id = derived_id("coral-slot", activation_id, str(roster_index))`.
- **Columns** (18):
  - `activation_id Uuid16 NN`, `roster_index SmallInteger NN`
  - `role SmallInteger NN` (step_agent=1, orchestrator=2, verifier=3, merge_resolver=4)
  - `profile_revision_id Uuid16 N`
  - `session_id Uuid16 N` (current), `session_generation SmallInteger NN`
  - `status SmallInteger NN` (pending=1, session_created=2, briefed=3, working=4, handoff_accepted=5, rejected=6, refreshing=7, restarting=8, closed=9)
  - `lease_expires_at BigInteger N`, `lease_holder String(64) N` (startup lease, `StartupLease` discipline, DD§6.2)
  - `branch String(255) N`, `worktree_path String(2048) N`
  - `last_turn_origin SmallInteger N` (engine=1, user=2; the nudge rule, DD§6.4)
  - `nudges SmallInteger NN`, `consecutive_rejections SmallInteger NN` (an O(1) counter, so the log is not scanned)
  - `context_used_bp SmallInteger N`
  - `created_at BigInteger NN`, `updated_at BigInteger NN`
- **Indexes**:
  - `ix_coral_agent_slots_activation (workspace_id, run_id, activation_id, roster_index, id)`
  - `ix_coral_agent_slots_expired (status, lease_expires_at, workspace_id, run_id, id)`: startup-lease recovery

#### T17 `coral_session_bindings`
- **PK** `(workspace_id, session_id Uuid16)`.
- **Columns**: `run_id Uuid16 NN`, `slot_id Uuid16 NN`, `role SmallInteger NN`, `generation SmallInteger NN`, `state SmallInteger NN` (active=1, superseded=2, released=3), `superseded_by_session_id Uuid16 N`, `bound_at BigInteger NN`, `released_at BigInteger N`.
- **Indexes**: `ix_coral_session_bindings_run (workspace_id, run_id, slot_id, generation, session_id)`.
- **Uses**:
  - The S1 observer and the TOOL_CALL intercept resolve session → run with one PK get. Non-Coral sessions miss cheaply.
  - Refresh and rotation history: native `/clear` session-id rotation (R12).
  - D4 persistent sessions: rebind `slot_id` across loop passes.

#### T18 `coral_signals`
- **PK** `(workspace_id, id)`. `id = derived_id("coral-signal", idempotency_key)`, for example `turn:{session}:{response_id}` or `item:{thread}:{turn}:{item}` (DD§7.2), so dedup is a PK conflict.
- **Columns**:
  - `run_id Uuid16 NN` (resolved through T17 before insert; unbound sessions insert nothing)
  - `session_id Uuid16 N`
  - `kind SmallInteger NN` (turn_ended=1, runner_lost=2, usage_limit=3, context_threshold=4, tool_result=5, elicitation_resolved=6, session_deleted=7, external_event=8)
  - `payload CAPPED_BLOB N` (for example `resets_at`)
  - `status SmallInteger NN` (pending=1, claimed=2)
  - `available_at BigInteger NN`, `lease_expires_at BigInteger N`, `created_at_us BigInteger NN`
- **Indexes**:
  - `ix_coral_signals_ready (status, available_at, workspace_id, id)`
  - `ix_coral_signals_run (workspace_id, run_id, status, id)`
- **Lifecycle**: inserted with insert-or-ignore (dialect upsert, §2.6). Reconcile claims the signals per run, applies them in the run's CAS transaction, and **deletes** them in the same transaction. Signals are hints and reconcile is level-triggered (DD§6.4), so the table stays small and duplicates that arrive after deletion are harmless.

#### T19 `coral_profiles`
- **PK** `(workspace_id, id)`. `id = derived_id("coral-profile", owner or "", profile_key)`.
- **Columns**: `user_id String(128) N`, `account_generation String(32) N`, `profile_key ident(128) NN`, `name String(256) NN`, `description CAPPED_BLOB N`, `source_kind SmallInteger NN` (repo_file=1, installed_agent=2, builtin=3), `agent_id Uuid16 N` (Omnigent `agents.id`), `latest_revision_id Uuid16 N`, `created_at BigInteger NN`, `updated_at BigInteger N`.
- **Indexes**: `ix_coral_profiles_owner (workspace_id, user_id, created_at, id)`.

#### T20 `coral_profile_revisions` (immutable)
- **PK** `(workspace_id, id)`. `id = derived_id("coral-profile-rev", profile_id, content_hash.hex())`.
- **Columns**:
  - `profile_id Uuid16 NN`, `content_hash CKSUM32 NN`
  - `agent_bundle_ref String(512) NN`: a **Coral-owned copy**, because reinstall updates agents in place (`designs/REUSABLE_USER_AGENTS.md:112`)
  - `agent_bundle_sha256 CKSUM32 NN`
  - `harness ident(64) NN`, `model String(128) N`
  - `expected_capabilities CAPPED_BLOB N`, `default_rules_ref String(512) N`
  - `auth_mode SmallInteger N`
  - `created_by String(128) N`, `created_at BigInteger NN`
- **Indexes**: `ix_coral_profile_revisions_profile (workspace_id, profile_id, created_at, id)`.

#### T21 `coral_version_profile_pins`
- **PK** `(workspace_id, version_id, profile_key ident(128))`.
- **Columns**: `profile_revision_id Uuid16 NN`.
- **Indexes**: `ix_coral_version_profile_pins_revision (workspace_id, profile_revision_id, version_id, profile_key)`, used by GC to ask "is this revision still pinned".

#### T22 `coral_alerts` (optional)
- **PK** `(workspace_id, id)`.
- **Columns**: `run_id Uuid16 NN`, `owner_user_id String(128) N`, `kind SmallInteger NN` (watchdog_escalation=1, overdue=2, paused=3, gate_waiting=4, rejected_calls=5, authority_revoked=6), `status SmallInteger NN` (open=1, acknowledged=2, resolved=3), `message String(1024) NN`, `created_at BigInteger NN`, `resolved_at BigInteger N`.
- **Indexes**: `ix_coral_alerts_inbox (workspace_id, owner_user_id, status, created_at, id)`.

#### T23 `coral_repositories`
- **PK** `(workspace_id, id)`. `id = derived_id("coral-repo", owner or "", canonical_repo_key)`, where the key is the normalized remote URL, or `host_id:path`.
- **Columns**: `user_id String(128) N`, `display_name String(256) NN`, `remote_url String(2048) N`, `host_id Uuid16 N`, `repo_path String(2048) N`, `setup_command CAPPED_BLOB N` (DD§13 per-worktree setup), `patterns_hash CKSUM32 N`, `patterns_confirmed_by String(128) N`, `patterns_confirmed_at BigInteger N`, `created_at BigInteger NN`, `updated_at BigInteger N`.
- **Indexes**: `ix_coral_repositories_owner (workspace_id, user_id, created_at, id)`.

#### T24 `coral_repo_command_patterns`
- **PK** `(workspace_id, repository_id, id)`.
- **Columns**: `kind SmallInteger NN` (test=1, lint=2, format_check=3, typecheck=4, build=5, other=6), `matcher_kind SmallInteger NN` (argv_prefix=1, regex=2), `matcher String(1024) NN`, `cwd_glob String(512) N`, `origin SmallInteger NN` (detected=1, author=2), `detected_from String(512) N` (for example `package.json#scripts.test`), `state SmallInteger NN` (proposed=1, confirmed=2, rejected=3), `created_at BigInteger NN`, `updated_at BigInteger N`.
- **Reads**: PK prefix per repository, paginated.

#### T25 `coral_command_observations`
- **PK** `(workspace_id, run_id, id)`. `id = derived_id("coral-obs", session_id, call_or_item_id)`, so re-delivery is idempotent.
- **Columns** (17):
  - `activation_id Uuid16 NN`, `slot_id Uuid16 NN`, `session_id Uuid16 NN`
  - `source SmallInteger NN` (sys_os_tool=1, codex_item=2, native_transcript=3, native_hook_hint=4, coral_check=5)
  - `session_item_id Uuid16 N`, `external_item_id String(128) N`
  - `command CAPPED_BLOB NN`, `cwd String(2048) N`
  - `exit_code Integer N`, `exit_status_source SmallInteger N` (exit_code=1, is_error=2, unknown=3; DD§9.1)
  - `matched_pattern_id Uuid16 N`, `pattern_kind SmallInteger N`
  - `fingerprint_before CKSUM32 N`, `fingerprint_after CKSUM32 N`
  - `report_ref String(512) N` (structured JUnit or JSON results, DD§9.3)
  - `observed_at_us BigInteger NN`
- **Indexes**: `ix_coral_command_observations_activation (workspace_id, run_id, activation_id, observed_at_us, id)`. This serves "last change", and "did a test command run after it" as a backward scan from the newest row.

#### T26 `coral_amendments`
- **PK** `(workspace_id, run_id, id)`.
- **Columns**: `from_version_id Uuid16 NN`, `to_version_id Uuid16 NN`, `status SmallInteger NN` (proposed=1, applied=2, refused=3), `plan_ref String(512) N` (Simulate from current state), `reason CAPPED_BLOB N`, `requested_by String(128) N`, `applied_by String(128) N`, `run_version_at_apply BigInteger N`, `created_at BigInteger NN`, `applied_at BigInteger N`.
- **Indexes**: `ix_coral_amendments_run (workspace_id, run_id, created_at, id)`.

### 6.4 Bounds and deletion

- **Every run child table** (T4-T13, T16, T25, T26) has `run_id` as the second PK column. `purge_run` therefore deletes by `(workspace_id, run_id)` prefix in bounded batches of about 500 rows per transaction, per table. Order: delete the artifacts recorded in T15 first, then the rows. T17 rows are deleted through `ix_coral_session_bindings_run`; T18 rows through `ix_coral_signals_run`.
- **Owned-row cleanup on account deletion.** Omnigent's `_revoke_durable_authority` (`omnigent/server/accounts_store.py:75-149`) and `_carry_registration_work` (`155-185`) list Omnigent tables explicitly. Coral rows are **not** covered (P-S6).
- **Index counts** stay at or below 3 per table (BP:190-194 flags more than 10). Column counts stay at or below 20 (BP:236-238). T3 has 17 and T4 has 20.

---

## 7. Artifact storage plan

- **Store.** Reuse Omnigent's `ArtifactStore` instance: the one passed to `create_app` (`cli.py:4920`; `app.py:1567`) or `omnigent.runtime.get_artifact_store()` (`runtime/__init__.py:96-106`). There is no new storage service, which meets BP:50-62.
- **Key scheme** (New). Keys are workspace-prefixed, because the artifact store is global while Coral's derived ids are unique only per workspace:
  - `coral/v1/{workspace_id}/workflows/{workflow_id}/{sha256}.yaml` and `.compiled.json`
  - `coral/v1/{workspace_id}/runs/{run_id}/{kind}/{sha256}`, where kind is one of `request`, `report`, `items`, `evidence`, `junit`, `body`, `plan`, `diag`
  - `coral/v1/{workspace_id}/profiles/{profile_id}/{sha256}.tar.gz` (the bundle copy)
  - Keys satisfy `LocalArtifactStore` validation: forward slashes, no `..` (`local.py:44-70`).
- **Write ordering.** `put` the content-addressed blob first, which is idempotent. Then commit the referencing row together with its T15 ledger row in the same transaction. A failed commit leaves a content-addressed orphan, collected by a periodic ledger-versus-prefix sweep; there is no list API, so orphans with no ledger row are accepted as rare and bounded. Never overwrite a key.
- **Size caps** (application-level, at the tool or API boundary):
  - handoff report ≤ 1 MiB, items ≤ 1,000 per handoff, workflow YAML ≤ 1 MiB, structured test report ≤ 4 MiB;
  - rows keep only a summary (`CAPPED_BLOB`) and the reference.

  `ArtifactStore.put` and `get` load whole blobs into memory (`__init__.py:37-59`), which is why the caps matter.
- **Reading old runs** never depends on the repository: the version's `yaml_ref` and `compiled_ref`, and the profile revisions' bundle copies, are immutable.
- **Encryption-ready.** Reports and request texts may contain proprietary code. They stay opaque (BP:318-337), are never indexed, and only digests appear in the DB.
- **Upstream candidate (optional).** Adding `list_prefix` or `delete_prefix` to the ABC would let Coral drop the orphan sweep. That is **not** required for v1.

---

## 8. Store interfaces per aggregate (Proposed)

Every SQLAlchemy implementation:
- calls `get_or_create_engine(db_uri)` and then `ensure_coral_schema(engine, db_uri)` in `__init__`;
- builds `self._session = make_named_managed_session_maker(engine, query_name_prefix="coral.<store>")` and `self._session_immediate = …(immediate=True)`;
- performs writes through `run_write_transaction(self._session_immediate, "<intent>", write)`;
- returns entities, never ORM rows;
- has paginated list methods that take `after: Cursor | None` and `limit: int` (≥ 1) and use a lifted `_cursor_after` (P-S9);
- requires reads to run inside the caller's `workspace_scope`; worker discovery methods suffixed `_all_workspaces` are the explicit cross-workspace exception, as `list_active_all_workspaces` is (`scheduled_task_store/sqlalchemy_store.py:332`).

Query-name suffixes are listed in brackets.

**`CoralWorkflowStore`** (T1, T2, T14, T21)
- `upsert_workflow(owner, workflow_key, name, source, …) -> Workflow` [`save_workflow`]
- `get_workflow(workflow_id, *, user_id)`, `list_workflows(*, user_id, after, limit)` [`list_workflows`]
- `record_version(workflow_id, content_hash, yaml_ref, compiled_ref, …) -> WorkflowVersion`: idempotent through the derived id [`record_workflow_version`]
- `get_version(version_id)`, `list_versions(workflow_id, after, limit)`
- `set_latest_version(workflow_id, version_id)` [`publish_workflow_version`]
- `delete_workflow(workflow_id, *, user_id)`: refuses while active runs exist [`delete_workflow`]
- Simulation cases: `create_case`, `update_case`, `delete_case`, `list_cases(workflow_id, after, limit)`, `record_case_result`
- `pin_profiles(version_id, pins)`, `list_pins(version_id)`, `list_versions_pinning(revision_id, after, limit)`

**`CoralRunStore`**, the aggregate root (T3-T13, T16, T26)
- `start_run(spec, version_id, initial: Transition) -> Run`: insert-or-return using the derived run id, inside one transaction with the first transition [`start_run`]
- `load_run_state(run_id) -> RunState`: run row, open activations through `ix_coral_activations_status`, their arrivals, slots, counters, open gates and armed timers. Wrapped in `shared_read_scope()` [`load_run_state`].
- `apply_transition(run_id, expected_version, transition) -> int` [`apply_run_transition`]. Steps:
  1. lock-and-recheck the run row with `session.get(..., with_for_update=True)`;
  2. if the version differs, raise `RunVersionConflict`;
  3. otherwise bump `version`;
  4. allocate `seq` values from `next_log_seq`;
  5. upsert state rows;
  6. append T13;
  7. insert T12 and T11;
  8. delete applied T18 and fired T11 rows.

  It calls `require_active_account(session, run.user_id, generation=run.account_generation)` **only for user commands**. Engine work relies on the ambient `account_authority_scope`.
- `get_run`, `list_runs(*, user_id, status=None, after, limit)`, `list_runs_for_workflow(workflow_id, after, limit)`
- `list_active_runs_all_workspaces(after, limit)`: the resync scan [`discover_active_runs`]
- `read_log(run_id, after_seq, limit)` [`read_run_log`]; `find_receipt(run_id, idempotency_cksum) -> LogEntry | None` [`find_command_receipt`]
- `list_activations(run_id, after, limit)`, `list_handoffs(activation_id, after, limit)`, `list_handoff_items(handoff_id, after_index, limit)`
- `list_open_gates(*, user_id, after, limit)` [`list_open_gates`]; `list_open_gates_all_workspaces(after, limit)`, used for re-publish
- `purge_run(run_id, *, batch_size) -> bool`: True while rows remain [`purge_run_batch`]
- Amendments: `propose_amendment(...)` and `list_amendments(run_id, after, limit)`. Applying one goes through `apply_transition`.
- The reduce-and-retry loop lives in `coral/engine/reconcile.py`, outside the store: read state, reduce, apply, and on `RunVersionConflict` re-read and retry up to N times (C14).

**`CoralQueueStore`** (T11, T12, T16 leases, T18)
- Timers: `list_due_timers_all_workspaces(now, after, limit)` [`discover_due_timers`]
- Effects:
  - `list_ready_effects_all_workspaces(now, after, limit)` [`discover_ready_effects`]
  - `claim_effect(effect, *, now, lease_seconds, holder) -> Effect | None`: lock and recheck, as in `sqlalchemy_store.py:1393-1425` [`claim_effect`]
  - `renew_effect_lease(effect_id, *, now, lease_seconds)`: never revives an expired lease, as in `1442-1457` [`renew_effect_lease`]
  - `finish_effect(effect, *, status, result, error_code)`: only while the lease matches, as in `1518-1544` [`finish_effect`]
  - `list_expired_effects_all_workspaces(now, after, limit)` [`discover_expired_effects`]
- Slots: `claim_slot_startup(...)`, `renew_slot_lease(...)`, `list_expired_slot_startups_all_workspaces(now, after, limit)`
- Signals: `enqueue_signal(key, session_id, kind, payload) -> bool`, which resolves the binding first and inserts or ignores [`enqueue_signal`]; `list_ready_signals_all_workspaces(now, after, limit)`; `list_pending_signals(run_id, limit)`. Application and deletion happen through `apply_transition`.

**`CoralSessionBindingStore`** (T17)
- `bind(session_id, run_id, slot_id, role, generation)`; `lookup(session_id) -> Binding | None` [`lookup_session_binding`, the hot path]; `supersede(old_session_id, new_session_id)`; `list_for_run(run_id, after, limit)`.

**`CoralProfileStore`** (T19, T20)
- `upsert_profile`, `get_profile`, `list_profiles(*, user_id, after, limit)`
- `record_revision(profile_id, content_hash, bundle_ref, …)`: idempotent
- `get_revision`, `list_revisions(profile_id, after, limit)`

**`CoralEvidenceStore`** (T23-T25)
- `upsert_repository`, `list_repositories(*, user_id, after, limit)`
- `replace_detected_patterns(repo_id, patterns)`, `confirm_patterns(repo_id, ids, *, by)`, `list_patterns(repo_id, after, limit)`
- `record_observation(obs) -> bool`: idempotent
- `list_observations(run_id, activation_id, after, limit)`; `latest_observation(run_id, activation_id)`, a backward scan with limit 1

**`CoralBlobLedger`** (T15)
- `record(scope_kind, scope_id, artifact_key, bytes, sha)`, `list_for_scope(scope_id, after, limit)`, `delete_for_scope_batch(scope_id, batch)`.

Wiring: a `CoralStores` dataclass, constructed once from `db_uri` and the `artifact_store`, handed to the routers (`extra_routers`) and to the workers (S32 hook). Optionally exposed as `app.state.coral` (P-S4).

---

## 9. Concurrency, queues and workers (persistence view)

- **Per-run serialization.** Lock-and-recheck on the T3 row:
  - Postgres: `FOR UPDATE`;
  - MySQL: row lock;
  - CockroachDB: READ COMMITTED `FOR UPDATE` (`utils.py:362-363`);
  - SQLite: `BEGIN IMMEDIATE`.

  This is preferred to a blind `UPDATE … WHERE version=?` because it also yields `next_log_seq` portably (MySQL has no `RETURNING`). MySQL's affected-row count is safe either way, because `version` always changes.
- **Never hold a transaction across an agent or network call.** Effects run after commit (DD§6.1).
- **SQLite contention** (R10). Every engine write competes with Omnigent's writers for the single writer lock, with a 20 s busy timeout (`utils.py:325, 968`). Keep transactions small: create activations lazily, delete signals on apply. Batch observation inserts per tool result.
- **Multi-replica** requires Postgres or CockroachDB. Refuse SQLite when `host_sharded=True` (`app.py:1602, 1769-1775`), and refuse D1 always. Shard effects by `owner_key` through the same `owned_hosts` callable contract (`dispatch_scheduler.py:924-941`).
- **Duplicates.** The derived-id PKs and digest unique keys are the backstop. The primary dedup is the state check under the run lock, so `IntegrityError` should not occur on hot paths. Where an insert may race (signals from the observer), use the dialect upsert or ignore pattern (`project_store/sqlalchemy_store.py:393-419`), because an `IntegrityError` rolls back the whole managed session (`utils.py:975-977`).
- **Account authority** for durable work:
  - Workers wrap each iteration in `workspace_scope(run.workspace_id)` and `account_authority_scope(run.user_id, run.account_generation)` (`account_authority.py:79-91`).
  - If `require_active_account` raises `UNAUTHORIZED` (`account_authority.py:145-197`), the run pauses with `authority_revoked`. That write runs under `account_checks_scope(False)` (`account_authority.py:36-47`) and records only the pause.
  - Generation rotation on a password change would otherwise strand runs, because scheduled tasks are carried (`accounts_store.py:155-185`) but Coral rows are not (P-S6).

---

## 10. Upstream seams (persistence track) with exact locations

DD seams are confirmed and refined. P-S1 to P-S9 are new and numbered locally to avoid collisions; the roadmap owner should assign global ids.

| Id | Change | Location (verified) | Size | Phase | Upstream candidate |
|---|---|---|---|---|---|
| **S29** | `include = ["omnigent*", "coral*"]`; add `package-data` for `coral.db` (`alembic.ini`) and `coral.db.migrations` (`script.py.mako`) | `pyproject.toml:456-464` | XS | 1 | No |
| **P-S1** (S29 extension) | pyrefly includes `coral/**/*.py`; pre-commit pyrefly `files` regex adds `coral/`; isort `known-first-party += "coral"`; coverage `source += "coral"` | `pyrefly.toml:1-5`; `.pre-commit-config.yaml:32`; `pyproject.toml:625`; `pyproject.toml:539` | XS | 1 | No |
| **S30** | `include_name` filter in Omnigent's env so autogenerate ignores `coral_*` and `coral_alembic_version` | `omnigent/db/migrations/env.py:37, 51-56, 85-89` | XS | 1 | Maybe (generic "ignore foreign tables") |
| **S31** | Keep `*alembic_version` across per-test truncation | `tests/conftest.py:736` | XS | 1 | No |
| **P-S8** (S31 extension) | Exclude `coral_*` from root truncation; Coral fixtures clean their own tables | `tests/conftest.py:734-746` | XS | 1 | No |
| **S39** | Add `"coral/"` to `SCANNED_ROOTS`; CODEOWNERS for `/coral/db/migrations/` and `/coral/db/alembic.ini`; a new import-boundary custom-lint rule registered in `custom_lint.py` | `dev/lint/lint_workspace_scoped_cache.py:40`; `.github/CODEOWNERS:1-6`; `dev/lint/custom_lint.py` `RULES` | XS-S | 1 | No |
| **S32** (owned by another agent; persistence needs) | Startup and shutdown hook in `create_app`: build `CoralStores`, call `ensure_coral_schema`, start workers, stop them on shutdown | `omnigent/server/app.py:1563-1611, 1933` | S | 1 | Yes |
| **P-S4** | CLI wiring: pass `extra_routers` (Coral API), or build Coral stores and routers inside the S32 hook from `permission_store.storage_location` (precedent `app.py:5110`); register the `coral db-upgrade` command | `omnigent/cli.py:4887-4920, 5118-5147`; `cli.py:12770-12795` | S | 1 | No |
| **P-S5** | Caller-supplied conversation id through the request-free session-create path (C5) | Store already supports it: `omnigent/stores/conversation_store/__init__.py:553, 616-618`. Creation path omits it: `omnigent/server/routes/_sessions/orchestration.py:12326-12344`; also `helpers.py:11181-11193`. Pairs with S3. | S | 2 | Yes |
| **P-S6** | Account lifecycle: registered callbacks in `_revoke_durable_authority` and `_carry_registration_work` so Coral can cancel and hard-delete or carry owned runs. v1 alternative: lazy authority checks (§9), no seam. Identity remap also skips Coral (and today skips scheduled tasks and projects too). | `omnigent/server/accounts_store.py:75-149, 155-185, 506, 580`; `omnigent/server/identity_migration.py:19-27, 43-52` | S | 2 / later | Yes |
| **P-S7** | Deploy entrypoints run Coral migrations after Omnigent's | `deploy/databricks/src/app.py:222-228` | XS | 1 | No |
| **P-S9** | Lift `_cursor_after` (keyset with MySQL fallback) to a shared `omnigent/db/pagination.py`; make enum `_encode`/`_decode` public. Alternative: copy them into `coral/db/`. | `omnigent/stores/scheduled_task_store/sqlalchemy_store.py:1040-1063`; `omnigent/db/enum_codecs.py:164-205` | XS | 1 | Yes |
| (test infra) | The server-suite SQLite template also runs `ensure_coral_schema`, if the Coral hook is enabled in server tests | `tests/server/conftest.py:519-547` | XS | 2 | No |

Private Omnigent imports that are acceptable **only inside `coral/db/migrate.py`**, each covered by a contract test:
- `omnigent.db.utils._set_alembic_database_url` (`utils.py:532-534`), `normalize_database_url` (`202`);
- `omnigent.db.cockroachdb._crdb_server_version` (`41-45`), `_prepare_crdb_schema_transaction` (`101-109`);
- `omnigent.db.db_models._on_sqlite_family` (`631-652`).

An optional upstream seam would expose a public `upgrade_alembic_environment(engine, config)` extracted from `utils.py:598-613`.

---

## 11. Test infrastructure plan

All test files are New unless noted.

- `tests/stores/coral/__init__.py` and `conftest.py`:
  - a `coral_db_uri(db_uri)` fixture that calls `ensure_coral_schema(get_or_create_engine(db_uri), db_uri)`;
  - store fixtures;
  - reuse `artifact_store` from `tests/stores/conftest.py:52-57`;
  - on the CockroachDB lane, run the first ensure per worker under the existing DDL lock path (`tests/db/conftest.py:26`, `filelock`);
  - cleanup of `coral_*` tables per P-S8.
- `tests/stores/coral/test_*_store.py`: CRUD, pagination with tie-breakers (model: `tests/stores/test_scheduled_task_store.py:602-674`), `workspace_scope` isolation (model: `test_scheduled_task_store.py:366-395`), and idempotency through derived ids. Concurrency tests go here as well, so they run on the Postgres, CockroachDB and MySQL lanes (C20):
  - CAS conflict between two threads;
  - effect claim races;
  - an expired lease that is not revived;
  - a run-scoped duplicate handoff across a session refresh.
- `tests/db/coral/__init__.py`. Name modules `test_migration_coral_*.py` so they inherit the CockroachDB DDL lock (`tests/db/conftest.py:29-33`):
  - `test_migration_coral_single_head.py`, mirroring `tests/db/test_migration_connections.py:34-37` against the Coral config;
  - `test_migration_coral_round_trip.py`: upgrade, downgrade to base, upgrade, on fresh SQLite (mirrors `test_migrations_sqlite_safe.py:53-84`); assert Omnigent's tables and `alembic_version` are untouched;
  - `test_migration_coral_sqlite_safe.py`: reuse `_raw_unsafe_op_calls` from `tests.db.test_migrations_sqlite_safe` against `coral/db/migrations/versions`;
  - `test_migration_coral_models_match.py`: `alembic.autogenerate.compare_metadata` with `include_name` must return an empty diff, on every lane. This replaces the missing `create_all` safety net (C18).
  - `test_migration_coral_guards.py`: newer-than-build refusal, D1 refusal, ordering (Coral before Omnigent on a fresh CockroachDB DB must fail loudly, not corrupt), and coexistence (Omnigent's `_initialize_or_verify_schema` is a no-op with Coral tables present).
  - `test_coral_schema_conventions.py`: iterate `CoralBase.metadata` and assert:
    - every name starts with `coral_`;
    - `workspace_id` leads every PK, with no `server_default`;
    - there are no FKs;
    - no Text, JSON or Float columns exist;
    - every `CompressedText` has `max_stored_bytes ≤ 16_383`;
    - every `String` length ≤ 4095;
    - all indexes are named and none is DESC;
    - every `SmallInteger` enum column has a CHECK.

    This is a cheap unit test that Omnigent itself lacks.
- `tests/coral/`: the pure reducer, Simulate, and engine fault injection with in-memory or SQLite stores. These are picked up by the `misc` group automatically (`python-matrix.json`).
- **CI**: no change to `ci.yml` is needed for the lanes. Add the fork-only rehearsal workflow (§5.5).
- **Local**: `just crdb-test` already runs `tests/stores tests/db` against the CockroachDB matrix (`justfile:72-73`; `scripts/test_crdb_matrix.sh:16-17`).

---

## 12. Persistence work items (dependency-aware, for the roadmap)

| Id | Item | Depends on | Notes |
|---|---|---|---|
| P1 | Packaging and tooling seams: S29, P-S1, S39 (lint roots, CODEOWNERS, import-boundary rule) | — | Config only; land first |
| P2 | `coral/db` foundation: `CoralBase`, `types.py`, `ids.py`, `enum_codecs.py`, `bounds.py`, plus the schema-conventions test | P1 | P-S9 lift or copy decided here |
| P3 | Coral Alembic environment: `alembic.ini`, `env.py`, `script.py.mako`, `migrate.py` (`ensure_coral_schema`, guards, CockroachDB path, D1 refusal), S30, S31 and P-S8, the `tests/db/coral` guard tests | P2 | No tables yet; the empty chain is tested |
| P4 | **Schema PR** `coral_0001_core` (T1-T16), standalone per BP:356-358, with the models-match test | P3 | Code-owner review by the Coral DB owners |
| P5 | `CoralRunStore`: `start_run`, `load_run_state`, `apply_transition` (CAS), log reads, receipts, purge; concurrency tests on all lanes | P4 | The engine's reducer integrates here |
| P6 | `CoralWorkflowStore` and the artifact key scheme plus `CoralBlobLedger` | P4 | Content-addressed versions |
| P7 | `CoralQueueStore`: timer scan, effect claim, renew and finish, expired-lease recovery; a StartupLease-style executor helper | P5 | Copies `scheduled_task_store` patterns |
| P8 | Wiring: S32 hook, P-S4 CLI and routers, P-S7 deploy, multi-replica and D1 refusals, the `coral db-upgrade` command | P5-P7 | Pairs with the API agent |
| P9 | **Schema PR** `coral_0002_agents` (T17-T22) | P4 | Phase 2 |
| P10 | `CoralSessionBindingStore` and the signal methods; P-S5 (caller-supplied session id) | P9 | Hot-path lookup |
| P11 | `CoralProfileStore` with bundle copy and version pins | P9, P6 | Resolves R13 |
| P12 | **Schema PR** `coral_0003_evidence` (T23-T25), plus `CoralEvidenceStore` | P4 | Phase 3 |
| P13 | **Schema PR** `coral_0004_amend` (T26), plus amendment methods | P5 | Phase 7 |
| P14 | Retention and purge jobs; account lifecycle (lazy checks first, P-S6 later) | P5, P9 | Product decision on retention (Q4) |
| P15 | Upstream merge rehearsal workflow | P4 | Fork CI |

---

## 13. The tech lead's discrepancies, from the persistence side

- **D1 (Draft 4 versus the deep dive).** Draft 4's "separate migration environment and version table" (coral-design.md:288) matches §4/§5 here and stays. Draft 4's `PersistentTaskScheduler` for timers and signals (coral-design.md:284) is **refuted** (C6). Draft 4's "every row carries an owner" (coral-design.md:290) is refined (C10). "API keys as first-class" (coral-design.md:16, 63, 402) has a persistence consequence: only `auth_mode` and `credential_ref` are stored in Coral, never key material. The 70% versus 80% threshold is resolved as data: `coral_run_specs.refresh_threshold_bp` defaults to 7000, per Draft 4 D§7.5. The deep dive's "80%" (App. B) describes Omnigent's context-use labels, not Coral's default. The decision log is a document section (C11).
- **D2.** `coral-requirements.md` is missing (`git ls-files` shows only the three Coral docs). The following persistence requirements are therefore **unknown** and listed as open questions: retention, export, team sharing, audit duration, and data residency.
- **D3.** `/schemas` ("State Schema") maps to T1/T2 (workflows and versions); `/profiles` ("Agent Profiles") maps to T19/T20. The UI doc's localStorage profiles cannot satisfy pinning (C17). The node taxonomy is deliberately kept **out of DB columns** (T5 stores only `node_id`), so renaming kinds (Phase/Gate/Note against Start/End/Work step/…) causes no migration. "Note" nodes never create activations. None of the UI doc's prototype files exist at HEAD (`git ls-files | grep -i concerto` is empty).
- **D4 (Elephant-Goldfish).** Persistent sessions per roster member across loop passes are handled by T17: a new slot for the next activation **rebinds** the same `session_id`, and `generation` is unchanged. Per-member input scoping is a compiled-graph and brief concern; the persisted handoffs (T8/T9) are already per slot, so scoping filters at brief time and needs no new table.

---

## 14. Open questions (persistence)

1. **Q1.** Are profiles server-side desk objects (T19), repository files (`.coral/profiles/*`), or Omnigent installed agents? T20/T21 are needed in every case for pinning; T19 only in the first.
2. **Q2.** Where do saved simulation cases and confirmed command patterns live: DB rows (T14, T24), repository files under `.coral/`, or both, with the file canonical and the DB as cache? This affects sharing through git (D§3 "Sharing").
3. **Q3.** Which backends are required for Coral v1? CI will exercise SQLite, Postgres, CockroachDB and MySQL anyway. Is MySQL or CockroachDB support a release commitment, or best-effort?
4. **Q4.** Retention of run logs, observations and artifacts, and a user-facing "delete run". `coral-requirements.md` is missing (D2).
5. **Q5.** `workspace_id` without `server_default`: accept the departure from house style (BP-compliant), or stay consistent with the existing tables?
6. **Q6.** Should the S1 observer's signal insert stay best-effort, on the ordered executor (`session_live_state.py:120-160`), or be synchronous? Either way the periodic resync is the guarantee. The choice affects wake-up latency and SQLite contention.
7. **Q7.** Who owns `coral/db/migrations/` reviews in the fork (CODEOWNERS)? Do the upstream owners stay on `omnigent/db/migrations/`?
8. **Q8.** Teams: `workspace_id` is a tenant partition, not a team (F32). Run sharing would need a Coral ACL table or reuse of Omnigent's session-permission levels on the orchestrator session (`LEVEL_MANAGE`/`LEVEL_EDIT`, DD§20.1 Q4). This is deferred, but the T3 owner columns must not preclude it.
9. **Q9.** Does a `coral` top-level import name collide with any dependency? **UNVERIFIED.**

---

## 15. Explicitly UNVERIFIED

- Whether Omnigent retains old installed-agent bundle blobs after a reinstall. Coral copies bundles regardless.
- Whether `CredentialStore` works in local mode without KMS or Vault (`credential_store/__init__.py:1-25` names KMS and Vault ciphers only).
- The CI-time cost of truncating about 26 extra tables per test on the MySQL and Postgres lanes (P-S8 mitigates it).
- How psycopg CockroachDB `RETRY_SERIALIZABLE` surfaces (`OperationalError` or not) during Coral's initial migration. Mitigation: per-worker DDL file lock in tests; `run_coral_migrations_with_retry` in deploy.
- Running several `CREATE TABLE`s in one SERIALIZABLE transaction on CockroachDB 23.2 for `coral_0001_core`. Omnigent does the same for post-baseline revisions (`utils.py:598-613`), but a 16-table revision has not been exercised. Test it on the CockroachDB lane.
- PyPI or dependency-set collision for the import name `coral`.
