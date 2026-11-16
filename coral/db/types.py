"""Custom database types and column factories for Coral models."""

from __future__ import annotations

from sqlalchemy import LargeBinary, String
from sqlalchemy.dialects.mysql import BINARY as MySQLBinary
from sqlalchemy.dialects.mysql import VARCHAR as MySQLVarchar

from omnigent.db.compression import CompressedText

# Inline compression framed caps.
MAX_STORED_BYTES = 16_383
LARGE_MAX_STORED_BYTES = 65_535

CAPPED_TEXT = CompressedText(max_stored_bytes=MAX_STORED_BYTES)
LARGE_CAPPED_TEXT = CompressedText(max_stored_bytes=LARGE_MAX_STORED_BYTES)
CHECKSUM32 = LargeBinary(32).with_variant(MySQLBinary(32), "mysql")


def CaseSensitiveString(length: int) -> String:
    """Return a String column that uses case-sensitive binary collation on MySQL."""
    return String(length).with_variant(
        MySQLVarchar(length, charset="utf8mb4", collation="utf8mb4_bin"), "mysql"
    )


__all__ = [
    "CAPPED_TEXT",
    "CHECKSUM32",
    "LARGE_CAPPED_TEXT",
    "LARGE_MAX_STORED_BYTES",
    "MAX_STORED_BYTES",
    "CaseSensitiveString",
]
