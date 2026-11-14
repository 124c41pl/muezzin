"""Command-line behaviour: a table a person can read, and a mistake they can act
on rather than a stack trace."""
from __future__ import annotations

import pytest

from muezzin.cli import STARTER, _fmt, main, starter_warnings
from muezzin.config import load_profile


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


def test_the_starter_names_no_speaker_the_reader_does_not_own(tmp_path, capsys):
    """The example profile shows four kinds of output because it is
    documentation. The file handed to a new user must name none of them: an
    output pointed at somebody else's speaker fails at every prayer, and the
    person who installed us five minutes ago has not seen a device list yet."""
    path = tmp_path / "muezzin.yaml"
    assert main(["init", "-c", str(path)]) == 0
    profile = load_profile(path)
    assert profile.outputs == [], "a starter may not name a device"
    assert len(profile.events) >= 5, "and it should still describe the five prayers"
    live = [ln for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    assert not [ln for ln in live if "target:" in ln], "a live target is a stranger's speaker"
    assert (path.parent / "media").is_dir()
    assert "no speakers are configured" in capsys.readouterr().out


def test_the_starter_says_out_loud_what_is_still_missing(tmp_path):
    """The two mistakes a starter makes easy both produce no error at all: a
    city nobody chose, and a schedule with nowhere to play."""
    path = tmp_path / "muezzin.yaml"
    main(["init", "-c", str(path)])
    notes = starter_warnings(load_profile(path))
    assert any("New York" in n for n in notes), notes
    assert any("no speakers" in n for n in notes), notes

    text = path.read_text(encoding="utf-8")
    text = text.replace("latitude: 40.7128", "latitude: 25.7123")
    text = text.replace("longitude: -74.006", "longitude: 51.0753")
    text = text.replace("timezone: America/New_York", "timezone: Asia/Tehran")
    # uncomment the shape as written, then take out the one field this kind of
    # output does not use: a commented example that cannot be uncommented as it
    # stands is a commented example that teaches nothing
    text = text.replace("  # - name: house-group", "  - name: house-group")
    text = text.replace("  #   kind: google_cast", "    kind: pc_speakers")
    text = text.replace("\n  #   target: Whole-house group", "")
    text = text.replace("  #   volume: 0.5", "    volume: 0.5")
    path.write_text(text, encoding="utf-8")
    set_up = load_profile(path)
    assert [o.name for o in set_up.outputs] == ["house-group"], "the shape uncomments cleanly"
    assert starter_warnings(set_up) == [], "a set-up profile gets lectured to nobody"


def test_the_starter_notes_reach_somebody_who_only_ran_the_table(tmp_path, capsys):
    """`times` is the first command a nervous user types, so the notes belong in
    its output - while the table on stdout stays a table that can be piped."""
    path = tmp_path / "muezzin.yaml"
    main(["init", "-c", str(path)])
    assert main(["times", "-c", str(path)]) == 0
    captured = capsys.readouterr()
    assert "New York" in captured.err and "no speakers" in captured.err
    assert "fajr" in captured.out
    assert "note:" not in captured.out, "the notes are not part of the table"


def test_a_profile_that_changed_one_number_is_not_lectured(tmp_path):
    """The location note fires on the starter's exact placeholder triple, not on
    New York. A household that typed its own latitude - even in New York, and
    even leaving the timezone alone - has already told us what it needs."""
    path = tmp_path / "muezzin.yaml"
    path.write_text(STARTER.replace("latitude: 40.7128", "latitude: 40.7306"),
                    encoding="utf-8")
    notes = starter_warnings(load_profile(path))
    assert not [n for n in notes if "New York" in n], notes
    assert any("no speakers" in n for n in notes)


def test_a_starter_with_everything_switched_off_says_so(tmp_path):
    """Disabling every output is a thing the page lets you do, and the schedule
    then goes quiet with no other clue why."""
    path = tmp_path / "muezzin.yaml"
    path.write_text(STARTER.replace("  # - name: house-group", "  - name: pc")
                    .replace("  #   kind: google_cast", "    kind: pc_speakers")
                    .replace("  #   target: Whole-house group", "    enabled: false")
                    .replace("  #   volume: 0.5", ""), encoding="utf-8")
    notes = starter_warnings(load_profile(path))
    assert any("disabled" in n for n in notes), notes


SPEAKERS = """
location: {latitude: 40.7128, longitude: -74.006, timezone: America/New_York}
method: {preset: isna}
media_dir: media
outputs:
  - name: study
    kind: google_cast
    target: Study speaker
  - name: porch
    kind: google_cast
    target: Porch speaker
    lead_seconds: 0
events:
  - name: fajr-adhan
    at: fajr
    media: [fajr.mp3]
"""


def test_next_says_the_sound_starts_a_few_seconds_early(tmp_path, capsys):
    """`next` is the command people trust, so it promises the same number the
    daemon keeps: the time stays the computed one, and the note says the recording
    reaches a speaker that has to be found on the network a little before it. A
    speaker told `lead_seconds: 0` gets no note, because it starts on the minute."""
    path = tmp_path / "muezzin.yaml"
    path.write_text(SPEAKERS, encoding="utf-8")
    assert main(["next", "-c", str(path)]) == 0
    rows = [ln for ln in capsys.readouterr().out.splitlines() if "fajr-adhan" in ln]
    assert len(rows) >= 2, rows
    assert "(played 8 s early)" in rows[0], rows[0]
    assert "-> study, porch" in rows[0], "the slowest of the two is what gets paid for"
    quiet = SPEAKERS.replace("  - name: study\n    kind: google_cast\n    target: Study speaker\n", "")
    path.write_text(quiet, encoding="utf-8")
    assert main(["next", "-c", str(path)]) == 0
    line = [ln for ln in capsys.readouterr().out.splitlines() if "fajr-adhan" in ln][0]
    assert "early" not in line, line
