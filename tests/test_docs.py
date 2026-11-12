"""What the published documents are allowed to contain about the author.

The reporting route for this project is GitHub, so every address in it should be
a URL on github.com. A personal inbox is easy to write back into a "report a
problem" section by reflex, and once a document is published the address is
effectively public forever: it is the one part of a release that cannot be
un-published by deleting a file.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Written by hand for a person to read, as opposed to code that a machine runs.
DOCS = [
    "README.md", "SECURITY.md", "THIRD-PARTY.md", "FINDINGS.md", "LICENSE",
    "config/README.md", "media/README.md", "pyproject.toml", "Dockerfile",
    "docker-compose.yml",
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
