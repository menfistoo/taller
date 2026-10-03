"""Verify the `claude` CLI's flag surface.

Spec 3.6's mapping table is a set of assumptions about a binary that changes
under us — spec 3.6.2 documents one flag that would silently break subscription
billing if it became a default. So the flags are checked, and the version is
recorded, rather than hoped for.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field

from .errors import ConfigError, InferenceError

# Every flag spec 3.6's mapping table depends on.
REQUIRED_FLAGS = [
    "-p",
    "--output-format",
    "--json-schema",
    "--append-system-prompt",
    "--resume",
    "--session-id",
    "--add-dir",
    "--allowedTools",
    "--disallowedTools",
    "--agents",
    "--model",
    "--permission-mode",
    "--strict-mcp-config",    # with no --mcp-config: no connected service loads
    "--setting-sources",      # project,local: her user settings and plugins stay out
]

# Used when present, omitted when not (spec 3.4).
OPTIONAL_FLAGS = [
    "--permission-prompts",   # needs 2.1.259+; dontAsk carries unattended alone
    "--bare",                 # absent on 2.1.74; spec 3.6.2's guard is forward-looking
]


@dataclass
class FlagReport:
    version: tuple[int, int, int] | None = None
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing_required

    def supports(self, flag: str) -> bool:
        """Whether this CLI accepts `flag`.

        Gated on a known flag name: an ungated version returned True for anything
        it had never heard of, so a typo in a caller silently became "supported"
        and got passed to the CLI. `inference.py` builds its argv from this.
        """
        if flag not in REQUIRED_FLAGS and flag not in OPTIONAL_FLAGS:
            raise ValueError(
                f"{flag!r} is not a flag Taller knows about. Add it to "
                f"REQUIRED_FLAGS or OPTIONAL_FLAGS before asking whether it is "
                f"supported."
            )
        return flag not in self.missing_optional and flag not in self.missing_required


def check_flags(help_text: str) -> FlagReport:
    report = FlagReport()
    for flag in REQUIRED_FLAGS:
        if not _mentions(help_text, flag):
            report.missing_required.append(flag)
    for flag in OPTIONAL_FLAGS:
        if not _mentions(help_text, flag):
            report.missing_optional.append(flag)
    return report


def _mentions(help_text: str, flag: str) -> bool:
    # Word boundary on the right so `-p` does not match `--print-foo`.
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", help_text) is not None


def parse_version(text: str) -> tuple[int, int, int] | None:
    # Anchored at the start so a banner like "node 20.11.1, claude 2.1.74" cannot
    # yield the wrong tool's version.
    match = re.match(r"\s*v?(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return None
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def version_at_least(version: tuple[int, int, int] | None, minimum: str) -> bool:
    """True when `version` is at least `minimum`.

    Both operands were previously unchecked behind a `type: ignore`, so an
    owner-edited `cli_min_version` of "2.1" produced a TypeError instead of a
    clear error — and `cli_min_version` is owner-editable configuration.
    """
    floor = parse_version(minimum)
    if floor is None:
        raise ConfigError(
            f"cli_min_version {minimum!r} is not a three-part version like "
            f"'2.1.74'."
        )
    if version is None:
        return False                    # unknown version satisfies no floor
    return version >= floor


def probe(executable: str = "claude") -> FlagReport:
    """Run the real binary. Used by `taller doctor`, never by unit tests."""
    # Resolve to an absolute path before spawning. On Windows, CreateProcess
    # appends only .exe to an extensionless name, so spawning bare "claude"
    # skips a claude.cmd earlier on PATH and runs the real claude.exe instead.
    # Harmless here (--help and --version are not billed) but this is the
    # pattern inference.py follows, where dispatches ARE billed — so the wrong
    # shape must not be the one on screen.
    resolved = shutil.which(executable)
    if resolved is None:
        raise InferenceError(
            f"The `{executable}` CLI is not on PATH. Taller performs every act of "
            f"inference through it (spec 3.6) and cannot work without it."
        )

    help_text = _run(resolved, "--help")
    version_text = _run(resolved, "--version")
    report = check_flags(help_text)
    report.version = parse_version(version_text)
    return report


def _run(resolved: str, flag: str) -> str:
    """Run one informational flag, reporting a broken CLI as a broken CLI.

    An unchecked returncode turned an unauthenticated or broken binary into empty
    stdout, which `check_flags` then read as "all twelve flags missing" — telling
    the owner to amend the specification when the real fault was their CLI.
    """
    try:
        completed = subprocess.run(
            [resolved, flag], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60
        )
    except subprocess.TimeoutExpired as exc:
        raise InferenceError(f"`{resolved} {flag}` did not respond within 60s.") from exc
    except OSError as exc:
        raise InferenceError(f"`{resolved} {flag}` could not be run: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:300]
        raise InferenceError(
            f"`{resolved} {flag}` exited {completed.returncode}. The CLI is present "
            f"but not working — check that it is authenticated. Detail: {detail}"
        )
    return completed.stdout
