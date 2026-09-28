"""What the whole-branch review of the plugin found, each pinned by a test.

The chat-facing protocol: answers Taller keeps per command (`taller answer`),
never reused by another command, replayed in order when a question comes twice,
and used only inside a Claude Code chat or with --answers.
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import pytest

import support
from taller import answers, cli, config, discovery, inference, locking, paths, spend, tickets
from taller.commands import brand as brand_command
from taller.commands import hook

from test_adopt import FILES, INTERVIEW, NEW_BRAND, SETUP, DISTILLED   # noqa: F401
from test_answers import NEW_PROJECT
from test_transcript_spend import record, ticket_on_branch, write_transcript

ROOT = Path(__file__).resolve().parents[2]
CLASSIFY = {"value": {"kind": "bug", "title": "Heading colour",
                      "summary": "The heading should use the danger colour."}}


@pytest.fixture
def chat(tmp_home: Path, identity, stub_claude, monkeypatch) -> Path:
    """A shell inside a Claude Code chat: CLAUDECODE set, no keyboard."""
    monkeypatch.setattr(brand_command, "open_in_browser", lambda page: None)
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    return tmp_home


def script(tmp_path: Path, monkeypatch, **roles) -> None:
    path = tmp_path / "script.json"
    path.write_text(json.dumps(roles), encoding="utf-8")
    monkeypatch.setenv("STUB_CLAUDE_SCRIPT", str(path))


def converse(argv: list[str], owner: dict, capsys, rounds: int = 40) -> str:
    """Run a command the way a command file says: on NEEDS, `taller answer`, rerun.

    `owner` maps an id to its answer, or to a tuple of answers for a question
    asked more than once in one run, in order.
    """
    given: dict[str, int] = {}
    for _ in range(rounds):
        code = cli.main(argv)
        out = capsys.readouterr().out
        if code != cli.EXIT_NEEDS_ANSWER:
            assert code == 0, out
            return out
        qid = re.search(r"^NEEDS (\S+)", out, re.MULTILINE).group(1)
        assert qid in owner, f"asked {qid}:\n{out}"
        wanted = owner[qid]
        wanted = wanted[given.get(qid, 0)] if isinstance(wanted, tuple) else wanted
        given[qid] = given.get(qid, 0) + 1
        values = wanted if isinstance(wanted, list) else [wanted]
        assert cli.main(["answer", qid, *values]) == 0, capsys.readouterr().out
        capsys.readouterr()
    raise AssertionError(f"{argv} still needed answers after {rounds} rounds")


# --- C1: a command's answers are its own, and gone when it finishes -----------------

def test_answers_belong_to_one_command_and_are_cleared_when_it_finishes(chat, tmp_path,
                                                                         monkeypatch, capsys):
    project = support.new_project()
    script(tmp_path, monkeypatch, chief=[CLASSIFY, CLASSIFY])
    argv = ["ticket", "new", "--path", str(project)]

    converse(argv, {"ticket.words": ["The red is wrong."]}, capsys)
    code = cli.main(argv)

    assert code == 3 and "NEEDS ticket.words" in capsys.readouterr().out
    assert len(tickets.list_tickets(project)[0]) == 1


def test_an_answer_with_nothing_waiting_is_refused(chat, capsys):
    assert cli.main(["answer", "q1", "x"]) == cli.EXIT_REFUSED
    assert "Nothing is waiting" in capsys.readouterr().out


def test_the_needs_message_says_how_to_answer_in_a_chat(chat, capsys):
    project = support.new_project()

    cli.main(["ticket", "new", "--path", str(project)])

    out = capsys.readouterr().out
    assert "taller answer ticket.words" in out and "answers file" not in out


# --- C3: a question asked twice in one run --------------------------------------------

ADOPTER = {**SETUP, **INTERVIEW, **NEW_BRAND, "resume": "y",
           "setup.roots": "", "setup.review": "1",
           "brief": ("4", "1")}           # keep the old review directories, then approve


@pytest.fixture
def adoptable(chat, monkeypatch) -> Path:
    monkeypatch.setenv("STUB_CLAUDE_RESPONSE", json.dumps({
        "type": "result", "subtype": "success", "is_error": False, "session_id": "s",
        "result": "", "structured_output": DISTILLED,
        "usage": {"input_tokens": 1, "output_tokens": 1}}))
    return support.make_repo(paths.home() / "projects" / "tool-library", FILES)


def test_a_question_asked_twice_takes_its_answers_in_order(adoptable, capsys):
    said = converse(["project", "adopt", str(adoptable), "--no-open"], ADOPTER, capsys)

    assert (adoptable / "code-review" / "README.md").is_file(), said   # the owner kept it
    assert answers.pending() is None


# --- C2: nothing is asked after the project exists --------------------------------------

def test_project_new_does_not_ask_about_a_remote_it_cannot_undo(chat, monkeypatch, capsys):
    monkeypatch.setattr(discovery, "gh_auth_status", lambda: {
        "ok": True, "account": "someone", "message": "Signed in to GitHub as someone."})
    projects = paths.home() / "projects"

    said = converse(["project", "new", "toolshed", "--path", str(projects), "--no-open"],
                    {**NEW_PROJECT, "resume": "y"}, capsys)

    assert (projects / "toolshed").is_dir()
    assert "gh repo create" in said and "not pushed" in said


# --- I1: a person at a console that is not a terminal still gets questions ------------

def test_without_a_chat_a_non_terminal_still_asks(tmp_home, identity, stub_claude,
                                                  monkeypatch, capsys):
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    typed = iter(["Fix the red heading", ""])          # the words, then an empty line

    def keyboard(prompt=""):
        try:
            return next(typed)
        except StopIteration:
            raise EOFError from None                    # the person stops typing
    monkeypatch.setattr("builtins.input", keyboard)
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    project = support.new_project()
    monkeypatch.setenv("STUB_CLAUDE_FAIL_EXIT", "1")

    code = cli.main(["ticket", "new", "--path", str(project)])

    assert code in (0, 1) and "NEEDS" not in capsys.readouterr().out


# --- I2: the distilled architecture is made once per adoption ---------------------------

def test_adoption_distils_claude_md_once_across_reruns(adoptable, stub_claude, capsys):
    # The brief is asked twice, so the command runs at least twice past the distillation.
    converse(["project", "adopt", str(adoptable), "--no-open"], ADOPTER, capsys)

    distils = [a for a in stub_claude.calls() if "ROLE: architect" in " ".join(a)]
    assert len(distils) == 1


def test_new_md_never_reruns_ticket_new_after_a_timeout():
    body = (ROOT / "commands" / "new.md").read_text(encoding="utf-8")

    assert "taller ticket list" in body and "timed out" in body


# --- I3: the permission layer ------------------------------------------------------------

@pytest.mark.parametrize("verb", ["new", "approve", "reject", "resume", "status", "amend",
                                  "onboard"])
def test_commands_answer_through_taller_and_allow_only_their_own_verbs(verb):
    text = (ROOT / "commands" / f"{verb}.md").read_text(encoding="utf-8")
    head = text.split("\n---\n", 1)[0]

    assert "--answers" not in text and "answers file" not in text
    assert "Bash(taller answer:*)" in head and "taller answer" in text


# --- I4: Taller's own dispatches are never chat spend --------------------------------------

def test_a_print_mode_dispatch_is_never_counted_as_chat_spend(chat, tmp_path):
    project = support.new_project()
    ticket = ticket_on_branch(project)
    lost = json.loads(record("killed-dispatch", ticket["branch"], "k1"))
    lost["entrypoint"] = "sdk-cli"
    write_transcript(tmp_path, project, "killed-dispatch", json.dumps(lost))

    assert spend.from_transcripts(project, ticket, root=tmp_path) == {}


# --- I5: a busy project says so, and never invites removing a live lock ------------------

def test_a_live_lock_names_its_holder_and_is_not_offered_for_removal(tmp_home):
    path = paths.run_dir() / "locks" / "busy.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(__import__("os").getpid()), encoding="ascii")

    with pytest.raises(Exception) as caught:
        with locking.file_lock(path, timeout=0.2):
            pass

    message = str(caught.value)
    assert str(__import__("os").getpid()) in message and "remove" not in message


@pytest.mark.parametrize("verb", ["new", "approve", "reject", "resume", "amend"])
def test_commands_wait_for_a_running_ticket_and_never_touch_locks(verb):
    body = (ROOT / "commands" / f"{verb}.md").read_text(encoding="utf-8")

    assert "wait" in body and "lock" in body


# --- I6: UTF-8 at the boundaries ----------------------------------------------------------

def test_the_hook_reads_its_event_as_utf8(monkeypatch):
    raw = json.dumps({"cwd": "C:/Usuarios/José/proyecto"}, ensure_ascii=False).encode("utf-8")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="cp1252"))

    assert hook.read_event() == {"cwd": "C:/Usuarios/José/proyecto"}


def test_an_answers_file_with_a_byte_order_mark_is_read(tmp_home, identity, stub_claude,
                                                         monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(discovery, "_run_gh", lambda args: None)
    project = support.new_project()
    sheet = tmp_path / "a.json"
    sheet.write_bytes(b"\xef\xbb\xbf" + json.dumps({"ticket.reason": "x"}).encode("utf-8"))

    cli.main(["--answers", str(sheet), "ticket", "list", "--path", str(project)])

    assert "not valid JSON" not in capsys.readouterr().out


# --- I7: a dispatch from a chat is not a nested session -----------------------------------

def test_a_dispatch_does_not_inherit_the_chat_session(chat, tmp_path, monkeypatch):
    log = tmp_path / "env.jsonl"
    monkeypatch.setenv("STUB_CLAUDE_ENV", str(log))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "host-session")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "claude-desktop")

    inference.infer(inference.Dispatch(role="scribe", prompt="hi",
                                       config=config.load_hub_config()))

    seen = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert not {"CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT"} & set(seen)
