"""The shared L1 byte layout."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from coral.evidence.fingerprint import blob_id, l1_digest


def test_the_digest_frames_each_field_so_they_cannot_run_together() -> None:
    one = l1_digest("h", b"ab", [(b"c", b"d")])
    assert one != l1_digest("h", b"a", [(b"bc", b"d")])
    assert one != l1_digest("h", b"ab", [(b"cd", b"")])
    assert one == l1_digest("h", b"ab", iter([(b"c", b"d")]))


def test_every_input_changes_the_digest() -> None:
    base = l1_digest("h1", b"s", [(b"p", b"file 1 2 x")])
    assert base != l1_digest("h2", b"s", [(b"p", b"file 1 2 x")])
    assert base != l1_digest("h1", b"t", [(b"p", b"file 1 2 x")])
    assert base != l1_digest("h1", b"s", [(b"p", b"file 1 3 x")])
    assert base != l1_digest("h1", b"s", [])


def test_blob_id_matches_git_hash_object(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_bytes(b"hello\n")
    expected = subprocess.run(
        ["git", "hash-object", "--no-filters", str(path)],
        check=True,
        capture_output=True,
    ).stdout.strip()
    assert blob_id("sha1", b"hello\n") == expected
    assert blob_id("sha256", b"") == hashlib.sha256(b"blob 0\0").hexdigest().encode()
