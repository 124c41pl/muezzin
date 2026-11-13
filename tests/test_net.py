"""muezzin runs three HTTP servers — the panel, the media server, and a box's own
— and none of them may stop to ask the network who this machine is.

The standard library's HTTP server does ask, as part of binding. On a machine
whose own name nothing resolves the answer is not "no" but a timeout: measuring
on an arm64 macOS runner on 2026-11-13, constructing a server there took 35.0
seconds and `socket.getfqdn()` took 70.0, while the same code on Linux and on
Windows took no measurable time. That is not only a CI curiosity — `raspberrypi`
with no DNS entry is a machine in that situation forever, and a daemon that says
nothing for half a minute before its port opens looks like one that is broken.
So `muezzin.net.LANServer` binds without asking, and these tests keep it that
way: `refuse_to_ask` makes the question raise, which is a sharper guard than
timing anything.
"""
from __future__ import annotations

import http.server
import socket

import pytest

from muezzin import net
from muezzin.box import Box
from muezzin.media import MediaServer
from muezzin.scheduler import Runner
from muezzin.web import WebPanel

from test_scheduler import profile_for


class Quiet(http.server.BaseHTTPRequestHandler):
    """A handler that says nothing about the request, so a test's output stays
    about the server and not about a line of stderr."""

    def log_message(self, fmt, *args):
        pass


def refuse_to_ask(monkeypatch):
    """Make the question the standard library asks impossible to answer politely."""
    def boom(*args):
        raise AssertionError("a muezzin server asked the network who this machine is")
    monkeypatch.setattr(socket, "getfqdn", boom)


def test_binding_a_server_does_not_ask_the_network_who_this_machine_is(monkeypatch):
    refuse_to_ask(monkeypatch)
    srv = net.LANServer(("127.0.0.1", 0), Quiet)
    try:
        # The two attributes the standard library fills in from that question are
        # still filled in, from what the socket itself knows.
        assert srv.server_name == "127.0.0.1"
        assert srv.server_port == srv.server_address[1] > 0
    finally:
        srv.server_close()


def test_the_standard_library_class_does_ask(monkeypatch):
    """Not muezzin's code, but the reason net.py exists. If upstream ever stops
    asking, this test is the one to delete — and the override becomes harmless."""
    refuse_to_ask(monkeypatch)
    with pytest.raises(AssertionError):
        http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet).server_close()


def test_the_port_handed_back_after_binding_zero_is_a_real_port():
    srv = net.LANServer(("127.0.0.1", 0), Quiet)
    try:
        assert srv.server_port != 0
        assert srv.server_port == srv.server_address[1]
    finally:
        srv.server_close()


def test_the_panel_media_server_and_box_all_bind_without_asking(tmp_path, monkeypatch):
    """All three servers, in one go: if any of them goes back to the stock class,
    this fails where it happens rather than as a suite that slows to a crawl."""
    refuse_to_ask(monkeypatch)

    media = MediaServer(tmp_path, port=0)
    media.start()
    profile, _ = profile_for(tmp_path)
    runner = Runner(profile)
    web = WebPanel(runner, port=0)
    web.start()
    box = Box("net-check", port=0)
    box.start()
    try:
        for server in (media._httpd, web._httpd, box._httpd):
            assert isinstance(server, net.LANServer)
            assert server.server_port != 0
    finally:
        box.shutdown()
        web.stop()
        runner.shutdown()
        media.stop()
