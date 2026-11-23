"""Native runtime ownership must be meaningful in the sweeping process's namespace."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from omnigent.native import owner_claim


def test_owner_claim_round_trip(tmp_path: Path) -> None:
    owner_claim.write_owner_claim(tmp_path)
    claim = owner_claim.read_owner_claim(tmp_path)
    assert claim is not None
    assert claim.pid == os.getpid()
    assert claim.pid_ns == owner_claim.current_pid_namespace()
    assert claim.boot_id == owner_claim.current_boot_id()
    with pytest.raises(ValueError):
        int((tmp_path / "owner.pid").read_text())


@pytest.mark.parametrize("raw", [b"", b"123", b"\xff", b"0\npid_ns=none", b"123\npid_ns="])
def test_invalid_or_legacy_claim_is_unknown(tmp_path: Path, raw: bytes) -> None:
    (tmp_path / "owner.pid").write_bytes(raw)
    assert owner_claim.read_owner_claim(tmp_path) is None


@pytest.mark.parametrize(
    ("current_ns", "recorded_ns", "recorded_boot", "alive", "gone", "probe"),
    [
        ("pid:[1]", "pid:[1]", "boot-now", False, True, True),
        ("pid:[1]", "pid:[1]", "boot-now", True, False, True),
        ("pid:[1]", "pid:[2]", "boot-now", False, False, False),
        (None, "none", "boot-now", False, False, False),
        ("pid:[1]", "pid:[2]", "boot-before", True, False, False),
        ("pid:[1]", "pid:[1]", "boot-before", False, False, False),
        ("pid:[1]", "pid:[1]", None, False, False, False),
        ("none", "none", None, False, True, True),
    ],
)
def test_owner_death_requires_resolvable_identity(
    monkeypatch: pytest.MonkeyPatch,
    current_ns: str | None,
    recorded_ns: str,
    recorded_boot: str | None,
    alive: bool,
    gone: bool,
    probe: bool,
) -> None:
    monkeypatch.setattr(owner_claim, "current_pid_namespace", lambda: current_ns)
    monkeypatch.setattr(owner_claim, "IS_LINUX", current_ns != "none")
    monkeypatch.setattr(
        owner_claim, "current_boot_id", lambda: None if current_ns == "none" else "boot-now"
    )
    probes: list[int] = []

    def process_alive(pid: int) -> bool:
        probes.append(pid)
        return alive

    claim = owner_claim.OwnerClaim(123, recorded_ns, recorded_boot)
    assert owner_claim.owner_is_gone(claim, process_alive=process_alive) is gone
    assert probes == ([123] if probe else [])


def test_unreadable_linux_namespace_remains_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(owner_claim, "IS_LINUX", True)

    def unreadable(_path: str) -> str:
        raise PermissionError("namespace masked")

    monkeypatch.setattr(owner_claim.os, "readlink", unreadable)
    assert owner_claim.current_pid_namespace() is None
    owner_claim.write_owner_claim(tmp_path)
    assert owner_claim.read_owner_claim(tmp_path) is None


# CORAL(S116): a claim is read only from this user's small regular file, without blocking; a
# read that blocks fails this test alone (the signal method), not the whole run
@pytest.mark.skipif(os.name == "nt", reason="POSIX file types")
@pytest.mark.timeout(30, method="signal")
@pytest.mark.parametrize(
    "kind",
    ["fifo", "symlink-to-dev-zero", "symlink-to-claim", "oversized", "foreign-owner", "directory"],
)
def test_a_claim_that_is_not_this_users_small_regular_file_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    """A link, FIFO, device, dir, oversized or foreign file is refused as unclaimed."""
    elsewhere, directory = tmp_path / "elsewhere", tmp_path / "dir"
    for path in (elsewhere, directory):
        path.mkdir()
    owner_claim.write_owner_claim(elsewhere)
    claim = directory / "owner.pid"
    if kind == "fifo":
        os.mkfifo(claim)
    elif kind == "symlink-to-dev-zero":
        claim.symlink_to("/dev/zero")
    elif kind == "symlink-to-claim":
        claim.symlink_to(elsewhere / "owner.pid")
    elif kind == "oversized":
        claim.write_text((elsewhere / "owner.pid").read_text() + "x" * 4096)
    elif kind == "directory":
        claim.mkdir()
    else:
        owner_claim.write_owner_claim(directory)
        uid = os.getuid()
        monkeypatch.setattr(os, "getuid", lambda: uid + 1)

    assert owner_claim.read_owner_claim(directory) is None
    assert owner_claim.read_owner_claim_bytes(directory) is None


# CORAL(S116): a new claim is a fresh 0600 file, never written over or through an entry there
@pytest.mark.skipif(os.name == "nt", reason="POSIX links")
@pytest.mark.parametrize("planted", ["symlink", "hard-link", "file"])
def test_a_new_claim_never_writes_through_an_entry_already_there(
    tmp_path: Path, planted: str
) -> None:
    outside, directory = tmp_path / "outside", tmp_path / "dir"
    outside.write_text("untouched")
    directory.mkdir()
    entry = directory / ".launch-owner"
    if planted == "symlink":
        entry.symlink_to(outside)
    elif planted == "hard-link":
        os.link(outside, entry)
    else:
        entry.write_text("planted")

    with pytest.raises(FileExistsError):
        owner_claim.create_owner_claim(directory, filename=".launch-owner")
    assert outside.read_text() == "untouched"
    if planted == "file":
        assert entry.read_text() == "planted"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_a_new_claim_names_the_given_owner_or_holds_the_given_bytes(tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    copy.mkdir()
    owner_claim.create_owner_claim(tmp_path, filename=".launch-target", pid=123)
    claim = owner_claim.read_owner_claim(tmp_path, filename=".launch-target")
    assert claim == owner_claim.OwnerClaim(
        123, owner_claim.current_pid_namespace() or "", owner_claim.current_boot_id()
    )
    assert (tmp_path / ".launch-target").stat().st_mode & 0o777 == 0o600
    data = owner_claim.read_owner_claim_bytes(tmp_path, filename=".launch-target")
    assert data is not None
    owner_claim.create_owner_claim(copy, filename=".launch-owner", data=data)
    assert (copy / ".launch-owner").read_bytes() == data
