# Third-party work, and what its licences ask for

muezzin is MIT licensed (see `LICENSE`). That is the licence of *this* code. These
are the programs it stands on, what they cost you, and the parts that are worth
knowing before you redistribute a build.

## At runtime

| package | version tested | licence | what it does here |
| --- | --- | --- | --- |
| [pychromecast](https://github.com/home-assistant/pychromecast) | 14.1.1 | MIT | talks to Cast speakers: discovery, the Dial channel, `play_media` |
| [python-zeroconf](https://github.com/python-zeroconf/python-zeroconf) | 0.154.0 | **LGPL 2.1 or later** | mDNS: finding speakers and other muezzin boxes on the LAN |
| [PyYAML](https://pyyaml.org) | 6.0.3 | MIT | reads and validates the profile; the page never writes YAML through it |
| [tzdata](https://github.com/python/tzdata) | 2026.6 | Apache-2.0 | the time zones `ZoneInfo` needs on Windows, which has none of its own |

MIT is short: keep the copyright lines, ship the notices, and you are done.
Apache-2.0 adds a patent grant and a "state changes" note.

### The one that needs attention: zeroconf

LGPL is not viral for the program that merely *calls* it, and it is not copyleft
for a profile in YAML. What it does ask, if you redistribute muezzin together with
zeroconf — a wheel bundle, a Docker image pushed to a registry, a Pi image:

* the zeroconf licence text travels with it (`COPYING` is inside the wheel; it
  stays there in any image you build);
* the user can swap zeroconf out for another implementation of the same interface,
  rather than being handed a statically glued binary. A `pip install` of muezzin,
  or an image with an ordinary Python environment, satisfies that by itself;
* you do not have to open your own code. Nothing in muezzin is derived from
  zeroconf's source: discovery is written against its public API, and the only
  mDNS packets in this repository are the ones that library sends.

The practical upshot: `pip install muezzin` and `docker run ghcr.io/…/muezzin` are
both fine, and the LAN discovery feature can be compiled out of a fork by dropping
the `discover_cast` / `discover_boxes` helpers, which is what the licence's
"work on the interface, not the library" distinction means in practice.

## Only in the tests

| package | version | licence | how it is used |
| --- | --- | --- | --- |
| [adhan](https://github.com/djwonka/adhan.py) | 0.1.1 | **LGPL 3.0** | an oracle. `tests/crosscheck.py` computes the same times twice and compares the answers |

That is a test dependency under the `dev` extra, never a runtime requirement, and
never a copy: **not one line of adhan or of Batoulapps.Adhan is in this
repository.** The comparison exists precisely because the two implementations
should agree without sharing code, and the licence permits using it that way. If
you strip `dev` out of a build — which is what a release does — LGPL 3.0 leaves
the picture entirely.

## Also true, and worth saying out loud

* `SmartAzanSetup.exe`, the unpacked Smart Azan binaries and the installer script
  extracted from them are **not** in this repository and stay out of it: they are
  someone else's proprietary work. They sit in a working copy while the
  teardown is being read, and `.gitignore` names each one.
* `FINDINGS.md` is a written description of what that teardown showed. Describing
  a program you are allowed to run is not the same as shipping it.
* Nothing is downloaded from the internet at runtime. The web page is one file
  served by the daemon, with no CDN, no web fonts and no analytics; the only URLs
  the program ever fetches are the ones in your own profile, and only if you put
  them there.
* The Arabic on the page is a handful of prayer, month and weekday names, and the
  geometry is girih-style tiling drawn in CSS. There is no figurative imagery and
  no religious artwork, so nothing here is a depiction anyone has to be careful
  about.
