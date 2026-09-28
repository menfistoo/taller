"""The roles: what each is told, and the shape of the answer it must give.

Spec 6 and 3.6.0. A role's brief is its definition (`agents/<role>.md`), then
its slices of the constitution, then anything the caller adds. The definition's
first line is always `ROLE: <role>`: it names the role for anyone reading a
transcript, and it is how the test stub knows whom it is answering.

`SCHEMAS` are the contract between the chief and the roles that answer in
structure. Each is passed to `claude` as `--json-schema`, and `check` validates
the answer again on this side, because an answer that satisfies a schema only
by the CLI's word is still an answer the chief is about to act on.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from . import inference

ROLES: tuple[str, ...] = (
    "chief", "architect", "implementer", "fixer", "gate_security", "gate_quality",
    "gate_ux", "explorer", "scribe", "summariser",
)
KINDS = ("bug", "feature", "refactor", "question", "idea")
CHANGE_KINDS = ("literal", "string", "style", "threshold", "other")

_TEXT = {"type": "string"}
_FLAG = {"type": "boolean"}
_PATHS = {"type": "array", "items": {"type": "string"}}


def _object(properties: dict[str, dict]) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": True}


SCHEMAS: dict[str, dict] = {
    "chief": _object({"kind": {"type": "string", "enum": list(KINDS)},
                      "title": {"type": "string", "maxLength": 120},
                      "summary": _TEXT}),
    "explorer": _object({"files": _PATHS, "adds_or_deletes_files": _FLAG,
                         "schema_change": _FLAG, "route_change": _FLAG,
                         "dependency_change": _FLAG,
                         "change_kind": {"type": "string", "enum": list(CHANGE_KINDS)},
                         "notes": _TEXT}),
    "architect": _object({"plan_md": _TEXT}),
    "implementer": _object({"summary": _TEXT, "commits": _PATHS}),
    "summariser": _object({"summary_md": _TEXT}),
}


@lru_cache(maxsize=None)
def definition(role: str) -> str:
    if role not in ROLES:
        raise inference.InferenceError(f"{role!r} is not one of the ten roles.")
    return (Path(__file__).resolve().parent / "agents" / f"{role}.md").read_text(encoding="utf-8")


def check(role: str, value: Any) -> str | None:
    """None when `value` has the role's answer shape; otherwise what is wrong."""
    schema = SCHEMAS.get(role)
    if schema is None:
        return None
    if not isinstance(value, dict):
        return f"the {role} answer must be an object, not {type(value).__name__}"
    for key, rule in schema["properties"].items():
        if key not in value:
            return f"the {role} answer has no `{key}`"
        problem = _check_value(value[key], rule)
        if problem:
            return f"`{key}` {problem}"
    return None


def _check_value(value: Any, rule: dict) -> str | None:
    kind = rule["type"]
    if kind == "string":
        if not isinstance(value, str):
            return "must be text"
        if "enum" in rule and value not in rule["enum"]:
            return f"must be one of {', '.join(rule['enum'])}, not {value!r}"
        if "maxLength" in rule and len(value) > rule["maxLength"]:
            return f"must be at most {rule['maxLength']} characters"
    elif kind == "boolean":
        if not isinstance(value, bool):
            return "must be true or false"
    elif kind == "array":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return "must be a list of text"
    return None
