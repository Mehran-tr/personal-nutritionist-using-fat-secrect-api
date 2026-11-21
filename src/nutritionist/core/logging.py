"""Structured logging with per-request correlation ids."""

import atexit
import contextlib
import logging
import queue
import re
import sys
import threading
from collections.abc import MutableMapping
from typing import Any, TextIO, cast

import structlog

# Defence in depth: even if someone logs a field by accident, these never reach logs.
_SENSITIVE_KEY = re.compile(
    r"pass(word)?|secret|token|authorization|api[_-]?key|cookie|credential", re.IGNORECASE
)
REDACTED = "[REDACTED]"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: REDACTED if _SENSITIVE_KEY.search(str(k)) else _redact(v) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact(v) for v in value]
    return value


def redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key != "event" and _SENSITIVE_KEY.search(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact(event_dict[key])
    return event_dict


class QueueWriter:
    """File-like object that hands log lines to a background thread.

    The request path only does a ``queue.put`` (microseconds). The slow,
    potentially blocking write to stdout happens on a daemon thread. Lines are
    flushed at exit. If the process is killed hard, lines still queued can be lost.
    """

    def __init__(self, stream: Any = None, maxsize: int = 10_000) -> None:
        self._stream = stream or sys.stdout
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=maxsize)
        self._thread = threading.Thread(target=self._drain, name="log-writer", daemon=True)
        self._thread.start()
        atexit.register(self.close)

    def write(self, text: str) -> int:
        # Never block a request because logging is backed up: drop the line instead.
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(text)
        return len(text)

    def flush(self) -> None:
        """No-op: the writer thread flushes."""

    def close(self, timeout: float = 2.0) -> None:
        if self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout)

    def _drain(self) -> None:
        while (item := self._queue.get()) is not None:
            self._stream.write(item)
            if self._queue.empty():
                self._stream.flush()


_writer: QueueWriter | None = None


def _async_stdout() -> QueueWriter:
    global _writer
    if _writer is None:
        _writer = QueueWriter()
    return _writer


def configure_logging(level: str = "INFO", *, json: bool = True, asynchronous: bool = True) -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_sensitive,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(
            # QueueWriter implements the parts of TextIO that print() uses.
            file=cast(TextIO, _async_stdout()) if asynchronous else sys.stdout
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
