"""One thing every test file needs, said once instead of twenty times.

The lookup door in this package keeps a gap between the questions it sends, because the
public lookup server asks applications for at most one request a second. No test here
sends a question anywhere: they answer at the door itself, one level below it. So the gap
would be a suite that waits twenty seconds for nothing, and it is switched off for the
run. The rule itself is not forgotten: one test shortens it on purpose and watches the
waiting happen, and another pins the length the server asks for.
"""
from __future__ import annotations

import pytest

from muezzin import geocode


@pytest.fixture(autouse=True)
def no_waiting_for_questions_that_are_answered_locally(monkeypatch):
    """The gap only matters when a real second is at stake, which in tests it never is."""
    monkeypatch.setattr(geocode, "ASK_SPACING", 0.0)
