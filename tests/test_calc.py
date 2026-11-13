"""Engine tests: published timetables, invariants, and the method features a
closed enum of named methods could not express (Shia angles, Jafari midnight,
maghrib depression angle, isha intervals, high-latitude rules).

Tolerances are in minutes and deliberately not tight: we are checking that the
implementation agrees with published timetables to about a minute, not that it
reproduces their rounding.
"""
from __future__ import annotations

import datetime as dt

import pytest

from muezzin import calc

MIN = 1.0 / 60.0

NYC = calc.Location(40.7128, -74.0060, "America/New_York")
LONDON = calc.Location(51.5074, -0.1278, "Europe/London")
QOM = calc.Location(34.6416, 50.8799, "Asia/Tehran")
MAKKAH = calc.Location(21.4225, 39.8262, "Asia/Riyadh")
REYKJAVIK = calc.Location(64.15, -21.94, "Atlantic/Reykjavik")

# api.aladhan.com, captured 2026-11-10
PUBLISHED = [
    ("NYC / ISNA (aladhan method 2)", NYC, dt.date(2026, 11, 10), calc.PRESETS["isna"],
     {"fajr": "05:19", "sunrise": "06:37", "dhuhr": "11:40", "asr": "14:21",
      "maghrib": "16:42", "isha": "18:00"}),
    ("London / Egyptian (aladhan method 5)", LONDON, dt.date(2026, 11, 10), calc.PRESETS["egyptian"],
     {"fajr": "05:04", "sunrise": "07:10", "dhuhr": "11:44", "asr": "13:56",
      "maghrib": "16:18", "isha": "18:11"}),
    # The case a closed enum of named methods could not express at all: the
    # Institute of Geophysics, Tehran (Fajr 17.7 / Isha 14, Jafari midnight). Its
    # published maghrib is a 4.5 deg depression, not sunset, so this row expects
    # the sunset value.
    ("Qom / Tehran institute (aladhan method 7)", QOM, dt.date(2026, 11, 10),
     calc.PRESETS["tehran"],
     {"fajr": "05:10", "sunrise": "06:35", "dhuhr": "11:50", "asr": "14:45",
      "maghrib": "17:05", "isha": "18:12"}),
]


def hhmm(text: str) -> float:
    h, m = text.split(":")
    return int(h) + int(m) / 60.0


@pytest.mark.parametrize("name,loc,date,params,expect", PUBLISHED, ids=[p[0] for p in PUBLISHED])
def test_matches_published_timetables(name, loc, date, params, expect):
    got = calc.compute_times(loc, date, params)
    for key, want in expect.items():
        value = getattr(got, key)
        assert value is not None, f"{name}: {key} missing"
        assert abs(value - hhmm(want)) * 60 <= 2.0, f"{name}: {key} off by more than 2 min"


@pytest.mark.parametrize("lat,lng,tz", [
    (40.7128, -74.006, "America/New_York"),
    (-33.8688, 151.2093, "Australia/Sydney"),
    (1.29, 36.82, "Africa/Nairobi"),
    (59.91, 10.75, "Europe/Oslo"),
])
@pytest.mark.parametrize("month", [3, 6, 9, 12])
def test_ordering_and_solar_symmetry(lat, lng, tz, month):
    """Sunrise and maghrib are the same depression, so they must be symmetric
    about dhuhr; and the five times must fall in the natural order."""
    date = dt.date(2026, month, 20)
    t = calc.compute_times(calc.Location(lat, lng, tz), date, calc.PRESETS["mwls"])
    order = [t.fajr, t.sunrise, t.dhuhr, t.asr, t.maghrib, t.isha]
    assert all(v is not None for v in order), f"{lat},{lng} {date}: a time is missing"
    assert order == sorted(order), f"{lat},{lng} {date}: out of order {order}"
    assert abs((t.sunrise + t.maghrib) / 2.0 - t.dhuhr) * 60 <= 1.5, "sun is not symmetric about dhuhr"


def test_hanafi_asr_is_later():
    date = dt.date(2026, 11, 10)
    std = calc.compute_times(NYC, date, calc.PRESETS["isna"], asr_shadow=calc.ASR_SHADOW_STANDARD)
    hanafi = calc.compute_times(NYC, date, calc.PRESETS["isna"], asr_shadow=calc.ASR_SHADOW_HANAFI)
    assert (hanafi.asr - std.asr) * 60 > 20


def test_isha_interval_preset_is_exactly_90_minutes():
    """Umm al-Qura gives no isha angle: isha is maghrib + 90 min."""
    t = calc.compute_times(MAKKAH, dt.date(2026, 11, 10), calc.PRESETS["umm_al_qura"])
    assert abs((t.isha - t.maghrib) * 60 - 90.0) < 0.1


def test_maghrib_depression_angle_matches_tehran_1724():
    """aladhan's Tehran timetable puts maghrib at a 4.5 deg depression. In
    muezzin that is data: maghrib_angle_offset = 4.5 - 0.833."""
    base = calc.PRESETS["tehran"]
    params = calc.MethodParams(base.fajr_angle, base.isha_angle,
                               maghrib_angle_offset=4.5 - 0.833,
                               midnight_from_fajr=True, label="Tehran with 4.5deg maghrib")
    t = calc.compute_times(QOM, dt.date(2026, 11, 10), params)
    assert abs(t.maghrib - hhmm("17:24")) * 60 <= 2.0
    assert t.maghrib > t.sunset


def test_jafari_midnight_follows_the_method():
    """Jafari/Tehran/Qom methods split the night sunset -> fajr. `midnight` must
    report the convention the method declares, not always the solar one."""
    date = dt.date(2026, 11, 10)
    jafari = calc.compute_times(QOM, date, calc.PRESETS["qom"])
    solar = calc.compute_times(QOM, date, calc.PRESETS["mwls"])
    assert jafari.midnight == pytest.approx(jafari.true_night)
    assert jafari.midnight < solar.midnight - 5 * MIN, "Jafari midnight should be earlier than solar"
    expected = jafari.maghrib + ((24.0 - jafari.maghrib) + jafari.fajr) / 2.0
    assert jafari.midnight == pytest.approx(expected, abs=MIN)
    # a method that does not declare midnight_from_fajr keeps the solar midpoint
    assert solar.midnight == pytest.approx(solar.dhuhr + 12.0, abs=2.0 * MIN)


def test_high_latitude_rules():
    """At the summer solstice Reykjavik has no 18 deg twilight: with the rule off
    the time is honestly missing, with a rule on it is a real fallback."""
    date = dt.date(2026, 6, 21)
    plain = calc.MethodParams(18.0, 17.0, high_latitude_rule=calc.HIGH_LAT_NONE, label="none")
    t = calc.compute_times(REYKJAVIK, date, plain)
    assert t.fajr is None and t.isha is None, "no true dawn at 64N on the solstice"

    for rule in (calc.HIGH_LAT_MIDDLE_OF_NIGHT, calc.HIGH_LAT_ONE_SEVENTH, calc.HIGH_LAT_ANGLE_BASED):
        t = calc.compute_times(REYKJAVIK, date,
                               calc.MethodParams(18.0, 17.0, high_latitude_rule=rule, label=rule))
        assert t.fajr is not None and t.isha is not None, f"{rule} produced no times"
        assert t.fajr < t.sunrise < t.maghrib <= t.isha


def test_missing_times_stay_missing_for_unwrapped_days():
    """A midnight-sun day: sunrise/sunset do not exist and the engine says so
    rather than inventing a time."""
    t = calc.compute_times(calc.Location(78.22, 15.65, "Arctic/Longyearbyen"),
                           dt.date(2026, 6, 21),
                           calc.MethodParams(18.0, 17.0, high_latitude_rule=calc.HIGH_LAT_NONE,
                                             label="none"))
    assert t.sunrise is None or t.sunset is None


def test_elevation_lowers_sunrise_and_raises_maghrib():
    """A mountain top sees the sun earlier and sets it later; the dip correction
    must move both times in the same direction as the adhan convention."""
    low = calc.Location(40.7128, -74.006, "America/New_York", elevation_m=0.0)
    high = calc.Location(40.7128, -74.006, "America/New_York", elevation_m=1000.0)
    date = dt.date(2026, 6, 21)
    a = calc.compute_times(low, date, calc.PRESETS["isna"])
    b = calc.compute_times(high, date, calc.PRESETS["isna"])
    assert b.sunrise < a.sunrise, "elevation should bring sunrise earlier"
    assert b.maghrib > a.maghrib, "elevation should delay maghrib"
    assert (a.sunrise - b.sunrise) * 60 > 2.0, "1000 m of elevation should matter"


def test_dhuhr_adjustment_moves_only_dhuhr():
    """Adjustments are per-prayer minutes, applied to that time only - the
    per-salat offset box every user expects, expressed as data."""
    date = dt.date(2026, 11, 10)
    plain = calc.compute_times(NYC, date, calc.PRESETS["isna"])
    adj = calc.Adjustments(dhuhr=5, isha=-3)
    moved = calc.compute_times(NYC, date, calc.PRESETS["isna"], adjustments=adj)
    assert abs((moved.dhuhr - plain.dhuhr) * 60 - 5.0) < 0.01
    assert abs((moved.isha - plain.isha) * 60 + 3.0) < 0.01
    assert moved.fajr == plain.fajr and moved.maghrib == plain.maghrib


def test_shia_presets_are_present_and_distinct():
    """The whole reason this project exists: a CalculationMethod enum with 11
    values has no Shia entries in it, and there is no way to add one."""
    for name in ("qom", "qom_khamenei_12", "tehran", "shia_ithna_ashari"):
        p = calc.PRESETS[name]
        assert p.midnight_from_fajr, f"{name} should use the Jafari night"
    angles = {name: (calc.PRESETS[name].fajr_angle, calc.PRESETS[name].isha_angle)
              for name in calc.PRESETS}
    assert angles["qom"] == (19.0, 14.0)
    assert angles["tehran"] == (17.7, 14.0)
    assert angles["shia_ithna_ashari"] == (16.0, 14.0)
    assert angles["mwls"] == (18.0, 17.0)


def test_method_from_config_accepts_raw_numbers():
    """A family whose authority is not in the list writes their own numbers."""
    p = calc.method_from_config({"method": {"fajr_angle": 16.5, "isha_angle": 15.0,
                                            "midnight_from_fajr": True}})
    assert (p.fajr_angle, p.isha_angle) == (16.5, 15.0)
    assert p.midnight_from_fajr is True
    t = calc.compute_times(QOM, dt.date(2026, 11, 10), p)
    assert t.fajr is not None


def test_method_from_config_preset_plus_override():
    p = calc.method_from_config({"method": {"preset": "qom", "isha_angle": 13.0}})
    assert p.fajr_angle == 19.0 and p.isha_angle == 13.0
    assert calc.method_from_config({"method": "mwls"}).fajr_angle == 18.0


def test_method_config_typos_are_rejected_with_a_useful_message():
    with pytest.raises(ValueError, match="degrees"):
        calc.method_from_config({"method": {"fajr_angle": 1800}})
    with pytest.raises(ValueError, match="MINUTES"):
        calc.method_from_config({"method": {"preset": "mwls", "isha_interval": 0}})
    with pytest.raises(KeyError, match="unknown method preset"):
        calc.method_from_config({"method": "my-masjid"})


def test_isha_interval_overrides_the_isha_angle():
    """Some authorities give a fixed interval after maghrib instead of an angle;
    when both are present the interval wins, which is what those tables mean."""
    p = calc.method_from_config({"method": {"preset": "mwls", "isha_interval": 90}})
    t = calc.compute_times(MAKKAH, dt.date(2026, 11, 10), p)
    assert abs((t.isha - t.maghrib) * 60 - 90.0) < 0.1


def test_times_are_not_wrapped_into_a_day():
    """A time past midnight must stay >24 so the scheduler can place it on the
    right calendar day."""
    t = calc.compute_times(REYKJAVIK, dt.date(2026, 6, 21),
                           calc.MethodParams(18.0, 17.0, high_latitude_rule=calc.HIGH_LAT_ONE_SEVENTH,
                                             label="seventh"))
    assert t.isha > 24.0, "isha after midnight should not be folded back to 00:xx"


def test_an_angle_based_rule_uses_the_angles_of_the_profile_it_is_running_for():
    """Reykjavik in June has no true fajr and no true isha, so the high-latitude
    rule is what decides. angle_based divides the profile's own angle by 60; when
    the call dropped that angle it fell back to one seventh of the night, and
    nothing about the printed time gave that away."""
    june = dt.date(2026, 6, 21)
    angle = calc.MethodParams(10.0, 12.0, high_latitude_rule=calc.HIGH_LAT_ANGLE_BASED,
                              label="angle based")
    seventh = calc.MethodParams(10.0, 12.0, high_latitude_rule=calc.HIGH_LAT_ONE_SEVENTH,
                                label="seventh")
    by_angle = calc.compute_times(REYKJAVIK, june, angle)
    by_seventh = calc.compute_times(REYKJAVIK, june, seventh)
    assert by_angle.fajr is not None and by_seventh.fajr is not None
    assert abs(by_angle.fajr - by_seventh.fajr) * 60 > 3.0, "two rules, two answers"
    night = (by_seventh.sunrise - by_seventh.sunset) % 24.0
    assert abs(by_angle.fajr - (by_seventh.sunrise - night * 10.0 / 60.0)) * 60 < 0.01
    assert abs(by_angle.isha - (by_seventh.sunset + night * 12.0 / 60.0)) * 60 < 0.01


def test_observer_height_moves_the_horizon_the_right_distance():
    """The horizon dips 0.0347469 * sqrt(height in metres) degrees, so 100 m buys
    a minute or two of daylight on each side of the day. A negative height is
    clamped at zero rather than handed to a square root."""
    date = dt.date(2026, 11, 10)
    at_sea = calc.Location(40.7128, -74.0060, "America/New_York")
    upstairs = calc.Location(40.7128, -74.0060, "America/New_York", elevation_m=100.0)
    basement = calc.Location(40.7128, -74.0060, "America/New_York", elevation_m=-400.0)
    sea = calc.compute_times(at_sea, date, calc.PRESETS["isna"])
    high = calc.compute_times(upstairs, date, calc.PRESETS["isna"])
    low = calc.compute_times(basement, date, calc.PRESETS["isna"])
    assert low.maghrib == sea.maghrib, "below sea level the horizon does not rise"
    later = (high.maghrib - sea.maghrib) * 60
    earlier = (sea.sunrise - high.sunrise) * 60
    assert 0.5 < later < 3.0 and 0.5 < earlier < 3.0
    assert abs(later - earlier) < 0.05, "one dip, applied to both sides of the day"


def test_midnight_follows_the_maghrib_and_fajr_the_household_actually_hears():
    """A maghrib expressed as a depression angle, or nudged by hand, has to carry
    midnight with it: `at: midnight` is measured between the two times the family
    is told, not between the raw solar values behind them."""
    date = dt.date(2026, 11, 10)
    plain = calc.compute_times(QOM, date, calc.PRESETS["qom"])
    deeper = calc.compute_times(
        QOM, date,
        calc.method_from_config({"method": {"preset": "qom", "maghrib_angle_offset": 2.0}}))
    assert deeper.maghrib > plain.maghrib
    assert abs((deeper.true_night - plain.true_night) * 60
               - (deeper.maghrib - plain.maghrib) * 60 / 2.0) < 0.01
    assert deeper.midnight == deeper.true_night, "qom counts the night from maghrib to fajr"
    nudged = calc.compute_times(QOM, date, calc.PRESETS["qom"],
                                adjustments=calc.Adjustments(maghrib=30))
    assert abs((nudged.midnight - plain.midnight) * 60 - 15.0) < 0.01


def test_an_adjustment_that_walks_isha_in_front_of_maghrib_says_so(caplog):
    """These times are deliberately not wrapped, so maghrib at 24:38 next to an
    isha at 22:34 is a night running backwards. That is a typo, and a silent typo
    in a prayer timetable is the worst kind."""
    with caplog.at_level("WARNING", logger="muezzin.calc"):
        times = calc.compute_times(NYC, dt.date(2026, 11, 10), calc.PRESETS["isna"],
                                   adjustments=calc.Adjustments(maghrib=90, isha=-120))
    assert times.isha < times.maghrib
    assert "before maghrib" in caplog.text


def test_the_documented_preset_count_and_names_match_the_table():
    """The docs say how many starting points there are, and the README table is
    where a reader goes looking for their own authority. Add a preset and forget
    the prose and the first command anyone runs, `muezzin methods`, disagrees
    with the page they are reading; this is the check that keeps them equal."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    example = (root / "config" / "example.yaml").read_text(encoding="utf-8")
    count = len(calc.PRESETS)
    # folded, because the sentence carrying the count may start a line: the thing
    # under test is the number, not which letter happens to be capital
    assert f"the {count} presets" in readme.lower(), "the README counts the presets wrong"
    assert f"Any of the {count} presets" in example, "config/example.yaml counts them wrong"
    for name in calc.PRESETS:
        assert f"`{name}`" in readme, f"{name} exists in the code but is not in the README table"
