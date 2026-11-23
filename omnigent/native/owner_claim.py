"""Qualify process ownership before deleting shared native runtime state."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from omnigent._platform import IS_LINUX

OWNER_PID_FILENAME = "owner.pid"
# CORAL(S116): a claim is a few short lines; a larger file is refused unread
_CLAIM_MAX_BYTES = 4096


@dataclass(frozen=True)
class OwnerClaim:
    """A process identifier qualified by its PID namespace and boot."""

    pid: int
    pid_ns: str
    boot_id: str | None


def current_pid_namespace() -> str | None:
    """Return a namespace identity, or None when Linux cannot identify it."""
    if not IS_LINUX:
        return "none"
    try:
        return os.readlink("/proc/self/ns/pid")
    except OSError:
        return None


def current_boot_id() -> str | None:
    """Return the kernel boot identity when available."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeError):
        return None


def _claim_text(pid: int) -> str:
    """CORAL(S116): the claim naming *pid*, qualified by this process's namespace and boot."""
    lines = [str(pid), f"pid_ns={current_pid_namespace() or ''}"]
    boot_id = current_boot_id()
    if boot_id is not None:
        lines.append(f"boot={boot_id}")
    return "\n".join(lines) + "\n"


def write_owner_claim(directory: Path, *, filename: str = OWNER_PID_FILENAME) -> None:
    """Record the current owner; older integer-only readers skip this format."""
    (directory / filename).write_text(_claim_text(os.getpid()), encoding="utf-8")  # CORAL(S116)


def create_owner_claim(
    directory: Path,
    *,
    filename: str,
    pid: int | None = None,
    data: bytes | None = None,
    dir_fd: int | None = None,
) -> None:
    """
    CORAL(S116): create a new 0600 claim, never over an existing entry or through a link.

    It names *pid*, by default this process, unless *data* gives a claim read earlier. With
    *dir_fd* it is made in that open dir, *directory* naming it only. POSIX only.

    :raises OSError: If the entry exists or the file cannot be written.
    """
    owner = os.getpid() if pid is None else pid
    content = data if data is not None else _claim_text(owner).encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    path = directory / filename if dir_fd is None else filename
    with open(os.open(path, flags, 0o600, dir_fd=dir_fd), "wb") as handle:
        handle.write(content)


def read_owner_claim_bytes(directory: Path, *, filename: str = OWNER_PID_FILENAME) -> bytes | None:
    """
    CORAL(S116): a claim's bytes, only from this user's regular file of at most 4 KiB.

    A link, FIFO or device is refused without blocking, so a planted claim cannot stall,
    exhaust or redirect the reader.
    """
    path = directory / filename
    getuid = getattr(os, "getuid", None)
    try:
        if getuid is None:
            # Windows has neither FIFOs nor owner uids to check.
            with path.open("rb") as handle:
                data = handle.read(_CLAIM_MAX_BYTES + 1)
        else:
            from omnigent.inner.sandbox import open_regular_file

            with open_regular_file(path) as handle:
                if os.fstat(handle.fileno()).st_uid != getuid():
                    return None
                data = handle.read(_CLAIM_MAX_BYTES + 1)
    except OSError:
        return None
    return data if len(data) <= _CLAIM_MAX_BYTES else None


def read_owner_claim(directory: Path, *, filename: str = OWNER_PID_FILENAME) -> OwnerClaim | None:
    """Read qualified ownership, conservatively skipping unknown or legacy claims."""
    # CORAL(S116): only this user's small regular file counts as a claim
    data = read_owner_claim_bytes(directory, filename=filename)
    if data is None:
        return None
    try:
        raw = data.decode("utf-8")
    except UnicodeError:
        return None
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        pid = int(lines[0])
    except ValueError:
        return None
    fields = dict(line.split("=", 1) for line in lines[1:] if "=" in line)
    pid_ns = fields.get("pid_ns")
    if pid <= 0 or not pid_ns:
        return None
    return OwnerClaim(pid=pid, pid_ns=pid_ns, boot_id=fields.get("boot") or None)


def owner_is_gone(claim: OwnerClaim, *, process_alive: Callable[[int], bool]) -> bool:
    """Require a dead process in the same boot and known namespace."""
    boot_id = current_boot_id()
    # Different boot IDs can belong to live kernels sharing a filesystem.
    if claim.boot_id != boot_id or (IS_LINUX and boot_id is None):
        return False
    pid_ns = current_pid_namespace()
    if pid_ns is None or claim.pid_ns != pid_ns:
        return False
    return not process_alive(claim.pid)
