"""Output backends: which speaker, for which prayer.

Each backend answers one question - "play this media here" - and a profile can
name as many outputs as it likes, individually or in groups. Media is delivered
as a local file (PC, LAN box), a served URL (Cast, which needs a reachable URL)
or an output directory (file backend, useful for testing and for feeding another
program).
"""
from __future__ import annotations

import abc
import base64
import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Optional
from uuid import UUID

from . import localplay

log = logging.getLogger("muezzin.backends")


class BackendError(RuntimeError):
    pass


# Where no `volume:` is written for a speaker we are casting to. Deliberately not
# zero: a missing field has never meant "play quietly", and now that a profile can
# tell "not written" from "written as 0.5" there is no reason to invent one.
DEFAULT_CAST_VOLUME = 0.5


class Backend(abc.ABC):
    kind = "?"
    # True for devices that can only play a URL they fetch themselves, which is
    # what makes muezzin start the little media server.
    needs_urls = False
    # Whether a `volume:` in the profile means anything for this kind of output.
    # Only a speaker muezzin is casting to: a Cast speaker exists to be driven and
    # its level is a property of the room. Everything else is a computer, and a
    # computer's volume belongs to the person who owns that computer.
    takes_volume = False
    # How far ahead of the moment an output belongs to its recording gets handed
    # over, so the first note is already in the air when that moment arrives.
    # A speaker on the network has to be found, woken, connected to and told to
    # fetch a URL before anybody hears anything, and all of that costs seconds.
    # `lead_seconds:` in the profile sets it for one output.
    lead_seconds = 0.0
    # Safety net so a stream that stalls cannot block the rest of the day's jobs.
    max_play_seconds = 30 * 60

    def __init__(self, cfg, media_server=None):
        self.cfg = cfg
        self.media_server = media_server
        if getattr(cfg, "volume", None) is not None and not self.takes_volume:
            # Say it once, when the output is built, rather than at every prayer
            # time: the profile named a knob this output will never use, and the
            # place to be told that is before the morning it would have mattered.
            log.warning("%s (%s): volume %s is ignored. muezzin sets a level only on a speaker it "
                        "casts to; the level on that machine is set on the machine itself",
                        cfg.name, self.kind, cfg.volume)

    @abc.abstractmethod
    def play(self, media: list[Path], volume: Optional[float] = None,
             members: Optional[dict] = None) -> None:
        """Play these files, at this call's levels.

        `volume` is what this prayer asked for - the event's own `volume:`, which
        overrides what the output has written - and `members` is the same thing one
        level deeper: a speaker's name on the network beside the level that prayer wants
        from that speaker alone. Both are borrowed and handed back; a level muezzin asks
        for is a level for the length of the call. Kinds that have no level of their own
        to be asked for take the arguments and pass them by, in the same way they already
        pass `volume` by.
        """
        ...

    def stop(self) -> bool:
        """End whatever this output is playing right now, and say whether anything was.

        Playback blocks: the thread inside play() sits in a speaker or a player until
        the recording ends, so an ask to go quiet has to reach the thing making the
        sound instead. A backend that drives something it holds - a Cast speaker, a
        machine's own player, a box on the LAN - answers that; the default here says
        there is nothing of ours to reach, which is the honest answer for an output that
        hands a recording over and lets go of it. An output that had already finished
        gives the same answer rather than an error.
        """
        return False

    def close(self) -> None:
        pass

    # helpers ---------------------------------------------------------------
    def _url_for(self, path: Path) -> str:
        if self.media_server is None:
            raise BackendError(f"{self.cfg.name}: {self.kind} needs a media URL but no media server "
                               f"is running (set http_port in the profile)")
        return self.media_server.url_for(path)


# ---------------------------------------------------------------------------
# the machine running muezzin
# ---------------------------------------------------------------------------

class PcSpeakersBackend(Backend):
    """Play on the machine muezzin itself is running on.

    The one output that needs no network: it asks localplay how this operating
    system plays a file - winmm on Windows, afplay on macOS, whichever of the
    usual players a Linux box has - and installs nothing on the way.

    There is no per-device routing: the sound goes to the machine's default
    output, so send it to a particular speaker by making that the system
    default, or use a google_cast or lan_box output for real routing.

    A `volume:` in the profile does nothing here, and says so once when the
    output is built. This is a computer, and the level a computer plays at is
    the business of whoever is sitting in front of it.
    """
    kind = "pc_speakers"

    def play(self, media, volume=None, members=None):
        for path in media:
            if not path.exists():
                log.warning("missing media %s", path)
                continue
            try:
                localplay.play_file(path)
            except localplay.Stopped:
                # Not a failure: this machine was told to go quiet, and the answer
                # travels up as the same word the page used to ask for it.
                raise
            except localplay.LocalPlaybackError as exc:
                raise BackendError(f"{self.cfg.name}: {exc}") from exc

    def stop(self):
        """End this machine's player. What makes the sound here is a process, or an
        MCI device on Windows, and either of them can be ended - see localplay.

        This stops every local playback this process is doing, which is what a
        household means by "stop the sound in this room": a daemon with two
        pc_speakers outputs is one machine, and the ask was not made of one of them
        alone. It does not touch the level of the machine, which stays that
        machine's own business.
        """
        return localplay.stop_all() > 0


class FileBackend(Backend):
    """Copy media into a directory. For testing, and for handing adhan to other software."""
    kind = "file"

    def play(self, media, volume=None, members=None):
        out_dir = Path(self.cfg.host or self.cfg.target or "out")
        if not out_dir.is_absolute():
            out_dir = Path.cwd() / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        for path in media:
            shutil.copy2(path, out_dir / path.name)
            log.info("file backend %s: wrote %s", self.cfg.name, out_dir / path.name)


# ---------------------------------------------------------------------------
# network speakers
# ---------------------------------------------------------------------------

def _clamp_level(value) -> float:
    """A level as a speaker can be asked for it: a number, held inside 0 and 1.

    The profile validator already refuses a level outside that range, and this is
    still here: a level also arrives from the web page and from an event's override,
    and a speaker handed 40 answers by treating the ask as nonsense rather than as
    loud.
    """
    return max(0.0, min(1.0, float(value)))


def call_level(name: str, event_members, event_volume, output_members,
               output_volume) -> float:
    """The level one speaker is asked for on one call, read out of a profile.

    Four numbers can answer that question, and what decides it is which of them is the
    more specific promise about this speaker and this call: what this prayer wrote beside
    this name, what this prayer wrote for everything it plays through, what the output
    wrote beside this name for every call, what the output wrote for everything. A
    prayer's blanket number outranks an output's line for this room on purpose - "the
    whole house at 70% for this Eid" is about tonight, and a standing exception that
    applies to every call of the year is the less specific of the two. The room's own line
    under the prayer outranks everything, which is the whole reason this exists: the
    kitchen woken for Fajr while the study keeps its usual level.

    This is a function rather than a method because the panel shows the number it decides
    before the prayer ever runs, and a page that worked the chain out on its own would be
    a second place to get the precedence wrong.
    """
    for level in ((event_members or {}).get(name), event_volume,
                  (output_members or {}).get(name), output_volume):
        if level is not None:
            return _clamp_level(level)
    return DEFAULT_CAST_VOLUME


# One speaker whose level muezzin is holding, and what to do about giving it back.
# `original` is None when the speaker never said where it was, which leaves nothing
# to restore and has to be said out loud rather than guessed at. `key` is which
# physical thing this debt is about, so the shared book below can tell one speaker
# from another: a room's uuid, or a group's when it is the group's own number that
# was moved. `owner` is the book's name for the play call that picked it up - the
# output and its number - so a thread that finishes after its call is over cannot
# pose as a holder of the next call's debt.
_Held = namedtuple("_Held", "name cast original asked key owner")

# How close a speaker's level has to be to what we asked for before muezzin believes
# it is the level muezzin put there. Speakers round, and a Nest reports 0.156249538064003
# for what the Home app calls 16%.
LEVEL_TOLERANCE = 0.01


def _level_of(cast) -> Optional[float]:
    """What level this speaker is at, as of right now, or None if it will not say.

    Asked for fresh rather than read off the last status that happened to arrive:
    what is being decided here is whether to move somebody's room back to where it
    was, and an old number is a poor reason to do it.
    """
    receiver = getattr(getattr(cast, "socket_client", None), "receiver_controller", None)
    if receiver is not None:
        try:
            receiver.update_status()
        except Exception:
            # Any of pychromecast's family plus the socket under it. The status we
            # already have is a worse answer than none, so it is tried below.
            pass
    status = getattr(cast, "status", None)
    level = getattr(status, "volume_level", None) if status is not None else None
    return None if level is None else float(level)


def _ask_all(items, question, seconds: float) -> list:
    """Put the same question to every item at once, and keep the answers that came in.

    Four speakers asked one after another cost the adhan its lead, because every
    round trip is a second of its own; asked together they cost one round trip. A
    speaker that is switched off answers nothing at all, so the deadline is what
    keeps one dead speaker holding up the prayer. Nothing is cancelled at the
    deadline - a half-open connection is closed by the thread that opened it - so
    an answer that lands late still arrives, and the caller decides what to do
    with a thing that showed up after the call was over.
    """
    answers: list = [None] * len(items)
    if not items:
        return answers
    # One thread per question, not a capped pool: with a pool of eight, the ninth
    # speaker on the LAN never gets asked at all and comes back indistinguishable
    # from a speaker that was asked and said nothing. The deadline is what bounds
    # the call; a thread cap would quietly decide which rooms get to answer, and
    # nobody chose that.
    pool = ThreadPoolExecutor(max_workers=len(items))
    try:
        jobs = {pool.submit(question, item): i for i, item in enumerate(items)}
        done, _ = wait(jobs, timeout=seconds)
        for job in done:
            try:
                answers[jobs[job]] = job.result()
            except Exception as exc:
                # A question that fell over is one speaker with no answer, not a
                # reason to stop the adhan: the caller is told nothing came back and
                # says which speaker that was.
                log.warning("the ask got no answer: %s", exc)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return answers


class _LevelLedger:
    """Whose level is being held, by whom, across every output in this process.

    One speaker can be reached by two outputs in the same profile: a whole-house group
    and, written in the same profile, the kitchen that sits inside that group. Each
    output used to keep its own book, so the kitchen was borrowed twice and handed back
    twice - and the second hand-back went to the number the first borrower had left
    there, which is not where anybody's kitchen was. That is how a level went missing
    from a room for the rest of the day with nobody able to say who moved it. This is the
    one book: a speaker's level is noted once, by whoever picked it up first, and put
    back once, by whoever puts it down last.

    What is kept is deliberately small. `asks` is every level any holder has asked this
    speaker for, because the question at the end of a call is "is the number on it one of
    ours, or did somebody move it?" - and a number another of muezzin's own outputs asked
    for is one of ours too. A level read off a speaker that is already being held is never
    taken for where that speaker was: it is another borrower's ask, and adopting it would
    keep the borrowed level in the house for good.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # One entry per physical speaker: where it was, who is holding it now, and every
        # level anybody has asked it for while it has been held.
        self._debts: dict = {}

    def _others(self, debt, skip=None) -> list:
        """Which other outputs are holding this speaker, by the name the profile gives them."""
        return sorted({out for held_by, (out, _) in debt["holders"].items() if held_by != skip})

    def claim(self, key, owner, name, level, observed) -> tuple:
        """Take this output's place as a holder of one speaker's level.

        `observed` is the level just read off that speaker. The answer is the number this
        debt should go back to, which is not necessarily the one that was just read: if
        the speaker was already being held by another output, the number to go back to is
        the one that output noted before anybody moved anything. The second answer is who
        else is holding it, which is worth naming in the log because it means the profile
        points at the same speaker twice.
        """
        with self._lock:
            debt = self._debts.get(key)
            if debt is None:
                debt = self._debts[key] = {"original": observed, "holders": {}, "asks": []}
            elif (not debt["holders"] and observed is not None
                  and not any(abs(observed - ask) <= LEVEL_TOLERANCE for ask in debt["asks"])):
                # An entry left standing by a hand-back that fell over: nobody is
                # holding this speaker, and the number on it now is not one of ours, so
                # a person moved it - in the Home app or at the speaker itself. Their
                # ask is the newer promise, and their number is the honest one to hand
                # this call back to; the old original belonged to a call whose write
                # never landed and is not worth rolling a deliberate change over.
                debt["original"] = observed
                debt["asks"] = [observed]
            debt["holders"][owner] = (name, level)
            debt["asks"].append(level)
            return debt["original"], self._others(debt, skip=owner)

    def release(self, key, owner, now) -> tuple:
        """Put one output's claim down, and say what should happen to the speaker now.

        `now` is where the speaker is at this moment, or None if it will not say. The
        answer is an action for the caller to carry out, since the caller is the one
        holding a connection to the speaker:

          ``"held"``    - another output is still playing through this speaker, so its
                          turn decides where the number goes and this output writes nothing
          ``"restore"`` - nobody holds it any more and the number on it is one muezzin
                          asked for, so put the noted level back (the second answer)
          ``"moved"``   - the number on it is not one muezzin asked for, so a person, the
                          Google Home app or another program moved it more recently
          ``"nothing"`` - there is no number to go back to: this speaker never said where
                          it was, or the debt has already been discharged

        A debt that is about to be restored is left in the book rather than removed here,
        so that if the write falls over the next borrower still inherits the right number
        instead of reading muezzin's own borrowed level as where the speaker lived.
        """
        with self._lock:
            debt = self._debts.get(key)
            if debt is None:
                return "nothing", None, []
            debt["holders"].pop(owner, None)
            others = self._others(debt)
            if others:
                return "held", None, others
            original, asks = debt["original"], debt["asks"]
            if original is None:
                self._debts.pop(key, None)
                return "nothing", None, []
            if now is not None and not any(abs(now - asked) <= LEVEL_TOLERANCE for asked in asks):
                self._debts.pop(key, None)
                return "moved", None, []
            return "restore", original, []

    def unclaim(self, key, owner) -> None:
        """Take one output's name out of the book when its write never happened.

        An output that claimed a speaker and then could not reach it moved nothing, so it
        owes nothing - and a name left standing in the book would defer the hand-back to a
        call that is already over and is never coming back, which leaves the speaker at
        another output's borrowed level for good. The entry itself stays: it may be holding
        the number an earlier failed write never managed to put back, and that is worth
        more to the next caller than a tidy book.
        """
        with self._lock:
            debt = self._debts.get(key)
            if debt is not None:
                debt["holders"].pop(owner, None)

    def finish(self, key):
        """The number went back, or was left by a decision: the debt is paid, forget it."""
        with self._lock:
            self._debts.pop(key, None)

    def owed(self) -> dict:
        """What the book still has a number to say about: a speaker being held by somebody,
        or one whose hand-back fell over and is still standing. The tests use it to check
        that nothing leaks out of a call."""
        with self._lock:
            return {key: sorted({out for out, _ in debt["holders"].values()})
                    for key, debt in self._debts.items()}

    def reset(self):
        """Forget every debt. A process starts knowing nothing, and a test wants that too."""
        with self._lock:
            self._debts.clear()


# One book per process. The daemon is the only thing that borrows a speaker's level on a
# machine, and it plays every output in one process, so this is where two outputs that
# point at the same speaker meet. Two daemons, or a daemon and a `muezzin play-now` in
# another window, keep separate books: that is a thing to know, and running both at once
# is asking for trouble on other grounds anyway.
LEVELS = _LevelLedger()


class CastBackend(Backend):
    """Google Nest / Chromecast speakers, and Google home speaker GROUPS.

    A Cast device plays a URL it can fetch, so muezzin serves the media
    directory over HTTP on the LAN (see media_server). Discovery is mDNS, so no
    Google account, cloud call or pairing token is involved - which is why this
    keeps working when the internet is down.
    """
    kind = "google_cast"
    needs_urls = True
    takes_volume = True       # the one kind whose level is ours to ask for
    READY_SECONDS = 15.0    # how long the speaker has to send its first status
    START_SECONDS = 10.0    # how long it has to say PLAYING once handed a file
    # How many polls in a row a stopped state has to survive before the watch agrees the
    # file is over. One is not enough: a group says BUFFERING, and sometimes PAUSED, in the
    # middle of a recitation while its members fall back into step, and ending the watch at
    # the first of those stops the sound minutes before the end of the adhan.
    NOT_PLAYING_POLLS = 2
    # How long a player that has begun may go on saying nothing but BUFFERING before the
    # watch gives up on it. Members falling out of step take the stream again within a
    # second or two - measured here at half a second - so anything much longer than that
    # is a stream the network dropped, and waiting it out would keep the rooms sitting at
    # borrowed levels, and the rest of the output's recordings waiting behind it, for as
    # long as the ceiling above. Two minutes without a word of PLAYING is a ruined call
    # whichever way it turns out, so that is where the watch stops and says so.
    STALL_SECONDS = 120.0
    # How long a speaker inside a group gets to answer about its own level. The
    # speaker the sound actually goes through has READY_SECONDS above, because it is
    # the one that has to make a noise; these are guests whose levels are being
    # borrowed, and a room that is asleep or unplugged answers nothing at all.
    # Measured on a LAN with four speakers in a group, an awake one answers in about
    # a second, so this is mostly room for a speaker that is there but slow.
    MEMBER_SECONDS = 6.0
    # What the speaker costs before it makes a sound: a browse of the network
    # for its name (four seconds if it answers slowly), a handshake with the
    # receiver, then the launch of the file. Measured on a warm LAN that is two
    # to eight seconds, which is exactly the difference between an adhan that
    # lands on the time and one that lands after it. A group costs more than that:
    # after the browse, every speaker in it is asked which groups it belongs to,
    # and the ones that answer are each connected to about their own level. Those
    # asks happen at the same time as each other, and the measurement below is for
    # a group of four on a warm LAN, hand-off to the first second of sound.
    # A target that turns out to be a lone speaker is billed at this group's number
    # too, and that is deliberate: the lead is paid before anybody knows which one
    # it is - membership is a fact about the network, not the profile - and a few
    # seconds early beats the one speaker in the house that would have been late.
    lead_seconds = 12.0
    poll_seconds = 1.0      # how often to ask; a test may shrink it

    def __init__(self, cfg, media_server=None):
        super().__init__(cfg, media_server)
        # The speaker we are playing through right now, if any, and whether an ask to
        # stop has arrived. A playback is one blocking conversation with the receiver,
        # so this is the only way to reach a Nest that is half-way through a
        # recitation: the thread inside play() cannot be interrupted, and it is waiting
        # for the same file to end.
        self._live = []
        self._asked = False
        self._live_lock = threading.Lock()
        # Whether the thing said about a group's level has been said yet: it is not news
        # five times a day, and a person reading the log wants it once, not a copy per event.
        self._group_level_said = False
        # Which names have had the thing said about them already, on the same bargain as
        # the line above: each name once per output, but a name never said is said the
        # first time it turns up, however late in the daemon's life that is.
        self._missing_said: set[str] = set()   # written, and not a speaker on this network
        self._outside_said: set[str] = set()   # answered, and not inside this group
        self._quiet_said: set[str] = set()     # would not say who is inside this group
        # The levels that are being held on the speakers inside a group right now, and
        # whether they have been handed back. Held rather than simply set, because a
        # profile that writes `volume: 0.4` for a group is asking for 40% for the
        # length of a call, not for four rooms to be 40% from now until somebody
        # notices. The lock is here because the levels are taken by several threads at
        # once and paid back by one, and a level that arrives late still has to go back.
        self._held = []
        self._levels_returned = False
        self._level_lock = threading.Lock()
        # Which play call this output is on. A level thread that outlives its call must
        # not be taken for a holder of the next call: the level it moved belongs to the
        # call that is already over, and the newer call's ask for that same speaker is
        # the one that stands until the newer call ends.
        self._call_no = 0

    def stop(self):
        """Tell the speaker to stop, if we are the one playing through it.

        Nothing here waits: the poll loop in play() sees the change of state and comes
        back on its own, and the ask is one message on a connection already open. An
        output that was not playing anything answers no, which is the reply to the
        question rather than a complaint about it.
        """
        with self._live_lock:
            live = list(self._live)
            if live:
                self._asked = True
        if not live:
            return False
        for mc in live:
            try:
                mc.stop()
            except Exception as exc:
                # pychromecast's own family of errors, and the socket under them. A
                # speaker that walked out of the conversation in the middle of a test is
                # reported here and again by the poll loop; it is not a traceback for
                # the page that pressed the button.
                log.warning("%s: the ask to stop did not go through: %s", self.cfg.name, exc)
        return True

    def _call_level(self, name: str, volume: Optional[float], members) -> float:
        """The level this call asks one speaker, by name.

        This output's own two numbers, and the two the prayer carries, into the one place
        that decides (`call_level`), which is the same place the panel reads so that the
        figure beside a slider is the figure the speaker will be asked for. This is the
        only way this class asks a speaker for a level at all - the single speaker, the
        rooms inside a group, and a group's own receiver all come through here, so the
        page and the 5 am ask cannot drift apart.
        """
        return call_level(name, members, volume, self.cfg.members, self.cfg.volume)

    def _wanted_levels(self, dev, seen, volume, members=None) -> tuple[list, list[str], list[str], list[str]]:
        """Which speakers this call should put a level on, what to ask each for, and
        which of the names the profile wrote went unmatched, in three kinds.

        A group is not a thing with a level. Measured on a LAN with a Google Home group
        in it, a level aimed at the group goes into its receiver, which answers with the
        speakers inside it and the levels they are at, and after the ask every one of
        those numbers is still where the Home app left it; the group's own number moves,
        and moves again on its own a minute later. So the rooms are asked for themselves,
        over a connection of each one's own. The three lists after the levels are the
        names that are not speakers muezzin can see, the speakers that answered they are
        inside some other group, and the speakers that would not say: not errors, but
        the reasons a written `volume:` came out unheard, which is the thing somebody
        editing a profile needs to be told rather than left to guess.
        """
        if not dev["group"]:
            # One speaker: the connection this call plays through is that speaker's own
            # connection, so its level goes over it below, where it always has.
            return [], [], [], []
        rooms = [r for r in seen if not r.get("group")]
        written = {str(who): value for who, value in (self.cfg.members or {}).items()}
        written.update({str(who): value for who, value in (members or {}).items()})
        # Which rooms to ask. A name written down is matched against the speakers out
        # there, because a room that will not answer a question about who its groups are
        # is still the speaker this call is playing through; and the rooms nobody named
        # come from asking the speakers themselves, because the profile cannot know what
        # somebody added to the group in the Home app last week. Both halves are asked,
        # which means a call that names one room still asks who else is inside: the rooms
        # nobody named are owed the group's number, not left at whatever they were at.
        inside, outside, quiet = self._speakers_in_group(dev, rooms)
        asked: dict[str, tuple] = {}
        for rec in rooms:
            # A room that answered and said it is not inside this group is another
            # group's speaker: this call cannot make a noise through it, so it gets no
            # level written on it either. It is named in the log below instead.
            if rec["name"] in written and rec["name"] not in outside:
                asked[rec["name"]] = (rec, self._call_level(rec["name"], volume, members))
        for rec in inside:
            asked.setdefault(rec["name"], (rec, self._call_level(rec["name"], volume, members)))
        # Only the names the profile actually wrote are worth reporting: a speaker out
        # there that claims some other group is not news when nobody asked about it.
        outside_named = [who for who in outside if who in written]
        # The group's own name, if written, is not missing when no room answers: the
        # fallback that asks the group's receiver reads it with the same resolver.
        missing = [who for who in written if who not in asked and who not in outside
                   and not (who == dev["name"] and not asked)]
        return list(asked.values()), missing, outside_named, quiet

    def _speakers_in_group(self, dev, rooms) -> tuple[list, list[str], list[str]]:
        """Which of the speakers on this network the group we are playing through is made of.

        Neither the group's mDNS record nor its own receiver names the speakers inside
        it: both report the group's uuid and nothing else. What does answer is each
        physical speaker's setup endpoint, which says which groups *it* belongs to, so
        the list is built by asking every speaker at once and turning the answer inside
        out (see group_claims). Rooms are matched by uuid rather than by name, because a
        room renamed in the Google Home app is the same speaker it always was. The three
        answers split the rooms three ways: inside this group, answered and named only
        other groups, and answered nothing at all.
        """
        gid = _norm_id(dev.get("id"))
        answers = _ask_all([r["address"] for r in rooms],
                           lambda host: group_claims(host, timeout=self.MEMBER_SECONDS) if host else None,
                           self.MEMBER_SECONDS + 1.0)
        inside, outside, quiet = [], [], []
        for rec, claimed in zip(rooms, answers):
            if claimed is None:
                quiet.append(rec["name"])
            elif gid in claimed:
                inside.append(rec)
            else:
                outside.append(rec["name"])
        return inside, outside, quiet

    def _borrow_levels(self, wanted) -> list[str]:
        """Take each room's own level and put this call's level in its place.

        The taking is what makes a group's `volume:` mean something, and the giving
        back is what makes it honest: the profile asked for 40% for the length of a
        call, not for four rooms to be 40% until somebody notices. Every room is asked
        at the same time, because four rooms asked one after another is four seconds of
        an adhan's lead spent on nothing.
        """
        import pychromecast

        said = [line for line in _ask_all(
            wanted, lambda pair: self._borrow_one(pychromecast, pair[0], pair[1]),
            self.MEMBER_SECONDS + 2.0) if line]
        if said:
            log.info("%s: playing at %s, and each speaker goes back to the level it was at when the "
                     "call ends", self.cfg.name, "; ".join(said))
        return said

    def _borrow_one(self, pychromecast, rec, level) -> Optional[str]:
        """One room: connect, remember where its level was, ask for this call's level.

        Nothing about a room that will not answer stops the adhan. That speaker plays at
        whatever level it happens to be at, which is what the house would have heard
        anyway, and the log names the room and says why.
        """
        cast = None
        claimed = None
        # Read under the lock so the number this thread is answering for cannot change
        # between this line and the moment it decides whether its call is still current.
        with self._level_lock:
            my_no = self._call_no
        owner = (self, my_no)
        try:
            cast = pychromecast.get_chromecast_from_host(
                (rec["address"], rec["port"], UUID(rec["id"]), rec["model"], rec["name"]))
            # `wait()` is asked and ignored, for the reason spelled out below where the
            # speaker that carries the sound is connected: on a LAN where other programs
            # hold Cast channels open, it reports failure about a speaker that is
            # perfectly willing. The status message is the proof either way.
            cast.wait(timeout=self.MEMBER_SECONDS)
            if not self._await_status(cast, seconds=self.MEMBER_SECONDS):
                log.warning("%s: %s answered nothing about itself within %d seconds, so its level is "
                            "left where the Google Home app put it", self.cfg.name, rec["name"],
                            int(self.MEMBER_SECONDS))
                self._let_go(cast)
                return None
            original = _level_of(cast)
            key = _norm_id(rec.get("id")) or f"{rec.get('address')}:{rec.get('port')}"
            # Claimed before the write rather than after it, so that an output playing
            # through this same speaker at the same moment finds a level already spoken
            # for rather than a number it thinks nobody moved.
            back, others = LEVELS.claim(key, owner, self.cfg.name, level, original)
            claimed = key
            cast.set_volume(level)
            held = _Held(rec["name"], cast, back, level, key, owner)
            with self._level_lock:
                # Late in both directions: this call has already handed its rooms back,
                # or the call this thread was born in is over and a newer one is running.
                # Either way this level would be left moved underneath somebody else's
                # call, so the thread that moved it pays its own debt before it goes.
                late = self._levels_returned or self._call_no != my_no
                if not late:
                    self._held.append(held)
            if late:
                self._return_held([held])
                return None
            was = "no level at all" if back is None else f"{back:g}"
            shared = "" if not others else f", a level already held by {', '.join(others)}"
            return f"{rec['name']} from {was} to {level:g}{shared}"
        except Exception as exc:
            # pychromecast's family plus the socket under it: a speaker that walked out
            # of the conversation is a room that stays as it was, and says so.
            log.warning("%s: %s would not answer the ask to change its level: %s",
                        self.cfg.name, rec["name"], exc)
            if claimed is not None:
                # The write this claim was made for never happened, so this output moved
                # nothing and its name must not stay in the book holding off the hand-back
                # that another output owes on the same speaker.
                LEVELS.unclaim(claimed, owner)
            if cast is not None:
                self._let_go(cast)
            return None

    def _borrow_group_level(self, cast, level, key) -> _Held:
        """Ask a group's own receiver for a level, and hold the number rather than leave it.

        This is the one case where the group itself is asked: not one speaker inside it
        answered, so its receiver is the only address the call has, and a group assembled
        in a browser tab does answer to a level. Measured on a Home group, the ask does
        move the group's own number, which then drifts again by itself a minute later -
        so it is borrowed and paid back like a room's, and a number that moved on its own
        in the meantime is left where it is rather than rolled back over. It is written in
        the same book as a room's level, under the group's uuid, because two outputs can
        name the same group and one hand-back is the right answer there too.
        """
        with self._level_lock:
            owner = (self, self._call_no)
        original = _level_of(cast)
        back, _others = LEVELS.claim(key, owner, self.cfg.name, level, original)
        try:
            cast.set_volume(level)
        except Exception:
            # The claim was made and nothing was moved by it: see the room borrower that
            # cannot write, for why the name comes out of the book and the entry stays.
            LEVELS.unclaim(key, owner)
            raise
        return _Held(self.cfg.target, cast, back, level, key, owner)

    def _return_levels(self):
        """Hand every borrowed level back, because the call is over.

        Called from a finally, which is the only reason this happens after a play that
        failed halfway through as well as after one that worked: a room muezzin moved and
        did not move back is a hole in somebody's house, whatever else went wrong.
        """
        with self._level_lock:
            owed, self._held = self._held, []
            self._levels_returned = True
        self._return_held(owed)

    def _return_held(self, owed):
        for held in owed:
            self._return_one(held)
            self._let_go(held.cast)

    def _return_one(self, held):
        """Put one thing's level back, leaving its connection open for the caller.

        Shared by the rooms inside a group and by a group's own receiver, because the
        bargain is the same in both places: the level was borrowed for the length of a
        call, and a thing muezzin moved and did not move back is a hole in somebody's
        house, whatever else went wrong. What the number goes back to, and whether this
        output is the one that writes it, is decided by the shared book rather than here:
        the first output to pick a speaker's level up noted where it was, and the last one
        to put it down is the one that puts it back.
        """
        try:
            now = None if held.original is None else _level_of(held.cast)
            action, back, others = LEVELS.release(held.key, held.owner, now)
            if action == "held":
                # Another output in this same profile points at this speaker too, and is
                # still playing through it. Writing a number here would be two hand-backs
                # for one speaker, which is how a room used to end up at a level nobody
                # had chosen.
                log.info("%s: %s is still being held by %s, so its level goes back when the "
                         "last of them is done with it", self.cfg.name, held.name,
                         ", ".join(others))
                return
            if action == "moved":
                # Somebody moved this thing while the call was playing - the Home app, a
                # person at the speaker, or another of muezzin's own outputs writing a
                # level that is meant to stay put. Their ask is the newer one, so muezzin
                # keeps its hands off rather than rolling back a decision made in front of
                # them.
                log.info("%s: %s was moved to %g while the call was playing, and that ask is "
                         "newer than ours: leaving it there", self.cfg.name, held.name, now)
                return
            if action == "restore":
                held.cast.set_volume(back)
                LEVELS.finish(held.key)
            elif held.original is None:
                # Nothing to go back to. Saying which room and what it is now at is
                # the whole of it: muezzin will not invent a level for a room it was
                # never told about.
                log.warning("%s: %s never told muezzin what its own level was, so there is "
                            "nothing to put back: it is left at %g",
                            self.cfg.name, held.name, held.asked)
        except Exception as exc:
            # The debt is deliberately left in the book when the write fell over: a later
            # call to this speaker inherits the number it should go back to rather than
            # reading muezzin's own borrowed level as where the speaker lived.
            log.warning("%s: %s would not take its level back: %s", self.cfg.name, held.name, exc)

    def _let_go(self, cast):
        """Close a connection muezzin opened for a level and nothing else.

        Each of these is a receiver thread for as long as it is open, so a room that was
        only borrowed is let go of whether or not the level went back.
        """
        try:
            cast.disconnect()
        except Exception:
            pass

    def play(self, media, volume=None, members=None):
        import pychromecast

        if not self.cfg.target:
            raise BackendError(f"{self.cfg.name}: google_cast output needs a `target:` speaker or group name")
        dev, seen = find_cast(self.cfg.target)
        if dev is None:
            raise BackendError(
                f"{self.cfg.name}: no Cast device or group named {self.cfg.target!r}. "
                f"Seen on this LAN: {', '.join(d['name'] for d in seen) or 'nothing'}"
            )
        if not dev["id"] or not dev["address"]:
            raise BackendError(f"{self.cfg.name}: {dev['name']!r} advertised no uuid/address")
        # A group is not a thing with a level; see _wanted_levels. What the profile wrote
        # goes onto each speaker inside it, over a connection of that speaker's own, and
        # each one is put back afterwards. The group itself is still asked below, but only
        # when there is no speaker to ask, because a group assembled in a browser tab is
        # a different thing that does answer to it; what would be a lie is a log that
        # lets somebody read `volume: 0.4` and believe four rooms were asked for 40%.
        wanted, missing, outside, quiet = self._wanted_levels(dev, seen, volume, members)
        for who in missing:
            # Said once per name, like the two below: a room that is off will be named
            # at most once a day rather than five times, and a name that was never
            # right is not new news the fifth time either. A *different* name, though,
            # is different news and still gets said.
            if who in self._missing_said:
                continue
            self._missing_said.add(who)
            log.warning("%s: the profile gives a level to %s, which is not a speaker muezzin can see "
                        "on this network. Speakers it can see: %s",
                        self.cfg.name, who,
                        ", ".join(sorted(d["name"] for d in seen if not d.get("group"))) or "none")
        for who in outside:
            if who in self._outside_said:
                continue
            self._outside_said.add(who)
            log.warning("%s: the profile gives a level to %r, which answered that it is not "
                        "inside %r; its level is left alone",
                        self.cfg.name, who, self.cfg.target)
        if wanted:
            # A room that will not say who its groups are still gets nothing written on
            # it (there is no honest level to ask for if we do not know it is inside),
            # and in the common case - some rooms answered, this one slept through it -
            # nothing else in the log would ever name it.
            for who in quiet:
                if who in self._quiet_said:
                    continue
                self._quiet_said.add(who)
                log.warning("%s: %s would not say who is inside %r, so its level is left where "
                            "the Google Home app put it", self.cfg.name, who, self.cfg.target)
        if dev["group"] and not wanted and not self._group_level_said:
            self._group_level_said = True
            log.warning("%s: %s is a speaker group, so the level written for it (%s) is not a "
                        "level anyone will hear: a group's own number is a number its speakers "
                        "ignore, and not one speaker inside it answered. Silent speakers: %s. Set the "
                        "level in the Google Home app, name the rooms under `members:`, or give each "
                        "speaker its own output",
                        self.cfg.name, self.cfg.target, self.cfg.volume,
                        ", ".join(missing + quiet) or "none")
        # `id` in the _googlecast mDNS record is the device (or group) uuid.
        # From here the connection belongs to us, so the try starts at the moment
        # we make it: a speaker that is asleep or has a stale mDNS address fails
        # in `wait()`, and a socket left there keeps a receiver thread alive for
        # every event that ever tried to use it.
        cast = None
        # A group with no room to answer is asked for a level itself, over the
        # connection that carries its sound, and what it moved is remembered here so it
        # can go back while that connection is still open. `_held` cannot hold it: those
        # go back after this connection is closed, and a room connection is somebody
        # else's. None means no ask was made this call.
        group_held = None
        with self._level_lock:
            # A new call, so a new debt to pay. Whatever a previous call left behind has
            # already been handed back; a level thread still on its way from that call
            # will find its own number here is not the current one and pay its debt
            # itself, rather than join this call's list and hand back a level this call
            # has asked for since.
            self._call_no += 1
            self._levels_returned = False
            self._held = []
        try:
            cast = pychromecast.get_chromecast_from_host(
                (dev["address"], dev["port"], UUID(dev["id"]), dev["model"], dev["name"]))
            # `wait()` performs the handshake, but its verdict is not trusted.
            # Measured on a LAN where Chrome, Spotify and Steam each keep a Cast
            # channel open to every speaker, this receiver answered GET_STATUS,
            # accepted the volume and launched the media app, while `wait()`
            # reported failure because the reconnect that follows clears the flag
            # it checks. Gating on that wrote a healthy speaker off as asleep and
            # never sent it a byte. The status message is the proof of life, so
            # wait for that instead.
            cast.wait(timeout=15.0)
            if not self._await_status(cast):
                raise BackendError(f"{self.cfg.name}: {dev['name']!r} sent no receiver status "
                                   f"within {int(self.READY_SECONDS)} seconds, so nothing was "
                                   "sent to it")
            # The rooms are moved here rather than during discovery, with the thing that
            # carries the sound proved awake in front of us: a call that cannot make a
            # noise at all has no business changing four levels on its way to failing.
            if wanted:
                self._borrow_levels(wanted)
            elif dev["group"]:
                # Not one room answered, so the group's own receiver is the only address
                # this call has - and a group assembled in a browser tab does answer to a
                # level asked of it. The number is still borrowed rather than left,
                # because on a Home group it is a figure nobody hears, and a call nobody
                # can hear has no business leaving a new number in the Google Home app.
                group_held = self._borrow_group_level(cast, self._call_level(dev["name"], volume, members),
                                                      _norm_id(dev["id"]))
            mc = cast.media_controller
            # Held for the length of the playback, because that is the only way an ask
            # to stop can reach this speaker: the thread in front of these lines is
            # blocked until the recording ends, and a person who pressed Stop is asking
            # a different thread. Cleared in the finally below, which is also where a
            # connection that failed part way is let go of.
            with self._live_lock:
                self._asked = False
                self._live = [mc]
            for path in media:
                if not path.exists():
                    log.warning("missing media %s", path)
                    continue
                # A single speaker is asked over the connection that carries its sound,
                # and its level is the one the profile wrote for it, which is the level
                # that speaker stays at. A prayer may have named this speaker itself, in
                # which case that is the number asked for tonight and the profile's number
                # is the one for every other morning. A group is not asked here at all:
                # either its rooms carry the levels above, or its own number was borrowed
                # above and goes back when the call ends.
                if not dev["group"]:
                    cast.set_volume(self._call_level(dev["name"], volume, members))
                try:
                    # BUFFERED, not the library default of LIVE: these are finite
                    # files. Asked to play one as a live stream, a Nest sits on the
                    # last second of the adhan and then reports an error instead of
                    # saying it finished, which is exactly the difference between a
                    # delivered adhan and a silent speaker.
                    mc.play_media(self._url_for(path), _content_type(path),
                                  stream_type="BUFFERED")
                    mc.block_until_active(timeout=15)
                    # The device reports its own state; poll it instead of guessing the
                    # duration, so a long dua is not cut off and a dead stream is not
                    # waited on. Ending the watch at the first status that was not
                    # PLAYING was the old rule, and it stops before a short clip has
                    # really begun: a Nest given a four-second chime can be back at
                    # IDLE with the file loaded before the first poll lands, which then
                    # looks identical to a stream that never started. So the watch ends
                    # when the player has been seen playing and stopped, or when it has
                    # had its chance to start and did not.
                    #
                    # Measured on this LAN, on a night the network was unhappy: a group does
                    # not say BUFFERING only at the start of a file. It says it in the middle
                    # of one as well - PLAYING at 14:34:41, BUFFERING at 42.4 and again at
                    # 42.5 - which is what its members do when they fall out of step and take
                    # the stream again. Reading one poll of that as the end gave up on the
                    # call a second and a half in. The adhan played on regardless, because the
                    # quit goes to the group's receiver while the sound is being carried by
                    # its members - which is why nobody noticed for a day - but the quit also
                    # took with it the watch that was waiting for the file, and every room's
                    # borrowed level went back underneath the sound, so the call continued at
                    # the levels the house had chosen rather than the ones the profile asked
                    # for. Nothing was logged, because a buffering state is no error to
                    # report. So a state that is not playing has to outlast a poll of its own
                    # before it ends the watch, and a file that comes back to PLAYING gets the
                    # rest of its minutes.
                    started = False
                    stopped_for = 0
                    stalled = False
                    heard = time.time()     # the last moment the player said it was making
                    deadline = time.time() + self.max_play_seconds
                    may_give_up = time.time() + self.START_SECONDS
                    while time.time() < deadline:
                        time.sleep(self.poll_seconds)
                        mc.update_status()
                        state = getattr(mc.status, "player_state", None) if mc.status else None
                        if state == "PLAYING":
                            started = True
                            stopped_for = 0
                            heard = time.time()
                        elif self._asked:
                            # `self._asked` is the one that ends early: somebody
                            # pressed Stop, and this loop is what was waiting for the
                            # file to finish on its own. The speaker has already been
                            # told; here we simply stop watching and come back. It is
                            # checked before the BUFFERING branch, because a group that
                            # keeps saying BUFFERING after the stop would otherwise sit
                            # out its stall clock with the borrowed levels, and this
                            # output's remaining recordings queued behind it.
                            break
                        elif state == "BUFFERING":
                            # BUFFERING is not the end of the file - a group says it in
                            # the middle of one, above - so it does not feed the
                            # stopped_for count. What it does feed is the two clocks:
                            stopped_for = 0
                            if not started:
                                # A file that has never once said PLAYING gets
                                # START_SECONDS, BUFFERING included: a state that was
                                # BUFFERING from the first poll has not begun, and
                                # STALL_SECONDS is the allowance for a file that begun
                                # and fell silent, not a head start for one that never
                                # started. The line after the loop says which it was.
                                if time.time() >= may_give_up:
                                    break
                            elif time.time() - heard >= self.STALL_SECONDS:
                                # BUFFERING that never comes back is not a member falling
                                # out of step; that is a stream the network dropped. Waiting
                                # it out would hold the rooms at borrowed levels and keep the
                                # rest of this output's recordings waiting behind it, for as
                                # long as 30 minutes, over a speaker that has been silent the
                                # whole time. Give up and say so.
                                stalled = True
                                break
                        elif not started:
                            # Handed the file and nothing but silence back, so far: it gets
                            # START_SECONDS to say PLAYING once before that counts as
                            # unknown, which is the rule that was already there.
                            if time.time() >= may_give_up:
                                break
                        else:
                            stopped_for += 1
                            if stopped_for >= self.NOT_PLAYING_POLLS:
                                break
                except pychromecast.error.PyChromecastError as exc:
                    raise BackendError(
                        f"{self.cfg.name}: {dev['name']!r} would not play {path.name}: {exc}") from exc
                self._check_finished(dev["name"], path, mc.status, started, stalled)
                if self._asked:
                    # The next recording in the list does not get handed over after an
                    # ask to stop: the house asked for the sound to end, not for this
                    # one to end and the next one to begin.
                    break
        finally:
            with self._live_lock:
                self._live = []
            if cast is not None:
                try:
                    cast.quit_app()
                finally:
                    if group_held is not None:
                        # While this connection is still open. A room has a connection of
                        # its own to be paid back over, whenever the rooms' turn comes; a
                        # group has only the one that carried the sound, and closing it
                        # first would leave the number moved with nothing left to move it.
                        self._return_one(group_held)
                    cast.disconnect()
            # Last, and whatever happened above: the borrowed levels go back, whether the
            # play ran to its end, failed half-way, or was stopped by a person at the
            # page. The sound has already been stopped by here, so the numbers move with
            # nothing playing over them.
            self._return_levels()
        if self._asked:
            raise localplay.Stopped(f"{self.cfg.name}: {dev['name']!r} was stopped when asked")

    def _await_status(self, cast, seconds=None):
        """True as soon as the receiver has told us anything about itself.

        This is the first honest test of whether a speaker is really there: a
        Nest that has gone to sleep still answers mDNS, and the connection
        helper's own verdict is unreliable on a LAN where other apps already
        hold Cast channels. If no status ever arrives, nothing was sent and the
        caller should say so.
        """
        limit = time.time() + (self.READY_SECONDS if seconds is None else seconds)
        while getattr(cast, "status", None) is None and time.time() < limit:
            time.sleep(0.25)
        return getattr(cast, "status", None) is not None

    def _check_finished(self, name, path, status, started=True, stalled=False):
        """Say plainly whether the speaker really got to the end of the file.

        Returning success because the device is no longer playing is how a
        half-delivered adhan turns into a quiet morning: the receiver knows it
        failed, but the log and the web page would have said it played.
        """
        state = getattr(status, "player_state", None)
        reason = getattr(status, "idle_reason", None)
        if state == "PLAYING":
            raise BackendError(
                f"{self.cfg.name}: {path.name} was still playing on {name!r} after "
                f"{self.max_play_seconds // 60} minutes, so it was stopped")
        if reason == "ERROR":
            raise BackendError(
                f"{self.cfg.name}: {name!r} could not finish {path.name}; the speaker reported an "
                f"error (check that {self.cfg.name}'s media URL is reachable from the speaker)")
        if reason and reason != "FINISHED":
            if self._asked:
                # The house asked for this one to stop, so a speaker that came back
                # interrupted is the answer that was wanted rather than something to
                # worry about. It is still a line in the log, because a call to prayer
                # that is missing its end is a thing worth seeing in the morning.
                log.info("%s: %r stopped %s because you asked it to", self.cfg.name, name, path.name)
            else:
                log.warning("%s: %r stopped %s early (%s)", self.cfg.name, name, path.name, reason)
        elif stalled:
            # It said BUFFERING and never said PLAYING again, which is a stream the network
            # dropped rather than a member falling out of step. Whether anything was audible
            # during that stretch is not something the receiver will tell us, so say what it
            # looks like and where to look, rather than leaving the log saying the call was
            # delivered.
            log.warning("%s: %r went quiet in the middle of %s and never said it was playing "
                        "again for %d seconds; if the speaker stayed silent, the file was "
                        "dropped in transit", self.cfg.name, name, path.name,
                        int(self.STALL_SECONDS))
        elif state == "PAUSED" and started and not self._asked:
            # Not idle, not playing, and no reason given: something in the house paused
            # the file and left it there long enough for the watch to agree it was over.
            # The adhan began and then did not finish, and the log should not read as
            # though the call had been delivered whole.
            log.warning("%s: %r was left paused through %s and did not finish it",
                        self.cfg.name, name, path.name)
        elif not started:
            # The file was handed over and the speaker never once said PLAYING. It
            # either played something short entirely between two polls or it sat
            # silent, and the receiver cannot tell us which. Saying "played" would
            # be a guess, so name what is actually unknown.
            log.warning("%s: %r never reported playing %s; if the speaker stayed silent, check "
                        "that its media URL is reachable from the speaker",
                        self.cfg.name, name, path.name)


class LanBoxBackend(Backend):
    """A box on the LAN running the muezzin player (a Pi, another PC).

    Protocol: POST http://host:port/play with either {"urls": [...]} or
    {"files": {"name.mp3": "<base64>"}}. The box pulls the served URL when a
    media server is running, which keeps a long recording from passing through
    this process; otherwise muezzin sends the bytes itself, so a box that cannot
    route back still plays.

    There is no level in the request. A box is a computer: its volume is set on
    that box, by whoever uses it, and a daemon across the house has no business
    changing it. A daemon that still sends `volume` - an older one - is ignored.
    """
    kind = "lan_box"
    needs_urls = True
    # One request across the LAN and then the box starts its own player: a second
    # covers the round trip and the player waking up, and nothing more is owed.
    lead_seconds = 1.0

    def play(self, media, volume=None, members=None):
        host = self.cfg.host or self.cfg.target
        if not host:
            raise BackendError(f"{self.cfg.name}: lan_box output needs `host:`")
        port = self.cfg.port or 8090
        base = f"http://{host}:{port}"
        for path in media:
            if not path.exists():
                log.warning("missing media %s", path)
                continue
            if self.media_server is not None:
                # Preferred: the box pulls the file, so a long recording costs nothing here.
                payload = {"urls": [self._url_for(path)]}
            else:
                # Fallback: send the bytes inline, so the box needs no route back to this machine.
                payload = {"files": {path.name: base64.b64encode(path.read_bytes()).decode()}}
            body = json.dumps(payload).encode()
            req = urllib.request.Request(base + "/play", data=body,
                                         headers={"Content-Type": "application/json"})
            # The box plays inline: its answer to /play comes back when the recording
            # has finished, so this socket stays open for the whole of a recitation.
            # That is why the timeout is the same safety net every other backend uses
            # rather than a short one: a three-minute adhan over a wire is not a
            # failure, and a ten-second ask would report it as one while the box went on
            # playing. A box that has truly hung is let go of at the same moment a
            # stalled Cast stream is.
            with urllib.request.urlopen(req, timeout=self.max_play_seconds) as resp:
                if resp.status >= 300:
                    raise BackendError(f"{self.cfg.name}: {base}/play returned {resp.status}")
                said = (resp.read() or b"").strip()
            if said == b"stopped":
                # The box ended this one because somebody else asked it to. That is not
                # a failure, and the page that pressed Stop needs the same word back.
                raise localplay.Stopped(f"{self.cfg.name}: the box stopped {path.name} when asked")

    def stop(self):
        """Tell the box to put down whatever it is playing.

        The player is running over there, so the ask has to travel: the daemon's own
        thread is sitting in the POST that does not come back until a recording ends.
        A box from before this route existed answers 404, which is that box honestly
        saying it cannot be interrupted from here.
        """
        host = self.cfg.host or self.cfg.target
        if not host:
            return False
        port = self.cfg.port or 8090
        base = f"http://{host}:{port}"
        try:
            req = urllib.request.Request(base + "/stop", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                said = json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                log.warning("%s: the box at %s has no /stop route, so this version of it "
                            "cannot be interrupted from the daemon", self.cfg.name, base)
                return False
            raise BackendError(f"{self.cfg.name}: {base}/stop returned {exc.code}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise BackendError(f"{self.cfg.name}: the box at {base} would not answer: {exc}") from exc
        return int(said.get("stopped") or 0) > 0


# ---------------------------------------------------------------------------
# registry + discovery
# ---------------------------------------------------------------------------

KINDS = {
    "pc_speakers": PcSpeakersBackend,
    "file": FileBackend,
    "google_cast": CastBackend,
    "lan_box": LanBoxBackend,
}


def build(cfg, media_server=None) -> Backend:
    cls = KINDS.get(cfg.kind)
    if cls is None:
        raise BackendError(f"output {cfg.name!r}: unknown kind {cfg.kind!r} "
                           f"(known: {', '.join(sorted(KINDS))})")
    return cls(cfg, media_server)


def lead_for(cfg) -> float:
    """Seconds before the moment this output should start, per the profile or per
    what its kind of speaker costs. An output that says nothing takes the default
    for its kind; an output that says `lead_seconds: 0` starts exactly on time.
    """
    named = getattr(cfg, "lead_seconds", None)
    if named is not None:
        return max(0.0, float(named))
    cls = KINDS.get(getattr(cfg, "kind", None))
    return float(getattr(cls, "lead_seconds", 0.0)) if cls else 0.0


def _content_type(path: Path) -> str:
    """The type a Cast device is told the file is.

    This has to cover every suffix the web panel will accept as an upload, or a
    clip that uploads happily never plays on a speaker.
    """
    return {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
            ".wav": "audio/wav", ".wave": "audio/wav", ".ogg": "audio/ogg",
            ".oga": "audio/ogg", ".opus": "audio/opus", ".aac": "audio/aac",
            ".flac": "audio/flac"}.get(path.suffix.lower(), "application/octet-stream")


def local_ip() -> str:
    """Best-guess LAN address for the media server URL."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def browse_service(service_type: str, timeout: float = 4.0) -> list[dict]:
    """One mDNS query round for a service type; returns the raw records."""
    from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

    class Listener(ServiceListener):
        def __init__(self):
            self.found: list[dict] = []

        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name)
            if info is None:
                return                       # record not cached yet; the next scan will see it
            props = {}
            for k, v in (info.properties or {}).items():
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode(errors="replace") if isinstance(v, bytes) else v
                props[key] = val
            self.found.append({
                "instance": name,
                "server": info.server,
                "props": props,
                "addresses": [str(a) for a in info.parsed_addresses()],
                "port": info.port,
            })

        def remove_service(self, zc, type_, name):
            pass

        def update_service(self, zc, type_, name):
            pass

    listener = Listener()
    zc = Zeroconf()
    try:
        browser = ServiceBrowser(zc, service_type, listener)
        time.sleep(timeout)
        browser.cancel()
    finally:
        zc.close()
    # one record can arrive on several interfaces; keep one row per device
    unique = {(r["instance"], r["port"], tuple(r["addresses"])): r for r in listener.found}
    return sorted(unique.values(), key=lambda r: r["instance"])


def discover_cast(timeout: float = 4.0) -> list[dict]:
    """mDNS scan for Chromecast / Nest speakers and speaker groups."""
    rows = []
    for r in browse_service("_googlecast._tcp.local.", timeout):
        model = r["props"].get("md", "")
        rows.append({
            "name": r["props"].get("fn") or r["server"].split(".")[0],
            "model": model,
            "id": r["props"].get("id", ""),
            # Cast groups set the "ng" (group) property; the model name is the
            # reliable fallback across firmware versions.
            "group": bool(r["props"].get("ng")) or "cast group" in model.lower(),
            "address": r["addresses"][0] if r["addresses"] else "",
            "port": r["port"],
        })
    return sorted(rows, key=lambda d: (d["group"], d["name"]))


def discover_boxes(timeout: float = 4.0) -> list[dict]:
    """Speaker boxes on the LAN: the ones that speak muezzin's own protocol.

    `_muezzin._tcp` is what `muezzin box` advertises, and it is the only service
    type browsed here. A device that takes orders from some other program is not
    ours to send a recording to, and listing things a reader cannot use is noise
    at the exact moment they are choosing a speaker.
    """
    rows = []
    for r in browse_service("_muezzin._tcp.local.", timeout):
        rows.append({
            "name": r["props"].get("name") or r["server"].split(".")[0],
            "kind": "muezzin_box",
            "instance": r["instance"],
            "player": r["props"].get("player", ""),
            "address": r["addresses"][0] if r["addresses"] else "",
            "port": r["port"],
        })
    return sorted(rows, key=lambda d: (d["kind"], d["name"]))


def _norm_id(value) -> str:
    """Compare device uuids the way the devices themselves do not.

    A group's mDNS record writes its uuid with dashes, a speaker's writes it
    without, and the setup endpoint writes it with dashes again. Lower-cased and
    undecorated, they are the same thing.
    """
    return str(value or "").replace("-", "").strip().lower()


def group_claims(host: str, timeout: float = 6.0) -> Optional[set[str]]:
    """Ask one speaker which groups it belongs to, by uuid.

    Measured on this LAN: neither a group's mDNS record nor its own endpoint
    (port 32211 and friends) ever lists members - both report only the group uuid
    and the memberships of whichever speaker happens to lead it. What does answer
    is each physical speaker's setup endpoint, which names the groups *it* is in.
    So the mapping is built by asking every speaker and turning the answer inside
    out. None means the speaker did not answer, which is different from an empty
    set meaning it answered and belongs to no group.
    """
    try:
        from pychromecast import dial
    except ImportError:
        return None
    try:
        status = dial.get_multizone_status(host, timeout=timeout)
    except Exception:
        # any of urllib/OSError/ValueError; a speaker that will not talk about its
        # groups is a normal thing on a LAN, not a crash
        return None
    if status is None:
        return None
    return {_norm_id(g.uuid) for g in list(status.groups) + list(status.dynamic_groups)
            if g.uuid}


def attach_group_members(groups: list[dict], claims: dict[str, set[str]],
                         silent: list[str]) -> list[dict]:
    """Turn "every speaker's groups" into "every group's speakers".

    A group whose members all stayed silent is reported with empty members and
    the silent names attached, rather than as an empty group: "nobody answered"
    and "this group has no speakers in it" are different news, and only one of
    them should make you edit your profile.
    """
    out = []
    for g in groups:
        gid = _norm_id(g.get("id"))
        members = sorted(name for name, claimed in claims.items() if gid in claimed)
        out.append({**g, "members": members,
                    "membership_known": bool(claims),
                    "silent": sorted(silent)})
    return out


def scan_speakers(timeout: float = 5.0, ask_members: bool = True) -> dict:
    """One look at what can make sound on this network, groups unpacked.

    Discovery is not cached here on purpose: a speaker that was switched off, a
    group someone re-made in the Google Home app, a box that just came up - all of
    them are wrong news an hour later, and playback re-resolves by name anyway.
    """
    rows = discover_cast(timeout)
    speakers = [r for r in rows if not r["group"]]
    groups = [r for r in rows if r["group"]]
    claims: dict[str, set[str]] = {}
    silent: list[str] = []
    if ask_members:
        for s in speakers:
            if not s["address"]:
                silent.append(s["name"])
                continue
            got = group_claims(s["address"], timeout=timeout)
            if got is None:
                silent.append(s["name"])
            else:
                claims[s["name"]] = got
    return {
        "speakers": speakers,
        "groups": attach_group_members(groups, claims, silent),
        "boxes": discover_boxes(timeout),
        "asked": len(speakers),
        "silent": sorted(silent),
    }


def find_cast(target: str, tries: int = 2) -> tuple[Optional[dict], list[dict]]:
    """Look one device or group up by name.

    Nest speakers answer mDNS inconsistently - a Mini that has gone quiet often
    misses the first query round - so a second, longer scan is worth it before
    telling the user the speaker is gone.
    """
    seen: list[dict] = []
    for attempt in range(tries):
        seen = discover_cast(4.0 if attempt == 0 else 9.0)
        dev = next((d for d in seen if d["name"] == target), None)
        if dev is not None:
            return dev, seen
    return None, seen
