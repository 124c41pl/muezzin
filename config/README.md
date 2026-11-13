Put your `muezzin.yaml` in this folder and the container will read it as
`/app/config/muezzin.yaml`. Nothing in here is part of the image: your times,
your speakers and your schedule stay on your machine.

To start one off:

    docker run --rm -v "%cd%\config:/app/config" muezzin:0.1.1 init -c /app/config/muezzin.yaml

On Linux or macOS, replace `%cd%` with `$PWD`. Then edit the file — set
`location` to where you actually are, pick a `method`, and add your speakers
under `outputs`. A starter lists no speakers on purpose: an output pointed at a
speaker nobody owns is an error at every prayer time, so the list only ever
contains what you added, from the page or by hand.

The starter's `media_dir: media` is relative to the profile, so your recordings
live in this folder's `media` subfolder. Set it to `/app/media` instead if you
want to use the `./media` folder that `docker-compose.yml` mounts.
