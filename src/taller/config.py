"""Configuration: the shipped defaults, the deep merge, and the hub-only view.

Spec 4.4 resolves configuration in one chain — hub taller.yml, then profile, then
project taller.yml — separately from slice text. This module owns that chain's
mechanics; constitution.py owns applying it to a project.

Nothing here knows about any particular owner: `language` is None until asked,
and no brand or profile is assumed (spec 4.0, goal G9).
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

from . import paths
from .errors import ConfigError

HubConfig = dict[str, Any]

# Lists normally replace on merge. This one appends, at every level.
APPEND_ONLY_LIST_PATHS = {
    ("paths", "security_sensitive"),
    ("non_suppressible",),       # spec 4.5 - a project may add, never remove
}

SHIPPED_DEFAULTS: HubConfig = {
    "cli_min_version": "2.1.74",
    "model_aliases": {
        "thinker": "opus",
        "worker": "sonnet",
        "cheap": "haiku",
        "creative": "fable",
    },
    "models": {
        "chief": "worker",
        "architect": "thinker",
        "implementer": "worker",
        "fixer": "worker",
        "gate_security": "thinker",
        "gate_quality": "worker",
        "gate_ux": "worker",
        "explorer": "cheap",
        "scribe": "cheap",
        "summariser": "cheap",
    },
    "effort": {
        "chief": "low",
        "architect": "high",
        "implementer": "medium",
        "fixer": "medium",
        "gate_security": "medium",
        "gate_quality": "medium",
        "gate_ux": "medium",
        "default": "low",
    },
    "fallback": "worker",
    "language": None,          # asked at `taller setup`; never assumed
    "billing": {"mode": None}, # detected; see billing.detect()
    "concurrency": {"max_parallel_gates": 3, "max_parallel_thinker": 1},
    "weights": {"input": 1.0, "cache_write": 1.25, "cache_read": 0.1, "output": 5.0},
    "pricing": {
        "as_of": "2026-06-24",
        "claude-opus-5": {"input": 5.00, "output": 25.00},
        "claude-sonnet-5": {"input": 2.00, "output": 10.00},
        "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
        "claude-fable-5-1": {"input": 10.00, "output": 50.00},
    },
    "budget": {"per_ticket_warn": 400_000, "per_ticket_stop": 1_200_000},
    "thresholds": {
        "max_file_lines": 800,
        "max_function_lines": 80,
        "max_fast_lane_lines": 50,
        "max_fix_rounds": 2,
        "min_coverage_pct": 0,
        "dup_block_lines": 12,
    },
    "paths": {"security_sensitive": [".env*", "**/*secret*", "**/*credential*"]},
    # Rule ids no override may suppress (spec 4.5). Configuration, not prose:
    # an earlier draft put this in never.md front matter, where a parser
    # expecting it at line 1 would have read it as empty and silently made
    # every rule suppressible.
    "non_suppressible": [],
}


def deep_merge(base: Any, over: Any, _trail: tuple[str, ...] = ()) -> Any:
    """Merge `over` onto `base`. Later wins; lists replace; one list appends."""
    if isinstance(base, dict) and isinstance(over, dict):
        out = copy.deepcopy(base)
        for key, value in over.items():
            out[key] = deep_merge(out.get(key), value, _trail + (key,))
        return out
    if _trail in APPEND_ONLY_LIST_PATHS:
        # Type-guarded: a scalar here would otherwise silently replace the hub
        # floor, which is exactly what the append-only rule forbids (spec 4.4).
        if not isinstance(over, list):
            raise ConfigError(
                f"{'.'.join(_trail)} must be a list; got {type(over).__name__}. "
                f"It is append-only, so a scalar cannot replace it."
            )
        merged = list(base or [])
        merged.extend(item for item in over if item not in merged)
        return merged
    return copy.deepcopy(over)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping, not {type(data).__name__}.")
    return data


def load_hub_config() -> HubConfig:
    """The hub layer alone. Succeeds on a completely empty hub (spec 4.4.1)."""
    cfg = deep_merge(SHIPPED_DEFAULTS, _read_yaml(paths.hub_config()))
    if cfg["billing"]["mode"] is None:
        cfg["billing"]["mode"] = detect_billing_mode()
    cfg["hub_sha"] = hub_sha()
    return cfg


def hub_sha() -> str:
    """The hub's HEAD, recorded on every gate verdict (spec 4.4.1, 7.4).

    Empty string when the hub is not yet a git repository, which is the state a
    first-ever install is in.
    """
    import subprocess

    if not (paths.hub() / ".git").exists():
        return ""
    try:
        out = subprocess.run(
            ["git", "-C", str(paths.hub()), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30,
        )
    except OSError:
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def detect_billing_mode() -> str:
    """Determined from the environment, not asked (spec 5.2)."""
    if os.environ.get("CLAUDE_CODE_USE_BEDROCK"):
        return "bedrock"
    if os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        return "vertex"
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "api"
    return "subscription"


def resolve_model(role: str, cfg: HubConfig) -> str:
    """role -> alias -> concrete model id.

    Two hops on purpose: `model_aliases` is the only place a concrete model name
    appears, so a new model release is one line (spec 5.1).
    """
    try:
        alias = cfg["models"][role]
    except KeyError as exc:
        raise ConfigError(f"No model configured for role {role!r}.") from exc
    try:
        return cfg["model_aliases"][alias]
    except KeyError as exc:
        raise ConfigError(
            f"Role {role!r} maps to alias {alias!r}, which no model_aliases entry defines."
        ) from exc


def read_project_config(project_path: Path) -> dict[str, Any]:
    """A project's `.taller/taller.yml` — config overrides only (spec 5.1).

    `{}` when there is none, which is the common case: a project states only what
    it changes. Chain 1 merges this last (spec 4.4), so a key absent here keeps
    whatever the profile or the hub said.
    """
    return _read_yaml(paths.project_config(Path(project_path)))


def resolve_effort(role: str, cfg: HubConfig) -> str:
    """The role's key if present, else `default`. Never a KeyError (spec 4.4.1)."""
    effort = cfg["effort"]
    return effort.get(role, effort["default"])
