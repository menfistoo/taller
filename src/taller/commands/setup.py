"""`taller setup`: connect, and the three languages (spec 4.7 rounds 1 and 5).

`project new` runs both rounds inline on a hub whose `language` is unset, so a
first-ever user never has to know that `setup` exists (spec 11.1). Discovery —
rounds 2, 3, 4 and 6 — registers existing repositories, which is adoption, and
arrives with it.
"""

from __future__ import annotations

import re
from typing import Any

from .. import config, discovery, hub
from ..onboarding import Question, ask
from ..prompter import Prompter

LANGUAGE_CODE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})?$")
BILLING_LABELS = {
    "subscription": "your Claude subscription",
    "api": "an Anthropic API key (billed per token)",
    "bedrock": "Amazon Bedrock",
    "vertex": "Google Vertex AI",
}


def needed() -> bool:
    """True when the hub has never been through the language round."""
    language = config.load_hub_config().get("language")
    return not (isinstance(language, dict) and language.get("code"))


def connect(prompter: Prompter) -> None:
    """Round 1: GitHub, how Claude is reached, and the deployment host."""
    prompter.say(discovery.gh_auth_status()["message"])

    detected = config.detect_billing_mode()
    prompter.say(
        f"Claude is reached through the `claude` command, signed in as it already "
        f"is. Detected: {BILLING_LABELS[detected]}. Taller stores no key of its own."
    )
    right = ask(prompter, Question("setup.billing", "billing", 0, "Is that right?",
                                   "yes_no", default=True))
    if not right:
        mode = ask(prompter, Question(
            "setup.billing.mode", "billing", 0, "How is Claude reached?", "choice",
            choices=tuple(BILLING_LABELS.items())))
        hub.update_config({"billing": {"mode": mode}})

    current = (hub.read_config().get("deploy") or {}).get("host") or ""
    host = prompter.ask(
        "setup.host",
        "  The server your projects deploy to, if there is one (Enter for none)"
        + (f"\n     [{current}]" if current else ""),
    ).strip() or current
    if host and host != current:
        hub.update_config({"deploy": {"host": host}})


def languages(prompter: Prompter) -> dict[str, str]:
    """Round 5: asked, never assumed. No defaults on a hub that has none."""
    current = hub.read_config().get("language") or {}
    chosen = {
        "code": _code(prompter, "setup.language.code",
                      "Language for code, comments and identifiers (for example en)",
                      current.get("code")),
        "ui": _code(prompter, "setup.language.ui",
                    "Language your projects' screens are written in (for example es "
                    "or en), or none for projects without a user interface",
                    current.get("ui"), allow_none=True),
        "commits": _code(prompter, "setup.language.commits",
                         "Language for commit messages (for example en)",
                         current.get("commits")),
    }
    hub.update_config({"language": chosen})
    return chosen


def _code(prompter: Prompter, qid: str, text: str, default: Any,
          allow_none: bool = False) -> str:
    prompt = f"  {text}" + (f"\n     [{default}]" if default else "")
    while True:
        raw = prompter.ask(qid, prompt).strip().lower()
        if not raw and default:
            return str(default)
        if LANGUAGE_CODE.match(raw) or (allow_none and raw == "none"):
            return raw
        prompter.say("  Use a language code such as en, es or pt-br"
                     + (", or none." if allow_none else "."))


def run_inline(prompter: Prompter) -> None:
    """What `project new` runs first on an unconfigured hub (spec 11.1)."""
    prompter.say("This is a new hub. Two short questions about how you work come first.")
    connect(prompter)
    languages(prompter)
    hub.commit("setup: connection and languages")


def run(args: Any, prompter: Prompter) -> int:
    prompter.say("Connect")
    connect(prompter)
    prompter.say("\nLanguages")
    languages(prompter)
    committed = hub.commit("setup: connection and languages")
    prompter.say("\nSaved to your hub." if committed else "\nNothing changed.")
    return 0
