from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from groundskeeping.contracts import (
    collapse_tqdm_tail,
    read_log_tail,
    spawn_logged_process,
    tail_log,
)


def _wait_for(process_id: int) -> None:
    os.waitpid(process_id, 0)


def test_spawn_logged_process_captures_output_and_merges_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GROUNDSKEEPING_PARENT_MARKER", "parent")
    launch = spawn_logged_process(
        (
            sys.executable,
            "-c",
            (
                "import os; print(os.environ['GROUNDSKEEPING_PARENT_MARKER']); "
                "print(os.environ['GROUNDSKEEPING_OVERRIDE_MARKER'])"
            ),
        ),
        log_dir=tmp_path,
        log_prefix="capture",
        env_overrides={"GROUNDSKEEPING_OVERRIDE_MARKER": "override"},
    )

    _wait_for(launch.pid)

    assert launch.pid > 0
    assert launch.log_path.parent == tmp_path
    assert stat.S_IMODE(launch.log_path.stat().st_mode) == 0o600
    assert read_log_tail(launch.log_path) == "parent\noverride\n"


def test_spawn_logged_process_removes_log_when_spawn_fails(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        spawn_logged_process(
            ("/definitely/not/a/real/executable",),
            log_dir=tmp_path,
            log_prefix="failed",
        )

    assert tuple(tmp_path.iterdir()) == ()


def test_spawn_logged_process_rejects_unsafe_prefix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="log_prefix"):
        spawn_logged_process((sys.executable,), log_dir=tmp_path, log_prefix="bad/name")


def test_spawn_logged_process_disconnects_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_popen(*_args: object, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(pid=1234)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    spawn_logged_process((sys.executable,), log_dir=tmp_path)

    assert captured["stdin"] is subprocess.DEVNULL


def test_read_log_tail_returns_the_recent_character_limit(tmp_path: Path) -> None:
    path = tmp_path / "output.log"
    content = "older output\n" + ("x" * 3000) + ("€" * 1000)
    path.write_text(content, encoding="utf-8")

    assert read_log_tail(path) == content[-2000:]
    assert read_log_tail(path, max_chars=0) == ""
    with pytest.raises(ValueError, match="max_chars"):
        read_log_tail(path, max_chars=-1)


def test_read_log_tail_tolerates_a_partial_utf8_sequence(tmp_path: Path) -> None:
    path = tmp_path / "output.log"
    path.write_bytes((b"x" * 9000) + b"\xe2\x82" + b"tail")

    assert read_log_tail(path).endswith("tail")


def test_tail_log_reads_a_byte_bounded_tail(tmp_path: Path) -> None:
    path = tmp_path / "output.log"
    path.write_bytes(b"0123456789")

    assert tail_log(path, max_bytes=4) == "6789"
    assert tail_log(path, max_bytes=0) == ""
    with pytest.raises(ValueError, match="max_bytes"):
        tail_log(path, max_bytes=-1)


def test_tail_log_replaces_a_partial_utf8_sequence(tmp_path: Path) -> None:
    path = tmp_path / "output.log"
    path.write_bytes("older €".encode() + b"tail")

    assert tail_log(path, max_bytes=5) == "�tail"


def test_collapse_tqdm_tail_preserves_context_and_latest_progress() -> None:
    raw = (
        "Preparing embedding population.\n"
        "\x1b[2KProcessing: 10%|          | 712500/6898521 "
        "[3:40:27<32:16:00, 53.25concept/s]\r"
        "\x1b[2KProcessing: 10%|          | 712600/6898521 "
        "[3:40:30<32:13:22, 53.33concept/s]\n"
    )

    rendered = collapse_tqdm_tail(raw)

    assert "Preparing embedding population." in rendered
    assert rendered.count("Processing:") == 1
    assert "712,600/6,898,521" in rendered
    assert "53.33concept/s" in rendered
    assert "ETA 32:13:22" in rendered
    assert "█" in rendered


def test_collapse_tqdm_tail_strips_ansi_from_non_progress_text() -> None:
    assert collapse_tqdm_tail("\x1b[31mworker warning\x1b[0m\n") == "worker warning"
