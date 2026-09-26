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
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return None
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def version_at_least(version: tuple[int, int, int], minimum: str) -> bool:
    return version >= parse_version(minimum)  # type: ignore[operator]


def probe(executable: str = "claude") -> FlagReport:
    """Run the real binary. Used by `taller doctor`, never by unit tests."""
    from .errors import InferenceError

    if shutil.which(executable) is None:
        raise InferenceError(
            f"The `{executable}` CLI is not on PATH. Taller performs every act of "
            f"inference through it (spec 3.6) and cannot work without it."
        )
    help_text = subprocess.run(
        [executable, "--help"], capture_output=True, text=True, timeout=60
    ).stdout
    version_text = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, timeout=60
    ).stdout
    report = check_flags(help_text)
    report.version = parse_version(version_text)
    return report
