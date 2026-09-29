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
                      "title": {"type": "string", "minLength": 1, "maxLength": 120},
                      "summary": {"type": "string", "minLength": 1}}),
    "explorer": _object({"files": _PATHS, "adds_or_deletes_files": _FLAG,
                         "schema_change": _FLAG, "route_change": _FLAG,
                         "dependency_change": _FLAG,
                         "change_kind": {"type": "string", "enum": list(CHANGE_KINDS)},
                         "notes": _TEXT}),
    "architect": _object({"plan_md": _TEXT}),
    "implementer": _object({"summary": _TEXT, "commits": _PATHS}),
    "summariser": _object({"summary_md": _TEXT}),
}

# The three model gates answer with findings (spec 9.7): each declares its own
# severity and remediation. Items are validated one by one in `gates.llm`, where
# a malformed finding is dropped with a note rather than failing the answer.
_FINDING = {
    "type": "object",
    "properties": {
        "rule": {"type": "string"},
        "severity": {"type": "string", "enum": ["BLOCKER", "HIGH", "MEDIUM", "LOW", "NIT"]},
        "file": {"type": "string"},
        "line": {"type": "integer"},
        "message": {"type": "string"},
        "fix_hint": {"type": ["string", "null"]},
        "remediation": {"type": "string", "enum": ["agent", "escalate"]},
    },
    "required": ["rule", "severity", "file", "line", "message", "remediation"],
}
for _gate in ("gate_security", "gate_quality", "gate_ux"):
    SCHEMAS[_gate] = _object({"findings": {"type": "array", "items": _FINDING}})

SCHEMAS["fixer"] = _object({"summary": _TEXT, "commits": _PATHS})

# Optional: which routes render each template the change touches (spec 9.6). The
# smoke gate GETs them; a template it cannot map is shown to the owner at ⑦.
SCHEMAS["explorer"]["properties"]["templates"] = {
    "type": "object", "additionalProperties": _PATHS}


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
            if key not in schema.get("required", []):
                continue
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
        if "minLength" in rule and len(value.strip()) < rule["minLength"]:
            return "must not be blank"
        if "maxLength" in rule and len(value) > rule["maxLength"]:
            return f"must be at most {rule['maxLength']} characters"
    elif kind == "object":
        if not isinstance(value, dict):
            return "must be a mapping"
        inner = rule.get("additionalProperties")
        if isinstance(inner, dict):
            for item in value.values():
                problem = _check_value(item, inner)
                if problem:
                    return problem
    elif kind == "boolean":
        if not isinstance(value, bool):
            return "must be true or false"
    elif kind == "array":
        if not isinstance(value, list):
            return "must be a list"
        strings = (rule.get("items") or {}).get("type") == "string"
        if strings and not all(isinstance(v, str) for v in value):
            return "must be a list of text"
    return None
