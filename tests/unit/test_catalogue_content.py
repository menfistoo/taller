"""The catalogue is data, so its correctness is asserted rather than reviewed.

Spec 4.0 makes the catalogue inert but not arbitrary. Three properties are load
bearing and none of them is visible by reading one file: `render_index` (spec 3.1)
collects the `> ` first line of every module verbatim, goal G9 forbids the shipped
stock from naming anyone's line of business, and spec 4.6 compares generated
artefacts byte for byte, which only holds if what was copied was LF and UTF-8 to
begin with.

Every check is parametrised over the files actually on disk, so a tenth module or
a fourth profile reports under its own name instead of hiding inside a loop.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from taller import paths

MODULES_DIR = paths.catalogue() / "modules"
PROFILES_DIR = paths.catalogue() / "profiles"

# Spec 4.0's shipped stock. The three profiles between them name all nine.
EXPECTED_MODULES = {
    "stack/flask-sqlite",
    "stack/static-site",
    "stack/python-packaged",
    "security/web-app",
    "security/minimal",
    "conventions/python",
    "conventions/js",
    "ux/bootstrap",
    "never",
}

EXPECTED_PROFILES = {"flask-sqlite", "static-site", "python-packaged"}

# Spec 4.3. The list is closed; a directory outside it is a vocabulary error.
SLICES = {
    "product",
    "architecture",
    "stack",
    "conventions",
    "security",
    "ux",
    "brand",
    "never",
    "overrides",
}

# Spec 15.6's domain vocabulary, as far as the catalogue can be checked against it
# on its own: lines of business a generic tool must not assume it is working for.
# Matched on word boundaries, because a substring match would flag "spacing" for
# "spa" and "navbar" for "bar" and teach the next author to disable the test.
DOMAIN_VOCABULARY = (
    "hotel", "hostel", "resort", "restaurant", "cafeteria", "beach", "club",
    "spa", "sunbed", "lounger", "booking", "bookings", "reservation",
    "reservations", "guest", "guests", "voucher", "vouchers", "tourist",
    "concierge", "reception", "clinic", "patient", "pharmacy", "dentist",
    "gym", "salon", "boutique", "winery", "vineyard", "dealership",
    "realtor", "landlord", "invoice", "invoices", "payroll",
)

# Keys spec 4.1 shows and that resolve() plus the smoke gate read.
REQUIRED_PATH_KEYS = {"security_sensitive", "ui", "layers", "tests_dir", "brand_tokens"}
SMOKE_KINDS = {"http", "import", "none"}


def module_files() -> list[Path]:
    return sorted(MODULES_DIR.rglob("*.md"))


def module_id(path: Path) -> str:
    return path.relative_to(MODULES_DIR).with_suffix("").as_posix()


def profile_files() -> list[Path]:
    return sorted(PROFILES_DIR.glob("*.yml"))


def slice_of(path: Path) -> str:
    """The slice a module provides: its directory, or its own name at the root.

    `never.md` sits at the root of `modules/` because it is the one slice with a
    single file (spec 4.0's tree), so the slice name has to come from somewhere.
    """
    relative = path.relative_to(MODULES_DIR)
    return relative.parts[0] if len(relative.parts) > 1 else relative.stem


# --- invariant 1 -------------------------------------------------------------

def test_the_catalogue_ships_exactly_nine_modules():
    """The three profiles between them name all nine (spec 4.0). A module no
    profile names is dead stock; a name no module answers breaks install."""
    assert {module_id(path) for path in module_files()} == EXPECTED_MODULES


# --- invariant 2 -------------------------------------------------------------

@pytest.mark.parametrize("path", module_files(), ids=module_id)
def test_every_module_opens_with_a_one_sentence_summary(path: Path):
    """`render_index` collects this line verbatim into a 40-line index (spec 3.1).
    A module without one leaves a hole in the routing map the chief reads."""
    first = path.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("> "), f"{path.name} does not open with a '> ' summary"
    assert len(first) <= 100, f"summary is {len(first)} chars, over the 100 budget"
    summary = first[2:].strip()
    assert summary.endswith("."), "the summary is a sentence and ends in a full stop"
    assert ". " not in summary, "the summary is ONE sentence"


# --- invariant 3 -------------------------------------------------------------

@pytest.mark.parametrize("path", module_files(), ids=module_id)
def test_no_catalogue_file_names_a_domain_a_brand_or_a_person(path: Path):
    """Goal G9. The catalogue is inside the package, so spec 15.6's vocabulary
    rule covers it: the tool must ship knowing nothing about whoever installs it.

    Non-ASCII text is the machine-checkable half of "no language but the
    plugin's own English" — an accented word is prose someone's UI leaked in.
    """
    text = path.read_text(encoding="utf-8")
    found = sorted(
        {
            word
            for word in DOMAIN_VOCABULARY
            if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE)
        }
    )
    assert found == [], f"{path.name} names a line of business: {found}"
    non_ascii = sorted({char for char in text if ord(char) > 127})
    assert non_ascii == [], f"{path.name} holds non-ASCII characters: {non_ascii}"


# --- invariant 4 -------------------------------------------------------------

@pytest.mark.parametrize("path", module_files(), ids=module_id)
def test_every_catalogue_file_is_utf8_with_lf_endings(path: Path):
    """Spec 4.6 compares generated artefacts byte for byte. A CRLF module copied
    into a hub would make the same content hash differently per platform."""
    raw = path.read_bytes()
    assert b"\r\n" not in raw, f"{path.name} has CRLF endings"
    raw.decode("utf-8")  # raises UnicodeDecodeError if it is not UTF-8


# --- invariant 5 -------------------------------------------------------------

@pytest.mark.parametrize("path", module_files(), ids=module_id)
def test_every_module_sits_in_a_slice_of_the_closed_vocabulary(path: Path):
    """Spec 4.3's list is closed. Chain 2 keys resolved text by slice name, so a
    module filed under an unknown one would resolve into nothing."""
    assert slice_of(path) in SLICES
