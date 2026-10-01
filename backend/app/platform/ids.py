"""UUIDv7 identifiers (RFC 9562 section 5.7). Python 3.13 has no `uuid.uuid7`.

Layout: 48-bit Unix time in milliseconds, 4-bit version (7), 12 random bits, 2-bit variant
(0b10), 62 random bits. IDs created in later milliseconds sort after earlier ones.
"""

import secrets
import time
from uuid import UUID

_VERSION = 0x7
_VARIANT = 0b10


def new_id() -> UUID:
    unix_ms = time.time_ns() // 1_000_000
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (
        (unix_ms & 0xFFFF_FFFF_FFFF) << 80 | _VERSION << 76 | rand_a << 64 | _VARIANT << 62 | rand_b
    )
    return UUID(int=value)


def id_timestamp_ms(value: UUID) -> int:
    """The Unix time in milliseconds embedded in a UUIDv7."""
    return value.int >> 80
