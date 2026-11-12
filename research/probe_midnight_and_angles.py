import datetime as dt
import sys

sys.path.insert(0, "src")
from muezzin import calc

base = calc.PRESETS["tehran"]
qom = calc.Location(34.6416, 50.8799, "Asia/Tehran")
# aladhan's Tehran method puts maghrib at a 4.5 deg depression, not at sunset:
p = calc.MethodParams(base.fajr_angle, base.isha_angle,
                      maghrib_angle_offset=4.5 - 0.833,
                      midnight_from_fajr=base.midnight_from_fajr,
                      high_latitude_rule=base.high_latitude_rule,
                      label="tehran + 4.5deg maghrib")
t = calc.compute_times(qom, dt.date(2026, 11, 10), p)


def hhmm(x):
    h = int(x) % 24
    return f"{h:02d}:{round((x - int(x)) * 60):02d}" + ("+1" if x >= 24 else "")


print("sunset ", hhmm(t.sunset), " maghrib", hhmm(t.maghrib), " dhuhr", hhmm(t.dhuhr),
      " midnight", hhmm(t.midnight))
print("published Tehran: maghrib 17:24, fajr 05:10, isha 18:12")
# isha_interval preset check (Umm al-Qura = maghrib + 90 min)
makkah = calc.Location(21.4225, 39.8262, "Asia/Riyadh")
t2 = calc.compute_times(makkah, dt.date(2026, 11, 10), calc.PRESETS["umm_al_qura"])
print("Umm al-Qura maghrib", hhmm(t2.maghrib), "isha", hhmm(t2.isha),
      "diff", round((t2.isha - t2.maghrib) * 60, 1), "min")
# hanafi asr later than standard
nyc = calc.Location(40.7128, -74.006, "America/New_York")
a1 = calc.compute_times(nyc, dt.date(2026, 11, 10), calc.PRESETS["isna"], asr_shadow=1.0)
a2 = calc.compute_times(nyc, dt.date(2026, 11, 10), calc.PRESETS["isna"], asr_shadow=2.0)
print("asr standard", hhmm(a1.asr), "hanafi", hhmm(a2.asr), "delta", round((a2.asr - a1.asr) * 60), "min")
# jafari midnight vs sunset-to-sunrise midnight
for name in ("qom", "shia_ithna_ashari", "tehran"):
    pp = calc.PRESETS[name]
    tt = calc.compute_times(qom, dt.date(2026, 11, 10), pp)
    print(f"{name:18s} mid={hhmm(tt.midnight)} true_night={hhmm(tt.true_night)} "
          f"midnight_from_fajr={pp.midnight_from_fajr}")
