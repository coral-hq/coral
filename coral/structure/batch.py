"""SES-10 K14 gate batch payload helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BatchItem:
    item_path: tuple[str, ...]
    visit_token: str
    context: str = ""


@dataclass(frozen=True)
class GateBatch:
    """Payload shape for a batched gate card (WEB-10 renders it)."""

    batch_id: str
    gate_node: str
    items: tuple[BatchItem, ...]

    def payload(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "gate_node": self.gate_node,
            "items": [
                {
                    "item_path": list(item.item_path),
                    "visit_token": item.visit_token,
                    "context": item.context,
                }
                for item in self.items
            ],
        }
