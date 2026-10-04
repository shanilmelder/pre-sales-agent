"""The process's ModelGateway, for job handlers (Story 2.5 Part A).

The `worker` installs one `ModelGateway` at startup (`install`) and removes it on shutdown;
handlers get it with `current()`. Tests install a fake. This module imports only the port,
so business modules (which the `api` process imports too) can depend on it without pulling
in the gateway or the Ollama adapter (AD-8): the `api` process never installs one.
"""

from app.platform.model_gateway.port import ModelGatewayPort

_current: ModelGatewayPort | None = None


class NoModelGatewayError(RuntimeError):
    """No gateway is installed in this process (it isn't the worker, or it is stopping)."""


def install(gateway: ModelGatewayPort | None) -> None:
    """Make `gateway` the process's gateway (None removes it)."""
    global _current
    _current = gateway


def current() -> ModelGatewayPort:
    if _current is None:
        raise NoModelGatewayError("No ModelGateway is installed in this process.")
    return _current
