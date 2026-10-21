"""`python -m app.evals run [--config <agent_id>=<version> ...] [--only <slug> ...]
[--timeout <s>]` (`make eval ARGS="..."`), and `python -m app.evals conflicts [--only <case>
...] [--profile <name>]` (`make eval-conflicts ARGS="..."`, Story 6.2: precision and recall of
semantic Conflict detection per type; exit 0 once the report is written, 2 for an invalid or
unknown case), and `python -m app.evals retrieval [--timeout <s>]` (`make eval-retrieval`,
Story 3.3: hit rate at k and citation validity of Knowledge search in the eval database;
exit 0 once the report is written, 2 refused, 3 timed out).

Exit codes: 0 passed; 1 failed (a bar missed or regressed, or a stage failed; the result
is still stored); 2 refused or could not run (an unknown `--only` slug, invalid
annotations, the eval database reset failing; nothing stored); 3 timed out ("Eval timed
out — GPU busy"; nothing stored).
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from app.evals import conflicts as conflicts_eval
from app.evals import retrieval as retrieval_eval
from app.evals.annotations import ReferenceSetError
from app.evals.harness import (
    DEFAULT_TIMEOUT_S,
    EvalOptions,
    EvalRefusedError,
    EvalTimedOutError,
    parse_configs,
    run_eval,
)
from app.evals.report import render
from app.platform.config import get_settings
from app.platform.logging import configure_logging

EXIT_FAILED, EXIT_REFUSED, EXIT_TIMED_OUT = 1, 2, 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.evals", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run the reference set and store the result.")
    run.add_argument(
        "--config",
        action="append",
        default=[],
        metavar="AGENT_ID=VERSION",
        help="Evaluate this config version of the Agent (repeatable; default: current).",
    )
    run.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="SLUG",
        help="Run only this reference Opportunity (repeatable).",
    )
    run.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help=f"Seconds before the eval gives up (default {DEFAULT_TIMEOUT_S:g}).",
    )
    semantic = commands.add_parser(
        "conflicts", help="Run the semantic Conflict detection cases (evals/conflicts/)."
    )
    semantic.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="CASE",
        help="Run only this case (repeatable).",
    )
    semantic.add_argument(
        "--profile", default=None, help="The model profile (default: PSA_MODEL_PROFILE_CHAT)."
    )
    retrieval = commands.add_parser(
        "retrieval", help="Score Knowledge search on evals/knowledge/ (hit rate, citations)."
    )
    retrieval.add_argument(
        "--timeout",
        type=float,
        default=retrieval_eval.DEFAULT_TIMEOUT_S,
        help=f"Seconds before the eval gives up (default {retrieval_eval.DEFAULT_TIMEOUT_S:g}).",
    )
    return parser


def _retrieval(args: argparse.Namespace) -> int:
    settings = get_settings()
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        outcome = asyncio.run(
            retrieval_eval.run_retrieval_eval(settings, timeout_s=args.timeout),
            loop_factory=loop_factory,
        )
    except (EvalRefusedError, retrieval_eval.CaseError) as exc:
        print(f"Eval refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except RuntimeError as exc:  # e.g. the eval database reset failed
        print(f"Eval could not run: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except EvalTimedOutError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_TIMED_OUT
    print(retrieval_eval.render(outcome.report))
    print(f"\nReport: {outcome.out_dir / 'report.json'}")
    return 0


def _conflicts(args: argparse.Namespace) -> int:
    settings = get_settings()
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        outcome = asyncio.run(
            conflicts_eval.run_conflicts_eval(
                settings, only=tuple(args.only), profile=args.profile
            ),
            loop_factory=loop_factory,
        )
    except conflicts_eval.CaseError as exc:
        print(f"Eval refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(conflicts_eval.render(outcome.report))
    print(f"\nReport: {outcome.out_dir / 'report.json'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # The report prints ≥ and ≤, which a Windows console's legacy code page can't encode.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    configure_logging("WARNING")
    if args.command == "conflicts":
        return _conflicts(args)
    if args.command == "retrieval":
        return _retrieval(args)
    settings = get_settings()
    try:
        options = EvalOptions(
            configs=parse_configs(args.config), only=tuple(args.only), timeout_s=args.timeout
        )
        loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
        outcome = asyncio.run(run_eval(options, settings=settings), loop_factory=loop_factory)
    except EvalRefusedError as exc:
        print(f"Eval refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except ReferenceSetError as exc:
        print(f"Eval refused: the reference set is invalid: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except RuntimeError as exc:  # e.g. the eval database reset failed
        print(f"Eval could not run: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except EvalTimedOutError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_TIMED_OUT
    print(render(outcome.report))
    print(f"\nReport: {outcome.out_dir / 'report.json'}")
    return 0 if outcome.passed else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
