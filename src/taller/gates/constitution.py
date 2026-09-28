"""The constitution gate: every rule has a decidable test (spec 9.1).

`run` judges a change - added lines, new files, the branch's commits. `scan`
judges a whole tree with the same rules, minus the ones only a change can break
(commit shape, new UI text, a branch carrying the snapshot).

A file that is binary or not UTF-8 is skipped with a note in `metrics.skipped`,
never a crash. So is a Python file whose imports cannot be parsed.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from typing import Any

from taller import globs, overrides
from taller.gates import Finding, Verdict, finding, verdict
from taller.gates.diff import Diff

GATE = "constitution"

STYLE_SUFFIXES = (".css", ".scss")
MARKUP_SUFFIXES = (".html", ".htm", ".j2", ".jinja", ".jinja2", ".vue")
SCRIPT_SUFFIXES = (".js",)
TEMPLATE_SUFFIXES = (".html", ".htm", ".j2", ".jinja", ".jinja2")

ROOT_MARKDOWN_ALLOWED = {"readme.md", "claude.md", "changelog.md", "license.md"}
SINGLE_USE = ("fix_*.py", "check_*.py", "debug_*.py", "diagnose_*.py", "_*.py", "test_*.py")
COMMIT_SHAPE = re.compile(r"^(feat|fix|refactor|chore|docs|test|perf)(\([a-z0-9-]+\))?: .{1,72}$")
SNAPSHOT_FILES = (".taller/resolved.json", ".taller/constitution/00-index.md")
SNAPSHOT = ".taller/resolved.json"
FONT_KEYWORDS = {"inherit", "initial", "unset", "revert"}

# `&#39;` is an entity and `a#b` part of a word: neither is a colour.
_HEX = re.compile(r"(?<![&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])")
_FUNCTION = re.compile(r"\b(?:rgba?|hsla?)\(", re.IGNORECASE)
_VAR_OPEN = re.compile(r"\bvar\(")
# Attribute values that hold anchors and targets, not colours.
_ANCHOR_ATTRS = re.compile(
    r"""\b(?:href|id|for|name|xlink:href|data-[\w-]+|aria-[\w-]+)\s*=\s*("[^"]*"|'[^']*')""",
    re.IGNORECASE)
# In markup and script, `#fade {`, `#fade:hover`, `#fade > a` are selectors.
_SELECTOR_AFTER = re.compile(r"\s*\{|[:.\[][A-Za-z-]|\s*[>+~]")
_FONT = re.compile(r"font-family\s*:\s*([^;}]+)", re.IGNORECASE)
_WHOLLY_VAR = re.compile(r"^var\(--[\w-]+(?:\s*,.*)?\)$", re.DOTALL)
_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}")
_TEXT_ATTRS = re.compile(
    r"""\b(placeholder|title|aria-label|alt)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
_TAG = re.compile(r"<[^<>]*>")
_ENTITY = re.compile(r"&#?\w+;")
_LETTER = re.compile(r"[^\W\d_]")


def run(diff: Diff, ruleset: Mapping[str, Any], *, snapshot_sha: str | None = None) -> Verdict:
    """The change on a branch. `snapshot_sha`: the `hub_sha` main's snapshot records."""
    return _judge(diff, ruleset, snapshot_sha=snapshot_sha, change=True)


def scan(tree_diff: Diff, ruleset: Mapping[str, Any], *,
         snapshot_sha: str | None = None) -> Verdict:
    """A whole tree (`diff.tree`): every file as added, no commits (spec 9.5)."""
    return _judge(tree_diff, ruleset, snapshot_sha=snapshot_sha, change=False)


def _judge(diff: Diff, ruleset: Mapping[str, Any], *, snapshot_sha: str | None,
           change: bool) -> Verdict:
    paths = ruleset.get("paths") or {}
    findings: list[Finding] = []
    skipped: list[str] = []
    tracked = diff.get("tracked") or [f["path"] for f in diff["files"]]
    ui_language = _ui_language(ruleset)

    for file in diff["files"]:
        path = file["path"]
        if file["status"] == "D":
            continue
        if change and path in SNAPSHOT_FILES:
            findings.append(finding(
                "constitution.resolved-snapshot-modified", path, 0,
                f"The branch changes {path}, which only `taller resolve` writes, on main.",
                "Drop the change to this file from the branch; nothing is lost."))
        if file["status"] == "A" and "/" not in path:
            findings.extend(_root_file(path, paths))
        if file["content"] is None:
            skipped.append(path)
            continue
        added = {entry["line"] for entry in file["added"]}
        if not added:
            continue
        lower = path.lower()
        if not _is_tokens_file(path, paths):
            if lower.endswith(STYLE_SUFFIXES + MARKUP_SUFFIXES + SCRIPT_SUFFIXES):
                findings.extend(_colours(path, file["content"], added))
            if lower.endswith(STYLE_SUFFIXES + MARKUP_SUFFIXES):
                findings.extend(_fonts(path, file["content"], added))
        if change and ui_language and lower.endswith(TEMPLATE_SUFFIXES):
            findings.extend(_ui_literals(path, file["content"], added))
        if lower.endswith(".py") and _layer_of(path, paths) is not None:
            layer_findings = _layers(path, file["content"], paths, tracked)
            if layer_findings is None:
                skipped.append(path)
            else:
                findings.extend(layer_findings)

    if change:
        findings.extend(_commit_shapes(diff.get("commits") or []))
    if snapshot_sha and ruleset.get("hub_sha") and snapshot_sha != ruleset["hub_sha"]:
        findings.append(finding(
            "constitution.resolved-snapshot-stale", SNAPSHOT, 0,
            f"The snapshot on main was resolved from hub {snapshot_sha[:7]}; "
            f"the rules are now at {str(ruleset['hub_sha'])[:7]}.",
            "`taller resolve` rewrites it."))
    findings.extend(overrides.apply([], dict(ruleset)))

    return verdict(GATE, findings, {"files_checked": len(diff["files"]), "skipped": skipped})


# --- rules ---------------------------------------------------------------------------

def _root_file(path: str, paths: Mapping[str, Any]) -> list[Finding]:
    if path.lower().endswith(".md") and path.lower() not in ROOT_MARKDOWN_ALLOWED:
        return [finding("constitution.root-markdown", path, 0,
                        f"{path} is a new markdown file at the repository root.",
                        "Move it under docs/, or fold it into README.md.")]
    tests_dir = str(paths.get("tests_dir") or "").strip("/")
    for pattern in SINGLE_USE:
        if pattern == "test_*.py" and tests_dir in ("", "."):
            continue
        if globs.match(path, pattern):
            return [finding("constitution.single-use-script", path, 0,
                            f"{path} looks like a one-off script committed at the root.",
                            "Delete it, or make it a test or a real command.")]
    return []


def _colours(path: str, content: str, added: set[int]) -> list[Finding]:
    """One finding per brand-shaped literal on an added line (Review Focus 5)."""
    out: list[Finding] = []
    is_style = path.lower().endswith(STYLE_SUFFIXES)
    state = _CssState()
    for number, raw in enumerate(content.splitlines(), 1):
        line = _blank_vars(raw)
        if not is_style:
            line = _blank(_ANCHOR_ATTRS, line)
        values = state.value_columns(line) if is_style else None
        if number not in added:
            continue
        for match in (*_HEX.finditer(line), *_FUNCTION.finditer(line)):
            if values is not None and match.start() not in values:
                continue
            if (values is None and match.group().startswith("#")
                    and _SELECTOR_AFTER.match(line, match.end())):
                continue
            literal = match.group().rstrip("(")
            out.append(finding("brand.hardcoded-color", path, number,
                               f"A literal colour, {literal}, where a brand token belongs.",
                               "Use the matching var(--brand-...) from the brand tokens."))
    return out


def _fonts(path: str, content: str, added: set[int]) -> list[Finding]:
    out: list[Finding] = []
    for number, line in enumerate(content.splitlines(), 1):
        if number not in added:
            continue
        for match in _FONT.finditer(line):
            value = match.group(1).strip().rstrip("\"'>").strip()
            if value.lower() in FONT_KEYWORDS or _WHOLLY_VAR.match(value):
                continue
            out.append(finding("brand.hardcoded-font", path, number,
                               f"A literal font, {value}, where the brand font token belongs.",
                               "Use var(--brand-font...) from the brand tokens."))
    return out


def _ui_literals(path: str, content: str, added: set[int]) -> list[Finding]:
    """New user-visible text in a template (spec 8.2). Language is not judged."""
    out: list[Finding] = []
    raw_block = None                    # inside <script> or <style>: code, not text
    for number, raw in enumerate(content.splitlines(), 1):
        line = _JINJA.sub(" ", raw)
        texts: list[str] = []
        for match in _TEXT_ATTRS.finditer(line):
            texts.append(match.group(2) if match.group(2) is not None else match.group(3))
        visible, raw_block = _text_nodes(line, raw_block)
        texts.extend(visible)
        if number not in added:
            continue
        for text in texts:
            text = " ".join(_ENTITY.sub(" ", text).split())
            if _LETTER.search(text):
                out.append(finding("constitution.new-ui-literal", path, number,
                                   f'New UI text: "{text}"',
                                   "Check it is in the project's UI language."))
    return out


def _text_nodes(line: str, raw_block: str | None) -> tuple[list[str], str | None]:
    texts: list[str] = []
    position = 0
    # The tail of a tag opened on an earlier line: `  placeholder="x">`.
    head = re.match(r"^[^<>]*=\s*(\"[^\"]*\"|'[^']*')[^<>]*>", line)
    if head:
        position = head.end()
    for tag in _TAG.finditer(line, position):
        if raw_block is None:
            texts.append(line[position:tag.start()])
        name = re.match(r"<\s*(/?)\s*(\w+)", tag.group())
        if name and name.group(2).lower() in ("script", "style"):
            raw_block = None if name.group(1) else name.group(2).lower()
        position = tag.end()
    tail = line[position:]
    if raw_block is None and "<" not in tail:
        texts.append(tail)
    elif raw_block is None:
        texts.append(tail[:tail.index("<")])
    return [t for t in texts if t.strip()], raw_block


def _layers(path: str, content: str, paths: Mapping[str, Any],
            tracked: list[str]) -> list[Finding] | None:
    """Imports of local modules the file's layer may not use; None if unparseable."""
    key = _layer_of(path, paths)
    allowed = [str(entry) for entry in (paths.get("layers") or {}).get(key) or []]
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return None
    own = path.split("/", 1)[0].removesuffix(".py")
    out: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            candidates = [[alias.name] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            candidates = [[node.module, f"{node.module}.{alias.name}"] for alias in node.names]
        else:
            continue
        for names in candidates:
            top = names[0].split(".", 1)[0]
            if top == own or not _is_local(top, tracked):
                continue
            if any(_allowed(name, allowed) for name in names):
                continue
            out.append(finding(
                "constitution.layer-violation", path, node.lineno,
                f"{path} imports `{names[0]}`, which its layer ({key}) may not use.",
                "Allowed here: " + (", ".join(allowed) or "nothing local") + "."))
            break
    return out


def _commit_shapes(commits: list[Mapping[str, Any]]) -> list[Finding]:
    out: list[Finding] = []
    for commit in commits:
        subject = str(commit.get("message") or "").splitlines()[0] if commit.get(
            "message") else ""
        # Taller's own merges of main into a ticket branch are not the author's words.
        if subject.startswith("Merge ") or COMMIT_SHAPE.match(subject):
            continue
        out.append(finding(
            "constitution.commit-message-shape", "", 0,
            f"Commit {str(commit.get('sha', ''))[:7]} is titled \"{subject}\".",
            "Use `type(scope): summary` - feat, fix, refactor, chore, docs, test or perf."))
    return out


# --- helpers -------------------------------------------------------------------------

class _CssState:
    """Which columns of each line are declaration values, across lines.

    A colour in a value is a literal; `#fade` before a `{` is a selector.
    Comments are skipped; nesting (SCSS) is followed by depth.
    """

    def __init__(self) -> None:
        self.depth = 0
        self.in_value = False
        self.in_comment = False

    def value_columns(self, line: str) -> set[int]:
        columns: set[int] = set()
        index = 0
        while index < len(line):
            pair = line[index:index + 2]
            if self.in_comment:
                if pair == "*/":
                    self.in_comment = False
                    index += 2
                    continue
            elif pair == "/*":
                self.in_comment = True
                index += 2
                continue
            else:
                char = line[index]
                if char == "{":
                    self.depth += 1
                    self.in_value = False
                elif char == "}":
                    self.depth = max(0, self.depth - 1)
                    self.in_value = False
                elif char == ";":
                    self.in_value = False
                elif char == ":" and self.depth > 0:
                    self.in_value = True
                elif self.in_value:
                    columns.add(index)
            index += 1
        return columns


def _blank(pattern: re.Pattern[str], line: str) -> str:
    """Replace each match with spaces, so columns and line numbers still line up."""
    return pattern.sub(lambda match: " " * len(match.group()), line)


def _blank_vars(line: str) -> str:
    """`var(--a, var(--b, #fff))`: the fallback is not a literal the author chose."""
    out = list(line)
    for match in _VAR_OPEN.finditer(line):
        depth, index = 0, match.end() - 1
        while index < len(line):
            depth += {"(": 1, ")": -1}.get(line[index], 0)
            if depth == 0:
                break
            index += 1
        out[match.start():index + 1] = " " * (min(index, len(line) - 1) + 1 - match.start())
    return "".join(out)


def _is_tokens_file(path: str, paths: Mapping[str, Any]) -> bool:
    tokens = paths.get("brand_tokens")
    return bool(tokens) and globs.match(path, str(tokens))


def _layer_of(path: str, paths: Mapping[str, Any]) -> str | None:
    for key in (paths.get("layers") or {}):
        if globs.match(path, str(key)):
            return str(key)
    return None


def _is_local(top: str, tracked: list[str]) -> bool:
    return any(p == f"{top}.py" or p.startswith(f"{top}/") for p in tracked)


def _allowed(name: str, allowed: list[str]) -> bool:
    for entry in allowed:
        if name == entry or name.startswith(entry + "."):
            return True
        if entry.endswith(".*") and (name == entry[:-2] or name.startswith(entry[:-1])):
            return True
    return False


def _ui_language(ruleset: Mapping[str, Any]) -> str | None:
    language = ruleset.get("language")
    if not isinstance(language, Mapping):
        return None
    ui = language.get("ui")
    return str(ui) if ui and ui != "none" else None
