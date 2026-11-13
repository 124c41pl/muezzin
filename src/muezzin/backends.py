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
import ctypes
import json
import logging
import socket
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional
from uuid import UUID

log = logging.getLogger("muezzin.backends")


class BackendError(RuntimeError):
    pass


class Backend(abc.ABC):
    kind = "?"
    # True for devices that can only play a URL they fetch themselves, which is
    # what makes muezzin start the little media server.
    needs_urls = False
    # Safety net so a stream that stalls cannot block the rest of the day's jobs.
    max_play_seconds = 30 * 60

    def __init__(self, cfg, media_server=None):
        self.cfg = cfg
        self.media_server = media_server

    @abc.abstractmethod
    def play(self, media: list[Path], volume: Optional[float] = None) -> None:
        ...

    def close(self) -> None:
        pass

    # helpers ---------------------------------------------------------------
    def _effective_volume(self, volume: Optional[float]) -> float:
        v = self.cfg.volume if volume is None else volume
        return max(0.0, min(1.0, float(v)))

    def _url_for(self, path: Path) -> str:
        if self.media_server is None:
            raise BackendError(f"{self.cfg.name}: {self.kind} needs a media URL but no media server "
                               f"is running (set http_port in the profile)")
        return self.media_server.url_for(path)


# ---------------------------------------------------------------------------
# the machine running muezzin
# ---------------------------------------------------------------------------

class PcSpeakersBackend(Backend):
    """Play on the local machine's default output device.

    On Windows this uses MCI (winmm), which handles wav/mp3 with no dependencies
    and no extra services. MCI has no per-device routing - it is the system
    default device - so send sound to a specific speaker by making that device
    the Windows default, or use a cast/lan_box output for real routing.
    """
    kind = "pc_speakers"

    def play(self, media, volume=None):
        if sys.platform != "win32":
            raise BackendError(f"{self.cfg.name}: pc_speakers playback is only implemented for Windows")
        vol = int(self._effective_volume(volume) * 1000)
        alias = f"azk{abs(id(self)) % 1000}"
        winmm = ctypes.windll.winmm
        buf = ctypes.create_unicode_buffer(512)
        err = ctypes.create_unicode_buffer(512)
        for path in media:
            if not path.exists():
                log.warning("missing media %s", path)
                continue
            for cmd in (f'open "{path}" type mpegvideo alias {alias}',
                        f'setvolume {alias} {vol}',
                        f'play {alias} wait',
                        f'close {alias}'):
                rc = winmm.mciSendStringW(cmd, buf, 512, 0)
                if rc != 0:
                    winmm.mciGetErrorStringW(rc, err, 512)
                    raise BackendError(f"{self.cfg.name}: MCI '{cmd.split()[0]}' failed ({rc}): {err.value}")

    def close(self):
        pass


class FileBackend(Backend):
    """Copy media into a directory. For testing, and for handing adhan to other software."""
    kind = "file"

    def play(self, media, volume=None):
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

class CastBackend(Backend):
    """Google Nest / Chromecast speakers, and Google home speaker GROUPS.

    A Cast device plays a URL it can fetch, so muezzin serves the media
    directory over HTTP on the LAN (see media_server). Discovery is mDNS, so no
    Google account, cloud call or pairing token is involved - which is why this
    keeps working when the internet is down.
    """
    kind = "google_cast"
    needs_urls = True
    READY_SECONDS = 15.0    # how long the speaker has to send its first status
    START_SECONDS = 10.0    # how long it has to say PLAYING once handed a file
    poll_seconds = 1.0      # how often to ask; a test may shrink it

    def play(self, media, volume=None):
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
        # `id` in the _googlecast mDNS record is the device (or group) uuid.
        # From here the connection belongs to us, so the try starts at the moment
        # we make it: a speaker that is asleep or has a stale mDNS address fails
        # in `wait()`, and a socket left there keeps a receiver thread alive for
        # every event that ever tried to use it.
        cast = None
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
            mc = cast.media_controller
            for path in media:
                if not path.exists():
                    log.warning("missing media %s", path)
                    continue
                cast.set_volume(self._effective_volume(volume))
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
                    started = False
                    deadline = time.time() + self.max_play_seconds
                    may_give_up = time.time() + self.START_SECONDS
                    while time.time() < deadline:
                        time.sleep(self.poll_seconds)
                        mc.update_status()
                        state = getattr(mc.status, "player_state", None) if mc.status else None
                        if state == "PLAYING":
                            started = True
                        elif started or time.time() >= may_give_up:
                            break
                except pychromecast.error.PyChromecastError as exc:
                    raise BackendError(
                        f"{self.cfg.name}: {dev['name']!r} would not play {path.name}: {exc}") from exc
                self._check_finished(dev["name"], path, mc.status, started)
        finally:
            if cast is not None:
                try:
                    cast.quit_app()
                finally:
                    cast.disconnect()

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

    def _check_finished(self, name, path, status, started=True):
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
            log.warning("%s: %r stopped %s early (%s)", self.cfg.name, name, path.name, reason)
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

    Protocol: POST http://host:port/play {"files": [...], "volume": 0..1}.
    The box pulls the served URL when `use_urls` is set, otherwise muezzin
    streams the file bytes as the request body. This is the same shape as Smart
    Azan's "Pi button scans the network and issues commands" flow, but the
    device list and the audio are ours, so the media is not limited to URLs.
    """
    kind = "lan_box"
    needs_urls = True

    def play(self, media, volume=None):
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
                payload = {"urls": [self._url_for(path)], "volume": self._effective_volume(volume)}
            else:
                # Fallback: send the bytes inline, so the box needs no route back to this machine.
                payload = {"files": {path.name: base64.b64encode(path.read_bytes()).decode()},
                           "volume": self._effective_volume(volume)}
            body = json.dumps(payload).encode()
            req = urllib.request.Request(base + "/play", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status >= 300:
                    raise BackendError(f"{self.cfg.name}: {base}/play returned {resp.status}")


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
