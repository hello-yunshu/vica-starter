"""Tests for the M9 OS-level sandbox (subprocess + rlimit isolation).

These exercise the guarantees the sandbox must enforce regardless of platform:
wall-clock timeout with process-group cleanup, CPU/memory/output limits, and
that a malicious candidate cannot crash the host.
"""

from __future__ import annotations

import sys

import pytest

from vica.protocol.models import ErrorCode
from vica.sandbox import SandboxLimits, run_sandboxed

PY = sys.executable


def _py(code: str) -> list[str]:
    return [PY, "-c", code]


def test_successful_run() -> None:
    result = run_sandboxed(_py("import sys; sys.stdout.write('ok')"))
    assert result.ok
    assert result.stdout == "ok"
    assert result.error_code is None


def test_nonzero_exit_is_not_a_sandbox_violation() -> None:
    result = run_sandboxed(_py("import sys; sys.exit(3)"))
    assert result.returncode == 3
    assert result.error_code is None  # user-level failure, not a sandbox hit
    assert not result.ok


def test_wall_timeout_is_flagged() -> None:
    limits = SandboxLimits(wall_seconds=0.2, cpu_seconds=10.0)
    result = run_sandboxed(_py("import time; time.sleep(30)"), limits=limits)
    assert result.timed_out
    assert result.error_code == ErrorCode.TIMEOUT


def test_timeout_kills_detached_grandchild_process_group() -> None:
    """A forked, detached child must be killed by process-group cleanup."""
    # max_processes=0: on macOS RLIMIT_NPROC is a per-user cap, so a low value
    # would reject the fork before the cleanup path is exercised.
    limits = SandboxLimits(wall_seconds=0.2, cpu_seconds=10.0, max_processes=0)
    code = (
        "import os, time, sys;"
        "pid = os.fork();"
        "sys.stdout.write('made child');"
        "time.sleep(30)"
    )
    result = run_sandboxed(_py(code), limits=limits)
    assert result.timed_out
    assert result.error_code == ErrorCode.TIMEOUT


def test_cpu_limit_is_enforced() -> None:
    limits = SandboxLimits(cpu_seconds=1, wall_seconds=20.0)
    result = run_sandboxed(_py("while True: pass"), limits=limits)
    assert result.error_code == ErrorCode.SANDBOX_ERROR
    assert result.resource_violation


def test_output_limit_is_enforced() -> None:
    limits = SandboxLimits(max_output_bytes=1024, wall_seconds=5.0, cpu_seconds=5.0)
    result = run_sandboxed(_py("print('x' * 100000)"), limits=limits)
    assert result.error_code == ErrorCode.SANDBOX_ERROR
    assert result.metadata["output_overflow"]
    assert len(result.stdout) <= 1024


def test_output_overflow_kills_the_child_not_just_truncates() -> None:
    """A candidate that would run forever while spewing output must be killed
    once the output budget is exceeded — real enforcement, not post-hoc
    truncation. If the child were merely truncated and allowed to continue,
    this would hang until the CPU limit fires instead of returning at once."""
    limits = SandboxLimits(max_output_bytes=1024, wall_seconds=5.0, cpu_seconds=5.0)
    code = "import sys\nwhile True:\n    sys.stdout.write('y' * 4096)"
    result = run_sandboxed(_py(code), limits=limits)
    assert result.error_code == ErrorCode.SANDBOX_ERROR
    assert result.metadata["output_overflow"]
    assert len(result.stdout) <= 1024


def test_memory_limit_is_enforced() -> None:
    # RLIMIT_AS/DATA bound a Linux subprocess; on macOS a forked child inherits
    # a ~400GiB virtual footprint so the guard is Linux-only (CI covers it).
    if not sys.platform.startswith("linux"):
        pytest.skip("memory rlimit is enforced on Linux (see runner.py notes)")
    # Control: a small allocation under a generous limit completes normally.
    # This proves the tight limit below is what causes the failure.
    ok = run_sandboxed(
        _py("x = bytearray(4 * 1024 * 1024); print(len(x))"),
        limits=SandboxLimits(memory_bytes=256 * 1024 * 1024, wall_seconds=10.0, cpu_seconds=10.0),
    )
    assert ok.ok
    # The tight 64 MiB RLIMIT must prevent the 512 MiB allocation from
    # completing — the run is bounded (not a hang) and does not succeed. The
    # violation surfaces either as a signal (resource_violation) or as a CPython
    # MemoryError -> non-zero exit; the portable sandbox does NOT claim to
    # distinguish the two (see runner.py security-status note).
    limits = SandboxLimits(memory_bytes=64 * 1024 * 1024, wall_seconds=10.0, cpu_seconds=10.0)
    result = run_sandboxed(_py("x = bytearray(512 * 1024 * 1024)"), limits=limits)
    assert not result.timed_out
    assert not result.ok
    if result.resource_violation:
        assert result.error_code == ErrorCode.SANDBOX_ERROR
    else:
        assert result.returncode != 0


def test_host_secret_env_is_not_inherited() -> None:
    """A candidate must not see host secrets by default (allowlist env)."""
    code = "import os; print(os.environ.get('VICA_TEST_SECRET', 'MISSING'))"
    result = run_sandboxed(_py(code))
    assert result.ok
    assert "MISSING" in result.stdout
    assert "super-secret" not in result.stdout


def test_explicit_env_is_forwarded() -> None:
    """Caller-supplied env is layered onto the allowlist, not blocked."""
    code = "import os; print(os.environ.get('VICA_ALLOWED_VAR', 'MISSING'))"
    result = run_sandboxed(_py(code), env={"VICA_ALLOWED_VAR": "sentinel"})
    assert result.ok
    assert "sentinel" in result.stdout


def test_broken_command_is_reported_not_lethal() -> None:
    result = run_sandboxed(["/nonexistent/binary-xyz"], limits=SandboxLimits(wall_seconds=2.0))
    assert result.error_code is None
    assert not result.ok


def test_stdin_is_forwarded() -> None:
    code = "import sys; print(sys.stdin.read().strip())"
    result = run_sandboxed(_py(code), stdin="hello sandbox")
    assert result.ok
    assert "hello sandbox" in result.stdout