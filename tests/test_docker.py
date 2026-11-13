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
