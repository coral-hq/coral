"""Golden IR: pinned hashes and canonical bytes.

Pinned runs fold with the graph their hash names, and a load recomputes that hash. If a
pinned value here changes, every run already pinned stops loading: never regenerate
these values; change the canonical form only together with an ``ir_version`` decision.
"""

from __future__ import annotations

import pytest

from coral.model import CompiledGraph, canonical_bytes, content_hash
from coral.model.ir import CompiledArrow, CompiledNode
from tests.coral.workflow_builders import compile_text, fixture_text

GOLDEN_HASHES = {
    "minimal": "089c34c39d4d33f82e0bedd2ad98a778c2dea158a79633f70ba87d6bbac51f0b",
    "loop": "64870cef3631139bbecdeccc663debbfd416741cbbde04a59942b9ee9db5b8ca",
    "parallel": "4c0129b39567966a13ff3e2cd5c02bb66222c1ecd377a112c0d79e5f54f0d33a",
    "review_prs": "4731bd48b5a74a117b0af27df5d5b4f9d0eb220057628abbcab35c4e5259c252",
    "deadlock_join": "f2d7d73e6ddaad4a45836df372b5067320318ee5039aa6c3642282e76f182263",
}

MINIMAL_CANONICAL = (
    '{"arrows":[{"id":"a1","source":"start","target":"work"},'
    '{"id":"a2","source":"work","target":"end"}],"ir_version":1,"name":"Demo","nodes":['
    '{"id":"start","kind":"start"},'
    '{"attempts":3,"concurrency":1,"goal":"Do the thing","id":"work","kind":"step",'
    '"name":"Work","roster":["implementer"]},'
    '{"id":"end","kind":"end"}],"workflow_id":"demo"}'
)


# A later IR release that adds one optional field to the graph, its nodes and its arrows.
class _LaterNode(CompiledNode):
    timeout_s: int | None = None


class _LaterArrow(CompiledArrow):
    weight: int = 1


class _LaterGraph(CompiledGraph):
    nodes: tuple[_LaterNode, ...]
    arrows: tuple[_LaterArrow, ...]
    owner: str | None = None


@pytest.mark.parametrize("name", sorted(GOLDEN_HASHES))
def test_fixture_hash_is_pinned(name: str) -> None:
    graph, _ = compile_text(fixture_text(name))
    assert graph.content_hash == GOLDEN_HASHES[name]


def test_minimal_canonical_bytes_are_pinned() -> None:
    graph, _ = compile_text(fixture_text("minimal"))
    assert canonical_bytes(graph).decode() == MINIMAL_CANONICAL


@pytest.mark.parametrize("name", sorted(GOLDEN_HASHES))
def test_an_added_optional_field_keeps_every_pinned_hash(name: str) -> None:
    graph, _ = compile_text(fixture_text(name))
    later = _LaterGraph.model_validate(graph.model_dump())
    assert content_hash(canonical_bytes(later)) == GOLDEN_HASHES[name]
    # The field is hashed once a graph sets it.
    nodes = (later.nodes[0].model_copy(update={"timeout_s": 60}), *later.nodes[1:])
    arrows = (later.arrows[0].model_copy(update={"weight": 2}), *later.arrows[1:])
    for changed in (
        later.model_copy(update={"owner": "alice"}),
        later.model_copy(update={"nodes": nodes}),
        later.model_copy(update={"arrows": arrows}),
    ):
        assert content_hash(canonical_bytes(changed)) != GOLDEN_HASHES[name]


def test_the_ir_version_is_always_hashed() -> None:
    graph, _ = compile_text(fixture_text("minimal"))
    assert b'"ir_version":1' in canonical_bytes(graph)
    bumped = graph.model_copy(update={"ir_version": 2})
    assert canonical_bytes(bumped) != canonical_bytes(graph)
