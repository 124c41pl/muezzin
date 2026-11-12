"""Tests for the display Hijri calendar.

The standard to hold it to is not "correct", because an arithmetic calendar
cannot be correct about a moon sighting. It is: self-consistent, close to the
calendars people actually read, and adjustable when a community disagrees with
all of them.
"""
from __future__ import annotations

import datetime as dt

import pytest

from muezzin.hijri import (LEAP_POSITIONS, MONTHS, MONTHS_AR, OBSERVANCES,
                           from_hijri, is_leap, month_days, to_hijri, year_days)

# Hijri dates api.aladhan.com publishes for these Gregorian dates (its arithmetic
# Kuwaiti calendar), fetched on 2026-11-10. (year, month, day).
PUBLISHED = [
    (dt.date(2024, 1, 1), (1445, 6, 19)),
    (dt.date(2024, 3, 10), (1445, 8, 29)),
    (dt.date(2024, 7, 6), (1445, 12, 30)),
    (dt.date(2024, 7, 16), (1446, 1, 10)),
    (dt.date(2025, 2, 28), (1446, 8, 29)),
    (dt.date(2025, 3, 1), (1446, 9, 1)),
    (dt.date(2025, 3, 13), (1446, 9, 13)),
    (dt.date(2025, 3, 30), (1446, 10, 1)),
    (dt.date(2025, 6, 6), (1446, 12, 10)),
    (dt.date(2025, 6, 26), (1447, 1, 1)),
    (dt.date(2025, 7, 5), (1447, 1, 10)),
    (dt.date(2025, 12, 31), (1447, 7, 11)),
    (dt.date(2026, 2, 4), (1447, 8, 16)),
    (dt.date(2026, 3, 19), (1447, 9, 30)),
    (dt.date(2026, 5, 26), (1447, 12, 9)),
    (dt.date(2026, 6, 3), (1447, 12, 17)),
    (dt.date(2026, 11, 10), (1448, 5, 30)),
    (dt.date(2027, 1, 1), (1448, 7, 23)),
    (dt.date(2027, 2, 7), (1448, 8, 30)),
    (dt.date(2027, 8, 20), (1449, 3, 18)),
    (dt.date(2028, 1, 1), (1449, 8, 4)),
    (dt.date(2028, 6, 15), (1450, 1, 22)),
    (dt.date(2029, 10, 10), (1451, 6, 2)),
    (dt.date(2030, 1, 1), (1451, 8, 26)),
    (dt.date(2031, 3, 1), (1452, 11, 7)),
    (dt.date(2035, 7, 4), (1457, 4, 28)),
]


def _as_tuple(h):
    return (h.year, h.month, h.day)


def _gap(date, want):
    """Gregorian days between what muezzin says and what the published calendars say.

    A positive number means muezzin is ahead. Some published months have a 30th day
    this arithmetic scheme cannot have - an even month stops at 29 - so those
    published dates are compared against the last day the month could have meant
    here, which is the day the two calendars are arguing about.
    """
    year, month, day = want
    last = month_days(year, month)
    if day > last:
        day = last
    return (date - from_hijri(year, month, day)).days


#: What this calendar is: plain arithmetic, odd months 30 days and even 29, with the
#: 30-year cycle of leap years. What the quoted dates are: printed calendars, which
#: follow a sighting or the Umm al-Qura computation. Measured on 2026-11-12: 13 of
#: the 26 dates land on the same Gregorian day, 13 have muezzin exactly one day
#: ahead, and one published date (30 Shaban 1448) has no name here at all, because
#: this reckoning makes that month 29 days. Re-measure before changing any of it.
EXACT, AHEAD, NO_NAME_HERE = 13, 13, 1


@pytest.mark.parametrize("date, want", PUBLISHED)
def test_published_dates_are_the_same_day_or_one_apart(date, want):
    """Never behind, never more than a day in front. Two days on any of these dates
    means the epoch moved; a different month means the month lengths moved."""
    year, month, day = want
    gap = _gap(date, want)
    assert 0 <= gap <= 1, (
        f"{date}: muezzin says {to_hijri(date).label}, published calendars say {day} "
        f"{MONTHS[month - 1]} {year} - {gap} days apart")


def test_the_agreement_with_published_calendars_is_pinned():
    """The loose version of this test let a refit of the epoch pass while making the
    display worse. These counts are the honest shape of the disagreement: half of
    printed calendars' dates land on the same day, and the rest are one day apart.
    If a count changes, the note above it changes with it, deliberately."""
    gaps = [_gap(date, want) for date, want in PUBLISHED]
    assert gaps.count(0) == EXACT, f"{gaps.count(0)} same day, pinned at {EXACT}"
    assert gaps.count(1) == AHEAD, f"{gaps.count(1)} one day ahead, pinned at {AHEAD}"
    assert len(gaps) == EXACT + AHEAD, f"the sample is not fully explained: {sorted(gaps)}"
    nameless = sum(1 for _, (year, month, day) in PUBLISHED if day > month_days(year, month))
    assert nameless == NO_NAME_HERE, f"{nameless} published days have no name here"


def test_the_documented_offset_really_closes_the_gap():
    """`hijri_offset: -1` is the answer given to a user whose month began a day
    later than this calendar thinks. It has to be the answer that works."""
    for date, want in PUBLISHED:
        year, month, day = want
        if day > month_days(year, month):
            continue        # a day this reckoning has no name for: no offset fixes that
        if _as_tuple(to_hijri(date)) == want:
            continue
        assert _as_tuple(to_hijri(date, -1)) == want, (
            f"{date}: offset -1 does not agree with published calendars either, it says "
            f"{to_hijri(date, -1).label} against {day} {MONTHS[month - 1]} {year}")


def test_a_day_the_printed_calendars_might_have_is_refused_politely():
    """Sha'ban 1448 has 30 days on printed calendars and 29 here. Saying so is the
    whole job: the alternative is a crash, or a silent wrong answer."""
    with pytest.raises(ValueError) as caught:
        from_hijri(1448, 8, 30)
    message = str(caught.value)
    assert f"of {MONTHS[7]} 1448" in message, "the refusal should name the month"
    assert "29" in message
    assert "hijri_offset" in message, "the refusal should say what to do about it"


def test_every_month_start_and_end_round_trips():
    for year in range(1440, 1461):
        for month in range(1, 13):
            for day in (1, month_days(year, month)):
                gregorian = from_hijri(year, month, day)
                assert _as_tuple(to_hijri(gregorian)) == (year, month, day)


def test_consecutive_days_never_skip_or_repeat():
    day = dt.date(2026, 11, 10)
    previous = to_hijri(day)
    for _ in range(800):
        day += dt.timedelta(days=1)
        current = to_hijri(day)
        if previous.day < month_days(previous.year, previous.month):
            assert _as_tuple(current) == (previous.year, previous.month, previous.day + 1)
        elif previous.month < 12:
            assert _as_tuple(current) == (previous.year, previous.month + 1, 1)
        else:
            assert _as_tuple(current) == (previous.year + 1, 1, 1)
        previous = current


def test_years_and_cycles():
    assert sum(1 for y in range(1, 31) if is_leap(y)) == 11
    assert len(LEAP_POSITIONS) == 11
    for year in (1445, 1446, 1447, 1448, 1449):
        assert sum(month_days(year, m) for m in range(1, 13)) == year_days(year)
        assert year_days(year) in (354, 355)


def test_month_lengths_alternate_except_the_twelfth():
    for year in (1446, 1447):
        for month in range(1, 12):
            assert month_days(year, month) == (30 if month % 2 else 29)
        assert month_days(year, 12) == (30 if is_leap(year) else 29)


def test_the_offset_knob_is_honest_about_what_it_does():
    """A positive offset must mean exactly one thing: the month started later."""
    day = dt.date(2026, 11, 10)
    assert to_hijri(day, 2) == to_hijri(day + dt.timedelta(days=2), 0)
    assert from_hijri(1448, 5, 30, 2) == from_hijri(1448, 5, 30, 0) - dt.timedelta(days=2)
    assert to_hijri(day, -1).day == to_hijri(day, 0).day - 1


@pytest.mark.parametrize("offset", [-4, 4, 10])
def test_an_absurd_offset_is_refused(offset):
    with pytest.raises(ValueError, match="between -3 and 3"):
        to_hijri(dt.date(2026, 11, 10), offset)


def test_impossible_hijri_dates_are_refused():
    with pytest.raises(ValueError, match="month must be 1-12"):
        from_hijri(1448, 13, 1)
    with pytest.raises(ValueError, match="year must be 1 or later"):
        from_hijri(0, 1, 1)
    with pytest.raises(ValueError, match="that month has 29 days"):
        from_hijri(1448, 2, 30)


def test_markers_land_where_their_names_say():
    assert to_hijri(from_hijri(1447, 1, 10)).day == 10
    ashura = [o for o in OBSERVANCES if o[2] == "Ashura"]
    assert ashura == [(1, 10, "Ashura", "عاشوراء", "mourn")]
    # the 12th month is the short one in a common year, so check the marker fits
    assert all(1 <= month <= 12 and 1 <= day <= month_days(1446, month)
               for (month, day, _, _, _) in OBSERVANCES)


def test_a_plain_day_has_no_markers():
    from muezzin.hijri import day_info
    info = day_info(dt.date(2026, 11, 10))
    assert info["marks"] == []
    assert info["hijri"] == "30 Jumada al-Ula 1448"
    assert info["hijri_ar"].endswith(MONTHS_AR[4])


def test_markers_show_up_on_the_day_they_fall_on():
    from muezzin.hijri import day_info
    info = day_info(from_hijri(1448, 7, 13))       # 13 Rajab, birth of Imam Ali
    assert [m["name"] for m in info["marks"]] == ["Birth of Imam Ali"]
    assert info["marks"][0]["kind"] == "celebrate"
    assert info["marks"][0]["ar"]


def test_every_marker_kind_is_one_the_page_knows_how_to_paint():
    assert {kind for (_, _, _, _, kind) in OBSERVANCES} <= {"mourn", "celebrate", "plain"}
