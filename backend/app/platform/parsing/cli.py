"""The parse child process (Stories 2.2 Part B and 3.2):
`python -m app.platform.parsing.cli <blob path> <ext>`.

Runs one parser on one file. First thing, it silences warnings and logging and, on Linux,
sets its own limits from the environment its parent (`parse_runner`) gave it
(`RLIMIT_AS`, `RLIMIT_CPU`); only then are the parsers imported. On success it writes the
normalised text, UTF-8 encoded, to stdout and `parser=<name>@<version>` as the last stderr
line, and exits 0. When the file can't be parsed it writes the failure code
(`domain.parsing.ParseErrorCode`) as the last stderr line and exits `EXIT_PARSE_ERROR`.
No content, file names or tracebacks are written.
"""

import logging
import os
import sys
import warnings
from pathlib import Path

EXIT_PARSE_ERROR = 3
EXIT_USAGE = 64
_PARSE_ERROR_CODE_UNREADABLE = "unreadable"


def _fail(code: str) -> int:
    """Write the failure code as the last stderr line."""
    sys.stderr.write(f"\n{code}")
    return EXIT_PARSE_ERROR


def _quiet() -> None:
    # Libraries log and warn about malformed input, sometimes quoting it: keep stderr to the
    # protocol lines.
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")


def _apply_limits() -> None:
    """Set `RLIMIT_AS` and `RLIMIT_CPU` from the parent's `PSA_PARSE_LIMIT_*` (Linux only)."""
    if sys.platform != "linux":
        return
    import resource

    memory_mb = os.environ.get("PSA_PARSE_LIMIT_MEMORY_MB")
    cpu_s = os.environ.get("PSA_PARSE_LIMIT_CPU_S")
    if memory_mb:
        memory = int(memory_mb) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    if cpu_s:
        resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_s), int(cpu_s) + 1))


def main(argv: list[str]) -> int:
    _quiet()
    _apply_limits()
    if len(argv) != 2:
        sys.stderr.write("usage")
        return EXIT_USAGE
    try:
        from app.platform.parsing.parsers import parse
        from app.platform.parsing.rules import ParseError
        from app.platform.parsing.runner import PARSER_PREFIX
    except Exception:  # MemoryError under the limit included
        return _fail(_PARSE_ERROR_CODE_UNREADABLE)

    path, ext = argv
    try:
        data = Path(path).read_bytes()
        result = parse(data, ext)
        encoded = result.text.encode("utf-8")
    except ParseError as exc:
        return _fail(exc.code.value)
    except Exception:  # MemoryError (the address-space limit) included
        return _fail(_PARSE_ERROR_CODE_UNREADABLE)
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    sys.stderr.write(f"\n{PARSER_PREFIX}{result.parser}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
