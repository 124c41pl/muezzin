"""One HTTP server class for the three places muezzin listens: the web panel,
the media server the speakers are told to fetch, and a box's own request handler.

The standard library's HTTP server does something muezzin cannot afford. When it
binds, it asks the operating system for this machine's fully-qualified name and
keeps the answer in `server_name`:

    class HTTPServer(socketserver.TCPServer):
        def server_bind(self):
            socketserver.TCPServer.server_bind(self)
            host, port = self.socket.getsockname()[:2]
            self.server_name = socket.getfqdn(host)      # <- this one

For a machine listening on `0.0.0.0` that question has no good answer, and the
operating system does not say "no" quickly - it waits for name resolution to give
up. Measured on 2026-11-13 on an arm64 macOS runner whose hostname ends in
`.local`: constructing a server there took 35.0 seconds, while the same code on
Linux and on Windows took no measurable time, and `socket.getfqdn()` with no
argument on that machine took 70.0 seconds. A Raspberry Pi on a home network
with a name nothing resolves is the same situation, only permanent.

Nothing muezzin sends depends on that name - it appears in no status line, header
or body - so bind here and fill in the two attributes the standard library would
have set from what the socket already knows.
"""
from __future__ import annotations

import socketserver
from http.server import ThreadingHTTPServer


class LANServer(ThreadingHTTPServer):
    """A threaded HTTP server that never asks DNS who this machine is.

    `server_name` is the address this server is actually listening on, which is
    the honest answer and costs nothing. `server_port` is the port, which matters
    because a server started on port 0 is told its real port by the operating
    system.
    """

    def server_bind(self) -> None:
        # TCPServer, not HTTPServer: this is the part that binds and re-reads the
        # socket address, and it is HTTPServer's extra line after it that asks DNS.
        socketserver.TCPServer.server_bind(self)
        self.server_name = self.server_address[0]
        self.server_port = self.server_address[1]
