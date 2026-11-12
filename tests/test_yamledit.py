"""Editing a profile without wrecking the parts nobody asked to touch.

The starter profile from `muezzin init` is the fixture, on purpose: if the
helpers cannot handle the exact file the project hands out, they are useless.
Every mutation here is also loaded back with load_profile, because a YAML
indent that is one space off is a crash at 5 am, not a test failure.
"""
import pytest
import yaml

from muezzin.cli import EXAMPLE
from muezzin.config import load_profile
from muezzin import yamledit as ye


def _loads_ok(text, tmp_path):
    path = tmp_path / "muezzin.yaml"
    path.write_text(text, encoding="utf-8")
    return load_profile(path)


def test_a_block_is_found_with_its_own_key_line():
    start, end = ye.find_block(EXAMPLE, "method")
    lines = EXAMPLE.split("\n")
    assert lines[start] == "method:"
    # stops before the blank line and the `adjustments:` key, so the comment
    # block under method is ours but the rest of the file is not
    assert "fajr_angle" in "\n".join(lines[start:end])
    assert "adjustments" not in "\n".join(lines[start:end])


def test_a_missing_block_reports_none_rather_than_guessing():
    assert ye.find_block(EXAMPLE, "no_such_thing") is None


def test_replacing_the_method_block_moves_only_that_block(tmp_path):
    new = ye.set_block(EXAMPLE, "method", ["  preset: qom", "  asr_shadow: standard"])
    assert "preset: qom" in new
    assert "preset: isna" not in new
    # untouched neighbours keep their comments verbatim
    assert "IANA name: DST is handled by the tz database" in new
    assert "# Display only. The page shows a tabular Hijri date" in new
    assert "jumuah" in new
    profile = _loads_ok(new, tmp_path)
    assert profile.params.label.startswith("Qom")


def test_a_single_value_is_changed_in_place(tmp_path):
    new = ye.set_scalar(EXAMPLE, "hijri_offset", 2)
    assert "hijri_offset: 2" in new and "hijri_offset: 0" not in new
    # the comment above it, which explains what the knob is for, is untouched
    assert "# Display only. The page shows a tabular Hijri date" in new
    assert _loads_ok(new, tmp_path).hijri_offset == 2


def test_a_value_only_mentioned_in_a_comment_is_appended_not_written_into():
    new = ye.set_scalar(EXAMPLE, "attribution", "Written by me")
    assert '# attribution: "your name or handle"' in new      # the comment survives
    assert new.rstrip().endswith("attribution: Written by me")


def test_a_whole_section_is_never_clobbered_by_a_single_value():
    with pytest.raises(ValueError) as err:
        ye.set_scalar(EXAMPLE, "method", "qom")
    assert "whole section" in str(err.value)


def test_the_output_entries_are_listed_in_order():
    rows = ye.entries(EXAMPLE, "outputs")
    assert [r["name"] for r in rows] == ["pc", "kitchen", "bedroom-group", "pi-box", "testdir"]
    assert rows[0]["index"] == 0
    assert "kind: pc_speakers" in rows[0]["text"]


def test_a_list_field_reads_in_either_yaml_style():
    flow = "  - name: a\n    targets: [pc, kitchen]"
    block = "  - name: a\n    targets:\n      - pc\n      - kitchen\n"
    assert ye.entry_list(flow, "targets") == ["pc", "kitchen"]
    assert ye.entry_list(block, "targets") == ["pc", "kitchen"]
    assert ye.entry_list(flow, "volume") is None


def test_a_nested_list_is_not_mistaken_for_a_new_entry():
    text = ("events:\n"
            "  - name: one\n    at: fajr\n    media:\n      - a.mp3\n      - b.mp3\n"
            "  - name: two\n    at: isha\n    media: [c.mp3]\n")
    rows = ye.entries(text, "events")
    assert [r["name"] for r in rows] == ["one", "two"]
    assert ye.entry_list(rows[0]["text"], "media") == ["a.mp3", "b.mp3"]


def test_editing_one_entry_leaves_its_neighbours_alone(tmp_path):
    rows = ye.entries(EXAMPLE, "outputs")
    kitchen = next(r for r in rows if r["name"] == "kitchen")
    new = ye.edit_entry(EXAMPLE, "outputs", kitchen["index"],
                        {"volume": 0.35, "target": "Kitchen speaker"})
    assert "volume: 0.35" in new
    assert "target: Kitchen speaker" in new
    # the entry whose line was rewritten lost its trailing comment; the sibling
    # two lines away did not, and that is the honest limit of writing text back
    assert "`muezzin devices` lists names" not in new
    assert "a Google Home speaker GROUP works as one target" in new
    assert "kind: pc_speakers" in new
    _loads_ok(new, tmp_path)


def test_a_field_the_entry_lacks_is_added_to_that_entry(tmp_path):
    rows = ye.entries(EXAMPLE, "events")
    jumuah = next(r for r in rows if r["name"] == "jumuah")
    assert ye.entry_scalar(jumuah["text"], "targets") is None
    new = ye.edit_entry(EXAMPLE, "events", jumuah["index"], {"targets": ["kitchen"]})
    profile = _loads_ok(new, tmp_path)
    event = next(e for e in profile.events if e.name == "jumuah")
    assert event.targets == ["kitchen"]
    assert event.days == ["fri"]          # the Friday restriction survived


def test_a_list_field_written_block_style_is_replaced_whole(tmp_path):
    text = ("outputs:\n"
            "  - name: a\n    kind: file\n    host: out\n"
            "events:\n"
            "  - name: fajr\n    at: fajr\n    targets:\n      - a\n      - b\n    media: [x.mp3]\n"
            "  - name: c\n    kind: file\n    host: out\n")
    new = ye.edit_entry(text, "events", 0, {"targets": ["a"]})
    assert "targets: [a]" in new
    assert "- b" not in new
    assert ye.entries(new, "events")[0]["text"].count("targets") == 1


def test_an_appended_output_lands_inside_its_own_section(tmp_path):
    new = ye.append_entry(EXAMPLE, "outputs",
                          {"name": "bedroom", "kind": "google_cast",
                           "target": "Bedroom group", "volume": 0.4})
    assert "\n  - name: bedroom\n" in new
    rows = ye.entries(new, "outputs")
    assert [r["name"] for r in rows][-1] == "bedroom"
    # appended before the blank line and the `events:` heading, not after them
    assert new.index("name: bedroom") < new.index("events:")
    assert "events:" in new and "jumuah" in new
    profile = _loads_ok(new, tmp_path)
    assert profile.output("bedroom").volume == 0.4


def test_an_appended_entry_keeps_the_files_dash_indent_when_the_file_has_none():
    text = "outputs:\n- name: a\n  kind: file\n  host: out\n"
    new = ye.append_entry(text, "outputs", {"name": "b", "kind": "file", "host": "out"})
    assert "\n- name: b\n" in new
    assert ye.entries(new, "outputs")[-1]["name"] == "b"


def test_a_section_written_from_scratch_is_valid_yaml(tmp_path):
    text = "location:\n  latitude: 1\n  longitude: 2\n  timezone: UTC\n"
    new = ye.append_entry(text, "outputs", {"name": "here", "kind": "file", "host": "out"})
    assert "outputs:\n  - name: here\n" in new
    assert _loads_ok(new, tmp_path).output("here").kind == "file"


def test_deleting_an_output_takes_its_blank_line_too(tmp_path):
    new = ye.delete_entry(EXAMPLE, "outputs", 3)      # pi-box
    assert "pi-box" not in new.split("events:")[0]
    assert "kind: pc_speakers" in new and "kind: file" in new
    assert new.split("events:")[0].count("  - name: ") == 4
    # the events block still names pi-box, which the loader is right to reject
    with pytest.raises(ValueError) as err:
        _loads_ok(new, tmp_path)
    assert "pi-box" in str(err.value)


def test_values_are_written_the_way_a_person_would_type_them():
    assert ye.scalar(0.35) == "0.35"
    assert ye.scalar(5) == "5"
    assert ye.scalar(False) == "false"
    assert ye.scalar("Kitchen speaker") == "Kitchen speaker"
    assert ye.scalar("Bedroom: group") == '"Bedroom: group"'
    assert ye.flow(["a.mp3", "b c.mp3"]) == "[a.mp3, b c.mp3]"
    assert ye.flow(["a,b.mp3"]) == '["a,b.mp3"]'


def test_an_index_that_is_not_there_is_an_error_not_a_silent_no_op():
    with pytest.raises(IndexError):
        ye.edit_entry(EXAMPLE, "outputs", 9, {"volume": 1.0})
    with pytest.raises(IndexError):
        ye.delete_entry(EXAMPLE, "outputs", 9)


def test_only_the_fields_asked_for_are_written_into_a_section(tmp_path):
    # the method block is knobs plus a comment each; re-rendering it would drop
    # the knobs the person set by hand and every word explaining them
    new = ye.set_in_block(EXAMPLE, "method", {"preset": "qom", "asr_shadow": "hanafi"})
    profile = _loads_ok(new, tmp_path)
    assert profile.params.label.startswith("Qom")
    assert profile.asr_shadow == 2.0
    assert "# override a single number to match your community" in new
    # the untouched hints are still hints, not live values
    assert "# fajr_angle: 15.0" in new
    assert ye.block_fields(new, "method") == ["preset", "asr_shadow"]


def test_a_field_that_only_exists_as_a_hint_grows_a_real_line_above_the_hint(tmp_path):
    new = ye.set_in_block(EXAMPLE, "method", {"fajr_angle": 15.0})
    assert ye.block_fields(EXAMPLE, "method") == ["preset", "asr_shadow"]
    assert ye.block_fields(new, "method") == ["preset", "asr_shadow", "fajr_angle"]
    profile = _loads_ok(new, tmp_path)
    assert profile.params.fajr_angle == 15.0
    # the hint survives, so the next reader still learns the knob exists
    assert "# fajr_angle: 15.0" in new
    assert new.index("  fajr_angle: 15.0") < new.index("  # fajr_angle: 15.0")


def test_the_note_on_a_line_survives_changing_that_line(tmp_path):
    new = ye.set_in_block(EXAMPLE, "method", {"asr_shadow": "hanafi"})
    assert "asr_shadow: hanafi" in new
    assert "standard | hanafi" in new
    _loads_ok(new, tmp_path)


def test_a_short_block_written_on_one_line_is_still_editable(tmp_path):
    # plenty of people write `method: {preset: isna}`; inserting lines underneath
    # that would be a syntax error, so the one line gets rewritten instead
    text = ("location: {latitude: 40.7128, longitude: -74.006, timezone: America/New_York}\n"
            "method: {preset: isna, adjustments: {dhuhr: 0}}\n"
            "media_dir: media\n")
    new = ye.set_in_block(text, "method", {"preset": "qom", "asr_shadow": "hanafi"})
    head = [line for line in new.splitlines() if line.startswith("method:")]
    assert len(head) == 1 and head[0].startswith("method: {"), new
    assert "preset: qom" in new and "adjustments: {dhuhr: 0}" in new
    profile = _loads_ok(new, tmp_path)
    assert profile.params.label.startswith("Qom") and profile.asr_shadow == 2.0


def test_a_field_of_a_block_reads_back_in_either_style():
    one_line = ("method: {preset: isna, adjustments: {dhuhr: 0}}\n"
                "media_dir: media\n")
    assert ye.block_value(one_line, "method", "preset") == "isna"
    assert ye.block_value(EXAMPLE, "method", "preset") == "isna"
    assert ye.block_value(EXAMPLE, "method", "fajr_angle") is None, \
        "a commented-out hint is not a value the profile is using"
    nested = ("method:\n  preset: qom\n  adjustments:\n    dhuhr: 5\n"
              "  # fajr_angle: 15.0\nmedia_dir: media\n")
    assert ye.block_fields(nested, "method") == ["preset", "adjustments"], \
        "dhuhr belongs to adjustments, not to method"
    assert ye.block_value(nested, "method", "asr_shadow") is None


def test_a_list_written_on_one_line_is_refused_rather_than_mangled():
    with pytest.raises(ValueError) as exc:
        ye.append_entry("events: []\n", "events",
                        {"name": "fajr-adhan", "at": "fajr", "media": ["a.mp3"]})
    assert "one entry per line" in str(exc.value)


# --- each one below was a real way to lose a value; pinned so they stay lost ---

def test_a_field_nested_inside_an_entry_is_not_the_entry_s_own_field():
    text = ("outputs:\n  - name: bedroom\n    kind: cast\n    limits:\n      volume: 0.2\n"
            "    volume: 0.35\n")
    row = ye.entries(text, "outputs")[0]
    assert str(ye.entry_scalar(row, "volume")) == "0.35"
    new = ye.edit_entry(text, "outputs", 0, {"volume": 0.9})
    assert "volume: 0.9" in new and "volume: 0.2" in new
    assert new.count("volume") == 2, "one write, and the nested field left alone"


def test_a_comment_line_does_not_tell_the_editor_where_the_keys_line_up():
    text = ("outputs:\n  - name: bedroom\n    kind: cast\n"
            "    # volume: 0.9\n    volume: 0.4\n")
    row = ye.entries(text, "outputs")[0]
    assert str(ye.entry_scalar(row, "volume")) == "0.4"


def test_writing_a_field_of_a_block_does_not_reach_into_a_nested_block():
    text = ("method:\n  preset: isna\n  adjustments:\n    dhuhr: 5\n"
            "  # dhuhr: 3\nmedia_dir: media\n")
    new = ye.set_in_block(text, "method", {"dhuhr": 7})
    assert "dhuhr: 7" in new and "dhuhr: 5" in new, "the adjustment keeps its own value"
    assert new.count("dhuhr") == 3, "and the commented hint stays a comment"


def test_a_quoted_field_name_names_the_same_field(tmp_path):
    text = ('location: {latitude: 40.71, longitude: -74.0, timezone: America/New_York}\n'
            'method:\n  "preset": isna\n  asr_shadow: standard\nmedia_dir: media\n')
    new = ye.set_in_block(text, "method", {"preset": "qom"})
    assert new.count("preset") == 1, new
    assert _loads_ok(new, tmp_path).params.label.startswith("Qom")


def test_a_duplicate_top_level_key_is_read_the_way_yaml_reads_it():
    text = "method: {preset: isna}\nmedia_dir: media\nmethod: {preset: qom}\n"
    assert ye.block_value(text, "method", "preset") == "qom"
    start, end = ye.find_block(text, "method")
    assert "qom" in "\n".join(text.split("\n")[start:end])


def test_a_flow_value_holding_a_comma_stays_one_value():
    text = ('events:\n  - name: fajr\n    at: fajr\n'
            '    media: ["fajr.mp3", "adhan, jumuah.mp3"]\n')
    row = ye.entries(text, "events")[0]
    assert ye.entry_list(row, "media") == ["fajr.mp3", "adhan, jumuah.mp3"]


def test_an_output_whose_name_has_a_comma_in_it_can_be_removed():
    text = ('outputs:\n  - name: "Front Hall, Landing"\n    kind: cast\n'
            '    host: 192.168.0.21\n  - name: kitchen\n    kind: cast\n'
            '    host: 192.168.0.23\n')
    assert [ye.entry_scalar(e, "name") for e in ye.entries(text, "outputs")] == \
        ["Front Hall, Landing", "kitchen"]
    new = ye.delete_entry(text, "outputs", 0)
    assert "Front Hall, Landing" not in new and "kitchen" in new


def test_deleting_an_entry_leaves_the_next_one_s_comment_alone():
    text = ("outputs:\n  - name: one\n    kind: cast\n    host: a\n\n"
            "  # jumuah only, keep it short\n  - name: two\n    kind: cast\n    host: b\n")
    new = ye.delete_entry(text, "outputs", 0)
    assert "jumuah only" in new
    assert [ye.entry_scalar(e, "name") for e in ye.entries(new, "outputs")] == ["two"]


def test_a_value_that_would_read_back_as_something_else_is_quoted():
    for word in ("no", "Off", "0755", "0.35", "null"):
        assert ye.scalar(word).startswith('"'), word
        assert yaml.safe_load(f"x: {ye.scalar(word)}") == {"x": word}
    assert ye.scalar("Bedroom") == "Bedroom"
    assert ye.scalar("192.168.0.21") == "192.168.0.21"
