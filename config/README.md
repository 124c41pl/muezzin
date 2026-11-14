Put your `muezzin.yaml` in this folder and the container will read it as
`/app/config/muezzin.yaml`. Nothing in here is part of the image: your times,
your speakers and your schedule stay on your machine.

To start one off:

    docker run --rm -v "%cd%\config:/app/config" muezzin:0.1.2 init -c /app/config/muezzin.yaml

On Linux or macOS, replace `%cd%` with `$PWD`. Then point it at your house. The page
does all three of those jobs: a **Where** section where numbers can be checked against
the towns this program carries or a position clicked out on the map, a dropdown for the
method, and **look again** then **use** for the speakers — so not one of those lines has
to be typed into a file. A starter lists no speakers on purpose: an output pointed at a
speaker nobody owns is an error at every prayer time, so the list only ever contains
what you added, from the page or by hand.

The starter's `media_dir: media` is relative to the profile, so your recordings
live in this folder's `media` subfolder. Set it to `/app/media` instead if you
want to use the `./media` folder that `docker-compose.yml` mounts.

The quickest way to set those three location lines is the **Where** section on the
page: numbers typed there can be checked against the town centres this program carries,
and the map behind them can be clicked to point instead. `muezzin where --online <words>`
is the same thing from a command line. The forms that use words ask OpenStreetMap's
Nominatim once, because you pressed the button; the map squares are the one thing that
goes out unprompted, and `map_tiles: off` in the profile stops even that. None of this
needs an API key. If you would rather the lookup be a courtesy than anonymous, give it a
way back to you:

    MUEZZIN_CONTACT="https://example.org/muezzin"    # added to the request's name
    MUEZZIN_GEOCODE="https://nominatim.example.org"  # your own instance instead

Neither is needed, nothing about a lookup is stored here, and no lookup in this
program asks for an API key. With no outbound network at all the times do not care: type
the coordinates in by hand, put `map_tiles: off` in the profile, and this daemon never
asks anybody anything.
