"""Scratch, read-only: enumerate every mDNS service type visible on this LAN, then
dump the instances for the interesting ones. Used to learn what the Smart Azan Pi
box advertises so muezzin can speak to it. Makes no writes to any device."""
import re
import socket
import sys
import time
from collections import Counter

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

SEEN_TYPES: Counter = Counter()
SEEN_INSTANCES: dict[str, list] = {}


class TypeSniffer(ServiceListener):
    """Browsing _services._dns-sd._udp.local. yields the list of advertised types."""

    def add_service(self, zc, type_, name):
        SEEN_TYPES[name] += 1

    def remove_service(self, zc, type_, name):
        pass

    def update_service(self, zc, type_, name):
        pass


class InstanceSniffer(ServiceListener):
    def __init__(self, stype):
        self.stype = stype

    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info is None:
            SEEN_INSTANCES.setdefault(self.stype, []).append((name, None, None, None))
            return
        props = {}
        for k, v in (info.properties or {}).items():
            key = k.decode(errors="replace") if isinstance(k, bytes) else k
            val = v.decode(errors="replace") if isinstance(v, bytes) else v
            props[key] = val
        SEEN_INSTANCES.setdefault(self.stype, []).append(
            (name, info.server, info.port, (info.parsed_addresses(), props))
        )

    def remove_service(self, zc, type_, name):
        pass

    def update_service(self, zc, type_, name):
        pass


def main() -> int:
    hold = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
    zc = Zeroconf()
    try:
        b1 = ServiceBrowser(zc, "_services._dns-sd._udp.local.", TypeSniffer())
        time.sleep(hold)
        b1.cancel()
        print(f"--- service types seen ({hold}s) ---")
        for t, n in SEEN_TYPES.most_common():
            print(f"{n:3d}  {t}")

        skip = {"_googlecast._tcp.local.", "_services._dns-sd._udp.local."}
        types = [t for t in SEEN_TYPES if t not in skip]
        browsers = [ServiceBrowser(zc, t, InstanceSniffer(t)) for t in types]
        time.sleep(hold)
        for b in browsers:
            b.cancel()
        print(f"\n--- instances ({hold}s) ---")
        for t, rows in SEEN_INSTANCES.items():
            print(t)
            for name, server, port, extra in rows:
                print(f"   {name}  server={server} port={port}")
                if extra:
                    print(f"      addrs={extra[0]} props={extra[1]}")
    finally:
        zc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
