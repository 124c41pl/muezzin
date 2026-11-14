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
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from . import places
from .places import Place

__all__ = ["Hit", "search", "reverse", "nearest_named", "GeocodeError", "NeedsInternet",
           "RefusedLookup", "TileMissing", "user_agent", "provider", "zone_known",
           "ENDPOINT", "TILE_HOST", "MAP_CREDIT", "tile_url", "fetch_tile",
           "ZONE_NEAR_KM", "FAR_KM"]

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


# The map squares, used only when a profile asks for a map. Zoom 19 is as deep as the
# public layer goes, and asking deeper than that is how a browser's panning turns into a
# lot of requests at somebody else's server.
TILE_HOST = "https://tile.openstreetmap.org"
TILE_MAX_ZOOM = 19

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


def _ask(url: str) -> bytes:
    """The door with its manners: one request, no second try, and a reason that does not
    repeat the question.

    No retry because the usage policy asks for at most one request a second, and because a
    person who mistyped a name would otherwise fire the same question at a stranger three
    times. The reasons deliberately leave out the text that was looked up: this line ends
    up in a terminal, a log, or a bug report, and it is the one place a household's street
    could ride along in.
    """
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


def search(text: str, limit: int = LIMIT) -> list[Hit]:
    """Places that could be what was typed, nearest-meaning first.

    The text goes over the wire, which is the whole point and the whole cost. It is
    never written to disk, and the errors never quote it back.
    """
    text = (text or "").strip()
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


def fetch_tile(zoom: int, x: int, y: int) -> bytes:
    """One square of the map, asked for once.

    Checked to be a picture before anyone is shown it: a captive portal, a proxy's error
    page or a hijacked answer arrives with a 200 and HTML inside it, and passing that on
    from this page's own address is how somebody else's markup ends up looking like ours.
    """
    url = tile_url(zoom, x, y)
    try:
        body = _open(url, accept="image/png")
    except urllib.error.HTTPError as exc:
        raise TileMissing(f"the map server answered HTTP {exc.code} for that square, "
                          "which is not a picture") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, str) and "certificate" in reason.casefold():
            raise TileMissing("the map server could not be verified, so nothing was taken "
                              "from it") from None
        raise TileMissing(f"{urllib.parse.urlsplit(url).netloc} did not answer. The map is "
                          "a courtesy on the page; the times do not need it.") from None
    if not body.startswith(PNG_HEAD):
        raise TileMissing("what came back from the map server is not a picture, so it is "
                          "not being shown")
    return body
