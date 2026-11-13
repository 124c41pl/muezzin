"""What the published documents are allowed to contain about the author.

The reporting route for this project is GitHub, so every address in it should be
a URL on github.com. A personal inbox is easy to write back into a "report a
problem" section by reflex, and once a document is published the address is
effectively public forever: it is the one part of a release that cannot be
un-published by deleting a file.

The second guard is about other people's products: these files describe what this
program does, so the name of another product should not appear anywhere in the
published tree - not in a document, and not in a comment either.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Written by hand for a person to read, as opposed to code that a machine runs.
DOCS = [
    "README.md", "SECURITY.md", "THIRD-PARTY.md", "LICENSE",
    "docs/HOW-IT-WORKS.md", "config/README.md", "media/README.md",
    "pyproject.toml", "Dockerfile", "docker-compose.yml",
]

# Free mailboxes, i.e. the ones a maintainer does not want printed here. A URL on
# github.com is fine on purpose: that is where the reporting route points.
PERSONAL_MAIL = ("gmail.com", "googlemail.com", "outlook.com", "hotmail.com",
                 "yahoo.com", "proton.me", "protonmail.com", "icloud.com")


def test_no_document_prints_a_personal_mailbox():
    hits = []
    for name in DOCS:
        text = (REPO / name).read_text(encoding="utf-8")
        for domain in PERSONAL_MAIL:
            if domain in text.lower():
                hits.append(f"{name}: {domain}")
    assert not hits, "a personal address in a published document: " + ", ".join(hits)


def test_the_security_document_points_at_github():
    """A reporting route that goes through someone's inbox is a route that stops
    working the day the inbox changes. The private advisory form is the one that
    keeps a vulnerability off the public issue list without needing a person."""
    text = (REPO / "SECURITY.md").read_text(encoding="utf-8")
    assert "security/advisories/new" in text, "no private reporting route"
    assert "124c41pl/muezzin/issues" in text, "no route for ordinary bugs"


# Built from pieces so this file does not match its own pattern. Matching is over
# the whole file, not one line at a time: the mention that survived an earlier
# version of this test was the name split by a line break in a docstring, `Smart`
# at the end of one line and the rest at the start of the next.
OTHER_PRODUCT = re.compile("(?is)" + "smart" + ".?" + "azan")

# Text files are the ones that get read. Private working notes, unpacked
# installers and the developer's own configs are not published here, and are not
# this test's business.
SKIP_TOP = {"out", "notes", "tools", "extracted", "extracted2", "issdir",
            "media", "__pycache__"}
TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".toml", ".txt", ".cfg", ".ini",
                 ".html", ".in"}


def test_no_published_file_names_another_vendor():
    """muezzin describes what it does; it does not describe anyone else's product,
    and it does not name it in order to say so. The claim "these times are
    computed from your coordinates and your angles" stands on its own, and a
    document that leans on a competitor's name reads like advertising and goes
    stale the day that product changes.

    That includes the code: a device is driven because it advertises muezzin's own
    protocol, so there is no place in the program that needs another product's
    service type either.
    """
    hits = []
    for path in sorted(REPO.rglob("*")):
        rel = path.relative_to(REPO)
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if rel.parts[0] in SKIP_TOP or any(
                part.startswith(".") and part != ".github" for part in rel.parts):
            # .github is the one hidden directory that is published, so it is read
            # like the rest; the others are this machine's working files.
            continue
        if len(rel.parts) == 1 and path.suffix.lower() == ".yaml":
            continue          # the developer's own untracked profile
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in OTHER_PRODUCT.finditer(text):
            n = text.count("\n", 0, m.start()) + 1
            hits.append(f"{rel.as_posix()}:{n}: {m.group(0)!r}")
    assert not hits, "published files name another product:\n" + "\n".join(hits[:10])


def test_the_vendor_guard_catches_a_name_split_across_a_line():
    """That is exactly the spelling that got past the line-by-line version of this
    test, so the test that proves the guard is whole-file lives here."""
    split = "the Smart" + chr(10) + "Azan flow"
    assert OTHER_PRODUCT.search(split), "the split spelling slipped through"
    assert not OTHER_PRODUCT.search("an adhan, said well")
