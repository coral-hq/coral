"""The shared L1 byte layout (K13 obligation 4), so digests from every backend compare.

A backend gathers the three inputs (HEAD, the raw status output, and one entry per dirty
path in status order) and calls :func:`l1_digest`. Entries are built from ``lstat``, never
a shell ``stat``. :func:`blob_id` gives the id ``git hash-object --no-filters`` would.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

L1_LAYOUT = b"coral-l1-v1\0"


def l1_digest(head: str, status: bytes, entries: Iterable[tuple[bytes, bytes]]) -> str:
    """
    The L1 digest of a worktree.

    :param head: The HEAD commit id.
    :param status: The raw ``WORKSPACE_STATUS_ARGV`` output.
    :param entries: ``(path, entry)`` for each dirty path, in status order. It is read
        lazily, so a caller can check a deadline between entries.
    """
    digest = hashlib.sha256(L1_LAYOUT)
    digest.update(head.encode() + b"\0")
    digest.update(_framed(status))
    for path, entry in entries:
        digest.update(_framed(path))
        digest.update(_framed(entry))
    return digest.hexdigest()


def blob_id(object_format: str, content: bytes) -> bytes:
    """The id ``git hash-object --no-filters`` gives ``content`` (``sha1`` or ``sha256``)."""
    digest = hashlib.new(object_format, b"blob %d\0" % len(content))
    digest.update(content)
    return digest.hexdigest().encode()


def _framed(data: bytes) -> bytes:
    """``data`` behind its length, so adjacent fields cannot run together."""
    return b"%d:%s" % (len(data), data)


__all__ = ["L1_LAYOUT", "blob_id", "l1_digest"]
