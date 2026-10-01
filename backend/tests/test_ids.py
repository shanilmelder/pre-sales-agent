import time
from uuid import UUID

from app.platform.ids import id_timestamp_ms, new_id


def test_new_id_is_rfc9562_uuid_v7() -> None:
    value = new_id()
    assert isinstance(value, UUID)
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"
    assert UUID(str(value)) == value


def test_new_id_embeds_current_unix_ms() -> None:
    before = time.time_ns() // 1_000_000
    value = new_id()
    after = time.time_ns() // 1_000_000
    assert before <= id_timestamp_ms(value) <= after


def test_new_ids_are_unique_and_sort_by_time() -> None:
    ids = [new_id() for _ in range(10_000)]
    assert len(set(ids)) == len(ids)
    first = new_id()
    time.sleep(0.002)
    second = new_id()
    assert first < second
    assert str(first) < str(second)
