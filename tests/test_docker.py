"""Container files are documentation that runs.

These checks are cheap, and they live next to the code because the two mistakes
they prevent are the boring kind that only show up after a release: a Dockerfile
that COPYs a path the repo no longer has, and a compose file that quietly drops
the mount or the network mode the speaker discovery depends on. Nothing here
needs a Docker daemon.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _copy_lines(text: str) -> list[list[str]]:
    """The COPY instructions in a Dockerfile, as argument lists."""
    return [line.strip().split()[1:] for line in text.splitlines()
            if line.strip().upper().startswith("COPY ")]


def test_the_image_copies_only_paths_this_repo_has():
    """A COPY that names a deleted directory is a build that fails on someone
    else's machine an hour after the commit that seemed fine here."""
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    copies = _copy_lines(text)
    assert copies, "the Dockerfile copies nothing, so it builds an image with no muezzin in it"
    for parts in copies:
        for src in parts[:-1] if len(parts) > 1 else parts:
            if src.startswith("--"):               # a COPY --from=stage flag
                continue
            assert (ROOT / src).exists(), f"COPY {parts}: this repo has no {src}"


def test_the_container_does_not_run_as_root():
    """It listens on the LAN and reads whatever the profile points it at; staying
    an ordinary user is cheap insurance when something in that chain is wrong."""
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "useradd" in text and "USER azan" in text


def test_the_image_ships_no_code_that_is_not_mine():
    """This directory also holds private notes, personal configs and working
    material gathered while looking at another program's installer. None of it is
    muezzin's, and none of it may leave this repo inside an image."""
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for blocked in (".git/", ".venv/", "research/", "notes/", "tests/", "FINDINGS.md"):
        assert blocked in ignore, f".dockerignore does not exclude {blocked}"


def test_the_compose_file_parses_and_keeps_what_discovery_needs():
    doc = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = doc["services"]
    main = services["muezzin"]
    assert main["build"] == "."
    assert main["network_mode"] == "host", "speaker discovery needs the LAN, not a bridge"
    mounts = " ".join(main["volumes"])
    assert "/app/config" in mounts and "/app/media" in mounts, "your profile and audio must be mounted"
    assert "ports" not in main, "with host networking a port mapping is silently ignored"
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "Docker Desktop" in text, "the one thing Windows users hit must be said out loud"


def _instruction(text: str, word: str) -> str:
    """The Dockerfile's single ENTRYPOINT or CMD line, or a loud failure."""
    lines = [line.strip() for line in text.splitlines() if line.strip().upper().startswith(word)]
    assert len(lines) == 1, f"the Dockerfile should hold exactly one {word}, found {len(lines)}"
    return lines[0]


def test_the_container_lets_the_page_finish_the_setup():
    """Everything that sets a household up — the map, the postal-code box, the
    speaker scan, the upload — is on the page, and the image is what a person
    pulls before they own a profile. Defaulting that page to read-only shipped a
    container that could only ever display somebody else's timetable, with the fix
    hidden in a flag nobody read; the comment beside it even named the flag that
    does the opposite. So writing is the default, and what has to stay in this file
    is the reason: the page has no login, and `--read-only` is the variant for a
    network you would not hand your schedule to."""
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    cmd = _instruction(docker, "CMD")
    assert "daemon" in cmd and "--web" in cmd, "the default has to run the daemon and the page"
    assert "muezzin.yaml" in cmd, "and read the profile from the folder compose mounts"
    assert "--read-only" not in cmd, "the page must be able to save the profile being set up"
    assert "--read-only" in docker, "the locked variant belongs in the comment next to it"
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "--read-only" in compose, "a hardened box needs the shape ready to uncomment"
    assert "login" in docker + compose, "the cost of a writable page is stated, not implied"


def test_the_first_run_of_a_container_has_a_profile_to_read():
    """A daemon pointed at an empty volume answers with a usage error and exits 2,
    which on `docker compose up` reads as a broken image rather than as a step
    nobody told you about. So the image writes the starter itself, once."""
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    script = (ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert _instruction(docker, "ENTRYPOINT") == 'ENTRYPOINT ["/app/docker-entrypoint.sh"]'
    assert "docker-entrypoint.sh /app/" in docker, "the script has to be in the image"
    assert "chmod 755" in docker, "a script nobody may execute is a container that never starts"
    assert "-c \"$CONFIG\"" in script and "--media-dir /app/media" in script, \
        "the starter must name the mounted audio folder, not a path inside the config volume"
    assert "[ ! -f" in script, "a profile that already exists is never written over"
    # exec is not style: without it this script is PID 1, `docker stop` waits out
    # its timeout instead of stopping, and an adhan that was mid-play gets killed.
    assert "exec muezzin" in script, "the daemon must be the process Docker sends signals to"


def test_the_script_the_container_runs_survives_a_windows_clone():
    """The entrypoint is the one file here that an operating system executes rather
    than reads, and the kernel takes the shebang as the name of an interpreter. Give
    that file Windows endings and the name it asks for is `/bin/sh` with a carriage
    return on the end, which is not a thing that exists: the container answers
    "no such file or directory" and dies before muezzin starts, in front of somebody
    who followed our own build-the-image instructions and changed nothing wrong.
    `core.autocrlf=true`, the usual setting on Windows, is what does it to a clone."""
    script = (ROOT / "docker-entrypoint.sh").read_bytes()
    assert b"\r" not in script, "a carriage return in a shell script names an interpreter that is not there"
    assert script.startswith(b"#!/bin/sh\n"), "the shebang has to end where the line does"
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh" in attributes and "eol=lf" in attributes, \
        "nothing else in this suite can notice a clone that cannot boot"


def test_the_published_tag_is_the_one_the_readme_promises():
    """The registry tag must be the version, not the git tag.

    Publishing the git ref name puts a `v`-prefixed tag on ghcr while every
    instruction in the README says to pull the bare version, and the build stays
    green the whole time: the failure belongs to whoever follows the
    instructions a week later, with no way to tell that the recipe and the
    pantry disagree. Nothing else in this suite reads the workflow, so this is
    the only check that can notice.
    """
    from muezzin import __version__

    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "image.yml").read_text(encoding="utf-8"))
    steps = doc["jobs"]["build"]["steps"]
    pushed = "\n".join(step["with"]["tags"] for step in steps
                       if step.get("with", {}).get("tags"))
    assert "env.IMAGE_TAG" in pushed, "the published tag must be the version, not the git tag"
    assert "ref_name" not in pushed, "the workflow publishes a v-prefixed tag while the docs promise the bare version"
    guard = "\n".join(step.get("run", "") for step in steps)
    assert "IMAGE_TAG" in guard and "GITHUB_ENV" in guard, "IMAGE_TAG is never set, so the tag is empty"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"docker pull ghcr.io/124c41pl/muezzin:{__version__}" in readme, \
        "the README must tell people to pull the version this package actually is"
    assert "ghcr.io/124c41pl/muezzin:v" not in readme, "no v-prefixed tag is ever published"


def test_the_image_can_also_be_published_by_hand():
    """A tag push is not the only day this build matters.

    A base image with a hole in it has to be republished under the version
    people already pull, and a repository recreated under the same name can take
    its tags as a push that fires nothing at all: the registry still answers, the
    releases still read perfectly, and nowhere does anything say the pipeline
    behind them has never run once. A hand-started run fixes either case without
    inventing a version number to force one through.

    Both ways this can be wrong are invisible next to a green check mark. A
    hand-started run that builds the branch it was started from publishes a
    version number built from other code, and a hand-started run of an older tag
    also republishes `latest`, which is what everybody who pulls without naming a
    version ends up with.
    """
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "image.yml").read_text(encoding="utf-8"))
    triggers = doc.get("on") or doc.get(True)  # `on` is a boolean key under YAML 1.1
    assert "workflow_dispatch" in triggers, "the image cannot be rebuilt without inventing a release"
    assert "tag" in triggers["workflow_dispatch"]["inputs"], \
        "a hand-started run with no tag builds the branch it was started from and publishes a version number"

    steps = doc["jobs"]["build"]["steps"]
    checkout = next(step for step in steps if str(step.get("uses", "")).startswith("actions/checkout"))
    assert "inputs.tag" in checkout.get("with", {}).get("ref", ""), \
        "a hand-started run checks out the branch it was dispatched from, not the tag it names"

    guards = [step for step in steps if "latest" in step.get("run", "")]
    assert guards, "nothing stops a hand-built older version taking over latest"
    assert any("inputs.tag" in str(step.get("if", "")) for step in guards), \
        "the latest guard runs on tag pushes too, where there is no input to compare against"


def test_a_mistyped_tag_is_refused_before_anything_is_fetched():
    """A typo in the tag box should read like a typo, not like a git crash.

    The first hand-started run of this workflow was asked for `v.0.1.4`, one dot
    too many. Nothing in the workflow noticed, the mistyped name was handed to
    the checkout action as a ref, and what came back was three retries ending in
    "The process '/usr/bin/git' failed with exit code 1": a log full of
    machinery that never once mentions the tag, the box it came from, or what
    either of them should have held. The whole run was spent finding out that a
    string was wrong.
    """
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "image.yml").read_text(encoding="utf-8"))
    steps = doc["jobs"]["build"]["steps"]
    shape = [i for i, step in enumerate(steps) if "is not a tag" in step.get("run", "")]
    assert shape, "a mistyped tag becomes a git crash instead of one sentence naming what was typed"

    checkout_at = next(i for i, step in enumerate(steps) if str(step.get("uses", "")).startswith("actions/checkout"))
    assert shape[0] < checkout_at, "the tag is examined after it has already been handed to git"

    guard = steps[shape[0]]
    assert "workflow_dispatch" in str(guard.get("if", "")), \
        "a tag push has no tag box, so this guard would fail every release build"

    checkout = steps[checkout_at]
    assert "trim(" in checkout.get("with", {}).get("ref", ""), \
        "a tag copied out of a release page carries a space, and git calls that a ref that does not exist"
