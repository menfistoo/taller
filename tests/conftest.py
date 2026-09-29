"""Shared fixtures. Every test runs against an isolated HOME."""

import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty HOME. No hub, no runtime state, nothing registered.

    This is the state a first-ever install is in, and the state spec 15.5
    requires the greenfield test to run against.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)
    return home


import json
import shutil
import stat
import sys


@pytest.fixture
def stub_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Put a fake `claude` first on PATH and expose what it was called with."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    source = Path(__file__).parent / "stub_claude.py"

    # Known limit of this shim: on Windows a .cmd is run through cmd.exe, which
    # re-parses `%*`. A newline cannot survive a cmd.exe command line, so an argv
    # value containing one (the multi-line role briefing) arrives truncated. The
    # real binary is spawned without a shell and receives it intact. Assert
    # multi-line content against the pure function that builds it, and use argv
    # assertions only for single-line values.
    if sys.platform == "win32":
        # A .cmd shim, because Windows will not execute a bare .py from PATH.
        shim = bindir / "claude.cmd"
        # newline="" so text mode does not turn \n into \r\r\n.
        shim.write_text(f'@echo off\n"{sys.executable}" "{source}" %*\n',
                        encoding="utf-8", newline="")
    else:
        shim = bindir / "claude"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{source}" "$@"\n', encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

    argv_log = tmp_path / "argv.jsonl"
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("STUB_CLAUDE_ARGV", str(argv_log))

    class Stub:
        log = argv_log

        def calls(self) -> list[list[str]]:
            if not argv_log.exists():
                return []
            return [json.loads(line) for line in argv_log.read_text(encoding="utf-8").splitlines()]

        def last(self) -> list[str]:
            return self.calls()[-1]

        def flags(self) -> str:
            return " ".join(self.last())

    return Stub()


@pytest.fixture
def identity(monkeypatch: pytest.MonkeyPatch):
    """Commits must not depend on the machine's git identity."""
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Taller Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
