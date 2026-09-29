"""`taller models probe`: which models this account can reach (spec 6.2)."""

from __future__ import annotations

from typing import Any

from .. import models
from ..prompter import Prompter


def probe(args: Any, prompter: Prompter) -> int:
    candidates = args.model or list(models.CANDIDATES)
    prompter.say(f"Asking {len(candidates)} models one trivial question each; this uses "
                 f"a little of your usage window.")
    record = models.probe(candidates)
    lines = []
    for name, entry in record["models"].items():
        if entry["ok"]:
            lines.append(f"  {name:<8} reachable   {entry['latency_s']}s")
        else:
            lines.append(f"  {name:<8} NOT reachable - {entry['error']}")
    prompter.say("\n".join(lines))
    return 0
