"""Smoke check: one tiny structured call against a live chat profile from the registry.

    uv run python -m app.platform.model_gateway.smoke --profile ollama-cloud-chat

`--profile` (required) names a profile in `registry_model_profiles`. Needs a reachable Ollama
(`PSA_OLLAMA_URL`, signed in for cloud profiles; for an `openai` profile such as
`openai-chat`, the server at `PSA_OPENAI_BASE_URL`; for an `anthropic` profile such as
`anthropic-opus-chat`, `PSA_ANTHROPIC_API_KEY`) and a migrated database (`PSA_DATABASE_URL`) for the
profile and the call row. The prompt is a fixed, non-customer text.

A command-line entry point, like `main_worker`: it is the one `app.platform` module allowed to
import the registry (for its `profile_resolver`; see `pyproject.toml`).
Prints the outcome, tokens and latency only, never the model's reply. Exit code 0 on `ok`,
1 on a failed call, 2 for a missing or unknown `--profile`.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from app.modules.registry.application import public as registry
from app.platform.config import get_settings
from app.platform.db import create_engine
from app.platform.model_gateway.gateway import ModelGateway
from app.platform.model_gateway.port import (
    CallerMetadata,
    Message,
    ModelGatewayError,
    StructuredRequest,
)
from app.platform.model_gateway.profiles import UnknownModelProfileError

SMOKE_AGENT_ID = "platform_smoke"


class SmokeReply(BaseModel):
    status: Literal["ok"]
    sum: int


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.platform.model_gateway.smoke")
    parser.add_argument(
        "--profile", required=True, help="The chat model profile (a registry profile name)."
    )
    return parser


async def _main(profile: str) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        async with ModelGateway(
            settings, engine, resolve_profile=registry.profile_resolver(engine)
        ) as gateway:
            request = StructuredRequest(
                messages=[
                    Message(role="system", content="You answer with JSON only."),
                    Message(
                        role="user",
                        content='Reply with {"status": "ok", "sum": <the sum of 2 and 3>}.',
                    ),
                ],
                output_model=SmokeReply,
                caller=CallerMetadata(agent_id=SMOKE_AGENT_ID, config_version="0"),
                profile=profile,
                priority="interactive",
            )
            try:
                result = await gateway.complete_structured(request)
            except ModelGatewayError as exc:
                print(
                    f"{exc.outcome} error_code={exc.error_code} call_id={exc.call_id} "
                    f"profile={profile}"
                )
                return 1
            except UnknownModelProfileError:
                print(f"unknown_profile profile={profile}")
                return 2
            print(
                f"ok profile={result.profile} model={result.model} "
                f"input_tokens={result.input_tokens} output_tokens={result.output_tokens} "
                f"latency_ms={result.latency_ms} attempts={result.attempts} "
                f"digest={result.model_digest} call_id={result.call_id}"
            )
            return 0
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)  # a missing `--profile` exits 2
    # psycopg's async driver cannot use the Windows Proactor loop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    sys.exit(asyncio.run(_main(args.profile), loop_factory=loop_factory))


if __name__ == "__main__":
    main()
