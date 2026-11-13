Put your `muezzin.yaml` in this folder and the container will read it as
`/app/config/muezzin.yaml`. Nothing in here is part of the image: your times,
your speakers and your schedule stay on your machine.

To start one off:

    docker run --rm -v "%cd%\config:/app/config" muezzin:0.1.2 init -c /app/config/muezzin.yaml

On Linux or macOS, replace `%cd%` with `$PWD`. Then edit the file — set
`location` to where you actually are, pick a `method`, and add your speakers
under `outputs`. A starter lists no speakers on purpose: an output pointed at a
speaker nobody owns is an error at every prayer time, so the list only ever
contains what you added, from the page or by hand.

The starter's `media_dir: media` is relative to the profile, so your recordings
live in this folder's `media` subfolder. Set it to `/app/media` instead if you
want to use the `./media` folder that `docker-compose.yml` mounts.

The quickest way to set those three location lines is the **Where** section on the
page, or `muezzin where --online <words>` on a command line: both ask OpenStreetMap's
Nominatim once, and `map_tiles: osm` adds a map to the page. Both need this container
to have a way out to the internet, and neither is switched on by itself. If you would
rather the lookup be a courtesy than anonymous, give it a way back to you:

    MUEZZIN_CONTACT="https://example.org/muezzin"    # added to the request's name
    MUEZZIN_GEOCODE="https://nominatim.example.org"  # your own instance instead

Neither is needed, nothing about a lookup is stored here, and no lookup in this
program asks for an API key. With no outbound network at all the times do not care:
type the coordinates in by hand and the daemon never asks anybody anything.
