"""Scratch, READ-ONLY prober for the Smart Azan Pi box found via mDNS.

GET requests and a raw banner read only. It deliberately never issues POST/PUT,
so it cannot make the box play anything or change its settings.
"""
import socket
import sys
import urllib.error
import urllib.request

HOST = sys.argv[1] if len(sys.argv) > 1 else ""
PORTS = [int(p) for p in (sys.argv[2:] or ["9874", "5500"])]
PATHS = ["/", "/index.html", "/api", "/api/status", "/api/players", "/api/media", "/status",
         "/config", "/health", "/swagger", "/swagger/v1/swagger.json", "/openapi.json",
         "/hub", "/signalr", "/media", "/players", "/device", "/info", "/version"]
# NOTE: no /play in this list on purpose. On a naive device a *GET* to a play
# endpoint would start audio in someone's house, which this probe must not do.


def http_get(port, path):
    url = f"http://{HOST}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            body = r.read(1500)
            return (r.status, r.headers.get("Content-Type", ""), dict(r.headers), body)
    except urllib.error.HTTPError as e:
        return (e.code, e.headers.get("Content-Type", ""), dict(e.headers), e.read(600))
    except Exception as exc:
        return (None, f"ERR {type(exc).__name__}: {exc}", {}, b"")


def banner(port):
    try:
        with socket.create_connection((HOST, port), timeout=3) as s:
            s.settimeout(2.5)
            data = s.recv(300)
            return data
    except Exception as exc:
        return f"ERR {type(exc).__name__}: {exc}".encode()


def main() -> int:
    if not HOST:
        print("name the host to probe (take it from an mDNS scan); this probe keeps no "
              "default on purpose so it never points at somebody's house by accident")
        return 2
    for port in PORTS:
        print(f"\n===== {HOST}:{port} raw banner =====")
        print(banner(port)[:300])
        for path in PATHS:
            status, ctype, headers, body = http_get(port, path)
            server = headers.get("Server", "")
            print(f"\n--- {port}{path} -> {status} [{ctype}] server={server!r}")
            if body:
                text = body.decode(errors="replace").replace("\r\n", "\n")
                print("   " + text[:700].replace("\n", "\n   "))
            if status in (None,) and port != PORTS[0]:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
