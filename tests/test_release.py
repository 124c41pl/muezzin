"""Which build this actually is.

The version number says which release. It cannot say which *try* at that release a
machine is running, and for a Windows install - set up once, on a machine nobody can walk
over to with a laptop and ask - that is the first question a bug report has to answer. So
a candidate build carries its number inside the exe and reads it back out again onto the
page's bottom line and into its own log."""
from __future__ import annotations

import pathlib

import muezzin
from muezzin import RELEASE_FILE, release_version

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
