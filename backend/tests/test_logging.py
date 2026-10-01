import json
import logging
import sys

from app.platform.logging import JsonFormatter


def test_formatter_emits_exception_type_and_extras_but_no_message_text() -> None:
    try:
        raise RuntimeError("secret customer text")
    except RuntimeError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        name="app.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="request.unhandled_error",
        args=None,
        exc_info=exc_info,
    )
    record.request_id = "req-1"

    output = JsonFormatter().format(record)
    payload = json.loads(output)

    assert payload["event"] == "request.unhandled_error"
    assert payload["exc_type"] == "RuntimeError"
    assert payload["request_id"] == "req-1"
    assert "secret" not in output
