"""The action catalogue (AD-15): every authorizable action, in one place.

Names follow `<module>.<entity>.<verb>` and match the command that performs them. The
Agent Registry reuses these names later.
"""

import re
from enum import StrEnum

_SEGMENT = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
ACTION_NAME_RE = re.compile(rf"^{_SEGMENT}\.{_SEGMENT}\.{_SEGMENT}$")


class Action(StrEnum):
    USER_LIST = "identity.user.list"
    USER_ASSIGN_ROLE = "identity.user.assign_role"
    USER_REMOVE_ROLE = "identity.user.remove_role"
