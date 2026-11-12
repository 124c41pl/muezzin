"""Scheduling: turn a profile's events into wall-clock wakeups and run them.

Times come from calc.compute_times as "decimal hours in local civil time" and
may fall past midnight (a late isha, a Reykjavik maghrib at 00:04). They are
converted to timezone-aware datetimes with ZoneInfo, so DST transitions and the
two days where the clock moves are handled by the tz database rather than by
hand-rolled arithmetic.
"""
from __future__ import annotations

import datetime as dt
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

from . import calc
from .config import EventConfig, Profile

# How late an event may be and still be worth playing. A speaker that is asleep
# or buffering can hold the queue up, and an adhan that arrives forty minutes
# after the time it belongs to is not a reminder, it is a wrong claim about the
# prayer times - so it gets logged and skipped instead.
LATE_GRACE = dt.timedelta(minutes=15)

log = logging.getLogger("muezzin.scheduler")

PRAYER_KEYS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha",
               "midnight", "true_night", "shurf", "sunset")


class ScheduledEvent:
    def __init__(self, when: dt.datetime, event: EventConfig):
        self.when = when
        self.event = event

    def __repr__(self):
        return f"<{self.when:%Y-%m-%d %H:%M} {self.event.name}>"


def events_for_date(profile: Profile, date: dt.date) -> list[ScheduledEvent]:
    tzname = profile.location.timezone
    times = calc.compute_times(profile.location, date, profile.params,
                               asr_shadow=profile.asr_shadow, adjustments=profile.adjustments)
    out: list[ScheduledEvent] = []
    for ev in profile.events:
        if ev.days and date.weekday() not in _day_names_to_index(ev.days):
            continue
        hours = getattr(times, ev.at, None)
        if hours is None:
            log.warning("%s: %s has no computable time on %s (high-latitude rule? skipping)",
                        ev.name, ev.at, date)
            continue
        when = _wall_clock(date, hours + ev.offset_min / 60.0, tzname)
        out.append(ScheduledEvent(when, ev))
    return sorted(out, key=lambda e: e.when)


def _day_names_to_index(names: Iterable[str]) -> set[int]:
    table = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    return {table[str(n).lower()[:3]] for n in names}


def _wall_clock(date: dt.date, hours: float, tzname: str) -> dt.datetime:
    """Interpret hours as local wall-clock time on `date` (may spill into the
    next day), then attach the IANA zone. Ambiguous/Nonexistent times resolve
    with the tz database's default (fold=0)."""
    from zoneinfo import ZoneInfo
    naive = dt.datetime(date.year, date.month, date.day) + dt.timedelta(hours=hours)
    return naive.replace(tzinfo=ZoneInfo(tzname))


def upcoming(profile: Profile, now: Optional[dt.datetime] = None, days: int = 2) -> list[ScheduledEvent]:
    """Events from today through `days` ahead, in chronological order, past ones dropped."""
    now = now or dt.datetime.now(dt.timezone.utc)
    local_today = now.astimezone(_zone(profile.location.timezone)).date()
    out: list[ScheduledEvent] = []
    # start one day back: a maghrib that falls at 00:38 belongs to yesterday's
    # row, and a window that begins at today never sees it. The filter below
    # drops the parts of that row that have already gone by.
    for i in range(-1, days + 1):
        out.extend(events_for_date(profile, local_today + dt.timedelta(days=i)))
    return [e for e in out if e.when >= now]


def _zone(name: str):
    from zoneinfo import ZoneInfo
    return ZoneInfo(name)


class Runner:
    """Resolves backends once and fires events until stopped."""

    def __init__(self, profile: Profile):
        from .media import MediaServer

        self.profile = profile
        # only start the media server if some output can only play a URL it fetches
        self.media = None
        if self._needs_urls(profile):
            self.media = MediaServer(profile.media_dir, profile.http_port)
            self.media.start()
        self.backends = {}
        self.backends = self._build_backends()
        # Bumped whenever the running config changes. run_forever computes its
        # queue once per pass and then sleeps for hours, so this is how an edit
        # made while the daemon sleeps reaches the schedule.
        self.generation = 0
        self._stop = threading.Event()
        # One thing out of the speakers at a time: a test file from the web page
        # must not play on top of the adhan that is due.
        self._play_lock = threading.Lock()
        # players a reload or a toggle took out of service, waiting for the
        # player thread to come up for air
        self._retired: list = []
        # Playing happens on its own thread. A sleeping or buffering speaker can
        # hold one play for minutes, and the schedule has to keep advancing while
        # that happens instead of losing the prayers that come due during it.
        self._pending: queue.Queue = queue.Queue()
        self._watermark: Optional[dt.datetime] = None
        threading.Thread(target=self._drain, daemon=True, name="muezzin-player").start()

    def _needs_urls(self, profile: Profile) -> bool:
        from . import backends as B
        return any(getattr(B.KINDS.get(o.kind), "needs_urls", False)
                   for o in profile.enabled_outputs())

    def _build_backends(self) -> dict:
        from . import backends as B
        return {o.name: B.build(o, self.media) for o in self.profile.enabled_outputs()}

    def _media_matches(self, profile: Profile, server) -> bool:
        """Is the media server we already have the one this profile wants?"""
        if server is None or Path(server.media_dir) != Path(profile.media_dir):
            return False
        # `http_port: 0` means "any free port", which the server answered with a
        # real number - only compare when the profile asks for a specific port.
        return not profile.http_port or server.port == profile.http_port

    def reload(self, profile: Profile) -> None:
        """Swap in a re-read profile - the web panel does this after you edit the
        YAML while the daemon is running.

        Everything new is built before anything old is closed, and if building
        the new set fails the previous one is put back. A half-swapped daemon is
        worse than a refused edit: the old backends would be holding a media
        server that has already stopped answering, and every play after that
        would fail until someone restarted the process.
        """
        from .media import MediaServer

        old_backends, old_media, old_profile = self.backends, self.media, self.profile
        try:
            self.profile = profile
            if self._needs_urls(profile):
                if self._media_matches(profile, old_media):
                    self.media = old_media
                else:
                    self.media = MediaServer(profile.media_dir, profile.http_port)
                    self.media.start()
            self.backends = self._build_backends()
        except Exception:
            self.profile, self.backends, self.media = old_profile, old_backends, old_media
            raise
        # The new server is listening and the new backends point at it, so the old
        # ones can go - but "go" means when the player thread is between plays. A
        # Cast backend that is closed stops the stream it is holding, so pulling it
        # down while an adhan is mid-note cuts the adhan short, and a speaker still
        # downloading from the old media server loses the rest of its file.
        self._retire(old_backends.values(),
                     old_media if old_media is not self.media else None)
        # A new profile may have added or moved events, so forget where we had got
        # to; the grace window stops the old queue from firing again.
        self._watermark = None
        self.generation += 1
        log.info("profile reloaded (generation %d): %d outputs, %d events",
                 self.generation, len(profile.outputs), len(profile.events))

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Turn one output on or off for the running daemon only. To make it
        permanent, change the profile file (`muezzin web` shows you the YAML)."""
        out = self.profile.output(name)
        if out is None:
            raise ValueError(f"no output named {name!r} in this profile")
        out.enabled = enabled
        backend = self.backends.pop(name, None)
        if enabled:
            from . import backends as B
            self.backends[name] = B.build(out, self.media)
        if backend is not None:
            self._retire([backend], None)

    def _retire(self, backends, media) -> None:
        """Park players that a reload or a toggle has taken out of service.

        Shutting a player down is neither instant nor harmless: closing a Cast
        backend stops whatever it is streaming, and stopping a media server
        strangles a download in flight. So the retired objects wait here and the
        player thread closes them the first time it comes up between plays. Saving
        the YAML in the middle of an adhan cannot truncate the adhan, and the panel
        never blocks waiting for a speaker to finish.
        """
        self._retired.extend(backends)
        if media is not None:
            self._retired.append(media)

    def _close_retired(self) -> bool:
        """Close the parked players if nobody is playing. True means some still wait."""
        if not self._retired:
            return False
        if not self._play_lock.acquire(blocking=False):
            return True          # someone is mid-note; try again when they are done
        try:
            while self._retired:
                thing = self._retired.pop(0)
                # a backend closes and a media server stops: both mean "let go of
                # the socket", and a reload can hand either one to this list
                closer = getattr(thing, "close", None) or getattr(thing, "stop", None)
                try:
                    if closer is not None:
                        closer()
                except Exception as exc:
                    log.warning("a retired player did not close cleanly: %s", exc)
        finally:
            self._play_lock.release()
        return bool(self._retired)

    def play_now(self, name: str, media: list[str], volume: Optional[float] = None) -> None:
        """Play files through one output right now - what the web panel's test
        button and `muezzin play-now` use."""
        out = self.profile.output(name)
        if out is None:
            raise ValueError(f"no output named {name!r} in this profile")
        backend = self.backends.get(name)
        if backend is None:
            raise RuntimeError(f"output {name!r} is disabled, so it has no player to send to")
        paths = [self.profile.media_path(p) for p in media]
        with self._play_lock:
            backend.play(paths, out.volume if volume is None else volume)

    def fire(self, sev: ScheduledEvent) -> None:
        ev = sev.event
        media = [self.profile.media_path(p) for p in ev.media]
        targets = self.profile.targets_for(ev)
        if not targets:
            log.warning("%s: no enabled output matched %s", ev.name, ev.targets or "(all)")
            return
        with self._play_lock:
            for out in targets:
                backend = self.backends.get(out.name)
                if backend is None:
                    # The profile says it should be playing and the daemon has no
                    # player for it: that is worth a line in the log, because the
                    # alternative is a silent morning and no clue why.
                    log.error("%s: %s is named as a target but has no player (disabled?), "
                              "so it stays quiet", ev.name, out.name)
                    continue
                try:
                    log.info("%s -> %s (%s)", ev.name, out.name, out.kind)
                    backend.play(media, ev.volume)
                except Exception as exc:                    # one dead speaker must not stop the rest
                    log.error("%s on %s failed: %s", ev.name, out.name, exc)

    def _drain(self) -> None:
        """The player thread: fire queued events one at a time."""
        while True:
            sev = self._pending.get()
            if sev is None:
                return
            try:
                self.fire(sev)
            except Exception as exc:
                log.error("%s failed: %s", sev.event.name, exc)
            finally:
                self._pending.task_done()
                # the lock has just been let go of, so whatever a reload parked
                # can be closed here without stepping on a play
                self._close_retired()

    def stop(self) -> None:
        """Ask run_forever to come back at its earliest convenience."""
        self._stop.set()

    def _sleep(self, seconds: float, generation: int) -> bool:
        """Sleep up to `seconds`, coming back early if the config changed or we
        were asked to stop. True means: the queue you are holding is stale."""
        deadline = time.monotonic() + max(0.0, seconds)
        while not self._stop.is_set() and self.generation == generation:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._stop.wait(min(remaining, 5.0))
            # the daemon spends most of its life in this loop, so this is where
            # parked players get shut down while the speakers are idle
            self._close_retired()
        return self.generation != generation or self._stop.is_set()

    def _still_worth_saying(self, sev: ScheduledEvent, now=None) -> bool:
        """Whether an event whose moment has passed should still be played.

        A few minutes late is a speaker that was still busy with the previous
        adhan: the call is still the call, and a house that hears nothing is the
        worse outcome. An hour late makes a different claim about what time it
        is, so it is refused out loud instead of played quietly.
        """
        now = now or dt.datetime.now(dt.timezone.utc)
        return (now - sev.when) <= LATE_GRACE

    def run_forever(self) -> None:
        log.info("muezzin daemon: %s / %s / asr=%s", self.profile.location,
                 self.profile.params.label, "hanafi" if self.profile.asr_shadow == 2.0 else "standard")
        while not self._stop.is_set():
            # one pass per generation: a config edit bumps the counter and this
            # loop recomputes the whole queue instead of waiting on the old one
            generation = self.generation
            # Look a little way back as well as two days forward: an event that
            # came due while a speaker was still busy with the previous one is
            # still worth playing, and dropping it is how a whole day goes quiet.
            floor = dt.datetime.now(dt.timezone.utc) - LATE_GRACE
            due = [e for e in upcoming(self.profile, now=floor)
                   if self._watermark is None or e.when > self._watermark]
            if not due:
                log.warning("nothing scheduled in the next two days")
                self._sleep(3600.0, generation)
                continue
            sev = due[0]
            delay = (sev.when - dt.datetime.now(dt.timezone.utc)).total_seconds()
            if delay >= 0:
                log.info("next: %s at %s (%.0f min)", sev.event.name,
                         sev.when.strftime("%Y-%m-%d %H:%M %Z"), delay / 60.0)
                while delay > 0:
                    if self._sleep(min(delay, 3600.0), generation):
                        break
                    delay = (sev.when - dt.datetime.now(dt.timezone.utc)).total_seconds()
            else:
                log.warning("%s came due %.0f min ago, playing it now",
                            sev.event.name, -delay / 60.0)
            if self.generation != generation or self._stop.is_set():
                continue
            if not self._still_worth_saying(sev):
                # Late enough that playing it would say something untrue about the
                # time, so say so loudly rather than pretend nothing happened.
                log.error("%s was due at %s and the speakers were still busy: skipped",
                          sev.event.name, sev.when.strftime("%H:%M"))
                self._watermark = sev.when
                continue
            self._watermark = sev.when
            self._pending.put(sev)
            if delay > 0:
                self._sleep(60.0, generation)   # never fire two events on top of each other

    def shutdown(self) -> None:
        self._stop.set()
        self._pending.put(None)
        for b in list(self.backends.values()):
            b.close()
        while self._retired:
            thing = self._retired.pop(0)
            closer = getattr(thing, "close", None) or getattr(thing, "stop", None)
            try:
                if closer is not None:
                    closer()
            except Exception as exc:
                log.warning("a retired player did not close cleanly: %s", exc)
        if self.media:
            self.media.stop()
