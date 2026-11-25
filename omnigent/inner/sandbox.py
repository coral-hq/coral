"""Sandbox interfaces, registry, and generic helpers."""

from __future__ import annotations

import base64
import contextlib  # CORAL(S116)
import errno  # CORAL(S115)
import json
import logging
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time  # CORAL(S116)
from abc import ABC, abstractmethod
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO, Protocol, cast  # CORAL(S115)

from omnigent.runner.identity import RUNNER_AUTH_SECRET_ENV_VARS
from omnigent.util.json_types import JsonValue

from .agent_env import DESKTOP_SESSION_ENV_VARS
from .datamodel import (
    CredentialProxySpec,
    CredentialSourceSpec,
    GitSshBinding,
    OSEnvSandboxSpec,
    OSEnvSpec,
)

logger = logging.getLogger(__name__)

# Diagnostic: prepend ``strace -f -y -e trace=file`` to the spawned
# target so the next debug nightly captures every file-related syscall
# (and any EACCES sandbox denials) in the wrapper's stderr. Goes
# through the executor's tee.
_SANDBOX_STRACE_ENV = "OMNIGENT_SANDBOX_STRACE"

# Re-exec marker for ``run_launcher``: when set, the script is
# already running INSIDE a ``bwrap`` / ``sandbox-exec`` wrap and
# must NOT re-exec itself again. Set right before the re-exec call
# and inherited by the wrapped process.
_LAUNCHER_WRAPPED_ENV = "OMNIGENT_LAUNCHER_SPAWN_WRAPPED"

# Hand-off marker for the spawn-time re-exec: the host pass mints the
# private scratch tmpdir, grants it in the profile, and names it here
# so the in-wrap pass adopts that exact dir (instead of minting a
# second, un-granted one) and owns its cleanup on exit. Names the one
# dir the host pass created, so cleanup can never touch a spec-supplied
# write root that merely happens to sit under the system tempdir.
_LAUNCHER_PRIVATE_TMPDIR_ENV = "OMNIGENT_LAUNCHER_SPAWN_PRIVATE_TMPDIR"
# CORAL(S109): names this launch's own target dir for the in-wrap pass, which removes it.
_LAUNCHER_LAUNCH_TMPDIR_ENV = "OMNIGENT_LAUNCHER_LAUNCH_TMPDIR"

# Trusted outer-launcher hint consumed before sandbox environment filtering.
# Active sandbox helpers and launcher targets strip it; unsandboxed children keep it.
HOST_SANDBOX_BACKEND_ENV = "OMNIGENT_HOST_SANDBOX_BACKEND"

# Backends that need a spawn-time wrap (parent-side ``bwrap`` /
# ``sandbox-exec`` invocation) in addition to whatever in-process
# work ``activate_sandbox`` does. ``none`` is a no-op backend so it
# doesn't need a wrap.
_SPAWN_WRAP_BACKENDS = frozenset({"linux_bwrap", "darwin_seatbelt"})


def _json_string_list(values: Sequence[object]) -> list[JsonValue]:
    return cast(list[JsonValue], [str(value) for value in values])


@dataclass
class SandboxPolicy:
    """
    Resolved sandbox policy serialized between the parent and helper.

    :param backend_type: The :attr:`SandboxBackend.type_name` of the
        backend that produced this policy, e.g. ``"linux_bwrap"``,
        ``"darwin_seatbelt"``, or ``"none"``.
    :param active: Whether the helper should run any sandbox activation
        for this policy. ``False`` for the ``"none"`` backend.
    :param read_roots: Per-spec read-only allow-list, or ``None`` when
        reads are unrestricted by the policy. The bwrap backend treats
        each entry as an extra ``--ro-bind-try`` mount on top of the
        hermetic root.
    :param write_roots: Directories the helper may write into, e.g.
        the cwd plus the per-helper scratch tmpdir.
    :param write_files: Per-file write grants for non-directory paths
        that can't live in :attr:`write_roots` (bwrap treats these as
        additional ``--bind-try`` mounts).
    :param credential_source_paths: Canonical private credential paths that
        must remain unreadable and unreachable, including through implicit
        runtime mounts. Carried through launcher serialization and policy clones.
    :param allow_network: ``True`` to share the host network namespace,
        ``False`` to isolate (bwrap adds ``--unshare-net``).
    :param cwd_allow_hidden: List of dotfile / dotdir basenames that
        pass through the sandbox view at any depth under cwd. ``"*"``
        explicitly allows every dotpath while retaining symlink escape
        masking. ``None`` lets the backend apply its default.
    :param cwd_hidden_scan_max_entries: Cap on entries the bwrap
        backend's recursive cwd walker visits. Ignored by other
        backends. Pair with :attr:`cwd_hidden_scan_overflow` to
        control behaviour when the cap is reached.
    :param cwd_hidden_scan_overflow: One of ``"error"``, ``"warn"``,
        or ``"unlimited"``. See :class:`OSEnvSandboxSpec` for the
        per-mode semantics.
    :param cwd_hidden_scan_recursive: When ``False`` (default) the
        dotfile / escaping-symlink masker scans only the top level of
        cwd and each read root; when ``True`` it recurses the full
        tree. See :class:`OSEnvSandboxSpec` for the security
        trade-off.
    :param mask_paths: Explicit files/directories the helper must not
        see, resolved to absolute paths by the backend. Masked with
        the same emit shape as the dotfile walker's entries (empty
        dir / empty file). ``None`` means no explicit masks.
    :param env_passthrough: User-declared environment-variable names
        the helper subprocess is allowed to inherit beyond the
        always-passed minimal default
        (:data:`omnigent.inner.os_env._DEFAULT_ENV_PASSTHROUGH`).
        Carried on the policy so every backend that spawns the
        helper applies the same allowlist; the parent-side
        :func:`omnigent.inner.os_env.build_helper_env` reads
        this and strips everything else from the helper's environment
        before ``subprocess.Popen``. ``None`` is treated identically
        to an empty list ("only the defaults pass through").
    :param spawn_env_allowlist: Exact environment-variable names the
        spawning executor deliberately included in the launcher
        subprocess's ``env=``. When set, :func:`run_launcher` prunes
        its inherited environment down to these names (plus internal
        launcher markers) before wrapping / exec-ing the target, so a
        spawn site that regresses to inheriting the full host
        environment cannot leak it into the sandbox.
        ``None`` (the default) skips the prune for spawn sites that
        haven't opted in.
    :param bind_host_proc: Launcher-local bwrap choice. ``None`` means the
        process constructing the final launcher has not resolved it yet.
    :param egress_relay_port: TCP port the in-namespace relay listens
        on (loopback). Set when ``egress_rules`` is active; the helper
        starts a relay daemon on this port at activation time. C1
        hardening: chosen as a random ephemeral port per helper by
        the parent rather than a hardcoded well-known port, so a
        port-squat attacker has to race every helper start instead
        of pre-binding a single known number.
    :param egress_socket_path: Absolute path (inside the namespace) to
        the Unix socket connecting to the parent's egress proxy. The
        relay forwards all traffic through this socket.
    :param deny_unix_socket_paths: Absolute paths to AF_UNIX (pathname)
        sockets the helper must NOT be able to ``connect(2)`` to, even
        when ``allow_network`` is true. Keeps a sandboxed pane from
        reaching back to an unsandboxed control-plane server over a
        socket that lives inside a bound write root (e.g. the managed
        tmux control socket). The bwrap backend overlays
        ``--bind-try /dev/null <path>`` so the path resolves to a
        character device, not a socket, and the connect fails; the
        seatbelt backend (whose default ``allow_network=true`` emits
        ``(allow network*)``, which would otherwise permit the AF_UNIX
        connect) emits an explicit last-match deny for each path.
        ``None`` is treated identically to an empty list, e.g.
        ``[Path("/tmp/omnigent-terminal-ab12/tmux.sock")]``.
        CORAL(S112): seatbelt also denies writing each socket and its parent
        dir, so neither can be renamed away from the deny; files inside that
        dir stay writable, but the dir itself cannot be renamed or removed.
    :param deny_unix_socket_roots: CORAL(S112): directories under which the
        sandboxed process may not ``connect(2)`` to any AF_UNIX socket, even when
        ``allow_network`` is true. :func:`resolve_sandbox` sets the harness socket
        roots on every active policy. Stored resolved. Seatbelt denies each as a
        ``subpath``, plus the per-user default root even when this is empty. Only
        where ``(allow network*)`` applies, it then allows the policy's
        :attr:`private_tmpdir` and any write root inside a denied root again (the
        CLI's launch dir sits under the harness root). bwrap ignores it: its
        ``--tmpfs /tmp`` hides the default root. ``None`` is the same as an
        empty list.
    :param scratch_dir_env: CORAL(S113): the name of an environment variable that the
        launcher's in-wrap pass sets to a fresh 0700 directory inside the target's private
        scratch, named after the variable, lowercased (``claude_config_dir``). It is removed
        with the scratch when the target exits, and needs no grant, because the scratch is
        one. ``None``: no such dir.
    :param scratch_dir_files: CORAL(S113): names created as empty files in that dir, so the
        target cannot make a directory of that name there.
    :param scratch_dir_extra_envs: CORAL(S113): further environment variables the in-wrap
        pass sets to that same dir, over any inherited value.
    :param scratch_dir_seed: CORAL(S115): ``(entry name, absolute source file)`` pairs the
        in-wrap pass copies into that dir, each as a fresh 0600 file, before it creates
        ``scratch_dir_files``. A missing source, a link, any other non-regular file, or one
        another user owns or can write, fails the launch. :func:`with_scratch_dir_env` grants
        each source as a read root. Empty: an empty dir.
    :param mask_scan_skip_roots: Write roots the dotfile / escaping-symlink
        mask scan must skip — the framework's own scratch / runtime dirs
        added post-resolve via :func:`with_additional_write_roots`. These
        hold sandbox scaffolding (the egress ``.egress.sock``, CA bundle,
        credential-proxy files), never pre-existing user secrets, so
        scanning them is both pointless and harmful (masking
        ``.egress.sock`` breaks the egress relay). ``None`` is treated
        identically to an empty list.

    Historical note: a previous revision carried an
    ``egress_auth_token`` field shared between the parent (embedded
    as Basic auth in ``HTTP_PROXY``) and the relay (which validated
    a matching ``Proxy-Authorization`` header). That field was
    dropped — see :func:`omnigent.inner.os_env._HelperProcessClient.
    _start_egress_proxy_locked` for the rationale. The token used to
    leak through ``Popen`` argv (visible via ``ps`` to any same-UID
    process) and didn't add real protection given the relay's other
    bind-fails-loud guarantees.
    """

    backend_type: str
    active: bool
    read_roots: list[Path] | None
    write_roots: list[Path]
    write_files: list[Path]
    allow_network: bool
    copy_on_write_roots: list[Path] | None = None
    copy_on_write_namespace: tuple[int, int, int] | None = None
    cwd_allow_hidden: list[str] | None = None
    cwd_hidden_scan_max_entries: int = 50000
    cwd_hidden_scan_overflow: str = "warn"
    cwd_hidden_scan_recursive: bool = False
    mask_paths: list[Path] | None = None
    env_passthrough: list[str] | None = None
    spawn_env_allowlist: list[str] | None = None
    bind_host_proc: bool | None = None
    egress_relay_port: int | None = None
    egress_socket_path: str | None = None
    git_ssh_socket_path: str | None = None
    deny_unix_socket_paths: list[Path] | None = None
    # CORAL(S112): directories whose AF_UNIX sockets stay unreachable, the harness socket roots
    deny_unix_socket_roots: list[Path] | None = None
    credential_source_paths: list[Path] | None = None
    # CORAL(S109): per launch, a spawn-time-wrap launcher makes a private dir under this
    # parent, grants it, sets the target's env var to it, and removes it when the target exits.
    launch_tmpdir_env: str | None = None
    launch_tmpdir_parent: Path | None = None
    # CORAL(S113): the launcher points this env var at a fresh 0700 dir inside the target's scratch
    scratch_dir_env: str | None = None
    scratch_dir_files: tuple[str, ...] = ()
    scratch_dir_extra_envs: tuple[str, ...] = ()
    scratch_dir_seed: tuple[tuple[str, str], ...] = ()  # CORAL(S115)
    # Parent-side only: the resolved credential-proxy policy. Read in
    # ``_HelperProcessClient._start_locked`` (parent) to mint synthetic
    # placeholders and proxy rewrite rules. Intentionally NOT carried in
    # ``to_jsonable`` / ``from_jsonable`` — the helper receives only the
    # non-secret synthetic payload over the config FD, and resolved
    # secrets never touch the policy that serialises into logs / dumps.
    credential_proxy: CredentialProxySpec | None = None
    git_ssh: list[GitSshBinding] | None = None
    # Parent-side only: write roots the dotfile / escaping-symlink mask
    # scan must NOT walk. Framework code adds the sandbox's own runtime
    # scaffolding to ``write_roots`` via
    # :func:`with_additional_write_roots` (the per-helper scratch tmpdir
    # holding the egress ``.egress.sock``, the CA bundle, credential-proxy
    # files, harness state dirs). Those are created fresh by the framework
    # and never hold pre-existing user secrets, so scanning them is
    # pointless — and actively harmful: the scan would ``--bind-try
    # /dev/null`` the dotfile ``.egress.sock``, breaking the egress relay.
    # Every root recorded here is dropped from the scan set (along with
    # anything nested under it). Built parent-side during arg emission;
    # like ``credential_proxy`` it is intentionally NOT serialised.
    mask_scan_skip_roots: list[Path] | None = None
    # CORAL(S112): parent-side only, the scratch the child gets as $TMPDIR (with_private_tmpdir).
    # Not serialised: each profile is built by the process that minted this dir.
    private_tmpdir: Path | None = None

    def to_jsonable(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {
            "backend_type": self.backend_type,
            "active": self.active,
            "read_roots": (
                _json_string_list(self.read_roots) if self.read_roots is not None else None
            ),
            "copy_on_write_roots": _json_string_list(self.copy_on_write_roots or []),
            "copy_on_write_namespace": (
                cast(list[JsonValue], list(self.copy_on_write_namespace))
                if self.copy_on_write_namespace
                else None
            ),
            "write_roots": _json_string_list(self.write_roots),
            "write_files": _json_string_list(self.write_files),
            "allow_network": self.allow_network,
            "cwd_allow_hidden": (
                _json_string_list(self.cwd_allow_hidden)
                if self.cwd_allow_hidden is not None
                else None
            ),
            "cwd_hidden_scan_max_entries": self.cwd_hidden_scan_max_entries,
            "cwd_hidden_scan_overflow": self.cwd_hidden_scan_overflow,
            "cwd_hidden_scan_recursive": self.cwd_hidden_scan_recursive,
            "mask_paths": (
                _json_string_list(self.mask_paths) if self.mask_paths is not None else None
            ),
            "env_passthrough": (
                _json_string_list(self.env_passthrough)
                if self.env_passthrough is not None
                else None
            ),
            "spawn_env_allowlist": (
                _json_string_list(self.spawn_env_allowlist)
                if self.spawn_env_allowlist is not None
                else None
            ),
            "bind_host_proc": self.bind_host_proc,
            "egress_relay_port": self.egress_relay_port,
            "egress_socket_path": self.egress_socket_path,
            "git_ssh_socket_path": self.git_ssh_socket_path,
            "deny_unix_socket_paths": (
                _json_string_list(self.deny_unix_socket_paths)
                if self.deny_unix_socket_paths is not None
                else None
            ),
            # CORAL(S112)
            "deny_unix_socket_roots": (
                _json_string_list(self.deny_unix_socket_roots)
                if self.deny_unix_socket_roots is not None
                else None
            ),
            "credential_source_paths": (
                _json_string_list(self.credential_source_paths)
                if self.credential_source_paths is not None
                else None
            ),
            # CORAL(S109)
            "launch_tmpdir_env": self.launch_tmpdir_env,
            "launch_tmpdir_parent": (
                str(self.launch_tmpdir_parent) if self.launch_tmpdir_parent is not None else None
            ),
            # CORAL(S113)
            "scratch_dir_env": self.scratch_dir_env,
            "scratch_dir_files": _json_string_list(self.scratch_dir_files),
            "scratch_dir_extra_envs": _json_string_list(self.scratch_dir_extra_envs),
            # CORAL(S115)
            "scratch_dir_seed": cast(
                list[JsonValue], [_json_string_list(pair) for pair in self.scratch_dir_seed]
            ),
        }
        return result

    @classmethod
    def from_jsonable(cls, data: dict[str, JsonValue]) -> SandboxPolicy:
        read_roots_data = data.get("read_roots")
        read_roots = None
        if isinstance(read_roots_data, list):
            read_roots = [Path(str(root)) for root in read_roots_data]
        write_roots_data = data.get("write_roots", [])
        write_files_data = data.get("write_files", [])
        if not isinstance(write_roots_data, list):
            write_roots_data = []
        if not isinstance(write_files_data, list):
            write_files_data = []
        cwd_allow_hidden_data = data.get("cwd_allow_hidden")
        cwd_allow_hidden: list[str] | None = None
        if isinstance(cwd_allow_hidden_data, list):
            cwd_allow_hidden = [str(name) for name in cwd_allow_hidden_data]
        # Narrow scan-cap fields defensively — ``data`` is a generic
        # JSON map that could carry any value at runtime even though
        # the spec parser already validated the source. The typed
        # field needs an int, so fall back to the dataclass default
        # when the encoded value isn't usable.
        max_entries_raw = data.get("cwd_hidden_scan_max_entries", 50000)
        max_entries = max_entries_raw if isinstance(max_entries_raw, int) else 50000
        overflow_raw = data.get("cwd_hidden_scan_overflow", "warn")
        overflow = overflow_raw if isinstance(overflow_raw, str) else "warn"
        recursive_raw = data.get("cwd_hidden_scan_recursive", False)
        recursive = recursive_raw if isinstance(recursive_raw, bool) else False
        bind_host_proc_raw = data.get("bind_host_proc")
        bind_host_proc = bind_host_proc_raw if isinstance(bind_host_proc_raw, bool) else None
        mask_paths_data = data.get("mask_paths")
        mask_paths: list[Path] | None = None
        if isinstance(mask_paths_data, list):
            mask_paths = [Path(str(path)) for path in mask_paths_data]
        env_passthrough_data = data.get("env_passthrough")
        env_passthrough: list[str] | None = None
        if isinstance(env_passthrough_data, list):
            env_passthrough = [str(name) for name in env_passthrough_data]
        spawn_env_allowlist_data = data.get("spawn_env_allowlist")
        spawn_env_allowlist: list[str] | None = None
        if isinstance(spawn_env_allowlist_data, list):
            spawn_env_allowlist = [str(name) for name in spawn_env_allowlist_data]
        egress_relay_port_raw = data.get("egress_relay_port")
        egress_relay_port: int | None = (
            int(egress_relay_port_raw) if isinstance(egress_relay_port_raw, (int, float)) else None
        )
        egress_socket_path_raw = data.get("egress_socket_path")
        egress_socket_path: str | None = (
            str(egress_socket_path_raw) if egress_socket_path_raw is not None else None
        )
        git_ssh_socket_path_raw = data.get("git_ssh_socket_path")
        git_ssh_socket_path = (
            str(git_ssh_socket_path_raw) if git_ssh_socket_path_raw is not None else None
        )
        deny_unix_socket_paths_data = data.get("deny_unix_socket_paths")
        deny_unix_socket_paths: list[Path] | None = None
        if isinstance(deny_unix_socket_paths_data, list):
            deny_unix_socket_paths = [Path(str(path)) for path in deny_unix_socket_paths_data]
        # CORAL(S112): an old payload has no roots
        deny_unix_socket_roots_data = data.get("deny_unix_socket_roots")
        deny_unix_socket_roots = (
            [Path(str(path)) for path in deny_unix_socket_roots_data]
            if isinstance(deny_unix_socket_roots_data, list)
            else None
        )
        credential_source_paths_data = data.get("credential_source_paths")
        credential_source_paths = (
            [Path(str(path)) for path in credential_source_paths_data]
            if isinstance(credential_source_paths_data, list)
            else None
        )
        # CORAL(S109)
        launch_env_raw = data.get("launch_tmpdir_env")
        launch_parent_raw = data.get("launch_tmpdir_parent")
        # CORAL(S113): an old payload asks for no private dir; a malformed one is refused
        scratch_dir_env = data.get("scratch_dir_env")
        scratch_dir_files = data.get("scratch_dir_files", [])
        scratch_dir_extra_envs = data.get("scratch_dir_extra_envs", [])
        scratch_dir_seed = data.get("scratch_dir_seed", [])  # CORAL(S115)
        if (
            scratch_dir_env is not None
            or scratch_dir_files != []
            or scratch_dir_extra_envs != []
            or scratch_dir_seed != []  # CORAL(S115)
        ):
            _check_scratch_dir(
                scratch_dir_env, scratch_dir_files, scratch_dir_extra_envs, scratch_dir_seed
            )
        cow_roots = data.get("copy_on_write_roots", [])
        if not isinstance(cow_roots, list) or any(not isinstance(p, str) for p in cow_roots):
            raise ValueError("Invalid copy_on_write_roots")
        cow_namespace = data.get("copy_on_write_namespace")
        namespace = None
        if cow_namespace is not None:
            from omnigent.sandbox.copy_on_write import parse_namespace

            namespace = parse_namespace(cow_namespace)
        return cls(
            copy_on_write_roots=[Path(str(p)) for p in cow_roots] or None,
            copy_on_write_namespace=namespace,
            backend_type=str(data.get("backend_type", "none")),
            active=bool(data.get("active", False)),
            read_roots=read_roots,
            write_roots=[Path(str(root)) for root in write_roots_data],
            write_files=[Path(str(path)) for path in write_files_data],
            allow_network=bool(data.get("allow_network", True)),
            cwd_allow_hidden=cwd_allow_hidden,
            cwd_hidden_scan_max_entries=max_entries,
            cwd_hidden_scan_overflow=overflow,
            cwd_hidden_scan_recursive=recursive,
            mask_paths=mask_paths,
            env_passthrough=env_passthrough,
            spawn_env_allowlist=spawn_env_allowlist,
            bind_host_proc=bind_host_proc,
            egress_relay_port=egress_relay_port,
            egress_socket_path=egress_socket_path,
            git_ssh_socket_path=git_ssh_socket_path,
            deny_unix_socket_paths=deny_unix_socket_paths,
            deny_unix_socket_roots=deny_unix_socket_roots,  # CORAL(S112)
            credential_source_paths=credential_source_paths,
            launch_tmpdir_env=launch_env_raw if isinstance(launch_env_raw, str) else None,
            launch_tmpdir_parent=(
                Path(launch_parent_raw) if isinstance(launch_parent_raw, str) else None
            ),
            # CORAL(S113): both were checked above
            scratch_dir_env=cast("str | None", scratch_dir_env),
            scratch_dir_files=tuple(cast("list[str]", scratch_dir_files)),
            scratch_dir_extra_envs=tuple(cast("list[str]", scratch_dir_extra_envs)),
            scratch_dir_seed=tuple(  # CORAL(S115): checked above
                (name, source) for name, source in cast("list[list[str]]", scratch_dir_seed)
            ),
        )


class ContainmentHandle(Protocol):
    """A releasable handle for post-spawn containment (e.g. a Job Object).

    Returned by :meth:`SandboxBackend.post_spawn` and held by the parent for
    the helper's lifetime. ``close()`` releases the resource; for a Windows
    Job Object configured with kill-on-close, that terminates the contained
    process tree.
    """

    def close(self) -> None:
        pass


class SandboxBackend(ABC):
    """
    Backend interface for host sandbox implementations.

    All built-in backends are **spawn-time** backends (e.g.
    ``linux_bwrap``, ``darwin_seatbelt``): they launch the helper
    subprocess *through* a sandbox launcher (bubblewrap, sandbox-exec,
    etc.) so the kernel sets up namespaces / mount views before the
    helper executes. They override :meth:`wrap_launcher_argv` to
    prepend the launcher and may additionally use :meth:`activate` for
    in-process hardening that runs after the launcher (e.g. seccomp
    filters layered on top of the namespace).

    The interface still permits **in-process** backends that apply
    syscalls to the current process inside :meth:`activate` and keep
    the no-op :meth:`wrap_launcher_argv` default, but none ship today.
    """

    type_name: str

    @abstractmethod
    def resolve(self, spec: OSEnvSpec, cwd: Path) -> SandboxPolicy:
        raise NotImplementedError

    @abstractmethod
    def activate(self, policy: SandboxPolicy) -> None:
        raise NotImplementedError

    def wrap_launcher_argv(
        self,
        argv: list[str],
        policy: SandboxPolicy,
        cwd: Path,
        chdir: Path | None = None,
        target: str | None = None,
    ) -> list[str]:
        """
        Wrap *argv* with whatever launcher the backend needs at spawn
        time, or return *argv* unchanged for backends that sandbox
        in-process from :meth:`activate`.

        Called by :class:`omnigent.inner.os_env._HelperProcessClient`
        on the parent side immediately before ``subprocess.Popen`` so
        the wrap can prepend a sandbox launcher (e.g. ``bwrap`` plus
        its mount/namespace flags). The default is a no-op so existing
        backends keep working without overriding anything.

        :param argv: The unwrapped command argv the parent intends to
            spawn, e.g. ``[sys.executable, "-m",
            "omnigent.inner.os_env", "helper", "<encoded>"]``.
        :param policy: The resolved :class:`SandboxPolicy` (the same
            object that will be passed to :meth:`activate` inside the
            helper). Backends that need read/write roots, the
            scratch tmpdir, or ``allow_network`` to shape their
            launcher args read them from here.
        :param cwd: Workspace directory the helper was launched from.
            Backends that bind-mount (bwrap) use this verbatim and
            should keep it exposed even when *chdir* differs.
        :param chdir: Optional separate ``--chdir`` target. When
            ``None``, the helper starts in *cwd*. When set (e.g. for
            ``OSEnvSpec.start_in_scratch``), the launcher chdirs
            there on entry. In-process backends may ignore this.
        :param target: Absolute path to the binary that the launcher
            will exec as its final target (e.g. the ``claude`` CLI).
            When set, the backend must ensure this path is reachable
            inside the sandbox namespace — for bwrap this means
            bind-mounting the target's directory chain just as it does
            for ``argv[0]`` (the Python interpreter). ``None`` when
            the target is already covered by the default mounts (e.g.
            ``/usr/bin/something``).
        :returns: The (possibly wrapped) argv. The default
            implementation returns *argv* unchanged.
        """
        del policy, cwd, chdir, target
        return argv

    def prepare_launcher_policy(self, policy: SandboxPolicy) -> SandboxPolicy:
        """Resolve host-local policy immediately before launcher construction."""
        return policy

    def post_spawn(self, policy: SandboxPolicy, pid: int) -> ContainmentHandle | None:
        """
        Apply post-spawn containment to a just-launched helper process.

        Called by :class:`omnigent.inner.os_env._HelperProcessClient` on
        the parent side immediately after ``subprocess.Popen`` returns,
        for active policies. Unlike :meth:`wrap_launcher_argv` (which
        prepends a launcher *before* exec), this hook acts on an
        already-running ``pid`` — the model Windows Job Objects require,
        since a process is assigned to a job only after it exists.

        :param policy: The resolved :class:`SandboxPolicy`.
        :param pid: OS process id of the just-spawned helper.
        :returns: An optional :class:`ContainmentHandle` releasing the
            containment resource (e.g. the Job Object handle) on
            ``close()``. The caller holds it for the helper's lifetime
            and closes it on teardown. The default returns ``None``.
        """
        del policy, pid
        return None


_BACKENDS: dict[str, SandboxBackend] = {}


def register_backend(backend: SandboxBackend) -> None:
    _BACKENDS[backend.type_name] = backend


def _resolve_grant_root(cwd: Path, root: str) -> Path:
    """Resolve a spec-supplied path grant against *cwd*.

    Expands ``~`` but intentionally NOT ``$VAR`` -- env-var expansion at
    resolve time is a grant-widening lever when an attacker can shape the
    parent environment (mirrors the hardening in
    :func:`omnigent.inner.bwrap_sandbox._resolve_root`). Relative entries
    resolve against *cwd*; the result is absolute and symlink-normalised
    (``strict=False`` -- a granted path need not exist yet). Callers compare
    already-resolved target paths against these roots, so traversal via
    symlinks or ``..`` cannot escape a grant.

    :param cwd: The environment's working directory; relative grants resolve
        against it.
    :param root: The raw path string from the spec, e.g. ``"~/code"`` or
        ``"../sibling"``.
    :returns: An absolute, normalised :class:`Path`.
    """
    if "$" in root:
        logger.warning(
            "sandbox: grant path %r contains '$', which is NOT expanded "
            "against the parent environment (security hardening -- env-var "
            "expansion was a grant-widening lever). Use a literal path or ~.",
            root,
        )
    expanded = os.path.expanduser(root)
    path = Path(expanded)
    if not path.is_absolute():
        path = cwd / path
    return path.resolve(strict=False)


def resolve_sandbox(spec: OSEnvSpec, cwd: Path) -> SandboxPolicy:
    sandbox_spec = spec.sandbox or _default_sandbox_for_platform()
    if sandbox_spec.git_ssh:
        if sandbox_spec.type not in ("linux_bwrap", "darwin_seatbelt"):
            raise ValueError("git_ssh requires linux_bwrap or darwin_seatbelt")
        from .git_ssh import normalize_git_ssh_bindings

        sandbox_spec = replace(
            sandbox_spec, git_ssh=normalize_git_ssh_bindings(sandbox_spec.git_ssh)
        )
        spec = replace(spec, sandbox=sandbox_spec)
    if sandbox_spec.type != "linux_bwrap" and any(
        grant.copy_on_write for grant in sandbox_spec.write_path_specs
    ):
        raise ValueError("copy_on_write requires sandbox.type=linux_bwrap")
    if sandbox_spec.type == "none":
        # ``sandbox.type: none`` runs the helper UNSANDBOXED, so path grants
        # cannot *restrict* the (unconfined) shell -- a network restriction is
        # still meaningless here and rejected. But ``read_paths`` /
        # ``write_paths`` / ``write_files`` ARE honoured as explicit
        # FILE-TOOL reach grants: they are the opt-in that lets
        # ``sys_os_read`` / ``sys_os_write`` / ``sys_os_edit`` reach declared
        # paths OUTSIDE the workspace root (enforced by ``_assert_within_reach``
        # in ``os_env.py``). With none declared, ``read_roots``/``write_roots``
        # stay empty and the file tools remain confined to cwd exactly as
        # before -- the default is byte-for-byte unchanged.
        if sandbox_spec.allow_network is False:
            raise ValueError("sandbox type 'none' cannot restrict network")
        read_roots = (
            [_resolve_grant_root(cwd, root) for root in sandbox_spec.read_paths]
            if sandbox_spec.read_paths is not None
            else None
        )
        write_roots = [
            _resolve_grant_root(cwd, grant.path) for grant in sandbox_spec.write_path_specs
        ]
        write_files = [_resolve_grant_root(cwd, root) for root in (sandbox_spec.write_files or [])]
        return SandboxPolicy(
            backend_type="none",
            active=False,
            read_roots=read_roots,
            write_roots=write_roots,
            write_files=write_files,
            allow_network=True,
        )
    policy = _get_backend(sandbox_spec.type).resolve(spec, cwd)
    # CORAL(S112): no sandboxed process may reach a harness socket, its own session's included
    policy = with_denied_unix_socket_roots(policy, _harness_socket_roots())
    if policy.credential_proxy is not None:
        for entry in policy.credential_proxy.entries:
            if (
                entry.source.kind == "unix_socket"
                or entry.source.refresh_interval_seconds is not None
            ):
                protect_credential_source(entry.source, policy, cwd=cwd)
    if policy.git_ssh:
        for binding in policy.git_ssh:
            for path in (binding.identity_file, binding.known_hosts_file):
                protect_credential_source(
                    CredentialSourceSpec(kind="file", path=path), policy, cwd=cwd
                )
    if policy.copy_on_write_roots:
        from omnigent.sandbox.copy_on_write import attach_shared_environment

        attach_shared_environment(policy)
    return policy


def protect_credential_source(
    source: CredentialSourceSpec, sandbox: SandboxPolicy | None, *, cwd: Path | None = None
) -> Path:
    """Validate private source placement and carry its canonical path into every launcher."""
    if sandbox is None or not sandbox.active:
        raise ValueError("credential refresh requires an active sandbox policy")
    if source.kind not in ("file", "unix_socket") or not source.path:
        raise ValueError("credential refresh requires a file or unix_socket source")
    if sandbox.backend_type not in _SPAWN_WRAP_BACKENDS:
        raise ValueError("credential refresh requires a filesystem-confined sandbox")
    path = Path(source.path).expanduser()
    if not path.is_absolute():
        raise ValueError("refresh source must use an absolute path")
    roots = tuple(root.resolve() for root in sandbox.write_roots)
    files = tuple(allowed.resolve() for allowed in sandbox.write_files)
    read_roots = (
        *(root.resolve() for root in (sandbox.read_roots or [])),
        (cwd or Path.cwd()).resolve(),
    )
    for component in (path, *path.parents):
        for candidate in (component.absolute(), component.resolve()):
            if any(candidate.is_relative_to(root) for root in roots) or candidate in files:
                raise ValueError("refresh source must stay outside sandbox-writable paths")
            if any(candidate.is_relative_to(root) for root in read_roots):
                raise ValueError("refresh source must stay outside sandbox-readable paths")
    if path.exists() and path.stat().st_nlink != 1:
        raise ValueError("refresh source must not be hard-linked")
    canonical = path.resolve()
    if sandbox.credential_source_paths is None:
        sandbox.credential_source_paths = []
    if canonical not in sandbox.credential_source_paths:
        sandbox.credential_source_paths.append(canonical)
    return canonical


def containment_prefix(root: str | Path) -> str:
    """
    Express *root* as a prefix for a containment test.

    The trailing separator is load-bearing: it is what stops a boundary at
    ``/data`` from admitting a sibling ``/database``, and — because the
    candidate is put in the same form — it lets the boundary path itself
    still match.

    Does NOT resolve: callers pass roots that are already canonical (grant
    roots are resolved when the policy is built), and re-resolving here
    would put a filesystem syscall in the agent's per-operation guard.

    :param root: Canonical absolute path, e.g. ``"/data"``.
    :returns: The same path with one trailing separator, e.g. ``"/data/"``.
    """
    text = str(root)
    return text if text.endswith(os.sep) else text + os.sep


def contained_realpath(candidate: str, prefix: str) -> str | None:
    """
    Fully resolve *candidate*, returning it only if it stays under *prefix*.

    Resolution happens BEFORE the comparison, so neither a ``..`` segment nor
    a symlink can aim the final path outside the boundary that admitted it.

    Deliberately ``os.path.realpath`` rather than ``Path.resolve()``: the
    pathlib form is a filesystem access performed through a path object built
    from unchecked input, so it acts on the path before this function can vet
    it. ``realpath`` normalizes the string first. (This is also the shape
    CodeQL's ``py/path-injection`` recognizes as safe — normalize, then test
    the prefix — so the guard is machine-checkable rather than a claim in a
    comment.)

    :param candidate: Path to resolve, e.g. ``"/data/../etc/passwd"``.
    :param prefix: Boundary from :func:`containment_prefix`.
    :returns: The resolved absolute path, or ``None`` when it escapes.
    """
    # Both sides carry a trailing separator for the comparison — that is what
    # keeps a boundary at "/data" from admitting "/database", and what lets the
    # boundary directory itself match. Stripped back off before returning so
    # callers get an ordinary path.
    probe = os.path.realpath(candidate)
    if not probe.endswith(os.sep):
        probe += os.sep
    if probe.startswith(prefix):
        return probe.rstrip(os.sep) or os.sep
    return None


@dataclass(frozen=True)
class ReachableRoot:
    """
    One path an environment's file tools are permitted to reach.

    Produced from runtime policy by :func:`reachable_roots` or from remote
    declarations by :func:`declared_filesystem_reach`. Both use the same
    grant assembly for enforcement and file-browsing metadata.

    :param path: Resolved absolute path of the grant, e.g.
        ``Path("/Users/corey/data")``.
    :param access: ``"write"`` when the grant admits reads and writes,
        ``"read"`` when it admits reads only.
    :param origin: Which declaration produced this grant — ``"cwd"``,
        ``"read_paths"``, ``"write_paths"``, or ``"write_files"``.
        ``"unconfined"`` marks the synthetic filesystem-root grant that
        :func:`omnigent.runner.environment_filesystem.resolve_browse_target`
        adds for an unconfined policy; it is never advertised or returned
        by :func:`reachable_roots`.
        Carried for display; enforcement uses :attr:`kind` and
        :attr:`access`.
    :param kind: ``"tree"`` when the grant covers the subtree rooted at
        :attr:`path`, ``"file"`` when it covers exactly that one path.
    """

    path: Path
    access: str
    origin: str
    kind: str

    @property
    def prefix(self) -> str:
        """
        This grant's boundary in comparison form — the single definition of
        "inside", shared by :meth:`contains` and by the callers that must
        inline the comparison (see :func:`contained_realpath`).

        :returns: :attr:`path` with a trailing separator, e.g. ``"/data/"``.
        """
        return containment_prefix(self.path)

    def contains(self, resolved: Path) -> bool:
        """
        Whether *resolved* falls inside this grant.

        :param resolved: Fully-resolved candidate path.
        :returns: ``True`` when the grant covers it.
        """
        probe = containment_prefix(resolved)
        if not probe.startswith(self.prefix):
            return False
        # A file grant covers exactly one path; equal prefix lengths means the
        # candidate IS that path rather than something notionally beneath it.
        return self.kind == "tree" or len(probe) == len(self.prefix)


def reachable_roots(cwd: Path, policy: SandboxPolicy) -> list[ReachableRoot]:
    """
    Enumerate the paths an environment's file tools may reach.

    Mirrors the grant vocabulary the sandbox backends already populate:
    *cwd* is always reachable for read and write; ``write_paths`` /
    ``write_files`` admit reads and writes of their target; ``read_paths``
    admits reads only. With no grants declared the result is *cwd* alone
    — the historical confinement, unchanged.

    This describes the FILE-TOOL boundary only. It is deliberately not
    widened when the policy is inactive: under ``sandbox.type: none`` the
    co-resident shell is unconfined, but ``sys_os_read`` and friends stay
    confined here on purpose. Callers that browse on a human's behalf
    should consult :func:`is_unconfined` separately rather than expecting
    this list to grow.

    :param cwd: The environment root.
    :param policy: Resolved sandbox policy carrying the declared grants.
    :returns: Grants in precedence order, cwd first. Never empty.
    """
    return _filesystem_reach_roots(
        cwd, policy.write_roots, policy.write_files, policy.read_roots or []
    )


def declared_filesystem_reach(cwd: Path, spec: OSEnvSpec) -> tuple[list[ReachableRoot], bool]:
    """Describe declared file grants without preparing a local sandbox.

    Remote metadata readers need neither sandbox binaries nor runtime mounts.
    Only an explicitly unconfined spec permits browsing beyond these grants.

    :returns: Declared reachable roots and whether the spec is unconfined.
    """
    sandbox = spec.sandbox
    if sandbox is None:
        return _filesystem_reach_roots(cwd, [], [], []), False
    return (
        _filesystem_reach_roots(
            cwd,
            [_resolve_grant_root(cwd, grant.path) for grant in sandbox.write_path_specs],
            [_resolve_grant_root(cwd, root) for root in sandbox.write_files or []],
            [_resolve_grant_root(cwd, root) for root in sandbox.read_paths or []],
        ),
        sandbox.type == "none",
    )


def _filesystem_reach_roots(
    cwd: Path,
    write_roots: Sequence[Path],
    write_files: Sequence[Path],
    read_roots: Sequence[Path],
) -> list[ReachableRoot]:
    # Resolving cwd is what makes the grants comparable to a resolved
    # candidate path. Callers pass a root that is already contained — see
    # `_session_workspace` / `compute_default_env_root`, which vet it against
    # the runner workspace before it ever reaches here.
    roots = [ReachableRoot(path=cwd.resolve(), access="write", origin="cwd", kind="tree")]
    roots += [
        ReachableRoot(path=root, access="write", origin="write_paths", kind="tree")
        for root in write_roots
    ]
    roots += [
        ReachableRoot(path=grant, access="write", origin="write_files", kind="file")
        for grant in write_files
    ]
    roots += [
        ReachableRoot(path=root, access="read", origin="read_paths", kind="tree")
        for root in read_roots
    ]
    return roots


def reach_payload(roots: Sequence[ReachableRoot], *, unconfined: bool) -> dict[str, object]:
    """
    JSON-ready description of what an environment's file browsing can reach.

    The single definition of this wire shape. Both producers use it — the
    runner when the agent is awake, and the server when it synthesizes the
    environment for a sleeping agent — so a browser cannot be told one thing
    by one and something else by the other.

    :param roots: Grants from :func:`reachable_roots`.
    :param unconfined: Result of :func:`is_unconfined`.
    :returns: ``{"unconfined": bool, "roots": [{"path", "access", "origin"}]}``.
    """
    return {
        "unconfined": unconfined,
        "roots": [
            {"path": str(root.path), "access": root.access, "origin": root.origin}
            for root in roots
        ],
    }


def is_unconfined(policy: SandboxPolicy) -> bool:
    """
    Whether the policy leaves the environment without OS-level confinement.

    ``True`` for ``sandbox.type: none``, where no bwrap / seatbelt wrap is
    applied and the environment's shell runs with the caller's own
    privileges. File *tools* remain confined to :func:`reachable_roots`
    regardless; this reports only that the process itself is not boxed in,
    which is what lets a human-facing browser show paths the shell could
    already read anyway.

    :param policy: Resolved sandbox policy.
    :returns: ``True`` when no sandbox backend is active.
    """
    return not policy.active


def activate_sandbox(policy: SandboxPolicy) -> None:
    if not policy.active:
        return
    _get_backend(policy.backend_type).activate(policy)


def _clone_policy_with(
    policy: SandboxPolicy,
    *,
    read_roots: list[Path] | None,
    write_roots: list[Path],
    write_files: list[Path],
    mask_scan_skip_roots: list[Path] | None = None,
) -> SandboxPolicy:
    """
    Build a new :class:`SandboxPolicy` with the supplied root/file
    lists, copying the rest of the fields from *policy* unchanged.

    The ``with_additional_*`` helpers only ever change one of the
    three list fields; centralising the clone keeps every field on
    :class:`SandboxPolicy` (including newer additions like
    ``env_passthrough``) automatically preserved across all three
    helpers without each one redeclaring every constructor arg.
    """
    return SandboxPolicy(
        copy_on_write_roots=list(policy.copy_on_write_roots)
        if policy.copy_on_write_roots
        else None,
        copy_on_write_namespace=policy.copy_on_write_namespace,
        backend_type=policy.backend_type,
        active=policy.active,
        read_roots=read_roots,
        write_roots=write_roots,
        write_files=write_files,
        allow_network=policy.allow_network,
        cwd_allow_hidden=(
            list(policy.cwd_allow_hidden) if policy.cwd_allow_hidden is not None else None
        ),
        cwd_hidden_scan_max_entries=policy.cwd_hidden_scan_max_entries,
        cwd_hidden_scan_overflow=policy.cwd_hidden_scan_overflow,
        cwd_hidden_scan_recursive=policy.cwd_hidden_scan_recursive,
        mask_paths=(list(policy.mask_paths) if policy.mask_paths is not None else None),
        env_passthrough=(
            list(policy.env_passthrough) if policy.env_passthrough is not None else None
        ),
        spawn_env_allowlist=(
            list(policy.spawn_env_allowlist) if policy.spawn_env_allowlist is not None else None
        ),
        bind_host_proc=policy.bind_host_proc,
        egress_relay_port=policy.egress_relay_port,
        egress_socket_path=policy.egress_socket_path,
        git_ssh_socket_path=policy.git_ssh_socket_path,
        deny_unix_socket_paths=(
            list(policy.deny_unix_socket_paths)
            if policy.deny_unix_socket_paths is not None
            else None
        ),
        # CORAL(S112)
        deny_unix_socket_roots=(
            list(policy.deny_unix_socket_roots)
            if policy.deny_unix_socket_roots is not None
            else None
        ),
        credential_source_paths=(
            list(policy.credential_source_paths)
            if policy.credential_source_paths is not None
            else None
        ),
        # CORAL(S109)
        launch_tmpdir_env=policy.launch_tmpdir_env,
        launch_tmpdir_parent=policy.launch_tmpdir_parent,
        # CORAL(S113)
        scratch_dir_env=policy.scratch_dir_env,
        scratch_dir_files=policy.scratch_dir_files,
        scratch_dir_extra_envs=policy.scratch_dir_extra_envs,
        scratch_dir_seed=policy.scratch_dir_seed,  # CORAL(S115)
        # Preserve the credential-proxy policy across clones: the
        # ``with_additional_*`` helpers run before the parent reads it in
        # ``_start_locked``, so dropping it here would silently disable
        # the feature.
        credential_proxy=policy.credential_proxy,
        git_ssh=policy.git_ssh,
        # Preserve (or, when a helper is extending it, override) the set
        # of framework write roots excluded from the mask scan. ``None``
        # from a caller means "keep whatever the source policy carried".
        mask_scan_skip_roots=(
            list(mask_scan_skip_roots)
            if mask_scan_skip_roots is not None
            else (
                list(policy.mask_scan_skip_roots)
                if policy.mask_scan_skip_roots is not None
                else None
            )
        ),
        private_tmpdir=policy.private_tmpdir,  # CORAL(S112)
    )


def with_additional_write_roots(
    policy: SandboxPolicy,
    extra_roots: Sequence[Path],
) -> SandboxPolicy:
    write_roots = list(policy.write_roots)
    skip_roots = (
        list(policy.mask_scan_skip_roots) if policy.mask_scan_skip_roots is not None else []
    )
    for root in extra_roots:
        resolved = root.resolve(strict=False)
        if all(existing != resolved for existing in write_roots):
            write_roots.append(resolved)
        # Framework-added write roots hold the sandbox's own runtime
        # scaffolding (scratch tmpdir with the egress ``.egress.sock``, CA
        # bundle, credential-proxy files, harness state dirs), never
        # pre-existing user secrets. Record them so the dotfile mask scan
        # skips them — otherwise the scan hides ``.egress.sock`` and the
        # egress relay's connection is reset.
        if all(existing != resolved for existing in skip_roots):
            skip_roots.append(resolved)
    return _clone_policy_with(
        policy,
        read_roots=list(policy.read_roots) if policy.read_roots is not None else None,
        write_roots=write_roots,
        write_files=list(policy.write_files),
        mask_scan_skip_roots=skip_roots,
    )


def _restore_broker_socket_roots(policy: SandboxPolicy) -> SandboxPolicy:
    roots = [
        Path(path).parent
        for path in (policy.egress_socket_path, policy.git_ssh_socket_path)
        if path is not None
    ]
    return with_additional_write_roots(policy, roots) if roots else policy


def with_additional_read_roots(
    policy: SandboxPolicy,
    extra_roots: Sequence[Path],
) -> SandboxPolicy:
    # ``read_roots=None`` means "no spec-supplied grants" for deny-default
    # backends (darwin_seatbelt, linux_bwrap). Treat it as an empty list so
    # caller-supplied extra roots (e.g. the pi node_modules dir granted by
    # _try_sandbox_pi) are not silently dropped when the spec declares no
    # read_paths. Do NOT short-circuit: the caller is explicitly widening the
    # policy, so we must honour it even when the spec itself has no grants.
    read_roots = list(policy.read_roots) if policy.read_roots is not None else []
    for root in extra_roots:
        resolved = root.resolve(strict=False)
        if all(existing != resolved for existing in read_roots):
            read_roots.append(resolved)

    return _clone_policy_with(
        policy,
        read_roots=read_roots,
        write_roots=list(policy.write_roots),
        write_files=list(policy.write_files),
    )


def with_additional_write_files(
    policy: SandboxPolicy,
    extra_files: Sequence[Path],
) -> SandboxPolicy:
    write_files = list(policy.write_files)
    for path in extra_files:
        resolved = path.resolve(strict=False)
        if all(existing != resolved for existing in write_files):
            write_files.append(resolved)
    return _clone_policy_with(
        policy,
        read_roots=list(policy.read_roots) if policy.read_roots is not None else None,
        write_roots=list(policy.write_roots),
        write_files=write_files,
    )


def with_spawn_env_allowlist(
    policy: SandboxPolicy,
    names: Sequence[str] | None,
) -> SandboxPolicy:
    """
    Return a copy of *policy* with :attr:`SandboxPolicy.spawn_env_allowlist`
    set to *names*, so :func:`run_launcher` prunes its inherited
    environment to exactly that set before exec-ing the target.

    :param policy: The resolved policy to augment. Returned unchanged
        (same object) when *names* is ``None``.
    :param names: The environment-variable names the spawning executor
        deliberately passes in the launcher subprocess's ``env=``,
        e.g. ``[*clean_env, "PI_CODING_AGENT_DIR"]``. Deduplicated and
        sorted for a deterministic wire encoding.
    :returns: The augmented policy copy, or *policy* when *names* is
        ``None``.
    """
    if names is None:
        return policy
    return replace(policy, spawn_env_allowlist=sorted(set(names)))


def with_denied_unix_sockets(
    policy: SandboxPolicy,
    sockets: Sequence[Path],
) -> SandboxPolicy:
    """
    Return *policy* extended with AF_UNIX sockets the helper may not
    ``connect(2)`` to.

    See :attr:`SandboxPolicy.deny_unix_socket_paths`. Paths are resolved
    (non-strict, sockets may not exist yet at policy-build time) and
    de-duplicated. Called before the egress proxy is wired up, so the
    egress relay fields are still unset and preserved as-is.

    :param policy: The base policy to extend.
    :param sockets: Absolute (or resolvable) AF_UNIX socket paths to deny.
    :returns: A new :class:`SandboxPolicy` carrying the merged deny list.
    """
    # CORAL(S112): shares its resolve-and-dedupe step with the root form
    return replace(
        policy, deny_unix_socket_paths=_merged_resolved(policy.deny_unix_socket_paths, sockets)
    )


def _resolved_path(path: Path) -> Path:
    """
    CORAL(S112): as ``Path.resolve(strict=False)``, but never raises.

    A symlink loop keeps its path. A path swapped while it resolves (``realpath`` does not
    guard ``readlink``) keeps its plain normalised spelling; the profile builder resolves
    it again and fails closed if it still cannot.
    """
    try:
        return Path(os.path.realpath(path))
    except OSError:
        return Path(os.path.normpath(path))


# CORAL(S112): one resolve-and-dedupe step for the socket and root deny lists
def _merged_resolved(existing: list[Path] | None, paths: Sequence[Path]) -> list[Path]:
    merged = list(existing) if existing else []
    for path in paths:
        resolved = _resolved_path(path)
        if resolved not in merged:
            merged.append(resolved)
    return merged


# CORAL(S112): the directory form of with_denied_unix_sockets
def with_denied_unix_socket_roots(policy: SandboxPolicy, roots: Sequence[Path]) -> SandboxPolicy:
    """
    Return *policy* extended with directories under which no AF_UNIX connect is allowed.

    See :attr:`SandboxPolicy.deny_unix_socket_roots`. Roots are resolved (non-strict; a root
    may not exist yet) and de-duplicated; *policy* is not mutated.
    """
    return replace(
        policy, deny_unix_socket_roots=_merged_resolved(policy.deny_unix_socket_roots, roots)
    )


def _harness_socket_roots() -> list[Path]:
    """
    CORAL(S112): this process's harness socket root, then the per-user default.

    Never raises, so a bad setting cannot fail :func:`resolve_sandbox` into an unsandboxed
    run: a configured root that cannot be resolved (``~nosuchuser``, a relative root in a
    deleted cwd) is left out with a warning, and the default is always kept. A relative root,
    or one holding the temp or home dir, is kept with a warning.
    """
    try:
        from omnigent.runtime.harnesses.paths import (
            HARNESS_TMP_PARENT_ENV_VAR,
            harness_tmp_parent,
            resolve_harness_tmp_parent,
        )
    except ImportError:  # the profile builder still denies the default root
        return []

    roots: list[Path] = []
    setting = os.environ.get(HARNESS_TMP_PARENT_ENV_VAR, "")
    try:
        configured = _resolved_path(resolve_harness_tmp_parent())
        # CORAL(S112)
        if configured.is_symlink():
            _warn_once(setting, "The harness socket root is a symlink loop; denying it as spelled")
        elif not harness_tmp_parent().is_absolute() or _holds_temp_or_home(configured):
            _warn_once(setting, "The harness socket root is relative or holds the temp or home")
        roots.append(configured)
    except (OSError, RuntimeError) as exc:
        _warn_once(
            setting,
            "Cannot resolve the configured harness socket root (%s); denying the default only",
            type(exc).__name__,
        )
    default = _resolved_path(resolve_harness_tmp_parent({}))
    return roots if default in roots else [*roots, default]


# CORAL(S112): each (setting, message) is logged once per process, not on every resolve_sandbox
_WARNED_ROOT_SETTINGS: set[tuple[str, str]] = set()


def _warn_once(setting: str, message: str, *args: object) -> None:
    if (setting, message) not in _WARNED_ROOT_SETTINGS:
        _WARNED_ROOT_SETTINGS.add((setting, message))
        logger.warning(message, *args)


def _holds_temp_or_home(root: Path) -> bool:
    """CORAL(S112): a deny under such a root would also hit the policy's own broker sockets."""
    try:
        anchors = [Path(tempfile.gettempdir()), Path("/tmp"), Path.home()]
    except (OSError, RuntimeError):
        anchors = [Path("/tmp")]
    return any(_resolved_path(anchor).is_relative_to(root) for anchor in anchors)


def _prune_environ_to_spawn_allowlist(sandbox: SandboxPolicy) -> None:
    """
    Drop every variable not named in
    :attr:`SandboxPolicy.spawn_env_allowlist` from ``os.environ``.

    Defense in depth against host-env leakage: the spawning executor
    already passes a filtered ``env=`` to the launcher subprocess, so on
    the normal path this is a no-op — it only bites when a spawn site
    regresses to inheriting the full host environment. It runs before
    the spawn-time re-exec, so the wrap (``bwrap`` / ``sandbox-exec``)
    and the in-sandbox ``subprocess.run`` both inherit only the pruned
    set. ``--clearenv`` + ``--setenv`` on the bwrap argv was rejected
    for this purpose: argv values are world-readable via
    ``/proc/<pid>/cmdline``, the same channel that got
    ``egress_auth_token`` removed (see the class docstring).

    :param sandbox: The decoded launcher policy. No-op when its
        ``spawn_env_allowlist`` is ``None``. The internal launcher
        markers (:data:`_LAUNCHER_WRAPPED_ENV`,
        :data:`_SANDBOX_STRACE_ENV`,
        :data:`_LAUNCHER_PRIVATE_TMPDIR_ENV`) are always retained —
        dropping the tmpdir marker would make the in-wrap pass mint a
        second scratch dir the profile never granted.
    """
    if sandbox.spawn_env_allowlist is None:
        return
    allowed = set(sandbox.spawn_env_allowlist) | {
        _LAUNCHER_WRAPPED_ENV,
        _SANDBOX_STRACE_ENV,
        _LAUNCHER_PRIVATE_TMPDIR_ENV,
        _LAUNCHER_LAUNCH_TMPDIR_ENV,  # CORAL(S109)
    }
    if sandbox.launch_tmpdir_env is not None:
        allowed.add(sandbox.launch_tmpdir_env)  # CORAL(S109)
    for name in list(os.environ):
        if name not in allowed:
            del os.environ[name]


def create_private_tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="omnigent-osenv-"))


def with_private_tmpdir(policy: SandboxPolicy, tmpdir: Path) -> SandboxPolicy:
    """CORAL(S112): grant *tmpdir* and record it as the scratch the child gets as ``$TMPDIR``."""
    granted = with_additional_write_roots(policy, [tmpdir])
    return replace(granted, private_tmpdir=tmpdir.resolve(strict=False))


def set_sandbox_env(env: MutableMapping[str, str], tmpdir: Path) -> None:
    """Give sandboxed tools private scratch/runtime storage and no host desktop bus."""
    for key in DESKTOP_SESSION_ENV_VARS:
        env.pop(key, None)
    set_temp_env(env, tmpdir)
    env["XDG_RUNTIME_DIR"] = str(tmpdir)


def set_temp_env(env: MutableMapping[str, str], tmpdir: Path) -> None:
    tmp_value = str(tmpdir)
    for key in ("TMPDIR", "TMP", "TEMP", "TEMPDIR"):
        env[key] = tmp_value


def cleanup_private_tmpdir(tmpdir: Path | None) -> None:
    if tmpdir is None:
        return
    shutil.rmtree(tmpdir, ignore_errors=True)


def with_launch_tmpdir(policy: SandboxPolicy, env_name: str, parent: Path) -> SandboxPolicy:
    """CORAL(S109): give each launch's target its own dir under ``parent``, in ``env_name``."""
    return replace(policy, launch_tmpdir_env=env_name, launch_tmpdir_parent=parent)


# CORAL(S113): an environment variable name, which also names the dir in the scratch
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
# CORAL(S113): the only variables a payload may point at its private dir
_SCRATCH_DIR_ENVS = frozenset({"CLAUDE_CONFIG_DIR", "CLAUDE_SECURESTORAGE_CONFIG_DIR"})
# CORAL(S113): a plain entry name in that dir, never a path
_SCRATCH_ENTRY_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")


def _all_match(values: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(values, (list, tuple)) and all(
        isinstance(value, str) and pattern.fullmatch(value) for value in values
    )


def _check_scratch_dir(
    env_name: object,
    files: object,
    extra_envs: object = (),
    seed: object = (),  # CORAL(S115)
) -> None:
    """CORAL(S113): raise ``ValueError`` unless these name a private dir, its files and envs."""
    if not _all_match([env_name], _ENV_NAME) or not _all_match(extra_envs, _ENV_NAME):
        raise ValueError("scratch_dir_env names must be upper-case environment variable names")
    if not {env_name, *extra_envs} <= _SCRATCH_DIR_ENVS:  # type: ignore[misc]
        raise ValueError("scratch_dir_env names must be Claude config dir variables")
    if not _all_match(files, _SCRATCH_ENTRY_NAME):
        raise ValueError("scratch_dir_files must be plain file names")
    if not _is_scratch_seed(seed, cast("list[str]", files)):  # CORAL(S115)
        raise ValueError(
            "scratch_dir_seed must pair distinct file names with absolute normalized sources"
        )


# CORAL(S115): a seed copy's name in the private dir; a leading dot is allowed (".claude.json")
_SCRATCH_SEED_NAME = re.compile(r"\.?[A-Za-z0-9_][A-Za-z0-9._-]*")


def _is_scratch_seed(seed: object, files: Sequence[str]) -> bool:
    """CORAL(S115): ``(name, source)`` pairs with unique names that no listed file takes."""
    if not isinstance(seed, (list, tuple)):
        return False
    names: list[str] = []
    for pair in seed:
        if not (
            isinstance(pair, (list, tuple))
            and len(pair) == 2
            and all(isinstance(part, str) for part in pair)
        ):
            return False
        name, source = pair
        if not _SCRATCH_SEED_NAME.fullmatch(name) or not os.path.isabs(source):
            return False
        if os.path.normpath(source) != source:
            return False
        names.append(name)
    return len(set(names)) == len(names) and not set(names) & set(files)


def with_scratch_dir_env(
    policy: SandboxPolicy,
    env_name: str,
    *,
    files: Sequence[str] = (),
    extra_envs: Sequence[str] = (),
    seed: Sequence[tuple[str, Path | str]] = (),  # CORAL(S115)
) -> SandboxPolicy:
    """
    CORAL(S113): give the target a private dir in its scratch, named in ``env_name``.

    CORAL(S115): ``seed`` names files copied into it at launch; each source becomes a read root.
    """
    # A relative source is left as it is, so the check refuses it.
    pairs = tuple(
        (name, str(Path(source).resolve(strict=False) if os.path.isabs(source) else source))
        for name, source in seed
    )
    _check_scratch_dir(env_name, files, extra_envs, pairs)
    if pairs:
        policy = with_additional_read_roots(policy, [Path(source) for _, source in pairs])
    return replace(
        policy,
        scratch_dir_env=env_name,
        scratch_dir_files=tuple(files),
        scratch_dir_extra_envs=tuple(extra_envs),
        scratch_dir_seed=pairs,  # CORAL(S115)
    )


def open_regular_file(path: Path, *, follow_symlinks: bool = False) -> BinaryIO:
    """
    CORAL(S115): open *path* for reading only if it is a regular file.

    A FIFO or device is opened without blocking and refused, and so is a symlink unless
    *follow_symlinks*.

    :raises OSError: If *path* is missing, a refused link or not a regular file.
    """
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC
    descriptor = os.open(path, flags if follow_symlinks else flags | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError(errno.EINVAL, "Not a regular file", str(path))
        os.set_blocking(descriptor, True)
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _copy_seed_file(source: Path, target: Path) -> None:
    """
    CORAL(S115): copy a regular seed file, never a link or a FIFO, to a new 0600 file.

    The seed must be this user's and writable by no one else, so no other account can plant it.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    with open_regular_file(source) as reader:
        info = os.fstat(reader.fileno())
        if info.st_uid != os.getuid() or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise OSError(errno.EPERM, "The seed is not this user's private file", str(source))
        with open(os.open(target, flags, 0o600), "wb") as writer:
            shutil.copyfileobj(reader, writer)


# CORAL(S115): a CLI version query's arguments, as in the Agent SDK's check of the CLI
_VERSION_QUERY_ARGVS = (["-v"], ["--version"])


def export_scratch_dir(
    policy: SandboxPolicy,
    scratch: Path | None,
    *,
    copy_seed: bool = True,  # CORAL(S115)
) -> None:
    """
    CORAL(S113): create the policy's private dir in ``scratch`` and name it to the target.

    It overwrites an inherited value of each variable. Without a scratch it raises rather than
    let the target fall back to a default location.

    :param copy_seed: CORAL(S115): ``False`` leaves the seed copies out of the dir.
    """
    if policy.scratch_dir_env is None:
        return
    if scratch is None:
        raise RuntimeError("The launcher has no scratch dir for the target's private dir")
    path = Path(os.path.abspath(scratch)) / policy.scratch_dir_env.lower()
    path.mkdir(mode=0o700)
    for name, source in policy.scratch_dir_seed if copy_seed else ():  # CORAL(S115)
        _copy_seed_file(Path(source), path / name)
    for name in policy.scratch_dir_files:
        (path / name).touch(mode=0o600, exist_ok=False)
    for env_name in (policy.scratch_dir_env, *policy.scratch_dir_extra_envs):
        os.environ[env_name] = str(path)


# CORAL(S109): launch dirs are ``mkdtemp(prefix="c")`` names holding this owner claim.
_LAUNCH_TMPDIR_NAME = re.compile(r"c[a-z0-9_]{8}")
_LAUNCH_TMPDIR_OWNER = ".launch-owner"
# CORAL(S116): on seatbelt, the target a launcher started, which can outlive it; the target's
# claim is removed first, so a dir left between the two removals still names its owner
_LAUNCH_TARGET_CLAIM = ".launch-target"
_CLAIM_NAMES = (_LAUNCH_TARGET_CLAIM, _LAUNCH_TMPDIR_OWNER)
# CORAL(S116): a launch scratch's name, as create_private_tmpdir makes it
PRIVATE_TMPDIR_NAME = re.compile(r"omnigent-osenv-[a-z0-9_]{8}")
# CORAL(S116): one sweep's share of the work; the next sweep goes on from there
_SWEEP_SECONDS = 2.0
_SWEEP_MAX_REMOVALS = 64
# CORAL(S116): a dead tree nested deeper is left and counted, never descended
_SWEEP_MAX_DEPTH = 64


class _SweepStopped(Exception):
    """CORAL(S116): a dir's removal reached the sweep's deadline, or its depth cap."""

    def __init__(self, *, too_deep: bool) -> None:
        super().__init__("too deep" if too_deep else "out of time")
        self.too_deep = too_deep


def claim_temp_dir(
    path: Path, *, filename: str = _LAUNCH_TMPDIR_OWNER, pid: int | None = None
) -> None:
    """
    CORAL(S116): name *path*'s owner, this process by default, so a sweep removes it once gone.

    *pid* names another process. A failure, or a platform without owner uids, leaves the dir
    unclaimed and never swept; it never raises.
    """
    from omnigent.native.owner_claim import create_owner_claim

    if not hasattr(os, "getuid"):
        return
    try:
        create_owner_claim(path, filename=filename, pid=pid)
    except OSError as exc:
        logger.warning("Cannot record a temp dir's owner (%s)", type(exc).__name__)


def _claimed_process_alive(pid: int) -> bool:
    """
    CORAL(S116): whether *pid* may still run; only ``ESRCH`` or a zombie seen as one is gone.

    ``EPERM``, or a process the kernel finds but psutil cannot see (``/proc`` hides it),
    counts as alive.
    """
    import psutil  # type: ignore[import-untyped]

    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OverflowError):
        return False
    except OSError:
        return True
    try:
        return bool(psutil.Process(pid).status() != psutil.STATUS_ZOMBIE)
    except psutil.ZombieProcess:
        return False
    except psutil.Error:
        return True


def _is_private_dir(path: Path) -> bool:
    """CORAL(S109): a real directory, not a symlink, owned by this uid with mode 0700."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o700
    )


def _is_orphaned(child: Path) -> bool:
    """CORAL(S116): a private dir whose claimed owner, and recorded target if any, are gone."""
    from omnigent.native.owner_claim import owner_is_gone, read_owner_claim

    if not _is_private_dir(child):
        return False
    for filename in _CLAIM_NAMES:
        if filename != _LAUNCH_TMPDIR_OWNER and not os.path.lexists(child / filename):
            continue
        claim = read_owner_claim(child, filename=filename)
        if claim is None or not owner_is_gone(claim, process_alive=_claimed_process_alive):
            return False
    return True


def _remove_entry(parent: int, name: str, deadline: float, depth: int) -> None:
    """
    CORAL(S116): remove *name* in the dir at *parent* bottom-up, never following a link.

    :raises _SweepStopped: At *deadline*, or below the depth cap; what is left stays.
    :raises OSError: If an entry cannot be removed, or changed while open.
    """
    if time.monotonic() >= deadline:
        raise _SweepStopped(too_deep=False)
    info = os.lstat(name, dir_fd=parent)
    if not stat.S_ISDIR(info.st_mode):
        os.unlink(name, dir_fd=parent)
        return
    if depth >= _SWEEP_MAX_DEPTH:
        raise _SweepStopped(too_deep=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    descriptor = os.open(name, flags, dir_fd=parent)
    try:
        if not os.path.samestat(info, os.fstat(descriptor)):
            raise OSError(errno.EAGAIN, "The entry changed")
        with os.scandir(descriptor) as entries:
            names = [entry.name for entry in entries]
        for child in names:
            _remove_entry(descriptor, child, deadline, depth + 1)
    finally:
        os.close(descriptor)
    os.rmdir(name, dir_fd=parent)


def _empty_but_claims(descriptor: int, deadline: float | None) -> bool:
    """
    CORAL(S116): remove every entry but the claims from the dir at *descriptor*.

    With a *deadline* the removal is bounded (it raises :class:`_SweepStopped`); without one
    it goes as deep as needed. Returns whether only claims are left.
    """
    failed = False

    def _failed(*_args: object) -> None:
        nonlocal failed
        failed = True

    with os.scandir(descriptor) as entries:
        names = [entry.name for entry in entries if entry.name not in _CLAIM_NAMES]
    for name in names:
        try:
            if deadline is not None:
                _remove_entry(descriptor, name, deadline, 1)
            elif stat.S_ISDIR(os.lstat(name, dir_fd=descriptor).st_mode):
                shutil.rmtree(name, dir_fd=descriptor, onexc=_failed)
            else:
                os.unlink(name, dir_fd=descriptor)
        except OSError:
            failed = True
    with os.scandir(descriptor) as entries:
        return not failed and not any(entry.name not in _CLAIM_NAMES for entry in entries)


def _remove_claimed_dir(child: Path, deadline: float | None, *, keep_claims: bool = False) -> bool:
    """
    CORAL(S116): empty *child* but for its claims, then remove those and the dir.

    Entries go relative to the dir's descriptor, so a swapped link is never followed. A
    failure, the deadline or *keep_claims* keeps the claims; if the dir cannot go once they
    are gone, they are put back. Either way the next sweep tries again.
    """
    from omnigent.native.owner_claim import create_owner_claim, read_owner_claim_bytes

    descriptor = os.open(child, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            return False
        if not _empty_but_claims(descriptor, deadline) or keep_claims:
            return False
        saved = {name: read_owner_claim_bytes(child, filename=name) for name in _CLAIM_NAMES}
        for name in _CLAIM_NAMES:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name, dir_fd=descriptor)
        try:
            os.rmdir(child)
        except OSError:
            # A late writer: the claims go back, owner first, so the dir is retried.
            for name, data in reversed(saved.items()):
                if data is not None:
                    with contextlib.suppress(OSError):
                        create_owner_claim(child, filename=name, data=data, dir_fd=descriptor)
            return False
    finally:
        os.close(descriptor)
    return True


def _remove_orphaned_launch_tmpdirs(
    parent: Path, name: re.Pattern[str] = _LAUNCH_TMPDIR_NAME, *, deadline: float | None = None
) -> None:
    """
    CORAL(S109): remove launch dirs left by launchers that died before their cleanup.

    CORAL(S116): *name* picks the children; S109's call keeps the default. A child goes only
    when it is this user's 0700 dir whose claimed owner, and recorded target, are gone, and
    its claims go last. The sweep stops at *deadline* (default two seconds from now) or after
    a fixed number of removals, does nothing without owner uids, and never raises.
    """
    if not hasattr(os, "getuid"):
        return
    if deadline is None:
        deadline = time.monotonic() + _SWEEP_SECONDS
    removed = kept = too_deep = 0
    try:
        with os.scandir(parent) as entries:
            for entry in entries:
                if time.monotonic() >= deadline or removed >= _SWEEP_MAX_REMOVALS:
                    break
                if not name.fullmatch(entry.name):
                    continue
                child = Path(entry.path)
                try:
                    if not _is_orphaned(child):
                        continue
                    if _remove_claimed_dir(child, deadline):
                        removed += 1
                    else:
                        kept += 1
                except _SweepStopped as stop:
                    kept += 1
                    too_deep += stop.too_deep
                    if not stop.too_deep:
                        break
                except FileNotFoundError:
                    continue  # another sweep removed it first
                except Exception as exc:  # noqa: BLE001 — one bad dir must not stop the rest
                    logger.warning("Cannot sweep a temp dir (%s)", type(exc).__name__)
    except OSError:
        return
    except Exception as exc:  # noqa: BLE001 — callers run it in teardown
        logger.warning("Cannot sweep the temp dirs (%s)", type(exc).__name__)
    if removed or kept:
        logger.debug(
            "Removed %d orphaned temp dirs; kept %d to retry, %d too deep", removed, kept, too_deep
        )


def create_launch_tmpdir(policy: SandboxPolicy) -> Path | None:
    """
    CORAL(S109): a fresh 0700 dir under the policy's launch parent, or ``None``.

    ``None`` when the policy asks for none, or when the parent is not this user's private
    directory (a symlink, another owner, or a mode other than 0700): someone else could then
    swap the dir before the grant resolves it. The dir records its launcher as owner, and
    siblings whose launcher is gone are removed first.
    """
    from omnigent.native.owner_claim import create_owner_claim  # CORAL(S116)

    parent = policy.launch_tmpdir_parent
    if policy.launch_tmpdir_env is None or parent is None:
        return None
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Cannot create the launch temp dirs' parent (%s)", type(exc).__name__)
        return None
    if not _is_private_dir(parent):
        logger.warning("Not creating a launch temp dir: its parent is not a private directory")
        return None
    _remove_orphaned_launch_tmpdirs(parent)
    launch_tmpdir: Path | None = None
    try:
        launch_tmpdir = Path(tempfile.mkdtemp(prefix="c", dir=parent))
        # CORAL(S116): a new file, never written through an entry planted in the fresh dir
        create_owner_claim(launch_tmpdir, filename=_LAUNCH_TMPDIR_OWNER)
    except OSError as exc:
        logger.warning("Cannot create a launch temp dir (%s)", type(exc).__name__)
        cleanup_private_tmpdir(launch_tmpdir)
        return None
    return launch_tmpdir


def run_launcher(
    encoded_sandbox: str, target_path: str, argv: list[str], *, cwd: str | None = None
) -> int:
    """
    Activate the sandbox and exec the wrapped target inside it.

    Runs in the launcher process (spawned by the parent spawn site, or
    re-exec'd under ``bwrap`` / ``sandbox-exec`` for spawn-time-wrap
    backends). Decodes the policy, optionally re-execs self under the
    backend wrap, activates the sandbox, then runs *target_path* with
    *argv* and returns its exit code.

    First strips the runner-auth secret from ``os.environ`` so it reaches
    neither the bwrap re-exec nor the final ``subprocess.run`` (both
    inherit ``os.environ``): the runner tunnel binding token must never
    reach the agent's target.

    :param encoded_sandbox: JSON-encoded :class:`SandboxPolicy`, as
        produced by ``_encode_json_arg(sandbox.to_jsonable())``.
    :param target_path: Absolute path to the wrapped executable to run
        inside the sandbox, e.g. ``"/usr/bin/python3"``.
    :param argv: Arguments passed to *target_path* (the launcher's own
        ``sys.argv[1:]``).
    :returns: The target process's exit code.
    :raises ValueError: If *encoded_sandbox* does not decode to a dict.
    """
    from omnigent.sandbox.copy_on_write import SHARED_ENVIRONMENT_VAR

    os.environ.pop(SHARED_ENVIRONMENT_VAR, None)
    for secret_name in RUNNER_AUTH_SECRET_ENV_VARS:
        os.environ.pop(secret_name, None)

    decoded = _decode_json_arg(encoded_sandbox)
    if not isinstance(decoded, dict):
        raise ValueError("Invalid launcher sandbox payload")
    # The JSON policy omits parent-owned mask exemptions; recover the
    # broker dirs before bwrap scans dotfiles and hides their sockets.
    sandbox = _restore_broker_socket_roots(SandboxPolicy.from_jsonable(decoded))

    # Older launcher payloads may not have frozen host-local choices. Resolve
    # them only on the host-side pass; the re-encoded policy carries the result.
    if (
        sandbox.active
        and sandbox.backend_type in _SPAWN_WRAP_BACKENDS
        and os.environ.get(_LAUNCHER_WRAPPED_ENV) != "1"
    ):
        sandbox = get_backend(sandbox.backend_type).prepare_launcher_policy(sandbox)

    # Unsandboxed children may launch their own runner and still need the hint.
    if sandbox.active:
        os.environ.pop(HOST_SANDBOX_BACKEND_ENV, None)

    # Before any wrap / exec so neither the re-exec'd launcher nor the target
    # can see env vars the spawner didn't deliberately pass.
    _prune_environ_to_spawn_allowlist(sandbox)
    launch_tmpdir: Path | None = None  # CORAL(S109)

    # Spawn-time wrap re-exec for backends whose sandbox enforcement
    # is installed by the spawning process (``bwrap`` /
    # ``sandbox-exec``).
    # Previously every caller of ``create_exec_launcher`` outside
    # :class:`_HelperProcessClient` (notably the tmux terminal path)
    # skipped the wrap entirely — the launcher script ran in the
    # host namespace with no enforcement.
    # On macOS seatbelt and Linux bwrap, that collapsed to ZERO
    # sandboxing for the spawned target.
    #
    # We re-exec self under ``backend.wrap_launcher_argv``. The
    # wrapped invocation re-enters this function (via the launcher
    # script's ``__main__``) but ``_LAUNCHER_WRAPPED_ENV`` breaks the loop
    # and we proceed to the in-process ``activate_sandbox`` +
    # ``subprocess.run`` path. The wrap inherits HTTP_PROXY / CA
    # env vars set by the parent (terminal path) so the relay
    # daemon spun up by ``activate_sandbox`` is reachable.
    if (
        sandbox.active
        and sandbox.backend_type in _SPAWN_WRAP_BACKENDS
        and os.environ.get(_LAUNCHER_WRAPPED_ENV) != "1"
    ):
        backend = get_backend(sandbox.backend_type)
        # Mint the private scratch tmpdir HERE, on the host, before the
        # wrap is built — the reference pattern from
        # ``_HelperProcessClient._start_locked``. The wrap bakes the
        # sandbox profile (seatbelt SBPL / bwrap binds) from ``sandbox``
        # right now, so the scratch dir has to be a write root *before*
        # that snapshot or the profile never grants it. Deferring the
        # ``create_private_tmpdir`` to the in-wrap pass (as before) left
        # the in-jail ``mkdtemp`` targeting ``$TMPDIR`` = the system
        # tempdir root, which the profile only granted a subpath of —
        # ``FileNotFoundError: No usable temporary directory`` on
        # seatbelt (bwrap masked it via its ``--tmpfs /tmp`` fallback).
        host_tmpdir = create_private_tmpdir()
        # CORAL(S116): owned by this pid, which the wrap's exec keeps, in the spawner's pid
        # namespace; claimed at once, before S109's sweep below
        claim_temp_dir(host_tmpdir)
        # CORAL(S109): this launch's own target dir, granted here and removed in-wrap
        launch_tmpdir = create_launch_tmpdir(sandbox)
        try:
            launch_roots = [launch_tmpdir] if launch_tmpdir is not None else []
            # CORAL(S112): record the scratch, so seatbelt keeps the target's $TMPDIR reachable
            sandbox = with_private_tmpdir(sandbox, host_tmpdir)
            sandbox = with_additional_write_roots(sandbox, launch_roots)
            set_sandbox_env(os.environ, host_tmpdir)
            if launch_tmpdir is not None and sandbox.launch_tmpdir_env is not None:
                os.environ[sandbox.launch_tmpdir_env] = str(launch_tmpdir)
                os.environ[_LAUNCHER_LAUNCH_TMPDIR_ENV] = str(launch_tmpdir)
            encoded_sandbox = _encode_json_arg(sandbox.to_jsonable())
            # Name the dir for the in-wrap pass: it adopts this exact
            # path (no second mint) and owns the cleanup on exit.
            os.environ[_LAUNCHER_PRIVATE_TMPDIR_ENV] = str(host_tmpdir)
            # Re-invoke run_launcher via an INLINE python -c script
            # rather than re-running the launcher tempfile. Reason:
            # bwrap mounts ``/tmp`` as a fresh tmpfs, so the host's
            # ``/tmp/omnigent-sandbox-*`` script written by
            # ``create_exec_launcher`` is invisible inside the wrap.
            # ``python -c '<inline>'`` doesn't need a script file in
            # the sandbox view — the inline string travels through
            # argv. Bwrap's ``_ensure_executable_visible`` already
            # ensures ``sys.executable`` is reachable. The project
            # root is added to sys.path inside the inline so
            # ``omnigent.inner.sandbox`` imports succeed even when
            # the cwd is outside the project tree (terminal case).
            # The inline carries the RE-ENCODED policy so the in-wrap
            # pass decodes the same granted scratch root the profile
            # was built from.
            project_root = repr(str(_project_root()))
            inline = (
                "import sys; "
                f"sys.path.insert(0, {project_root}); "
                "from omnigent.inner.sandbox import run_launcher; "
                f"raise SystemExit(run_launcher({encoded_sandbox!r}, "
                f"{target_path!r}, sys.argv[1:]))"
            )
            # -P keeps the wrap's cwd (the workspace) off sys.path, as in
            # the host-side launcher script.
            launcher_argv = [sys.executable, "-P", "-c", inline, *argv]
            wrapped = list(
                backend.wrap_launcher_argv(
                    launcher_argv,
                    sandbox,
                    Path(cwd or os.getcwd()),
                    target=target_path,
                )
            )
            os.environ[_LAUNCHER_WRAPPED_ENV] = "1"
            logger.info(
                "[omnigent-sandbox] spawn-time wrap re-exec backend=%s wrap_head=%s",
                sandbox.backend_type,
                wrapped[:3],
            )
            # ``os.execvp`` replaces the process; nothing after this
            # line runs unless the exec fails (which raises). On success
            # the in-wrap pass adopts ``tmpdir`` and cleans it up; this
            # ``except`` only fires if the wrap/exec never handed off.
            os.execvp(wrapped[0], wrapped)
        except BaseException:
            cleanup_private_tmpdir(host_tmpdir)
            cleanup_private_tmpdir(launch_tmpdir)  # CORAL(S109)
            raise

    tmpdir: Path | None = None
    claimed: list[Path] = []  # CORAL(S116)
    if sandbox.active:
        inherited = os.environ.get(_LAUNCHER_PRIVATE_TMPDIR_ENV)
        if inherited:
            # CORAL(S109): adopt this launch's own target dir so it goes when the target exits
            if launch := os.environ.get(_LAUNCHER_LAUNCH_TMPDIR_ENV):
                launch_tmpdir = Path(launch)
            # In-wrap pass of a spawn-time-wrap backend: adopt the dir
            # the host pass minted and granted. Re-assert ``$TMPDIR`` in
            # case the env prune stripped it; do NOT mint a second dir
            # (that one wouldn't be in the baked profile).
            tmpdir = Path(inherited)
            set_sandbox_env(os.environ, tmpdir)
            # CORAL(S116): the dirs the host pass claimed, seen before the target can change them
            claimed = _claimed_launch_dirs(tmpdir, launch_tmpdir)
        else:
            # Single-pass active backends (no spawn-time re-exec, e.g.
            # ``windows_jobobject``): mint + grant + surface here.
            tmpdir = create_private_tmpdir()
            sandbox = with_additional_write_roots(sandbox, [tmpdir])
            set_sandbox_env(os.environ, tmpdir)
    # Checkpoints around activate + spawn so a hang in either step is
    # visible in the wrapper's stderr (the wrapper template enables INFO).
    logger.info(
        "[omnigent-sandbox] activating backend=%s active=%s target=%s",
        sandbox.backend_type,
        sandbox.active,
        target_path,
    )
    target_argv: list[str] = [target_path, *argv]
    if os.environ.get(_SANDBOX_STRACE_ENV):
        strace_bin = shutil.which("strace")
        if strace_bin is None:
            logger.warning(
                "%s set but strace is not on PATH; running target unwrapped.",
                _SANDBOX_STRACE_ENV,
            )
        else:
            # ``-f`` follows forks, ``-y`` annotates FDs with paths,
            # ``trace=file`` keeps the trace focused on the syscalls
            # where sandbox denials surface (openat/stat/mkdir/etc).
            target_argv = [
                strace_bin,
                "-f",
                "-y",
                "-e",
                "trace=file",
                "--",
                *target_argv,
            ]
            logger.warning(
                "[omnigent-sandbox] strace active; wrapping target with %s",
                strace_bin,
            )
    try:
        activate_sandbox(sandbox)
        # CORAL(S113, S115): a version query needs no config, and its caller may kill it before
        # the cleanup below, so it gets no seed copy
        export_scratch_dir(sandbox, tmpdir, copy_seed=argv not in _VERSION_QUERY_ARGVS)
        logger.info("[omnigent-sandbox] activated; spawning target=%s", target_path)
        # CORAL(S116): a seatbelt target shares the spawner's pid namespace, where a sweep sees it
        seatbelt = sandbox.backend_type == "darwin_seatbelt"
        returncode = _run_target(target_argv, claimed if seatbelt else [])
        logger.info("[omnigent-sandbox] target exited rc=%s", returncode)
        return int(returncode)
    finally:
        # CORAL(S116): a claimed dir keeps its claims while it stays; a bwrap mount point stays
        removable = sandbox.backend_type == "darwin_seatbelt"
        for directory in (tmpdir, launch_tmpdir):  # CORAL(S109)
            _clean_launch_dir(directory, claimed=directory in claimed, removable=removable)


def _claimed_launch_dirs(*directories: Path | None) -> list[Path]:
    """CORAL(S116): the dirs that hold the owner claim the host pass wrote."""
    from omnigent.native.owner_claim import read_owner_claim_bytes

    return [
        directory
        for directory in directories
        if directory is not None
        and read_owner_claim_bytes(directory, filename=_LAUNCH_TMPDIR_OWNER) is not None
    ]


def _clean_launch_dir(directory: Path | None, *, claimed: bool, removable: bool) -> None:
    """
    CORAL(S116): remove a launch dir as its launcher ends, never its claims while it stays.

    A claimed private dir is emptied first; its claims and the dir go only if *removable* (not
    a bwrap mount point). A kill at any point leaves it claimed for the spawner's sweep.
    """
    if directory is None:
        return
    if not (claimed and _is_private_dir(directory)):
        cleanup_private_tmpdir(directory)
        return
    with contextlib.suppress(OSError):
        _remove_claimed_dir(directory, None, keep_claims=not removable)


def _run_target(argv: list[str], claimed: Sequence[Path]) -> int:
    """
    CORAL(S116): run the target as ``subprocess.run`` does, naming it first in each *claimed* dir.

    A sweep then keeps those dirs while the target outlives its launcher.
    """
    if not claimed:
        return subprocess.run(argv).returncode
    with subprocess.Popen(argv) as process:
        try:
            for directory in claimed:
                claim_temp_dir(directory, filename=_LAUNCH_TARGET_CLAIM, pid=process.pid)
            return process.wait()
        except BaseException:
            process.kill()
            raise


def _launcher_inline_source(
    target_path: str, sandbox: SandboxPolicy, *, cwd: str | None = None
) -> str:
    """Build the ``python -c`` program the exec launcher runs.

    basicConfig so ``run_launcher``'s INFO records reach stderr; the
    project root goes on ``sys.path`` so the import works from any cwd.
    """
    encoded = _encode_json_arg(sandbox.to_jsonable())
    return (
        "import logging, sys; "
        f"sys.path.insert(0, {str(_project_root())!r}); "
        "logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr); "
        "from omnigent.inner.sandbox import run_launcher; "
        f"raise SystemExit(run_launcher({encoded!r}, {target_path!r}, sys.argv[1:], cwd={cwd!r}))"
    )


def create_exec_launcher(
    target_path: str, sandbox: SandboxPolicy, *, cwd: str | None = None
) -> str:
    """Write an executable launcher that runs ``target_path`` inside ``sandbox``.

    Callers hand the returned path to spawners that ``execve`` it
    directly (the Claude Agent SDK, tmux, the ACP/qwen/kimi/goose/pi
    executors), so the file must be executable by the kernel on its
    own.

    :param target_path: The real binary the launcher ultimately spawns.
    :param sandbox: Policy baked into the launcher and applied before the spawn.
    :returns: Path to the launcher script; the caller owns deleting it.
    :raises OSError: If the running interpreter cannot be named in the
        launcher, which would produce an unrunnable script.
    :raises ValueError: If a write grant includes the launcher directory.
    """
    launcher_dir = Path(tempfile.gettempdir()).resolve(strict=False)
    if sandbox.active:
        for root in [*sandbox.write_roots, *sandbox.write_files]:
            if launcher_dir.is_relative_to(root.resolve(strict=False)):
                raise ValueError(
                    f"Sandbox write grant {root} exposes the host launcher directory. "
                    "Grant a dedicated scratch directory instead of the host temporary root."
                )
        if sandbox.backend_type in _SPAWN_WRAP_BACKENDS:
            # Path-based spawners may filter the launcher environment. Freeze
            # host-local choices here, immediately before encoding the policy.
            sandbox = get_backend(sandbox.backend_type).prepare_launcher_policy(sandbox)
    inline = _launcher_inline_source(target_path, sandbox, cwd=cwd)
    interpreter = sys.executable
    if not interpreter:
        raise OSError(
            "Cannot build the sandbox exec launcher: sys.executable is empty, so "
            "the launcher has no interpreter to invoke. Run omnigent under a "
            "regular Python installation, or disable the CLI sandbox wrap."
        )

    if os.name == "nt":
        # Windows resolves ``.py`` through PATHEXT; keep the ``#!`` line so
        # the ``py`` launcher (a common .py association) picks the *current*
        # interpreter rather than the machine default.
        fd, path = tempfile.mkstemp(prefix="omnigent-sandbox-", suffix=".py", dir=launcher_dir)
        script = f"#!{interpreter}\n{inline}\n"
    else:
        # ``/bin/sh`` is the only interpreter guaranteed to be a native
        # executable. Naming ``sys.executable`` in a shebang instead
        # breaks whenever it is a wrapper script, sits behind a path
        # too long for the kernel's shebang buffer, or contains spaces —
        # each of which surfaces as an opaque ENOEXEC from the spawner.
        # Spawners usually run it from the agent workspace. -P keeps that cwd
        # off sys.path but, unlike -I, still honours the runtime's PYTHONPATH.
        fd, path = tempfile.mkstemp(prefix="omnigent-sandbox-", suffix=".sh", dir=launcher_dir)
        script = f'#!/bin/sh\nexec {shlex.quote(interpreter)} -P -c {shlex.quote(inline)} "$@"\n'

    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(script)
    os.chmod(path, 0o700)
    return path


def get_backend(type_name: str) -> SandboxBackend:
    """
    Look up a registered :class:`SandboxBackend` by ``type_name``,
    importing the built-in backends on first call.

    Used by the parent-side spawn site
    (:meth:`omnigent.inner.os_env._HelperProcessClient._start_locked`)
    to call :meth:`SandboxBackend.wrap_launcher_argv` before
    ``subprocess.Popen``.

    :param type_name: Backend identifier matching
        :attr:`SandboxBackend.type_name`, e.g. ``"linux_bwrap"``,
        ``"darwin_seatbelt"``, or ``"none"``.
    :returns: The registered backend instance.
    :raises NotImplementedError: If no backend is registered under
        ``type_name``.
    """
    return _get_backend(type_name)


def _get_backend(type_name: str) -> SandboxBackend:
    _ensure_builtin_backends()
    try:
        return _BACKENDS[type_name]
    except KeyError as exc:
        raise NotImplementedError(f"sandbox type '{type_name}' is not implemented") from exc


def _ensure_builtin_backends() -> None:
    if "linux_bwrap" not in _BACKENDS:
        from . import bwrap_sandbox  # noqa: F401
    if "darwin_seatbelt" not in _BACKENDS:
        from . import seatbelt_sandbox  # noqa: F401
    # Windows-only: the backend module touches ctypes.windll, so import it
    # solely on Windows to keep the POSIX import graph clean.
    if os.name == "nt" and "windows_jobobject" not in _BACKENDS:
        from . import windows_jobobject_sandbox  # noqa: F401


def _default_sandbox_for_platform() -> OSEnvSandboxSpec:
    """
    Pick the platform-preferred sandbox backend for the host OS.

    - **Linux**: ``linux_bwrap`` (mount/PID/UTS/IPC namespaces +
      seccomp via the ``bwrap`` binary).
    - **macOS**: ``darwin_seatbelt`` (SBPL via ``sandbox-exec``).
    - **Windows**: ``windows_jobobject`` (Job Object process-tree
      containment + resource limits; no filesystem/network isolation).

    This is a pure *platform* decision — it does **not** probe for the
    backend's binary. The default is resolved at spec **parse** time
    (e.g. :func:`omnigent.inner.loader._parse_os_env_sandbox_spec`
    and :func:`omnigent.spec.parser._parse_os_env_sandbox`) to fill
    in an absent ``type:``; parsing a YAML must not depend on whether
    the host that happens to be loading it has ``bwrap`` installed
    (CI nodes, dev laptops, and the runtime host can all differ).

    Fail-loud is preserved, but at the layer that actually matters:
    when the chosen backend is resolved at **run** time and its binary
    is missing, the backend raises (see
    :meth:`omnigent.inner.bwrap_sandbox.BwrapSandboxBackend.resolve`,
    which errors with an install hint when ``bwrap`` is not on
    ``PATH``). So an agent that omitted ``sandbox.type`` on a host with
    no usable mechanism still fails loudly rather than silently running
    unsandboxed — it just fails when the sandbox is built, not when the
    spec is parsed. The only explicit opt-out remains
    ``os_env.sandbox.type='none'``.

    Spec-self-containment is preserved: a YAML that explicitly
    declares ``sandbox.type: linux_bwrap`` still routes to the bwrap
    backend and errors loudly on macOS (the author asked for it). The
    default fires when ``sandbox:`` is omitted, when its ``type:`` is
    omitted, or when ``type: auto`` is selected explicitly.

    :returns: :class:`OSEnvSandboxSpec` with the OS-appropriate
        ``type``.
    :raises OSError: When the host platform has no sandbox backend at
        all (anything other than Linux, macOS, or Windows). Set
        ``os_env.sandbox.type='none'`` explicitly to run without one.
    """
    if sys.platform.startswith("linux"):
        return OSEnvSandboxSpec(type="linux_bwrap")
    if sys.platform == "darwin":
        return OSEnvSandboxSpec(type="darwin_seatbelt")
    if os.name == "nt":
        return OSEnvSandboxSpec(type="windows_jobobject")
    raise OSError(
        f"No sandbox backend is available on platform {sys.platform!r}. "
        "Set os_env.sandbox.type='none' explicitly to run without a sandbox."
    )


def _resolve_sandbox_type(raw_type: str | None) -> str:
    """Resolve ``auto`` to the platform default and null to disabled."""
    if raw_type is None:
        return "none"
    if raw_type == "auto":
        return _default_sandbox_for_platform().type
    return raw_type


def _project_root() -> Path:
    # File lives at omnigent/inner/sandbox.py; climb two levels to the
    # repo root that hosts `omnigent/` as a package.
    return Path(__file__).resolve().parents[2]


def _encode_json_arg(value: JsonValue) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_json_arg(value: str) -> JsonValue:
    padded = value + "=" * (-len(value) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    return cast(JsonValue, json.loads(raw.decode("utf-8")))
