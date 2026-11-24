"""Serve the media directory on the LAN so Cast devices can fetch it.

Cast/Nest playback is URL-based, so a daemon that wants to play a local adhan
file has to hand the speaker a URL it can reach. This is a plain HTTP server on
the LAN interface with no auth - the same tradeoff any local cast sender makes.
"""
from __future__ import annotations

import functools
import http.server
import logging
import os
import threading
import time
from http import HTTPStatus
from pathlib import Path

from . import fileserve, net
from .backends import local_ip

log = logging.getLogger("muezzin.media")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    # A speaker that opens a connection and then says nothing must not occupy a
    # thread for the rest of the day.
    timeout = 20

    def log_message(self, fmt, *args):
        log.debug("media http: " + fmt, *args)

    def _one_file(self):
        """The recording this request is for, or None if it answered for itself.

        Never a listing. A Nest is only ever told the name of one recording, so a
        directory list would tell a stranger on the wifi which mornings this house
        keeps - and what else the person who set this up happened to put in the
        folder.
        """
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            self.send_error(HTTPStatus.NOT_FOUND, "the media folder is not browsable")
            return None
        if not os.path.isfile(path):
            self.send_error(HTTPStatus.NOT_FOUND, "no such recording in the media folder")
            return None
        return path

    def do_GET(self):
        path = self._one_file()
        if path is None:
            return
        try:
            span = fileserve.plan(self.headers.get("Range"), os.path.getsize(path))
        except fileserve.BadRange as exc:
            # The same answer the panel gives: the length the device got wrong, in a
            # header, so a speaker with a stale idea of a recording stops asking for
            # bytes that were never in it.
            fileserve.refuse(self, os.path.getsize(path), str(exc))
            return
        try:
            fileserve.deliver(self, Path(path), self.guess_type(path), span)
        except (BrokenPipeError, ConnectionResetError):
            # The speaker stopped listening. A device that was only checking a file
            # is there often reads the headers and hangs up, which is not an error.
            self.close_connection = True

    # The same answer without the bytes: a device asking how long a recording is, or
    # whether it is still there, gets the headers and nothing else.
    do_HEAD = do_GET


class MediaServer:
    def __init__(self, media_dir: Path, port: int = 8010):
        self.media_dir = Path(media_dir)
        self.port = port
        self._ip: str | None = None
        self._ip_at = 0.0
        # the same question asked per device, and answered just as freshly
        self._peers: dict[str, tuple[str, float]] = {}
        self._httpd = None
        self._thread = None

    @property
    def host_ip(self) -> str:
        """The address to hand a speaker, worked out again every few minutes.

        Fixed at start-up it goes quietly wrong: the laptop moves from wifi to
        ethernet, or the router hands out a new lease, and every speaker then
        fails to fetch a file that is sitting right there - at 5 am, while
        nobody is looking at the log.
        """
        if self._ip is None or time.time() - self._ip_at > 300:
            ip = local_ip()
            if self._ip is None or ip != "127.0.0.1":
                self._ip, self._ip_at = ip, time.time()
        return self._ip

    def host_ip_for(self, peer: str | None) -> str:
        """The address to hand one particular device.

        This machine's default-route address is the wrong answer wherever another
        network also leads out of it, and that is now ordinary: a mesh VPN adapter
        on the same box takes the default route, so the address every speaker is
        handed belongs to a network the speaker has no route back into. The device
        is asked instead - which of my addresses does this machine use to reach
        you - and its answer is the URL that device can fetch.
        """
        if not peer:
            return self.host_ip
        now = time.time()
        hit = self._peers.get(peer)
        if hit is None or now - hit[1] > 300:
            self._peers[peer] = (local_ip(peer), now)
        return self._peers[peer][0]

    def url_for(self, path: Path, peer: str | None = None) -> str:
        path = Path(path)
        try:
            rel = path.resolve().relative_to(self.media_dir.resolve())
        except ValueError:
            raise ValueError(f"{path} is not inside the media dir {self.media_dir}; "
                             f"Cast devices can only be given files from media_dir")
        from urllib.parse import quote
        return f"http://{self.host_ip_for(peer)}:{self.port}/{quote(str(rel).replace(chr(92), '/'))}"

    def start(self) -> None:
        if self._httpd:
            return
        handler = functools.partial(_QuietHandler, directory=str(self.media_dir))
        # LANServer rather than the standard library's class: see net.py.
        self._httpd = net.LANServer(("0.0.0.0", self.port), handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="muezzin-media", daemon=True)
        self._thread.start()
        log.info("media server serving %s on port %s; a device is handed the address of this "
                 "machine that reaches its network, which is not always %s",
                 self.media_dir, self.port, self.host_ip)

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
