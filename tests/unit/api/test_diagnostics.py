import json
import logging
from uuid import uuid4

import pytest
import structlog

from grafy_api.diagnostics import (
    DiagnosticContext,
    configure_diagnostics,
    diagnostic_scope,
    record_failure,
)
from grafy_api.settings import Settings
from grafy_core.domain.errors import FailureKind, NotFoundError
from grafy_core.domain.templates import TemplateCopyRejectedError


class _CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _remove_diagnostics_handler() -> None:
    root_logger = logging.getLogger()
    for handler in tuple(root_logger.handlers):
        if handler.get_name() == "grafy.diagnostics":
            root_logger.removeHandler(handler)
            handler.close()
    structlog.contextvars.clear_contextvars()


def test_settings_have_safe_local_logging_defaults() -> None:
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.log_level == "INFO"
    assert settings.log_renderer == "console"


def test_record_failure_projects_expected_error_safely(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _remove_diagnostics_handler()
    configure_diagnostics(level="INFO", renderer="json")
    exception = NotFoundError("Secret document", "private-id")

    failure = record_failure(exception, operation="document.read")

    assert failure.code == "resource.not_found"
    assert failure.kind is FailureKind.NOT_FOUND
    assert failure.message == "Not found"
    output = capsys.readouterr().err
    assert "operation_rejected" in output
    assert "private-id" not in output
    assert "exception" not in output
    _remove_diagnostics_handler()


def test_unexpected_failure_omits_message_and_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _remove_diagnostics_handler()
    configure_diagnostics(level="INFO", renderer="json")
    sentinel = "TOP-SECRET-SENTINEL"
    try:
        raise RuntimeError(f"raw runtime message {sentinel}")
    except RuntimeError as exception:
        failure = record_failure(exception, operation="graph.execute")

    output = capsys.readouterr().err
    event = json.loads(output)
    assert failure.code == "internal.error"
    assert failure.kind is FailureKind.INTERNAL
    assert failure.message == "An internal error occurred"
    assert sentinel not in output
    assert "raw runtime message" not in output
    assert event["exception"]["type"] == "builtins.RuntimeError"
    assert all(
        not frame["file"].startswith("/") for frame in event["exception"]["frames"]
    )
    _remove_diagnostics_handler()


def test_expected_failure_keeps_only_declared_diagnostic_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _remove_diagnostics_handler()
    configure_diagnostics(level="INFO", renderer="json")
    exception = TemplateCopyRejectedError(
        reason_code="secret_binding",
        diagnostic_message="Node private-node-id contains a secret binding",
    )

    record_failure(exception, operation="template.copy")

    event = json.loads(capsys.readouterr().err)
    assert event["failure_context"] == {"reason_code": "secret_binding"}
    assert "private-node-id" not in repr(event)
    _remove_diagnostics_handler()


def test_diagnostic_scope_overlays_and_clears_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _remove_diagnostics_handler()
    configure_diagnostics(level="INFO", renderer="json")
    logger = structlog.get_logger("scope-test")
    request_id = uuid4()
    workspace_id = uuid4()

    with diagnostic_scope(DiagnosticContext(request_id=request_id)):
        with diagnostic_scope(DiagnosticContext(workspace_id=workspace_id)):
            logger.info("overlay")
        logger.info("outer")
        with diagnostic_scope(
            DiagnosticContext(node_id="isolated"),
            inherit=False,
        ):
            logger.info("isolated")
        logger.info("cleared")

    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    overlay, outer, isolated, cleared = events
    assert overlay["request_id"] == str(request_id)
    assert overlay["workspace_id"] == str(workspace_id)
    assert outer["request_id"] == str(request_id)
    assert "workspace_id" not in outer
    assert isolated["node_id"] == "isolated"
    assert "request_id" not in isolated
    assert "request_id" not in cleared
    assert "node_id" not in cleared
    _remove_diagnostics_handler()


def test_configuration_is_idempotent_and_preserves_foreign_handlers() -> None:
    _remove_diagnostics_handler()
    root_logger = logging.getLogger()
    foreign_handler = _CapturingHandler()
    root_logger.addHandler(foreign_handler)
    try:
        configure_diagnostics(level="INFO", renderer="console")
        configure_diagnostics(level="DEBUG", renderer="json")

        logging.getLogger("foreign.library").warning(
            "foreign event",
            extra={"payload": {"token": "RAW-EXTRA-SENTINEL"}},
        )
        try:
            raise RuntimeError("RAW-EXCEPTION-SENTINEL")
        except RuntimeError:
            logging.getLogger("foreign.library").exception("foreign failure")

        owned_handlers = [
            handler
            for handler in root_logger.handlers
            if handler.get_name() == "grafy.diagnostics"
        ]
        assert len(owned_handlers) == 1
        assert foreign_handler in root_logger.handlers
        assert owned_handlers[0].level == logging.DEBUG
        assert len(foreign_handler.records) == 2
        assert foreign_handler.records[0].payload == "[REDACTED]"  # type: ignore[attr-defined]
        exception_record = foreign_handler.records[1]
        assert exception_record.exc_info is None
        assert exception_record.exception["type"] == "builtins.RuntimeError"  # type: ignore[attr-defined]
        assert "RAW-EXTRA-SENTINEL" not in repr(foreign_handler.records)
        assert "RAW-EXCEPTION-SENTINEL" not in repr(foreign_handler.records)
    finally:
        root_logger.removeHandler(foreign_handler)
        _remove_diagnostics_handler()


def test_standard_library_logs_use_the_structured_pipeline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _remove_diagnostics_handler()
    configure_diagnostics(level="INFO", renderer="json")

    logging.getLogger("foreign.library").warning(
        "foreign event",
        extra={
            "payload": {"password": "should-not-appear"},
            "broker_rejected_policy_version": True,
        },
    )

    output = capsys.readouterr().err
    event = json.loads(output)
    assert event["event"] == "foreign event"
    assert event["logger"] == "foreign.library"
    assert event["level"] == "warning"
    assert event["payload"] == "[REDACTED]"
    assert event["broker_rejected_policy_version"] is True
    assert "should-not-appear" not in output
    _remove_diagnostics_handler()


def test_console_renderer_keeps_the_last_line_of_an_oversized_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _remove_diagnostics_handler()
    configure_diagnostics(level="INFO", renderer="console")

    logging.getLogger("foreign.library").error(
        f"{'filler frame ' * 900}RuntimeError: another owner holds the lease"
    )

    output = capsys.readouterr().err
    assert "filler frame" in output
    assert "chars omitted" in output
    assert "RuntimeError: another owner holds the lease" in output
    _remove_diagnostics_handler()


def test_console_renderer_keeps_line_breaks_in_messages(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _remove_diagnostics_handler()
    configure_diagnostics(level="INFO", renderer="console")

    logging.getLogger("foreign.library").error("first line\nlast line")

    output = capsys.readouterr().err
    assert "first line\nlast line" in output
    assert "\\n" not in output
    _remove_diagnostics_handler()


def test_json_renderer_keeps_records_on_one_line_with_real_newlines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _remove_diagnostics_handler()
    configure_diagnostics(level="INFO", renderer="json")

    logging.getLogger("foreign.library").error("first line\nlast line")

    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "first line\nlast line"
    _remove_diagnostics_handler()


def test_console_renderer_handles_sanitized_standard_library_exceptions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _remove_diagnostics_handler()
    configure_diagnostics(level="INFO", renderer="console")
    sentinel = "CONSOLE-EXCEPTION-SECRET"

    try:
        raise RuntimeError(sentinel)
    except RuntimeError:
        logging.getLogger("foreign.library").exception("foreign failure")

    output = capsys.readouterr().err
    assert "foreign failure" in output
    assert "builtins.RuntimeError" in output
    assert "exception_diagnostic" in output
    assert sentinel not in output
    assert "Logging error" not in output
    _remove_diagnostics_handler()
