"""
Try a throwaway Claude config home and the CLI's own config dir; report ``name yes|no`` lines.

Run as ``python _claude_config_probe.py <report> <home> [<seed source> [<model key>]]``, the key
given as :func:`secret_spec` gives it, never as itself. It prints nothing, so it can run as an
API key helper. It writes only the report, entries in the cwd that it removes
again, ``$CLAUDE_CONFIG_DIR``, the home and the seed source, which a wrapped CLI's launcher copies
into ``$CLAUDE_CONFIG_DIR``. It overwrites a seeded file without creating it, and makes a new file
only in a seeded dir below ``.claude``, so a path a sandbox hides reads ``no``: bwrap's private
``/tmp`` holds the home itself as the parent of its ``~/.npm/_logs`` mount. The last line names
``$CLAUDE_CONFIG_DIR``, a test temp path. :func:`seed_claude_home` writes the layout the checks
try, and :func:`tree` snapshots it.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path

HOOK = Path(".claude/plugins/cache/m/p/1.0.0/hooks/hooks.json")
KEY = Path(".claude/sessions") / ("4242." + "a" * 64 + ".key")
KEYCHAIN = Path("Library/Keychains/login.keychain-db")
# The MCP server a seeded CLI's private global config names.
SEED_SERVER = "seeded-probe"
_SEEDED_FILES = {
    HOOK: '{"hooks": {}}',
    KEY: '{"peerToken": "throwaway"}',
    Path(".claude/.credentials.json"): '{"throwaway": true}',
    Path(".claude.json"): "{}",
    KEYCHAIN: "throwaway",
}
_SEEDED_DIRS = (Path(".claude/session-env/user-session"), Path(".claude/backups"))
# Each reads yes outside a sandbox and must read no inside the CLI's wrap.
HOME_CHECKS = (
    "plugins_hook",
    "plugins_new",
    "sessions_list",
    "sessions_key",
    "sessions_write",
    "session_env",
    "backups",
    "claude_json_read",
    "claude_json_write",
    "credentials",
    "keychain",
    "link_key",
    "link_keychain",
    "symlink_hook",
    "rename_plugins",
)


def seed_claude_home(home: Path) -> None:
    """A plugin hook, a session key, credentials, a global config and a keychain stand-in."""
    for relative, text in _SEEDED_FILES.items():
        (home / relative).parent.mkdir(parents=True, exist_ok=True)
        (home / relative).write_text(text)
    for relative in _SEEDED_DIRS:
        (home / relative).mkdir(parents=True, exist_ok=True)
    # Not 0700, so the outside run, whose config dir this is, reads config_private "no".
    (home / ".claude").chmod(0o755)


def tree(root: Path) -> dict[str, bytes | None]:
    """Every entry under *root*: a file's bytes, ``None`` for a dir."""
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in sorted(root.rglob("*"))
    }


def _overwrite(path: Path) -> Callable[[], object]:
    """Truncate and write an existing file; never create it."""

    def action() -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC)
        with os.fdopen(descriptor, "w") as handle:
            handle.write("planted")

    return action


def _write(path: Path) -> Callable[[], object]:
    def action() -> None:
        with open(path, "w") as handle:
            handle.write("planted")

    return action


def _read(path: Path) -> Callable[[], object]:
    def action() -> None:
        with open(path, "rb") as handle:
            handle.read(1)

    return action


def _through(
    make: Callable[[str, str], None],
    source: Path,
    name: str,
    use: Callable[[Path], Callable[[], object]],
) -> Callable[[], object]:
    """Make *name* in the cwd from *source* (a hard link or symlink), use it, remove it."""

    def action() -> None:
        try:
            make(str(source), name)
            use(Path(name))()
        finally:
            if os.path.lexists(name):
                os.unlink(name)

    return action


def _rename_and_back(path: Path, name: str) -> Callable[[], object]:
    def action() -> None:
        os.rename(path, name)
        os.rename(name, path)

    return action


def _private(own: str, scratch: str) -> Callable[[], object]:
    """An absolute 0700 dir inside the launcher's scratch."""

    def action() -> bool:
        real, root = os.path.realpath(own), os.path.realpath(scratch)
        info = os.lstat(own)
        return (
            os.path.isabs(own)
            and real.startswith(root + os.sep)
            and stat.S_ISDIR(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o700
        )

    return action


def _seeded(own: str) -> Callable[[], object]:
    """The private dir's global config is a regular file naming :data:`SEED_SERVER`."""

    def action() -> bool:
        path = Path(own) / ".claude.json"
        if not own or not stat.S_ISREG(os.lstat(path).st_mode):
            return False
        try:
            return SEED_SERVER in json.loads(path.read_text()).get("mcpServers", {})
        except ValueError:
            return False

    return action


# The session token a Coral CLI presents to its executor's credential proxy.
PROXY_TOKEN = "OMNIGENT_CLAUDE_PROXY_TOKEN"


def secret_spec(value: str) -> str:
    """``<length>:<sha256>`` of a secret, which lets the probe look for it without holding it."""
    return f"{len(value)}:{hashlib.sha256(value.encode()).hexdigest()}"


def _environ_holds(spec: str) -> Callable[[], object]:
    """Whether any environment value contains the secret ``spec`` describes."""

    def action() -> bool:
        length, _, digest = spec.partition(":")
        size = int(length)
        return any(
            hashlib.sha256(value[start : start + size].encode()).hexdigest() == digest
            for value in os.environ.values()
            for start in range(len(value) - size + 1)
        )

    return action


def _checks(
    home: Path, own: str, scratch: str, seed_source: str = "", model_key: str = ""
) -> dict[str, Callable[[], object]]:
    claude = home / ".claude"
    checks = {
        "plugins_hook": _overwrite(home / HOOK),
        "plugins_new": lambda: os.mkdir(claude / "plugins" / "planted"),
        "sessions_list": lambda: os.listdir(claude / "sessions"),
        "sessions_key": _read(home / KEY),
        "sessions_write": _write(claude / "sessions" / "planted.key"),
        "session_env": _write(claude / "session-env" / "user-session" / "x-hook-0.sh"),
        "backups": _write(claude / "backups" / ".claude.json.backup.1"),
        "claude_json_read": _read(home / ".claude.json"),
        "claude_json_write": _overwrite(home / ".claude.json"),
        "credentials": _read(claude / ".credentials.json"),
        "keychain": _read(home / KEYCHAIN),
        "link_key": _through(os.link, home / KEY, "linked-key", _read),
        "link_keychain": _through(os.link, home / KEYCHAIN, "linked-keychain", _read),
        "symlink_hook": _through(os.symlink, home / HOOK, "linked-hook", _overwrite),
        "rename_plugins": _rename_and_back(claude / "plugins", "moved-plugins"),
        "config_private": _private(own, scratch),
        "config_writable": _write(Path(own) / "probe.txt"),
        "projects": lambda: os.makedirs(Path(own) / "projects" / "probe"),
        "config_seeded": _seeded(own),
        # The seed is read-only in the wrap, so a launch cannot poison the next one's copy.
        "seed_source_write": _overwrite(Path(seed_source)) if seed_source else lambda: False,
    }
    if not own:
        checks.update(dict.fromkeys(("config_writable", "projects"), lambda: False))
    # The credential store and keychain item follow this name; it must name the private dir.
    store = os.environ.get("CLAUDE_SECURESTORAGE_CONFIG_DIR")
    checks["securestorage_own"] = lambda: bool(own) and store == own
    if model_key:
        # A Coral CLI's environment: its session token, and nowhere the model key itself.
        checks["proxy_token"] = lambda: bool(os.environ.get(PROXY_TOKEN))
        checks["model_key"] = _environ_holds(model_key)
    return checks


def _verdict(action: Callable[[], object]) -> str:
    try:
        return "no" if action() is False else "yes"
    except OSError:
        return "no"


def main(report: str, home: str, seed_source: str = "", model_key: str = "") -> None:
    own = os.environ.get("CLAUDE_CONFIG_DIR", "")
    checks = _checks(Path(home), own, os.environ.get("TMPDIR", ""), seed_source, model_key)
    lines = [f"{name} {_verdict(action)}" for name, action in checks.items()]
    Path(report).write_text("\n".join([*lines, f"config_dir {own}"]) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:5])
