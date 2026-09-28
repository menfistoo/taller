"""Path globs as a person means them - the way `.gitignore` reads them.

`fnmatch` is the wrong tool for a security list: `**` means nothing special to
it, and a pattern without a slash is matched against the whole path, so the
shipped floor `**/*secret*` missed a root-level `secrets.py` and `.env*` missed
`config/.env.prod`. For §8.2's precedence rule that is the unsafe direction -
security-sensitive files reached the fast lane. Found by the phase B review.

Rules: `**/` matches zero or more directories; `**` alone matches anything;
`*` and `?` never cross a `/`; a pattern with no `/` matches a file's name at
any depth; a pattern with a `/` is anchored at the repository root.
"""

from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def match(path: str, pattern: str) -> bool:
    """Whether a repo-relative path matches a glob, by the rules above."""
    path = path.replace("\\", "/").lstrip("/")
    pattern = pattern.replace("\\", "/").lstrip("/")
    if not pattern:
        return False
    if "/" not in pattern.rstrip("/"):
        name = path.rsplit("/", 1)[-1]
        return bool(_compile(pattern).match(name)) or bool(_compile(pattern).match(path))
    return bool(_compile(pattern).match(path))


def any_match(path: str, patterns: list[str]) -> str | None:
    """The first pattern the path matches, or None."""
    return next((pattern for pattern in patterns if match(path, pattern)), None)
