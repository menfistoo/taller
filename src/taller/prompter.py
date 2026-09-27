"""The seam between Taller's questions and whoever answers them.

A wizard is a list of questions and a loop; the terminal is one way to answer
them and a scripted answer sheet is another. Keeping the seam this thin is what
lets the acceptance test drive the real `taller project new` rather than a copy
of it (plan, chunk 8).

Questions are addressed by **id**, never by order: a scripted answer sheet
survives a question being reworded or inserted, and a question nobody scripted
fails loudly instead of consuming someone else's answer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from .errors import TallerError


class Cancelled(TallerError):
    """The owner ended the conversation (Ctrl+C, Ctrl+D, or chose cancel)."""


class UnscriptedQuestion(Exception):
    """A scripted prompter was asked something its answer sheet does not cover.

    Deliberately not a TallerError: the CLI turns those into a one-line refusal,
    and a broken answer sheet must fail the test with a traceback instead.
    """


class Prompter(ABC):
    @abstractmethod
    def say(self, text: str) -> None:
        """Show text. No answer expected."""

    @abstractmethod
    def ask(self, qid: str, prompt: str) -> str:
        """One line of input, unvalidated. Validation is the caller's."""

    @abstractmethod
    def ask_lines(self, qid: str, prompt: str) -> list[str]:
        """Several lines; an empty line ends the list."""


class TerminalPrompter(Prompter):
    def say(self, text: str) -> None:
        print(text, flush=True)

    def ask(self, qid: str, prompt: str) -> str:
        print(prompt, flush=True)
        try:
            return input("  > ")
        except (EOFError, KeyboardInterrupt):
            print()
            raise Cancelled("Stopped. Answers given so far are kept.") from None

    def ask_lines(self, qid: str, prompt: str) -> list[str]:
        print(prompt, flush=True)
        lines: list[str] = []
        while True:
            try:
                line = input("  > ")
            except (EOFError, KeyboardInterrupt):
                print()
                raise Cancelled("Stopped. Answers given so far are kept.") from None
            if not line.strip():
                return lines
            lines.append(line)


class ScriptedPrompter(Prompter):
    """Answers from a sheet keyed by question id.

    A string answers once. A tuple answers the same id several times in order -
    how a test gives an invalid answer and then a valid one. A list answers an
    `ask_lines` question.
    """

    def __init__(self, answers: Mapping[str, Any]):
        self._queues: dict[str, list[Any]] = {
            qid: list(value) if isinstance(value, tuple) else [value]
            for qid, value in answers.items()
        }
        self.said: list[str] = []
        self.asked: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)

    def ask(self, qid: str, prompt: str) -> str:
        value = self._next(qid, prompt)
        if isinstance(value, list):
            raise UnscriptedQuestion(f"{qid} is a one-line question; the sheet gave a list.")
        return str(value)

    def ask_lines(self, qid: str, prompt: str) -> list[str]:
        value = self._next(qid, prompt)
        if not isinstance(value, list):
            raise UnscriptedQuestion(f"{qid} takes several lines; the sheet gave {value!r}.")
        return [str(line) for line in value]

    def _next(self, qid: str, prompt: str) -> Any:
        self.asked.append(qid)
        queue = self._queues.get(qid)
        if not queue:
            raise UnscriptedQuestion(
                f"Asked {qid!r}, which the answer sheet does not cover (or has run "
                f"out of answers for):\n{prompt}"
            )
        return queue.pop(0)

    def unused(self) -> dict[str, list[Any]]:
        return {qid: queue for qid, queue in self._queues.items() if queue}

    def assert_all_used(self) -> None:
        left = self.unused()
        if left:
            raise AssertionError(f"Scripted answers never asked for: {left}")
