"""The append-only trace (AD-12). Write rows only with `append`."""

from app.platform.trace.catalogue import CATALOGUE, TracePayload, register
from app.platform.trace.models import TraceEvent
from app.platform.trace.writer import UnknownTraceEventError, append

__all__ = [
    "CATALOGUE",
    "TraceEvent",
    "TracePayload",
    "UnknownTraceEventError",
    "append",
    "register",
]
