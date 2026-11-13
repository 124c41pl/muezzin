"""The city table behind `muezzin where`, and the one edit it is allowed to make.

Two things are worth pinning down here. The first is that the table is data a
person will trust: a made-up time zone name or a transposed coordinate produces a
timetable that looks fine and is wrong, which is exactly the failure this command
exists to prevent. The second is that the claim the help text and the README both
make - that a time zone labels the clock while the coordinates move the times - is
true of our own engine, and should be tested rather than repeated.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from muezzin import calc, places
from muezzin.cli import STARTER, main, starter_warnings
from muezzin.config import load_profile


def _notes(path):
    return starter_warnings(load_profile(path))


def test_every_row_is_a_place_the_engine_can_actually_take():
    seen = set()
    for p in places.PLACES:
        assert p.name and p.timezone, p.label
        assert -90.0 <= p.latitude <= 90.0, f"{p.label} latitude"
        assert -180.0 <= p.longitude <= 180.0, f"{p.label} longitude"
        key = (p.name.casefold(), p.region.casefold())
        assert key not in seen, f"{p.label} is in the table twice"
        seen.add(key)


def test_every_time_zone_is_a_name_the_clock_database_knows():
    """An invented zone is the quiet failure of this table: the coordinates would
    still be right, and every time would land an hour off without a complaint."""
    for p in places.PLACES:
        try:
            ZoneInfo(p.timezone)
        except ZoneInfoNotFoundError:
            pytest.fail(f"{p.label} claims a zone nobody runs: {p.timezone}")


def test_the_table_is_a_shortcut_and_not_an_index_of_the_world():
    """Big enough that the common cities are there; small enough that the docstring's
    promise - city centres, hand-checked - is still true of every row."""
    assert 60 <= len(places.PLACES) <= 150, len(places.PLACES)


def test_a_name_two_cities_share_is_not_decided_by_guessing():
    """`London` picking one of them silently would put a family's times on the
    other side of an ocean, and the page would never mention it."""
    hits = places.find("london")
    assert [h.label for h in hits] == ["London, Ontario", "London, United Kingdom"]
    assert len(places.find("birmingham")) == 2
    with pytest.raises(places.AmbiguousPlace) as exc:
        places.lookup("london")
    assert "London, Ontario" in str(exc.value) and "United Kingdom" in str(exc.value)


def test_naming_the_region_narrows_the_answer_instead_of_missing_it():
    for query in ("london ontario", "London, Ontario", "LONDON  ontario"):
        hit = places.lookup(query)
        assert hit.label == "London, Ontario", query
        assert hit.timezone == "America/Toronto", query


def test_cities_are_found_whatever_way_the_reader_types_them():
    assert places.lookup("orlando").label == "Orlando, Florida"
    assert places.lookup("ORLANDO").label == "Orlando, Florida"
    assert places.lookup("orlando florida").label == "Orlando, Florida"
    assert places.lookup("qom").label == "Qom, Iran"
    # the spellings people arrive with, and the punctuation a region brings
    assert places.lookup("mecca").label == "Makkah, Saudi Arabia"
    assert places.lookup("nyc").label == "New York, New York"
    assert places.lookup("washington, d.c.").label == "Washington, District of Columbia"


def test_every_alias_lands_on_exactly_one_row_in_the_table():
    """An alias pointed at a city the table does not have is a silent dead end: the
    reader typed a common name and got "no such city"."""
    names = {p.name.casefold() for p in places.PLACES}
    for alias, target in places.ALIASES.items():
        assert len([p for p in places.PLACES if p.name.casefold() == target.casefold()]) == 1, \
            f"{alias} -> {target}"
    assert names.isdisjoint(places.ALIASES), "an alias that shadows its own city is a tangle"


def test_a_city_that_is_not_here_is_answered_with_a_no():
    assert places.find("") == []
    assert places.find("   ") == []
    assert places.find("llanfairpwllgwyngyll") == []
    with pytest.raises(places.UnknownPlace):
        places.lookup("llanfairpwllgwyngyll")


def test_the_coordinates_are_the_ones_the_timetables_for_that_city_quote():
    """Spot-checked against the usual published centre points, so a row cannot drift
    into a decimal-place typo that moves a prayer by minutes."""
    orlando = places.lookup("orlando")
    assert round(orlando.latitude, 1) == 28.5 and round(orlando.longitude, 1) == -81.4
    qom = places.lookup("qom")
    assert round(qom.latitude, 2) == 34.64 and round(qom.longitude, 2) == 50.88
    assert qom.timezone == "Asia/Tehran"


def test_one_clock_does_not_mean_one_timetable():
    """The sentence the help text and the README both make, proved on the engine:
    Orlando and Erie share America/New_York, and their Maghrib lands far apart,
    because the sun sits at a different angle over each of them."""
    orlando, erie = places.lookup("orlando"), places.lookup("erie")
    assert orlando.timezone == erie.timezone == "America/New_York"
    assert abs(orlando.latitude - erie.latitude) > 13.0
    day = dt.date(2026, 12, 21)          # the spread is widest at the solstice
    a = calc.compute_times(calc.Location(orlando.latitude, orlando.longitude, orlando.timezone),
                           day, calc.PRESETS["isna"])
    b = calc.compute_times(calc.Location(erie.latitude, erie.longitude, erie.timezone),
                           day, calc.PRESETS["isna"])
    spread = abs(a.maghrib - b.maghrib)
    # measured, not guessed: 17:33 in Orlando against 16:51 in Erie. Half an hour
    # is comfortably more than the minute a person acts on, and comfortably less
    # than what a wrong time zone would have done to the same two rows.
    assert spread > 0.5, f"only {spread * 60:.0f} minutes apart; the claim needs the winter sun"
    assert a.fajr != b.fajr


def test_lookup_returns_the_three_lines_a_profile_needs():
    assert places.lookup("qom").as_config() == {
        "latitude": 34.6416, "longitude": 50.8799, "timezone": "Asia/Tehran"}


# --- the command itself -------------------------------------------------------

def test_where_without_a_city_explains_itself_rather_than_listing_everything(capsys):
    assert main(["where"]) == 0
    out = capsys.readouterr().out
    assert str(len(places.PLACES)) in out
    assert "labels the clock" in out, "the sun/clock distinction is the point of the command"


def test_an_ambiguous_city_gives_the_reader_the_next_command_to_type(tmp_path, capsys):
    assert main(["where", "london", "-c", str(tmp_path / "muezzin.yaml")]) == 2
    err = capsys.readouterr().err
    assert "London, Ontario" in err and "United Kingdom" in err
    assert 'muezzin where "London, Ontario"' in err, "the fix is shown, not described"


def test_a_city_we_do_not_have_sends_the_reader_to_their_own_coordinates(tmp_path, capsys):
    assert main(["where", "timbuktu", "-c", str(tmp_path / "muezzin.yaml")]) == 2
    err = capsys.readouterr().err
    assert "no city centre" in err and "latitude" in err


def test_reading_a_city_out_loud_does_not_touch_the_profile(tmp_path):
    path = tmp_path / "muezzin.yaml"
    path.write_text(STARTER, encoding="utf-8")
    before = path.read_bytes()
    assert main(["where", "qom", "-c", str(path)]) == 0
    assert path.read_bytes() == before, "looking something up writes nothing"


def test_write_replaces_three_lines_and_keeps_everything_else(tmp_path, capsys):
    """The comment on each line is the explanation of that line. A command that
    rewrote the block would take the teaching with it, which is why this goes
    through the same line-preserving editor the page uses."""
    path = tmp_path / "muezzin.yaml"
    path.write_text(STARTER, encoding="utf-8")
    assert main(["where", "--write", "qom", "-c", str(path)]) == 0
    text = path.read_text(encoding="utf-8")
    assert "latitude: 34.6416" in text and "longitude: 50.8799" in text
    assert "timezone: Asia/Tehran" in text
    assert "# your latitude, north positive" in text, "the comment outlives the edit"
    assert "# IANA name: DST is handled by the tz database" in text
    assert text.count("#") == STARTER.count("#"), "no comment was lost anywhere in the file"
    profile = load_profile(path)
    assert round(profile.location.latitude, 4) == 34.6416
    assert profile.location.timezone == "Asia/Tehran"
    assert not [n for n in _notes(path) if "placeholder" in n], "the nag is now a lie"


def test_write_keeps_the_line_endings_a_windows_profile_already_uses(tmp_path):
    """A profile checked out with CRLF should show one changed line in a diff, not
    the whole file rewritten - so the endings have to be kept, not normalised."""
    path = tmp_path / "muezzin.yaml"
    path.write_bytes(STARTER.replace("\n", "\r\n").encode("utf-8"))
    assert main(["where", "--write", "qom", "-c", str(path)]) == 0
    raw = path.read_bytes()
    # every line feed already has its carriage return in front of it: no line was
    # left with the other style, and none was doubled
    assert raw.count(b"\n") == raw.count(b"\r\n") == STARTER.count("\n")


def test_choosing_the_starter_s_city_leaves_the_honest_notice_alone(tmp_path, capsys):
    """New York is in the table, and its centre is the placeholder the starter
    guesses. Writing it in is still a real choice, but the page's check is on those
    three exact numbers, so the note stays - and the command says why instead of
    letting the page contradict what the reader just did."""
    path = tmp_path / "muezzin.yaml"
    path.write_text(STARTER, encoding="utf-8")
    assert main(["where", "--write", "new york", "-c", str(path)]) == 0
    assert "the starter profile guesses" in capsys.readouterr().out
    assert [n for n in _notes(path) if "placeholder" in n]


def test_write_refuses_a_profile_that_is_not_there_yet(tmp_path, capsys):
    assert main(["where", "--write", "qom", "-c", str(tmp_path / "muezzin.yaml")]) == 2
    assert "muezzin init" in capsys.readouterr().err


def _readme() -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


def test_the_read_advertises_the_command_it_ships():
    """`where` is step one of the four steps in the README; a README that stops
    naming it while the code keeps it is a doc that has quietly gone stale."""
    assert "muezzin where" in _readme() and "places.py" in _readme()


def test_the_city_count_the_readme_promise_makes_matches_the_table():
    """A count is the one sentence in the README that changes when somebody adds a
    row, so the row and the sentence get checked together - same reason the
    "18 presets" line is pinned in test_calc.py."""
    import re
    claim = re.search(r"knows (\d+) city centres", _readme())
    assert claim, "the README no longer says how many city centres `where` knows"
    assert int(claim.group(1)) == len(places.PLACES), \
        f"the README promises {claim.group(1)}, the table has {len(places.PLACES)}"
