"""Work out the arithmetic Hijri calendar that matches the published values.

Not library code: a small brute-force tabular calendar (354/355-day years, odd
months 30 days, even 29, month 12 gains a day in a leap year) fitted against the
Hijri dates aladhan publishes, so the fit is a fact we can re-test rather than a
number remembered from a book.
"""
from __future__ import annotations

import datetime as dt

# (gregorian, day, month, year) as published by api.aladhan.com on 2026-11-10
FIXTURES = [
    (2025, 6, 7, 11, 12, 1446),
    (2026, 11, 10, 30, 5, 1448),
    (2030, 1, 1, 26, 8, 1451),
    (2024, 7, 6, 30, 12, 1445),
    (2025, 3, 13, 13, 9, 1446),
    (2026, 5, 26, 9, 12, 1447),
    (2027, 1, 1, 23, 7, 1448),
    (2029, 10, 10, 2, 6, 1451),
    (2031, 3, 1, 7, 11, 1452),
]

CYCLE_LEAPS = {
    "kuwaiti": {2, 5, 7, 10, 13, 16, 18, 21, 24, 26, 29},
    "tabular": {2, 5, 8, 11, 14, 17, 19, 22, 25, 28, 30},
    "french": {2, 5, 9, 12, 15, 18, 21, 24, 27, 29, 30},
}


def jdn(date: dt.date) -> int:
    """Julian day number for a civil Gregorian date (noon convention)."""
    a = (14 - date.month) // 12
    y = date.year + 4800 - a
    m = date.month + 12 * a - 3
    return (date.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045)


def month_days(year: int, month: int, leaps: set[int]) -> int:
    if month == 12:
        return 30 if (year % 30) in leaps else 29
    return 30 if month % 2 else 29


def to_hijri(date: dt.date, leaps: set[int], epoch_jdn: int) -> tuple[int, int, int]:
    """Brute force from the epoch: fast enough to run a handful of times a day."""
    k = jdn(date) - epoch_jdn
    if k < 0:
        raise ValueError("before the Hijri epoch")
    year = 1
    while True:
        span = 354 + (1 if (year % 30) in leaps else 0)
        if k < span:
            break
        k -= span
        year += 1
    month = 1
    while True:
        span = month_days(year, month, leaps)
        if k < span:
            break
        k -= span
        month += 1
    return year, month, k + 1


for name, leaps in CYCLE_LEAPS.items():
    best = None
    for shift in range(-4, 5):
        epoch = 1948440 + shift          # 1 Muharram 1 AH, Friday 16 Jul 622 CE (Julian)
        hits = 0
        for gy, gm, gd, hd, hm, hy in FIXTURES:
            try:
                got = to_hijri(dt.date(gy, gm, gd), leaps, epoch)
            except ValueError:
                continue
            hits += got == (hy, hm, hd)
        if best is None or hits > best[0]:
            best = (hits, shift)
    print(f"{name:8s} best {best[0]}/{len(FIXTURES)} at shift {best[1]:+d}")

# with the best candidate, show any misses so we can see how far off they are
leaps = CYCLE_LEAPS["kuwaiti"]
for shift in (-2, -1, 0, 1, 2):
    epoch = 1948440 + shift
    miss = []
    for gy, gm, gd, hd, hm, hy in FIXTURES:
        got = to_hijri(dt.date(gy, gm, gd), leaps, epoch)
        if got != (hy, hm, hd):
            want = dt.date(gy, gm, gd)
            off = jdn(want) - jdn(dt.date(2026, 11, 10))
            miss.append((f"{gy}-{gm:02d}-{gd:02d}", got, (hy, hm, hd)))
    print(f"kuwaiti shift {shift:+d}: {len(miss)} misses -> {miss[:2]}")
