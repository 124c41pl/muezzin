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


GROUP = """
location: {latitude: 40.7128, longitude: -74.006, timezone: America/New_York}
method: {preset: isna}
media_dir: media
outputs:
  - name: whole-house
    kind: google_cast
    target: Home group
    volume: 0.4
    members:
      Kitchen speaker: 0.5
      Office speaker: 0.4
events:
  - name: fajr-adhan
    at: fajr
    media: [fajr.mp3]
    targets: [whole-house]
"""


def test_a_group_can_be_handed_levels_room_by_room(tmp_path):
    """`members:` is how a speaker group gets a level at all. Measured on a LAN with a
    Google Home group in it, an ask aimed at the group moves a number inside the group
    that the speakers inside it ignore, so the rooms have to be named one at a time. Each
    one is put back where its owner had left it as soon as the call ends, which is why
    writing 0.5 here is not a permanent change to somebody's kitchen."""
    p = load_profile(write(tmp_path, GROUP))
    out = p.output("whole-house")
    assert out.volume == 0.4, "the level for the rooms the profile did not name"
    assert out.members == {"Kitchen speaker": 0.5, "Office speaker": 0.4}


def test_a_room_level_that_is_not_a_number_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="gives the speaker 'Kitchen speaker' the level"):
        load_profile(write(tmp_path, GROUP.replace("Kitchen speaker: 0.5",
                                                   "Kitchen speaker: quite loud")))


def test_a_room_level_outside_the_range_is_rejected(tmp_path):
    """40 is what a phone shows as a percentage and 0.4 is what a speaker is asked for.
    The error says which one to write rather than quietly taking the loud one."""
    with pytest.raises(ValueError, match="number between 0 and 1"):
        load_profile(write(tmp_path, GROUP.replace("Office speaker: 0.4", "Office speaker: 40")))


def test_a_room_level_written_as_a_yes_or_no_is_rejected(tmp_path):
    """`off:` is the word somebody reaches for when they want a room quiet at Fajr, and
    YAML hands it over as a boolean that float() would read as 0.0 - a level taken as
    silence when the line meant a level. The refusal names the trap and the fix."""
    with pytest.raises(ValueError, match="is a yes-or-no, not a number between 0 and 1"):
        load_profile(write(tmp_path, GROUP.replace("Kitchen speaker: 0.5",
                                                   "Kitchen speaker: off")))


def test_a_members_block_that_is_not_rooms_and_levels_is_rejected(tmp_path):
    bad = GROUP.replace("    members:\n      Kitchen speaker: 0.5\n      Office speaker: 0.4\n",
                        "    members: [Kitchen speaker, Office speaker]\n")
    with pytest.raises(ValueError, match="members:` block that is not speaker names with levels"):
        load_profile(write(tmp_path, bad))


def test_a_members_block_on_an_output_with_no_rooms_is_rejected(tmp_path):
    """A LAN box and the computer's own speaker are one thing to play through: a list of
    rooms beside them would never be looked up, so it is refused at load rather than
    ignored until the morning it matters."""
    with pytest.raises(ValueError, match="is kind file and carries"):
        load_profile(write(tmp_path, BASE.replace(
            "  - name: spare\n    kind: file\n    host: out",
            "  - name: spare\n    kind: file\n    host: out\n    members:\n"
            "      Kitchen speaker: 0.5")))


def test_a_prayer_can_name_the_rooms_it_wants_at_its_own_level(tmp_path):
    """The same block one level deeper: what the kitchen is asked for at this prayer and
    at no other. A prayer that names some rooms says nothing about the rest of them, which
    take whatever the output says, so the Fajr that only wakes the kitchen is two lines and
    no opinion about the study. The names are the speakers' own names on the network, the
    same words the sliders on the panel write."""
    text = GROUP.replace("    media: [fajr.mp3]\n",
                         "    media: [fajr.mp3]\n    members:\n      Kitchen speaker: 0.7\n")
    p = load_profile(write(tmp_path, text))
    assert p.events[0].members == {"Kitchen speaker": 0.7}
    assert p.events[0].volume is None, "no blanket number, so the other rooms keep their own"


def test_a_prayer_level_that_is_not_a_number_is_rejected(tmp_path):
    """Read the same way as an output's rooms are, so the same mistake gets the same
    sentence wherever it is written - and the sentence says which prayer, because the one
    that is wrong is the one somebody has to go and fix."""
    text = GROUP.replace("    media: [fajr.mp3]\n",
                         "    media: [fajr.mp3]\n    members:\n      Kitchen speaker: mostly\n")
    with pytest.raises(ValueError,
                       match="event 'fajr-adhan' gives the speaker 'Kitchen speaker' the level"):
        load_profile(write(tmp_path, text))


def test_a_prayer_that_names_speakers_it_never_reaches_is_rejected(tmp_path):
    """A level that cannot be asked is a level that goes unheard until somebody stands in
    the kitchen wondering why it was quiet. This one is refused where it is typed rather
    than at 5 am, and says what the prayer reaches instead, because the fix is usually
    further up the file than the line that tripped."""
    text = GROUP.replace("    members:\n      Kitchen speaker: 0.5\n      Office speaker: 0.4\n", "")
    text = text.replace("    media: [fajr.mp3]\n",
                        "    media: [fajr.mp3]\n    members:\n      Kitchen speaker: 0.7\n")
    text = text.replace("kind: google_cast", "kind: file").replace("target: Home group",
                                                                   "host: out")
    with pytest.raises(ValueError, match="names speakers under `members:`, but nothing it plays"):
        load_profile(write(tmp_path, text))


def test_a_prayer_on_the_computer_s_own_speaker_naming_rooms_is_rejected(tmp_path):
    """`members:` beside a prayer pointed at a computer or a LAN box is the same mistake as
    beside such an output, in a place where it is easier to make: the panel will not offer
    it, so a person typing it deserves to be told which line is wrong."""
    text = BASE.replace("    targets: [study]",
                        "    targets: [parlour]\n    members:\n      Kitchen speaker: 0.7")
    text = text.replace("  - name: study\n    kind: google_cast\n    target: Study speaker",
                        "  - name: parlour\n    kind: pc_speakers")
    with pytest.raises(ValueError, match="names speakers under `members:`"):
        load_profile(write(tmp_path, text))


def test_typo_in_at_is_rejected(tmp_path):
    """`at: fagr` must not become a silent, quiet morning."""
    with pytest.raises(ValueError, match="unknown `at: fagr`"):
        load_profile(write(tmp_path, BASE.replace("at: fajr", "at: fagr")))


def test_event_targeting_a_missing_output_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="do not exist"):
        load_profile(write(tmp_path, BASE.replace("targets: [study]", "targets: [kithcen]")))


def test_event_without_media_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="has nothing to play"):
        load_profile(write(tmp_path, BASE.replace("media: [fajr.mp3]", "media: []")))


def test_an_event_can_ask_the_library_instead_of_naming_files(tmp_path):
    """`random: 2` is the other way to say what an event plays: two recordings drawn from
    the media folder at the moment it fires, so the same event sounds different next week.
    An event that does that has no `media:` list to check against the folder."""
    p = load_profile(write(tmp_path, BASE.replace("media: [fajr.mp3]", "random: 2")))
    assert p.events[0].random == 2
    assert p.events[0].media == []


def test_a_random_ask_outside_the_sane_range_is_rejected(tmp_path):
    """An event that draws 900 recordings has no ending, and nobody means that; the number
    is refused where it is typed rather than at the time it would have started."""
    for ask in ("-1", "900"):
        with pytest.raises(ValueError, match="between 0 and 50"):
            load_profile(write(tmp_path, BASE.replace("media: [fajr.mp3]", f"random: {ask}")))


def test_a_random_ask_that_is_not_a_number_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="not a number of recordings"):
        load_profile(write(tmp_path, BASE.replace("media: [fajr.mp3]", "random: some")))


def test_the_profile_can_hold_recordings_out_of_the_drawing(tmp_path):
    """`library: exclude:` is how something stays out of random picks without deleting it:
    "do not play this by accident" and "I do not have this any more" are different
    intentions, and only one of them is served by deleting a file."""
    p = load_profile(write(tmp_path, BASE + "library:\n  exclude: [english-translation.mp3]\n"))
    assert p.library_exclude == ["english-translation.mp3"]


def test_a_library_block_that_says_something_else_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="holds an exclude: list"):
        load_profile(write(tmp_path, BASE + "library: english-translation.mp3\n"))
    with pytest.raises(ValueError, match="has no excluede"):
        load_profile(write(tmp_path, BASE + "library:\n  excluede: [a.mp3]\n"))


def test_a_library_exclusion_that_is_a_path_is_rejected(tmp_path):
    """The media folder is one level deep, so a name with a slash or a `..` in it is a
    mistake about which file is meant. A rule that quietly never matches anything is worse
    than an error, because the recording keeps playing."""
    for held in ("old/sub.mp3", "../outside.mp3"):
        with pytest.raises(ValueError, match="name of a file in media_dir"):
            load_profile(write(tmp_path, BASE + f"library:\n  exclude: [{held}]\n"))


def test_the_library_is_the_folder_the_profile_points_at(tmp_path):
    """There is no database of recordings and no copy of anything: the folder is the list,
    so what you put in it is what there is to hear, and a file that is not audio is not
    offered anywhere."""
    (tmp_path / "media").mkdir()
    for name in ("dua.mp3", "adhan.wav", "notes.txt", "notes.pdf"):
        (tmp_path / "media" / name).write_bytes(b"x")
    p = load_profile(write(tmp_path, BASE))
    assert p.library() == ["adhan.wav", "dua.mp3"]


def test_the_drawing_reaches_every_recording_but_the_ones_held_back(tmp_path):
    """Two properties, both of which the page will be judged on: a drawing hands back the
    number it was asked for without repeats, and it never hands back a name the profile
    excluded. It is a drawing, so it is also checked for actually varying."""
    (tmp_path / "media").mkdir()
    for name in ("a.mp3", "b.mp3", "c.mp3", "d.mp3", "khutbah.mp3"):
        (tmp_path / "media" / name).write_bytes(b"x")
    p = load_profile(write(tmp_path, BASE + "library:\n  exclude: [khutbah.mp3]\n"))
    seen = set()
    for _ in range(20):
        picked = p.random_picks(2)
        assert len(picked) == 2, "asked for two, got two"
        assert len(set(picked)) == 2, "one drawing does not hand back the same file twice"
        assert "khutbah.mp3" not in picked
        seen.add(frozenset(picked))
    assert len(seen) > 1, "the same two recordings every single time is not a drawing"
    assert set(p.random_picks(99)) == {"a.mp3", "b.mp3", "c.mp3", "d.mp3"}, \
        "asking for more than the folder has plays what the folder has"
    assert p.random_picks(0) == []


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


def test_a_speaker_can_say_how_early_it_needs_to_start(tmp_path):
    """`lead_seconds:` on an output is the head start a slow speaker needs so the
    first note is in the air at the time, not after it. Saying nothing means: take
    the default for this kind of speaker. `0` is a real answer, not an absent one -
    it means exactly on the minute."""
    p = load_profile(write(tmp_path, BASE.replace("target: Study speaker",
                                                  "target: Study speaker\n    lead_seconds: 2")))
    assert p.output("study").lead_seconds == 2.0
    assert p.output("spare").lead_seconds is None


def test_a_lead_that_is_not_a_lead_is_refused(tmp_path):
    """A negative lead means starting late, and an hour of lead is somebody typing
    minutes. Both are refused where they are typed, and the message points at the
    knob that really does move the printed time."""
    for bad in ("-3", "9000"):
        with pytest.raises(ValueError, match="between 0 and"):
            load_profile(write(tmp_path, BASE.replace(
                "target: Study speaker",
                f"target: Study speaker\n    lead_seconds: {bad}")))
    with pytest.raises(ValueError, match="offset_min"):
        load_profile(write(tmp_path, BASE.replace("target: Study speaker",
                                                  "target: Study speaker\n    lead_seconds: 5000")))


def test_the_map_is_on_from_the_first_run_and_one_line_puts_it_back(tmp_path):
    """A feature that only appears once someone has found the right line to write in a
    file is a feature most people never meet, so the map is what a new profile gets. What
    stays available is the way out, in one line: the position is still drawn from the
    numbers, which is why the timetable is the same either way.

    That line is spelled `off`, and YAML reads off, no, yes and on as booleans, so the
    reader has to meet it halfway: the documented spelling, the plain-language one, and
    the boolean each of them arrives as all load. A word that means neither of the two is
    an error rather than a shrug, because the difference between them is whether this
    network went and asked somebody something.
    """
    def variant(spelling):
        return BASE.replace("media_dir: media\n",
                            f"media_dir: media\nmap_tiles: {spelling}\n")

    assert load_profile(write(tmp_path, BASE)).map_tiles == "osm"
    for spelling, want in (("off", "off"), ("no", "off"), ("none", "off"),
                           ("yes", "osm"), ("openstreetmap", "osm"), ("OSM", "osm")):
        assert load_profile(write(tmp_path, variant(spelling))).map_tiles == want, spelling
    p = load_profile(write(tmp_path, variant("off")))
    assert p.params.fajr_angle == 15.0, "turning the map off moved the times"
    for junk in ("local", "maybe"):
        with pytest.raises(ValueError, match="one of off, osm"):
            load_profile(write(tmp_path, variant(junk)))


# ---- the media port, and the second container ---------------------------------

def test_the_media_port_is_the_profiles_own(tmp_path, monkeypatch):
    monkeypatch.delenv("MUEZZIN_HTTP_PORT", raising=False)
    assert load_profile(write(tmp_path, BASE)).http_port == 8010
    p = load_profile(write(tmp_path, BASE + "http_port: 8015\n"))
    assert p.http_port == 8015, "which port this household serves its recordings over is its own business"


def test_the_environment_moves_the_media_port_off_one_already_taken(tmp_path, monkeypatch):
    """A container image carries the profile it is about to read, so on a machine
    that already runs a muezzin there is no file to edit before the bind: the
    operator says the port once, next to the image name, and the second daemon
    starts instead of failing on the address the first one is holding. The variable
    therefore outranks the file, and the file is left alone - the page's own edits
    still round-trip the text it holds."""
    monkeypatch.setenv("MUEZZIN_HTTP_PORT", "8015")
    p = load_profile(write(tmp_path, BASE + "http_port: 8010\n"))
    assert p.http_port == 8015


def test_a_media_port_of_zero_means_take_a_free_one(tmp_path, monkeypatch):
    """The other answer to two servers on one machine, for whoever would rather not
    keep a port ledger at all: the speaker is handed the port that was picked."""
    monkeypatch.setenv("MUEZZIN_HTTP_PORT", "0")
    assert load_profile(write(tmp_path, BASE)).http_port == 0


def test_a_bad_media_port_names_where_the_value_came_from(tmp_path, monkeypatch):
    """The file and the variable are two different places to look, and a message
    that says only "http_port" sends a person to a YAML file that says nothing of
    the kind. A value that is not a number at all gets the same sentence rather
    than a traceback out of int()."""
    with pytest.raises(ValueError, match=r"http_port must be a port number.*eighty"):
        load_profile(write(tmp_path, BASE + "http_port: eighty\n"))
    with pytest.raises(ValueError, match=r"muezzin\.yaml: http_port"):
        load_profile(write(tmp_path, BASE + "http_port: 70000\n"))
    monkeypatch.setenv("MUEZZIN_HTTP_PORT", "eighty")
    with pytest.raises(ValueError, match="MUEZZIN_HTTP_PORT must be a port number"):
        load_profile(write(tmp_path, BASE))
    monkeypatch.setenv("MUEZZIN_HTTP_PORT", "70000")
    with pytest.raises(ValueError, match="MUEZZIN_HTTP_PORT must be between 0 and 65535"):
        load_profile(write(tmp_path, BASE))

