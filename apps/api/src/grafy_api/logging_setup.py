import logging
from typing import Literal

import structlog
from structlog.typing import Processor


def configure_logging(
    *,
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"],
    renderer: Literal["console", "json"],
) -> None:
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    rendering: list[Processor] = [
        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
    ]
    if renderer == "json":
        rendering.extend(
            [
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ]
        )
    else:
        rendering.append(
            structlog.dev.ConsoleRenderer(
                colors=False,
                exception_formatter=structlog.dev.plain_traceback,
            )
        )

    handler = logging.StreamHandler()
    handler.set_name("grafy.logging")
    handler.setLevel(level)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[*shared, structlog.stdlib.ExtraAdder()],
            processors=rendering,
        )
    )
    root = logging.getLogger()
    for previous in tuple(root.handlers):
        if previous.get_name() == "grafy.logging":
            root.removeHandler(previous)
            previous.close()
    root.addHandler(handler)
    root.setLevel(level)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
