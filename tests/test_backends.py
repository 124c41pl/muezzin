"""What a backend is allowed to claim it did.

The Cast path needs a real speaker to run, but the judgement it makes afterwards
- did the adhan actually reach the end of the file? - is plain arithmetic over
the status the speaker reported, so that judgement is what is tested here. It is
the difference between a log line and a quiet morning. So is the judgement it
makes before sending anything: whether the speaker is awake, tested against a
connection that behaves the way pychromecast behaves when other apps already
hold the speaker open.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from muezzin import backends
from muezzin.backends import BackendError, CastBackend, LanBoxBackend, PcSpeakersBackend
from muezzin.config import OutputConfig


@pytest.fixture(autouse=True)
def _a_fresh_level_book():
    """No test inherits another test's borrowed levels. The book of who is holding which
    speaker's level lives for the life of the process, which is exactly what is wanted at
    5 am and exactly what would make one test's kitchen leak into the next test's."""
    backends.LEVELS.reset()
    yield
    backends.LEVELS.reset()


def study() -> CastBackend:
    return CastBackend(OutputConfig(name="study", kind="google_cast",
                                    target="Study speaker"))


def status(player_state, idle_reason=None):
    return SimpleNamespace(player_state=player_state, idle_reason=idle_reason)


def test_a_clip_the_speaker_played_to_the_end_counts_as_played():
    study()._check_finished("Study speaker", Path("fajr.wav"), status("IDLE", "FINISHED"))


def test_a_dead_stream_is_not_reported_as_a_played_adhan():
    """The receiver says ERROR when it cannot fetch or decode the file. Reporting
    that as success is how a wrong media URL becomes silence at 5 am."""
    with pytest.raises(BackendError, match="could not finish"):
        study()._check_finished("Study speaker", Path("fajr.wav"), status("IDLE", "ERROR"))


def test_a_clip_still_playing_past_the_limit_is_a_failure():
    with pytest.raises(BackendError, match="still playing"):
        study()._check_finished("Study speaker", Path("dua.wav"), status("PLAYING"))


def test_someone_else_taking_over_the_speaker_is_a_warning_not_an_error(caplog):
    """Interrupted means another source grabbed the speaker mid-adhan: worth a
    log line, but nothing went wrong in muezzin and the rest of the profile runs."""
    study()._check_finished("Study speaker", Path("fajr.wav"), status("IDLE", "CANCELINTERRUPTED"))
    assert "stopped fajr.wav early" in caplog.text


def test_a_speaker_that_reported_nothing_is_not_claimed_to_have_finished():
    """A media status of [] is what a Nest sends right after a load; the caller
    has already waited, so it is neither a success claim nor a crash."""
    study()._check_finished("Study speaker", Path("fajr.wav"), None)


@pytest.mark.parametrize("name,expected", [
    ("fajr.wav", "audio/wav"),
    ("fajr.mp3", "audio/mpeg"),
    ("dua.m4a", "audio/mp4"),
    ("dua.opus", "audio/opus"),
    ("dua.flac", "audio/flac"),
    ("strange.qqq", "application/octet-stream"),
])
def test_the_type_handed_to_the_speaker_matches_the_file(name, expected):
    """A Nest decides whether to fetch a URL by the type it is told. Guess wrong
    and the adhan is refused at the speaker, which is the one failure the log
    cannot see from the daemon's side."""
    from muezzin.backends import _content_type
    assert _content_type(Path(name)) == expected


def test_a_speaker_that_never_sends_a_status_fails_cleanly(monkeypatch):
    """A Nest that has gone to sleep still answers mDNS, so a status message is
    the first honest test of whether it is there. Waiting on it forever would stop
    every later speaker in the profile behind it, and a connection left open on
    the way out leaves a receiver thread behind for every retry."""
    import pychromecast

    from muezzin import backends

    calls = []

    class Asleep:
        status = None

        def wait(self, timeout=None):
            calls.append("wait")
            return False                      # what pychromecast returns on a timeout

        def quit_app(self):
            calls.append("quit")

        def disconnect(self):
            calls.append("disconnect")

    monkeypatch.setattr(backends, "find_cast", lambda target, tries=2: (
        device("Study speaker", id="0e5a9d4f-3f2f-4a4b-9e1c-1f3b2c8d9e0a"), []))
    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", lambda info: Asleep())
    b = study()
    b.READY_SECONDS = 0.2
    with pytest.raises(BackendError, match="sent no receiver status"):
        b.play([Path("fajr.wav")])
    assert calls == ["wait", "quit", "disconnect"], "the connection was left lying around"


def test_a_speaker_the_helper_wrote_off_still_gets_the_audio(monkeypatch, tmp_path):
    """The live failure this test exists for.

    Chrome, Spotify and Steam each keep a Cast control channel permanently open to
    every speaker on this LAN, and the receiver accepts our connection and then
    drops it and reconnects. pychromecast's `wait()` reports failure in that
    situation while the speaker is perfectly willing - it answered GET_STATUS,
    took the volume and launched the media app. A daemon that trusted that verdict
    played nothing at 5 am and called a healthy speaker asleep, which is the worst
    kind of bug in this program: the adhan is quietly skipped and the log looks fine.
    """
    import pychromecast

    from muezzin import backends

    sent = []

    class Media:
        def __init__(self):
            self.polls = 0
            self.status = SimpleNamespace(player_state="IDLE", idle_reason=None)

        def play_media(self, url, ctype, stream_type=None):
            sent.append(("media", url, ctype, stream_type))

        def block_until_active(self, timeout=None):
            self.status = SimpleNamespace(player_state="PLAYING", idle_reason=None)

        def update_status(self):
            self.polls += 1
            if self.polls >= 2:               # it plays, then reports it finished
                self.status = SimpleNamespace(player_state="IDLE", idle_reason="FINISHED")

    class Speaker:
        def __init__(self):
            self.status = None
            self.media_controller = Media()

        def wait(self, timeout=None):
            self.status = SimpleNamespace(app_id=None)   # the status arrives anyway
            return False                                  # ... and the lie

        def set_volume(self, level):
            sent.append(("volume", level))

        def quit_app(self):
            sent.append("quit")

        def disconnect(self):
            sent.append("disconnect")

    clip = tmp_path / "fajr.wav"
    clip.write_bytes(b"RIFF")
    monkeypatch.setattr(backends, "find_cast", lambda target, tries=2: (
        device("Study speaker", id="0e5a9d4f-3f2f-4a4b-9e1c-1f3b2c8d9e0a"), []))
    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", lambda info: Speaker())
    b = study()
    b.poll_seconds = 0.01
    b.max_play_seconds = 2.0
    b.media_server = SimpleNamespace(url_for=lambda p, peer=None: "http://192.0.2.10:8010/" + p.name)
    b.play([clip])
    assert [c[0] for c in sent[:2]] == ["volume", "media"], sent
    assert sent[0][1] == backends.DEFAULT_CAST_VOLUME, "a speaker is the one thing a level applies to"
    assert sent[1][1:] == ("http://192.0.2.10:8010/fajr.wav", "audio/wav", "BUFFERED"), sent
    assert "quit" in sent and "disconnect" in sent, "the connection was left lying around"


def test_a_speaker_that_never_says_playing_is_reported_as_unproven(caplog):
    """A four-second chime can be over before the first poll lands, so the receiver
    never shows PLAYING to us. Claiming it played would be a guess; claiming it
    failed would be wrong just as often. Say which of the two is unknown."""
    study()._check_finished("Study speaker", Path("fajr.wav"), status("IDLE"), started=False)
    assert "never reported playing fajr.wav" in caplog.text
    assert "did not finish" not in caplog.text


def test_a_silent_speaker_is_told_which_address_it_was_handed(caplog):
    """The hardest silence to read is the one where every part of this machine is
    happy: the speaker was found, connected to, given the file and left alone. The
    one fact that decides whether a room made a noise is the address in the URL it
    was handed, so the line has to carry it - a person reading the log at 5 am is
    going to ask the speaker's network about that address and nothing else."""
    b = study()
    b._handed = ("Study speaker", "http://100.64.100.6:8010/fajr.wav")
    b._check_finished("Study speaker", Path("fajr.wav"), status("IDLE"), started=False)
    assert "told to fetch http://100.64.100.6:8010/fajr.wav" in caplog.text, caplog.text


def test_a_speaker_is_handed_an_address_it_can_reach(tmp_path, monkeypatch):
    """Measured on a household machine, not a fixture: the daemon named the speaker,
    set four rooms' levels, launched the media app, and the house stayed silent while
    the log read like a delivered adhan. The URL had been http://100.64.100.6:8010 -
    the address of a mesh VPN adapter, because that adapter owns the default route
    and the old question was "which address do I reach the internet from". A Google
    Home on the wifi has no route into that network. The same trick, asked about the
    speaker instead of the internet, answers the question that matters - and a device
    this machine cannot route to at all still gets the old, general answer."""
    from muezzin import media as media_module

    asked = []

    class FakeSocket:
        """The UDP trick, played back: connecting a datagram socket sends nothing,
        it only asks the routing table which source address it would answer from."""
        def connect(self, addr):
            asked.append(addr[0])
            if addr[0] == "192.0.2.7":
                raise OSError("no route to that network from here")
            self.source = "192.168.0.8" if addr[0].startswith("192.168.") else "100.64.100.6"

        def getsockname(self):
            return (self.source, 0)

        def close(self):
            pass

    monkeypatch.setattr(backends.socket, "socket", lambda family, kind: FakeSocket())
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    clip = media_dir / "adhan.mp3"
    clip.write_bytes(b"ID3")
    server = media_module.MediaServer(media_dir, port=8010)

    assert server.url_for(clip, "192.168.0.44").startswith("http://192.168.0.8:8010/"), \
        "a speaker on the wifi is given the address that is on the wifi"
    assert asked == ["192.168.0.44"], "asked about the device, not about the internet"
    assert server.url_for(clip, "192.0.2.7").startswith("http://100.64.100.6:8010/"), \
        "no route to a device is not a reason to hand it nothing at all"
    assert asked[-1] == "8.8.8.8", "the fallback is the question this code always asked"
    assert server.url_for(clip).startswith("http://100.64.100.6:8010/"), \
        "with no device in mind there is nothing newer to ask"



def test_a_computer_output_is_never_handed_a_level(tmp_path, monkeypatch, caplog):
    """pc_speakers is this machine's own speaker, so neither the profile's `volume:`
    nor an event's override may reach it. And a profile that wrote the knob anyway
    is told so once, when the output is built, rather than at the 5 am it would
    otherwise have surfaced."""
    seen = []
    monkeypatch.setattr(backends.localplay, "play_file",
                        lambda path, player=None: seen.append(path.name))
    with caplog.at_level("WARNING"):
        b = PcSpeakersBackend(OutputConfig(name="parlour", kind="pc_speakers", volume=0.2))
    assert "parlour" in caplog.text and "volume" in caplog.text and "0.2" in caplog.text
    clip = tmp_path / "fajr.mp3"
    clip.write_bytes(b"ID3")
    b.play([clip], 0.9)          # an event's level, aimed at a computer: it goes to the speaker as-is
    assert seen == ["fajr.mp3"], "playback still happens, at the machine's own level"


def test_the_level_a_speaker_is_asked_for_is_the_one_the_profile_wrote():
    """The web page now writes `volume:` for a speaker, on the promise that the test you
    can hear comes out at the level you set rather than at whatever the room happened to
    be left at. That promise is this one arithmetic, so it is pinned here: the level the
    output carries is the level the speaker is asked for when the play call carries none
    of its own, which is exactly what a test from the page sends. An event that asked for
    its own level still wins, because that is the more recent ask; and a written `0` has
    to mean silence rather than the default, because a person who wrote 0 meant it."""
    def asked(volume, per_call):
        return CastBackend(OutputConfig(name="nest", kind="google_cast",
                                        target="Nest Mini", volume=volume))._call_level("Nest Mini", per_call, None)

    assert asked(0.35, None) == 0.35
    assert asked(0.35, 0.8) == 0.8, "an event's own `volume:` out-ranks the speaker's"
    assert asked(0.0, None) == 0.0, "the default must not talk a written silence out of it"
    assert asked(None, None) == backends.DEFAULT_CAST_VOLUME, \
        "nothing written is the default, and saying so is what the page shows"
    assert asked(40, None) == 1.0, "a level that left the page is clamped on the way to the speaker"


def test_which_of_the_four_written_levels_one_speaker_is_asked_for():
    """Four numbers in a profile can answer "what should the kitchen be asked for right
    now", and the page is going to show one of them before the prayer ever runs, so the
    order is pinned as arithmetic instead of being whatever branch a play test happened
    to reach. Most specific about this speaker and this call first: this prayer's line for
    this room, this prayer's number for every room it plays through, this room's standing
    line under the output, the output's standing number, and only if none of them was
    written, the default. The middle pair is the part worth arguing about, and it is
    deliberate: "the whole house at 70% for this Eid" is about tonight, and a line that
    applies to every call of the year is the less specific of the two."""
    def asked(name, volume, members, standing_members, standing):
        return CastBackend(OutputConfig(name="whole-house", kind="google_cast",
                                        target="Home group", volume=standing,
                                        members=standing_members))._call_level(
            name, volume, members)

    assert asked("Kitchen speaker", None, {}, {"Kitchen speaker": 0.3}, 0.2) == 0.3
    assert asked("Kitchen speaker", 0.5, {}, {"Kitchen speaker": 0.3}, 0.2) == 0.5, \
        "what this call asked of every room out-ranks a line written for every call"
    assert asked("Kitchen speaker", None, {"Kitchen speaker": 0.9}, {"Kitchen speaker": 0.3},
                 0.2) == 0.9, "the room's own line under this prayer beats its standing line"
    assert asked("Hall speaker", None, {"Kitchen speaker": 0.9}, {"Hall speaker": 0.4},
                 0.2) == 0.4, "a room this prayer said nothing about falls back to its standing line"
    assert asked("Hall speaker", None, {"Kitchen speaker": 0.9}, {}, 0.2) == 0.2
    assert asked("Hall speaker", None, {}, {}, None) == backends.DEFAULT_CAST_VOLUME
    assert asked("Kitchen speaker", 0.0, {}, {}, 0.6) == 0.0, "a written 0 means silence"
    assert asked("Kitchen speaker", None, {"Kitchen speaker": 40}, {}, 0.6) == 1.0, \
        "a level that left the page is clamped here too"


def test_a_group_whose_speakers_stay_silent_is_said_out_loud_to_have_no_level_of_its_own(
        tmp_path, monkeypatch, caplog):
    """Measured on a LAN with a Google Home group in it: an ask aimed at the group moves a
    number inside the group's receiver that the speakers inside it ignore, and that number
    drifts on its own a minute later. So the level goes to each speaker over a connection
    of its own instead - and when not one speaker answers the ask about which groups it
    belongs to, the written level has nowhere to go. What would be a lie is a log that
    stayed quiet there and let somebody read `volume: 0.4` and believe four rooms were
    asked for 40%. Said once per output: this is not news five times a day."""
    import pychromecast

    clip = tmp_path / "fajr.wav"
    clip.write_bytes(b"RIFF")
    monkeypatch.setattr(backends, "find_cast", lambda target, tries=2: (
        device("Whole-house group", group=True,
               id="0e5a9d4f-3f2f-4a4b-9e1c-1f3b2c8d9e0a"), []))

    def walked_out(info):
        raise OSError("the group's receiver closed the door")

    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", walked_out)
    b = CastBackend(OutputConfig(name="whole-house", kind="google_cast",
                                 target="Whole-house group", volume=0.4))
    with caplog.at_level("WARNING"):
        for _ in range(2):
            with pytest.raises(OSError):
                b.play([clip])
    assert "whole-house" in caplog.text and "0.4" in caplog.text
    assert "is a speaker group" in caplog.text
    assert caplog.text.count("is a speaker group") == 1, "once, not once per event"


GROUP_UUID = "0e5a9d4f-3f2f-4a4b-9e1c-1f3b2c8d9e0a"
KITCHEN_UUID = "11111111-1111-1111-1111-111111111111"
OFFICE_UUID = "22222222-2222-2222-2222-222222222222"
HALL_UUID = "33333333-3333-3333-3333-333333333333"


class Room:
    """One physical speaker inside a group, answering a connection of its own.

    Measured on this LAN: every speaker in a group advertises its own `_googlecast`
    record and answers a connection to it with exactly the level the group's status
    reports for it, which is what makes a level per room possible at all. This fake
    answers the same way, and keeps every level it was asked for in order, so a test
    can read back what the room was put through.
    """
    def __init__(self, name, uuid, level):
        self.name = name
        self.uuid = uuid
        self.address = "192.0.2." + uuid[:2]     # rooms are told apart by address
        self.status = SimpleNamespace(app_id=None, volume_level=level)
        self.levels = []
        self.open = False
        # A test that cares about *when* a room's level moved - which poll of the file it
        # landed under - hangs a callable here; see the buffering test below.
        self.witness = None

    def record(self):
        return device(self.name, id=self.uuid, address=self.address)

    def wait(self, timeout=None):
        self.open = True
        return True

    def set_volume(self, level):
        self.levels.append(level)
        if self.witness is not None:
            self.witness(self.name, level)
        self.status.volume_level = level

    def disconnect(self):
        self.open = False


class Clip:
    """A media controller that plays a file and reports it, or one that refuses the file.

    `stutter` is a list of states to report, one per poll, for the situation a real Google
    Home group gets into by itself: it says BUFFERING in the middle of a recitation while
    its members fall back into step, and what muezzin makes of that decides whether the
    rooms stay at the levels the profile asked for until the file is really over or get put
    back a second and a half into it. `finished_at` records the poll on which the fake first
    said the file was over, so a test can ask whether the watch was still paying attention
    then or had already given up on it.
    """
    def __init__(self, breaks=False, stutter=None):
        self.polls = 0
        self.breaks = breaks
        self.stutter = list(stutter or [])
        self.finished_at = None
        self.during = None
        self.stopped = False
        self.status = SimpleNamespace(player_state="IDLE", idle_reason=None)

    def play_media(self, url, ctype, stream_type=None):
        if self.breaks:
            import pychromecast
            raise pychromecast.error.PyChromecastError("the receiver closed the door")

    def stop(self):
        self.stopped = True

    def block_until_active(self, timeout=None):
        self.status = SimpleNamespace(player_state="PLAYING", idle_reason=None)

    def update_status(self):
        self.polls += 1
        if self.polls == 1 and self.during is not None:
            self.during()           # what the house does while the adhan is playing
        if self.stutter:
            state, reason = self.stutter.pop(0)
            self.status = SimpleNamespace(player_state=state, idle_reason=reason)
        elif self.polls >= 2:
            self.status = SimpleNamespace(player_state="IDLE", idle_reason="FINISHED")
        if getattr(self.status, "idle_reason", None) == "FINISHED" and self.finished_at is None:
            self.finished_at = self.polls


class GroupReceiver:
    """The group's own receiver: the connection the sound goes through.

    `levels` is kept so a test can see whether muezzin asked this thing for a level,
    which on a real group is an ask that changes nothing anybody can hear - and where it
    is asked at all, as a fallback, the number it moves is a number the Google Home app
    shows, so the fake moves it and gets it back.
    """
    def __init__(self, level=0.1, breaks=False, stutter=None):
        self.status = SimpleNamespace(app_id=None, volume_level=level)
        self.levels = []
        self.closed = False
        self.media_controller = Clip(breaks, stutter)

    def wait(self, timeout=None):
        return True

    def set_volume(self, level):
        self.levels.append(level)
        self.status.volume_level = level

    def quit_app(self):
        pass

    def disconnect(self):
        self.closed = True


def cast_group(monkeypatch, rooms, group=None, members=None, volume=0.4, claims=None):
    """A group play wired to fakes: the group, the speakers in it, and their claims.

    `claims` is what each speaker's setup endpoint says about which groups it belongs
    to, which on a real LAN is the only thing that names a group's members at all. By
    default every room in the fixture claims the group.
    """
    import pychromecast

    monkeypatch.setattr(backends, "find_cast", lambda target, tries=2: (
        device("Home group", group=True, id=GROUP_UUID), [r.record() for r in rooms]))
    if claims is None:
        bare = GROUP_UUID.replace("-", "")
        claims = {r.name: {bare} for r in rooms}
    monkeypatch.setattr(backends, "group_claims",
                        lambda host, timeout=6.0: claims.get(host_to_room(rooms).get(host)))
    group = group or GroupReceiver()
    targets = {"Home group": group}
    targets.update({r.name: r for r in rooms})
    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", lambda info, *a, **k: targets[info[4]])
    b = CastBackend(OutputConfig(name="whole-house", kind="google_cast", target="Home group",
                                 volume=volume, members=members or {}))
    b.poll_seconds = 0.01
    b.max_play_seconds = 2.0
    b.media_server = SimpleNamespace(url_for=lambda p, peer=None: "http://192.0.2.10:8010/" + p.name)
    b.group_receiver = group          # so a test can put something in the middle of the play
    return b


def host_to_room(rooms) -> dict:
    """Which room a claimed address belongs to, since the fake answers by address."""
    return {r.record()["address"]: r.name for r in rooms}


def clip(tmp_path, name="adhan.wav"):
    path = tmp_path / name
    path.write_bytes(b"RIFF")
    return path


def test_a_group_gets_its_level_room_by_room_and_the_rooms_go_back(tmp_path, monkeypatch, caplog):
    """The whole promise in one test, and the part that makes it honest is the second
    half of it. A group has no level of its own that anybody hears, so what the profile
    wrote goes to each speaker inside it over a connection of that speaker's own; and
    when the call is over, each room is put back where the Google Home app had left it,
    which is what lets a profile say "0.4 for the adhan" without redecorating the house
    for the rest of the day. The rooms asked are the ones that claim the group's uuid,
    not the ones whose names happen to be nearby."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    office = Room("Office speaker", OFFICE_UUID, 0.8)
    hall = Room("Hall speaker", HALL_UUID, 0.6)
    group = GroupReceiver()
    bare = GROUP_UUID.replace("-", "")
    b = cast_group(monkeypatch, [kitchen, office, hall], group=group,
                   claims={kitchen.name: {bare}, office.name: {bare}, hall.name: set()})
    with caplog.at_level("INFO"):
        b.play([clip(tmp_path)])
    assert kitchen.levels == [0.4, 0.1], "asked for the call, then back where it was"
    assert office.levels == [0.4, 0.8], "a loud room is turned down for the call and back up after"
    assert hall.levels == [], "a speaker that is not in this group is not touched at all"
    assert group.levels == [], "the group's own number is not asked for, because nobody hears it"
    assert not kitchen.open and not office.open, "the room connections are let go of"
    assert group.closed, "and so is the group's"
    assert "Kitchen speaker from 0.1 to 0.4" in caplog.text
    assert "goes back to the level it was at" in caplog.text, "the log says the debt was paid"


def test_a_group_that_buffers_in_the_middle_of_a_file_is_not_told_to_stop(tmp_path, monkeypatch, caplog):
    """The other half of the promise above: the rooms go back when the file is over, not
    when the receiver first says something other than PLAYING.

    Measured on this LAN, a Google Home group says BUFFERING in the middle of a file, not
    only at its start - that is what its members do while they fall back into step, and
    the rooms are still pouring out the recitation the whole time. One poll of that used to
    end the watch, which quit the receiver a second and a half into a five minute asr, put
    every room's level back underneath the sound, and logged nothing at all, because a
    buffering state is no error to report. The recitation carried on regardless, because the
    quit goes to the group's receiver while its members carry the sound, which is why it
    took a log line to notice at all: the harm was the levels going back under a call that
    was still playing, and a watch that had stopped watching. So a state that is not playing
    has to outlast a poll of its own before muezzin believes it, and a file that comes back
    to PLAYING gets the rest of its minutes."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.6)
    office = Room("Office speaker", OFFICE_UUID, 0.3)
    group = GroupReceiver(stutter=[("PLAYING", None), ("BUFFERING", None), ("BUFFERING", None),
                                    ("PLAYING", None), ("IDLE", "FINISHED")])
    b = cast_group(monkeypatch, [kitchen, office], group=group, volume=0.4)
    # Which poll of the file each level move landed under. The harm in the old behaviour
    # was not that the rooms were put back, but that they were put back while the adhan
    # was still coming out of them.
    moved = []
    for room in kitchen, office:
        room.witness = lambda name, level: moved.append((name, level, group.media_controller.polls))
    with caplog.at_level("WARNING"):
        b.play([clip(tmp_path)])
    mc = group.media_controller
    assert mc.finished_at, "the group was never left alone long enough to say the file was over"
    back = [(name, level, when) for name, level, when in moved if level != 0.4]
    assert sorted(level for _, level, _ in back) == [0.3, 0.6], "each room back where the app left it"
    assert all(when >= mc.finished_at for _, _, when in back), \
        f"the rooms went back at polls {[when for _, _, when in back]}, but the group only " \
        f"said it was done at poll {mc.finished_at}"
    assert not caplog.records, "and a stutter is nothing to warn about, so the log stays quiet"


def test_a_stream_the_network_dropped_is_given_up_on_and_not_waited_for(tmp_path, monkeypatch, caplog):
    """The other side of the rule above, and the reason the watch is allowed to wait at all.

    A group that buffers for half a second is a member falling out of step. A group that
    says BUFFERING and never says it is playing again is a stream the network dropped, and
    sitting in front of that until the 30-minute ceiling would leave every room in the house
    at a borrowed level and the rest of the output's recordings queued behind it, while the
    speaker has made no sound for twenty minutes. So a file that begins and then goes quiet
    gets STALL_SECONDS of it, and after that the rooms go back and the log says what
    happened."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.6)
    group = GroupReceiver(stutter=[("PLAYING", None)] + [("BUFFERING", None)] * 40)
    b = cast_group(monkeypatch, [kitchen], group=group, volume=0.4)
    b.STALL_SECONDS = 0.05        # the same rule, on a clock a test can wait on
    with caplog.at_level("WARNING"):
        b.play([clip(tmp_path)])
    assert kitchen.levels == [0.4, 0.6], "the room is back where its owner left it, not held"
    assert group.media_controller.finished_at is None, "the watch gave up; it was never told"
    assert "went quiet in the middle of adhan.wav" in caplog.text, "and the log says so"


def test_a_speaker_left_paused_through_a_file_does_not_count_as_having_played_it(caplog):
    """Two polls of PAUSED with no reason given is a file that began and then sat still,
    not a file that finished. The watch ends there, and the verdict has to say so out loud
    rather than leave the log reading as though the call had been delivered whole."""
    study()._check_finished("Study speaker", Path("adhan.wav"), status("PAUSED"), started=True)
    assert "was left paused through adhan.wav and did not finish it" in caplog.text


def test_a_stop_ask_is_honored_while_the_group_says_buffering(tmp_path, monkeypatch, caplog):
    """Stop means stop, whatever the player is saying. A BUFFERING state is a reason to
    keep the watch alive while a file has begun - but a person who pressed Stop has already
    had the speaker told, and a watch that only takes the ask in states outside BUFFERING
    would sit out the whole stall clock with the borrowed levels held and this output's
    other recordings queued behind a file nobody wants any more."""
    from muezzin import localplay

    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.6)
    group = GroupReceiver(stutter=[("PLAYING", None)] + [("BUFFERING", None)] * 200)
    b = cast_group(monkeypatch, [kitchen], group=group, volume=0.4)
    b.STALL_SECONDS = 5.0          # the stall clock is not what should end this watch
    group.media_controller.during = b.stop     # the ask, arriving mid-file
    with pytest.raises(localplay.Stopped), caplog.at_level("WARNING"):
        b.play([clip(tmp_path)])
    mc = group.media_controller
    assert mc.stopped, "the speaker was told to go quiet"
    assert mc.polls < 20, f"and the watch came away at poll {mc.polls}, not at the end of its window"
    assert kitchen.levels == [0.4, 0.6], "the borrowed level went back with the call"
    assert "went quiet in the middle" not in caplog.text, "a stop asked is not a speaker that fell silent"


def test_a_file_that_only_ever_says_buffering_gives_up_on_the_start_clock(tmp_path, monkeypatch, caplog):
    """BUFFERING is an allowance for a file that began and fell silent, not a head start
    for one that never began. A receiver that says BUFFERING from the first poll and never
    says PLAYING was given START_SECONDS before this branch of the watch gave it
    STALL_SECONDS instead - two minutes a file, over a speaker that never made a sound."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.6)
    group = GroupReceiver(stutter=[("BUFFERING", None)] * 200)
    b = cast_group(monkeypatch, [kitchen], group=group, volume=0.4)
    b.START_SECONDS = 0.05         # the start clock, shrunk for the test, as the others are
    b.STALL_SECONDS = 5.0
    with caplog.at_level("WARNING"):
        b.play([clip(tmp_path)])
    mc = group.media_controller
    assert mc.polls < 20, f"the watch gave up at poll {mc.polls}, on the start clock"
    assert kitchen.levels == [0.4, 0.6], "the room is back where its owner left it"
    assert "never reported playing adhan.wav" in caplog.text, "and the log says it never began"
    assert "went quiet in the middle" not in caplog.text, "a file that never began did not go quiet mid-way"


def test_every_room_gets_asked_even_when_the_house_has_nine(tmp_path, monkeypatch):
    """The asks all go out at once, and the deadline is what bounds the round - a cap on
    the asking threads must not be the thing that decides which rooms get to answer. A
    household of nine Minis and a capped pool of eight left the ninth room permanently
    indistinguishable from one that was asked and said nothing: never borrowed, never
    named, its level quietly never asked for."""
    rooms = [Room(f"Speaker {i}", "%x%x222222-2222-2222-2222-222222222222" % (i, i), 0.1)
             for i in range(9)]
    b = cast_group(monkeypatch, rooms)
    b.play([clip(tmp_path)])
    for room in rooms:
        assert room.levels == [0.4, 0.1], f"{room.name} was asked and given back, like the others"


def test_a_room_that_named_another_group_gets_no_level_written_on_it(tmp_path, monkeypatch, caplog):
    """A room that answers and says it is inside some other group is that other group's
    speaker: this call cannot make a sound through it, and a `members:` line that names it
    - usually a rename in the Home app, or a typo one room off - must not redecorate it for
    the length of the adhan. The answer that the network gave outranks the name written in
    the profile, and the log says which of the two it sided with."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    hall = Room("Hall speaker", HALL_UUID, 0.9)
    bare = GROUP_UUID.replace("-", "")
    b = cast_group(monkeypatch, [kitchen, hall],
                   claims={kitchen.name: {bare}, hall.name: {"99" + "9" * 30}},
                   members={"Hall speaker": 0.5})
    with caplog.at_level("WARNING"):
        b.play([clip(tmp_path)])
    assert hall.levels == [], "hall answered another group: nothing was written on it, in either direction"
    assert kitchen.levels == [0.4, 0.1], "the room that claimed this group still gets its call"
    assert "Hall speaker" in caplog.text and "not inside" in caplog.text and "left alone" in caplog.text


def test_the_group_asked_because_no_room_answered_gives_its_own_number_back(tmp_path, monkeypatch, caplog):
    """The fallback used to be the one place a level was simply left behind. With no room
    answering, the only address there is is the group's own receiver, so the ask went to it
    - and stayed there. Measured on this LAN that ask does move the group's number, and the
    Google Home app shows that number even though no speaker behind it obeys it, so it is
    borrowed and paid back like a room's: the call asked, and the house is left showing
    what it showed before. The log still says out loud that no room heard the level."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    group = GroupReceiver(level=0.1)
    b = cast_group(monkeypatch, [kitchen], group=group, claims={})   # nobody claims the group
    with caplog.at_level("WARNING"):
        b.play([clip(tmp_path)])
    assert group.levels == [0.4, 0.1], "the fallback asked for the call and gave the number back"
    assert kitchen.levels == [], "a speaker that is not in this group is not touched"
    assert group.closed, "and the connection it was asked over is let go of"
    assert "is a speaker group" in caplog.text, "and the log says the level reached no room"


def test_the_group_asked_because_no_room_answered_leaves_a_number_that_moved_on_its_own(
        tmp_path, monkeypatch, caplog):
    """Measured: a group's own number drifts by itself a minute after anything happens to
    it. So the hand-back uses the rooms' rule and checks where the number is now - a
    figure that moved on its own, or by a person in the app, is left where it is rather
    than rolled back over."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    group = GroupReceiver(level=0.1)
    b = cast_group(monkeypatch, [kitchen], group=group, claims={})
    b.group_receiver.media_controller.during = lambda: group.set_volume(0.7)
    with caplog.at_level("INFO"):
        b.play([clip(tmp_path)])
    assert group.levels == [0.4, 0.7], "asked for the call, then the newer number, and no third move"
    assert "Home group was moved to 0.7" in caplog.text


def test_each_room_of_a_group_can_be_handed_its_own_level(tmp_path, monkeypatch):
    """Why `members:` exists: one call at 50% in the kitchen and 40% in the office while
    both rooms were left by their owner at 10% and 80%, and both back at 10% and 80% the
    second the call ends. A level for the length of a prayer, and then no trace of it.
    The rooms nobody named are asked as well, at the number written for the output: naming
    the kitchen is a decision about the kitchen, not a decision to let the hall play this
    call at whatever the Google Home app happened to leave it at.
    """
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    office = Room("Office speaker", OFFICE_UUID, 0.8)
    hall = Room("Hall speaker", HALL_UUID, 0.6)
    b = cast_group(monkeypatch, [kitchen, office, hall], volume=0.2,
                   members={"Kitchen speaker": 0.5, "Office speaker": 0.4})
    b.play([clip(tmp_path)])
    assert kitchen.levels == [0.5, 0.1]
    assert office.levels == [0.4, 0.8]
    assert hall.levels == [0.2, 0.6], "the room nobody named follows the group's own number"


def test_rooms_named_in_the_profile_are_asked_even_when_the_speakers_will_not_say(
        tmp_path, monkeypatch, caplog):
    """Asking who is inside a group is how a room nobody named gets found. A speaker that
    will not answer that question is not a reason to leave the rooms that were named by
    hand at the wrong level, so those are matched from what the network already announced
    and the call goes out with them. What is lost is only the rooms muezzin could not
    find out about, and that is said in the log rather than kept quiet."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    office = Room("Office speaker", OFFICE_UUID, 0.8)

    def will_not_say(host, timeout=6.0):
        raise OSError("the speaker would not say which groups it belongs to")

    b = cast_group(monkeypatch, [kitchen, office],
                   members={"Kitchen speaker": 0.5, "Office speaker": 0.4})
    monkeypatch.setattr(backends, "group_claims", will_not_say)
    b.play([clip(tmp_path)])
    assert kitchen.levels == [0.5, 0.1]
    assert office.levels == [0.4, 0.8]
    assert "would not say who is inside" in caplog.text, \
        "and the silence is named per room: a level that went out on trust says so out loud"


def test_a_prayer_can_ask_the_kitchen_for_more_than_the_study(tmp_path, monkeypatch):
    """One level deeper than `members:`: the same group, and this one prayer wants the
    kitchen at 60% while every other call keeps the house's numbers. What the prayer says
    nothing about is what the house already says - which is why the happy Fajr that only
    wakes the kitchen has two lines written under it and no opinion about the study.
    """
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    office = Room("Office speaker", OFFICE_UUID, 0.8)
    hall = Room("Hall speaker", HALL_UUID, 0.6)
    b = cast_group(monkeypatch, [kitchen, office, hall], volume=0.2,
                   members={"Office speaker": 0.3})
    b.play([clip(tmp_path)], None, {"Kitchen speaker": 0.6})
    assert kitchen.levels == [0.6, 0.1], "the kitchen, for this prayer alone"
    assert office.levels == [0.3, 0.8], "a room this prayer said nothing about keeps its standing line"
    assert hall.levels == [0.2, 0.6], "and so does one nobody ever wrote about"


def test_a_prayer_s_own_number_covers_the_rooms_it_never_named(tmp_path, monkeypatch):
    """The one ordering worth writing down, because two numbers in a profile can look like
    they both apply to the office: `volume: 0.5` on a prayer is this call, every room it
    plays through, and a room's line under the output is every call of the year. The
    promise about tonight is the more specific one, so tonight the office is asked for 50%
    and not the 30% written beside it - and the hall, which nobody has ever named, is asked
    for 50% too, because a number for every room means every room."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    office = Room("Office speaker", OFFICE_UUID, 0.8)
    hall = Room("Hall speaker", HALL_UUID, 0.6)
    b = cast_group(monkeypatch, [kitchen, office, hall], volume=0.2,
                   members={"Office speaker": 0.3})
    b.play([clip(tmp_path)], 0.5, {})
    assert kitchen.levels == [0.5, 0.1]
    assert office.levels == [0.5, 0.8], "this call out-ranks a line written for every call"
    assert hall.levels == [0.5, 0.6], "a blanket number is a blanket number"


def test_a_prayer_can_name_the_one_speaker_it_plays_through(tmp_path, monkeypatch):
    """A house with one speaker on the network and three prayers pointed at it has the same
    wish in a smaller shape: the chime before Fajr quiet, the adhan itself loud. That is
    what an event's `members:` does for a single-speaker output, named the way the speaker
    is named on the network, which is the same word `target:` carries. Nothing is borrowed
    and handed back here: a single speaker's level is the level it stays at, and the
    prayer's number is the one for tonight only in the sense that every other morning asks
    for the output's number instead.
    """
    import pychromecast

    from muezzin import backends

    asked = []

    class Media:
        def __init__(self):
            self.polls = 0
            self.status = SimpleNamespace(player_state="IDLE", idle_reason=None)

        def play_media(self, url, ctype, stream_type=None):
            asked.append("media")

        def block_until_active(self, timeout=None):
            self.status = SimpleNamespace(player_state="PLAYING", idle_reason=None)

        def update_status(self):
            self.polls += 1
            if self.polls >= 2:
                self.status = SimpleNamespace(player_state="IDLE", idle_reason="FINISHED")

    class Speaker:
        def __init__(self):
            self.media_controller = Media()

        def wait(self, timeout=None):
            self.status = SimpleNamespace(app_id=None, volume_level=0.2)
            return True

        def set_volume(self, level):
            asked.append(level)

        def quit_app(self):
            pass

        def disconnect(self):
            pass

    monkeypatch.setattr(backends, "find_cast", lambda target, tries=2: (
        device("Study speaker", id="0e5a9d4f-3f2f-4a4b-9e1c-1f3b2c8d9e0a"), []))
    monkeypatch.setattr(pychromecast, "get_chromecast_from_host", lambda info, *a, **k: Speaker())
    b = CastBackend(OutputConfig(name="study", kind="google_cast", target="Study speaker",
                                 volume=0.2))
    b.poll_seconds = 0.01
    b.max_play_seconds = 2.0
    b.media_server = SimpleNamespace(url_for=lambda p, peer=None: "http://192.0.2.10:8010/" + p.name)
    b.play([clip(tmp_path)], None, {"Study speaker": 0.75})
    assert asked[0] == 0.75, "the prayer's number is the number this speaker is asked for"
    assert asked[1] == "media", "and the adhan still goes out"
    b.play([clip(tmp_path)])
    assert asked[-2] == 0.2, "a prayer that named nothing asks the output's number again"


def test_the_levels_go_back_when_the_play_fails_halfway(tmp_path, monkeypatch):
    """The test that matters most in this feature. A play that fell over - here the
    receiver closed the door on the file - used to leave nothing behind but an error. It
    must not also leave somebody's kitchen at 40% for the rest of the day, so the
    hand-back sits in a finally and happens whatever else went wrong."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    group = GroupReceiver(breaks=True)
    b = cast_group(monkeypatch, [kitchen], group=group)
    with pytest.raises(BackendError):
        b.play([clip(tmp_path)])
    assert kitchen.levels == [0.4, 0.1], "moved for a call that never happened, and put back"
    assert not kitchen.open


def test_a_room_moved_while_the_call_plays_is_left_where_somebody_put_it(tmp_path, monkeypatch, caplog):
    """A person at the speaker, or in the Google Home app, out-ranks the daemon: their
    ask is the newer one, and rolling it back would be muezzin contradicting somebody
    standing in front of it. So a room is only put back if it is still at the level
    muezzin gave it."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    group = GroupReceiver()
    b = cast_group(monkeypatch, [kitchen], group=group)
    b.group_receiver.media_controller.during = lambda: kitchen.set_volume(0.9)
    with caplog.at_level("INFO"):
        b.play([clip(tmp_path)])
    assert kitchen.levels == [0.4, 0.9], "muezzin's level, then the newer ask, and no third move"
    assert kitchen.status.volume_level == 0.9
    assert "newer than ours" in caplog.text and "Kitchen speaker" in caplog.text


def test_a_name_in_the_profile_that_is_not_on_the_network_is_said_once(tmp_path, monkeypatch, caplog):
    """`members:` is written by hand, and a name typed wrong is a level that goes
    nowhere. The log has to name the name and say what muezzin can see instead, because
    a silent miss is the kind of bug that eats a week. Once per output: a typo does not
    become new news at the next prayer."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    b = cast_group(monkeypatch, [kitchen],
                   members={"Kitcen speaker": 0.5, "Kitchen speaker": 0.3})
    with caplog.at_level("WARNING"):
        for _ in range(2):
            b.play([clip(tmp_path)])
    assert kitchen.levels == [0.3, 0.1, 0.3, 0.1], "the room that does exist still gets its level"
    assert "Kitcen speaker" in caplog.text and "Kitchen speaker" in caplog.text
    assert caplog.text.count("not a speaker muezzin can see") == 1


def test_a_room_that_never_said_its_own_level_says_so(tmp_path, monkeypatch, caplog):
    """Nothing to go back to, and muezzin does not invent one. Which room it is and what
    it is now at are both in the sentence, because that is what somebody has to go and
    set by hand."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, None)
    kitchen.status.volume_level = None
    b = cast_group(monkeypatch, [kitchen])
    with caplog.at_level("WARNING"):
        b.play([clip(tmp_path)])
    assert kitchen.levels == [0.4], "the level was asked for, as the profile wrote"
    assert "never told muezzin what its own level was" in caplog.text
    assert "left at 0.4" in caplog.text


def test_a_room_that_answers_nothing_does_not_hold_up_the_adhan(tmp_path, monkeypatch, caplog):
    """A switched-off speaker is a normal thing on a LAN. It stays at whatever level it
    is at, the log names it, and the adhan goes out on the rooms that are there - which
    is what the house would have heard anyway."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    office = Room("Office speaker", OFFICE_UUID, 0.8)
    b = cast_group(monkeypatch, [kitchen, office])
    b.MEMBER_SECONDS = 0.05           # the deadline for an answer, shrunk for the test
    office.status = None              # it answers mDNS and then says nothing at all
    b.play([clip(tmp_path)])
    assert kitchen.levels == [0.4, 0.1], "the room that answered got its level and gave it back"
    assert office.levels == []
    assert "Office speaker answered nothing about itself" in caplog.text


def test_a_level_that_arrives_after_the_call_is_over_goes_back_itself(monkeypatch):
    """The race in the room-asks: a slow speaker's connection lands after the play has
    finished and the other rooms have been handed back. A level moved then would be left
    moved with nobody owing it, so the thread that moved it pays its own debt."""
    late = Room("Office speaker", OFFICE_UUID, 0.8)
    b = cast_group(monkeypatch, [late])
    with b._level_lock:
        b._levels_returned = True       # the call is already over
    import pychromecast
    assert b._borrow_one(pychromecast, late.record(), 0.4) is None
    assert late.levels == [0.4, 0.8], "borrowed and paid back by the thread that borrowed it"
    assert not late.open
    assert b._held == []


def test_two_outputs_that_reach_one_speaker_agree_on_where_its_level_goes(tmp_path, monkeypatch, caplog):
    """One kitchen, two outputs, one book. A profile can point at the same speaker twice -
    a whole-house group, and the kitchen group that kitchen is also in - and each output
    used to keep its own notes about what it borrowed. The second borrower then wrote down
    the *first borrower's* level as where the speaker lived; and when the first call ended,
    it found a number that was not the one it had asked for, read that as a person who had
    moved the speaker, and kept its hands off - leaving the kitchen at a level nobody in
    the house had chosen, with a log line blaming somebody who was not there. Now the level
    to go back to belongs to whoever picked the speaker up first, and the last one to put
    it down is the one that puts it back."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    house = cast_group(monkeypatch, [kitchen], volume=0.6)
    other = CastBackend(OutputConfig(name="kitchen-group", kind="google_cast",
                                     target="Kitchen group", volume=0.3))
    with caplog.at_level("INFO"):
        house._borrow_levels([(kitchen.record(), 0.6)])
        other._borrow_levels([(kitchen.record(), 0.3)])
        assert kitchen.levels == [0.6, 0.3], "the second ask is the one the room is obeying"
        house._return_levels()
        assert kitchen.levels == [0.6, 0.3], "the other call is still playing through it"
        other._return_levels()
    assert kitchen.levels == [0.6, 0.3, 0.1], "one hand-back, to where anybody had left it"
    assert "already held by whole-house" in caplog.text, "the log names the overlap as it happens"
    assert "still being held by kitchen-group" in caplog.text
    assert backends.LEVELS.owed() == {}, "nothing is left owing once both calls are over"


def test_two_outputs_naming_the_same_group_move_its_own_number_once(tmp_path, monkeypatch, caplog):
    """The same book at the other end of the wire. Two outputs naming one group is the
    kind of thing a rename in the Google Home app leaves behind, and the fallback that
    asks a group's own receiver for a level would then have asked twice and handed back
    twice - over a number nobody hears either way. The ask is still made twice, because
    that is what the profile asked for; the number goes back once."""
    group = GroupReceiver(level=0.1)
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    first = cast_group(monkeypatch, [kitchen], group=group, claims={})
    second = CastBackend(OutputConfig(name="also-house", kind="google_cast",
                                      target="Home group", volume=0.3))
    key = backends._norm_id(GROUP_UUID)
    with caplog.at_level("INFO"):
        one = first._borrow_group_level(group, 0.6, key)
        two = second._borrow_group_level(group, 0.3, key)
        first._return_one(one)
        assert group.levels == [0.6, 0.3], "the other output is still holding this one"
        assert "still being held by also-house" in caplog.text
        second._return_one(two)
    assert group.levels == [0.6, 0.3, 0.1]
    assert backends.LEVELS.owed() == {}


def test_a_number_another_output_asked_for_is_never_where_the_speaker_lived():
    """The rule the whole book turns on, stated on the book itself rather than left to the
    callers to get right. A borrower reads the level off a speaker it is about to move, and
    if that number is muezzin's own borrowed level then adopting it makes the borrowed
    level permanent - the exact failure, one floor down. So the number to go back to is the
    one noted when the speaker was first picked up, whoever picked it up, and the hand-back
    belongs to whoever puts the speaker down last."""
    book = backends.LEVELS
    assert book.claim("k", "house", "whole-house", 0.6, 0.1) == (0.1, [])
    assert book.claim("k", "kitchen", "kitchen-group", 0.3, 0.6) == (0.1, ["whole-house"])
    assert book.release("k", "house", 0.3) == ("held", None, ["kitchen-group"])
    assert book.release("k", "kitchen", 0.3) == ("restore", 0.1, [])
    book.finish("k")
    assert book.owed() == {}
    # A speaker that never said where it was has no number to go back to, and saying so is
    # the whole answer: muezzin does not invent one out of the level it moved it to.
    assert book.claim("k", "house", "whole-house", 0.6, None) == (None, [])
    assert book.release("k", "house", None) == ("nothing", None, [])
    assert book.owed() == {}


def test_a_speaker_that_would_not_give_its_level_back_keeps_the_debt(tmp_path, monkeypatch, caplog):
    """A write that falls over is not a debt paid. The entry stays in the book, so the next
    call to that speaker inherits the number it should have gone back to rather than
    reading muezzin's own borrowed level as where the speaker lived - which would turn one
    failed write into a level that outlives every later call."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    b = cast_group(monkeypatch, [kitchen])
    b._borrow_levels([(kitchen.record(), 0.4)])

    def refuse(level):
        kitchen.levels.append(level)
        raise RuntimeError("the receiver closed the door")

    kitchen.set_volume = refuse
    with caplog.at_level("WARNING"):
        b._return_levels()
    assert kitchen.levels == [0.4, 0.1], "the hand-back was tried, and it fell over"
    assert "would not take its level back" in caplog.text
    assert backends.LEVELS.owed(), "and the debt is still standing"
    del kitchen.set_volume          # the room is willing again, on the next call
    b._borrow_levels([(kitchen.record(), 0.4)])
    assert kitchen.levels == [0.4, 0.1, 0.4, 0.1], "back to 0.1, not to the 0.4 it was stuck at"
    assert backends.LEVELS.owed() == {}, "the second call paid the first one's debt as well"


def test_a_person_who_moved_the_speaker_by_hand_out_ranks_a_stale_debt():
    """The kept-over entry is the number a failed write could not put back - until somebody
    moves the speaker on purpose. A leftover debt whose ask nobody is holding, met by a
    level that is not one of ours, is a deliberate change by the household, and their ask
    is the newer promise: adopting the stale number would roll a person's decision over at
    the 5 am prayer, which is the opposite of the rule every hand-back in this file
    follows. So the entry rebases onto the new level, and that is what the next call owes."""
    book = backends._LevelLedger()
    assert book.claim("k", "house", "whole-house", 0.6, 0.1) == (0.1, [])
    assert book.release("k", "house", 0.6) == ("restore", 0.1, [])
    # Say the write of that restore fell over: the entry stays, holders empty, and the
    # speaker sits at muezzin's own 0.6.
    assert book.owed() == {"k": []}, "the debt stands with nobody holding it"
    # A person moves the speaker to 0.95, and the morning call reads that number.
    assert book.claim("k", "morning", "whole-house", 0.4, 0.95) == (0.95, []), \
        "their number, not the stale one, is what this call hands back to"
    assert book.release("k", "morning", 0.4) == ("restore", 0.95, [])


def test_a_room_that_could_not_be_written_to_owes_nothing(tmp_path, monkeypatch, caplog):
    """A claim whose write never happened is not a debt, and the name that made it is not
    a holder either. The name has to come out of the book, or the hand-back another output
    owes on that same speaker waits on a call that is already over and leaves the room at a
    borrowed level for good. The number that was noted on the way in is kept, because it is
    the honest one."""
    kitchen = Room("Kitchen speaker", KITCHEN_UUID, 0.1)
    house = cast_group(monkeypatch, [kitchen])
    other = CastBackend(OutputConfig(name="kitchen-group", kind="google_cast",
                                     target="Kitchen group", volume=0.3))
    real = kitchen.set_volume

    def refuse(level):
        raise RuntimeError("the receiver closed the door")

    kitchen.set_volume = refuse
    with caplog.at_level("WARNING"):
        assert other._borrow_levels([(kitchen.record(), 0.3)]) == [], "the write fell over"
    assert "would not answer the ask to change its level" in caplog.text
    kitchen.set_volume = real
    house._borrow_levels([(kitchen.record(), 0.6)])
    assert kitchen.levels == [0.6]
    with caplog.at_level("INFO"):
        house._return_levels()
    assert kitchen.levels == [0.6, 0.1], "nothing was left to wait on, so the room went home"
    assert backends.LEVELS.owed() == {}


def test_the_box_is_told_what_to_play_and_nothing_about_its_volume(tmp_path, monkeypatch):
    """What the daemon puts on the wire for a box is media and nothing else. A box
    is somebody's computer, and a request that also moved its volume would be
    reaching into a room that is not ours."""
    bodies = []

    class Resp:
        status = 200

        def read(self):
            # What the real box answers when a recording has finished: the daemon reads
            # the word so a playback someone stopped comes back as "stopped".
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def capture(req, timeout=None):
        bodies.append(req.data)
        return Resp()

    monkeypatch.setattr(backends.urllib.request, "urlopen", capture)
    clip = tmp_path / "fajr.mp3"
    clip.write_bytes(b"ID3")
    b = LanBoxBackend(OutputConfig(name="attic-pi", kind="lan_box",
                                   host="192.0.2.156", volume=0.3))
    b.play([clip], 0.9)
    assert len(bodies) == 1, bodies
    assert b"files" in bodies[0] and b"volume" not in bodies[0], bodies[0]


def answering(body: bytes):
    """A stand-in for `urlopen` that hands back one HTTP answer with `body` in it."""
    class Resp:
        status = 200

        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False
    return lambda req, timeout=None: Resp()


def test_a_box_that_was_stopped_says_so_and_the_daemon_says_it_back(tmp_path, monkeypatch):
    """The box knows the difference between a recording that ended and a recording
    somebody put down, and that difference has to travel back: a test called out of
    the hall speaker is not a speaker that failed, and the line a person reads the
    next morning should not read like one."""
    from muezzin import localplay

    monkeypatch.setattr(backends.urllib.request, "urlopen",
                        answering(b"stopped"))
    clip = tmp_path / "fajr.mp3"
    clip.write_bytes(b"ID3")
    b = LanBoxBackend(OutputConfig(name="attic-pi", kind="lan_box", host="192.0.2.156"))
    with pytest.raises(localplay.Stopped):
        b.play([clip], 0.9)


def test_the_ask_to_stop_reaches_the_box_over_the_wire(tmp_path, monkeypatch):
    """The daemon's own thread is the one sitting in the long `/play`, so going quiet
    means a second request to the box and not a word to itself."""
    asks = []
    answer = answering(b'{"stopped": 2}')

    def capture(req, timeout=None):
        asks.append((req.full_url, req.get_method()))
        return answer(req, timeout)

    monkeypatch.setattr(backends.urllib.request, "urlopen", capture)
    b = LanBoxBackend(OutputConfig(name="attic-pi", kind="lan_box", host="192.0.2.156"))
    assert b.stop() is True
    assert asks == [("http://192.0.2.156:8090/stop", "POST")]


def test_a_box_from_before_the_stop_route_says_it_cannot_be_interrupted(tmp_path, monkeypatch):
    """A 404 from an older box is that box honestly saying it has no such route. The
    daemon reports that as "no" and says where to look, rather than raising."""
    import urllib.error

    def refuse(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, None)

    monkeypatch.setattr(backends.urllib.request, "urlopen", refuse)
    b = LanBoxBackend(OutputConfig(name="attic-pi", kind="lan_box", host="192.0.2.156"))
    assert b.stop() is False


def device(name, group=False, **extra):
    row = {"name": name, "model": "Nest Audio", "group": group, "id": name,
           "address": "192.168.0.21", "port": 8009}
    row.update(extra)
    return row


def test_the_devices_list_prints_who_is_inside_a_group(monkeypatch, capsys):
    """The command is how most people first find out that a group is not a
    speaker, so the members have to be in its output - and a group whose speakers
    would not answer must read as unknown rather than as an empty room."""
    from muezzin import cli

    def fake(timeout=5.0, ask_members=True):
        return {
            "speakers": [device("Landing speaker")],
            "groups": [
                device("Whole-house group", group=True, members=["Landing speaker"],
                       membership_known=True, silent=[]),
                device("Quiet group", group=True, members=[], membership_known=False,
                       silent=["nobody"]),
            ],
            "boxes": [], "asked": 1, "silent": ["nobody"],
        }

    monkeypatch.setattr("muezzin.backends.scan_speakers", fake)
    assert cli.cmd_devices(1.0) == 0
    printed = capsys.readouterr().out
    assert "members: Landing speaker" in printed
    assert "Quiet group" in printed
    assert "members: unknown, those speakers did not answer" in printed
