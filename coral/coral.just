# Coral verification and test recipes (invoked from the root justfile via `mod coral`).

# Run all Coral test suites from the repository root.
test:
    cd .. && uv run --no-sync pytest tests/coral --reruns 0

# Run Coral unit tests from the repository root.
test-unit:
    cd .. && uv run --no-sync pytest tests/coral --reruns 0

# Run the Coral DB-lane tests on SQLite. Set OMNIGENT_TEST_DB_URI to run another lane.
test-db:
    cd .. && uv run --no-sync pytest tests/stores/coral --reruns 0

# Run the split-DB lane: operational and conversation DBs in separate SQLite files.
test-split:
    cd .. && uv run --no-sync pytest tests/stores/coral -k split --reruns 0

# Run the Coral DB-lane tests on CockroachDB 23.2 (port 26323). Run `just crdb-up` first.
test-crdb:
    cd .. && OMNIGENT_TEST_DB_URI="cockroachdb+psycopg://root@localhost:26323/defaultdb?sslmode=disable" uv run --extra all --extra cockroachdb pytest tests/stores/coral --reruns 0 -n 4 --dist=loadfile

# Run Tier B: the real claude CLI against mock_llm_server. Skips without the claude CLI.
test-e2e:
    cd .. && uv run --no-sync pytest tests/e2e/coral --reruns 0 -rs -n 2 --dist=loadscope

# Print the fast SPK-03 claude-sdk probe verdicts (spikes 4, 1 and 7) as JSON.
probe-claude-sdk:
    cd .. && uv run --no-sync python docs/coral/decisions/probes/spike_04.py
    cd .. && uv run --no-sync python docs/coral/decisions/probes/spike_01.py
    cd .. && uv run --no-sync python docs/coral/decisions/probes/spike_07.py --seconds 30
