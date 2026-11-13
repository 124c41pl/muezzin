"""The box protocol: what the daemon sends and what a speaker box accepts, on
whichever machine each of them landed on. Kept device-free so it runs anywhere."""
from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from muezzin.box import Box

# a stub "player": copy the file it was handed to a marker path so the test can
# see exactly what reached the speaker
STUB = "import shutil,sys; shutil.copyfile(sys.argv[2], sys.argv[1])"


@pytest.fixture
def box(tmp_path):
    marker = tmp_path / "marker"
    b = Box("test-box", port=0)
    b.player_name = "stub"
    b.player_cmd = [sys.executable, "-c", STUB, str(marker)]
    b.start()
    yield b, marker
    b.shutdown()


def post(box, payload):
    req = urllib.request.Request(f"http://127.0.0.1:{box.port}/play",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, resp.read()


def get(box, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{box.port}{path}", timeout=10) as resp:
        return resp.status, resp.read()


def test_ping_answers(box):
    b, _ = box
    assert get(b, "/ping") == (200, b"Pong")


def test_box_decodes_an_inlined_file_and_hands_the_player_a_real_file(box):
    """Small media goes as base64 so a box that cannot route back to the daemon
    still gets it. The body also carries a volume, as a daemon written before the
    rule that a box's own level is none of the network's business would send one:
    it arrives, changes nothing, and is not remembered."""
    b, marker = box
    payload = {"files": {"fajr.mp3": base64.b64encode(b"ID3\x03real-audio").decode()}, "volume": 0.4}
    status, body = post(b, payload)
    assert status == 200 and body == b"ok"
    assert marker.read_bytes() == b"ID3\x03real-audio"
    assert b.last["played"] == ["fajr.mp3"]
    assert "volume" not in b.last, "a stray volume must not be remembered as if it did something"


def test_box_fetches_a_url_instead_of_waiting_for_an_upload(box):
    """Big recordings stream: the daemon sends a URL and the speaker pulls it."""
    b, marker = box

    def fake_download(url, directory):
        dest = Path(directory) / "long-recording.mp3"
        dest.write_bytes(b"from-the-media-server")
        return dest

    b._download = fake_download
    status, _ = post(b, {"urls": ["http://192.168.0.5:8010/long-recording.mp3"]})
    assert status == 200
    assert marker.read_bytes() == b"from-the-media-server"


def test_path_in_a_filename_is_not_followed_outside_the_temp_dir(box):
    """A crafted name must not make the box write into the filesystem."""
    b, marker = box
    evil = "../../../../Windows/TMPCLEANME"
    status, body = post(b, {"files": {evil: base64.b64encode(b"x").decode()}})
    assert status == 200
    assert b.last["played"] == ["TMPCLEANME"]      # basename only, inside the temp dir


def test_bad_json_is_a_400_not_a_dead_box(box):
    b, _ = box
    req = urllib.request.Request(f"http://127.0.0.1:{b.port}/play", data=b"{not json",
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected 400")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
    assert get(b, "/ping") == (200, b"Pong"), "the box survived a bad request"


def test_unknown_paths_are_404(box):
    b, _ = box
    assert get(b, "/status")[0] == 200
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(b, "/api/exeCommand")
    assert exc.value.code == 404, "the box exposes exactly the verbs it documents"


# ---- what a stranger on the wifi may not ask a $25 speaker to do ----

@pytest.fixture
def guarded(tmp_path):
    """A box that was told which machine serves the daemon's media, which is the
    only reason `urls:` is a safe thing to accept at all."""
    marker = tmp_path / "marker"
    b = Box("guarded-box", port=0,
            allow_hosts=("192.168.0.5", "media.home.local", ".media.home.local"))
    b.player_name = "stub"
    b.player_cmd = [sys.executable, "-c", STUB, str(marker)]
    b.start()
    yield b, marker
    b.shutdown()


def post_status(b, payload):
    """(status, did it raise) - the refusals are expected answers here."""
    try:
        return post(b, payload)[0]
    except urllib.error.HTTPError as exc:
        return exc.code


def test_a_url_from_anywhere_else_is_not_fetched(guarded, caplog):
    """`urls:` asks the box to make a request. Pointed at a router admin page, a
    cloud metadata address or a phone, that is no longer a speaker feature."""
    b, marker = guarded
    for bad in ("http://evil.example/fajr.mp3", "http://192.168.0.6:8010/fajr.mp3",
                "http://169.254.169.254/latest/meta-data/", "http://[::1]:631/printers"):
        assert post_status(b, {"urls": [bad]}) == 400
    assert "allow-host" in caplog.text
    assert not marker.exists(), "a refused URL must never reach the player"


def test_only_http_and_https_are_fetchable(guarded, caplog):
    b, _ = guarded
    assert post_status(b, {"urls": ["file:///etc/passwd"]}) == 400
    assert post_status(b, {"urls": ["ftp://192.168.0.5/fajr.mp3"]}) == 400
    assert "only http and https" in caplog.text


def test_an_allowed_name_can_cover_the_machine_under_it(guarded):
    """`--allow-host 192.168.0.5` is one machine. A name that starts with a dot
    is that name and anything beneath it, which is how a household that serves
    its media at daem0n.media.local survives the box being rebuilt; the dot is
    what stops a bare name from quietly becoming a wildcard."""
    b, _ = guarded
    for host in ("192.168.0.5", "media.home.local", "daem0n.media.home.local"):
        assert b._allowed(host), host
    for host in ("192.168.0.6", "home.local", "media.home.local.evil.example", ""):
        assert not b._allowed(host), host


def test_one_play_is_a_couple_of_files_not_a_thousand(guarded, caplog):
    b, _ = guarded
    many = [f"http://192.168.0.5:8010/{i}.mp3" for i in range(21)]
    assert post_status(b, {"urls": many}) == 400
    assert "at most" in caplog.text


def test_an_inline_file_bigger_than_the_cap_is_refused_before_it_lands(guarded, caplog, monkeypatch):
    """A base64 blob is decoded into memory; without a cap a 20 MB Pi has to be
    asked nicely to run out of it."""
    from muezzin import box as box_module

    monkeypatch.setattr(box_module, "MAX_FILE_BYTES", 1024)
    b, marker = guarded
    big = base64.b64encode(b"x" * 4096).decode()
    assert post_status(b, {"files": {"big.mp3": big}}) == 400
    assert "too big" in caplog.text and not marker.exists()


def test_a_file_name_that_is_not_a_plain_file_name_is_refused(guarded):
    """Names end up on a command line for the player, and hidden or decorated
    ones are not what a recording is called."""
    b, marker = guarded
    for bad in ("../../.secret", "fajr;rm -rf.mp3", "fajr%00.mp3", "x" * 200 + ".mp3"):
        assert post_status(b, {"files": {bad: base64.b64encode(b"x").decode()}}) == 400
    assert not marker.exists()


def test_an_empty_body_is_refused(box):
    """A POST with nothing in it is a scanner, not a playback request; answer it
    without pretending to have played something."""
    b, _ = box
    req = urllib.request.Request(f"http://127.0.0.1:{b.port}/play", data=b"",
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected 400")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
    assert get(b, "/ping") == (200, b"Pong")


def test_a_chunked_request_is_answered_and_closed(box):
    """The box speaks HTTP/1.0 with a length, because that is what it can hold in
    memory on a Pi. Chunked means "I will send you an unbounded body", so it is a
    501, not a slow hang."""
    import socket

    b, _ = box
    with socket.create_connection(("127.0.0.1", b.port), timeout=10) as sock:
        sock.sendall(b"POST /play HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n"
                     b"5\r\nhello\r\n0\r\n\r\n")
        reply = sock.recv(4096).decode("latin-1")
    assert reply.startswith("HTTP/1.0 501") or reply.startswith("HTTP/1.1 501"), reply.splitlines()[0]

