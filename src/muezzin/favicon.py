"""The panel's tab icon, as bytes. Generated - do not edit.

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
FAVICON_SIZE = 32

# The 32px render, base64 of a PNG with an alpha channel.
_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAADoUlEQVR42s2X30tTcRjGz3Vq"
    "5tQ53dyOcxpsburaprOcF54df/8oAxNFqSZFSRBREJR5401YXhTVhdBFUFFSIELkzfkXugsJ"
    "uu2m/+Htfb46PTueHc8JjQaP53zfH5/n2QZukyTdwx1pkhsyydWQktbkc/EjFZhgw0Mye8hn"
    "40uh3jR5os1U2RQ4FoEND3gVmAe44EtFycVD/0LwCuRDVIcbZaRyhfyOlZsfoanp3r/ahSe8"
    "pYbuxGpNSxO5Gv0HlL53g+q7zpj25NYwfd+8KYR7sxnsgmHWgye8pVBvp1bRWE9GnR7vo6G1"
    "FYpfmyaz/taHJdr+OCq08ea+6Qx2wQDLrA9vyd/VrlUEuWCQ8mSR+p4v88sUInekmbKPH4or"
    "erO5SfqxMbcXAPeooaefxS4YYJl5wJsDtHEAH+nlS7eL5MlbV8Q5xdeZr+/FFef1V7k987xQ"
    "M5sFAywwjT7wlvxpDtDABZ3CkyM7L92YKs6ja08F1B1uonA8eMA8L/Qwg1nsYBcMsMA0+sBb"
    "8ne2aadkL+kVm70olgI9HeIM4MCzZVq4PkRf1mbp26d5+rl1u0CooYcZzGIHu2CABabRB96O"
    "Aqy/zBV99ntvBc84DxCoI71isxM7ATIpcZ78/JouvH0h7vvOD9LvX9umQg8zmMUO7sHYCTBB"
    "Rp+9AOV80CuoZsRSlJdw7nl0Rzwj1FWLAOhhBrPYwW5098mgbvTZDdCqlftrSa/KZlksKSuL"
    "4hzMdgtoy6UxUscHigfgHmZEWN7BLhhggWn0gbfk7+AA9VwwKLFwWSz6u1PiXNsWEdfDAuhn"
    "sQsGWGYe8OYAMQ7gIaPc/MmF5fbcVEFdHe+3CNBfMItdMMAy84C3VJ+KaSd9HjJTbSJ2oKaO"
    "WQTgnh1GXvDeDVBDdnV4APus/QBeLtiUOmoRgHtOWPsB6txkV+pIX/EA3HPCEgF8/KeMD3aV"
    "tQiAnhOWTwRIRrWy2mqyq+ywWjwA95yw4P0fBEi0aKWeKrIrZThbNAB6Tljw3glQwwWbUoYs"
    "AnDPCUsXoJLsShlSLAIo5IQlAgR7klqpmws2pQxaBOCeExa88WG0iq9HJW6XLfVaBEDPLkd8"
    "JWNvqdznkYOZJJVUuw7V5sa7ouZ5YcYOC57wFr+OfPHIUk0kRCVVFZaauzpDDxbvWgozh3Hg"
    "Bc+C34deLvCvV/6q5KUTPHQcAhseXqN5/sEfEDL/f15tyCQ0bzx8pAITbHjoTf8Avx2vvqhw"
    "pWUAAAAASUVORK5CYII="
)

FAVICON_PNG = base64.b64decode(_B64)
FAVICON_DATA_URL = "data:image/png;base64," + _B64
