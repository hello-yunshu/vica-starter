"""OS-level sandbox for executing untrusted candidate code.

Milestone M9 (docs/TASKS.md). The SYNTH-v0.1 verifier uses an interpreter-level
guard (no exec; see challenges/synth_v01/family.py), which is sufficient today.
This module is the OS-level isolation layer that will back future challenge
families that execute arbitrary code (any language).

Design (portable to macOS + Linux, no external deps):

- Run the candidate in a fresh subprocess.
- Apply resource limits via ``preexec_fn`` + :mod:`resource` so they are set
  *before* the payload runs:
    - RLIMIT_CPU   -> CPU time limit -> SIGXCPU
    - RLIMIT_AS    -> memory limit   -> SIGKILL/SIGSEGV
    - RLIMIT_NPROC -> process limit
    - RLIMIT_NOFILE-> file descriptor cap
    - RLIMIT_FSIZE -> output / file write cap
    - RLIMIT_CORE  -> no core dumps
- Start the child in its own process group (``start_new_session``) so a
  candidate that forks cannot escape a wall-clock timeout: we kill the whole
  group on timeout (cleanup after execution).
- Bound stdout/stderr reads to ``max_output_bytes``.
- Opportunistic hardening that is only applied when the platform/kernel allows
  it (never a hard failure on a normal dev machine):
    - network namespace disable (Linux + root, ``unshare(CLONE_NEWNET)``)
    - chroot to an empty read-only-ish scratch dir (Linux + root)
  When not available these are skipped with a warning; the rlimit + process
  group + output-bound guarantees always apply.

All violations map to deterministic ErrorCodes (SPEC section 4):
TIMEOUT / SANDBOX_ERROR.
"""

from __future__ import annotations

import os
import resource
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

from vica.protocol.models import ErrorCode

# ---------------------------------------------------------------------- limits


@dataclass(frozen=True)
class SandboxLimits:
    """Resource envelope applied to a sandboxed child process.

    ``SomeLimit`` values are only applied when set to a positive number.
    """

    cpu_seconds: float = 1.0
    wall_seconds: float = 5.0
    memory_bytes: int = 256 * 1024 * 1024
    max_processes: int = 32
    max_fds: int = 64
    max_output_bytes: int = 64 * 1024
    max_file_bytes: int = 1024 * 1024
    # Platform-gated hardening (default off; see module docstring).
    disable_network: bool = False
    chroot: bool = False


class SandboxError(RuntimeError):
    """A sandbox constraint rejected the candidate."""


# ---------------------------------------------------------------------- result


@dataclass
class SandboxResult:
    """Outcome of one sandboxed run. Never raises for candidate failures."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    resource_violation: bool
    error_code: ErrorCode | None
    wall_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error_code is None and self.returncode == 0


# ---------------------------------------------------------------------- preexec


def _apply_rlimits(limits: SandboxLimits, *, scratch_dir: str | None) -> None:
    """Set hard resource limits for the child process. Runs inside the child,
    before exec, so the payload cannot weaken them."""
    if limits.cpu_seconds > 0:
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (int(limits.cpu_seconds), int(limits.cpu_seconds)),
        )
    if limits.max_fds > 0:
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (limits.max_fds, limits.max_fds),
        )
    if limits.max_processes > 0:
        try:
            resource.setrlimit(
                resource.RLIMIT_NPROC,
                (limits.max_processes, limits.max_processes),
            )
        except (ValueError, OSError):
            pass  # not enforced on all systems
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if limits.max_file_bytes > 0:
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (limits.max_file_bytes, limits.max_file_bytes),
        )
    if limits.memory_bytes > 0 and sys.platform.startswith("linux"):
        # RLIMIT_AS / RLIMIT_DATA reliably bound a fresh Linux subprocess.
        # On macOS a forked child inherits a ~400GiB virtual data footprint, so a
        # finite AS/DATA limit would abort exec before any candidate runs; the
        # memory guard is therefore Linux-only (CI covers it). macOS memory
        # isolation belongs to a container/sandbox-exec backend.
        try:
            resource.setrlimit(
                resource.RLIMIT_AS,
                (limits.memory_bytes, limits.memory_bytes),
            )
        except (ValueError, OSError):
            try:
                resource.setrlimit(
                    resource.RLIMIT_DATA,
                    (limits.memory_bytes, limits.memory_bytes),
                )
            except (ValueError, OSError):
                pass
    if limits.chroot and scratch_dir and os.geteuid() == 0:
        os.chroot(scratch_dir)
        os.chdir("/")


def __make_preexec(limits: SandboxLimits, scratch_dir: str | None) -> Any:
    def _preexec() -> None:
        _apply_rlimits(limits, scratch_dir=scratch_dir)
        if limits.disable_network:
            # Linux + root only: drop into a fresh network namespace. On macOS
            # this mechanism does not exist; the rlimit + process-group
            # guarantees still apply.
            try:
                if os.geteuid() == 0 and sys.platform.startswith("linux"):
                    import ctypes

                    CLONE_NEWNET = 0x40000000
                    libc = ctypes.CDLL(None, use_errno=True)
                    if libc.unshare(ctypes.c_int(CLONE_NEWNET)) != 0:
                        raise OSError("unshare(CLONE_NEWNET) failed")
            except Exception as exc:  # pragma: no cover - platform specific
                import warnings

                warnings.warn(
                    f"sandbox: network namespace disabled unavailable: {exc}",
                    stacklevel=2,
                )

    return _preexec


# ---------------------------------------------------------------------- signal mapping


def _signal_code(returncode: int) -> ErrorCode | None:
    """Map a negative (killed-by-signal) returncode to an ErrorCode."""
    sig = -returncode
    if sig == signal.SIGXCPU or sig == signal.SIGXFSZ:
        return ErrorCode.SANDBOX_ERROR
    if sig == signal.SIGKILL or sig == signal.SIGSEGV:
        return ErrorCode.SANDBOX_ERROR
    return None


# ---------------------------------------------------------------------- runner


def run_sandboxed(
    cmd: list[str],
    *,
    limits: SandboxLimits | None = None,
    stdin: str | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> SandboxResult:
    """Run *cmd* under the sandbox and return a :class:`SandboxResult`.

    The child always runs in its own session (new process group). On wall-clock
    timeout the entire group is terminated (SIGKILL) so detached grandchildren
    are cleaned up too.
    """
    limits = limits or SandboxLimits()
    start = time.perf_counter()

    scratch_dir: str | None = None
    child_cwd = cwd
    if limits.chroot:
        if os.geteuid() == 0:
            scratch_dir = tempfile.mkdtemp(prefix="vica-sandbox-")
            child_cwd = "/"
        else:  # pragma: no cover - docstring warns; degrade gracefully
            child_cwd = cwd

    sandbox_env = os.environ.copy()
    if env is not None:
        sandbox_env.update(env)
    # Minimal-ish environment: drop locale/user shell noise that a candidate
    # could read to leak host info.
    for key in ("HOME", "USER", "LOGNAME", "SHELL"):
        sandbox_env.pop(key, None)

    timed_out = False
    launch_error = False
    returncode: int | None = None
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    output_overflow = False
    wall_ms = 0.0

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=child_cwd,
            env=sandbox_env,
            start_new_session=True,
            preexec_fn=__make_preexec(limits, scratch_dir),
        )
        try:
            out, err = proc.communicate(
                input=stdin.encode("utf-8") if stdin is not None else None,
                timeout=limits.wall_seconds,
            )
            stdout_chunks.append(out)
            stderr_chunks.append(err)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Cleanup: kill the whole process group so forked children die too.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                out, err = proc.communicate()
                if out:
                    stdout_chunks.append(out)
                if err:
                    stderr_chunks.append(err)
            except Exception:
                pass
        finally:
            returncode = proc.returncode
    except FileNotFoundError as exc:
        launch_error = True
        returncode = -1
        stdout_chunks.append(b"")
        stderr_chunks.append(str(exc).encode())
    except Exception as exc:
        returncode = -1
        stderr_chunks.append(f"sandbox internal error: {exc}\n".encode())
    finally:
        wall_ms = (time.perf_counter() - start) * 1000.0
        if scratch_dir is not None:
            import shutil

            try:
                shutil.rmtree(scratch_dir, ignore_errors=True)
            except Exception:
                pass

    stdout = _truncate(b"".join(stdout_chunks), limits.max_output_bytes)
    stderr = _truncate(b"".join(stderr_chunks), limits.max_output_bytes)
    if len(stdout_chunks) and len(b"".join(stdout_chunks)) > limits.max_output_bytes:
        output_overflow = True
    if len(stderr_chunks) and len(b"".join(stderr_chunks)) > limits.max_output_bytes:
        output_overflow = True

    error_code: ErrorCode | None = None
    resource_violation = False
    if timed_out:
        error_code = ErrorCode.TIMEOUT
    elif launch_error:
        error_code = None  # command not found / granular launch failure
    elif returncode is not None and returncode < 0:
        code = _signal_code(returncode)
        resource_violation = code is not None
        error_code = code or ErrorCode.SANDBOX_ERROR
    elif output_overflow:
        error_code = ErrorCode.SANDBOX_ERROR

    if returncode is None:
        returncode = -1

    return SandboxResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        resource_violation=resource_violation,
        error_code=error_code,
        wall_ms=wall_ms,
        metadata={
            "limits": limits,
            "output_overflow": output_overflow,
            "launch_error": launch_error,
        },
    )


def _truncate(data: bytes, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    clipped = data[:max_bytes]
    return clipped.decode("utf-8", errors="replace")


__all__ = ["SandboxError", "SandboxLimits", "SandboxResult", "run_sandboxed"]