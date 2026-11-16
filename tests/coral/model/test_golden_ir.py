"""Golden IR: pinned hashes and canonical bytes. A change here is an IR-version decision."""

from __future__ import annotations

import pytest

from coral.model import canonical_bytes
from tests.coral.workflow_builders import compile_text, fixture_text

GOLDEN_HASHES = {
    "minimal": "735341285b49b50d7b75d5324f64d8f361993760d46c4039e03e6ac4bc8a42d8",
    "loop": "bfad5c4f161488a68433c1d00490b3e0fbed4657253a371acc37cb5e0c8d5690",
    "parallel": "b655190baf24b6aefc51ad15b72a83be455fd291c1521d6c3e9576757cbfc0b1",
    "review_prs": "1ec4a61c5e14d6d007bf83d0b5e1a023d36da53557bb9811e169e81fde3bf4f3",
    "deadlock_join": "260556b8abbdfa9eafce94eb071999bd8d3cc712bee558957633d3d3addda4ec",
}

MINIMAL_CANONICAL = (
    '{"arrows":[{"at_limit":null,"id":"a1","label":null,"limit":null,"source":"start",'
    '"target":"work"},{"at_limit":null,"id":"a2","label":null,"limit":null,"source":"work",'
    '"target":"end"}],"description":null,"ir_version":1,"name":"Demo","nodes":['
    '{"attempts":null,"concurrency":null,"goal":null,"harness":null,"id":"start",'
    '"kind":"start","list_from":null,"name":null,"outcomes":[],"parts":[],"prompt":null,'
    '"question":null,"roster":[]},'
    '{"attempts":3,"concurrency":1,"goal":"Do the thing","harness":null,"id":"work",'
    '"kind":"step","list_from":null,"name":"Work","outcomes":[],"parts":[],"prompt":null,'
    '"question":null,"roster":["implementer"]},'
    '{"attempts":null,"concurrency":null,"goal":null,"harness":null,"id":"end",'
    '"kind":"end","list_from":null,"name":null,"outcomes":[],"parts":[],"prompt":null,'
    '"question":null,"roster":[]}],"workflow_id":"demo"}'
)


@pytest.mark.parametrize("name", sorted(GOLDEN_HASHES))
def test_fixture_hash_is_pinned(name: str) -> None:
    graph, _ = compile_text(fixture_text(name))
    assert graph.content_hash == GOLDEN_HASHES[name]


def test_minimal_canonical_bytes_are_pinned() -> None:
    graph, _ = compile_text(fixture_text("minimal"))
    assert canonical_bytes(graph).decode() == MINIMAL_CANONICAL
