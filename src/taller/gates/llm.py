"""The three model gates: security (thinker), quality and ux (worker). Spec 9.1.

Each is one one-shot dispatch - never resumed, so no gate inherits another's
conversation - with the worktree as its working directory, the diff in the
prompt, and its role's constitution slices. The answer is a list of findings,
each declaring its own severity and remediation (spec 9.7); a finding outside
the gate's domain, or malformed, is dropped with a note in `metrics.dropped`
rather than failing the gate. An unusable answer twice is `result: error`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from taller import inference, models, roles
from taller.errors import TallerError
from taller.gates import SEVERITIES, Finding, Verdict, verdict

GATES = ("security", "quality", "ux")
REMEDIATIONS = ("agent", "escalate")
ATTEMPTS = 2

TASKS = {
    "security": "Review this change for security problems.",
    "quality": "Review this change for code quality: reuse, dead code, error handling, "
               "simplification - the judgement calls a linter cannot make.",
    "ux": "Review this change's user interface: component conventions, mobile, "
          "accessibility, brand tokens in context, and the language of every "
          "user-visible string.",
}


def role_of(gate: str) -> str:
    if gate not in GATES:
        raise ValueError(f"{gate!r} is not a model gate: {', '.join(GATES)}.")
    return f"gate_{gate}"


def prompt_for(gate: str, ticket: Mapping[str, Any], diff_text: str,
               ruleset: Mapping[str, Any]) -> str:
    parts = [TASKS[gate],
             f"Ticket {int(ticket.get('id') or 0):04d}: {ticket.get('title', '')}",
             f"The owner asked:\n{ticket.get('words', '')}"]
    if gate == "ux":
        language = ruleset.get("language") or {}
        ui = language.get("ui") if isinstance(language, Mapping) else None
        if ui and ui != "none":
            parts.append(f"UI language: {ui}. Every user-visible string must be in it; "
                         f"report one that is not as ux.ui-language.")
    parts.append(f"Every finding's rule id starts with `{gate}.`. Severity is one of "
                 f"{', '.join(SEVERITIES)}; remediation is `agent` (a fixer can repair it "
                 f"safely) or `escalate` (the owner must decide).")
    parts.append(f"The change:\n```diff\n{diff_text}\n```")
    return "\n\n".join(parts)


def run(gate: str, project: Path, ticket: Mapping[str, Any], diff_text: str,
        ruleset: Mapping[str, Any], cfg: Mapping[str, Any], *,
        cwd: Path | None = None,
        on_result: Callable[[inference.Result], None] | None = None
        ) -> tuple[Verdict, inference.Result]:
    """One gate. `cwd`: the ticket's worktree (default: the project). `on_result`
    sees every dispatch - the retry included - so the chief can fold its spend."""
    role = role_of(gate)
    prompt = prompt_for(gate, ticket, diff_text, ruleset)
    problem = ""
    result = inference.Result(ok=False, error="not dispatched")
    model: str | None = None
    fell_back = False
    attempt = 0
    while attempt < ATTEMPTS:
        dispatch = _dispatch(role, prompt, ruleset, cfg, cwd or project)
        dispatch.model = model
        result = inference.infer(dispatch)
        if on_result is not None:
            on_result(result)
        # §14: an unreachable model falls back once, and that is not the retry.
        if not result.ok and not fell_back and models.UNAVAILABLE.search(result.error or ""):
            fallback = models.fallback_for(role, ruleset or cfg)
            if fallback:
                fell_back, model = True, fallback
                continue
        attempt += 1
        problem = (result.error or "the dispatch failed") if not result.ok \
            else roles.check(role, result.value)
        if problem is None:
            findings, dropped = _findings(gate, result.value["findings"])
            return verdict(gate, findings, {"dropped": dropped}), result
    error = f"The {gate} gate gave no usable answer twice: {problem}"
    failed = inference.Result(ok=False, value=result.value, error=error,
                              session_id=result.session_id, usage=result.usage,
                              cost_usd=result.cost_usd)
    return {"gate": gate, "result": "error", "findings": [], "metrics": {},
            "error": error}, failed


def dry_run(gate: str, ruleset: Mapping[str, Any], cfg: Mapping[str, Any]) -> str | None:
    """The dispatch built but not sent; None, or what would stop it (spec 15.4)."""
    role = role_of(gate)
    project = Path(str((ruleset.get("project") or {}).get("path") or "."))
    dispatch = _dispatch(role, prompt_for(gate, {"id": 0, "title": "dry run"}, "", ruleset),
                         ruleset, cfg, project)
    dispatch.tools = inference.role_tools(role)
    try:
        inference._build(dispatch, "claude")
        inference._prompt(dispatch)
    except (TallerError, OSError) as exc:
        return f"the {gate} gate's dispatch cannot be built: {exc}"
    model = inference.config.resolve_model(role, ruleset or cfg)
    if models.reachable(model, models.load_probe()) is False:
        return (f"the {gate} gate runs on {model}, which the last `taller models probe` "
                f"could not reach")
    return None


def _dispatch(role: str, prompt: str, ruleset: Mapping[str, Any], cfg: Mapping[str, Any],
              cwd: Path) -> inference.Dispatch:
    return inference.Dispatch(role=role, prompt=prompt, config=dict(cfg),
                              ruleset=dict(ruleset), cwd=str(cwd),
                              schema=roles.SCHEMAS[role])


def _findings(gate: str, raw: Any) -> tuple[list[Finding], list[str]]:
    kept: list[Finding] = []
    dropped: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        problem = _problem(gate, item)
        if problem:
            dropped.append(problem)
            continue
        try:
            line = int(item.get("line") or 0)
        except (TypeError, ValueError):
            line = 0
        hint = item.get("fix_hint")
        rule, remediation = _repair(gate, item)
        kept.append({"gate": gate, "severity": item["severity"], "rule": rule,
                     "file": str(item.get("file") or ""), "line": line,
                     "message": item["message"].strip(),
                     "fix_hint": hint if isinstance(hint, str) and hint.strip() else None,
                     "overridden": None, "remediation": remediation})
    return kept, dropped


def _problem(gate: str, item: Any) -> str | None:
    """What makes a finding unusable. A rule id or remediation that is merely off is
    repaired in `_repair` instead: a dropped BLOCKER would read as a pass."""
    if not isinstance(item, Mapping):
        return f"a finding that is not an object: {item!r}"
    rule = item.get("rule")
    if not isinstance(rule, str) or not rule.strip(" .") or rule.strip() == f"{gate}.":
        return f"{rule!r} is not a rule id"
    if item.get("severity") not in SEVERITIES:
        return f"{rule}: severity {item.get('severity')!r} is not one of {', '.join(SEVERITIES)}"
    if not isinstance(item.get("message"), str) or not item["message"].strip():
        return f"{rule}: no message"
    return None


def _repair(gate: str, item: Mapping[str, Any]) -> tuple[str, str]:
    """The rule under the gate's own domain, and a remediation the owner decides
    when the model's is not one of the two."""
    rule = item["rule"].strip()
    if not rule.startswith(f"{gate}."):
        rule = f"{gate}.{rule}"
    remediation = item.get("remediation")
    return rule, remediation if remediation in REMEDIATIONS else "escalate"
