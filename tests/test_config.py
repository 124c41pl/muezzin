"""Config tests: the YAML is the whole interface, so what it accepts and what it
refuses matters as much as the astronomy."""
from __future__ import annotations

import pytest

from muezzin.config import load_profile

BASE = """
location: {latitude: 40.7128, longitude: -74.006, timezone: America/New_York}
method: {preset: isna}
media_dir: media
outputs:
  - name: study
    kind: google_cast
    target: Study speaker
  - name: spare
    kind: file
    host: out
    enabled: false
events:
  - name: fajr-adhan
    at: fajr
    media: [fajr.mp3]
    targets: [study]
"""


def write(tmp_path, text: str):
    path = tmp_path / "muezzin.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_profile_reads_a_plain_file(tmp_path):
    p = load_profile(write(tmp_path, BASE))
    assert p.params.fajr_angle == 15.0            # ISNA
    assert p.asr_shadow == 1.0
    assert [o.name for o in p.enabled_outputs()] == ["study"]
    assert [t.name for t in p.targets_for(p.events[0])] == ["study"]


def test_method_override_on_top_of_a_preset(tmp_path):
    p = load_profile(write(tmp_path, BASE.replace("{preset: isna}",
                                                  "{preset: isna, isha_angle: 15.0, fajr_angle: 18}")))
    assert (p.params.fajr_angle, p.params.isha_angle) == (18.0, 15.0)


def test_method_can_be_only_numbers(tmp_path):
    """No preset, just the angles your masjid publishes."""
    p = load_profile(write(tmp_path, BASE.replace("method: {preset: isna}",
                                                  "method: {fajr_angle: 16.5, isha_angle: 14.0, "
                                                  "midnight_from_fajr: true}")))
    assert (p.params.fajr_angle, p.params.isha_angle) == (16.5, 14.0)
    assert p.params.midnight_from_fajr is True


def test_hanafi_asr(tmp_path):
    p = load_profile(write(tmp_path, BASE.replace("{preset: isna}", "{preset: isna, asr_shadow: hanafi}")))
    assert p.asr_shadow == 2.0


def test_disabled_output_is_not_a_target(tmp_path):
    """`enabled: false` is how you park a speaker without deleting its config."""
    p = load_profile(write(tmp_path, BASE.replace("targets: [study]", "targets: [study, spare]")))
    assert [t.name for t in p.targets_for(p.events[0])] == ["study"]


def test_unknown_output_kind_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown kind 'google_case'"):
        load_profile(write(tmp_path, BASE.replace("kind: google_cast", "kind: google_case")))


def test_typo_in_at_is_rejected(tmp_path):
    """`at: fagr` must not become a silent, quiet morning."""
    with pytest.raises(ValueError, match="unknown `at: fagr`"):
        load_profile(write(tmp_path, BASE.replace("at: fajr", "at: fagr")))


def test_event_targeting_a_missing_output_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="do not exist"):
        load_profile(write(tmp_path, BASE.replace("targets: [study]", "targets: [kithcen]")))


def test_event_without_media_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="no `media:`"):
        load_profile(write(tmp_path, BASE.replace("media: [fajr.mp3]", "media: []")))


def test_hijri_offset_and_attribution_default_to_nothing(tmp_path):
    p = load_profile(write(tmp_path, BASE))
    assert p.hijri_offset == 0
    assert p.attribution is None


def test_hijri_offset_and_attribution_are_read(tmp_path):
    p = load_profile(write(tmp_path, BASE + "hijri_offset: 1\nattribution: Ali's house\n"))
    assert p.hijri_offset == 1
    assert p.attribution == "Ali's house"


def test_an_absurd_hijri_offset_is_rejected(tmp_path):
    """It only moves a date on screen, so a large number is a typo, not a
    preference, and the page would quietly disagree with the local calendar."""
    with pytest.raises(ValueError, match="hijri_offset must be between -3 and 3"):
        load_profile(write(tmp_path, BASE + "hijri_offset: 30\n"))
    with pytest.raises(ValueError, match="whole number of days"):
        load_profile(write(tmp_path, BASE + "hijri_offset: last week\n"))


# ---- the parts a stranger on the wifi, or a careless afternoon, could reach ----

def test_a_coordinate_off_the_globe_is_rejected(tmp_path):
    """A latitude of 407 is a decimal point in the wrong place, and the daemon
    would then spend the day computing sun angles for a place that does not
    exist, printing times that look plausible."""
    base = "location: {latitude: 40.7128, longitude: -74.006, timezone: America/New_York}"
    for bad in ("location: {latitude: 407, longitude: -74.006, timezone: America/New_York}",
                "location: {latitude: -91, longitude: -74.006, timezone: America/New_York}",
                "location: {latitude: 40.7128, longitude: 181, timezone: America/New_York}",
                "location: {latitude: 40.7128, longitude: -180.5, timezone: America/New_York}"):
        with pytest.raises(ValueError, match="between -90 and 90"):
            load_profile(write(tmp_path, BASE.replace(base, bad)))

    # a coordinate that is simply absent is the same kind of mistake, and it used
    # to arrive as a KeyError about a dictionary instead of a sentence about a file
    for missing in ("location: {latitude: 40.7128, timezone: America/New_York}",
                    "location: {longitude: -74.006, timezone: America/New_York}",
                    "location: {}"):
        with pytest.raises(ValueError, match="needs latitude and longitude"):
            load_profile(write(tmp_path, BASE.replace(base, missing)))


def test_a_timezone_the_machine_does_not_know_is_refused_where_it_is_typed(tmp_path):
    """Nothing else checks the zone before the daemon has committed to it, so a
    typo would end as a traceback and a silent morning."""
    with pytest.raises(ValueError, match="not a zone this machine knows"):
        load_profile(write(tmp_path, BASE.replace("America/New_York", "Amrica/New_York")))


def test_a_host_with_anything_extra_in_it_is_rejected(tmp_path):
    """`host:` ends up inside a URL the daemon sends a request to. A newline or a
    path in that value is how one config line becomes two requests, or a request
    to somewhere the profile never named."""
    for bad in ("192.168.0.5\n", "http://evil.example/", "10.0.0.1 /x", "%00", ""):
        with pytest.raises(ValueError, match="not a plain hostname"):
            load_profile(write(tmp_path,
                               BASE.replace("target: Study speaker", f'host: "{bad}"')))


def test_a_port_that_is_not_a_port_is_rejected(tmp_path):
    for bad in ("0", "-1", "70000"):
        with pytest.raises(ValueError, match="not between 1 and 65535"):
            load_profile(write(tmp_path,
                               BASE.replace("target: Study speaker",
                                            f"target: Study speaker\n    port: {bad}")))


def test_an_offset_longer_than_a_day_is_a_typo(tmp_path):
    """A shift bigger than a day moves the event onto another weekday, so it
    either never fires or fires on the wrong morning."""
    for bad in ("9999", "-2000"):
        with pytest.raises(ValueError, match="within one day"):
            load_profile(write(tmp_path,
                               BASE.replace("at: fajr", f"at: fajr\n    offset_min: {bad}")))


def test_days_says_which_weekdays_it_knows(tmp_path):
    with pytest.raises(ValueError, match="frr"):
        load_profile(write(tmp_path, BASE.replace("at: fajr", "at: fajr\n    days: [frriday]")))
    # `days: fri` is one weekday in YAML, not three letters to be checked
    p = load_profile(write(tmp_path, BASE.replace("at: fajr", "at: fajr\n    days: fri")))
    assert p.events[0].days == ["fri"]


def test_a_file_output_cannot_write_just_anywhere(tmp_path):
    """kind: file is a useful feature and also a way to write into any folder on
    the machine, so the profile names one root and the outputs stay inside it."""
    for bad in ("../../private", "C:/Windows"):
        with pytest.raises(ValueError, match="outside out_dir"):
            load_profile(write(tmp_path, BASE.replace("    host: out", f"    host: {bad}")))

    p = load_profile(write(tmp_path, BASE.replace("    host: out", "    host: copies/tray")
                           .replace("media_dir: media", "media_dir: media\nout_dir: copies")))
    assert p.out_dir.name == "copies"
    assert p.output("spare").host.replace("\\", "/").endswith("copies/tray")


def test_media_names_are_resolved_inside_the_media_dir(tmp_path):
    """Every read of a recording goes through the profile, so this is the one
    place a `../` has to be stopped."""
    p = load_profile(write(tmp_path, BASE))
    assert p.media_path("fajr.mp3").name == "fajr.mp3"
    with pytest.raises(ValueError):
        p.media_path("../../secret.wav")


def test_offsets_written_inside_the_method_block_are_used(tmp_path):
    """People write minute offsets under `method:` because that is where the
    method lives. Reading only the top level meant the numbers were typed, saved,
    shown on the page and never applied to a single time."""
    nested = load_profile(write(tmp_path, BASE.replace("method: {preset: isna}",
                                                       "method: {preset: isna, "
                                                       "adjustments: {maghrib: 10, isha: -3}}")))
    plain = load_profile(write(tmp_path, BASE))
    assert (nested.adjustments.maghrib, nested.adjustments.isha) == (10, -3)
    assert plain.adjustments.maghrib == 0
    assert nested.adjustments.dhuhr == 0


def test_the_same_prayer_adjusted_in_two_places_is_refused(tmp_path):
    """Two answers for one prayer is a coin toss the person should not have to
    settle by remembering which key the code reads."""
    text = BASE.replace("method: {preset: isna}",
                        "method: {preset: isna, adjustments: {maghrib: 5}}") + "adjustments: {maghrib: 20}\n"
    with pytest.raises(ValueError, match="adjusted twice"):
        load_profile(write(tmp_path, text))


def test_an_offset_for_a_name_that_is_not_a_prayer_is_refused(tmp_path):
    """`sunrisee: 5` used to disappear without a trace, and the house waited for a
    nudge that was never going to arrive."""
    with pytest.raises(ValueError, match="not a prayer time"):
        load_profile(write(tmp_path, BASE + "adjustments: {sunrisee: 5}\n"))
    with pytest.raises(ValueError, match="whole minutes"):
        load_profile(write(tmp_path, BASE + "adjustments: {fajr: soon}\n"))

