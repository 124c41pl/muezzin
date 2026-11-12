Put your `muezzin.yaml` in this folder and the container will read it as
`/app/config/muezzin.yaml`. Nothing in here is part of the image: your times,
your speakers and your schedule stay on your machine.

To start one off:

    docker run --rm -v "%cd%\config:/app/config" muezzin:0.1.0 init -c /app/config/muezzin.yaml

On Linux or macOS, replace `%cd%` with `$PWD`. Then edit the file — set
`location`, pick a `method`, add your speakers under `outputs` — and bring the
service up with `docker compose up`.
