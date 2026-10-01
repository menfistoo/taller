"""Spec 4.3, 4.4, 4.4.1 — the two chains, resolved into one `RuleSet`.

Chain 1 is configuration (hub -> profile -> project, deep merge) and chain 2 is
slice text (hub modules in profile order -> project constitution/ -> the project's
`never.md`, appended). They are deliberately separate: nothing in `constitution/`
sets configuration, and prose is only ever appended, so a project cannot delete a
hub prohibition.

The invariant numbers are the plan's, task 13.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from taller import config, constitution, paths
from taller.errors import ConfigError

import support

# Spec 4.3. The list is closed; adding one changes the specification.
SLICES = {
    "product", "architecture", "stack", "conventions", "security", "ux",
    "brand", "never", "overrides",
}

# Spec 4.4's RuleSet. Every later component reads these keys, so a missing one
# is a contract break rather than a detail.
RULESET_KEYS = {
    "project", "slices", "brand", "paths", "smoke", "thresholds",
    "model_aliases", "models", "fallback", "effort", "billing", "concurrency",
    "budget", "weights", "pricing", "language", "overrides", "non_suppressible",
    "hub_sha", "mode",
}


# --- invariant 1 -------------------------------------------------------------

def test_a_slice_the_project_does_not_provide_is_absent_not_empty(tmp_home: Path):
    """An absent key says "this project has no product slice"; an empty string
    would say "it has one and it is blank", which no caller can act on."""
    project = support.make_project()
    ruleset = constitution.resolve(project)

    assert set(ruleset["slices"]) <= SLICES
    # flask-sqlite names six modules across five slices; brand is `none` here.
    assert set(ruleset["slices"]) == {"stack", "security", "conventions", "ux", "never"}
    assert "product" not in ruleset["slices"]
    assert "architecture" not in ruleset["slices"]
    assert "overrides" not in ruleset["slices"]
    assert ruleset["brand"] is None


def test_a_project_file_provides_the_project_only_slices(tmp_home: Path):
    project = support.make_project(slices={
        "product": "> What this does and what must never break.\n",
        "architecture": "> Layers and dependency rules.\n",
    })
    ruleset = constitution.resolve(project)

    assert "must never break" in ruleset["slices"]["product"]["text"]
    assert ruleset["slices"]["architecture"]["sources"] == [
        str(paths.project_constitution(project) / "architecture.md")
    ]


# --- invariant 2 -------------------------------------------------------------

def test_a_hub_module_named_product_is_ignored(tmp_home: Path):
    """`product`, `architecture` and `overrides` are project-only (spec 4.3):
    they are what makes a project itself. A hub module of that name is ignored -
    not merged, and not preferred."""
    project = support.make_project(
        hub_modules={"product": "> Hub prose that must never reach a project.\n"},
        profile_patch={"modules": ["stack/flask-sqlite", "never", "product"]},
        slices={"product": "> The project's own product slice.\n"},
    )
    ruleset = constitution.resolve(project)

    text = ruleset["slices"]["product"]["text"]
    assert "must never reach a project" not in text
    assert "The project's own product slice." in text
    assert len(ruleset["slices"]["product"]["sources"]) == 1


# --- invariant 3 -------------------------------------------------------------

def test_conventions_concatenates_its_modules_in_profile_order(tmp_home: Path):
    """flask-sqlite names `conventions/python` before `conventions/js`. Profile
    order is the order the chief reads, so it is not incidental."""
    project = support.make_project()
    ruleset = constitution.resolve(project)

    sources = ruleset["slices"]["conventions"]["sources"]
    assert [Path(source).stem for source in sources] == ["python", "js"]

    text = ruleset["slices"]["conventions"]["text"]
    assert text.index("Python naming") < text.index("JavaScript")


# --- invariant 4 -------------------------------------------------------------

def test_a_project_never_md_is_appended_and_the_hub_prohibitions_survive(tmp_home: Path):
    """The only way a rule stops applying is an override with a reason (spec 4.4),
    so an appending project file can add a prohibition and never remove one."""
    project = support.make_project(slices={
        "never": "> This project's own prohibitions.\n\n## Never touch the till log\n",
    })
    ruleset = constitution.resolve(project)

    text = ruleset["slices"]["never"]["text"]
    assert "Never commit a secret" in text, "the hub prohibition survives"
    assert "Never touch the till log" in text
    sources = ruleset["slices"]["never"]["sources"]
    assert sources[0] == str(paths.modules() / "never.md"), "the hub comes first"
    assert sources[-1] == str(paths.project_constitution(project) / "never.md")


# --- invariant 5 -------------------------------------------------------------

def test_chain_1_merges_hub_then_profile_then_project(tmp_home: Path):
    project = support.make_project(
        hub_config={"thresholds": {"max_file_lines": 500, "max_function_lines": 90}},
        profile_patch={"thresholds": {"max_function_lines": 40}},
        project_config={"thresholds": {"max_file_lines": 400}},
    )
    ruleset = constitution.resolve(project)

    assert ruleset["thresholds"]["max_file_lines"] == 400, "the project wins"
    assert ruleset["thresholds"]["max_function_lines"] == 40, "the profile wins over the hub"
    assert ruleset["thresholds"]["max_fast_lane_lines"] == 50, "a shipped default survives"
    assert ruleset["paths"]["tests_dir"] == "tests", "the profile carries the path block"
    assert ruleset["smoke"]["kind"] == "http"


def test_security_sensitive_cannot_be_narrowed_by_a_profile_or_a_project(tmp_home: Path):
    """A project able to shrink its own security surface would make spec 8.2's
    mandatory gate optional. Append-only at every level (spec 4.4)."""
    project = support.make_project(
        profile_patch={"paths": {"security_sensitive": ["routes/**"], "ui": [],
                                 "layers": {}, "tests_dir": "tests",
                                 "brand_tokens": "static/css/tokens.css"}},
        project_config={"paths": {"security_sensitive": ["billing/**"]}},
    )
    sensitive = constitution.resolve(project)["paths"]["security_sensitive"]

    assert ".env*" in sensitive, "the hub floor holds"
    assert "**/*secret*" in sensitive
    assert "routes/**" in sensitive
    assert "billing/**" in sensitive


def test_nothing_in_the_constitution_sets_configuration(tmp_home: Path):
    """Chain 2 is prose. A `thresholds:` block in a slice file is text about
    thresholds, not a threshold - otherwise a branch could raise its own limits
    by editing a Markdown file the gates read."""
    project = support.make_project(slices={
        "architecture": "> Layers.\n\n---\nthresholds:\n  max_file_lines: 1\n---\n",
    })
    ruleset = constitution.resolve(project)

    assert ruleset["thresholds"]["max_file_lines"] == 800
    assert "max_file_lines: 1" in ruleset["slices"]["architecture"]["text"]


# --- invariant 6 -------------------------------------------------------------

def test_models_holds_aliases_so_one_resolver_serves_both(tmp_home: Path):
    """Spec 4.4.1: `RuleSet["models"]` holds aliases exactly as `HubConfig` does,
    so `config.resolve_model` serves both and `model_aliases` stays the single
    place a concrete model name appears."""
    project = support.make_project()
    ruleset = constitution.resolve(project)

    assert ruleset["models"]["chief"] == "worker", "an alias, not a model id"
    assert ruleset["fallback"] == "worker", "itself an alias (spec 4.4.1)"
    assert config.resolve_model("architect", ruleset) == "opus"
    assert config.resolve_effort("scribe", ruleset) == "low", "falls back to default"


# --- invariant 7 -------------------------------------------------------------

def test_brand_none_yields_no_brand(tmp_home: Path):
    project = support.make_project(brand=None)
    ruleset = constitution.resolve(project)

    assert ruleset["brand"] is None
    assert "brand" not in ruleset["slices"]


def test_a_real_brand_contributes_parsed_tokens_and_its_prose(tmp_home: Path):
    """Values live only in `tokens.css` (spec 4.2); `brand.md` is the prose slice
    saying which token applies where."""
    project = support.make_project(brand="acme")
    ruleset = constitution.resolve(project)

    assert ruleset["brand"]["slug"] == "acme"
    assert ruleset["brand"]["tokens_path"] == str(paths.brands() / "acme" / "tokens.css")
    assert ruleset["brand"]["tokens"]["--color-primary"] == "#1b365d"
    assert ruleset["brand"]["tokens"]["--font-body"] == '"Inter", sans-serif'
    assert "--color-accent" in ruleset["slices"]["brand"]["text"]


# --- invariant 8 -------------------------------------------------------------

def test_mode_is_local_and_the_project_block_is_recorded(tmp_home: Path):
    """`mode` travels inside the RuleSet so `gates/*.py` stay pure over their
    arguments instead of reading the environment (spec 4.4)."""
    project = support.make_project(name="demo", profile="flask-sqlite")
    ruleset = constitution.resolve(project)

    assert ruleset["mode"] == "local"
    assert isinstance(ruleset["hub_sha"], str), "'' until the hub is a git repository"
    assert ruleset["project"] == {
        "path": str(project.resolve()), "profile": "flask-sqlite", "name": "demo",
    }
    assert RULESET_KEYS <= set(ruleset), (
        f"missing RuleSet keys: {sorted(RULESET_KEYS - set(ruleset))}"
    )


# --- invariant 9 -------------------------------------------------------------

def test_resolve_writes_nothing(tmp_home: Path):
    """The purity spec 4.6's byte-for-byte tamper check rests on: a resolve()
    that wrote would rewrite the very file the check compares, so the check could
    never fail. Asserted over every file under HOME, by mtime and size."""
    project = support.make_project(
        brand="acme",
        slices={"product": "> What this does.\n",
                "overrides": "---\noverrides:\n  - rule: size.file-too-long\n"
                             "    reason: Recorded.\n---\n"},
    )
    before = support.tree_mtimes(tmp_home)
    constitution.resolve(project)
    assert support.tree_mtimes(tmp_home) == before


# --- invariant 10 ------------------------------------------------------------

def test_an_unregistered_project_is_a_clear_error(tmp_home: Path):
    project = support.make_project(register=False)
    with pytest.raises(ConfigError, match="not registered"):
        constitution.resolve(project)


def test_a_profile_naming_a_module_the_hub_lacks_is_a_clear_error(tmp_home: Path):
    """Chain 2 would otherwise resolve a dangling reference into silence: the
    slice would simply be absent, and nobody would know a rule stopped applying."""
    project = support.make_project(
        profile_patch={"modules": ["stack/flask-sqlite", "never", "security/ghost"]}
    )
    with pytest.raises(ConfigError, match="security/ghost"):
        constitution.resolve(project)


# --- the overrides slice, read by overrides.apply ----------------------------

def test_overrides_are_parsed_from_the_projects_overrides_md(tmp_home: Path):
    project = support.make_project(slices={"overrides": (
        "---\n"
        "overrides:\n"
        "  - rule:   size.file-too-long\n"
        '    scope:  "routes/legacy_report.py"\n'
        '    reason: "Being split ticket by ticket; see 0031."\n'
        "    until:  2026-12-31\n"
        "---\n"
        "\n"
        "Prose context for a human reader.\n"
    )})
    ruleset = constitution.resolve(project)

    assert len(ruleset["overrides"]) == 1
    assert ruleset["overrides"][0]["rule"] == "size.file-too-long"
    assert ruleset["overrides"][0]["until"] == date(2026, 12, 31)
    # Repo-relative, because it is shown to the owner on a Finding (spec 7.4).
    assert ruleset["overrides"][0]["source"] == ".taller/constitution/overrides.md"
    assert ruleset["non_suppressible"] == []


def test_non_suppressible_is_append_only_through_chain_1(tmp_home: Path):
    """Spec 4.5: the hub declares a floor, a profile and a project may add to it,
    and nothing can remove an entry."""
    project = support.make_project(
        hub_config={"non_suppressible": ["brand.hardcoded-color"]},
        project_config={"non_suppressible": ["constitution.layer-violation"]},
    )
    assert constitution.resolve(project)["non_suppressible"] == [
        "brand.hardcoded-color", "constitution.layer-violation",
    ]


# --- the snapshot names no machine -------------------------------------------

def test_the_snapshot_names_no_machine(tmp_home: Path):
    """`resolved.json` is committed to the project, and the project may be public.

    It already left the project's own path out for that reason; the paths of the
    rule files it was built from name the machine - the home directory, and with it
    the owner's user name - just as much, and made the snapshot differ from one
    checkout to the next.
    """
    project = support.make_project(slices={"product": "> What this does.\n"})

    written = constitution.render_snapshot(constitution.resolve(project)).decode("utf-8")
    snapshot = json.loads(written)

    assert str(tmp_home) not in written and str(tmp_home).replace("\\", "\\\\") not in written
    assert snapshot["slices"]["product"]["sources"] == ["project/.taller/constitution/product.md"]
    hub_sources = [source for slice_ in snapshot["slices"].values()
                   for source in slice_["sources"] if source.startswith("hub/")]
    assert hub_sources and all(source.startswith("hub/modules/") for source in hub_sources)


def test_resolving_still_gives_real_paths_for_the_screens_that_edit_them(tmp_home: Path):
    project = support.make_project(slices={"product": "> What this does.\n"})

    live = constitution.resolve(project)

    assert Path(live["slices"]["product"]["sources"][0]).is_file()
