import logging
import os
import sys
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Literal, cast
from uuid import UUID, uuid4

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from grafy_core.domain.errors import (
    Failure,
    FailureKind,
    FailureSpec,
    GrafyCoreError,
)


LogRenderer = Literal["console", "json"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

_HANDLER_NAME = "grafy.diagnostics"
_EMERGENCY_LINE = b"grafy diagnostics: failure recording failed\n"
_MAX_STRING_LENGTH = 2_048
_TRUNCATION_TAIL_LENGTH = 512
_MAX_COLLECTION_ITEMS = 32
_MAX_DEPTH = 6
_MAX_EXCEPTION_DEPTH = 8
_MAX_STACK_FRAMES = 32
_PROJECT_PACKAGE_MARKERS = frozenset(
    {
        "grafy_api",
        "grafy_core",
        "grafy_persistence",
        "grafy_storage",
    }
)
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "authorization",
        "body",
        "config",
        "cookie",
        "credential",
        "header",
        "password",
        "payload",
        "query",
        "secret",
        "token",
        "url",
    }
)
_configuration_lock = Lock()
_STANDARD_LOG_RECORD_FIELDS = frozenset(
    logging.LogRecord(
        name="",
        level=0,
        pathname="",
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    ).__dict__
)


@dataclass(frozen=True, slots=True)
class DiagnosticContext:
    request_id: UUID | None = None
    primary_error_id: UUID | None = None
    actor_id: UUID | None = None
    workspace_id: UUID | None = None
    graph_id: UUID | None = None
    graph_revision: int | None = None
    execution_id: UUID | None = None
    workflow_run_id: UUID | None = None
    node_id: str | None = None
    node_run_id: UUID | None = None
    plugin_slug: str | None = None
    plugin_revision: int | None = None
    invocation_id: UUID | None = None


def _bounded_string(value: str) -> str:
    """Bound a string while keeping both ends, since the last line of a
    formatted traceback carries the exception a reader has to act on."""

    if len(value) <= _MAX_STRING_LENGTH:
        return value
    head = value[: _MAX_STRING_LENGTH - _TRUNCATION_TAIL_LENGTH]
    tail = value[-_TRUNCATION_TAIL_LENGTH:]
    omitted = len(value) - _MAX_STRING_LENGTH
    return f"{head}...[{omitted} chars omitted]...{tail}"


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _safe_value(value: object, *, depth: int = 0) -> object:
    if depth >= _MAX_DEPTH:
        return "[truncated]"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return _safe_value(value.value, depth=depth + 1)
    if isinstance(value, str):
        return _bounded_string(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return "[binary omitted]"
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        mapping_result: dict[str, object] = {}
        for index, (raw_key, item) in enumerate(mapping.items()):
            if index >= _MAX_COLLECTION_ITEMS:
                mapping_result["__truncated__"] = True
                break
            key = _bounded_string(str(raw_key))
            if _is_sensitive_key(key):
                mapping_result[key] = "[REDACTED]"
            else:
                mapping_result[key] = _safe_value(item, depth=depth + 1)
        return mapping_result
    if isinstance(value, Sequence):
        sequence = cast(Sequence[object], value)
        items = list(sequence[:_MAX_COLLECTION_ITEMS])
        sequence_result = [_safe_value(item, depth=depth + 1) for item in items]
        if len(sequence) > _MAX_COLLECTION_ITEMS:
            sequence_result.append("[truncated]")
        return sequence_result
    if type(value).__name__.casefold() in {
        "secretbytes",
        "secretstr",
    }:
        return "[REDACTED]"
    return f"<{type(value).__module__}.{type(value).__qualname__}>"


def _safe_stack_path(filename: str) -> str:
    parts = Path(filename).parts
    for index, part in enumerate(parts):
        if part in _PROJECT_PACKAGE_MARKERS:
            return "/".join(parts[index:])
    return Path(filename).name


def _exception_chain(exception: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exception
    while (
        current is not None
        and id(current) not in seen
        and len(chain) < _MAX_EXCEPTION_DEPTH
    ):
        seen.add(id(current))
        chain.append(current)
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None
    return chain


def _exception_diagnostic(
    exception: BaseException,
) -> dict[str, object]:
    chain = _exception_chain(exception)
    frames: list[dict[str, object]] = []
    for chained_exception in chain:
        traceback = chained_exception.__traceback__
        while traceback is not None and len(frames) < _MAX_STACK_FRAMES:
            code = traceback.tb_frame.f_code
            frames.append(
                {
                    "file": _safe_stack_path(code.co_filename),
                    "function": _bounded_string(code.co_name),
                    "line": traceback.tb_lineno,
                }
            )
            traceback = traceback.tb_next
    return {
        "type": (f"{type(chain[0]).__module__}.{type(chain[0]).__qualname__}"),
        "cause_types": [
            f"{type(item).__module__}.{type(item).__qualname__}" for item in chain[1:]
        ],
        "frames": frames,
        "truncated": (
            len(chain) == _MAX_EXCEPTION_DEPTH or len(frames) == _MAX_STACK_FRAMES
        ),
    }


def _exception_from_info(value: object) -> BaseException | None:
    if value is True:
        return sys.exc_info()[1]
    if (
        isinstance(value, tuple)
        and len(cast(tuple[object, ...], value)) == 3
        and isinstance(cast(tuple[object, ...], value)[1], BaseException)
    ):
        return cast(BaseException, cast(tuple[object, ...], value)[1])
    if isinstance(value, BaseException):
        return value
    return None


def _sanitize_log_record(record: logging.LogRecord) -> None:
    raw_message = cast(object, record.msg)  # pyright: ignore[reportUnknownMemberType]
    if isinstance(raw_message, Mapping):
        message = cast(Mapping[object, object], raw_message)
        record.msg = _safe_value(message)
    elif isinstance(raw_message, str):
        record.msg = _bounded_string(raw_message)
    else:
        record.msg = _safe_value(raw_message)

    if isinstance(record.args, tuple):
        record.args = tuple(_safe_value(value) for value in record.args)
    elif isinstance(record.args, Mapping):
        record.args = cast(Mapping[str, object], _safe_value(record.args))

    for key in tuple(record.__dict__):
        if key in _STANDARD_LOG_RECORD_FIELDS or key in {"message", "asctime"}:
            continue
        value = record.__dict__[key]
        record.__dict__[key] = (
            "[REDACTED]" if _is_sensitive_key(key) else _safe_value(value)
        )

    exception = _exception_from_info(record.exc_info)
    if exception is not None:
        record.__dict__["exception"] = _exception_diagnostic(exception)
    record.exc_info = None
    record.exc_text = None


class _SanitizeLogRecordFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        _sanitize_log_record(record)
        return True


def _install_handler_filter(handler: logging.Handler) -> None:
    if any(
        isinstance(existing, _SanitizeLogRecordFilter) for existing in handler.filters
    ):
        return
    handler.addFilter(_SanitizeLogRecordFilter())


def _render_exception(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    exception = _exception_from_info(event_dict.pop("exc_info", None))
    if exception is not None:
        event_dict["exception"] = _exception_diagnostic(exception)
    return event_dict


def _sanitize_event(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    for key in tuple(event_dict):
        if key in {"_record", "_from_structlog"}:
            continue
        if _is_sensitive_key(key):
            event_dict[key] = "[REDACTED]"
        else:
            event_dict[key] = _safe_value(event_dict[key])
    return event_dict


def _prepare_console_event(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    exception = event_dict.get("exception")
    if isinstance(exception, Mapping):
        event_dict["exception_diagnostic"] = event_dict.pop("exception")
    return event_dict


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.ExtraAdder(),
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _render_exception,
        _sanitize_event,
    ]


def configure_diagnostics(*, level: LogLevel, renderer: LogRenderer) -> None:
    """Configure one shared pipeline for application and standard-library logs."""
    final_renderer = (
        structlog.processors.JSONRenderer()
        if renderer == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    renderer_processors: list[Processor] = []
    if renderer == "console":
        renderer_processors.append(_prepare_console_event)
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            *renderer_processors,
            final_renderer,
        ],
    )

    with _configuration_lock:
        root_logger = logging.getLogger()
        owned_handler = next(
            (
                handler
                for handler in root_logger.handlers
                if handler.get_name() == _HANDLER_NAME
            ),
            None,
        )
        if owned_handler is None:
            owned_handler = logging.StreamHandler()
            owned_handler.set_name(_HANDLER_NAME)
        elif owned_handler in root_logger.handlers:
            root_logger.removeHandler(owned_handler)
        root_logger.handlers.insert(0, owned_handler)
        _install_handler_filter(owned_handler)
        for handler in root_logger.handlers[1:]:
            _install_handler_filter(handler)
        for configured_logger in logging.root.manager.loggerDict.values():
            if not isinstance(configured_logger, logging.Logger):
                continue
            for handler in configured_logger.handlers:
                _install_handler_filter(handler)
        owned_handler.setLevel(level)
        owned_handler.setFormatter(formatter)
        root_logger.setLevel(level)

        structlog.configure(
            processors=[
                *_shared_processors(),
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=False,
        )

        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _context_values(context: DiagnosticContext) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in fields(context):
        value = getattr(context, field.name)
        if value is not None:
            values[field.name] = _bounded_string(str(value))
    return values


@contextmanager
def diagnostic_scope(
    context: DiagnosticContext,
    *,
    inherit: bool = True,
) -> Generator[None]:
    """Bind allowlisted diagnostic identifiers for the duration of one operation."""
    values = _context_values(context)
    if inherit:
        with structlog.contextvars.bound_contextvars(**values):
            yield
        return

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**values)
    try:
        yield
    finally:
        structlog.contextvars.clear_contextvars()


def _failure_spec(exception: Exception, explicit: FailureSpec | None) -> FailureSpec:
    if explicit is not None:
        return explicit
    if isinstance(exception, GrafyCoreError):
        declared = exception.failure_spec
        if declared is not None:
            return declared
    return FailureSpec(
        code="internal.error",
        kind=FailureKind.INTERNAL,
        public_message="An internal error occurred",
    )


def _public_message(
    exception: Exception,
    spec: FailureSpec,
    *,
    explicit: bool,
) -> str:
    if explicit:
        return spec.public_message
    if isinstance(exception, GrafyCoreError):
        declared = exception.public_message
        if declared is not None:
            return declared
    return spec.public_message


def _emit_failure(
    exception: Exception,
    *,
    operation: str,
    failure: Failure,
) -> None:
    logger = structlog.get_logger("grafy.diagnostics")
    event_fields: dict[str, object] = {
        "error_id": str(failure.error_id),
        "failure_code": failure.code,
        "failure_kind": failure.kind.value,
        "operation": operation,
    }
    if isinstance(exception, GrafyCoreError) and exception.diagnostic_context:
        event_fields["failure_context"] = exception.diagnostic_context
    if failure.kind is FailureKind.INTERNAL:
        logger.error(
            "operation_failed",
            **event_fields,
            exc_info=(type(exception), exception, exception.__traceback__),
        )
    elif failure.kind is FailureKind.UNAVAILABLE:
        logger.warning(
            "operation_failed",
            **event_fields,
            exc_info=(type(exception), exception, exception.__traceback__),
        )
    elif failure.kind is FailureKind.CAPACITY:
        logger.warning("operation_failed", **event_fields)
    else:
        logger.info("operation_rejected", **event_fields)


def record_failure(
    exception: Exception,
    *,
    operation: str,
    spec: FailureSpec | None = None,
) -> Failure:
    """Project an exception safely and record one correlated diagnostic event."""
    resolved_spec = _failure_spec(exception, spec)
    failure = Failure(
        error_id=uuid4(),
        code=resolved_spec.code,
        kind=resolved_spec.kind,
        message=_public_message(
            exception,
            resolved_spec,
            explicit=spec is not None,
        ),
    )
    try:
        _emit_failure(exception, operation=operation, failure=failure)
    except Exception:
        try:
            os.write(2, _EMERGENCY_LINE)
        except OSError:
            pass
    return failure


__all__ = [
    "DiagnosticContext",
    "LogLevel",
    "LogRenderer",
    "configure_diagnostics",
    "diagnostic_scope",
    "record_failure",
]
