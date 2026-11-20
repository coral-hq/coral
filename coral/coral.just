# Coral verification and test recipes (invoked from the root justfile via `mod coral`).

# Run all Coral test suites from the repository root.
test:
    cd .. && uv run --no-sync pytest tests/coral --reruns 0

# Run Coral unit tests from the repository root.
test-unit:
    cd .. && uv run --no-sync pytest tests/coral --reruns 0

# Run the Coral DB-lane tests on SQLite. Set OMNIGENT_TEST_DB_URI to run another lane;
# the root conftest drops and recreates databases there, so use a disposable server only.
test-db:
    cd .. && uv run --no-sync pytest tests/stores/coral --reruns 0

# Run the split fixture contract tests: operational and conversation DBs in separate SQLite files.
test-split:
    cd .. && uv run --no-sync pytest tests/stores/coral/test_split_layout.py --reruns 0

# Run the Coral DB-lane tests on CockroachDB 23.2 (port 26323). Run `just crdb-up` first.
test-crdb:
    cd .. && OMNIGENT_TEST_DB_URI="cockroachdb+psycopg://root@localhost:26323/defaultdb?sslmode=disable" uv run --extra all --extra cockroachdb pytest tests/stores/coral --reruns 0 -n 4 --dist=loadfile

# Regenerate coral/api/openapi.json from the Coral routers, then the web's TypeScript types from it.
openapi:
    cd .. && uv run --no-sync python -m coral.omni.server.openapi

# Fail when coral/api/openapi.json or the web's generated Coral API types are stale.
openapi-check:
    cd .. && uv run --no-sync python -m coral.omni.server.openapi --check

# Run Tier B: the real claude CLI against mock_llm_server. Skips without the claude CLI;
# the stack sample also needs CORAL_TIER_B_STACK_SAMPLE=1.
test-e2e:
    cd .. && uv run --no-sync pytest tests/e2e/coral --reruns 0 -rs -n 2 --dist=loadscope

# Print the fast claude-sdk probe verdicts (mock base URL, tool gate, MCP timeout) as JSON.
probe-claude-sdk:
    cd .. && uv run --no-sync python docs/coral/decisions/probes/spike_04.py
    cd .. && uv run --no-sync python docs/coral/decisions/probes/spike_01.py
    cd .. && uv run --no-sync python docs/coral/decisions/probes/spike_07.py --seconds 30
