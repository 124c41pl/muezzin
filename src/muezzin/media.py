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

from .backends import local_ip

log = logging.getLogger("muezzin.media")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    # A speaker that opens a connection and then says nothing must not occupy a
    # thread for the rest of the day.
    timeout = 20

    def log_message(self, fmt, *args):
        log.debug("media http: " + fmt, *args)

    def send_head(self):
        """Answer for one file at a time; never hand out a listing.

        A Nest is only ever told the name of one recording, so a directory list
        would tell a stranger on the wifi which mornings this house keeps - and
        what else the person who set this up happened to put in the folder.
        """
        if os.path.isdir(self.translate_path(self.path)):
            self.send_error(HTTPStatus.NOT_FOUND, "the media folder is not browsable")
            return None
        return super().send_head()


class MediaServer:
    def __init__(self, media_dir: Path, port: int = 8010):
        self.media_dir = Path(media_dir)
        self.port = port
        self._ip: str | None = None
        self._ip_at = 0.0
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

    def url_for(self, path: Path) -> str:
        path = Path(path)
        try:
            rel = path.resolve().relative_to(self.media_dir.resolve())
        except ValueError:
            raise ValueError(f"{path} is not inside the media dir {self.media_dir}; "
                             f"Cast devices can only be given files from media_dir")
        from urllib.parse import quote
        return f"http://{self.host_ip}:{self.port}/{quote(str(rel).replace(chr(92), '/'))}"

    def start(self) -> None:
        if self._httpd:
            return
        handler = functools.partial(_QuietHandler, directory=str(self.media_dir))
        self._httpd = http.server.ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="muezzin-media", daemon=True)
        self._thread.start()
        log.info("media server serving %s at http://%s:%s", self.media_dir, self.host_ip, self.port)

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
