"""Hand one file to a client, in the piece of it that the client asked for.

Two servers in muezzin give out recordings: the panel, so a browser can play one
without anything reaching a speaker, and the media server, so a Cast speaker can
fetch one. Both used to answer every request with the whole file from byte zero,
which is enough until somebody drags a slider to the middle of a two-minute
recitation: a browser told there is nothing to seek in keeps the sound where it
is and gives no hint why. It is also how a speaker that lost its connection comes
back for the rest of a file instead of starting the recitation over, so this is
one implementation of that answer for both servers rather than two.

`Range` is a request for bytes, not for a position in time: the browser works out
which bytes its codec needs, and this side only answers for the file it has.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger("muezzin.fileserve")

# Copied in pieces so that a hundred-megabyte recitation does not have to be held
# in memory by the process that is merely carrying it.
CHUNK = 64 * 1024

# `bytes=9000-`, `bytes=0-8999`, `bytes=-4000`. A request naming two ranges at once
# wants a multipart body that neither of our clients can read, so it falls through
# to "the whole file" - an answer every client understands - instead of an error.
_ONE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class BadRange(Exception):
    """A Range header nothing can satisfy, because the file is smaller than the ask.

    The answer to this is 416, not the whole file: a client that asked for byte
    500000 of a 40000 byte recording has a wrong idea about the file, and quietly
    getting all of it is how a download loop starts.
    """


def plan(header, size: int):
    """The piece a `Range` header asks for, as (first, last) byte numbers inclusive.

    `None` means the whole file, which is also the answer to a header this server
    does not recognise: RFC 9110 lets a server ignore a Range it cannot parse, and
    a half-implemented speaker client that always sends one is better served by the
    recording than by a refusal it does not know how to handle.
    """
    text = str(header or "").strip()
    if not text:
        return None
    match = _ONE_RANGE.match(text)
    if not match:
        return None
    first, last = match.group(1), match.group(2)
    if not first and not last:
        return None                 # `bytes=-` names nothing at all; give the file
    if not first:
        # `bytes=-N` is the last N bytes: the ask of a client that has the beginning
        # and wants the end. More than the file holds is not an error, it is all of it.
        take = int(last)
        if take <= 0:
            raise BadRange(f"{text}: {take} bytes from the end of a {size} byte file asks "
                           "for nothing")
        return max(0, size - take), size - 1
    start = int(first)
    if start >= size:
        raise BadRange(f"{text}: this recording is {size} bytes, so byte {start} is not in it")
    end = size - 1
    if last:
        end = min(int(last), size - 1)
        if end < start:
            raise BadRange(f"{text}: it ends at byte {end}, before it starts at byte {start}")
    return start, end


def refuse(handler, size: int, message: str) -> None:
    """Answer a `Range` that nothing in this file can satisfy.

    The file's real length goes in the `Content-Range` header as `bytes */8`,
    because that number is the thing the client got wrong: a speaker asking for
    byte 500000 of a short clip is told how long the clip actually is, which is how
    it stops asking. The reason travels as a line of plain text for a person rather
    than as JSON, because the clients here are firmware and a browser's media
    element and neither of them reads a body - but the wording is what a log shows
    when somebody asks why the speaker was quiet.
    """
    body = str(message).encode("utf-8")
    handler.send_response(416)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Range", f"bytes */{size}")
    # Still true of this file: what the client asked for is the problem, not the
    # file's inability to be asked for in pieces.
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if str(getattr(handler, "command", "GET")).upper() != "HEAD":
        handler.wfile.write(body)


def deliver(handler, path: Path, content_type: str, span=None, cache: str | None = None) -> int:
    """Write the answer for one file, and return how many bytes of it went out.

    `cache` is the `Cache-Control` header to send, or nothing when it is None: the
    panel insists that everything it says is not to be kept, because the page edits
    the profile that lives behind it, while a recording on the media server is not
    a thing that changes between one speaker's request and the next.

    A `HEAD` request gets the headers, including the length, and no body - which is
    what a speaker checking whether a file is still there is asking for.
    """
    size = os.path.getsize(path)
    start, length = (span[0], span[1] - span[0] + 1) if span else (0, size)
    handler.send_response(206 if span else 200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(length))
    # The header that tells a browser this file can be asked for in pieces, which is
    # what makes a seek bar something a browser will offer at all.
    handler.send_header("Accept-Ranges", "bytes")
    if span:
        handler.send_header("Content-Range", f"bytes {start}-{start + length - 1}/{size}")
    if cache:
        handler.send_header("Cache-Control", cache)
    handler.end_headers()
    if str(getattr(handler, "command", "GET")).upper() == "HEAD":
        return 0
    sent = 0
    with open(path, "rb") as handle:
        handle.seek(start)
        while sent < length:
            chunk = handle.read(min(CHUNK, length - sent))
            if not chunk:
                # The file was shortened from under us between the length above and
                # this read. Send what there is and let the client notice the shortfall;
                # an exception here would break the connection without a word.
                log.warning("%s shrank: wanted %d bytes from %d and found %d",
                            path, length, start, sent)
                break
            handler.wfile.write(chunk)
            sent += len(chunk)
    return sent
