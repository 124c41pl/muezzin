"""Scratch: pull printable ASCII and UTF-16 strings out of the unpacked Smart Azan
binaries and grep them for mDNS service types, HTTP routes and Pi protocol hints.
Read-only analysis of files we already unpacked; no code is copied."""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "extracted2/{app}")
patterns = sys.argv[2:] or ["_tcp", "_udp", "local.", "/play", "http://", "Raspi", "9874", "5500"]
ascii_re = re.compile(rb"[\x20-\x7e]{4,}")
utf16_re = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")

for f in sorted(root.rglob("*")):
    if not f.is_file() or f.suffix.lower() not in (".exe", ".dll", ".config", ".json", ".ini", ".xml"):
        continue
    data = f.read_bytes()
    hits = set()
    for m in ascii_re.finditer(data):
        s = m.group().decode(errors="replace")
        if any(p in s for p in patterns):
            hits.add(s)
    for m in utf16_re.finditer(data):
        s = m.group().decode("utf-16-le", errors="replace")
        if any(p in s for p in patterns):
            hits.add(s)
    if hits:
        print(f"== {f}")
        for h in sorted(hits)[:80]:
            print("   " + h[:220])
