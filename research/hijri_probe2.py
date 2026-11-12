"""Second pass: the Kuwaiti calendar published by aladhan does not use a fixed
leap-year position list, so try the year-length rules that are written as
arithmetic instead. Still brute force, still fitted to published values.
"""
from __future__ import annotations

import datetime as dt

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
    (2024, 1, 1, 19, 11, 1445),
    (2025, 12, 31, 10, 6, 1447),
    (2035, 7, 4, None, None, None),   # no published value: keep as unknown
]
FIXTURES = [f for f in FIXTURES if f[3] is not None]


def jdn(date: dt.date) -> int:
    a = (14 - date.month) // 12
    y = date.year + 4800 - a
    m = date.month + 12 * a - 3
    return (date.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045)


RULES = {
    # name: predicate on the Hijri year -> is it 355 days?
    "kuwaiti-dm":   lambda y: ((11 * y + 14) % 30) > 10,
    "kuwaiti-not":  lambda y: ((11 * y + 14) % 30) <= 10,
    "3y+11":        lambda y: ((3 * y + 11) % 30) <= 10,
    "3y+13":        lambda y: ((3 * y + 13) % 30) <= 10,
    "11y+11":       lambda y: ((11 * y + 11) % 30) > 10,
    "11y+4":        lambda y: ((11 * y + 4) % 30) > 10,
}
POSITIONS = {
    "kuwaiti-pos": {2, 5, 7, 10, 13, 16, 18, 21, 24, 26, 29},
    "tabular-pos": {2, 5, 8, 11, 14, 17, 19, 22, 25, 28, 30},
}


def month_days(year, month, leap):
    if month == 12:
        return 30 if leap(year) else 29
    return 30 if month % 2 else 29


def to_hijri(date, leap, epoch_jdn):
    k = jdn(date) - epoch_jdn
    if k < 0:
        raise ValueError("before the epoch")
    year = 1
    while True:
        span = 354 + (1 if leap(year) else 0)
        if k < span:
            break
        k -= span
        year += 1
    month = 1
    while True:
        span = month_days(year, month, leap)
        if k < span:
            break
        k -= span
        month += 1
    return year, month, k + 1


def month_days_alt(year, month, leap):
    """Some Kuwaiti descriptions alternate from the *other* end of the year."""
    if month == 12:
        return 30 if leap(year) else 29
    return 29 if month % 2 else 30


for label, leap in list(RULES.items()) + [
        (name, (lambda y, s=pos: (y % 30) in s)) for name, pos in POSITIONS.items()]:
    for month_rule in (month_days, month_days_alt):
        best = None
        for shift in range(-3, 3):
            hits = 0
            for gy, gm, gd, hd, hm, hy in FIXTURES:
                try:
                    got = to_hijri(dt.date(gy, gm, gd), leap, 1948440 + shift)
                except ValueError:
                    continue
                hits += got == (hy, hm, hd)
            if best is None or hits > best[0]:
                best = (hits, shift)
        if best[0] >= 7:
            print(f"{label:12s} months={'alt' if month_rule is month_days_alt else 'std'}"
                  f"  best {best[0]}/{len(FIXTURES)} at shift {best[1]:+d}")
print("done")
