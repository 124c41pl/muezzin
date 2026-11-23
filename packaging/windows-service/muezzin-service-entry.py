# The frozen build's entry point. Not a second startup path: this is the same
# `muezzin = "muezzin.cli:main"` console script pyproject.toml declares, and it
# exists only because a spec that analyses src/muezzin/cli.py *as a script*
# makes it a top-level module, and every `from . import ...` inside the package
# then fails at start with "attempted relative import with no known parent
# package" — found the honest way, by running the first build.
from muezzin.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
