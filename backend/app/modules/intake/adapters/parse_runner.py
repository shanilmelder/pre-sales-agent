"""Runs the parse child process (`parse_cli`) for one stored file (Story 2.2 Part B).

The worker never parses in its own process: each file is parsed by a fresh
`python -m app.modules.intake.adapters.parse_cli <blob path> <ext>` under a wall-clock limit
(`timeout_s`) and, on Linux, an address-space limit (`RLIMIT_AS`) and a CPU-time limit
(`RLIMIT_CPU`). The limits travel in the child's environment (`LIMIT_*_ENV`) and the child
sets them itself first thing (no `preexec_fn`, which is unsafe in a threaded parent).
Elsewhere only the wall-clock limit applies. The child gets an allowlisted environment
only, never the worker's database URL or secrets.

The child is waited for in a thread (`asyncio.to_thread`), so the event loop keeps
running the job's heartbeat; it works on the Windows selector loop too, which has no
asyncio subprocess support. If the waiting task is cancelled, the child is killed.
"""

import asyncio
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.modules.intake.domain.parsing import (
    MAX_TEXT_CHARS,
    ParseError,
    ParseErrorCode,
)

CHILD_MODULE = "app.modules.intake.adapters.parse_cli"
BACKEND_ROOT = Path(__file__).resolve().parents[4]
"""The directory holding the `app` package: the child's working directory."""
PARSER_PREFIX = "parser="
LIMIT_MEMORY_ENV = "PSA_PARSE_LIMIT_MEMORY_MB"
LIMIT_CPU_ENV = "PSA_PARSE_LIMIT_CPU_S"
ENV_ALLOWLIST = (
    "PATH",
    "PYTHONPATH",
    "PYTHONHOME",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
)
"""The only parent environment variables the child sees (plus the limits)."""
_MAX_STDOUT_BYTES = MAX_TEXT_CHARS * 4 + 1024
_KNOWN_CODES = {code.value: code for code in ParseErrorCode}


class ParseTimeoutError(Exception):
    """The child ran past its time limit and was killed."""

    def __init__(self, timeout_s: float) -> None:
        super().__init__(f"parse exceeded {timeout_s:g}s")


@dataclass(frozen=True, slots=True)
class ChildOutput:
    text: str
    parser: str


def child_command(path: Path, ext: str) -> list[str]:
    """The child's argv. Tests replace this to stand in a slow or broken child."""
    return [sys.executable, "-m", CHILD_MODULE, str(path), ext]


def child_env(max_memory_mb: int, cpu_s: int) -> dict[str, str]:
    """The child's environment: the allowlisted variables and its limits."""
    env = {name: os.environ[name] for name in ENV_ALLOWLIST if name in os.environ}
    env[LIMIT_MEMORY_ENV] = str(max_memory_mb)
    env[LIMIT_CPU_ENV] = str(cpu_s)
    return env


def _last_line(stderr: bytes) -> str:
    """The last non-empty stderr line: the protocol line (anything before it is noise)."""
    lines = [line.strip() for line in stderr.decode("utf-8", errors="replace").splitlines()]
    return next((line for line in reversed(lines) if line), "")


def _decode(stdout: bytes) -> str:
    if len(stdout) > _MAX_STDOUT_BYTES:
        raise ParseError(ParseErrorCode.TOO_LARGE_OUTPUT)
    try:
        text = stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise ParseError(ParseErrorCode.UNREADABLE) from None
    if len(text) > MAX_TEXT_CHARS:
        raise ParseError(ParseErrorCode.TOO_LARGE_OUTPUT)
    if not text.strip():
        raise ParseError(ParseErrorCode.NO_TEXT)
    return text


def _outcome(returncode: int, stdout: bytes, stderr: bytes, timeout_s: float) -> ChildOutput:
    message = _last_line(stderr)
    if returncode == 0 and message.startswith(PARSER_PREFIX):
        return ChildOutput(text=_decode(stdout), parser=message.removeprefix(PARSER_PREFIX)[:100])
    if returncode < 0:
        # Killed by a signal (the CPU limit's SIGXCPU/SIGKILL, the OOM killer): retryable.
        raise ParseTimeoutError(timeout_s)
    raise ParseError(_KNOWN_CODES.get(message) or ParseErrorCode.UNREADABLE)


async def run_parse(path: Path, ext: str, *, timeout_s: float, max_memory_mb: int) -> ChildOutput:
    """Parse the file at `path` (a stored blob) as `ext` in a child process.

    Returns the text and the parser's name. Raises `ParseError(code)` when the child could
    not parse it, and `ParseTimeoutError` when it ran past `timeout_s` (it is killed first)
    or was killed by a signal."""
    cpu_s = max(1, math.ceil(timeout_s)) + 1
    process = subprocess.Popen(  # noqa: S603, ASYNC220 (fixed argv, no shell; fork is quick)
        child_command(path, ext),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=BACKEND_ROOT,
        env=child_env(max_memory_mb, cpu_s),
    )
    try:
        stdout, stderr = await asyncio.to_thread(process.communicate, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        await asyncio.to_thread(process.communicate)
        raise ParseTimeoutError(timeout_s) from None
    except BaseException:  # cancelled (worker stopping, lease lost) or anything else
        process.kill()
        raise
    return await asyncio.to_thread(_outcome, process.returncode, stdout, stderr, timeout_s)
