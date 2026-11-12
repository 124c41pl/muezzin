# muezzin as a container: one daemon, one YAML, one media folder.
#
# Read the compose file and the README before blaming the image for a speaker
# that cannot be found. Google Cast is found with mDNS, and mDNS does not cross
# a Docker bridge network; see "Running in a container" in the README.

FROM python:3.12-slim

# tzdata is already in the Debian base, so zoneinfo lookups work without it.
# No audio toolchain here on purpose: a container has no sound card, so
# kind: pc_speakers cannot work inside one and is not pretended to work.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# The manifests come first so a code change does not throw away the dependency
# layer: `pip install` then stays cached until pyproject.toml itself changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# Config and media are mounted, never baked in: whose times, whose voices, and
# whose speakers are your business, not the image's.
RUN useradd --create-home --uid 10001 azan \
 && mkdir -p /app/config /app/media /app/out \
 && chown -R azan:azan /app
USER azan

# 8020 is the panel, 8010 the media server the speakers pull audio from.
EXPOSE 8020 8010

ENTRYPOINT ["muezzin"]
# Read-only by default: a container on a home network usually runs unattended,
# and the panel has no password, so what arrives by default is a page that shows
# the times and the schedule. Put "--read-only" in front of the other arguments
# in a compose `command:` when you want the page to edit the profile; the config
# folder has to be writable for that to work.
CMD ["daemon", "-c", "/app/config/muezzin.yaml", "--web", "8020", "--read-only"]

