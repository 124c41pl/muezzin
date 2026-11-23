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
#
# The entrypoint script joins that step: with an empty /app/config it writes a
# starter profile, so a first `docker run` lands on a page you can finish setting
# up instead of a usage error, and then execs the daemon you asked for. It is made
# executable in this RUN rather than by `COPY --chmod`, which older builders do not
# understand; the chmod has to happen before the USER line below, because after it
# this build is an ordinary user and cannot change a root-owned file.
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN useradd --create-home --uid 10001 azan \
 && mkdir -p /app/config /app/media /app/out \
 && chmod 755 /app/docker-entrypoint.sh \
 && chown -R azan:azan /app
USER azan

# 8020 is the panel, 8010 the media server the speakers pull audio from. These are
# the defaults, not a promise: MUEZZIN_WEB_PORT and MUEZZIN_HTTP_PORT say otherwise
# for one container, which is how a second muezzin on the same machine gets its own
# ports without rewriting the command below. EXPOSE keeps the defaults, because it
# is documentation for whoever is reading this file, and Docker uses it for nothing
# except what `docker inspect` reports.
EXPOSE 8020 8010

ENTRYPOINT ["/app/docker-entrypoint.sh"]
# The page can edit the profile, because the map, the speaker scan and the upload
# box are how anyone finishes setting this up: a container nobody can configure
# from the page is not something you can pull and use. The honest cost is that the
# page has no login, so whoever can reach port 8020 on that machine can change the
# schedule. On a network you do not trust, put "--read-only" at the end of the
# arguments in a compose `command:`; the config folder has to be writable for the
# page to save at all, read-only or not.
#
# `--web` is left bare on purpose. The number is what a second container has to
# change, and an argument already carrying a number beats an environment variable,
# so pinning 8020 here would mean rewriting this whole line - and the argument list
# is also where the read-only and allow-host choices live. A bare --web says "the
# page runs", and MUEZZIN_WEB_PORT says on which port, 8020 when it is not set.
CMD ["daemon", "-c", "/app/config/muezzin.yaml", "--web"]

