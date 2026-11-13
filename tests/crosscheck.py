"""Compare muezzin.calc against the independent (LGPL) adhan.py package.

adhan.py is used ONLY as an oracle at test time - none of its code is part of
muezzin. Note adhan.py 0.1.1 has a known hemisphere bug in solar noon (it uses
abs(longitude)), so the oracle comparison is limited to western longitudes;
eastern-hemisphere sites are checked with internal invariants instead.

Run: python tests/crosscheck.py
"""
import datetime as dt
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from muezzin import calc

try:
    from adhan.adhan import adhan as ref_adhan
except ImportError:
    print("adhan.py not installed (pip install adhan); skipping oracle comparison")
    ref_adhan = None

# name, lat, lng, ref param dict, our preset, asr shadow factor, date
ORACLE_CASES = [
    ("ISNA NYC", 40.7128, -74.0060, {"fajr_angle": 15, "isha_angle": 15, "asr_multiplier": 1}, calc.PRESETS["isna"], 1.0, dt.date(2026, 11, 10)),
    ("MWL London", 51.5074, -0.1278, {"fajr_angle": 18, "isha_angle": 17, "asr_multiplier": 1}, calc.PRESETS["mwls"], 1.0, dt.date(2026, 11, 10)),
    ("Karachi", 24.8607, -67.0011, {"fajr_angle": 18, "isha_angle": 18, "asr_multiplier": 1}, calc.PRESETS["karachi"], 1.0, dt.date(2026, 1, 15)),
    ("Hanafi asr NYC", 40.7128, -74.0060, {"fajr_angle": 15, "isha_angle": 15, "asr_multiplier": 2}, calc.PRESETS["isna"], 2.0, dt.date(2026, 11, 10)),
]

# eastern-hemisphere sites: internal invariants (solar geometry must be symmetric about dhuhr)
INVARIANT_CASES = [
    ("Tehran (summer solstice)", 35.6892, 51.3890, calc.PRESETS["tehran"], dt.date(2026, 6, 21)),
    ("Qom jafari", 34.6416, 50.8799, calc.PRESETS["shia_ithna_ashari"], dt.date(2026, 11, 10)),
    ("Makkah umm al-Qura", 21.4225, 39.8262, calc.PRESETS["umm_al_qura"], dt.date(2026, 11, 10)),
    ("Reykjavik (extreme latitude)", 64.1466, -21.9426, calc.PRESETS["mwls"], dt.date(2026, 6, 21)),
    ("Reykjavik (winter)", 64.1466, -21.9426, calc.PRESETS["mwls"], dt.date(2026, 12, 21)),
]


def fmt(h):
    if h is None:
        return "  --  "
    day = ""
    if h >= 24.0:
        day, h = "+1", h - 24.0
    elif h < 0:
        day, h = "-1", h + 24.0
    m = int(round((h % 1) * 60))
    if m == 60:
        h, m = h + 1, 0
    return f"{int(h) % 24:02d}:{m:02d}{day}"


worst = 0.0
failures = 0
if ref_adhan:
    print("== oracle comparison (UTC decimal times, western longitudes) ==")
    for name, lat, lng, refparams, ourparams, asr_shadow, date in ORACLE_CASES:
        ref = ref_adhan(date, (lat, lng), refparams, timezone_offset=0)
        ours = calc.compute_times(calc.Location(lat, lng, "UTC"), date, ourparams, asr_shadow=asr_shadow)
        print(f"-- {name} {date}")
        for key, refkey in (("fajr", "fajr"), ("sunrise", "shuruq"), ("dhuhr", "zuhr"),
                            ("asr", "asr"), ("maghrib", "maghrib"), ("isha", "isha")):
            o = getattr(ours, key)
            r = ref[refkey]
            rh = r.hour + r.minute / 60.0 + r.second / 3600.0
            diff = abs(o - rh) * 60 if o is not None else float("nan")
            worst = max(worst, diff)
            flag = "" if diff <= 2.0 else "  <-- CHECK"
            print(f"   {key:8s} muezzin={fmt(o)}  oracle={fmt(rh)}  d={diff:4.1f}min{flag}")

print("\n== invariant checks (all hemispheres) ==")
for name, lat, lng, params, date in INVARIANT_CASES:
    t = calc.compute_times(calc.Location(lat, lng, "UTC"), date, params)
    ok = True
    msgs = []
    if t.sunrise is not None and t.sunset is not None:
        # sunrise and sunset must be symmetric about dhuhr
        asym = abs(((t.sunrise + t.sunset) / 2.0) - t.dhuhr) * 60
        if asym > 0.5:
            ok = False
        msgs.append(f"sun symmetry {asym:.2f}min")
        # day length sanity
        dl = (t.sunset - t.sunrise) % 24.0
        if not (0.0 <= dl <= 24.0):
            ok = False
        msgs.append(f"daylen {dl:.2f}h")
    if t.fajr is None:
        msgs.append("fajr missing->HL rule should have fired?" if params.high_latitude_rule != "none" else "fajr absent (rule=none)")
    if params.midnight_from_fajr and t.true_night is not None and t.maghrib is not None:
        half = ((t.true_night - t.maghrib) % 24.0)
        span = ((t.fajr - t.maghrib) % 24.0) if t.fajr is not None else None
        if span is not None and abs(half * 2 - span) > 0.02:
            ok = False
            msgs.append("true-night midpoint WRONG")
        else:
            msgs.append(f"true-night {half:.2f}h after maghrib (half of {span:.2f}h sunset->fajr)")
    print(f"-- {name} {date}: {'OK' if ok else 'FAIL'} | {'; '.join(msgs)}")
    print(f"   fajr={fmt(t.fajr)} sunrise={fmt(t.sunrise)} dhuhr={fmt(t.dhuhr)} asr={fmt(t.asr)} "
          f"maghrib={fmt(t.maghrib)} isha={fmt(t.isha)} midnight={fmt(t.midnight)} trueNight={fmt(t.true_night)}")
    if not ok:
        failures += 1

def hours_of(hhmm: str) -> float:
    h, m = hhmm.split(":")
    return int(h) + int(m) / 60.0


# Third tier: published timetables, captured 2026-11-10 from api.aladhan.com
# (v1/timings, which implements the adhan.js algorithm family) plus the
# method parameters each request reports. Times are local civil time.
PUBLISHED_CASES = [
    {
        "name": "NYC, ISNA (aladhan method 2)",
        "lat": 40.7128, "lng": -74.0060, "tz": "America/New_York",
        "date": dt.date(2026, 11, 10), "params": calc.PRESETS["isna"], "shadow": 1.0,
        "expect": {"fajr": "05:19", "sunrise": "06:37", "dhuhr": "11:40",
                   "asr": "14:21", "maghrib": "16:42", "isha": "18:00"},
    },
    {
        "name": "London, Egyptian General Authority (aladhan method 5)",
        "lat": 51.5074, "lng": -0.1278, "tz": "Europe/London",
        "date": dt.date(2026, 11, 10), "params": calc.PRESETS["egyptian"], "shadow": 1.0,
        "expect": {"fajr": "05:04", "sunrise": "07:10", "dhuhr": "11:44",
                   "asr": "13:56", "maghrib": "16:18", "isha": "18:11"},
    },
    {
        # The case a closed enum of named methods could not express at all:
        # the Institute of Geophysics, Tehran (Fajr 17.7 / Isha 14, Jafari midnight).
        "name": "Qom, Institute of Geophysics Tehran (aladhan method 7)",
        "lat": 34.6416, "lng": 50.8799, "tz": "Asia/Tehran",
        "date": dt.date(2026, 11, 10), "params": calc.PRESETS["tehran"], "shadow": 1.0,
        # maghrib here is sunset; that source's 17:24 maghrib applies a 4.5 deg
        # angle, which muezzin expresses as maghrib_angle_offset instead.
        "expect": {"fajr": "05:10", "sunrise": "06:35", "dhuhr": "11:50",
                   "asr": "14:45", "maghrib": "17:05", "isha": "18:12"},
    },
]

print("\n== published timetables (api.aladhan.com, captured 2026-11-10) ==")
pub_worst = 0.0
for case in PUBLISHED_CASES:
    t = calc.compute_times(calc.Location(case["lat"], case["lng"], case["tz"]),
                           case["date"], case["params"], asr_shadow=case["shadow"])
    print(f"-- {case['name']} {case['date']}")
    for key, want in case["expect"].items():
        got = getattr(t, key)
        diff = abs(got - hours_of(want)) * 60
        pub_worst = max(pub_worst, diff)
        flag = "" if diff <= 2.0 else "  <-- CHECK"
        print(f"   {key:8s} muezzin={fmt(got)}  published={want}  d={diff:4.1f}min{flag}")

print(f"published worst deviation: {pub_worst:.1f} min")

print(f"\noracle worst deviation: {worst:.1f} min | invariant failures: {failures}")
