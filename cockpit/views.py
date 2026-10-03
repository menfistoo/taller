"""The cockpit's two screens, and the two writes (spec 12).

Reading is `reading.py`'s job and writing is the library's; this module only
routes, and turns a refusal into something a person can act on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from taller import onboarding, paths, publishing, tickets
from taller.errors import TallerError

from . import (check_token, configuration, health, interview, plain, project_settings,
               reading, rules, runs, services, spending, usage, words)

bp = Blueprint("cockpit", __name__)


@bp.get("/")
def home():
    """Her projects and what she asked for, in plain words (the plain front)."""
    return render_template("plain/home.html", page=plain.home())


@bp.post("/publish/<project>")
def publish(project: str):
    """Her say-so: send everything of this project's that waited."""
    check_token()
    try:
        path = Path(reading.entry_for(project)["path"])
        sent = publishing.send(path)
    except TallerError as exc:
        flash(plain.problem(exc), "warning")
        return redirect(url_for("cockpit.home"))
    if sent["problem"]:
        flash(sent["problem"], "warning")
    else:
        flash(words.PUBLISH["done"], "info")
    return redirect(url_for("cockpit.home"))


@bp.get("/project/<project>/about")
def settings_about(project: str):
    try:
        page = project_settings.about(project)
    except TallerError as exc:
        abort(404, str(exc))
    return render_template("plain/settings/about.html", page=page, current_tab="about")


@bp.post("/project/<project>/about")
def settings_about_change(project: str):
    """One card's answers, written the way `taller project brief` writes them."""
    check_token()
    given = {key: value for key, value in request.form.items()
             if key in project_settings.EDITABLE}
    try:
        done = project_settings.change_answers(project, given)
    except TallerError as exc:
        done = {"ok": False, "problem": plain.problem(exc), "lines": []}
    for line in (done["lines"] if done["ok"] else [done["problem"]]):
        flash(line, "info" if done["ok"] else "warning")
    return redirect(url_for("cockpit.settings_about", project=project))


@bp.get("/project/<project>/rules")
def settings_rules(project: str):
    try:
        page = project_settings.rules(project)
    except TallerError as exc:
        abort(404, str(exc))
    return render_template("plain/settings/rules.html", page=page, current_tab="rules")


@bp.post("/project/<project>/rules/add")
def settings_rules_add(project: str):
    check_token()
    try:
        for line in project_settings.add_rule(project, request.form.get("kind", ""),
                                              request.form.get("text", ""),
                                              request.form.get("why", "")):
            flash(line, "info")
    except TallerError as exc:
        flash(plain.problem(exc), "warning")
    return redirect(url_for("cockpit.settings_rules", project=project))


@bp.post("/project/<project>/rules/remove")
def settings_rules_remove(project: str):
    check_token()
    try:
        index = int(request.form.get("index", "-1"))
        for line in project_settings.remove_rule(project, request.form.get("kind", ""), index,
                                                 request.form.get("why", "")):
            flash(line, "info")
    except ValueError:
        flash("That rule could not be found; the page may be out of date.", "warning")
    except TallerError as exc:
        flash(plain.problem(exc), "warning")
    return redirect(url_for("cockpit.settings_rules", project=project))


@bp.get("/usage")
def usage_page():
    return render_template("plain/usage.html", page=usage.usage())


@bp.post("/usage/strongest")
def usage_strongest():
    check_token()
    try:
        for line in usage.choose_strongest(request.form.get("job", ""),
                                           request.form.get("on") == "1"):
            flash(line, "info")
    except TallerError as exc:
        flash(plain.problem(exc), "warning")
    return redirect(url_for("cockpit.usage_page"))


@bp.post("/usage/leave-out")
def usage_leave_out():
    check_token()
    try:
        for line in usage.leave_out(request.form.get("on") == "1"):
            flash(line, "info")
    except TallerError as exc:
        flash(plain.problem(exc), "warning")
    return redirect(url_for("cockpit.usage_page"))


@bp.get("/services")
def services_page():
    return render_template("plain/services.html",
                           page=services.page(request.args.get("project") or None))


@bp.get("/services/search")
def services_search():
    from taller import connections

    query = request.args.get("q", "")
    found = connections.search(query)
    if found["problem"]:
        found["problem"] = words.SERVICES["search_failed"]
    return render_template("plain/services.html",
                           page=services.page(request.args.get("project") or None,
                                              search=found, query=query))


@bp.post("/services/level")
def services_level():
    """One service's level for one project; the first time, Taller learns what
    the service can do - one small request, said on the page beforehand."""
    from taller import connections

    check_token()
    project = request.form.get("project", "")
    try:
        path = Path(reading.entry_for(project)["path"])
        connections.allow(path, request.form.get("service", ""), request.form.get("level", ""))
        flash(words.SERVICES["saved"], "info")
    except TallerError as exc:
        flash(plain.problem(exc), "warning")
    return redirect(url_for("cockpit.services_page", project=project))


@bp.post("/services/notify")
def services_notify():
    from taller import notify

    check_token()
    try:
        notify.choose(request.form.get("channel") or None, request.form.getlist("when"))
        flash(words.SERVICES["saved"], "info")
    except TallerError as exc:
        flash(plain.problem(exc), "warning")
    return redirect(url_for("cockpit.services_page"))


@bp.post("/services/add")
def services_add():
    """Adding asks first: a page naming the maker. Only the second press adds -
    and what is added is read again from the catalogue, never from the form."""
    from taller import connections

    check_token()
    name = request.form.get("name", "")
    if request.form.get("confirmed") != "1":
        entry = connections.entry_named(name)
        if entry is None:
            flash(words.SERVICES["search_failed"], "warning")
            return redirect(url_for("cockpit.services_page"))
        return render_template("plain/services_confirm.html", entry=entry)
    try:
        for line in connections.add(name):
            flash(line, "info")
    except TallerError as exc:
        flash(plain.problem(exc), "warning")
    return redirect(url_for("cockpit.services_page"))


@bp.get("/project/<project>/choices")
def settings_choices(project: str):
    try:
        page = project_settings.choices(project)
    except TallerError as exc:
        abort(404, str(exc))
    return render_template("plain/settings/choices.html", page=page, current_tab="choices")


@bp.post("/project/<project>/choices")
def settings_choices_change(project: str):
    """One option, written to the project's own settings the way the terminal does."""
    check_token()
    try:
        for line in project_settings.choose(project, request.form.get("choice", ""),
                                            request.form.get("option", "")):
            flash(line, "info")
    except TallerError as exc:
        flash(plain.problem(exc), "warning")
    return redirect(url_for("cockpit.settings_choices", project=project))


@bp.get("/project/<project>/look")
def settings_look(project: str):
    try:
        page = project_settings.look(project)
    except TallerError as exc:
        abort(404, str(exc))
    return render_template("plain/settings/look.html", page=page, current_tab="look")


@bp.post("/project/<project>/look/guide")
def settings_look_guide(project: str):
    """A brand guide, read into a proposal. The size is checked before anything is read."""
    check_token()
    if (request.content_length or 0) > project_settings.UPLOAD_MAX:
        flash(words.LOOK["too_big"], "warning")
        return redirect(url_for("cockpit.settings_look", project=project))
    upload = request.files.get("guide")
    if upload is None or not upload.filename:
        return redirect(url_for("cockpit.settings_look", project=project))
    if Path(upload.filename).suffix.lower() not in project_settings.UPLOAD_KINDS:
        flash(words.LOOK["not_a_guide"], "warning")
        return redirect(url_for("cockpit.settings_look", project=project))
    kept = project_settings.keep_upload(upload, upload.filename)
    proposal = project_settings.propose_from(kept, upload.filename)
    if proposal["problem"]:
        flash(proposal["problem"], "warning")
        return redirect(url_for("cockpit.settings_look", project=project))
    try:
        page = project_settings.look(project)
    except TallerError as exc:
        abort(404, str(exc))
    page["proposal"] = proposal
    return render_template("plain/settings/look.html", page=page, current_tab="look")


@bp.post("/project/<project>/look/save")
def settings_look_save(project: str):
    check_token()
    tokens = {key[2:]: value for key, value in request.form.items() if key.startswith("t:")}
    try:
        for line in project_settings.save_brand(request.form.get("slug", ""), tokens,
                                                request.form.get("prose", ""),
                                                new=bool(request.form.get("new")),
                                                name=request.form.get("name", "")):
            flash(line, "info")
    except TallerError as exc:
        flash(plain.problem(exc), "warning")
    return redirect(url_for("cockpit.settings_look", project=project))


@bp.post("/project/<project>/look/use")
def settings_look_use(project: str):
    """Putting a brand on a project is work: it becomes a thing, and starts."""
    check_token()
    try:
        made = project_settings.use_brand(project, request.form.get("slug", ""))
    except TallerError as exc:
        flash(plain.problem(exc), "warning")
        return redirect(url_for("cockpit.settings_look", project=project))
    flash(words.LOOK["asked"], "info")
    return redirect(url_for("cockpit.thing", project=project, ticket_id=made))


@bp.get("/ask")
def ask_page():
    return _ask_form(chosen=request.args.get("project") or "")


@bp.post("/ask")
def ask():
    """Her words become a ticket, and the work starts by itself.

    No kind, no lane, no title to invent: her first line stands in as the title
    until the chief names it at ① - which it does for any ticket nobody has named.
    """
    check_token()
    name = request.form.get("project") or ""
    said = request.form.get("words") or ""
    if not said.strip():
        return _ask_form(chosen=name, words=said, problem=words.ASK["empty"])
    known = {entry["name"]: entry for entry in reading.project_entries() if entry["available"]}
    if name not in known:
        return _ask_form(chosen=name, words=said, problem=words.ASK["no_project"])
    path = Path(known[name]["path"])
    first = said.strip().splitlines()[0]
    title = " ".join(first.split())[:tickets.TITLE_MAX].rstrip()
    try:
        made = tickets.create(path, title=title, words=said.strip(), kind="feature",
                              named_by=None)
        runs.start(path, name, int(made["id"]))
    except TallerError as exc:
        return _ask_form(chosen=name, words=said, problem=plain.problem(exc))
    return redirect(url_for("cockpit.thing", project=name, ticket_id=int(made["id"])))


def _ask_form(*, chosen: str, words: str = "", problem: str = "") -> Any:
    projects = [entry["name"] for entry in reading.project_entries() if entry["available"]]
    if chosen not in projects:
        chosen = projects[0] if projects else ""
    return render_template("plain/ask.html", projects=projects, chosen=chosen, words=words,
                           problem=problem)


@bp.get("/thing/<project>/<int:ticket_id>")
def thing(project: str, ticket_id: int):
    """One thing she asked for, in plain words."""
    try:
        page = plain.thing(project, ticket_id)
    except TallerError as exc:
        abort(404, str(exc))
    return render_template("plain/thing.html", page=page)


@bp.get("/thing/<project>/<int:ticket_id>/plan")
def thing_plan(project: str, ticket_id: int):
    try:
        page = plain.plan_of(project, ticket_id)
    except TallerError as exc:
        abort(404, str(exc))
    return render_template("plain/plan.html", page=page)


@bp.post("/thing/<project>/<int:ticket_id>/yes")
def thing_yes(project: str, ticket_id: int):
    """"Yes, carry on": the approval, and the work starts again by itself."""
    def act(path: Path, name: str) -> None:
        tickets.approve(path, ticket_id)
        runs.start(path, name, ticket_id)

    return _write(project, ticket_id, act, back="cockpit.thing")


@bp.post("/thing/<project>/<int:ticket_id>/no")
def thing_no(project: str, ticket_id: int):
    """"No, change it": her words are what the next attempt reads."""
    reason = request.form.get("reason", "")

    def act(path: Path, name: str) -> None:
        stage = tickets.load(path, ticket_id)["stage"]
        tickets.reject(path, ticket_id, reason)
        # A new plan, or a new attempt, starts at once with her words. Later
        # checkpoints stay stopped: what to change there is not the work's to guess.
        if stage == "design":
            tickets.resume(path, ticket_id)
        if stage in ("design", "review"):
            runs.start(path, name, ticket_id)

    return _write(project, ticket_id, act, back="cockpit.thing")


@bp.post("/thing/<project>/<int:ticket_id>/try-again")
def thing_try_again(project: str, ticket_id: int):
    """After a stop: pick it up again, and let it carry on by itself."""
    def act(path: Path, name: str) -> None:
        tickets.resume(path, ticket_id)
        runs.start(path, name, ticket_id)

    return _write(project, ticket_id, act, back="cockpit.thing")


@bp.get("/board")
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
        # Chosen here and used here: a redirect would ask the registry twice.
        available = [entry["name"] for entry in reading.project_entries()
                     if entry["available"]]
        if not available:
            return render_template("problem.html", heading="No projects yet",
                                   detail="`taller project new` starts one, and its rules "
                                          "appear here."), 404
        wanted = available[0]
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
    except (RuntimeError, OSError) as exc:
        # `scan.health` runs the gates, and a gate that cannot read the project
        # raises git's own words rather than one of ours.
        flash(f"{project} could not be checked: {exc}", "warning")
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


def _write(project: str, ticket_id: int, act: Callable[[Path, str], None], *,
           back: str = "cockpit.ticket") -> Any:
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
    except TallerError as exc:
        flash(plain.problem(exc), "warning")
    return redirect(url_for(back, project=project, ticket_id=ticket_id))
