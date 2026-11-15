"""Optional online place lookup, for someone starting from an address instead of a number.

The offline table in `places.py` answers for a city. It cannot answer for a street, a
village that is not in the table, or a set of numbers someone copied off a form. So
there is a second door here, and it is deliberately narrow: one HTTPS request, to one
host, at the moment a person asks for it, and nothing else in this package ever dials
out on its own.

Why OpenStreetMap rather than the other map companies: their documented lookup
endpoints all require an API key, which means a prospective user would have to open an
account, attach something to bill, and hand over a token before the program can find
out where they live. OpenStreetMap's Nominatim asks for none of that. Its
https://operations.osmfoundation.org/policies/nominatim/ usage policy asks for at most
one request a second and a User-Agent that says which application is calling, so both
are fixed here rather than left to whoever runs the daemon.

The cost of that door is stated plainly, in the docs and on the terminal: the place
name a person types travels to a third party. Nothing is cached, nothing is logged, the
text is not written into the profile, and the request carries no identifier of this
household beyond the User-Agent the policy requires.

The same file also carries the other outward thing this program can do: fetching one
square of the OpenStreetMap map for the page. That one is on by default, because the map
is how a household notices where its numbers actually point, and `map_tiles: off` in the
profile puts it away. It is fetched by the daemon rather than by each browser so the
request identifies this program the way the tile policy asks, each square is fetched once
and kept, and what comes back is only passed on if it really is a picture.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from . import places
from .places import Place

__all__ = ["Hit", "search", "shorter", "reverse", "nearest_named", "GeocodeError",
           "NeedsInternet", "RefusedLookup", "TileMissing", "TileBusy", "user_agent",
           "provider", "zone_known", "ENDPOINT", "TILE_HOST", "MAP_CREDIT", "tile_url",
           "fetch_tile", "TILE_SPACING", "TILE_RETRY_WAIT", "ZONE_NEAR_KM", "FAR_KM",
           "ASK_SPACING", "ROAD_WORDS"]

# The one host a lookup goes to, unless the person running this points it at a
# Nominatim they run themselves. Overriding is a real use case - someone in Qatar who
# self-hosts a geocoder for speed, or a site with no outbound internet at all - but the
# default is fixed so nothing sends a household's addresses somewhere by accident.
ENDPOINT = "https://nominatim.openstreetmap.org"

# A lookup is for a human sitting at a keyboard, so it answers fast or gives up. Long
# enough for a satellite link, short enough that a dead network is a message and not a
# hung terminal.
TIMEOUT = 12.0

# A real answer is a few kilobytes. The cap is for a hostile or misconfigured endpoint
# answering with something enormous, not for a normal search.
MAX_BODY = 256 * 1024

# How close a place in the offline table has to be for its time zone to be offered as
# the zone for an unknown place. A city centre and its suburbs share a zone; two
# different cities do not, and 150 km is wider than any metropolitan area whose
# centre is in the table.
ZONE_NEAR_KM = 150.0

# Past this distance, "the nearest city muezzin can name" stops being a helpful answer
# and becomes the sign that somebody copied the wrong numbers. It is not a fact about the
# world - only about what is worth saying out loud.
FAR_KM = 300.0

# A lookup is ambiguous by nature, so several candidates are normal. Five is enough to
# pick from and few enough that nobody has to scroll.
LIMIT = 5


class GeocodeError(Exception):
    """Something a person can act on: check the spelling, check the network."""


class NeedsInternet(GeocodeError):
    """No answer came back. The wording never repeats what was searched for."""

    def __init__(self, host: str):
        super().__init__(
            f"{host} did not answer. The place you typed was not saved anywhere, and "
            "nothing else about this machine was sent with the request. Type the "
            "latitude, longitude and timezone into the profile instead, or point "
            "MUEZZIN_GEOCODE at a lookup you run yourself.")


class RefusedLookup(GeocodeError):
    """The answer arrived, or was on its way somewhere, and was not followed."""


class TileMissing(GeocodeError):
    """A map square could not be had, or was not the picture it was asked to be."""


class TileBusy(TileMissing):
    """Reachable, but that square did not come.

    A 429 or a 5xx, or a connection that never finished: all of them are a server that
    is stretched rather than a server that said no, and all of them usually answer a
    second time. That distinction is what decides whether `fetch_tile` asks again.
    """


# The map squares, used only when a profile asks for a map. Zoom 19 is as deep as the
# public layer goes, and asking deeper than that is how a browser's panning turns into a
# lot of requests at somebody else's server.
TILE_HOST = "https://tile.openstreetmap.org"
TILE_MAX_ZOOM = 19

# The public tile layer asks to be treated the way a person browsing a map behaves: no
# more than about one request a second, and an application that says what it is. A view
# of the page is nine squares, and a browser sends all nine at once, so the panel keeps
# them in a queue instead.
TILE_SPACING = 1.1

# A second ask only after a pause, and only for a server that looked busy rather than
# unwilling. The answer is worth waiting a moment for: a hole in the middle of the map
# is the one thing on this page that makes people doubt the numbers next to it.
TILE_RETRY_CODES = frozenset({408, 429, 500, 502, 503, 504})
TILE_RETRY_WAIT = 1.0

# The lookup server says the same thing about itself, but as a rule rather than a custom:
# at most one request a second, counted for the whole application no matter how many
# people are typing into it. Tiles have their own queue, and nothing here kept two asks
# apart, so a search followed quickly by a look at one of its own answers could put two
# questions inside the same second. One gap covers both, because they are the same server.
ASK_SPACING = 1.1
_last_ask = 0.0

# There is deliberately no rule here about how big a square ought to be, because the
# measurement says not to have one: the square of lake west of Erie at zoom 12 is 103
# bytes, and the square beside it with a shoreline in it is 4,687. A flat colour
# compresses to almost nothing, so a small PNG can be a perfectly good map, and a rule
# built on size would have the daemon asking a stranger again and again for something
# it already handed over.

# The tile and address data here is OpenStreetMap's, under the ODbL, and their usage
# policy asks that it be shown as theirs. A page that shows somebody else's map without
# saying so is not just rude: it is a person trusting a map with no way to find out whose.
MAP_CREDIT = "\u00a9 OpenStreetMap contributors"


def provider() -> str:
    """The host a lookup would go to, as shown to a person. Never carries a query."""
    try:
        return urllib.parse.urlsplit(endpoint()).netloc
    except GeocodeError:
        return urllib.parse.urlsplit(ENDPOINT).netloc


def user_agent() -> str:
    """Identify the application, because the usage policy asks for that rather than a
    stock library string. MUEZZIN_CONTACT lets whoever runs this add a way to reach
    them, which is what the policy is actually after."""
    contact = (os.environ.get("MUEZZIN_CONTACT") or "").strip()
    base = "muezzin prayer-time daemon (self-hosted; https://github.com/124c41pl/muezzin)"
    return f"{base}; {contact}" if contact else base


def endpoint() -> str:
    """The lookup host in use, after the override, checked before anything is sent.

    HTTPS unless the host is a local one: a Nominatim on the same LAN is a normal thing
    to run, and it is closer than the public instance anyway. Anything else going over
    plain HTTP would carry the address in the clear, so it is refused here rather than
    trusted to be configured correctly somewhere else.
    """
    url = (os.environ.get("MUEZZIN_GEOCODE") or ENDPOINT).strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    local = (host == "localhost" or "." not in host
             or _is_local_address(host))
    if parts.scheme == "https":
        return url
    if parts.scheme == "http" and local:
        return url
    raise RefusedLookup(
        f"the lookup address {url!r} is not usable: https, or http only for a lookup "
        "on this machine or this network. A plain request would carry your address in "
        "the clear.")


def _is_local_address(host: str) -> bool:
    """True for a literal address that cannot leave the building."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


class _NoRedirecting(urllib.request.HTTPRedirectHandler):
    """Refuse to be pointed at another host.

    A lookup carries the place someone typed. Following a redirect would carry it to a
    host that was never named, and an answer from wherever it landed would still be
    presented as a place. So a redirect is an error, not a step.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


_OPENER = urllib.request.build_opener(_NoRedirecting)


def _open(url: str, accept: str = "application/json") -> bytes:
    """The raw door: one request, once, and nothing that reads the answer.

    Kept this thin on purpose. It is the only place in this package that opens a socket
    to a machine which is not on the owner's network, so it is the one thing a test has to
    stand in for, and everything said about the answer belongs above it.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": user_agent(), "Accept": accept,
                      "Accept-Language": "en"})
    with _OPENER.open(request, timeout=TIMEOUT) as response:
        return response.read(MAX_BODY)


def _take_a_turn() -> None:
    """Wait until a second has gone by since the last question left for the lookup server.

    The public instance counts traffic per application rather than per person, so two asks
    from one house - a search, then a look at one of its own answers - are simply two asks
    and they take turns. The pause is measured from the ask before it, and the length is
    read when called so that a test can ask for a shorter one and still see the turn taken.
    """
    global _last_ask
    wait = ASK_SPACING - (time.monotonic() - _last_ask)
    if wait > 0:
        time.sleep(wait)
    _last_ask = time.monotonic()


def _ask(url: str) -> bytes:
    """The door with its manners: one request at a time, no second try, and a reason that
    does not repeat the question.

    No retry because the usage policy asks for at most one request a second, and because a
    person who mistyped a name would otherwise fire the same question at a stranger three
    times. The gap first is the other half of that same rule: the limit is one ask a
    second for this application as a whole, not one per button, so a search and then a
    look at one of its own answers take turns. The reasons deliberately leave out the text
    that was looked up: this line ends up in a terminal, a log, or a bug report, and it is
    the one place a household's street could ride along in.
    """
    _take_a_turn()
    try:
        return _open(url)
    except urllib.error.HTTPError as exc:
        # A 3xx reaches here because the redirect handler above declines it.
        if exc.code in (301, 302, 303, 307, 308):
            raise RefusedLookup(
                f"{provider()} tried to send the lookup elsewhere (HTTP {exc.code}), "
                "and it was not followed: an answer from an unnamed host is not a "
                "place.") from None
        raise RefusedLookup(f"{provider()} answered HTTP {exc.code}, which is not a "
                            "place.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, str) and "certificate" in reason.casefold():
            raise RefusedLookup(
                f"{provider()} could not be verified, so the lookup was not sent: a "
                "place you typed should not go to an unverified connection.") from None
        raise NeedsInternet(urllib.parse.urlsplit(url).netloc) from None


def _zone(name: str) -> str | None:
    """Accept a zone only if this machine actually knows that name."""
    if not name:
        return None
    try:
        ZoneInfo(name)
    except (ValueError, KeyError):
        return None
    return name


def zone_known(name: str) -> bool:
    """Whether this machine's time zone database actually has that name.

    The panel asks before it writes a clock line into a profile, because a name the
    database does not know is not a slightly wrong guess - it is a profile that will not
    load at all, which is a bad thing to discover at the next restart.
    """
    return _zone(str(name or "")) is not None


@dataclass(frozen=True)
class Hit:
    """One candidate place, and how honest we can be about the clock line."""

    label: str
    latitude: float
    longitude: float
    timezone: str | None
    zone_note: str

    @property
    def known_zone(self) -> bool:
        return bool(self.timezone)

    def as_place(self) -> Place:
        if not self.timezone:
            raise RefusedLookup(
                f"{self.label} has no time zone anyone could agree on for it: the "
                "lookup did not name one and no city muezzin knows is close enough. "
                "Write the timezone line yourself; the two coordinates are right.")
        return Place(name=self.label, region="", latitude=self.latitude,
                     longitude=self.longitude, timezone=self.timezone)

    def as_config(self) -> dict:
        return self.as_place().as_config()


def _zone_for(item: dict, latitude: float, longitude: float) -> tuple[str | None, str]:
    """The clock line, and a sentence about where it came from.

    Neither map says which zone a house is in - a zone is a political decision about
    naming an hour, and it is not geography - so the order here is: say so if the map
    did record one; otherwise borrow the zone of the nearest city in the offline table,
    which is right for a suburb and wrong if the town is in another country's zone;
    otherwise refuse to guess.
    """
    said = _zone(str((item.get("extratags") or {}).get("timezone", "")))
    if said:
        return said, "the lookup named this zone"
    close = places.nearest(latitude, longitude, 1)
    if close and close[0][1] <= ZONE_NEAR_KM:
        place, km = close[0][0], close[0][1]
        return place.timezone, (f"borrowed from {place.label}, {km:.0f} km away, "
                                "because no zone came with the place")
    return None, ("no time zone came with it and no city muezzin knows is within "
                  f"{ZONE_NEAR_KM:.0f} km")


def _rows(body: bytes) -> list[dict]:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RefusedLookup(f"{provider()} answered something that is not a list of "
                            f"places ({type(exc).__name__}), so nothing was picked "
                            "from it.") from None
    if isinstance(data, dict):
        data = [data]
    return [item for item in data if isinstance(item, dict)]


def _hit(item: dict) -> Hit | None:
    label = str(item.get("display_name") or "").strip()
    try:
        latitude = float(item["lat"])
        longitude = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not label:
        label = f"{latitude:.5f}, {longitude:.5f}"
    zone, note = _zone_for(item, latitude, longitude)
    return Hit(label=label, latitude=round(latitude, 6), longitude=round(longitude, 6),
               timezone=zone, zone_note=note)


# The words that name a road rather than a town, so that everything after them - the town,
# the state, the postcode - can be dropped when a line comes back with nothing in it. A
# full address is one hard constraint to a lookup: measured on the public instance, a line
# naming a house and a street answered with that exact door, while the same line with the
# city people write in that address appended answered with nothing at all. The street is in
# the data, filed under the name of the place it sits in, which is often not the postal
# name used in the address - an unincorporated suburb, a neighbourhood, a district. English
# first, because that is what the wording on the page is written around; the rest are the
# common forms elsewhere. It is a hint rather than a rule, and a line this cannot read
# simply gets no offer at all, which is the safe way for a guess to fail.
ROAD_WORDS = frozenset("""
    street st str rd road ave avenue av blvd boulevard dr drive ln lane ct court cres
    crescent way pl place platz ter terrace cir circle hwy highway pkwy parkway close
    walk row mews sq square quay rise run path footpath alley arcade parade
    rue calle carrera via callejon jalan lorong gang gali marg strad strada straasse
    strasse straße chemin weg gadim ghadim
""".split())


def shorter(text: str) -> str | None:
    """The same question with the tail cut off, for when a town is what stopped it.

    Nothing here is sent anywhere. It is an offer, and the words are shown before anyone
    decides to ask, so a second request stays a thing a person did rather than something
    this program did behind their back. Nor is it a promise: it is the part of the line the
    map is known to be good at, and sometimes that is still not enough.
    """
    words = (text or "").strip()
    if not words:
        return None
    head = words.split(",")[0].strip()
    parts = head.split()
    keep = -1
    for position, word in enumerate(parts):
        if word.strip(".,;:()").casefold() in ROAD_WORDS:
            keep = position
    piece = " ".join(parts[:keep + 1]) if keep >= 0 else head
    piece = piece.strip(" ,.;:()")
    # Three words, or nothing: "5 rue" and "1200 peach" are not an address, and asking
    # with a bare word or a bare number is how a person ends up looking at a street of the
    # same name on another continent. Where the street name comes before the road word -
    # most addresses that are not written in English - this stays quiet rather than offer
    # something that would not answer.
    if len(piece.split()) < 3 or piece.casefold() == words.casefold():
        return None
    return piece


def search(text: str, postcode: str = "", limit: int = LIMIT) -> list[Hit]:
    """Places that could be what was typed, nearest-meaning first.

    The text goes over the wire, which is the whole point and the whole cost. It is
    never written to disk, and the errors never quote it back.

    A postal code is worth a town, which is why it gets a box of its own rather than being
    left to the sentence somebody composes. Measured against the public instance:
    "2456 w 12th st erie pa" answered with five stretches of West 12th Street, none of them
    the door asked for, because a street is filed under the place it sits in and not the
    town name people put in a posting address; the same words with the code in place of the
    town - "2456 w 12th st, 16508" - answered with one row, house number 2456, in the
    township that holds it. A street and a code with no number answers with the street,
    which is enough: the map then lets the person click the door they live at instead of
    trusting the lookup to have mapped it.
    """
    text = (text or "").strip()
    postcode = (postcode or "").strip()
    if postcode:
        text = f"{text}, {postcode}" if text else postcode
    if not text:
        raise RefusedLookup("nothing was typed to look up.")
    url = (f"{endpoint()}/search?" + urllib.parse.urlencode(
        {"q": text, "format": "jsonv2", "addressdetails": 1, "extratags": 1,
         "limit": max(1, min(limit, 10))}))
    return [hit for hit in (_hit(item) for item in _rows(_ask(url))) if hit]


def reverse(latitude: float, longitude: float) -> list[Hit]:
    """What these numbers are near, which is how a copied coordinate gets checked."""
    url = (f"{endpoint()}/reverse?" + urllib.parse.urlencode(
        {"lat": latitude, "lon": longitude, "format": "jsonv2", "addressdetails": 1,
         "extratags": 1, "zoom": 16}))
    return [hit for hit in (_hit(item) for item in _rows(_ask(url))) if hit]


def nearest_named(latitude: float, longitude: float, count: int = 5) -> list[dict]:
    """The offline table's nearest cities: what a place is, with no network at all.

    This is the answer for "did I put in the right numbers" when there is no reason to
    ask a stranger - and it is also what the page draws a small diagram from.
    """
    return [{"name": place.label, "latitude": place.latitude,
             "longitude": place.longitude, "timezone": place.timezone,
             "km": round(km, 1), "bearing": round(places.bearing(latitude, longitude,
                                                                 place.latitude,
                                                                 place.longitude))}
            for place, km in places.nearest(latitude, longitude, count)]


def tile_url(zoom: int, x: int, y: int) -> str:
    """The address of one map square, and the only map address this code will use.

    The numbers are checked here rather than left to the caller because they arrive from
    a browser: a zoom of 2^31 or a negative square would otherwise turn one request for a
    picture into a request for nonsense, or into a great many of them.
    """
    zoom, x, y = int(zoom), int(x), int(y)
    if not 0 <= zoom <= TILE_MAX_ZOOM:
        raise TileMissing(f"the map goes from zoom 0 to {TILE_MAX_ZOOM}, not {zoom}")
    edge = 2 ** zoom
    if not 0 <= x < edge or not 0 <= y < edge:
        raise TileMissing(f"at zoom {zoom} the squares run from 0 to {edge - 1}, "
                          f"not {x} or {y}")
    return f"{TILE_HOST}/{zoom}/{x}/{y}.png"


# The eight bytes every PNG starts with, spelled out as numbers so nothing here depends
# on how an escape sequence happens to be read.
PNG_HEAD = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])


def _one_tile(url: str) -> bytes:
    """One request for one square, with the answer checked before it is believed."""
    try:
        body = _open(url, accept="image/png")
    except urllib.error.HTTPError as exc:
        if exc.code in TILE_RETRY_CODES:
            raise TileBusy(f"the map server was busy with that square (HTTP {exc.code})") \
                from None
        raise TileMissing(f"the map server answered HTTP {exc.code} for that square, "
                          "which is not a picture") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, str) and "certificate" in reason.casefold():
            raise TileMissing("the map server could not be verified, so nothing was taken "
                              "from it") from None
        raise TileBusy(f"{urllib.parse.urlsplit(url).netloc} did not answer") from None
    if not body.startswith(PNG_HEAD):
        raise TileMissing("what came back from the map server is not a picture, so it is "
                          "not being shown")
    return body


def fetch_tile(zoom: int, x: int, y: int) -> bytes:
    """One square of the map, asked for once, and once more if it came back wrong.

    Checked to be a picture before anyone is shown it: a captive portal, a proxy's error
    page or a hijacked answer arrives with a 200 and HTML inside it, and passing that on
    from this page's own address is how somebody else's markup ends up looking like ours.

    A view of the page is nine squares, and the public layer says no more than about one
    request a second, so a square that fails is asked for once more rather than
    repeatedly: that is the difference between a hole in the map and one more request at
    a server that is already stretched. Only a server that looked busy is asked again,
    and only a moment later. A square the server refused is not asked again at all.
    """
    url = tile_url(zoom, x, y)
    trouble = None
    for ask in (1, 2):
        if ask > 1:
            time.sleep(TILE_RETRY_WAIT)
        try:
            return _one_tile(url)
        except TileBusy as exc:
            trouble = str(exc)
    raise TileBusy(f"{trouble}. The map is a courtesy on the page; the times do not "
                   "need it") from None
