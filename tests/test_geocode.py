"""The one door in this package that opens outward, and what it is allowed to carry.

A lookup is the only request muezzin makes to a machine that is not on the owner's
network, and it carries a place someone typed - for a lot of people, their home. So the
things worth testing are not really about geography: that the request goes to exactly
one named host over an encrypted connection, that it is not followed when it is handed a
redirect, that it is made once rather than retried, that nothing about the question is
kept or repeated back in an error, and that the clock line - which no map actually knows
- is never invented.

None of these tests touch the network. The seam is `_open`, the single function that
would otherwise reach the internet, and everything above it is the part with the promises
in it.
"""
from __future__ import annotations

import json
import urllib.error

import pytest

from muezzin import geocode, places
from muezzin.cli import main

# Two answers in the shape Nominatim sends. The first names a zone; the second does
# not, and has to borrow one. Neither is anybody's house: a main street in a city that
# is already in the offline table.
ANSWER = json.dumps([
    {"display_name": "1200, Peach Street, Erie, Erie County, Pennsylvania, "
                      "United States",
     "lat": "42.1023456", "lon": "-80.0654321",
     "address": {"house_number": "1200", "road": "Peach Street", "city": "Erie",
                 "state": "Pennsylvania", "country_code": "us"},
     "extratags": {"timezone": "America/New_York"}},
    {"display_name": "Peach Street, Erie, Erie County, Pennsylvania, United States",
     "lat": "42.11", "lon": "-80.07", "address": {}, "extratags": {}},
]).encode()


class FakeNetwork:
    """Stands in for the one call that would leave this machine, and counts it."""

    def __init__(self, body=b"[]", error=None):
        self.calls: list[str] = []
        self.wanted: list[str] = []
        self.body = body
        self.error = error

    def __call__(self, url: str, accept: str = "application/json") -> bytes:
        self.calls.append(url)
        self.wanted.append(accept)
        if self.error is not None:
            raise self.error
        return self.body

    @property
    def asked(self) -> str:
        return " & ".join(self.calls)


@pytest.fixture
def offline(monkeypatch):
    """A network that answers nothing, so a test fails loudly if it reaches anyway."""
    net = FakeNetwork(error=AssertionError("a lookup test tried to reach the internet"))
    monkeypatch.setattr(geocode, "_open", net)
    return net


@pytest.fixture
def answering(monkeypatch):
    net = FakeNetwork(body=ANSWER)
    monkeypatch.setattr(geocode, "_open", net)
    return net


def test_the_default_lookup_needs_no_key_and_names_its_host():
    """The reason OpenStreetMap was chosen over the map companies, said in code."""
    assert geocode.endpoint() == "https://nominatim.openstreetmap.org"
    assert "key=" not in geocode.endpoint()
    agent = geocode.user_agent()
    assert "muezzin" in agent and "github.com/124c41pl" in agent
    assert "Python-urllib" not in agent, "the usage policy asks who is calling"


def test_the_contact_line_is_there_for_whoever_runs_this(monkeypatch):
    monkeypatch.setenv("MUEZZIN_CONTACT", "you@example.com")
    assert "you@example.com" in geocode.user_agent()


def test_asking_sends_one_request_to_one_host_with_the_question_in_it(answering):
    hits = geocode.search("1200 Peach Street, Erie, PA")
    assert len(answering.calls) == 1
    url = answering.calls[0]
    assert url.startswith("https://nominatim.openstreetmap.org/search?")
    assert "q=1200+Peach+Street" in url, "the question is what is being looked up"
    assert "key=" not in url and "token=" not in url
    assert hits and hits[0].label.startswith("1200, Peach Street")
    assert hits[0].latitude == pytest.approx(42.1023456, abs=1e-5)


def test_a_question_that_is_empty_sends_nothing(offline):
    with pytest.raises(geocode.GeocodeError):
        geocode.search("   ")
    assert offline.calls == []


def test_the_answer_is_read_as_places_not_as_json_rows(answering):
    hits = geocode.search("peach street erie")
    assert len(hits) == 2
    named, borrowed = hits
    assert named.timezone == "America/New_York"
    assert "lookup named" in named.zone_note
    # The second row carries no zone, so the nearest city in the offline table lends
    # its clock - and the note says that is what happened, rather than presenting it as
    # fact.
    assert borrowed.timezone == "America/New_York"
    assert "borrowed" in borrowed.zone_note and "Erie, Pennsylvania" in borrowed.zone_note


def test_a_time_zone_the_machine_does_not_know_is_not_repeated_back(monkeypatch):
    """A map can carry a nonsense zone tag; passing it through would put the profile in
    a state where every prayer time is a different distance from the truth."""
    body = json.dumps([{"display_name": "Some Field, Nowhere", "lat": "42.11",
                        "lon": "-80.07", "extratags": {"timezone": "Mars/Olympus_Mons"}}])
    net = FakeNetwork(body=body.encode())
    monkeypatch.setattr(geocode, "_open", net)
    hit = geocode.search("some field")[0]
    assert hit.timezone == "America/New_York", "borrowed from the nearest city"
    assert "Mars" not in hit.zone_note


def test_a_place_nowhere_near_a_known_city_refuses_to_guess_its_clock(monkeypatch):
    body = json.dumps([{"display_name": "Middle of the South Atlantic",
                        "lat": "-30.0", "lon": "-20.0", "extratags": {}}]).encode()
    monkeypatch.setattr(geocode, "_open", FakeNetwork(body=body))
    hit = geocode.search("south atlantic")[0]
    assert hit.timezone is None and not hit.known_zone
    with pytest.raises(geocode.RefusedLookup) as caught:
        hit.as_place()
    assert "timezone" in str(caught.value), "the fix is named, not hinted at"


def test_a_failed_lookup_does_not_repeat_the_question(monkeypatch):
    """Errors end up in terminals, logs and bug reports. The place someone typed should
    not ride along in one of those when nothing was learned from it."""
    secret = "1200 Peach Street Erie"
    net = FakeNetwork(error=urllib.error.URLError("timed out"))
    monkeypatch.setattr(geocode, "_open", net)
    with pytest.raises(geocode.NeedsInternet) as caught:
        geocode.search(secret)
    message = str(caught.value)
    assert secret not in message and "Erie" not in message
    assert "nominatim.openstreetmap.org" in message
    assert "not saved" in message and "profile" in message


def test_the_question_is_asked_once_even_when_it_fails(monkeypatch):
    """Retrying a lookup is how one mistyped name becomes three requests at a stranger,
    and the usage policy asks for at most one a second."""
    net = FakeNetwork(error=urllib.error.URLError("connection refused"))
    monkeypatch.setattr(geocode, "_open", net)
    with pytest.raises(geocode.NeedsInternet):
        geocode.search("erie")
    assert len(net.calls) == 1


def test_an_answer_that_is_not_a_list_of_places_is_refused(monkeypatch):
    """A captive-portal page or a proxy's error page arrives with a 200 and HTML in it.
    Reading a place out of that is how a wrong city ends up in a profile."""
    for body in (b"<html><body>sign in</body></html>", b"", b"[{\"nonsense\": true}]"):
        monkeypatch.setattr(geocode, "_open", FakeNetwork(body=body))
        if body == b"[{\"nonsense\": true}]":
            assert geocode.search("erie") == [], "a row without coordinates is dropped"
        else:
            with pytest.raises(geocode.RefusedLookup):
                geocode.search("erie")


def test_a_plain_http_lookup_is_refused_before_the_question_is_sent(monkeypatch, offline):
    """Plain HTTP carries the address in the clear to whoever is listening. A lookup on
    this machine or this network is allowed; anything else is not."""
    monkeypatch.setenv("MUEZZIN_GEOCODE", "http://geocoder.example.org")
    with pytest.raises(geocode.RefusedLookup) as caught:
        geocode.search("erie")
    assert "in the clear" in str(caught.value)
    assert offline.calls == []


def test_a_lookup_on_the_local_network_is_allowed(monkeypatch, answering):
    for target in ("http://atlas:8080", "http://192.168.0.50", "http://localhost"):
        monkeypatch.setenv("MUEZZIN_GEOCODE", target)
        geocode.search("erie")
    assert answering.calls[-1].startswith("http://localhost/search?"), "no trailing /"


def test_the_public_endpoint_over_https_is_taken_as_it_is_given(monkeypatch, answering):
    monkeypatch.setenv("MUEZZIN_GEOCODE", "https://nominatim.example.net/")
    geocode.search("erie")
    assert answering.calls[-1].startswith("https://nominatim.example.net/search?")


def test_a_redirect_is_not_followed_because_it_carries_the_question():
    """The real opener, a real socket, and an answer that says "go away and ask
    somebody else". Following that would send a household's address to a host that was
    never named, and an answer from there would still look like a place."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Redirecting(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Redirecting)
    port = server.server_address[1]
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(geocode.RefusedLookup) as caught:
            geocode._ask(f"http://127.0.0.1:{port}/search?q=erie")
        assert "not followed" in str(caught.value)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_reverse_asks_about_the_numbers_it_was_given(answering):
    hits = geocode.reverse(42.1023, -80.0654)
    assert "lat=42.1023" in answering.calls[0] and "lon=-80.0654" in answering.calls[0]
    assert hits[0].known_zone


def test_what_a_point_is_near_is_answered_with_no_network_at_all(offline):
    """The part of "did I type the right numbers" that needs no stranger: the nearest
    cities muezzin already knows, with distance and direction."""
    near = geocode.nearest_named(42.1292, -80.0851, 3)
    assert [row["name"] for row in near] == [
        "Erie, Pennsylvania", "London, Ontario", "Cleveland, Ohio"]
    assert near[0]["km"] == pytest.approx(0.0, abs=1.0)
    assert near[2]["km"] > 100 and 0 <= near[2]["bearing"] < 360
    assert offline.calls == []


def test_the_nearest_places_agree_with_the_table_itself(offline):
    named = [item["name"] for item in geocode.nearest_named(40.7128, -74.006, 4)]
    scored = [place.label for place, _ in places.nearest(40.7128, -74.006, 4)]
    assert named == scored, "the page and the table say the same thing"
    assert places.nearest(40.7128, -74.006, 1)[0][1] < 1.0, "New York is near New York"


def test_a_point_on_the_other_side_of_the_world_is_named_as_far_away(offline):
    """The mistake this catches: a coordinate copied from a form that meant a different
    city. Saying "Accra, 4,487 km away" in front of the numbers is what makes it obvious,
    and that is arithmetic between two points on the table, not a lookup."""
    qom = geocode.nearest_named(34.6416, 50.8799, 1)[0]
    assert qom["name"] == "Qom, Iran" and qom["km"] < 1.0
    assert places.distance_km(40.7128, -74.006, 34.6416, 50.8799) > 9_500
    # A borrowed clock has to be a nearby clock: Accra is the closest city muezzin can
    # name to the middle of the South Atlantic, and 4,500 km is not somebody's clock.
    assert geocode.nearest_named(-30.0, -20.0, 1)[0]["km"] > geocode.ZONE_NEAR_KM


def test_the_command_writes_a_found_place_and_says_the_question_left(monkeypatch,
                                                                     tmp_path, capsys):
    path = tmp_path / "muezzin.yaml"
    monkeypatch.chdir(tmp_path)
    main(["init"])
    one = json.dumps([{"display_name": "Qom, Iran", "lat": "34.6416", "lon": "50.8799",
                       "extratags": {"timezone": "Asia/Tehran"}}]).encode()
    monkeypatch.setattr(geocode, "_open", FakeNetwork(body=one))
    assert main(["where", "--online", "--write", "qom, iran",
                 "-c", str(path)]) == 0
    text = path.read_text(encoding="utf-8")
    assert "latitude: 34.6416" in text and "Asia/Tehran" in text
    out = capsys.readouterr().out
    assert "nominatim.openstreetmap.org" in out, "the terminal says who was asked"


def test_the_command_offers_the_choices_instead_of_picking_one(monkeypatch, tmp_path,
                                                               capsys):
    path = tmp_path / "muezzin.yaml"
    monkeypatch.chdir(tmp_path)
    main(["init"])
    monkeypatch.setattr(geocode, "_open", FakeNetwork(body=ANSWER))
    assert main(["where", "--online", "peach street", "-c", str(path)]) == 2
    err = capsys.readouterr().err
    assert "1)" in err and "2)" in err, "the candidates are numbered so one can be picked"
    assert "not this program's call" in err
    assert "40.7128" in path.read_text(encoding="utf-8"), "nothing was written yet"
    # Picking one by number is how an ambiguous answer stops being a problem: the
    # program never chooses between two cities on someone's behalf.
    assert main(["where", "--online", "--choose", "2", "--write", "peach street",
                 "-c", str(path)]) == 0
    written = path.read_text(encoding="utf-8")
    assert "latitude: 42.11" in written and "longitude: -80.07" in written


def test_the_command_refuses_a_choice_that_was_not_offered(monkeypatch, tmp_path, capsys):
    path = tmp_path / "muezzin.yaml"
    monkeypatch.chdir(tmp_path)
    main(["init"])
    monkeypatch.setattr(geocode, "_open", FakeNetwork(body=ANSWER))
    assert main(["where", "--online", "--choose", "9", "--write", "peach street",
                 "-c", str(path)]) == 2
    assert "not one of the 2 answers" in capsys.readouterr().err
    assert "40.7128" in path.read_text(encoding="utf-8")


def test_the_command_reads_numbers_and_names_the_cities_near_them(tmp_path, capsys,
                                                                 monkeypatch):
    """The whole point of --coords is offline: a person with numbers from their phone
    finds out what muezzin would make of them without asking anybody."""
    path = tmp_path / "muezzin.yaml"
    monkeypatch.chdir(tmp_path)
    main(["init"])
    assert main(["where", "--coords", "42.1292,-80.0851", "-c", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Erie, Pennsylvania" in out and "0 km away" in out
    assert "Cleveland, Ohio" in out and "km away" in out
    assert "40.7128" in path.read_text(encoding="utf-8"), "--write was not asked for"


def test_numbers_from_the_wrong_side_of_the_world_are_called_far(tmp_path, capsys,
                                                                monkeypatch):
    path = tmp_path / "muezzin.yaml"
    monkeypatch.chdir(tmp_path)
    main(["init"])
    assert main(["where", "--coords", "-30.0,-20.0", "--write", "-c", str(path)]) == 2
    err = capsys.readouterr().err
    assert "long way from anywhere" in err and "timezone" in err
    assert "40.7128" in path.read_text(encoding="utf-8"), "nothing was written"


def test_numbers_south_of_the_equator_are_typed_the_way_they_read(tmp_path, capsys,
                                                                 monkeypatch):
    """A leading dash is a latitude, not a switch. argparse reads one as another option,
    which would have this program answer "expected one argument" to a question about
    Sydney, Australia - and only on some Python versions, which is worse."""
    path = tmp_path / "muezzin.yaml"
    monkeypatch.chdir(tmp_path)
    main(["init"])
    assert main(["where", "--coords", "-33.8683,151.2093", "--write",
                 "-c", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Sydney, Australia" in out and "0 km away" in out
    written = path.read_text(encoding="utf-8")
    assert "-33.86" in written and "Australia/Sydney" in written


def test_the_command_refuses_numbers_it_cannot_read(tmp_path, capsys, monkeypatch):
    path = tmp_path / "muezzin.yaml"
    monkeypatch.chdir(tmp_path)
    main(["init"])
    for bad in ("42.1", "42.1,-80.0,7", "42.1 -80.0", "91,-80.0", "north,east"):
        assert main(["where", "--coords", bad, "-c", str(path)]) == 2, bad
    assert "42.1292,-80.0851" in capsys.readouterr().err


# The map squares and the clock line are the two things a lookup cannot be trusted
# with. The squares arrive as bytes somebody else chose, so they get looked at before
# anyone is shown them; the clock does not arrive at all, so it is never implied.

# A PNG header, then a square of somebody's map. The header is spelled as numbers
# because an escape sequence in a test file is a thing a person can misread.
PICTURE = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"a square of map"


def test_the_two_distances_are_named_because_two_places_need_them():
    """How far a clock may be borrowed from, and how far away stops being believable."""
    assert geocode.ZONE_NEAR_KM < geocode.FAR_KM, "borrowing stops before giving up does"
    assert geocode.ZONE_NEAR_KM == 150.0 and geocode.FAR_KM == 300.0


def test_a_zone_counts_as_known_only_if_this_machine_can_open_its_clock():
    assert geocode.zone_known("America/New_York")
    assert not geocode.zone_known("Mars/Phobos")
    assert not geocode.zone_known("")
    assert not geocode.zone_known(None), "an absent line is not a zone to load"


def test_the_map_addresses_are_the_only_ones_this_code_will_use():
    assert geocode.tile_url(0, 0, 0) == "https://tile.openstreetmap.org/0/0/0.png"
    assert geocode.tile_url(geocode.TILE_MAX_ZOOM, 0, 0).startswith(geocode.TILE_HOST)
    assert geocode.tile_url(12, 3456, 1721).endswith("/12/3456/1721.png")


def test_a_square_off_the_edge_of_the_map_is_refused_before_anyone_is_asked(offline):
    """The numbers come out of a browser, so the door checks them instead of hoping."""
    for bad in ((30, 0, 0), (-1, 0, 0), (0, 1, 0), (2, 4, 0), (2, 0, 4), (2, -1, 0)):
        with pytest.raises(geocode.TileMissing):
            geocode.tile_url(*bad)
    assert offline.calls == [], "a square that does not exist is not worth a request"


def test_a_square_is_asked_for_as_a_picture_and_only_once(monkeypatch):
    net = FakeNetwork(body=PICTURE)
    monkeypatch.setattr(geocode, "_open", net)
    assert geocode.fetch_tile(12, 3456, 1721) == PICTURE
    assert net.calls == [geocode.tile_url(12, 3456, 1721)]
    assert net.wanted == ["image/png"], "the ask says what kind of bytes it expects"


def test_bytes_that_are_not_a_picture_are_not_handed_to_a_browser(monkeypatch):
    """A captive portal or a proxy's error page answers with a 200 and HTML inside it,
    and those bytes would then be shown from this page's own address."""
    for disguise in (b"GIF89a, not a png", b"<!doctype html>a door, not a map", b""):
        monkeypatch.setattr(geocode, "_open", FakeNetwork(body=disguise))
        with pytest.raises(geocode.TileMissing) as caught:
            geocode.fetch_tile(1, 1, 1)
        assert "not a picture" in str(caught.value)


def test_a_map_that_is_not_there_costs_nobody_the_times(monkeypatch):
    monkeypatch.setattr(geocode, "_open",
                        FakeNetwork(error=urllib.error.URLError("no route")))
    with pytest.raises(geocode.TileMissing) as caught:
        geocode.fetch_tile(12, 3456, 1721)
    note = str(caught.value)
    assert "tile.openstreetmap.org did not answer" in note
    assert "the times do not need it" in note, "a grey square must not read as a bad time"


def test_a_square_somebody_refused_says_who_refused_it(monkeypatch):
    refused = urllib.error.HTTPError(geocode.TILE_HOST, 404, "not here", {}, None)
    monkeypatch.setattr(geocode, "_open", FakeNetwork(error=refused))
    with pytest.raises(geocode.TileMissing) as caught:
        geocode.fetch_tile(1, 1, 1)
    assert "404" in str(caught.value)


def test_a_map_server_that_cannot_be_verified_is_not_listened_to(monkeypatch):
    monkeypatch.setattr(geocode, "_open",
                        FakeNetwork(error=urllib.error.URLError("certificate check failed")))
    with pytest.raises(geocode.TileMissing) as caught:
        geocode.fetch_tile(1, 1, 1)
    assert "could not be verified" in str(caught.value)
