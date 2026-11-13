"""City centres for `muezzin where`, with no network involved.

Location is the first thing a profile needs, and it is the one thing a person can
get wrong without anything complaining: a coordinate copied from somewhere, or the
starter's placeholder left in place, produces a timetable that looks completely
normal and belongs to another city. So the lookup is here, offline, in the same
package as the engine.

The table is deliberately small and deliberately blunt. Each row is a *city
centre*: the middle of town, not your street, and good enough to get a family's
timetable within a minute or two of what a printed schedule shows. Someone who
wants the times for their own address types their own numbers into the profile,
and that is always allowed - nothing here is privileged over a hand-written
coordinate.

Why the time zone sits in the same row as the coordinates is worth being plain
about. The zone decides only how the clock is labelled. Orlando, Florida and Erie,
Pennsylvania share `America/New_York`, and their Fajr and Maghrib land at
different clock times, because the sun sits at a different angle above each of
them. So a city lookup is really two facts at once: where the observer is, and
what the people there call the hour.

Ambiguity is not resolved by guessing. `London` matches two rows and says so,
because picking one silently would put someone's prayer times in another country.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

__all__ = ["Place", "PLACES", "ALIASES", "find", "lookup", "AmbiguousPlace",
           "UnknownPlace", "distance_km", "bearing", "nearest"]


@dataclass(frozen=True)
class Place:
    """One city centre, and the zone its civil clock runs on."""

    name: str
    region: str
    latitude: float
    longitude: float
    timezone: str

    @property
    def label(self) -> str:
        return f"{self.name}, {self.region}" if self.region else self.name

    def as_config(self) -> dict:
        """The three lines a profile needs, in the order it reads best."""
        return {"latitude": self.latitude, "longitude": self.longitude,
                "timezone": self.timezone}


# (name, region, latitude, longitude, timezone) - city centres, in no particular
# order. Latitudes and longitudes are the usual published centre points, rounded
# to four decimals: a tenth of a kilometre is a couple of seconds of arc, far
# below the minute a person can act on.
_ROWS = [
    # the places whose published timetables are already presets
    ("Qom", "Iran", 34.6416, 50.8799, "Asia/Tehran"),
    ("Tehran", "Iran", 35.6892, 51.3890, "Asia/Tehran"),
    ("Mashhad", "Iran", 36.2605, 59.6168, "Asia/Tehran"),
    ("Isfahan", "Iran", 32.6546, 51.6680, "Asia/Tehran"),
    ("Shiraz", "Iran", 29.5918, 52.5837, "Asia/Tehran"),
    ("Tabriz", "Iran", 38.0800, 46.2900, "Asia/Tehran"),
    ("Ahvaz", "Iran", 31.3183, 48.6706, "Asia/Tehran"),
    ("Najaf", "Iraq", 31.9994, 44.3140, "Asia/Baghdad"),
    ("Karbala", "Iraq", 32.6160, 44.0242, "Asia/Baghdad"),
    ("Baghdad", "Iraq", 33.3152, 44.4209, "Asia/Baghdad"),
    ("Makkah", "Saudi Arabia", 21.4225, 39.8262, "Asia/Riyadh"),
    ("Medina", "Saudi Arabia", 24.4686, 39.6142, "Asia/Riyadh"),
    ("Dammam", "Saudi Arabia", 26.4207, 50.0888, "Asia/Riyadh"),
    ("Riyadh", "Saudi Arabia", 24.7136, 46.6753, "Asia/Riyadh"),
    ("Kuwait City", "Kuwait", 29.3759, 47.9774, "Asia/Kuwait"),
    ("Manama", "Bahrain", 26.2285, 50.5860, "Asia/Bahrain"),
    ("Doha", "Qatar", 25.2854, 51.5310, "Asia/Qatar"),
    ("Dubai", "United Arab Emirates", 25.2048, 55.2708, "Asia/Dubai"),
    ("Beirut", "Lebanon", 33.8938, 35.5018, "Asia/Beirut"),
    ("Damascus", "Syria", 33.5138, 36.2765, "Asia/Damascus"),
    ("Amman", "Jordan", 31.9539, 35.9106, "Asia/Amman"),
    ("Karachi", "Pakistan", 24.8607, 67.0011, "Asia/Karachi"),
    ("Lahore", "Pakistan", 31.5204, 74.3587, "Asia/Karachi"),
    ("Dhaka", "Bangladesh", 23.8103, 90.4125, "Asia/Dhaka"),
    ("Mumbai", "India", 19.0760, 72.8777, "Asia/Kolkata"),
    ("Delhi", "India", 28.6139, 77.2090, "Asia/Kolkata"),
    ("Hyderabad", "India", 17.3850, 78.4867, "Asia/Kolkata"),
    ("Kuala Lumpur", "Malaysia", 3.1390, 101.6869, "Asia/Kuala_Lumpur"),
    ("Singapore", "Singapore", 1.3521, 103.8198, "Asia/Singapore"),
    ("Jakarta", "Indonesia", -6.2088, 106.8456, "Asia/Jakarta"),
    ("Tashkent", "Uzbekistan", 41.2995, 69.2401, "Asia/Tashkent"),
    ("Baku", "Azerbaijan", 40.4093, 49.8671, "Asia/Baku"),
    ("Cairo", "Egypt", 30.0444, 31.2357, "Africa/Cairo"),
    ("Alexandria", "Egypt", 31.2001, 29.9187, "Africa/Cairo"),
    ("Casablanca", "Morocco", 33.5731, -7.5898, "Africa/Casablanca"),
    ("Algiers", "Algeria", 36.7538, 3.0588, "Africa/Algiers"),
    ("Tunis", "Tunisia", 36.8065, 10.1815, "Africa/Tunis"),
    ("Lagos", "Nigeria", 6.5244, 3.3792, "Africa/Lagos"),
    ("Accra", "Ghana", 5.6037, -0.1870, "Africa/Accra"),
    ("Nairobi", "Kenya", -1.2921, 36.8219, "Africa/Nairobi"),
    ("Johannesburg", "South Africa", -26.2041, 28.0473, "Africa/Johannesburg"),
    ("Istanbul", "Turkey", 41.0082, 28.9784, "Europe/Istanbul"),
    ("London", "United Kingdom", 51.5074, -0.1278, "Europe/London"),
    ("Birmingham", "United Kingdom", 52.4862, -1.8904, "Europe/London"),
    ("Paris", "France", 48.8566, 2.3522, "Europe/Paris"),
    ("Berlin", "Germany", 52.5200, 13.4050, "Europe/Berlin"),
    ("Amsterdam", "Netherlands", 52.3676, 4.9041, "Europe/Amsterdam"),
    ("Stockholm", "Sweden", 59.3293, 18.0686, "Europe/Stockholm"),
    ("Vienna", "Austria", 48.2082, 16.3738, "Europe/Vienna"),
    ("Madrid", "Spain", 40.4168, -3.7038, "Europe/Madrid"),
    ("Lisbon", "Portugal", 38.7223, -9.1393, "Europe/Lisbon"),
    ("Moscow", "Russia", 55.7558, 37.6173, "Europe/Moscow"),
    ("Toronto", "Ontario", 43.6532, -79.3832, "America/Toronto"),
    ("Montreal", "Quebec", 45.5017, -73.5673, "America/Toronto"),
    ("London", "Ontario", 42.9846, -81.2441, "America/Toronto"),
    ("New York", "New York", 40.7128, -74.0060, "America/New_York"),
    ("Newark", "New Jersey", 40.7357, -74.1724, "America/New_York"),
    ("Philadelphia", "Pennsylvania", 39.9526, -75.1652, "America/New_York"),
    ("Boston", "Massachusetts", 42.3601, -71.0589, "America/New_York"),
    ("Washington", "District of Columbia", 38.9072, -77.0369, "America/New_York"),
    ("Atlanta", "Georgia", 33.7490, -84.3880, "America/New_York"),
    ("Orlando", "Florida", 28.5383, -81.3792, "America/New_York"),
    ("Tampa", "Florida", 27.9506, -82.4572, "America/New_York"),
    ("Miami", "Florida", 25.7617, -80.1918, "America/New_York"),
    ("Cleveland", "Ohio", 41.4993, -81.6944, "America/New_York"),
    ("Columbus", "Ohio", 39.9612, -82.9988, "America/New_York"),
    ("Erie", "Pennsylvania", 42.1292, -80.0851, "America/New_York"),
    ("Detroit", "Michigan", 42.3314, -83.0458, "America/Detroit"),
    ("Dearborn", "Michigan", 42.3223, -83.1763, "America/Detroit"),
    ("Indianapolis", "Indiana", 39.7684, -86.1581, "America/Indiana/Indianapolis"),
    ("Chicago", "Illinois", 41.8781, -87.6298, "America/Chicago"),
    ("Birmingham", "Alabama", 33.5186, -86.8104, "America/Chicago"),
    ("Houston", "Texas", 29.7604, -95.3698, "America/Chicago"),
    ("Dallas", "Texas", 32.7767, -96.7970, "America/Chicago"),
    ("Phoenix", "Arizona", 33.4484, -112.0740, "America/Phoenix"),
    ("Los Angeles", "California", 34.0522, -118.2437, "America/Los_Angeles"),
    ("San Francisco", "California", 37.7749, -122.4194, "America/Los_Angeles"),
    ("Sydney", "Australia", -33.8688, 151.2093, "Australia/Sydney"),
    ("Melbourne", "Australia", -37.8136, 144.9631, "Australia/Melbourne"),
]

PLACES: tuple[Place, ...] = tuple(
    Place(name=name, region=region, latitude=lat, longitude=lon, timezone=tz)
    for name, region, lat, lon, tz in _ROWS
)

# Spelling a city the way people actually type it. Kept short on purpose: an
# alias table that tries to cover every nickname becomes a second list nobody
# maintains. The keys are written the way `_normalise` below leaves them -
# folded, punctuation gone - because that is the only form they are ever looked
# up in; `"washington d.c."` arrives here as `washington d c`.
ALIASES = {
    "nyc": "New York",
    "ny": "New York",
    "new york city": "New York",
    "mecca": "Makkah",
    "mcg": "Makkah",
    "dc": "Washington",
    "d c": "Washington",
    "washington dc": "Washington",
    "washington d c": "Washington",
    "montréal": "Montreal",
}

_PUNCT = re.compile(r"[.,']+")


def _normalise(text: str) -> str:
    """Fold case, drop the punctuation a region name brings with it, and squash
    runs of spaces, so `Washington, D.C.` and `washington dc` meet."""
    return " ".join(_PUNCT.sub(" ", text.casefold()).split())


def find(query: str) -> list[Place]:
    """Every row that could be what was asked for, in label order.

    Empty means the table has no such city. More than one means the question was
    ambiguous, and the caller has to ask - not choose.
    """
    wanted = _normalise(query)
    if not wanted:
        return []
    wanted = ALIASES.get(wanted, wanted)
    wanted_norm = _normalise(wanted)
    words = set(wanted_norm.split())

    exact, partial = [], []
    for place in PLACES:
        label = _normalise(place.label)
        if wanted_norm in (_normalise(place.name), label):
            exact.append(place)
        elif words and words <= set(label.split()):
            # `orlando florida` against `Orlando, Florida`: the extra word is a
            # region, so it narrows rather than misses.
            partial.append(place)
    hits = exact or partial
    return sorted(hits, key=lambda p: p.label)


# How far apart two places are, and in which direction.
#
# Neither has anything to do with prayer times: the online lookup borrows a time zone
# from the nearest city in this table when the map did not name one, and the page draws
# a small picture of where the chosen point sits among the places it can name. A sphere
# is used on purpose: the difference against an ellipsoid is a few tenths of a percent,
# which is nothing beside the fact that a city centre sits a kilometre or two from any
# given house in it.
EARTH_KM = 6371.0


def distance_km(north_a: float, east_a: float, north_b: float, east_b: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    phi_a, phi_b = math.radians(north_a), math.radians(north_b)
    d_phi = phi_b - phi_a
    d_lambda = math.radians(east_b - east_a)
    haversine = (math.sin(d_phi / 2.0) ** 2
                 + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2.0) ** 2)
    return 2.0 * EARTH_KM * math.asin(math.sqrt(haversine))


def bearing(north_a: float, east_a: float, north_b: float, east_b: float) -> float:
    """The direction from A to B, degrees clockwise from true north, 0 to 360."""
    phi_a, phi_b = math.radians(north_a), math.radians(north_b)
    d_lambda = math.radians(east_b - east_a)
    y = math.sin(d_lambda) * math.cos(phi_b)
    x = math.cos(phi_a) * math.sin(phi_b) - math.sin(phi_a) * math.cos(phi_b) * math.cos(d_lambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def nearest(latitude: float, longitude: float, count: int = 5) -> list[tuple[Place, float]]:
    """The `count` closest city centres, nearest first, each with its distance in km.

    This answers "what is this point near" without a network, which is the part worth
    answering offline: a coordinate copied wrongly is usually obvious once something
    says it sits 4,000 km from the city it was meant to be.
    """
    scored = [(place, distance_km(latitude, longitude, place.latitude, place.longitude))
              for place in PLACES]
    scored.sort(key=lambda pair: pair[1])
    return scored[:max(0, count)]


class UnknownPlace(LookupError):
    def __init__(self, query: str):
        self.query = query
        super().__init__(f"no city centre called {query!r} in the table")


class AmbiguousPlace(LookupError):
    def __init__(self, query: str, options: list[Place]):
        self.query, self.options = query, options
        super().__init__(f"{query!r} could be " + " or ".join(p.label for p in options))


def lookup(query: str) -> Place:
    """The one row the query means, or a clear complaint about why there is not one."""
    hits = find(query)
    if not hits:
        raise UnknownPlace(query)
    if len(hits) > 1:
        raise AmbiguousPlace(query, hits)
    return hits[0]
