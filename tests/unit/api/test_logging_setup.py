import json
import logging
from collections.abc import Iterator
from typing import Literal

import pytest
import structlog

from grafy_api.logging_setup import configure_logging


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    previous_level = root.level
    previous_config = structlog.get_config()
    yield
    for handler in tuple(root.handlers):
        if handler.get_name() == "grafy.logging":
            root.removeHandler(handler)
            handler.close()
    root.setLevel(previous_level)
    structlog.configure(**previous_config)
    structlog.contextvars.clear_contextvars()


@pytest.mark.parametrize("source", ["stdlib", "structlog"])
@pytest.mark.parametrize("renderer", ["console", "json"])
def test_logs_preserve_chained_tracebacks_and_messages(
    source: Literal["stdlib", "structlog"],
    renderer: Literal["console", "json"],
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(level="INFO", renderer=renderer)
    logger = (
        logging.getLogger("example")
        if source == "stdlib"
        else structlog.get_logger("example")
    )
    try:
        try:
            raise ValueError("original failure")
        except ValueError as exc:
            raise RuntimeError("outer failure") from exc
    except RuntimeError:
        logger.exception("operation failed")
    output = capsys.readouterr().err
    if renderer == "json":
        event = json.loads(output)
        output = event["exception"]
        assert event["event"] == "operation failed"
    assert "Traceback (most recent call last)" in output
    assert "ValueError: original failure" in output
    assert "RuntimeError: outer failure" in output
    assert "The above exception was the direct cause" in output


def test_json_logs_keep_context_values_and_full_messages(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(level="INFO", renderer="json")
    message = "long message " * 1000
    with structlog.contextvars.bound_contextvars(request_id="request-1"):
        structlog.get_logger("example").info(
            message, query="useful query", values=list(range(40))
        )
    logging.getLogger("library").info("outside", extra={"custom_field": "preserved"})
    first, second = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert first["event"] == message
    assert first["request_id"] == "request-1"
    assert first["query"] == "useful query"
    assert first["values"] == list(range(40))
    assert "request_id" not in second
    assert second["custom_field"] == "preserved"


def test_reconfiguration_preserves_foreign_handlers_and_respects_level(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = logging.getLogger()
    foreign = logging.NullHandler()
    root.addHandler(foreign)
    try:
        configure_logging(level="DEBUG", renderer="console")
        configure_logging(level="WARNING", renderer="json")
        assert foreign in root.handlers
        assert foreign.filters == []
        assert (
            sum(handler.get_name() == "grafy.logging" for handler in root.handlers) == 1
        )
        logging.getLogger("example").info("hidden stdlib")
        structlog.get_logger("example").info("hidden structlog")
        structlog.get_logger("example").warning("visible")
        lines = capsys.readouterr().err.splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["event"] == "visible"
    finally:
        root.removeHandler(foreign)
