"""`taller doctor`: print every check; exit 1 when any fails (spec 15.4)."""

from __future__ import annotations

from typing import Any

from .. import doctor
from ..prompter import Prompter


def run(args: Any, prompter: Prompter) -> int:
    checks = doctor.run_checks(live=getattr(args, "live", False))
    prompter.say(doctor.render(checks))
    return 1 if any(check.status == doctor.FAIL for check in checks) else 0
