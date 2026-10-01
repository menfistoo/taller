"""Every word the plain front shows, and nothing else.

The owner is not an engineer, and the first cockpit spoke the machine's language
- stage numerals, lanes, gates, rule ids, severities. This file is where the
plain front's language lives instead, so it can be read, and changed, in one
place. `cockpit/plain.py` is the only thing that chooses among these words.

A test holds every sentence here to one rule: none of them may name the machine.
"""

from __future__ import annotations

# The four states a thing she asked for can be in. Twelve stages exist underneath,
# because the work needs them; she never has to know which one it is at.
STATES = {
    "working": "Working on it",
    "needs_you": "Needs you",
    "stopped": "Stopped",
    "done": "Done",
}

# What it is doing now, one sentence per stage.
DOING = {
    "intake": "Just asked for",
    "triage": "Looking at your project to see what this touches",
    "design": "Writing a plan for you to read",
    "build": "Making the change",
    "gates": "Checking its own work",
    "smoke": "Starting your app to see that it still runs",
    "review": "Writing up what it did for you",
    "pr": "Getting it ready to publish",
    "staging": "Ready for you to try",
    "merge": "Putting it into your project",
    "release": "Ready to finish",
    "close": "Finished",
}

# When the pause is hers rather than the work's, it says what she is waiting on.
WAITING = {
    "design": "A plan is ready for you to read",
    "review": "Ready for you to look at",
    "staging": "Ready for you to try",
    "release": "Ready to finish",
}
READY_TO_PUBLISH = "Finished, and waiting for you to publish it"
WAITING_FOR_GITHUB = "Published, and waiting to be merged on GitHub"
FINISHED_HERE = "Finished here"

# The library's refusals that reach a page, said for her: what happened, and that
# nothing was changed. Anything else it refuses is already written as a sentence.
BUSY = ("Taller is busy with this project for a moment, so nothing was done. "
        "Try again in a minute.")
HAND_CHANGES = ("Someone has changed this project's files by hand and not saved them yet, "
                "so Taller left it alone and nothing was changed. Try again once they "
                "have finished.")
NOT_ON_MAIN = ("Someone is working on this project's files by hand right now, so Taller "
               "left it alone and nothing was changed. Try again once they have finished.")

# A finding whose rule has no sentence of its own - most of what the model-run
# checks report - is said by the check that found it. Its own words, written for
# an engineer, stay on the detailed view.
CHECK_FOUND = {
    "security": "Its safety check found something worth a look before you say yes",
    "quality": "Its quality check found something worth a look",
    "ux": "Its check of how the screens look and read found something worth a look",
    "error": "One of its checks could not run, so that part was not checked",
    "other": "Its checks noticed something worth a look",
}
BUDGET_STOPPED = ("It stopped because it used everything one piece of work may use. To "
                  "let it use more, choose “A lot” under Choices for this "
                  "project, then press Try again.")

# Each thing its own checks can find, as a sentence about the finding. One for
# every rule id a check can report; a rule added later without a sentence shows
# its own message instead (never its id).
FINDINGS = {
    "brand.hardcoded-color":
        "A colour was written straight into the page instead of using your brand's",
    "brand.hardcoded-font":
        "A typeface was written straight into the page instead of using your brand's",
    "constitution.commit-message-shape":
        "One of its saved notes is not written the way your project writes them",
    "constitution.layer-violation":
        "One part of the program reaches into another part it should not touch",
    "constitution.new-ui-literal":
        "Some wording was typed into the page instead of kept where your wording lives",
    "constitution.override-expired":
        "A rule you set aside for a while has run out, so it applies again",
    "constitution.override-not-permitted":
        "Something tried to set aside a rule that can never be set aside",
    "constitution.override-without-reason":
        "A rule was set aside with no reason written down",
    "constitution.resolved-snapshot-modified":
        "The copy of your rules inside this project was edited by hand",
    "constitution.resolved-snapshot-stale":
        "Your rules changed, and this project has not caught up yet",
    "constitution.root-markdown":
        "A new notes file was left at the top of your project",
    "constitution.single-use-script":
        "A one-off script was left behind in your project",
    "constitution.unknown-rule-id":
        "Your rules mention a check that does not exist",
    "size.duplicate-block":
        "The same lines appear in more than one place",
    "size.file-too-long":
        "One file is getting long",
    "size.function-too-long":
        "One piece of the program is getting long",
    "smoke.boot-failed":
        "Your app did not start",
    "smoke.not-rendered":
        "A page came up empty",
    "smoke.route-error":
        "A page returned an error",
    "smoke.timeout":
        "Your app took too long to start",
    "smoke.unmapped-template":
        "There is a page that nothing links to",
    "tests.coverage-below-minimum":
        "Less of your project is covered by tests than you asked for",
    "tests.error":
        "The tests could not run",
    "tests.failed":
        "Some tests did not pass",
}

# Findings, sorted into two groups. Which severity goes where is decided in
# `plain.split`; the words for the severities themselves appear nowhere.
GROUPS = {
    "look": "Worth a look before you say yes",
    "small": "Small things",
    # When it has stopped there is no yes to say: the same findings, said plainly.
    "look_stopped": "What its checks found",
}

# --- the front page ------------------------------------------------------------

HOME = {
    "title": "My projects",
    "needs_you": "Needs you",
    "everything": "Everything",
    "ask": "Ask for something",
    "nothing_yet": "Nothing asked for yet.",
    "quiet": "nothing yet",
    "cant_find": "Taller can't find this project's folder right now.",
    "no_projects": "No projects yet.",
    "detail": "The detailed view",
}


def counted(state: str, number: int) -> str:
    """`2 need you`, `1 needs you`, `3 working`, `1 stopped`, `4 done`."""
    if state == "needs_you":
        return f"{number} {'needs' if number == 1 else 'need'} you"
    return f"{number} {state.replace('_', ' ')}"


def more_done(number: int) -> str:
    return f"and {number} more done"

# --- one thing ------------------------------------------------------------------

THING = {
    "back": "My projects",
    "asked": "You asked for",
    "did": "What it did",
    "plan": "Show me the plan it followed",
    "yes": "Yes, carry on",
    "no": "No, change it",
    "no_label": "What should be different?",
    "no_send": "Send it back",
    "try_again": "Try again",
    "interrupted": "Nothing is working on this right now: it was interrupted partway. "
                   "Nothing is lost - press Try again and it carries on from where it was.",
    "merge_on_github": "Published. It is waiting to be merged on GitHub; once it is, "
                       "it carries on here by itself.",
    "open_on_github": "Open it on GitHub",
    "only_here": "It's finished. This project is only on this computer, so there is "
                 "nowhere to publish it: putting it into the project is done by hand "
                 "for now.",
    "working_note": "This page follows along by itself; nothing needs you yet.",
    "publish_note": "It's finished here. Publishing sends it — and everything else "
                    "waiting — to GitHub.",
    "plan_title": "The plan it followed",
    "its_plan": "Its plan",
    "full_plan": "Show me the full plan",
    "builder_plan": "The full plan, as written for the builder",
    "plan_intro": "Read it, then say yes to let it start - or say what should be different.",
    "no_plan": "There is no plan for this one: it was small enough to go straight to "
               "the change.",
}


def files_changed(number: int) -> str:
    return f"{number} file{'s' if number != 1 else ''} changed"


def more_files(number: int) -> str:
    return f"and {number} more"

# --- asking for something -------------------------------------------------------

ASK = {
    "title": "What do you want?",
    "for": "For which project",
    "placeholder": "Say it however you like. For example: the loans list doesn't match "
                   "what's on the shelves.",
    "hint": "It starts working as soon as you ask, and tells you when it needs you. "
            "Nothing leaves this computer until you publish it.",
    "button": "Ask for it",
    "empty": "Say what you want first - a sentence is enough.",
    "no_project": "Choose which project this is for.",
    "no_projects": "There are no projects yet, so there is nothing to ask for yet.",
    "new_project": "Start a project",
}

# --- publishing -----------------------------------------------------------------

PUBLISH = {
    "button": "Publish",
    "alone": "This project is only on this computer.",
    "done": "Published. Everything that was waiting has left this computer.",
    "nothing": "Nothing was waiting to publish.",
}


def waiting_line(things: int) -> str:
    """How many things of hers have not left this computer yet."""
    if things == 0:
        return "Some changes have not left this computer yet."
    return f"{things} thing{'s have' if things != 1 else ' has'} not left this computer yet."

# --- a project's settings -------------------------------------------------------

TABS = (("about", "About it"), ("rules", "Its rules"), ("look", "Look and feel"),
        ("choices", "Choices"))

ABOUT = {
    "intro": "What you told Taller when you started. Everything it does is checked "
             "against this, so keep it true.",
    "cards": {
        "what": "What it does",
        "disaster": "What would be a disaster if it broke",
        "never": "What it should never turn into",
        "keeps": "What it keeps",
        "who": "Who uses it, and where",
    },
    "sensitive": "Money or personal details: yes - every change touching them is "
                 "checked twice.",
    "change": "Change",
    "save": "Save",
    "yes": "yes",
    "no": "no",
    "changed": "Changed. Everything Taller does is now checked against it.",
    "unchanged": "Nothing changed.",
}

_WHO = {"solo": "Only you", "team": "A group of people", "public": "Anyone"}
_WHERE = {"this machine": "on this computer", "a private network": "on a private network",
          "a VPN": "through a private connection", "the internet": "from anywhere, over "
                                                                   "the internet"}


def who_uses(users: object, reach: object, phone: object) -> str:
    """`Only you, on this computer. Not on a phone.`"""
    who = _WHO.get(str(users), str(users or ""))
    where = _WHERE.get(str(reach), str(reach or ""))
    return f"{who}, {where}. " + ("On a phone too." if phone else "Not on a phone.")

RULES = {
    "intro": "Your rules, in your words. Taller checks every change against them and "
             "tells you when one is broken.",
    "always": "It must always",
    "never": "It must never",
    "add_always": "Add something it must always do",
    "add_never": "Add something it must never do",
    "why": "Why? (you can leave this empty)",
    "add": "Add",
    "remove": "Remove",
    "remove_why": "Why take it away?",
    "remove_send": "Take it away",
    "none_always": "Nothing yet.",
    "none_never": "Nothing yet.",
    "from_about": "From About it, where you can change it.",
    "exceptions": "Exceptions you've allowed",
    "taller": "Rules that come with Taller",
    "taller_note": "Good practice for every project. You don't need to look after these.",
    "added": "added",
    "saved": "Saved. Taller checks every change against it from now on.",
}

# One plain line for each rule file Taller ships (its "modules"). A file without
# a line here shows the one-line summary it opens with - never its name.
PRACTICE = {
    "never": "Never save a password or key in the project, and never make a check easier "
             "just so it passes",
    "security/minimal": "Keep anything secret out of the project and out of its records",
    "security/web-app": "Every page that changes something checks who is asking, and "
                        "whether they may",
    "conventions/python": "The program is written the same way throughout, so any part can "
                          "be read",
    "conventions/js": "The code that runs in the browser is written the same way throughout",
    "stack/flask-sqlite": "It is built as a web app with its own small database",
    "stack/python-packaged": "It is built as a program you install and run",
    "stack/static-site": "It is built as a simple website of pages",
    "ux/bootstrap": "Every screen uses your brand's colours and fonts, never ones typed in, "
                    "and works without a mouse",
}

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")


def on_day(day: object) -> str:
    """`2026-12-31` -> `31 December 2026`."""
    text = str(day)[:10]
    try:
        year, month, dom = (int(part) for part in text.split("-"))
    except ValueError:
        return text
    return f"{dom} {_MONTHS[month - 1]} {year}"


def until_line(day: object, ran_out: bool) -> str:
    if ran_out:
        return f"It ran out on {on_day(day)}, so the rule applies again."
    return f"Until {on_day(day)} - then the rule applies again."

LOOK = {
    "intro": "The colours, typefaces and tone every screen of this project uses.",
    "none": "This project doesn't use a brand yet.",
    "in_words": "In words",
    "change": "Change a colour or typeface",
    "save": "Save",
    "shared": "This brand is also used by {others}. Changing it changes {them}.",
    "use_title": "Use a brand",
    "use_note": "Putting a brand on a project changes the project's own screens, so it "
                "is asked for as work: Taller does it, checks it, and asks you before it "
                "is kept.",
    "use": "Ask Taller to use {brand}",
    "guide_title": "Starting a new brand?",
    "guide": "Choose your brand guide - a PDF, a logo, a screenshot, or a stylesheet. "
             "Taller suggests the colours and typefaces, and you check them.",
    "guide_button": "Read it",
    "proposal": "Taller read your guide. Check the colours and typefaces, give the brand "
                "a name, and save it. Nothing is kept until you do.",
    "name": "What should the brand be called?",
    "prose_label": "In one line: what should it feel like, and what is each colour for?",
    "not_a_guide": "Taller can read a PDF, a picture (PNG or JPG) or a stylesheet. This "
                   "file is none of those, so nothing was read.",
    "too_big": "That file is too big to read - up to 20 MB, please. Nothing was read.",
    "nothing_found": "Taller could not find any colours or typefaces in that file. Nothing "
                     "was kept; try another page of the guide, or a picture of the logo.",
    "saved": "Saved. Every project using it now follows it.",
    "made": "The brand is made. Use it on a project from here whenever you like.",
    "asked": "Asked for. Taller is putting the brand on the project now.",
}

COLOUR_LABELS = {"--color-primary": "Main", "--color-accent": "Accent",
                 "--color-background": "Background", "--color-text": "Text"}
FONT_LABELS = {"--font-heading": "Headings", "--font-body": "Everything else"}

CHOICES = {
    "intro": "The few things worth choosing. Each one is for this project only.",
    "own": "Your own setting",
    "own_note": "Set some other way, so none of these is lit. Choose one to go back to it.",
    "saved": "Saved. It applies from the next piece of work.",
    "unknown": "That is not one of the choices; the page may be out of date.",
    "everything_else": "Everything else, for when something goes wrong",
    "items": {
        "publish": ("Publish on its own",
                    "Off: nothing leaves this computer until you press Publish. On: "
                    "finished work is sent to GitHub as soon as it is done."),
        "budget": ("How much one piece of work may use",
                   "Of your Claude plan. It tells you when it gets close, and stops at the "
                   "limit to ask you."),
        "tries": ("Tries before it asks you",
                  "When its own checks find a problem, how many times it fixes it itself "
                  "first."),
        "language": ("Language of the project's screens",
                     "The language people see on the screens it builds for this project."),
    },
    "options": {
        "publish": {"off": "Off", "on": "On"},
        "budget": {"little": "Little", "normal": "Normal", "a_lot": "A lot"},
        "tries": {"1": "Once", "2": "Twice", "3": "Three times"},
        "language": {"es": "Español", "en": "English"},
    },
}
