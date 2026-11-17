"""Parameter schemas of Coral's engine tools (JSON Schema, plain JSON values).

Standard library only: hosts and runners import this through the tool catalog.
"""

from __future__ import annotations

from collections.abc import Mapping

# The canonical handoff body a submit commits, in UTF-8 bytes.
HANDOFF_BODY_MAX_BYTES = 12_288

SUBMIT_HANDOFF_PARAMETERS: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "activation_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 512,
            "description": "The activation id from your brief.",
        },
        "status": {
            "type": "string",
            "enum": ["done", "blocked"],
            "description": "done when your work is finished; blocked when you cannot continue.",
        },
        "report": {
            "type": "string",
            "minLength": 1,
            "maxLength": 8000,
            "description": "What you did and how you checked it, or what you tried.",
        },
        "blocked_reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2000,
            "description": "Required when status is blocked: what stops you.",
        },
        # Only handoffs are offered: a refresh note would always be refused and counted.
        "kind": {
            "type": "string",
            "enum": ["handoff"],
            "default": "handoff",
            "description": "Leave this as handoff.",
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
            "description": (
                "Only for a done handoff when your brief lists outcome labels: the label "
                "that fits your result."
            ),
        },
        "artifacts": {
            "type": "array",
            "maxItems": 50,
            "items": {"type": "string", "minLength": 1, "maxLength": 1024},
            "description": "Paths or references to what you produced.",
        },
    },
    "required": ["activation_id", "status", "report"],
    "additionalProperties": False,
}

CHOOSE_ARROW_PARAMETERS: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "decision_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 512,
            "description": "The decision id from the decision request.",
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 200,
            "description": "One of the labels the decision request lists.",
        },
        "reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4000,
            "description": "A short reason for your choice.",
        },
    },
    "required": ["decision_id", "label", "reason"],
    "additionalProperties": False,
}
