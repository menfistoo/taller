"""The cockpit's two screens, and the two writes (spec 12).

Reading is `reading.py`'s job and writing is the library's; this module only
routes, and turns a refusal into something a person can act on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from taller import onboarding, paths, tickets
from taller.errors import LockTimeout, TallerError

from . import (check_token, configuration, health, interview, reading, rules, runs,
               spending)

bp = Blueprint("cockpit", __name__)


@bp.get("/")
def board():
    return render_template("board.html", board=reading.board())


@bp.get("/spend")
def spend():
    return render_template("spend.html", page=spending.figures())


@bp.get("/new")
def interview_new():
    """Where a project starts: its name, and the folder to put it in."""
    unfinished = []
    for kept in sorted(interview.started_dir().glob("*.json")):
        name = kept.stem
        answered = len(onboarding.load_progress(name))
        if answered < len(onboarding.QUESTIONS):
            unfinished.append((name, answered))
    return render_template("new.html", page={"default_path": str(paths.home() / "projects"),
                                             "unfinished": unfinished})


@bp.post("/new")
def interview_start():
    check_token()
    name = (request.form.get("name") or "").strip()
    begun = interview.start(name, request.form.get("path", ""))
    if begun.get("problem"):
        flash(begun["problem"], "warning")
        return redirect(url_for("cockpit.interview_new"))
    return redirect(url_for("cockpit.interview_page", name=name))


@bp.get("/new/<name>")
def interview_page(name: str):
    return render_template("interview.html", page=interview.page(name),
                           questions=onboarding.QUESTIONS)


@bp.post("/new/<name>")
def interview_answer(name: str):
    """One answer, judged by the same library call the terminal makes."""
    check_token()
    key = request.form.get("key", "")
    if request.form.get("again"):
        # "Change an answer": forget it, and the page asks it again.
        answers = onboarding.load_progress(name)
        answers.pop(key, None)
        onboarding.save_progress(name, answers)
        return redirect(url_for("cockpit.interview_page", name=name))
    taken = interview.answer(name, key, request.form.get("value", ""))
    if not taken["ok"]:
        flash(taken["problem"], "warning")
    return redirect(url_for("cockpit.interview_page", name=name))


@bp.post("/new/<name>/create")
def interview_create(name: str):
    check_token()
    try:
        made = interview.create(name)
        flash(f"Created {name} in {made['target']}.", "info")
        return redirect(url_for("cockpit.board"))
    except TallerError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("cockpit.interview_page", name=name))


@bp.get("/rules")
def rules_page():
    """One project's rules. With no project named, the first one she has."""
    wanted = request.args.get("project")
    if not wanted:
        available = [entry["name"] for entry in reading.projects() if entry["available"]]
        if not available:
            return render_template("problem.html", heading="No projects yet",
                                   detail="`taller project new` starts one, and its rules "
                                          "appear here."), 404
        return redirect(url_for("cockpit.rules_page", project=available[0]))
    try:
        page = rules.slices(wanted)
    except TallerError as exc:
        abort(404, str(exc))
    return render_template("rules.html", page=page)


@bp.post("/rules/<project>")
def rules_write(project: str):
    """Amend one rule file: write, commit, and refresh what it reaches."""
    check_token()
    try:
        for line in rules.save(project, request.form.get("path", ""),
                               request.form.get("text", ""),
                               request.form.get("reason", "")):
            flash(line, "info")
    except TallerError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("cockpit.rules_page", project=project))


@bp.get("/health")
def health_page():
    return render_template("health.html", page={"projects": health.projects()})


@bp.post("/health/<project>")
def health_check(project: str):
    """Scan one project now. She asked for it, so the request may take its time."""
    check_token()
    try:
        figures = health.check(project)
        flash(f"Checked {project} in {figures['seconds']}s.", "info")
    except TallerError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("cockpit.health_page"))


@bp.get("/settings")
def settings_page():
    return render_template("settings.html",
                           page=configuration.rows(request.args.get("project") or None))


@bp.post("/settings")
def settings_write():
    """One key, written to the layer the library chooses for it."""
    check_token()
    project = request.form.get("project") or None
    try:
        for line in configuration.save(request.form.get("key", ""),
                                       request.form.get("value", ""), project):
            flash(line, "info")
    except TallerError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("cockpit.settings_page", project=project))


@bp.get("/ticket/<project>/<int:ticket_id>")
def ticket(project: str, ticket_id: int):
    try:
        page = reading.ticket_page(project, ticket_id)
    except TallerError as exc:
        # A number she typed, or a ticket that never existed: her words back, not
        # a stack trace.
        abort(404, str(exc))
    return render_template("ticket.html", page=page,
                           run=runs.progress(runs.run_id(page["project"], ticket_id)))


@bp.post("/ticket/<project>/<int:ticket_id>/approve")
def approve(project: str, ticket_id: int):
    """Approve at this stage's checkpoint, then let the work carry on.

    The approval is `tickets.approve` - the same call the terminal makes, under
    the same lock - and the work that follows is `taller ticket run` in its own
    process. Nothing here waits for it: the page shows where it has got to and
    refreshes itself while it is going.
    """
    def act(path: Path, name: str) -> None:
        tickets.approve(path, ticket_id)
        runs.start(path, name, ticket_id)

    return _write(project, ticket_id, act)


@bp.post("/ticket/<project>/<int:ticket_id>/change")
def change(project: str, ticket_id: int):
    """Spec 12's third action: what she asked for, corrected in her own words."""
    title = request.form.get("title", "")
    words = request.form.get("words", "")

    def act(path: Path, name: str) -> None:
        tickets.reword(path, ticket_id, title=title, words=words)

    return _write(project, ticket_id, act)


@bp.post("/ticket/<project>/<int:ticket_id>/reject")
def reject(project: str, ticket_id: int):
    """Say no, in her own words. The words are the whole point: the next attempt
    reads them, so a rejection with nothing in it is refused rather than kept."""
    reason = request.form.get("reason", "")

    def act(path: Path, name: str) -> None:
        tickets.reject(path, ticket_id, reason)

    return _write(project, ticket_id, act)


def _write(project: str, ticket_id: int, act: Callable[[Path, str], None]) -> Any:
    """Check the token, do the write, and come back to the ticket's page.

    Every refusal the library can make - a checkpoint that is not one, a
    rejection with no reason, a project someone else is working on - arrives
    here as a TallerError carrying a sentence meant for her, so it is shown as
    that sentence and nothing is left half done.
    """
    check_token()
    try:
        entry = reading.entry_for(project)
        act(Path(entry["path"]), entry["name"])
    except LockTimeout as exc:
        flash(f"Taller is busy with this project, so nothing was changed. {exc}", "warning")
    except TallerError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("cockpit.ticket", project=project, ticket_id=ticket_id))
