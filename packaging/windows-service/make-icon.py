#!/usr/bin/env python3
"""Draw muezzin's icon and write it out as a Windows .ico.

Why this is a script in the repo rather than a binary someone drew once in a
paint program: every mark in the icon comes from the same palette the panel
itself uses (src/muezzin/page.py: --bg, --line, --fg, --gold, --turq), and the
sizes are rendered from one geometry. Change the geometry, re-run, and all
seven sizes in the .ico agree with each other. A hand-drawn .ico tends to
 quietly disagree with itself at 16px, which is the size a taskbar shows.

No dependencies: the drawing and the .ico/PNG containers are written here in
plain Python. Pillow would be twelve lines less code and one more thing every
machine that builds this has to install, and muezzin.spec already names PIL as
something the shipped exe must not carry.

    python make-icon.py --variant minaret --out muezzin.ico
    python make-icon.py --variant all --preview-dir previews
    python make-icon.py --favicon ../../src/muezzin/favicon.py

The --favicon route writes the panel's tab icon out as a Python module of bytes, because
that is the one surface of the four that is not a Windows file: see favicon_module below
for why bytes, and src/muezzin/favicon.py for the one that ships.

Sizes in the .ico: 16, 24, 32, 48, 64, 128, 256. That is what Windows asks for
between a list view and a desktop icon. Below 48px the thin parts of the
drawing (the smallest arc, the finial on the tower, the crescent) are left out
rather than left to turn to mud; the silhouette is what has to survive there.
"""

import argparse
import base64
import math
import struct
import zlib
from pathlib import Path

# The panel's palette, spelled the same way page.py spells it.
BG_TOP = "#132620"      # a touch lighter than --bg, so the tile reads as a tile
BG_BOT = "#0a1310"      # --bg
RIM = "#2c5145"         # between --line and --turq
CREAM = "#ece7d9"       # --fg
GOLD = "#d9ab4e"        # --gold
GOLD_HI = "#f0cf8c"     # --gold2
TURQ = "#5cb9a8"        # --turq
TURQ_2 = "#4b9c8c"      # --turq against the tile, for the second wave
TURQ_3 = "#3d8274"      # ...and the third, so the call fades as it travels

SIZES = [16, 24, 32, 48, 64, 128, 256]
SS = 4                  # samples per pixel per layer; 4x4 gives 17 coverage steps
FAVICON_SIZE = 32       # what a browser tab asks for; the .ico covers Windows' own sizes


def rgb(spec):
    return (int(spec[1:3], 16), int(spec[3:5], 16), int(spec[5:7], 16))


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


# --- shape predicates, all in the tile's own 0..1 coordinate space ----------
# A predicate answers "is this point inside the mark?" once, and the renderer
# counts how many of its 4x4 sub-samples answer yes. Every mark in every
# variant is one of these six, which is what keeps the whole icon family
# consistent - and what keeps a 16px render from needing its own artwork.

def rounded_rect(u, v, x0, y0, x1, y1, r):
    if u < x0 or u > x1 or v < y0 or v > y1:
        return False
    cx = min(max(u, x0 + r), x1 - r)
    cy = min(max(v, y0 + r), y1 - r)
    return (u - cx) ** 2 + (v - cy) ** 2 <= r * r


def disc(u, v, cx, cy, r):
    return (u - cx) ** 2 + (v - cy) ** 2 <= r * r


def ring(u, v, cx, cy, r_in, r_out, a0=None, a1=None):
    d2 = (u - cx) ** 2 + (v - cy) ** 2
    if d2 < r_in * r_in or d2 > r_out * r_out:
        return False
    if a0 is None:
        return True
    a = math.degrees(math.atan2(v - cy, u - cx))
    if a < -90:                       # the seam sits at the top, away from the arcs
        a += 360
    return a0 <= a <= a1


def capsule(u, v, ax, ay, bx, by, t):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    k = 0.0 if L2 == 0 else max(0.0, min(1.0, ((u - ax) * dx + (v - ay) * dy) / L2))
    px, py = ax + k * dx, ay + k * dy
    return (u - px) ** 2 + (v - py) ** 2 <= (t / 2.0) ** 2


def polygon(u, v, pts):
    # even-odd crossing count; the minaret is one polygon so it stays one solid mark
    inside = False
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        if (ay > v) != (by > v):
            x = ax + (v - ay) / (by - ay) * (bx - ax)
            if u < x:
                inside = not inside
    return inside


def arch(u, v, cx, ytop, ybase, wmax, taper):
    """A mihrab: straight sides rising to a point. taper > 1 pulls the top into
    a point instead of a semicircle, which is what makes it read as a prayer
    niche and not a doorway."""
    if v < ytop or v > ybase:
        return False
    t = (ybase - v) / (ybase - ytop)
    return abs(u - cx) <= wmax * (1.0 - t ** taper)


# --- the three candidate marks --------------------------------------------

def minaret_mark(detail, size=0):
    """The mark that ships: a minaret with the call leaving it from the
    balcony, both ways. Centred left-to-right on purpose - a tower off to one
    side with the sound going the other way looks like it is falling over at
    16px, which is the only size a taskbar ever shows.

    Reading order is what makes it legible: a cream shaft (the tallest,
    narrowest thing on the tile, so it wants the brightest colour), a gold
    roof and a gold gallery band (the second colour arrives early, because a
    single cream shape on a dark tile looks like a paper cutout), and the
    turquoise waves leaving the gallery - which is the whole app in one
    sentence: a tower that is on a schedule, driving speakers.

    The waves are the only part that changes with canvas size. At 48px and up
    there are three, each 3.4-3.8% of the tile thick, fading outwards. At
    24-32px two, at 5.5% thick, because a 3.4% stroke on a 32px canvas is a
    third of a pixel and turns to dirt. At 16px one wave per side, at 6.5%,
    which is a full pixel and reads as a bracket either side of the gallery
    rather than as noise. The tower is the same geometry at every size."""
    tower = [
        (0.350, 0.925), (0.350, 0.878),          # plinth, left
        (0.400, 0.878), (0.400, 0.345),          # shaft, left
        (0.360, 0.345), (0.360, 0.296),          # gallery, left
        (0.425, 0.296), (0.425, 0.205),          # upper shaft, left
        (0.500, 0.100),                          # roof point
        (0.575, 0.205), (0.575, 0.296),          # upper shaft, right
        (0.640, 0.296), (0.640, 0.345),          # gallery, right
        (0.600, 0.345), (0.600, 0.878),          # shaft, right
        (0.650, 0.878), (0.650, 0.925),          # plinth, right
    ]
    yield polygon, (tower,), CREAM
    # The roof and the gallery are painted over the tower in gold, in step with
    # the tower's own outline, so there is no seam between the two colours.
    yield polygon, (((0.500, 0.100), (0.615, 0.296), (0.385, 0.296)),), GOLD
    yield rounded_rect, (0.360, 0.296, 0.640, 0.345, 0.010), GOLD
    if detail:
        # A doorway at the foot of the shaft, in the tile's own dark: it gives
        # the tower a scale (a person could stand in it) and it is the mihrab
        # shape again, the one that points at the prayer.
        yield arch, (0.500, 0.690, 0.810, 0.048, 1.7), "#1c2c26"
    if size >= 48:
        waves = [(0.150, 0.034, TURQ), (0.232, 0.036, TURQ_2), (0.314, 0.038, TURQ_3)]
    elif size >= 24:
        waves = [(0.165, 0.055, TURQ), (0.275, 0.055, TURQ_2)]
    else:
        waves = [(0.210, 0.065, TURQ)]
    for r, t, colour in waves:
        yield ring, (0.500, 0.320, r, r + t, -36.0, 36.0), colour
        yield ring, (0.500, 0.320, r, r + t, 144.0, 216.0), colour
    if detail:
        yield capsule, (0.500, 0.104, 0.500, 0.062, 0.017), GOLD_HI
        yield disc, (0.500, 0.048, 0.021), GOLD


def crescent_mark(detail, size=0):
    """The moon the whole calendar turns on, over three levels of sound."""
    yield lambda u, v: disc(u, v, 0.500, 0.400, 0.290) and not disc(u, v, 0.588, 0.322, 0.248), None, GOLD
    bars = [(0.470, 0.700), (0.350, 0.782), (0.230, 0.864)]
    if not detail:
        bars = bars[:2]
    for w, y in bars:
        yield rounded_rect, (0.500 - w / 2, y - 0.028, 0.500 + w / 2, y + 0.028, 0.028), TURQ


def niche_mark(detail, size=0):
    """A mihrab arch with the call rising inside it: the niche points at the
    prayer, the arcs are what carries it into the rooms."""
    outer = (0.500, 0.160, 0.878, 0.212, 1.9)
    inner = (0.500, 0.222, 0.830, 0.156, 1.9)
    yield lambda u, v: arch(u, v, *outer) and not arch(u, v, *inner), None, GOLD
    arcs = [(0.095, 0.032), (0.165, 0.034)]
    if detail:
        arcs.append((0.235, 0.036))
    for r, t in arcs:
        yield ring, (0.500, 0.790, r, r + t, 208.0, 332.0), TURQ
    if detail:
        yield disc, (0.500, 0.790, 0.030), GOLD_HI


VARIANTS = {
    "minaret": minaret_mark,
    "crescent": crescent_mark,
    "niche": niche_mark,
}


def render(variant, size):
    """One tile: gradient, rim, then the mark. The tile and every mark are
    sampled on the same 4x4 grid, so they are antialiased against each other
    rather than each being blurred on its own."""
    bg_top, bg_bot, rim = rgb(BG_TOP), rgb(BG_BOT), rgb(RIM)
    marks = [(pred, args if args is not None else (), rgb(colour))
             for pred, args, colour in VARIANTS[variant](size >= 48, size)]
    out = bytearray()
    for py in range(size - 1, -1, -1):        # BMP rows run bottom-up
        base = mix(bg_top, bg_bot, (py + 0.5) / size)
        row = bytearray()
        for px in range(size):
            hits_tile = hits_rim = 0
            hit_counts = [0] * len(marks)
            for sy in range(SS):
                for sx in range(SS):
                    u = (px + (sx + 0.5) / SS) / size
                    # v runs down the mark (0 at the top of the drawing, 1 at the
                    # bottom), while py runs up the buffer, because the buffer is
                    # written bottom-up the way a BMP insists on being read.
                    # Getting these two lined up is the whole of getting an icon
                    # that is not a minaret with its finial in the ground: the
                    # first version of this line flipped every mark upside down.
                    v = (py + (sy + 0.5) / SS) / size
                    if not rounded_rect(u, v, 0.006, 0.006, 0.994, 0.994, 0.19):
                        continue
                    hits_tile += 1
                    if not rounded_rect(u, v, 0.026, 0.026, 0.974, 0.974, 0.175):
                        hits_rim += 1
                    for k, (pred, args, _colour) in enumerate(marks):
                        if pred(u, v, *args):
                            hit_counts[k] += 1
            tile = hits_tile / (SS * SS)
            if tile <= 0:
                row += b"\x00\x00\x00\x00"
                continue
            col = [float(c) for c in base]
            rimc = hits_rim / (SS * SS)
            for i in range(3):
                col[i] = col[i] * (1 - rimc) + rim[i] * rimc
            for k, (_pred, _args, colour) in enumerate(marks):
                a = hit_counts[k] / (SS * SS)
                if a:
                    for i in range(3):
                        col[i] = col[i] * (1 - a) + colour[i] * a
            r, g, b = (int(round(c)) for c in col)
            row += bytes((b, g, r, int(round(255 * tile))))
        out += row
    return bytes(out)


def ico_bytes(pairs):
    """A .ico of 32-bit BGRA entries - no compression, so whatever reads it
    (Explorer, Inno, a service listing) does not need to understand PNG."""
    n = len(pairs)
    dirs = b""
    data = b""
    offset = 6 + 16 * n
    for size, pixels in pairs:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        # the AND mask Inno and older readers insist on: one bit per pixel,
        # rows padded to 4 bytes, all zero because the alpha channel carries it
        stride = ((size + 31) // 32) * 4
        mask = b"\x00" * (stride * size)
        # biHeight is twice the image height. That is not padding and not a
        # mistake: the header describes the colour bitmap *and* the AND mask
        # below it as one bitmap, and GDI takes it literally. With a single
        # height here - which is what the first version of this line said -
        # every entry parsed, the offsets all lined up, System.Drawing's Icon
        # directory reader was happy, and `new Icon(path)` still failed with
        # "The operation completed successfully", which is GDI's way of saying
        # it got a bitmap it could not turn into an icon. Explorer would have
        # shown a blank tile, and Explorer is the only reader that matters.
        header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0)
        # The header belongs to the entry, not next to it. The first version of
        # this function built it, packed it into a local variable, and then wrote
        # pixels + mask without it - which is a .ico whose directory is perfect
        # (seven entries, right sizes, right offsets, offsets that tile the file
        # exactly) and whose payloads are bare BGRA. Every reader that parses the
        # directory is happy; every reader that wants the picture is not. The
        # tell, measured against C:\Windows\System32\OneDrive.ico, was the entry
        # size: its 16px entry is 1,128 bytes - 40 header + 1,024 pixels + 64
        # mask - and mine was 1,088.
        entry = header + pixels + mask
        dirs += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(entry), offset)
        data += entry
        offset += len(entry)
    return struct.pack("<HHH", 0, 1, n) + dirs + data


def png_bytes(width, height, rgba):
    """A PNG preview so a person can see the icon before anything is built."""
    rows = b""
    for py in range(height):
        rows += b"\x00" + rgba[py * width * 4:(py + 1) * width * 4]

    def chunk(kind, body):
        c = kind + body
        return struct.pack(">I", len(body)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9))
            + chunk(b"IEND", b""))


def bgra_to_rgba(pixels, size):
    out = bytearray()
    for py in range(size - 1, -1, -1):
        row = pixels[py * size * 4:(py + 1) * size * 4]
        for px in range(size):
            b, g, r, a = row[px * 4:px * 4 + 4]
            out += bytes((r, g, b, a))
    return bytes(out)


def favicon_module(variant, size=FAVICON_SIZE):
    """The text of src/muezzin/favicon.py: this mark, as a PNG in a string.

    Bytes in a module rather than a file on disk, because the panel has to show the mark
    every way muezzin runs - a checkout, a pip install, a container that ships no data
    files of its own, and a one-file exe whose data sits in a temp folder only the exe
    can name. A file next to the source is findable in the first three and a guessing
    game in the fourth; a constant is the same in all four.

    PNG at 32px rather than the .ico: a browser is told what it is being handed, the tab
    asks for that size anyway, and a 32px PNG of this mark is about a kilobyte against
    the .ico's three hundred and seventy. Same geometry, same palette, one render call -
    which is the whole point of the file.
    """
    png = png_bytes(size, size, bgra_to_rgba(render(variant, size), size))
    b64 = base64.b64encode(png).decode("ascii")
    lines = "\n".join(f'    "{b64[i:i + 72]}"' for i in range(0, len(b64), 72))
    return f'''"""The panel's tab icon, as bytes. Generated - do not edit.

    Drawn by packaging/windows-service/make-icon.py, which is what wrote this file:

        python make-icon.py --favicon ../../src/muezzin/favicon.py

    Change the drawing there and re-run that, and the tab, the exe, the installer and the
    Start Menu entry all change together, because they come from one render of one set of
    coordinates in one palette. Editing this file by hand buys a mark that matches none of
    them, and nothing in a test run would say so until a person noticed the tab was wrong.

    The page embeds FAVICON_DATA_URL in a <link rel="icon"> rather than serving a route,
    for the same reason its background lattice is a data: URL: the panel stays one document
    that asks its own address for nothing else.
    """
import base64

# Which square the mark was drawn into, in case a browser ever wants to be told.
FAVICON_SIZE = {size}

# The 32px render, base64 of a PNG with an alpha channel.
_B64 = (
{lines}
)

FAVICON_PNG = base64.b64decode(_B64)
FAVICON_DATA_URL = "data:image/png;base64," + _B64
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="minaret", choices=sorted(list(VARIANTS) + ["all"]))
    ap.add_argument("--out", default="muezzin.ico")
    ap.add_argument("--preview-dir", default="")
    ap.add_argument("--favicon", default="",
                    help="also write the panel's tab icon to this path as a Python module")
    args = ap.parse_args()

    if args.favicon:
        if args.variant == "all":
            raise SystemExit("--favicon needs one variant: the tab shows one mark, not three")
        fav = Path(args.favicon)
        fav.parent.mkdir(parents=True, exist_ok=True)
        # newline="\n" because this writes a Python source file and the repo's sources are
        # LF-only: left to itself, Python on Windows translates every line on the way out
        # and git answers the next commit with a warning about line endings.
        fav.write_text(favicon_module(args.variant), encoding="utf-8", newline="\n")
        print(f"{fav}: {fav.stat().st_size:,} bytes, the {args.variant} mark at {FAVICON_SIZE}px")

    for variant in (sorted(VARIANTS) if args.variant == "all" else [args.variant]):
        pairs = [(s, render(variant, s)) for s in SIZES]
        if args.variant == "all":
            out = Path(f"muezzin-{variant}.ico")
        else:
            out = Path(args.out)
        out.write_bytes(ico_bytes(pairs))
        print(f"{out}: {out.stat().st_size:,} bytes, sizes {', '.join(str(s) for s in SIZES)}")
        if args.preview_dir:
            prev = Path(args.preview_dir)
            prev.mkdir(parents=True, exist_ok=True)
            for size, pixels in pairs:
                (prev / f"{variant}-{size}.png").write_bytes(
                    png_bytes(size, size, bgra_to_rgba(pixels, size)))
            print(f"  previews in {prev}\\ at sizes {', '.join(str(s) for s in SIZES)}")


if __name__ == "__main__":
    main()
