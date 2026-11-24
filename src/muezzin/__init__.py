"""muezzin: prayer times + flexible speaker output, driven by config files."""
import os
import sys

__version__ = "0.1.6"

# What a release build calls itself, when it is a candidate rather than the release.
#
# The number above says which release a household is on. It cannot say which *try* at
# that release a machine is running, and for a Windows build - installed once, on a
# machine nobody can walk over to with a laptop - that is the first question a bug
# report has to answer. So the build script drops a one-line stamp file next to its own
# spec, PyInstaller puts that file inside the exe, and the exe reads it back out again
# to say, on the page's bottom line and in its own log, something like `0.1.6-r7`.
#
# Nothing else has one. A checkout, a `pip install`, and the container image answer with
# the plain version, which is the honest answer there: there is no candidate number for
# a build that was never a candidate.
RELEASE_FILE = "MUEZZIN-RELEASE.txt"


def release_version() -> str:
    """What to call this build the way a person would: `0.1.6`, or `0.1.6-r7`."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle is None:
        return __version__
    # utf-8-sig because a stamp written by a Windows script may well carry a byte-order
    # mark, and a page showing `muezzin 0.1.6` with an invisible character in front of
    # the number is worse than one showing the plain version.
    try:
        with open(os.path.join(bundle, RELEASE_FILE), encoding="utf-8-sig") as fh:
            stamped = fh.read().strip()
    except OSError:
        # Frozen without a stamp, or unreadable: the version, and no invented suffix.
        return __version__
    return stamped or __version__
