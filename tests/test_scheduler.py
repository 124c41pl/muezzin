"""Scheduler tests: the calendar arithmetic that turns prayer times into events
that fire at the right wall-clock instant, on the right day, in the right zone."""
from __future__ import annotations

import datetime as dt
import threading
import time
from pathlib import Path

import pytest

from muezzin import calc
from muezzin.config import load_profile
from muezzin.scheduler import PRAYER_KEYS, ScheduledEvent, _wall_clock, events_for_date, upcoming

# 2026-11-09 is a Monday; 2026-11-10 is a Tuesday.
MONDAY = dt.date(2026, 11, 9)
TUESDAY = dt.date(2026, 11, 10)

BASE = """
location: {latitude: 40.7128, longitude: -74.006, timezone: America/New_York}
method: {preset: isna, adjustments: {dhuhr: 0}}
media_dir: media
out_dir: "{out}"
http_port: 0
outputs:
  - name: outbox
    kind: file
    host: "{out}"
events:
  - name: fajr-adhan
    at: fajr
    media: [fajr.mp3]
  - name: dhuhr-nudge
    at: dhuhr
    offset_min: 5
    media: [dua.mp3]
  - name: friday-tune
    at: asr
    media: [dua.mp3]
    days: [fri]
"""


def profile_for(tmp_path, text: str = None):
    (tmp_path / "media").mkdir(exist_ok=True)
    for name in ("fajr.mp3", "dua.mp3"):
        (tmp_path / "media" / name).write_bytes(b"ID3\x03fake")
    out = tmp_path / "outbox"
    text = (text or BASE).replace("{out}", str(out).replace("\\", "/"))
    write(tmp_path, text)
    return load_profile(tmp_path / "muezzin.yaml"), out


def write(tmp_path, text: str):
    path = tmp_path / "muezzin.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_times_past_midnight_stay_on_the_next_day():
    when = _wall_clock(TUESDAY, 24.75, "America/New_York")
    assert (when.day, when.hour, when.minute) == (11, 0, 45)
    assert str(when.tzinfo) == "America/New_York"


def test_events_for_a_day_are_in_order_and_carry_offsets(tmp_path):
    profile, _ = profile_for(tmp_path)
    events = events_for_date(profile, TUESDAY)
    assert [e.event.name for e in events] == ["fajr-adhan", "dhuhr-nudge"]
    assert events[0].when < events[1].when
    times = calc.compute_times(profile.location, TUESDAY, profile.params,
                               asr_shadow=profile.asr_shadow, adjustments=profile.adjustments)
    # dhuhr + 5 min, as written in the YAML
    assert abs((events[1].when.hour * 60 + events[1].when.minute)
               - round(times.dhuhr * 60) - 5) <= 1


def test_day_filter_only_fires_on_that_weekday(tmp_path):
    profile, _ = profile_for(tmp_path)
    assert all(e.event.name != "friday-tune" for e in events_for_date(profile, TUESDAY))
    assert any(e.event.name == "friday-tune" for e in events_for_date(profile, dt.date(2026, 11, 13)))


def test_upcoming_skips_events_that_already_happened(tmp_path):
    profile, _ = profile_for(tmp_path)
    now = _wall_clock(TUESDAY, 6.0, "America/New_York")      # after fajr, before dhuhr
    rows = upcoming(profile, now=now, days=1)
    assert all(e.when >= now for e in rows), "past events must not fire late"
    tomorrow = TUESDAY + dt.timedelta(days=1)
    assert [e.event.name for e in rows if e.when.date() == TUESDAY] == ["dhuhr-nudge"]
    assert [e.event.name for e in rows if e.when.date() == tomorrow] == ["fajr-adhan", "dhuhr-nudge"]
    assert [e.when for e in rows] == sorted(e.when for e in rows)


def test_runner_copies_to_a_file_output_and_needs_no_media_server(tmp_path):
    """End-to-end without any audio device: profile -> scheduler -> backend."""
    from muezzin.scheduler import Runner

    profile, out = profile_for(tmp_path)
    runner = Runner(profile)
    try:
        assert runner.media is None, "a file output should not open a media server port"
        events = events_for_date(profile, TUESDAY)
        for sev in events:
            runner.fire(sev)
        assert (out / "fajr.mp3").read_bytes() == b"ID3\x03fake"
        assert (out / "dua.mp3").exists()
    finally:
        runner.shutdown()


def test_a_failing_speaker_does_not_stop_the_others(tmp_path):
    """One dead speaker at 5 am must not silence the rest of the house."""
    from muezzin.scheduler import Runner

    text = BASE.replace(
        '  - name: outbox\n    kind: file\n    host: "{out}"',
        '  - name: outbox\n    kind: file\n    host: "{out}"\n'
        '  - name: broken\n    kind: lan_box\n    host: 127.0.0.1\n    port: 1',
    ).replace("media: [fajr.mp3]", "media: [fajr.mp3]\n    targets: [broken, outbox]")
    profile, out = profile_for(tmp_path, text)
    runner = Runner(profile)
    try:
        runner.fire(events_for_date(profile, TUESDAY)[0])
        assert (out / "fajr.mp3").exists(), "the working speaker still played"
    finally:
        runner.shutdown()


def test_every_prayer_key_the_scheduler_knows_is_a_real_time():
    from muezzin import calc
    t = calc.compute_times(calc.Location(40.7128, -74.006, "America/New_York"),
                           TUESDAY, calc.PRESETS["isna"])
    for key in PRAYER_KEYS:
        assert hasattr(t, key), f"scheduler offers {key} but the engine does not compute it"


def test_an_edit_made_while_the_daemon_sleeps_reaches_the_schedule(tmp_path):
    """run_forever works out its queue and then sleeps for hours. An edit - a new
    event, a moved time, a deleted one - has to interrupt that sleep, or the day
    plays out the plan the user already replaced."""
    from muezzin.scheduler import Runner

    profile, _ = profile_for(tmp_path)
    runner = Runner(profile)
    try:
        before, woke = runner.generation, threading.Event()

        def waiter():
            # exactly what run_forever does between events
            if runner._sleep(120.0, runner.generation):
                woke.set()

        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        path = write(tmp_path, BASE.replace("{out}", str(tmp_path / "outbox").replace("\\", "/"))
                     .replace("at: fajr", "at: dhuhr"))
        runner.reload(load_profile(path))
        assert runner.generation > before
        assert woke.wait(10), "the daemon is still sleeping on the queue it threw away"
    finally:
        runner.shutdown()


def test_a_reload_replaces_a_media_server_that_no_longer_matches(tmp_path):
    """Cast and lan_box outputs get their URLs from the media server. If
    media_dir or http_port changed, the old server hands speakers a URL for a
    file that is not there and the adhan is dropped with "not inside the media
    dir" - so reload() has to swap the server, not reuse it."""
    from muezzin.scheduler import Runner

    text = BASE.replace("kind: file", "kind: google_cast").replace(
        '    host: "{out}"', "    target: Study speaker")
    profile, _ = profile_for(tmp_path, text)
    runner = Runner(profile)
    try:
        first = runner.media
        assert first is not None and first.port, "a cast profile needs a media server to serve from"
        other = tmp_path / "other-media"
        other.mkdir()
        (other / "fajr.mp3").write_bytes(b"ID3\x03fake")
        path = write(tmp_path, text.replace("media_dir: media", "media_dir: other-media"))
        runner.reload(load_profile(path))
        assert runner.media is not first, "a stale media server would hand speakers the old URL"
        assert Path(runner.media.media_dir).name == "other-media"
    finally:
        runner.shutdown()


def test_a_failed_reload_leaves_the_daemon_able_to_play(tmp_path, monkeypatch):
    """A reload is where a config edit meets the live speakers. If building the
    new one half-fails, the running daemon must keep what it had - otherwise an
    edit made after midnight silently costs the house its Fajr."""
    from muezzin.scheduler import Runner

    profile, out = profile_for(tmp_path)
    runner = Runner(profile)
    try:
        old_backends, old_media = dict(runner.backends), runner.media
        path = write(tmp_path, BASE.replace("{out}", str(tmp_path / "outbox").replace("\\", "/"))
                     + "hijri_offset: 1\n")
        monkeypatch.setattr(runner, "_build_backends",
                            lambda: (_ for _ in ()).throw(RuntimeError("a speaker refused to start")))
        with pytest.raises(RuntimeError, match="refused to start"):
            runner.reload(load_profile(path))
        assert runner.backends == old_backends, "the old players were thrown away anyway"
        assert runner.media is old_media
        runner.fire(events_for_date(profile, TUESDAY)[0])
        assert (out / "fajr.mp3").exists(), "the daemon still plays after a refused reload"
    finally:
        runner.shutdown()


def test_the_player_thread_picks_up_what_the_scheduler_queued(tmp_path):
    """run_forever queues an event and goes back to watching for the next one. If
    the queue is never drained - a player thread that died, an exception that was
    swallowed - every later adhan just sits in a list and the house is quiet."""
    from muezzin.scheduler import Runner

    profile, out = profile_for(tmp_path)
    runner = Runner(profile)
    try:
        runner._pending.put(events_for_date(profile, TUESDAY)[0])
        deadline = time.time() + 5.0
        # the file lands a moment before the queue reports the job finished, so wait
        # on the queue rather than on the file: the queue is the claim being tested,
        # and a deadline is only a way of not waiting forever
        while runner._pending.unfinished_tasks and time.time() < deadline:
            time.sleep(0.05)
        assert (out / "fajr.mp3").exists(), "nothing on the queue was ever played"
        assert runner._pending.unfinished_tasks == 0
    finally:
        runner.shutdown()


def test_late_is_forgiven_up_to_a_point(tmp_path):
    """A speaker still busy with the previous call delays the next by minutes, and
    a morning where nothing was said is worse than one said a little late. An hour
    late makes a different claim about what time it is, so that one is refused."""
    from muezzin.scheduler import Runner

    profile, _ = profile_for(tmp_path)
    runner = Runner(profile)
    try:
        now = dt.datetime.now(dt.timezone.utc)
        late = ScheduledEvent(now - dt.timedelta(minutes=8), profile.events[0])
        way_late = ScheduledEvent(now - dt.timedelta(minutes=40), profile.events[0])
        assert runner._still_worth_saying(late, now=now)
        assert not runner._still_worth_saying(way_late, now=now)
        # something that has not come due yet is not late at all
        assert runner._still_worth_saying(ScheduledEvent(now + dt.timedelta(minutes=3),
                                                         profile.events[0]), now=now)
    finally:
        runner.shutdown()


PAST_MIDNIGHT = """
location: {latitude: 40.7128, longitude: -74.006, timezone: America/New_York}
method: {preset: isna, adjustments: {isha: 420}}
media_dir: media
out_dir: "{out}"
http_port: 0
outputs:
  - name: outbox
    kind: file
    host: "{out}"
events:
  - name: late-isha
    at: isha
    media: [dua.mp3]
"""


def test_a_time_written_on_yesterday_s_row_is_still_coming(tmp_path):
    """A high-latitude maghrib at 00:38, or an isha pushed past midnight, is
    written on the previous day with a day marker of +1. A window that starts at
    today never reads that row, so the moment passes with the house silent."""
    profile, _ = profile_for(tmp_path, PAST_MIDNIGHT)
    rows = events_for_date(profile, MONDAY)
    assert rows[0].when.date() == TUESDAY, "the event belongs to yesterday's row"

    now = _wall_clock(TUESDAY, 0.25, "America/New_York")     # ten past midnight
    due = upcoming(profile, now=now, days=1)
    late = [e for e in due if e.event.name == "late-isha"]
    assert late, "the isha that spills past midnight was never scheduled"
    assert late[0].when.date() == TUESDAY
    assert now < late[0].when < _wall_clock(TUESDAY, 2.0, "America/New_York")
    assert all(e.when >= now for e in due)


def test_a_config_save_while_a_speaker_is_busy_does_not_cut_the_note_short(tmp_path,
                                                                          monkeypatch):
    """reload() used to close the old players on the panel thread. Closing a Cast
    backend stops the stream it is holding, so saving the YAML in the middle of an
    adhan ended the adhan. The old players now wait until the player thread is
    between plays - and the panel still returns straight away."""
    from muezzin.scheduler import Runner

    profile, out = profile_for(tmp_path)
    runner = Runner(profile)
    try:
        old_backend = runner.backends["outbox"]
        closed = []
        monkeypatch.setattr(old_backend, "close", lambda: closed.append(True))
        started, hold = threading.Event(), threading.Event()
        real_play = old_backend.play

        def slow_play(paths, volume):
            started.set()
            assert hold.wait(10), "the play was cut off"
            real_play(paths, volume)

        monkeypatch.setattr(old_backend, "play", slow_play)
        runner._pending.put(events_for_date(profile, TUESDAY)[0])
        assert started.wait(5), "the player thread never started"

        path = write(tmp_path, BASE.replace("{out}", str(tmp_path / "outbox").replace("\\", "/"))
                     + "hijri_offset: 1\n")
        done = []

        def timed_reload():
            runner.reload(load_profile(path))
            done.append(True)

        thread = threading.Thread(target=timed_reload, daemon=True)
        thread.start()
        thread.join(5)
        assert done, "saving the config blocked on the speaker"
        assert not closed, "the old player was closed while it was still playing"

        hold.set()
        deadline = time.time() + 5.0
        while not closed and time.time() < deadline:
            time.sleep(0.05)
        assert closed, "the retired player was never shut down"
        assert (out / "fajr.mp3").read_bytes() == b"ID3\x03fake", "the whole adhan was played"
    finally:
        runner.shutdown()


def test_disabling_an_output_waits_for_the_note_it_was_playing(tmp_path, monkeypatch):
    """The panel's toggle takes a speaker out of service. If it yanks the player
    away mid-stream the last thing the house hears is half a call to prayer."""
    from muezzin.scheduler import Runner

    profile, _ = profile_for(tmp_path)
    runner = Runner(profile)
    try:
        backend = runner.backends["outbox"]
        closed = []
        monkeypatch.setattr(backend, "close", lambda: closed.append(True))
        started, hold = threading.Event(), threading.Event()
        monkeypatch.setattr(backend, "play",
                            lambda paths, volume: (started.set(), hold.wait(10)))
        runner._pending.put(events_for_date(profile, TUESDAY)[0])
        assert started.wait(5), "the player thread never started"

        runner.set_enabled("outbox", False)
        assert "outbox" not in runner.backends, "the output is off from the panel's point of view"
        assert not closed, "the player was closed while it was still playing"
        hold.set()
        deadline = time.time() + 5.0
        while not closed and time.time() < deadline:
            time.sleep(0.05)
        assert closed, "the retired player was never shut down"
    finally:
        runner.shutdown()


SLOW_HOUSE = """
location: {latitude: 40.7128, longitude: -74.006, timezone: America/New_York}
method: {preset: isna, adjustments: {dhuhr: 0}}
media_dir: media
out_dir: "{out}"
http_port: 0
outputs:
  - name: nest
    kind: google_cast
    target: Study speaker
  - name: box
    kind: lan_box
    host: 127.0.0.1
  - name: drawer
    kind: file
    host: "{out}"
  - name: porch
    kind: google_cast
    target: Porch speaker
    lead_seconds: 0
events:
  - name: fajr-adhan
    at: fajr
    media: [fajr.mp3]
"""


def test_the_slowest_speaker_an_event_wants_sets_the_lead(tmp_path, monkeypatch):
    """A speaker on the network has to be found by name, connected to, and told to
    fetch a file before anyone hears a note, and that costs seconds nobody can know
    in advance. So the moment is paid for a little early, by as much as the slowest
    speaker this event wants needs. What a profile says for one speaker beats what
    its kind usually costs, and `lead_seconds: 0` is an answer, not an absence:
    exactly on the minute."""
    from muezzin import scheduler
    from muezzin.scheduler import Runner, lead_of, tidy_is_safe

    profile, _ = profile_for(tmp_path, SLOW_HOUSE)
    assert lead_of([profile.output("nest")]) == 8.0       # a Nest: found on the LAN
    assert lead_of([profile.output("box")]) == 1.0        # a box one request away
    assert lead_of([profile.output("drawer")]) == 0.0     # writing a file is instant
    assert lead_of([profile.output("porch")]) == 0.0      # told to be exactly on time
    assert lead_of([]) == 0.0

    monkeypatch.setattr(Runner, "_build_backends", lambda self: {})
    runner = Runner(profile)
    try:
        sev = events_for_date(profile, TUESDAY)[0]
        names = [o.name for o in profile.targets_for(sev.event)]
        assert names == ["nest", "box", "drawer", "porch"]
        assert runner.lead(sev) == 8.0, "the slowest target is the one that gets paid for"
    finally:
        runner.shutdown()

    # closing a parked player means talking to a speaker, and a speaker that has
    # gone quiet answers slowly, so that work stops when the moment is close
    assert tidy_is_safe(1000.0, 0.0)
    assert not tidy_is_safe(scheduler.IDLE_TIDY - 1.0, 0.0)


def test_a_parked_player_waits_for_a_quiet_moment(tmp_path, monkeypatch):
    """The daemon spends its life asleep between calls, and that is where it shuts
    down the players a reload parked. Half a minute before Fajr is not a quiet
    moment: that talk with a sleeping speaker is on its own long enough to be the
    reason the house hears the call late."""
    from muezzin.scheduler import Runner

    profile, _ = profile_for(tmp_path)
    runner = Runner(profile)
    try:
        closed = []

        def tidy_and_wake():
            closed.append(True)
            runner._stop.set()            # end the sleep just after the first tidy

        monkeypatch.setattr(runner, "_close_retired", tidy_and_wake)
        monkeypatch.setattr(runner._stop, "wait", lambda seconds: None)   # no real waiting
        runner._sleep(4.0, runner.generation)
        assert not closed, "the speakers were tidied up four seconds before a call"
        runner._sleep(45.0, runner.generation)
        assert closed, "with 45 seconds to spare the parked player should have been closed"
    finally:
        runner.shutdown()


def test_two_speakers_hear_the_call_at_the_same_instant(tmp_path):
    """One speaker that spends six seconds being found on the network used to make
    the wired box in the kitchen start six seconds behind it, so the house heard
    the adhan twice, badly out of step. Each speaker is handed the recording on its
    own thread, and the event still counts as unfinished until the last one is
    done, so a test click cannot interrupt a call that is going out."""
    from muezzin.scheduler import Runner

    text = BASE.replace('    host: "{out}"',
                        '    host: "{out}"\n  - name: slow\n    kind: file\n    host: "{out}"')
    profile, _ = profile_for(tmp_path, text)
    runner = Runner(profile)
    try:
        order, hold = [], threading.Event()

        class Slow:
            def play(self, paths, volume=None):
                order.append("slow in")
                hold.wait(10)
                order.append("slow out")

            def close(self):
                pass

        class Quick:
            def play(self, paths, volume=None):
                order.append("quick")

            def close(self):
                pass

        runner.backends = {"slow": Slow(), "outbox": Quick()}
        sev = events_for_date(profile, TUESDAY)[0]
        runner._pending.put(sev)
        deadline = time.time() + 5.0
        while "quick" not in order and time.time() < deadline:
            time.sleep(0.05)
        assert "quick" in order, "one slow speaker held the other one back"
        assert runner._pending.unfinished_tasks, "the call was counted as finished while a " \
                                                 "speaker was still playing it"
        hold.set()
        deadline = time.time() + 5.0
        while runner._pending.unfinished_tasks and time.time() < deadline:
            time.sleep(0.05)
        assert not runner._pending.unfinished_tasks
        assert order.count("slow out") == 1, "the slow speaker was cut off"
    finally:
        runner.shutdown()


SOON = """
location: {latitude: 40.7128, longitude: -74.006, timezone: America/New_York}
method: {preset: isna, adjustments: {dhuhr: 0}}
media_dir: media
out_dir: "{out}"
http_port: 0
outputs:
  - name: drawer
    kind: file
    host: "{out}"
    lead_seconds: {lead}
events:
  - name: dhuhr-call
    at: dhuhr
    offset_min: {shift}
    media: [dua.mp3]
"""


def test_the_sound_goes_out_before_the_time_it_belongs_to(tmp_path):
    """The promise the lead exists for: the first note is in the air at the
    computed time rather than a few seconds after it, because the daemon woke late
    and the speaker then needed seconds to find itself on the network. `when` is
    not moved - the page and `muezzin next` still print the time the sun gives."""
    from zoneinfo import ZoneInfo

    from muezzin.scheduler import Runner

    now = dt.datetime.now(ZoneInfo("America/New_York"))
    today = now.date()
    base = calc.compute_times(calc.Location(40.7128, -74.006, "America/New_York"),
                              today, calc.PRESETS["isna"])
    due = _wall_clock(today, base.dhuhr, "America/New_York")
    # `offset_min:` only comes in whole minutes, so nudge dhuhr to somewhere in the
    # next minute or so and let the lead pay for the rest of the way to a moment
    # about six seconds from now
    shift = int((now + dt.timedelta(seconds=30) - due).total_seconds() // 60) + 1
    when = due + dt.timedelta(minutes=shift)
    lead = (when - (now + dt.timedelta(seconds=6))).total_seconds()
    assert 0.0 < lead < 600.0, f"the test put the call at {lead:.0f} s out, which does not fit"

    profile, _ = profile_for(tmp_path, SOON.replace("{shift}", str(shift))
                             .replace("{lead}", f"{lead:.3f}"))
    sev = events_for_date(profile, today)[0]
    assert abs((sev.when - when).total_seconds()) < 1.0, "the call is not where the test put it"

    runner = Runner(profile)
    played = []

    class Stamp:
        def play(self, paths, volume=None):
            played.append(dt.datetime.now(dt.timezone.utc))

        def close(self):
            pass

    runner.backends = {"drawer": Stamp()}
    thread = threading.Thread(target=runner.run_forever, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 20.0
        while not played and time.time() < deadline:
            time.sleep(0.05)
    finally:
        runner.stop()
        thread.join(10)
        runner.shutdown()

    assert played, "the daemon never handed the recording to the speaker"
    early = (sev.when.astimezone(dt.timezone.utc) - played[0]).total_seconds()
    assert early > 0.0, f"the call started {abs(early):.1f} s after the time it belongs to"
    assert abs(early - lead) < 4.0, f"started {early:.1f} s early, wanted {lead:.1f} s"

