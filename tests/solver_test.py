"""Verify the solver against every vendored puzzle.

For each puzzle with a `goal`, solve it and check every cell of our
solution matches the goal. Prints one line per puzzle; exit code = fail
count. This is the acceptance test for hints — if the solver doesn't
agree with the author's goal, hints would mislead the player.
"""

from __future__ import annotations

import sys
import time

from nonograms_tui import solver
from nonograms_tui.puzzles import list_puzzles


def main() -> int:
    puzzles = list_puzzles()
    if not puzzles:
        print("No puzzles found (run 'make bootstrap').")
        return 1
    fails = 0
    total_time = 0.0
    for p in puzzles:
        if not p.has_goal:
            print(f"  {p.slug:<30}  [skip — no goal]")
            continue
        t0 = time.monotonic()
        try:
            result = solver.solve(p.rows, p.columns)
        except Exception as e:
            print(f"  {p.slug:<30}  ✗ crash: {e}")
            fails += 1
            continue
        dt = time.monotonic() - t0
        total_time += dt
        if result is None:
            print(f"  {p.slug:<30}  ✗ solver returned None ({dt:.2f}s)")
            fails += 1
            continue
        ok = True
        assert p.goal is not None
        for y in range(p.height):
            for x in range(p.width):
                want = solver.FILLED if p.goal[y][x] else solver.EMPTY
                if result[y][x] != want:
                    ok = False
                    break
            if not ok:
                break
        status = "✓" if ok else "✗ mismatch"
        print(f"  {p.slug:<30}  {p.width:>2}x{p.height:<2}  {status}  ({dt:.2f}s)")
        if not ok:
            fails += 1
    print(f"\n{len(puzzles) - fails}/{len(puzzles)} puzzles solved; "
          f"total {total_time:.2f}s")
    return fails


if __name__ == "__main__":
    sys.exit(main())
