"""The size gate: file length, function length, duplicated blocks (spec 9.1).

`run` judges what a change added: a function is judged when an added line falls
inside it, a duplicate when one of its windows holds an added line. `scan`
treats every line of every file as added.

Duplication follows spec 9.1 exactly: comments and blank lines dropped, runs of
whitespace collapsed, identifiers and literals kept verbatim - so the answer is
the same locally and in CI, and similar-but-distinct code is never flagged.
"""

from __future__ import annotations

import ast
import hashlib
import io
import re
import tokenize
from collections.abc import Mapping
from typing import Any

from taller.gates import Finding, Verdict, finding, verdict
from taller.gates.diff import Diff

GATE = "size"
DEFAULTS = {"max_file_lines": 800, "max_function_lines": 80, "dup_block_lines": 12}
# Hand-written source. A lock file or a data dump is long by nature, not by design.
SOURCE_SUFFIXES = (".py", ".js", ".ts", ".jsx", ".tsx", ".vue", ".css", ".scss",
                   ".html", ".htm", ".j2", ".jinja", ".jinja2", ".sh", ".sql")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/|<!--.*?-->|\{#.*?#\}", re.DOTALL)
_LINE_COMMENT = re.compile(r"(?:^|\s)//.*$")

Normalised = list[tuple[int, str]]          # (original line number, normalised text)


def run(diff: Diff, ruleset: Mapping[str, Any], *, tree: Diff | None = None) -> Verdict:
    """`tree` (usually `diff.tree(worktree)`) lets a duplicate of an untouched file count."""
    return _judge(diff, ruleset, tree=tree)


def scan(tree_diff: Diff, ruleset: Mapping[str, Any]) -> Verdict:
    return _judge(tree_diff, ruleset, tree=tree_diff)


def _judge(diff: Diff, ruleset: Mapping[str, Any], *, tree: Diff | None) -> Verdict:
    limits = {**DEFAULTS, **(ruleset.get("thresholds") or {})}
    findings: list[Finding] = []
    skipped: list[str] = []
    longest = 0
    files = [f for f in diff["files"] if f["status"] != "D"
             and f["path"].lower().endswith(SOURCE_SUFFIXES)]

    for file in files:
        if file["content"] is None:
            skipped.append(file["path"])
            continue
        count = len(file["content"].splitlines())
        if count > limits["max_file_lines"]:
            findings.append(finding(
                "size.file-too-long", file["path"], 0,
                f"{file['path']} is {count} lines; the limit is {limits['max_file_lines']}.",
                "Splitting it is a design decision - the owner or the architect makes it."))
        if file["path"].lower().endswith(".py"):
            functions = _functions(file["content"])
            if functions is None:
                skipped.append(file["path"])
                continue
            added = {entry["line"] for entry in file["added"]}
            for name, start, end in functions:
                if not added.intersection(range(start, end + 1)):
                    continue
                length = end - start + 1
                longest = max(longest, length)
                if length > limits["max_function_lines"]:
                    findings.append(finding(
                        "size.function-too-long", file["path"], start,
                        f"{name}() is {length} lines; the limit is "
                        f"{limits['max_function_lines']}.",
                        "Extract the steps it runs one after another into helpers."))

    corpus = [f for f in (tree or diff)["files"] if f["status"] != "D"
              and f.get("content") is not None
              and f["path"].lower().endswith(SOURCE_SUFFIXES)]
    findings.extend(_duplicates([f for f in files if f["content"] is not None], corpus,
                                int(limits["dup_block_lines"])))
    return verdict(GATE, findings, {"files_checked": len(files), "longest_function": longest,
                                    "skipped": skipped})


def _functions(content: str) -> list[tuple[str, int, int]] | None:
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return None
    return [(node.name, node.lineno, node.end_lineno or node.lineno)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


# --- duplication ---------------------------------------------------------------------

def normalise(path: str, content: str) -> Normalised:
    """Spec 9.1: no comments, no blank lines, whitespace runs collapsed."""
    if path.lower().endswith(".py"):
        content = _strip_python_comments(content)
    else:
        content = _BLOCK_COMMENT.sub(lambda m: "\n" * m.group().count("\n"), content)
    out: Normalised = []
    for number, line in enumerate(content.splitlines(), 1):
        if not path.lower().endswith(".py"):
            line = _LINE_COMMENT.sub("", line)
        text = " ".join(line.split())
        if text:
            out.append((number, text))
    return out


def _strip_python_comments(content: str) -> str:
    """Comments removed by the tokenizer, so a `#` inside a string survives."""
    lines = content.splitlines()
    try:
        for token in tokenize.generate_tokens(io.StringIO(content).readline):
            if token.type == tokenize.COMMENT:
                row, col = token.start
                lines[row - 1] = lines[row - 1][:col]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass                                # best effort: an unparseable file keeps its text
    return "\n".join(lines)


def _duplicates(changed: list[dict], corpus: list[dict], window: int) -> list[Finding]:
    if window < 1:
        return []
    normalised = {f["path"]: normalise(f["path"], f["content"]) for f in corpus}
    for f in changed:
        normalised.setdefault(f["path"], normalise(f["path"], f["content"]))
    index: dict[str, list[tuple[str, int]]] = {}
    for path, lines in normalised.items():
        for start in range(len(lines) - window + 1):
            index.setdefault(_digest(lines, start, window), []).append((path, start))

    findings: list[Finding] = []
    reported: set[tuple[tuple[str, int], tuple[str, int]]] = set()
    added_of = {f["path"]: {entry["line"] for entry in f["added"]} for f in changed}

    for f in changed:
        path, lines, added = f["path"], normalised[f["path"]], added_of[f["path"]]
        run_start = run_other = None
        for start in range(len(lines) - window + 1):
            covered = {number for number, _ in lines[start:start + window]}
            others = [(p, s) for p, s in index[_digest(lines, start, window)]
                      if p != path or abs(s - start) >= window]
            if covered & added and others:
                if run_start is None:
                    run_start, run_other = start, others[0]
                continue
            if run_start is not None:
                _report(findings, reported, path, lines, run_start, run_other, normalised,
                        start - run_start + window - 1)
                run_start = None
        if run_start is not None:
            _report(findings, reported, path, lines, run_start, run_other, normalised,
                    len(lines) - run_start)
    return findings


def _report(findings: list[Finding], reported: set, path: str, lines: Normalised,
            start: int, other: tuple[str, int], normalised: dict[str, Normalised],
            span: int) -> None:
    here = (path, lines[start][0])
    there = (other[0], normalised[other[0]][other[1]][0])
    pair = tuple(sorted((here, there)))
    if pair in reported:
        return
    reported.add(pair)
    findings.append(finding(
        "size.duplicate-block", path, here[1],
        f"{span} lines here repeat {there[0]}:{there[1]}.",
        "Extract the shared lines into one function both places call."))


def _digest(lines: Normalised, start: int, window: int) -> str:
    joined = "\n".join(text for _, text in lines[start:start + window])
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()
