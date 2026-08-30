"""Headless subprocess and log-file helpers.

``spawn_logged_process`` starts a process in a new session, redirects stdin from
``DEVNULL``, and redirects both output streams to a private log file. It does not
supervise, cancel, or reap the process; those responsibilities stay with the consuming
application.

Clipboard consumers should use :func:`read_log_tail`, which deliberately limits copied
output to the most recent 2,000 characters by default. Textual's OSC 52 clipboard support
does not work in macOS Terminal.app; that platform limitation belongs to the UI layer.

Log viewers should use :func:`tail_log` when they need the final byte-bounded portion of a
log, and may pass that text through :func:`collapse_tqdm_tail` for simple tqdm rendering.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class LoggedProcess:
    """The identity and log location of a spawned process."""

    pid: int
    log_path: Path


def spawn_logged_process(
    argv: Sequence[str],
    *,
    log_dir: str | Path = "/tmp",
    log_prefix: str = "job",
    env_overrides: Mapping[str, str] | None = None,
) -> LoggedProcess:
    """Start *argv* detached and redirect stdout and stderr to a private log file.

    The caller should admit any corresponding application job before calling this
    function. The log directory is created when needed, and the log file is created
    atomically with mode ``0600``. A failed spawn removes the newly-created file.
    """

    if not argv:
        raise ValueError("argv must contain at least one argument")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", log_prefix):
        raise ValueError("log_prefix must contain only letters, digits, '_' or '-'")

    directory = Path(log_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = directory / f"groundskeeping-{log_prefix}-{stamp}-{uuid4().hex[:8]}.log"

    fd = os.open(
        log_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(fd, "wb") as log_file:
            fd = -1
            environment = os.environ.copy()
            if env_overrides is not None:
                environment.update(env_overrides)
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=environment,
                start_new_session=True,
            )
    except BaseException:
        if fd != -1:
            os.close(fd)
        try:
            log_path.unlink()
        except FileNotFoundError:
            pass
        raise

    return LoggedProcess(pid=process.pid, log_path=log_path)


def read_log_tail(log_path: str | Path, *, max_chars: int = 2000) -> str:
    """Read the most recent ``max_chars`` characters from *log_path*.

    The file is read from a bounded byte window before decoding as UTF-8. Invalid
    sequences are replaced, matching the tolerant behavior used by existing consumers.
    ``max_chars`` must be non-negative; zero returns an empty string.
    """

    if max_chars < 0:
        raise ValueError("max_chars must be non-negative")
    if max_chars == 0:
        return ""

    path = Path(log_path).expanduser()
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        handle.seek(max(0, handle.tell() - max_chars * 4), os.SEEK_SET)
        text = handle.read().decode("utf-8", errors="replace")
    return text[-max_chars:]


_ANSI_ESCAPE = re.compile(r"\x1b(?:[@-_][0-?]*[ -/]*[@-~])")
_TQDM_PROGRESS = re.compile(
    r"(?P<label>[^:\r\n]{1,80}):\s*"
    r"(?P<percent>\d+(?:\.\d+)?)%\s*"
    r"(?:\|.*?\|\s*)?"
    r"(?P<current>\d[\d,]*)\s*/\s*(?P<total>\d[\d,]*)"
    r"(?:\s*\[(?P<elapsed>[^<\]]+?)\s*<\s*"
    r"(?P<remaining>[^,\]]+?)(?:,\s*(?P<rate>[^\]]+))?\])?"
)


def tail_log(log_path: str | Path, *, max_bytes: int = 8192) -> str:
    """Read the final ``max_bytes`` bytes from *log_path* as tolerant UTF-8."""

    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if max_bytes == 0:
        return ""

    path = Path(log_path).expanduser()
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        handle.seek(max(0, handle.tell() - max_bytes), os.SEEK_SET)
        return handle.read().decode("utf-8", errors="replace")


def collapse_tqdm_tail(tail: str, *, bar_width: int = 16) -> str:
    """Collapse repeated tqdm updates while preserving ordinary log lines.

    This is intentionally limited to tqdm-shaped progress output. Non-matching
    lines remain available as ordinary text.
    """

    cleaned = _ANSI_ESCAPE.sub("", tail).replace("\r", "\n")
    ordinary_lines: list[str] = []
    latest_progress: re.Match[str] | None = None
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _TQDM_PROGRESS.search(line)
        if match is None:
            ordinary_lines.append(line)
        else:
            latest_progress = match

    if latest_progress is None:
        return "\n".join(ordinary_lines)

    percent = max(0.0, min(100.0, float(latest_progress["percent"])))
    filled = round(bar_width * percent / 100)
    bar = "█" * filled + "░" * (bar_width - filled)
    percent_text = f"{percent:g}%"
    label = latest_progress["label"].strip()
    progress_lines = [f"{label}: [{bar}] {percent_text}"]
    counts = (
        f"{int(latest_progress['current'].replace(',', '')):,}/"
        f"{int(latest_progress['total'].replace(',', '')):,}"
    )
    metadata = [counts]
    if latest_progress["rate"]:
        metadata.append(latest_progress["rate"].strip())
    if latest_progress["remaining"]:
        metadata.append(f"ETA {latest_progress['remaining'].strip()}")
    if latest_progress["elapsed"]:
        metadata.append(f"elapsed {latest_progress['elapsed'].strip()}")
    progress_lines.append(" · ".join(metadata))
    return "\n".join((*ordinary_lines, *progress_lines))


__all__ = [
    "LoggedProcess",
    "collapse_tqdm_tail",
    "read_log_tail",
    "spawn_logged_process",
    "tail_log",
]
