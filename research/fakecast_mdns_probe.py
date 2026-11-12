"""Scratch: advertise a fake _googlecast._tcp service so `muezzin devices` can be
exercised on a machine with no real Nest speaker attached. Not part of the app."""
import socket, sys, time
from zeroconf import ServiceInfo, Zeroconf

ip = socket.inet_aton("127.0.0.1")
info = ServiceInfo(
    "_googlecast._tcp.local.",
    "Fake Kitchen._googlecast._tcp.local.",
    addresses=[ip],
    port=8009,
    properties={"fn": "Fake Kitchen", "md": "Chromecast (test)", "id": "FAKE1234", "ca": "2048"},
    server="fake-kitchen.local.",
)
z = Zeroconf()
z.register_service(info)
print("registered fake cast service; holding for 20s", flush=True)
time.sleep(20)
z.unregister_service(info)
z.close()
