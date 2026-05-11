"""Structured logging — context binding (task_id, run_id) + console / JSON renderers.

Mirrors the pattern used in MARS-PaperPulse so log shape is consistent across the
MARS product family. Safe to call ``configure_logging`` more than once (uvicorn
overrides the root logger after import; we re-apply on app startup).
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Optional

import structlog

current_task_id: ContextVar[Optional[str]] = ContextVar("task_id", default=None)
current_session_id: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
current_run_id: ContextVar[Optional[str]] = ContextVar("run_id", default=None)


def _ctx_processor(logger, method_name, event_dict):
    if (tid := current_task_id.get()):
        event_dict["task_id"] = tid
    if (sid := current_session_id.get()):
        event_dict["session_id"] = sid
    if (rid := current_run_id.get()):
        event_dict["run_id"] = rid
    return event_dict


_configured = False

structlog.configure(
    processors=[structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=False,
)


def configure_logging(log_level: str = "INFO", json_output: bool = False, log_file: Optional[str] = None) -> None:
    global _configured

    structlog_pre = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        _ctx_processor,
    ]
    foreign_pre = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        _ctx_processor,
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True, exception_formatter=structlog.dev.plain_traceback)

    structlog.configure(
        processors=structlog_pre + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=foreign_pre,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    ))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    if log_file:
        fh = logging.FileHandler(log_file, mode="a", delay=False)
        fh.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        fh.setFormatter(structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=foreign_pre,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        ))
        root.addHandler(fh)

    logging.disable(logging.NOTSET)
    for noisy in ("uvicorn.access", "httpx", "httpcore", "openai", "anthropic", "boto3", "botocore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    if not _configured:
        configure_logging()
    stdlib = logging.getLogger(name)
    if stdlib.level == logging.NOTSET:
        stdlib.setLevel(logging.INFO)
    return structlog.get_logger(name)


def bind_context(task_id: Optional[str] = None, session_id: Optional[str] = None, run_id: Optional[str] = None) -> None:
    if task_id:
        current_task_id.set(task_id)
    if session_id:
        current_session_id.set(session_id)
    if run_id:
        current_run_id.set(run_id)


def clear_context() -> None:
    current_task_id.set(None)
    current_session_id.set(None)
    current_run_id.set(None)
