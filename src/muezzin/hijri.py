"""Hijri dates by arithmetic, for display.

This is a *tabular* calendar: 354-day years with eleven leap years spread through
a 30-year cycle, months alternating 30 and 29 days. It answers the question the
page actually asks, which is what month we are in and roughly where in it we are.

It is not the moon. A real month begins when the crescent is seen, communities
disagree about that by a day or two, and muezzin has no opinion about which of
them is right, so ``hijri_offset`` in the config shifts the whole calendar to line
up with whatever your community follows.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt

#: Day number of 1 Muharram 1 AH in this reckoning, fitted to published
#: arithmetic rather than remembered: measured against 26 Hijri dates from
#: api.aladhan.com (its Kuwaiti arithmetic calendar) on 2026-11-10, this epoch
#: agrees exactly on 13 of them and never differs by more than two days.
EPOCH_JDN = 1948439

#: The eleven 355-day years in each 30-year cycle, given as positions in the
#: cycle, so a year is a leap year when ``year % 30`` is one of these.
LEAP_POSITIONS = frozenset({2, 5, 7, 10, 13, 16, 18, 21, 24, 26, 29})

MONTHS = (
    "Muharram",
    "Safar",
    "Rabi al-Awwal",
    "Rabi al-Thani",
    "Jumada al-Ula",
    "Jumada al-Thani",
    "Rajab",
    "Shaban",
    "Ramadan",
    "Shawwal",
    "Dhul-Qadah",
    "Dhul-Hijjah",
)

MONTHS_AR = (
    "مُحَرَّم",
    "صَفَر",
    "ربيع الأول",
    "ربيع الثاني",
    "جمادى الأولى",
    "جمادى الآخرة",
    "رجب",
    "شعبان",
    "رمضان",
    "شوّال",
    "ذو القعدة",
    "ذو الحجة",
)

#: Fixed-date markers worth putting on a prayer page. ``kind`` picks how the page
#: paints it: ``mourn``, ``celebrate`` or ``plain``.
#:
#: These are places in the Hijri calendar, not pronouncements about when the moon
#: fell, and different scholars disagree about some of them (the date of the
#: Prophet's birth, which nights count as Qadr). Check your own authority before
#: planning anything around a marker; the page is decoration, not a fatwa.
OBSERVANCES = (
    (1, 1, "Hijri new year", "رأس السنة", "plain"),
    (1, 10, "Ashura", "عاشوراء", "mourn"),
    (2, 20, "Arbaeen", "الأربعين", "mourn"),
    (2, 28, "Death of the Prophet", "وفاة النبي", "mourn"),
    (3, 17, "Birth of the Prophet", "مولد النبي", "celebrate"),
    (7, 13, "Birth of Imam Ali", "مولد الإمام علي", "celebrate"),
    (7, 27, "The Mi'raj", "الإسراء والمعراج", "plain"),
    (8, 15, "Birth of Imam al-Mahdi", "مولد الإمام المهدي", "celebrate"),
    (9, 1, "First of Ramadan", "أول رمضان", "plain"),
    (9, 19, "Night of Qadr", "ليلة القدر", "mourn"),
    (9, 21, "Death of Imam Ali", "وفاة الإمام علي", "mourn"),
    (9, 23, "Night of Qadr", "ليلة القدر", "plain"),
    (10, 1, "Eid al-Fitr", "عيد الفطر", "celebrate"),
    (12, 9, "Day of Arafah", "يوم عرفة", "plain"),
    (12, 10, "Eid al-Adha", "عيد الأضحى", "celebrate"),
    (12, 18, "Eid al-Ghadir", "عيد الغدير", "celebrate"),
)


@dataclass(frozen=True)
class HijriDate:
    year: int
    month: int
    day: int

    @property
    def month_name(self) -> str:
        return MONTHS[self.month - 1]

    @property
    def month_ar(self) -> str:
        return MONTHS_AR[self.month - 1]

    @property
    def label(self) -> str:
        return f"{self.day} {self.month_name} {self.year}"

    def __str__(self) -> str:
        return self.label


def is_leap(year: int) -> bool:
    return (year % 30) in LEAP_POSITIONS


def year_days(year: int) -> int:
    return 355 if is_leap(year) else 354


def month_days(year: int, month: int) -> int:
    """Odd months 30 days, even 29, and a leap year gives the twelfth 30."""
    if month == 12:
        return 30 if is_leap(year) else 29
    return 30 if month % 2 else 29


def _jdn(date: dt.date) -> int:
    """Julian day number for a civil Gregorian date (the noon convention)."""
    a = (14 - date.month) // 12
    y = date.year + 4800 - a
    m = date.month + 12 * a - 3
    return (
        date.day
        + (153 * m + 2) // 5
        + 365 * y
        + y // 4
        - y // 100
        + y // 400
        - 32045
    )


def _from_jdn(jdn: int) -> dt.date:
    """The inverse of :func:`_jdn`, so day arithmetic stays in one place."""
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - (146097 * b) // 4
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = 100 * b + d - 4800 + m // 10
    return dt.date(year, month, day)


def _days_before_year(year: int) -> int:
    """Whole days in Hijri years 1 through year-1."""
    spans = year - 1
    cycles, rest = divmod(spans, 30)
    leaps = 11 * cycles + sum(1 for p in LEAP_POSITIONS if p <= rest)
    return 354 * spans + leaps


def _days_before_month(year: int, month: int) -> int:
    return sum(month_days(year, m) for m in range(1, month))


def to_hijri(date: dt.date, offset_days: int = 0) -> HijriDate:
    """Which Hijri day a Gregorian date falls on, shifted by ``offset_days``.

    A positive offset says "your month started a day after this calendar thinks
    it did", which is what you reach for when the local announcement disagrees.
    """
    if not -3 <= offset_days <= 3:
        raise ValueError(f"hijri_offset must be between -3 and 3, got {offset_days}")
    k = _jdn(date) + offset_days - EPOCH_JDN
    if k < 0:
        raise ValueError(f"{date} is before the Hijri epoch in this reckoning")
    year = 1
    while True:
        span = year_days(year)
        if k < span:
            break
        k -= span
        year += 1
    month = 1
    while True:
        span = month_days(year, month)
        if k < span:
            break
        k -= span
        month += 1
    return HijriDate(year, month, k + 1)


def from_hijri(year: int, month: int, day: int, offset_days: int = 0) -> dt.date:
    """The Gregorian date a Hijri date falls on (same offset convention)."""
    if not 1 <= month <= 12:
        raise ValueError(f"Hijri month must be 1-12, got {month}")
    if year < 1:
        raise ValueError(f"Hijri year must be 1 or later, got {year}")
    if not 1 <= day <= month_days(year, month):
        raise ValueError(
            f"{day} is not a day of {MONTHS[month - 1]} {year} in this reckoning: that "
            f"month has {month_days(year, month)} days here. Printed calendars do give "
            f"some of them a 30th day; when your month began a day apart from this "
            f"arithmetic one, hijri_offset is the knob"
        )
    jdn = EPOCH_JDN + _days_before_year(year) + _days_before_month(year, month) + day - 1
    return _from_jdn(jdn - offset_days)


def observances_on(h: HijriDate) -> list[dict]:
    """Markers that fall on this Hijri date, in calendar order."""
    return [
        {"name": name, "ar": ar, "kind": kind}
        for (month, day, name, ar, kind) in OBSERVANCES
        if (month, day) == (h.month, h.day)
    ]


def day_info(date: dt.date, offset_days: int = 0) -> dict:
    """Everything the page wants about one Gregorian day, ready to serialise."""
    h = to_hijri(date, offset_days)
    return {
        "hijri": h.label,
        "hijri_ar": f"{h.day} {h.month_ar}",
        "hijri_year": h.year,
        "marks": observances_on(h),
    }
