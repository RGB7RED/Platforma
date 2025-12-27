"""Logging utilities with request/task correlation context."""

from __future__ import annotations

import contextvars
import logging
from typing import Optional

request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_id", default=None)
task_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("task_id", default=None)


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        record.task_id = task_id_var.get() or "-"
        return True


def configure_logging() -> None:
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format=(
                "%(asctime)s level=%(levelname)s logger=%(name)s "
                "request_id=%(request_id)s task_id=%(task_id)s message=\"%(message)s\""
            ),
        )
    for handler in root_logger.handlers:
        handler.addFilter(CorrelationFilter())


def set_request_id(value: Optional[str]) -> contextvars.Token:
    return request_id_var.set(value)


def reset_request_id(token: contextvars.Token) -> None:
    request_id_var.reset(token)


def get_request_id() -> Optional[str]:
    return request_id_var.get()


def set_task_id(value: Optional[str]) -> contextvars.Token:
    return task_id_var.set(value)


def reset_task_id(token: contextvars.Token) -> None:
    task_id_var.reset(token)


def get_task_id() -> Optional[str]:
    return task_id_var.get()
