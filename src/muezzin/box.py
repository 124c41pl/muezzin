"""muezzin box: the player that runs on any machine that is only a speaker.

The machine running the daemon decides *when* and *what*; a box decides only
*where the sound comes out*. That split is deliberate: a player that also computes
its own times has to support your calculation, and a player built from a fixed list
of named methods stops at that list. Here the box never computes anything, so any
method the daemon can express plays on it.

A box is a normal process, so it runs wherever the rest of muezzin runs: a
Raspberry Pi, a second PC, a Mac in the hall cupboard. Which program makes the
sound is a question for localplay, and the answer is part of what the box reports
on `/status` and over mDNS, so you can see it in `muezzin devices`.

Wire protocol (plain HTTP + JSON, no auth, LAN only):

    GET  /ping            -> "Pong"
    GET  /status          -> {"name":..., "player":..., "last":...}
    POST /play            -> {"urls": ["http://.../fajr.mp3"],
                              "files": {"name.mp3": "<base64>"},
                              "volume": 0.0-1.0}

`urls` is preferred: the box pulls the file from the daemon's media server, so a
long recording never passes through the daemon. It is also the one part of this
protocol that makes a network request on the daemon's behalf, so the box will
only fetch from hosts you named with `--allow-host`; without it, `urls` is
refused and you use `files` instead. `volume` is honoured where this machine's
own playback can take it and only logged where it cannot - a command-line player
plays at the level that machine is already set to.

The box announces itself with mDNS as _muezzin._tcp so `muezzin devices` finds it
without anyone typing an address. That service type is our own, which is also the
rule for who may be driven: muezzin sends a recording to a device that advertises
this protocol, and to nothing else.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import shlex
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import localplay

log = logging.getLogger("muezzin.box")

SERVICE_TYPE = "_muezzin._tcp.local."

# A box sits on the LAN with no credentials in front of it, so every limit here
# is the only thing between "somebody's laptop sends it a request" and the box
# pulling a 4 GB file into RAM on a 1 GB Pi.
MAX_BODY_BYTES = 96 * 1024 * 1024      # the whole POST /play request
MAX_FILE_BYTES = 64 * 1024 * 1024      # one downloaded or inline recording
MAX_ITEMS_PER_PLAY = 20                # files/urls in one request

_SAFE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._()\[\]-]{0,120}")


class Box:
    def __init__(self, name: str, port: int = 8090, player: str | None = None,
                 allow_hosts: tuple[str, ...] = ()):
        self.name = name
        self.port = port
        # Which hosts this box is allowed to fetch a recording from. Naming them
        # is what turns "POST me a URL" from a way to make this box request
        # anything on the network - a router admin page, a link-local metadata
        # address, a file on this very machine - into a way to play the daemon's
        # own files.
        self.allow_hosts = tuple(str(h).strip().lower() for h in allow_hosts if str(h).strip())
        self.player_name, self.player_cmd = localplay.candidate()
        if player:
            self.player_cmd = shlex.split(player)   # a player path with a space in it is normal
            self.player_name = Path(self.player_cmd[0]).name
        self.last: dict = {}
        self._httpd: ThreadingHTTPServer | None = None
        self._zeroconf = None
        self._lock = threading.Lock()   # one adhan at a time, not two overlapping

    # -- playback ----------------------------------------------------------
    def play(self, urls: list[str], files: dict[str, str], volume: float | None) -> None:
        if self.player_name == "none":
            # Say so before pulling a recording across the network for nothing.
            raise RuntimeError(f"no player on this box. {localplay.install_advice()}")
        if len(urls) + len(files) > MAX_ITEMS_PER_PLAY:
            raise ValueError(f"too many files in one request ({MAX_ITEMS_PER_PLAY} at most)")
        paths: list[Path] = []
        with tempfile.TemporaryDirectory(prefix="muezzin-") as tmp:
            for url in urls:
                paths.append(self._download(url, Path(tmp)))
            for fname, blob in (files or {}).items():
                # the safe name is the one we build, never the one the client sent
                safe = Path(str(fname)).name
                if not _SAFE_NAME_RE.fullmatch(safe):
                    raise ValueError(f"refusing the file name {fname!r}")
                if len(blob) > MAX_FILE_BYTES * 4 // 3 + 4:
                    raise ValueError(f"{safe} is too big for one request")
                p = Path(tmp) / safe
                p.write_bytes(base64.b64decode(blob))
                paths.append(p)
            for p in paths:
                log.info("playing %s on this box (player: %s)", p.name, self.player_name)
                with self._lock:
                    localplay.play_file(p, volume=volume, player=self.player_cmd or None)
        self.last = {"played": [p.name for p in paths], "volume": volume}

    def _download(self, url: str, directory: Path) -> Path:
        """Fetch one recording, from an allowed host only, size-capped."""
        import urllib.request
        from urllib.parse import urlparse

        where = urlparse(str(url))
        if where.scheme not in ("http", "https"):
            raise ValueError(f"only http and https URLs can be played, not {where.scheme or 'nothing'!r}")
        host = (where.hostname or "").lower()
        if not self._allowed(host):
            raise ValueError(
                f"refusing to fetch from {host or 'that URL'}. Start the box with "
                f"--allow-host <the daemon's address> for the machine that serves your media; "
                f"currently allowed: {', '.join(self.allow_hosts) or 'nobody'}")
        name = Path(where.path).name or "media"
        if not _SAFE_NAME_RE.fullmatch(name):
            raise ValueError(f"refusing the file name {name!r}")
        dest = directory / name
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "muezzin-box"}),
                                    timeout=20) as resp:
            # Read it in pieces: an unbounded resp.read() on a Pi is a way to run
            # the box out of memory with one request.
            written = 0
            with dest.open("wb") as out:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_FILE_BYTES:
                        raise ValueError(f"{name} is bigger than {MAX_FILE_BYTES // 1024 // 1024} MB")
                    out.write(chunk)
        if written == 0:
            raise ValueError(f"{name} came back empty")
        return dest

    def _allowed(self, host: str) -> bool:
        for entry in self.allow_hosts:
            if host == entry or (entry.startswith(".") and host.endswith(entry)):
                return True
        return False

    # -- serving -----------------------------------------------------------
    def start(self) -> None:
        box = self

        class Handler(BaseHTTPRequestHandler):
            # A stalled or half-open client must not hold a thread forever: this
            # server puts no cap on threads, because a house has a handful of
            # speakers and a handful of daemons, not a crowd.
            timeout = 30

            def _send(self, code: int, body: str, ctype: str = "text/plain") -> None:
                payload = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                if self.path == "/ping":
                    self._send(200, "Pong")
                elif self.path == "/status":
                    self._send(200, json.dumps({"name": box.name, "player": box.player_name,
                                                "last": box.last}), "application/json")
                else:
                    self._send(404, "not found")

            def do_POST(self):
                if self.path != "/play":
                    return self._send(404, "not found")
                if self.headers.get("Transfer-Encoding"):
                    # Deliberately not implemented: this handler speaks HTTP/1.0,
                    # and a chunked body read as if it were not would let one
                    # request's body be read as the next request.
                    return self._send(501, "this box speaks HTTP/1.0 with Content-Length only")
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return self._send(400, "bad Content-Length")
                if length <= 0:
                    return self._send(400, "an empty body cannot ask for a playback")
                if length > MAX_BODY_BYTES:
                    return self._send(413, f"body over {MAX_BODY_BYTES // 1024 // 1024} MB")
                try:
                    data = json.loads(self.rfile.read(length) or b"{}")
                    box.play(list(data.get("urls") or []), dict(data.get("files") or {}),
                             data.get("volume"))
                    self._send(200, "ok")
                except Exception:              # never let a bad request kill the box
                    # The detail goes to the log, not the client: an exception's
                    # text names temp paths and this box's own files, and nobody
                    # on the LAN needs to be told that to fix their speaker config.
                    log.exception("play failed")
                    self._send(400, "playback refused; see the box log for the reason")

            def log_message(self, fmt, *args):
                log.debug("box http: " + fmt, *args)

        self._httpd = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, name="muezzin-box-http",
                         daemon=True).start()
        log.info("muezzin box %r listening on port %s (player: %s)", self.name, self.port,
                 self.player_name)

    def advertise(self) -> None:
        """Announce the box over mDNS so the daemon can find it without an IP."""
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            log.warning("zeroconf not installed; the box will not be discoverable")
            return
        from .backends import local_ip

        ip = local_ip()
        info = ServiceInfo(
            SERVICE_TYPE, f"{self.name}.{SERVICE_TYPE}",
            addresses=[_aton(ip)], port=self.port,
            properties={"name": self.name, "player": self.player_name},
            server=f"{self.name.lower().replace(' ', '-')}.local.",
        )
        self._zeroconf = Zeroconf()
        self._zeroconf.register_service(info)
        self._info = info
        log.info("advertising %s%s on %s", self.name, SERVICE_TYPE, ip)

    def run_forever(self) -> None:
        self.start()
        self.advertise()
        try:
            while True:
                threading.Event().wait(3600)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        if self._zeroconf is not None:
            try:
                self._zeroconf.unregister_service(self._info)
                self._zeroconf.close()
            except Exception:
                pass
            self._zeroconf = None
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def _aton(ip: str) -> bytes:
    import socket
    try:
        return socket.inet_aton(ip)
    except OSError:
        return socket.inet_aton("127.0.0.1")
