"""Capture stdout/stderr produced by a stage and tee it to:

  1. The shared in-memory line buffer (consumed by the WebSocket endpoint).
  2. The original stdout (so logs still appear in `docker logs` / journal).
  3. A per-stage `console.log` file under the work directory.

Usage:

    with ConsoleCapture(buf_key="task:1", work_dir=work_dir, stage_num=1):
        do_stage_work()
"""

from __future__ import annotations

import io
import os
import sys
import threading
from contextvars import ContextVar
from typing import Dict, List, Optional

_console_buffers: Dict[str, List[str]] = {}
_console_lock = threading.Lock()
_MAX_LINES = 50_000


def get_lines(buf_key: str, since_index: int = 0) -> List[str]:
    with _console_lock:
        buf = _console_buffers.get(buf_key, [])
        return list(buf[since_index:])


def clear(buf_key: str) -> None:
    with _console_lock:
        _console_buffers.pop(buf_key, None)


def append(buf_key: str, line: str) -> None:
    with _console_lock:
        buf = _console_buffers.setdefault(buf_key, [])
        buf.append(line)
        if len(buf) > _MAX_LINES:
            del buf[: len(buf) - _MAX_LINES]


class _Tee(io.TextIOBase):
    """File-like wrapper that fans writes out to multiple targets."""
    def __init__(self, *, buf_key: str, original, file_writer: Optional[io.TextIOBase]) -> None:
        self.buf_key = buf_key
        self.original = original
        self.file_writer = file_writer
        self._line = ""

    def write(self, s: str) -> int:  # type: ignore[override]
        try:
            self.original.write(s)
            self.original.flush()
        except Exception:
            pass
        if self.file_writer is not None:
            try:
                self.file_writer.write(s)
                self.file_writer.flush()
            except Exception:
                pass
        # Buffer line-by-line for the WebSocket consumer.
        self._line += s
        while "\n" in self._line:
            line, _, rest = self._line.partition("\n")
            append(self.buf_key, line)
            self._line = rest
        return len(s)

    def flush(self) -> None:  # type: ignore[override]
        try:
            self.original.flush()
        except Exception:
            pass
        if self.file_writer is not None:
            try:
                self.file_writer.flush()
            except Exception:
                pass


class ConsoleCapture:
    def __init__(self, *, buf_key: str, work_dir: str, stage_num: int) -> None:
        self.buf_key = buf_key
        self.work_dir = work_dir
        self.stage_num = stage_num
        self._stdout_orig = None
        self._stderr_orig = None
        self._file: Optional[io.TextIOBase] = None

    def __enter__(self) -> "ConsoleCapture":
        log_dir = os.path.join(self.work_dir, f"stage_{self.stage_num}")
        os.makedirs(log_dir, exist_ok=True)
        try:
            self._file = open(os.path.join(log_dir, "console.log"), "a", encoding="utf-8", buffering=1)
        except Exception:
            self._file = None

        self._stdout_orig = sys.stdout
        self._stderr_orig = sys.stderr
        sys.stdout = _Tee(buf_key=self.buf_key, original=self._stdout_orig, file_writer=self._file)
        sys.stderr = _Tee(buf_key=self.buf_key, original=self._stderr_orig, file_writer=self._file)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            sys.stdout = self._stdout_orig  # type: ignore[assignment]
            sys.stderr = self._stderr_orig  # type: ignore[assignment]
        finally:
            if self._file is not None:
                try:
                    self._file.close()
                except Exception:
                    pass
