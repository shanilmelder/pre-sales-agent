"""Smoke check: one tiny structured call against the live configured profile.

    uv run python -m app.platform.model_gateway.smoke

Needs a reachable Ollama (`PSA_OLLAMA_URL`, signed in for cloud profiles) and a migrated
database (`PSA_DATABASE_URL`) for the call row. The prompt is a fixed, non-customer text.
Prints the outcome, tokens and latency only, never the model's reply. Exit code 0 on `ok`.
"""

import asyncio
import sys
from typing import Literal

from pydantic import BaseModel

from app.platform.config import get_settings
from app.platform.db import create_engine
from app.platform.model_gateway.gateway import ModelGateway
from app.platform.model_gateway.port import (
    CallerMetadata,
    Message,
    ModelGatewayError,
    StructuredRequest,
)

SMOKE_AGENT_ID = "platform_smoke"


class SmokeReply(BaseModel):
    status: Literal["ok"]
    sum: int


async def _main() -> int:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        async with ModelGateway(settings, engine) as gateway:
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
                priority="interactive",
            )
            try:
                result = await gateway.complete_structured(request)
            except ModelGatewayError as exc:
                print(
                    f"{exc.outcome} error_code={exc.error_code} call_id={exc.call_id} "
                    f"profile={settings.model_profile_chat}"
                )
                return 1
            print(
                f"ok profile={result.profile} model={result.model} "
                f"input_tokens={result.input_tokens} output_tokens={result.output_tokens} "
                f"latency_ms={result.latency_ms} attempts={result.attempts} "
                f"digest={result.model_digest} call_id={result.call_id}"
            )
            return 0
    finally:
        await engine.dispose()


def main() -> None:
    # psycopg's async driver cannot use the Windows Proactor loop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    sys.exit(asyncio.run(_main(), loop_factory=loop_factory))


if __name__ == "__main__":
    main()
