"""Entry point — `python nonograms.py [puzzle-name]`."""

from __future__ import annotations

import argparse

from nonograms_tui.app import run


def main() -> None:
    p = argparse.ArgumentParser(prog="nonograms-tui")
    p.add_argument("puzzle", nargs="?", default=None,
                   help="puzzle name (slug) from the pack; default is random")
    p.add_argument("--list", action="store_true",
                   help="list available puzzles and exit")
    args = p.parse_args()

    if args.list:
        from nonograms_tui.puzzles import list_puzzles
        for p in list_puzzles():
            print(f"{p.slug:<24}  {p.width:>2}x{p.height:<2}  {p.title}")
        return

    run(args.puzzle)


if __name__ == "__main__":
    main()
