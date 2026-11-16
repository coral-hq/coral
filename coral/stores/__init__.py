"""Coral persistence adapters; these may import Omnigent."""

from coral.stores.workflows import (
    SqlWorkflowDefinitionStore,
    WorkflowDefinition,
    WorkflowTooLargeError,
)

__all__ = [
    "SqlWorkflowDefinitionStore",
    "WorkflowDefinition",
    "WorkflowTooLargeError",
]
