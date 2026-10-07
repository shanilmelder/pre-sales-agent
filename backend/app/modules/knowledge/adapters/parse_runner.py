"""Runs the Knowledge parse child (`parse_cli`) for one stored file (Story 3.2), with the
platform's runner: wall-clock, CPU and memory limits, allowlisted environment."""

from pathlib import Path

from app.platform.parsing import runner
from app.platform.parsing.runner import ChildOutput, ParseTimeoutError

CHILD_MODULE = "app.modules.knowledge.adapters.parse_cli"

__all__ = ["CHILD_MODULE", "ChildOutput", "ParseTimeoutError", "run_parse"]


async def run_parse(path: Path, ext: str, *, timeout_s: float, max_memory_mb: int) -> ChildOutput:
    """Parse the stored file at `path` as `ext`; see `runner.run_parse`."""
    return await runner.run_parse(
        path, ext, timeout_s=timeout_s, max_memory_mb=max_memory_mb, child_module=CHILD_MODULE
    )
