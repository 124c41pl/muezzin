#!/bin/sh
# muezzin's container entrypoint: make the first run work, then get out of the way.
#
# /app/config is a volume, so on a fresh machine it arrives empty, and a daemon
# with no profile can only print a usage error and exit. Writing the starter here
# is what turns "docker run" into a page you can finish setting up. A profile that
# already exists is never touched, and `muezzin init` refuses to overwrite one, so
# this stays honest if the folder is half-set-up: it either writes the starter or
# says it could not.
#
# The media folder is named explicitly because the starter's default is relative
# to the profile, which in a container means inside the config volume, while
# compose mounts the audio at /app/media. Pointing the profile at the mount is
# what makes the recordings you copied land where the page looks for them.
set -eu

CONFIG=/app/config/muezzin.yaml
if [ ! -f "$CONFIG" ]; then
    echo "no profile at $CONFIG: writing a starter. Open the page and say where you are."
    if ! muezzin init -c "$CONFIG" --media-dir /app/media; then
        echo "could not write it. $CONFIG has to sit in a folder this container can write;" >&2
        echo "muezzin runs as uid 10001 in this image." >&2
        exit 2
    fi
fi

# exec, so the daemon itself is the process Docker sends SIGTERM to. Without it
# this script is the container's main process: the stop signal stops the script,
# the daemon keeps running as an orphan inside the container, and `docker stop`
# waits out its timeout and kills the lot. Reaching the daemon promptly is worth
# the line; note that nothing here finishes an adhan that was mid-play, because no
# part of muezzin traps SIGTERM — Ctrl-C is the clean stop, and the play is cut
# short either way.
exec muezzin "$@"
