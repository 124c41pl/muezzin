"""Re-run the published-date comparison with every comparison date fetched from
the API, so the table is captured rather than remembered.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from muezzin.hijri import from_hijri, to_hijri  # noqa: E402

DATES = [
    dt.date(y, m, d)
    for (y, m, d) in [
        (2024, 1, 1), (2024, 3, 10), (2024, 7, 6), (2024, 7, 16),
        (2025, 2, 28), (2025, 3, 1), (2025, 3, 13), (2025, 3, 30),
        (2025, 6, 6), (2025, 6, 26), (2025, 7, 5), (2025, 12, 31),
        (2026, 2, 4), (2026, 3, 19), (2026, 5, 26), (2026, 6, 3),
        (2026, 11, 10), (2027, 1, 1), (2027, 2, 7), (2027, 8, 20),
        (2028, 1, 1), (2028, 6, 15), (2029, 10, 10), (2030, 1, 1),
        (2031, 3, 1), (2035, 7, 4),
    ]
]

rows = []
for date in DATES:
    stamp = f"{date.day:02d}-{date.month:02d}-{date.year}"
    with urllib.request.urlopen(
        f"https://api.aladhan.com/v1/timings/{stamp}?latitude=40.7&longitude=-74&method=2",
        timeout=30,
    ) as r:
        h = json.load(r)["data"]["date"]["hijri"]
    want = (int(h["year"]), int(h["month"]["number"]), int(h["day"]))
    got = to_hijri(date)
    mine = (got.year, got.month, got.day)
    delta = None
    for probe in range(-5, 6):
        shift = date + dt.timedelta(days=probe)
        h2 = to_hijri(shift)
        if (h2.year, h2.month, h2.day) == want:
            delta = probe
            break
    rows.append((date, mine, want, delta))
    print(f"{'ok  ' if mine == want else 'off'} {date} ours {got.label:26s} "
          f"published {want[2]:2d} {h['month']['en'][:14]:14s} {want[0]}"
          f"{'' if delta is None else f'  needs {delta:+d} day shift'}")

exact = sum(1 for r in rows if r[1] == r[2])
within1 = sum(1 for r in rows if r[3] is not None and abs(r[3]) <= 1)
within2 = sum(1 for r in rows if r[3] is not None and abs(r[3]) <= 2)
worst = max((abs(r[3]) for r in rows if r[3] is not None), default=0)
print(f"\n{exact}/{len(rows)} exact, {within1} within a day, {within2} within two, "
      f"worst {worst} days")

print("\nthe same table as a python literal, for tests:")
for date, mine, want, delta in rows:
    print(f"    (dt.date({date.year}, {date.month}, {date.day}), {want}),")
