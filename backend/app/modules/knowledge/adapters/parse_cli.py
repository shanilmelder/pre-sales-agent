"""The Knowledge parse child process (Story 3.2):
`python -m app.modules.knowledge.adapters.parse_cli <blob path> <ext>`.

Knowledge's own entry to the sandbox: the work, the limits and the stderr protocol are the
platform's (`app.platform.parsing.cli`), which parses `.txt`, `.md`, `.docx` and `.pdf`."""

import sys

from app.platform.parsing.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
