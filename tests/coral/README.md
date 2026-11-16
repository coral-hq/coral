# Coral test lanes

Coral tests live in three directories. The directory decides which fixtures a
test inherits and which CI job runs it.

| Lane | Directory | Databases | CI job | Local command |
| --- | --- | --- | --- | --- |
| Tier A: unit, API, validation | `tests/coral/` | SQLite | default `pytest` shards | `just coral test` |
| DB lanes | `tests/stores/coral/` | SQLite, Postgres, CockroachDB, MySQL | default `pytest` shards (SQLite); `stores-postgres`, `stores-crdb-*`, `stores-mysql` in `.github/workflows/ci.yml` | `just coral test-db`, `just coral test-crdb` |
| Split-DB lane | `tests/stores/coral/` (`coral_split_db`, `coral_db_layout[split]`) | SQLite operational DB and SQLite conversation DB | default `pytest` shards; a dedicated job is OPS-02 | `just coral test-split` |
| Tier B: real `claude` CLI against `mock_llm_server` | `tests/e2e/coral/` | server-owned | e2e gate (`.github/workflows/e2e.yml` runs `tests/e2e/`) | `just coral test-e2e` |
| Tier C: claude-native | `tests/e2e/coral/` | server-owned | e2e gate | owned by HRN-03 |
| Tier D: credentialed claude-sdk live bench | not created yet | n/a | not wired | owned by HRN-08 |

Tier B rules, including what it cannot prove yet, are in
`docs/coral/testing/tier-b.md`.

## Fixtures for DB-lane tests

`tests/stores/coral/conftest.py` provides these fixtures to every test under
`tests/stores/coral/`:

- `coral_db_uri`: an operational DB with the Omnigent schema at head, the Coral
  tables and the test-only `coraltest_probe` table, and no rows. On SQLite it
  is a copy of a template built once per worker. On external lanes the Coral
  tables are created once per module under the CockroachDB DDL lock.
- `coral_split_db`: a `CoralSplitDb` with an operational DB from
  `coral_db_uri`, a separate SQLite conversation DB, both file paths, and a
  `SqlAlchemyConversationStore` wired to the pair. It skips on external lanes.
- `coral_db_layout`: a `CoralDbLayout` parametrized as `single` and `split`.
  Request it to run one test on both layouts. `split` skips on external lanes.

`tests/stores/coral/_faults.py` holds the fault and contention helpers. Each
takes its inputs from the caller and asserts nothing:

- `crash_around(monkeypatch, owner, attr, when="before" | "after")` makes
  `owner.attr` raise `SimulatedCrash`. `SimulatedCrash` is a `BaseException`,
  so catch it with `pytest.raises(SimulatedCrash)`.
- `fresh_process(uri)` drops and disposes the cached engine for `uri` and
  returns a new one, so the test sees only committed state. Pass
  `connect=get_or_create_conversation_engine` for a split conversation DB.
- `run_racing(count, operation)` starts `operation(index)` on `count` threads
  behind one barrier and returns one `RaceOutcome` per thread.
- `hold_sqlite_write_lock(path)` holds `BEGIN IMMEDIATE` on a second
  connection. `short_sqlite_busy(engine, milliseconds)` lowers the session
  busy timeout so a blocked write fails fast.

## Add a Coral store test

1. Put the test in `tests/stores/coral/` so it runs on all four DB lanes.
2. Request `coral_db_uri`, or `coral_db_layout` when the behavior must also hold
   with a separate conversation DB.
3. Build inputs with `tests.coral.workflow_builders` where one exists.
4. Inject the fault in the test with the helpers above, then assert on what a
   caller can read back after `fresh_process`.
5. Run `just coral test-db`. For a CockroachDB check, run `just crdb-up` and
   then `just coral test-crdb`.

Put a test that needs no database lane in `tests/coral/` instead. Put a test
that needs the real `claude` CLI in `tests/e2e/coral/`.
