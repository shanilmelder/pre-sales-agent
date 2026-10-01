"""Who performed an action. Shared by the trace and by `identity`, so it lives in `platform`
(which must not import business modules)."""

from dataclasses import dataclass
from typing import Literal

ActorType = Literal["user", "agent", "system"]


@dataclass(frozen=True, slots=True)
class Actor:
    type: ActorType
    id: str
