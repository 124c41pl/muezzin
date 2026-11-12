"""Command-line behaviour: a table a person can read, and a mistake they can act
on rather than a stack trace."""
from __future__ import annotations

import pytest

from muezzin.cli import _fmt, main


def test_a_time_that_rounds_up_carries_its_day_marker():
    """Times are deliberately not wrapped into one day, and the table marks that
    with +1. 23.9999 rounds to a whole hour, so it lands in tomorrow - and the
    marker has to follow the clock over, or the row says today at midnight."""
    assert _fmt(None) == "  --  "
    assert _fmt(5.0) == "05:00"
    assert _fmt(5.9999) == "06:00"
    assert _fmt(23.9999) == "00:00+1"
    assert _fmt(24.9999) == "01:00+1"
    assert _fmt(-0.0001) == "00:00-1"


def test_a_profile_that_is_not_readable_yaml_says_so(tmp_path, capsys):
    path = tmp_path / "muezzin.yaml"
    path.write_text("location: {latitude: 40.7, longitude: -74.0\n", encoding="utf-8")
    assert main(["times", "-c", str(path)]) == 2
    err = capsys.readouterr().err
    assert "not readable YAML" in err
    assert "Traceback" not in err, "a half-written file should not print a stack trace"


def test_a_config_option_pointed_at_a_directory_says_so(tmp_path, capsys):
    assert main(["times", "-c", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert err.strip() and "Traceback" not in err, "the user needs a sentence, not a trace"


def test_a_missing_profile_tells_the_user_to_start_one(tmp_path, capsys):
    assert main(["times", "-c", str(tmp_path / "nope.yaml")]) == 2
    assert "muezzin init" in capsys.readouterr().err
