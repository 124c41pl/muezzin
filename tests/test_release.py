"""Which build this actually is.

The version number says which release. It cannot say which *try* at that release a
machine is running, and for a Windows install - set up once, on a machine nobody can walk
over to with a laptop and ask - that is the first question a bug report has to answer. So
a candidate build carries its number inside the exe and reads it back out again onto the
page's bottom line and into its own log.

The same reasoning covers the other thing a build puts on itself - the mark it wears. An
icon is a binary nobody looks at while building, and a broken one does not fail a build: it
arrives as a blank tile on somebody's Start Menu, on a machine they are not standing next
to. So the file is parsed here, and the places that ask for it are checked against it."""
from __future__ import annotations

import base64
import pathlib
import re
import struct

import muezzin
from muezzin import RELEASE_FILE, favicon, release_version
from muezzin.page import PAGE

HERE = pathlib.Path(__file__).resolve().parents[1]
PACKAGING = HERE / "packaging" / "windows-service"


def _bundle(tmp_path, contents: str) -> str:
    """A unpacked-one-file-exe folder holding a stamp that says `contents`."""
    bundle = tmp_path / "unpacked"
    bundle.mkdir()
    (bundle / RELEASE_FILE).write_text(contents, encoding="utf-8")
    return str(bundle)


def test_a_build_anybody_makes_themself_says_its_plain_version(monkeypatch):
    """No stamp: a checkout, a `pip install`, the container image.

    Only the Windows build script writes one, so everywhere else the answer is the version
    number the package carries. A suffix invented out of nothing would be a worse kind of
    wrong than a number that simply leaves the try unstated."""
    monkeypatch.delattr("sys._MEIPASS", raising=False)
    assert release_version() == muezzin.__version__


def test_a_candidate_build_says_which_candidate_it_is(monkeypatch, tmp_path):
    """`0.1.6-r7` rather than `0.1.6`: the whole point of the exercise.

    Written here with a byte-order mark and a newline, because the thing that writes the
    real one is a PowerShell script and a page reading an invisible character in front of
    its version number is the kind of bug nobody notices until they are reading a log."""
    monkeypatch.setattr("sys._MEIPASS", _bundle(tmp_path, "\ufeff0.1.6-r7\n"), raising=False)
    assert release_version() == "0.1.6-r7"


def test_a_frozen_build_with_no_stamp_to_read_does_not_invent_one(monkeypatch, tmp_path):
    """The stamp lives inside the exe, so an exe whose stamp went missing on the way to a
    machine is a real possibility, and this is the answer it deserves: the version, and no
    number made up for it."""
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path / "nothing-unpacked-here"), raising=False)
    assert release_version() == muezzin.__version__


def test_an_empty_stamp_costs_the_suffix_and_nothing_else(monkeypatch, tmp_path):
    """A stamp file that a build script created and then wrote nothing into. The version
    stays; `muezzin ` on the bottom line is not an improvement on `muezzin 0.1.6`."""
    monkeypatch.setattr("sys._MEIPASS", _bundle(tmp_path, "   \n"), raising=False)
    assert release_version() == muezzin.__version__


def test_the_three_places_that_name_the_stamp_name_the_same_one():
    """A PowerShell script writes the stamp, a PyInstaller spec swallows it into the exe,
    and Python reads it back out under one filename - three places, no shared constant,
    and no build of this kind in the suite to catch it failing. So the one name is pinned
    here, along with the folder entry that keeps a candidate's number out of every build
    made after it: a committed stamp is a stamp inside everything."""
    spec = (PACKAGING / "muezzin.spec").read_text(encoding="utf-8")
    build = (PACKAGING / "build.ps1").read_text(encoding="utf-8")
    ignore = (HERE / ".gitignore").read_text(encoding="utf-8")
    assert RELEASE_FILE in spec, "the spec does not bundle the stamp the exe looks for"
    assert "os.path.exists(_stamp)" in spec, \
        "the spec bundles a stamp even for a build that was never given one"
    assert RELEASE_FILE in build, "build.ps1 does not write the stamp the spec looks for"
    assert f"packaging/windows-service/{RELEASE_FILE}" in ignore, \
        "a stamp left in a commit would sit inside every build made afterwards"


def test_the_setup_file_and_the_build_agree_on_which_try_they_are():
    """The name on disk, the version Programs and Features lists, and the number the page
    prints all come out of one string in the build script. They used to be written down by
    hand afterwards, which is how a machine ends up running a build whose own screen
    contradicts the file that installed it."""
    build = (PACKAGING / "build.ps1").read_text(encoding="utf-8")
    assert '$release = if ($RC) { "$version-r$RC" } else { $version }' in build, \
        "the candidate number is not derived from the version it belongs to"
    assert "/DVersion=$release" in build, \
        "the installer is told a different version than the build stamped itself with"
    assert "dist\\muezzin-$release-setup.exe" in build, \
        "the setup file build.ps1 points at is not the one it names the build by"


# What Windows asks for, at the sizes it asks for it: 16 in a list view, 32 in a taskbar,
# 48 on a desktop, 256 where a desktop gets scaled up. The drawing script calls this list
# SIZES; it is spelled out again here on purpose, the way the stamp's filename is, because
# a list quietly changed in one place is a build that stops answering a size it used to.
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def test_the_icon_file_is_an_icon_at_every_size_it_claims():
    """Parse the file the exe and the setup program take their picture from.

    Two mistakes happened while this was drawn, and neither one is visible in the file's
    own directory, which is what makes them worth pinning. An entry with no
    BITMAPINFOHEADER ahead of its pixels leaves the directory perfect - every offset
    tiles the file exactly, the count is right - and Windows still shows nothing, because
    it never finds a bitmap to read. And an entry that gives the height of the colour
    bitmap rather than the height of the bitmap *plus* its AND mask is a file that some
    readers accept and others refuse: System.Drawing throws on it, and the message it
    throws is "The operation completed successfully"."""
    raw = (PACKAGING / "muezzin.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", raw[:6])
    assert (reserved, kind) == (0, 1), "the file does not say it is an icon"
    assert count == len(ICO_SIZES), f"it carries {count} pictures, not the {len(ICO_SIZES)} we ask for"

    where = 6 + 16 * count
    for n in range(count):
        entry = raw[6 + 16 * n: 22 + 16 * n]
        width = entry[0] or 256          # a 256px entry writes its width as a zero byte
        assert (entry[1] or 256) == width, f"the {width}px picture is not square"
        entry_len, entry_at = struct.unpack("<II", entry[8:16])
        assert entry_at == where, f"the {width}px entry is not where the directory says it is"

        bitmap = raw[entry_at:entry_at + entry_len]
        header = struct.unpack("<IiiHHIIiiII", bitmap[:40])
        assert header[0] == 40, f"the {width}px entry has no BITMAPINFOHEADER in front of its pixels"
        assert (header[1], header[2]) == (width, width * 2), \
            f"the {width}px entry counts its height without the AND mask"
        assert (header[3], header[4], header[5]) == (1, 32, 0), \
            f"the {width}px entry is not uncompressed 32-bit colour, which is what every reader takes"
        # A 32-bit colour row is four bytes a pixel; the mask underneath it is one bit a
        # pixel, padded out to a whole number of dwords, which is the only reason the two
        # halves of one entry are not the same length.
        pixels = 4 * width * width
        stride = ((width + 31) // 32) * 4
        assert entry_len == 40 + pixels + stride * width, \
            f"the {width}px entry is {entry_len} bytes, which is not its size"
        assert bitmap[40 + pixels:] == b"\x00" * (stride * width), \
            f"the {width}px entry has an AND mask that is not empty: half the mark goes missing"
        where += entry_len

    assert where == len(raw), "bytes after the last picture: the file was written twice"


def test_the_mark_the_page_wears_is_the_mark_the_exe_wears():
    """Four surfaces show this program a person can see: the exe in a folder, the setup
    program beside it, the Start Menu entry, and the browser tab of the panel it runs.

    Three of those read the .ico out of the packaging folder. The fourth cannot - a page
    has to be handed its icon by the program that serves it - so the drawing script writes
    a second file for it, out of the same render, and this is the check that the handover
    happened: the page carries a data: URL, it decodes back to a PNG, and that PNG is the
    size the module says it is rather than a truncated paste of it."""
    found = re.search(
        r'<link rel="icon" type="image/png" href="data:image/png;base64,([^"]+)"', PAGE)
    assert found, "the page names no icon, so the tab wears whatever the browser draws"
    png = base64.b64decode(found.group(1))
    assert png == favicon.FAVICON_PNG, "the page's icon is not the bytes the module carries"
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "what the page carries is not a PNG"
    assert struct.unpack(">II", png[16:24]) == (favicon.FAVICON_SIZE,) * 2, \
        "the PNG in the page is not the square it claims to be"


def test_the_three_places_that_want_a_picture_want_the_same_one():
    """The spec hands the .ico to PyInstaller, the setup script names it for Inno, and the
    build script is what runs both. Nothing in a build fails if one of the three stops
    naming it: the exe comes out wearing Python's icon and the setup program wears Inno's
    default, which is exactly how this looked until somebody pointed at it."""
    spec = (PACKAGING / "muezzin.spec").read_text(encoding="utf-8")
    setup = (PACKAGING / "muezzin-setup.iss").read_text(encoding="utf-8-sig")   # Inno wants a BOM

    assert "muezzin.ico" in spec and "icon=_icon" in spec, \
        "the exe does not name the icon, so it wears the one PyInstaller drew"
    assert "os.path.dirname(os.path.abspath(SPEC))" in spec, \
        "the icon path is relative to wherever the build happened to be standing"
    assert "SetupIconFile=muezzin.ico" in setup, \
        "the setup program does not name the icon, so it wears Inno's default"
