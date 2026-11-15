# Coral verification and test recipes (invoked from the root justfile via `mod coral`).

# Run all Coral test suites from the repository root.
test:
    cd .. && uv run --no-sync pytest tests/coral --reruns 0

# Run Coral unit tests from the repository root.
test-unit:
    cd .. && uv run --no-sync pytest tests/coral --reruns 0
