"""Byte-range serving: the answer both file servers share.

A `Range` header is what makes a seek bar work in a browser, and what lets a speaker
that lost its connection come back for the rest of a file instead of starting the
recitation over. muezzin hands recordings out in two places - the panel's preview and
the media server a Cast speaker fetches from - so this is one piece of arithmetic for
both, tested here without either server in the way.
"""
from __future__ import annotations

import pytest

from muezzin import fileserve


def test_the_arithmetic_of_what_a_client_asks_for():
    """A range is two byte numbers, inclusive at both ends, and the awkward shapes all
    have a defined answer: an ask that runs past the end stops at the end, and an ask
    for more than the file holds is the whole file rather than a refusal."""
    assert fileserve.plan(None, 100) is None
    assert fileserve.plan("", 100) is None
    assert fileserve.plan("bytes=0-9", 100) == (0, 9)
    assert fileserve.plan("bytes=40-", 100) == (40, 99)
    assert fileserve.plan("bytes=-20", 100) == (80, 99)
    assert fileserve.plan("bytes=90-500", 100) == (90, 99)
    assert fileserve.plan("bytes=-9000", 100) == (0, 99)
    assert fileserve.plan("bytes=0-0", 100) == (0, 0)


def test_an_ask_this_server_cannot_read_is_ignored_not_refused():
    """RFC 9110 lets a server ignore a Range it does not understand, and the answer
    every client can handle is the whole file. Speaker firmware that always sends a
    two-range request is better served by the recording than by a multipart body it
    has no way to read."""
    for header in ("bytes=0-9, 20-29", "items=0-9", "bytes=", "bytes=abc-def", "0-9", None):
        assert fileserve.plan(header, 100) is None, header


def test_an_ask_for_bytes_that_are_not_there_is_refused():
    """The difference between "I cannot read that ask" and "those bytes are not in
    this file": a client with a wrong idea about a recording's length has to be told,
    or it asks again. The message says how long the file actually is, which is the one
    piece of information that fixes its idea."""
    with pytest.raises(fileserve.BadRange) as caught:
        fileserve.plan("bytes=100-", 100)
    assert "100 bytes" in str(caught.value)
    with pytest.raises(fileserve.BadRange):
        fileserve.plan("bytes=50-20", 100)
    with pytest.raises(fileserve.BadRange):
        fileserve.plan("bytes=-0", 100)


class _Client:
    """Stand-in for a request handler: keeps the headers it was told to send and the
    bytes that came after them, and stands in for the socket as well."""

    def __init__(self, command="GET"):
        self.command = command
        self.status = None
        self.out = []
        self.body = bytearray()
        self.wfile = self

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.out.append((key, value))

    def end_headers(self):
        self.out.append(("", ""))

    def write(self, data):
        self.body += data

    @property
    def sent(self):
        return dict(self.out)


def test_the_whole_file_is_still_the_answer_to_a_plain_request(tmp_path):
    path = tmp_path / "adhan.mp3"
    path.write_bytes(b"a" * 5000)
    client = _Client()
    assert fileserve.deliver(client, path, "audio/mpeg") == 5000
    assert client.status == 200
    assert client.sent["Content-Length"] == "5000"
    # Said even for a request that did not ask for a piece: this is the header that
    # tells a browser the file can be had in pieces, which is what makes a seek bar
    # something a browser is willing to show in the first place.
    assert client.sent["Accept-Ranges"] == "bytes"
    assert "Content-Range" not in client.sent
    assert bytes(client.body) == path.read_bytes()


def test_a_piece_comes_back_as_206_naming_the_whole_file(tmp_path):
    """A 206 without Content-Range is a body a client cannot place, so the piece
    always says where it sits inside the file it came from."""
    path = tmp_path / "adhan.wav"
    path.write_bytes(bytes(range(256)) * 8)
    client = _Client()
    span = fileserve.plan("bytes=1000-", path.stat().st_size)
    assert fileserve.deliver(client, path, "audio/wav", span) == 2048 - 1000
    assert client.status == 206
    assert client.sent["Content-Range"] == "bytes 1000-2047/2048"
    assert client.sent["Content-Length"] == "1048"
    assert bytes(client.body) == path.read_bytes()[1000:]


def test_a_head_request_gets_the_length_and_no_body(tmp_path):
    """What a speaker checking whether a recording is still there asks for. The
    headers say everything about the file; the bytes would be wasted across the
    LAN."""
    path = tmp_path / "check.mp3"
    path.write_bytes(b"z" * 300)
    client = _Client(command="HEAD")
    assert fileserve.deliver(client, path, "audio/mpeg") == 0
    assert client.status == 200
    assert client.sent["Content-Length"] == "300"
    assert client.body == bytearray()


def test_the_refusal_names_the_length_the_client_got_wrong(tmp_path):
    """416 alone does not help: the client asked for byte 500000 because it believes the
    file is at least that long. `Content-Range: bytes */40000` is the number that ends
    the loop, and the reason goes out as plain text because the client here is a
    speaker's firmware or a browser's media element, and neither reads a body."""
    client = _Client()
    fileserve.refuse(client, 40000, "bytes=500000-: this recording is 40000 bytes")
    assert client.status == 416
    assert client.sent["Content-Range"] == "bytes */40000"
    assert client.sent["Accept-Ranges"] == "bytes"
    assert client.sent["Content-Length"] == str(len(bytes(client.body)))
    assert b"40000 bytes" in bytes(client.body)


def test_the_pieces_are_small_and_still_every_byte(tmp_path, monkeypatch):
    """The 64 KB chunks are an implementation detail, so the test shrinks them: a seek
    into the middle of a real recitation must not turn into reading all of it into
    memory on a machine that is also keeping a schedule."""
    monkeypatch.setattr(fileserve, "CHUNK", 7)
    path = tmp_path / "small.mp3"
    path.write_bytes(b"0123456789" * 5)
    client = _Client()
    assert fileserve.deliver(client, path, "audio/mpeg", fileserve.plan("bytes=3-11", 50)) == 9
    assert bytes(client.body) == b"345678901"
