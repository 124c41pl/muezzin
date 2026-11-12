"""Solar-position and prayer-time math.

A compact, parameter-driven engine in the same family of published algorithms used
by PrayTimes.org, the adhan libraries (JS/Java/iOS) and Smart Azan's Batoulapps
port. Unlike those, there is no closed enum of "approved" methods: a method is a
plain dataclass of angles and rules, so any community profile is representable.

Conventions
-----------
* All times are *decimal hours in the local civil time* passed in.
* Sunrise/sunset angle: 0.833 deg accounts for refraction + solar semidiameter;
  and the horizon dips 0.0347469 * sqrt(elevation_meters) degrees below it.
* Twilight times solve for the sun reaching -angle degrees below the horizon.
* Asr solves the shadow-length rule (shadow = k * shadow_at_noon + equinox_min).
* Two midnights exist, and ``midnight`` reports whichever one the method
  declares with ``midnight_from_fajr``:
    - solar   midnight: midpoint sunset -> sunrise (majority convention)
    - Kuwaiti midnight: midpoint sunset -> fajr (Jafari / Tehran / Qom rulings;
      also the end of Isha and the start of tahajjud)
  ``true_night`` always carries the Kuwaiti value, whichever way you count.
"""

from dataclasses import dataclass, replace
import logging
import math
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# solar position (mean values; accuracy far below a minute of scheduling)
# ---------------------------------------------------------------------------

_OBLIQUITY_DEG = 23.4397  # mean obliquity of the ecliptic


def _julian_day(year: int, month: int, day: int) -> float:
    """Julian day for 0h local civil time of the given date (no TZ component)."""
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + b - 1524.5


def _mean_quantities(jd: float):
    """(mean anomaly of sun M, mean ecliptic longitude L) in degrees."""
    d = jd - 2451545.0
    m = math.remainder(357.5291 + 0.98560028 * d, 360.0)
    l = math.remainder(280.459 + 0.98564736 * d, 360.0)
    return m, l


def _mod360(x: float) -> float:
    """True modulo into [0, 360). math.remainder is NOT this (it is symmetric)."""
    return x - 360.0 * math.floor(x / 360.0)


def _wrap180(x: float) -> float:
    return (x + 180.0) % 360.0 - 180.0


def sun_position(jd: float):
    """Return (declination_deg, eqt_minutes) for the given Julian day.

    eqt follows the "apparent sundial minus mean clock" convention: positive
    means the sun crosses the meridian *before* mean (clock) noon.
    """
    m, l = _mean_quantities(jd)
    mr, lr = math.radians(m), math.radians(l)
    # ecliptic longitude including the equation of centre
    lam = lr + math.radians(1.915 * math.sin(mr) + 0.020 * math.sin(2 * mr))
    decl = math.degrees(math.asin(math.sin(math.radians(_OBLIQUITY_DEG)) * math.sin(lam)))
    # right ascension from the same ecliptic longitude
    ra = _mod360(math.degrees(math.atan2(
        math.cos(math.radians(_OBLIQUITY_DEG)) * math.sin(lam), math.cos(lam))))
    eqt = _wrap180(l - ra)          # degrees of arc
    return decl, eqt * 4.0          # 1 deg of arc = 4 minutes of time


# ---------------------------------------------------------------------------
# method parameters — the heart of "any method is just a config file"
# ---------------------------------------------------------------------------

ASR_SHADOW_STANDARD = 1.0   # Shafi'i/majority: shadow = shadow_at_noon + 1 * shadow_at_equinox_shadow (=tan(45-decl)) simplified as 1x
ASR_SHADOW_HANAFI = 2.0

HIGH_LAT_NONE = "none"              # leave times as computed (may be missing)
HIGH_LAT_MIDDLE_OF_NIGHT = "middle_of_the_night"
HIGH_LAT_ONE_SEVENTH = "one_seventh"
HIGH_LAT_ANGLE_BASED = "angle_based"


@dataclass
class MethodParams:
    fajr_angle: float = 15.0
    isha_angle: Optional[float] = 15.0   # None => use isha_interval
    isha_interval: Optional[int] = None  # minutes after maghrib
    maghrib_angle_offset: float = 0.0    # degrees added to sunset angle (e.g. +1 for some Maghrib-after-red-disc views)
    midnight_from_fajr: bool = False     # night defined sunset->fajr (Kuwaiti) when True
    high_latitude_rule: str = HIGH_LAT_ONE_SEVENTH
    shurf_angle: Optional[float] = None  # optional duha/shuruq-based extra event angle
    label: str = "custom"


# named presets (documented, overridable — override ANY single number)
PRESETS: dict[str, MethodParams] = {
    "mwls": MethodParams(18.0, 17.0, label="Muslim World League"),
    "isna": MethodParams(15.0, 15.0, label="ISNA (North America)"),
    "egyptian": MethodParams(19.5, 17.5, label="Egyptian General Authority"),
    "karachi": MethodParams(18.0, 18.0, label="Univ. of Sciences, Karachi"),
    "umm_al_qura": MethodParams(18.5, None, isha_interval=90, label="Umm al-Qura, Makkah"),
    "makkah_interval": MethodParams(18.5, None, isha_interval=90, label="Makkah interval variant"),
    "moonsighting": MethodParams(18.0, 17.0, maghrib_angle_offset=0.0, label="Moon Sighting Committee"),
    "kuwait": MethodParams(18.0, 17.5, label="Kuwait"),
    "qatar": MethodParams(18.0, None, isha_interval=90, label="Qatar"),
    "dubai": MethodParams(18.2, 18.2, label="Dubai (UAE)"),
    "singapore": MethodParams(20.0, 18.0, label="MUIS Singapore"),
    "turkey": MethodParams(18.0, 17.5, label="Diyanet, Turkey"),
    "france": MethodParams(12.0, 12.0, label="Muslim Council of France (12 deg)"),
    "tehran": MethodParams(17.7, 14.0, midnight_from_fajr=True, label="Institute of Geophysics, Tehran"),
    "shia_ithna_ashari": MethodParams(16.0, 14.0, midnight_from_fajr=True, label="Shia Ithna-Ashari (Jafari)"),
    "qom": MethodParams(19.0, 14.0, midnight_from_fajr=True, label="Qom (Ayat. Khamenei / Ayat. Khoei variant)"),
    "qom_khamenei_12": MethodParams(12.0, 15.0, midnight_from_fajr=True, label="Qom, 12/15 variant"),
    "othman_local": MethodParams(19.5, None, isha_interval=75, label="example: local masjid with 75-min Isha interval"),
}


@dataclass
class Adjustments:
    """Per-prayer minute offsets (masjid convention, minaret delay, etc.)."""
    fajr: int = 0
    sunrise: int = 0
    dhuhr: int = 0
    asr: int = 0
    maghrib: int = 0
    isha: int = 0


@dataclass
class Location:
    latitude: float
    longitude: float
    timezone: str            # IANA name, e.g. "America/New_York"
    elevation_m: float = 0.0


def _hour_angle(angle_deg: float, decl_deg: float, lat_deg: float) -> Optional[float]:
    """Hour angle (degrees) at which the sun is at -angle_deg elevation. None if never."""
    cos_h = (
        (-math.sin(math.radians(angle_deg)) - math.sin(math.radians(decl_deg)) * math.sin(math.radians(lat_deg)))
        / (math.cos(math.radians(decl_deg)) * math.cos(math.radians(lat_deg)))
    )
    if cos_h > 1.0 or cos_h < -1.0:
        return None
    return math.degrees(math.acos(cos_h))


# ---------------------------------------------------------------------------
# the engine
# ---------------------------------------------------------------------------

@dataclass
class PrayerTimes:
    date: str
    fajr: Optional[float]
    sunrise: Optional[float]
    dhuhr: float
    asr: Optional[float]
    sunset: Optional[float]
    maghrib: Optional[float]
    isha: Optional[float]
    midnight: Optional[float]        # the convention THIS method declares
    true_night: Optional[float]      # sunset -> fajr midpoint (Kuwaiti), always
    shurf: Optional[float] = None


def _local_offset_hours(date, tz: str, lng: float) -> float:
    """Civil-time offset for solar-noon bookkeeping: noon_local = 12 + (lng-15*off)/15 in local time."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    naive = datetime(date.year, date.month, date.day, 12, 0, tzinfo=ZoneInfo(tz))
    return naive.utcoffset().total_seconds() / 3600.0


def compute_times(loc: Location, date, params: MethodParams, asr_shadow: float = ASR_SHADOW_STANDARD,
                  adjustments: Optional[Adjustments] = None) -> PrayerTimes:
    jd = _julian_day(date.year, date.month, date.day)
    tz_offset = _local_offset_hours(date, loc.timezone, loc.longitude)
    transit = lambda jd_x: 12.0 - (loc.longitude - 15.0 * tz_offset) / 15.0 - sun_position(jd_x)[1] / 60.0

    # sample the sun at midnight, then re-sample at local solar noon (declination
    # moves ~0.4 deg/day, so sampling at noon removes most of that error)
    dhuhr = transit(jd)
    decl, eqt = sun_position(jd + (dhuhr - tz_offset) / 24.0)
    dhuhr = 12.0 - (loc.longitude - 15.0 * tz_offset) / 15.0 - eqt / 60.0

    # 0.833 deg covers refraction and the sun's own disc at sea level; on top of
    # that the horizon drops 0.0347469 * sqrt(height in metres) degrees, so a flat
    # on the fifth floor sees sunrise a minute or two early. The height is clamped
    # at zero rather than allowed to turn the square root imaginary below sea level.
    base_angle = 0.833 + 0.0347469 * math.sqrt(max(0.0, loc.elevation_m))

    def time_at_angle(angle: float) -> Optional[float]:
        """Local-clock time at which the sun is -angle deg (after noon side)."""
        ha = _hour_angle(angle, decl, loc.latitude)
        if ha is None:
            return None
        return dhuhr + ha / 15.0

    def before_noon(morning: Optional[float]) -> Optional[float]:
        return None if morning is None else 2.0 * dhuhr - morning

    sunrise = time_at_angle(base_angle)
    sunset = time_at_angle(base_angle)
    sunrise = before_noon(sunrise)
    sunset = sunset

    fajr = time_at_angle(params.fajr_angle)
    fajr = before_noon(fajr)

    maghrib_angle = base_angle + params.maghrib_angle_offset
    maghrib_solar = time_at_angle(maghrib_angle)

    asr = None
    ha = _asr_hour_angle(decl, loc.latitude, asr_shadow)
    if ha is not None:
        asr = dhuhr + ha / 15.0

    # --- night portion + high latitude correction -------------------------
    # The adhan-library convention: night = sunset -> next sunrise, and missing
    # twilight times are placed a fixed fraction into the night from each side.
    solar_night = None
    if sunset is not None and sunrise is not None:
        solar_night = (sunrise - sunset) % 24.0

    def hl(portion: float, morning: bool) -> Optional[float]:
        if solar_night is None:
            return None
        return (sunrise - solar_night * portion) if morning else (sunset + solar_night * portion)

    if fajr is None and params.high_latitude_rule != HIGH_LAT_NONE:
        # the rule's own angle has to travel with the call: without it an
        # angle_based profile silently solves at one seventh of the night, and
        # nothing about the printed time gives that away
        fajr = hl(_portion_for_rule(params, morning=True,
                                    fajr_angle=params.fajr_angle), morning=True)
    # asr is not rescued by a high-latitude rule: the shadow rule has a solution
    # whenever the sun rises at all, and where it does not, there is no asr to find

    if maghrib_solar is None:
        maghrib = None
    else:
        maghrib = maghrib_solar

    if params.isha_interval is not None and maghrib is not None:
        isha = maghrib + params.isha_interval / 60.0
    else:
        isha = time_at_angle(params.isha_angle if params.isha_angle is not None else 17.0)
        if isha is None and params.high_latitude_rule != HIGH_LAT_NONE:
            portion = _portion_for_rule(params, morning=False, fajr_angle=params.fajr_angle,
                                        other_angle=params.isha_angle)
            isha = hl(portion, morning=False)

    # midnight(s). Two conventions exist and which one is correct depends on the
    # madhhab: the common one splits the night sunset -> sunrise (solar
    # midnight), the "Kuwaiti" one splits sunset -> fajr (true night) and is what
    # Jafari/Tehran/Qom rulings use for the end of Isha and the start of the
    # night. `midnight` is the one THIS method observes - so an event written
    # `at: midnight` lands where the method says it should - while `true_night`
    # always carries the Kuwaiti value so both are visible.
    adj = adjustments or Adjustments()

    def off(t, minutes):
        # NOTE: deliberately NOT wrapped into [0,24): a value like 24.06 means
        # "00:04 the following day" and the scheduler turns these into real
        # datetimes. Wrapping would silently move an event by a whole day.
        return None if t is None else t + minutes / 60.0

    maghrib, isha = off(maghrib, adj.maghrib), off(isha, adj.isha)
    if maghrib is not None and isha is not None and isha + 1e-9 < maghrib:
        # a nudge that walks Isha back in front of Maghrib is a typing mistake, not
        # a ruling, so it gets said out loud instead of printed as a fact
        log.warning("%s: isha at %.2f lands before maghrib at %.2f once the "
                    "adjustments are applied; check adjustments.isha and "
                    "adjustments.maghrib", date, isha, maghrib)

    solar_midnight = None
    if sunset is not None and sunrise is not None:
        solar_midnight = sunset + ((24.0 - sunset) + sunrise) / 2.0
    # the night is measured between the maghrib and the fajr this profile actually
    # announces, so a maghrib_angle_offset or a hand nudge moves midnight along
    # with them instead of leaving it parked at the raw solar value
    night_maghrib, night_fajr = maghrib, off(fajr, adj.fajr)
    true_night = None
    if night_maghrib is not None and night_fajr is not None:
        span = (((24.0 - night_maghrib) + night_fajr) if night_maghrib >= night_fajr
                else (night_fajr - night_maghrib))
        true_night = night_maghrib + span / 2.0
    elif sunset is not None and sunrise is not None:
        true_night = solar_midnight  # fallback when no fajr is computable
    midnight = true_night if params.midnight_from_fajr else solar_midnight

    shurf = None
    if params.shurf_angle is not None:
        s = time_at_angle(params.shurf_angle)
        shurf = before_noon(s)

    return PrayerTimes(
        date=f"{date.year:04d}-{date.month:02d}-{date.day:02d}",
        fajr=off(fajr, adj.fajr),
        sunrise=off(sunrise, adj.sunrise),
        dhuhr=off(dhuhr, adj.dhuhr),
        asr=off(asr, adj.asr),
        sunset=off(sunset, 0),
        maghrib=maghrib,
        isha=isha,
        midnight=midnight,
        true_night=true_night,
        shurf=shurf,
    )


def _asr_hour_angle(decl: float, lat: float, shadow: float) -> Optional[float]:
    """Hour angle when shadow length = shadow_at_noon + shadow * (equinox noon shadow).

    PrayTimes convention: t = 1 + shadow factor; the "standard" madhhab uses 1,
    Hanafi 2. Generalised: cot(altitude) = shadow + tan|lat - decl| (PrayTimes formula).
    """
    t = shadow  # 1 or 2 in the classical rule
    # PrayTimes: inverse cotangent of (t + tan(|lat - decl|))
    val = math.tan(math.radians(abs(lat - decl))) + t
    cot_alt = val
    alt = math.degrees(math.atan2(1.0, cot_alt))
    return _hour_angle(-alt, decl, lat)


def _portion_for_rule(params: MethodParams, morning: bool, fajr_angle: float = None,
                      other_angle: float = None) -> float:
    rule = params.high_latitude_rule
    if rule == HIGH_LAT_ONE_SEVENTH:
        return 1.0 / 7.0
    if rule == HIGH_LAT_MIDDLE_OF_NIGHT:
        return 0.5
    if rule == HIGH_LAT_ANGLE_BASED:
        a = fajr_angle if morning else other_angle
        night_portion = a / 60.0 if a else 1.0 / 7.0
        return night_portion
    return 1.0 / 7.0


def method_from_config(cfg: dict) -> MethodParams:
    """Resolve a config block to MethodParams: named preset + arbitrary overrides.

    Accepts the shapes people actually write:

        method: qom
        method: {preset: qom, isha_angle: 15}
        method: {fajr_angle: 16.5, isha_angle: 15.0}      # no preset at all

    That last one is the point of the whole project: if your authority's numbers
    are not in the built-in list, you type them in and they work.
    """
    spec = dict(cfg)
    block = spec.get("method", spec.get("preset", "mwls"))
    if isinstance(block, dict):
        inner = dict(block)
        block = inner.pop("preset", None) or inner.pop("name", None)
        spec.update(inner)
    name = block or "mwls"
    base = PRESETS.get(name)
    if base is None:
        raise KeyError(f"unknown method preset: {name!r}; "
                       f"known: {', '.join(sorted(PRESETS))} (or provide explicit angles)")
    p = replace(base)
    for key in ("fajr_angle", "isha_angle", "isha_interval", "maghrib_angle_offset",
                "midnight_from_fajr", "high_latitude_rule", "shurf_angle"):
        if key in spec:
            setattr(p, key, spec[key])
    if spec.get("label"):
        p.label = spec["label"]
    # Angles are the numbers people copy out of a table, so a typo here is the
    # most likely way to get a wrong adhan time; catch it loudly instead of
    # quietly computing a time nobody recognises.
    ranges = {"fajr_angle": (0.0, False), "isha_angle": (0.0, False),
              "shurf_angle": (0.0, False),
              # 0 is the normal value here: maghrib AT sunset
              "maghrib_angle_offset": (0.0, True)}
    for key, (low, inclusive) in ranges.items():
        value = getattr(p, key)
        if value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"method.{key} must be a number of degrees, got {value!r}")
            if (value < low if inclusive else value <= low) or value >= 90.0:
                bound = f"{low} or more" if inclusive else f"more than {low}"
                raise ValueError(f"method.{key} must be {bound} and under 90 degrees, got {value}")
            setattr(p, key, value)
    if p.isha_interval is not None:
        p.isha_interval = float(p.isha_interval)
        if not 0.0 < p.isha_interval < 720.0:
            # minutes after maghrib: Umm al-Qura is 90, so anything over 12 hours
            # is a typo for an angle, not an interval
            raise ValueError(f"method.isha_interval is MINUTES after maghrib, got {p.isha_interval}")
    return p
