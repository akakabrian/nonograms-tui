"""Nonogram line solver — pure Python, no deps.

Algorithm: standard constraint propagation. For each row/column we
compute the set of "forced" cells — cells that are the same value
across *every* legal placement of its clue list. Repeat until nothing
new is forced. This solves all monotonic ("line-solvable") puzzles,
which covers the vast majority of hand-designed ones. For the rest we
fall back to plain recursive search.

Cell states:
- UNKNOWN = 0 : we haven't proved anything yet
- FILLED  = 1 : must be filled
- EMPTY   = 2 : must be blank / crossed

Top-level API:
    solve(clues_rows, clues_cols) -> list[list[int]]
    hint_cell(rows, cols, user_grid) -> (x, y, state) | None
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable

UNKNOWN = 0
FILLED = 1
EMPTY = 2


def _enumerate_placements(clues: tuple[int, ...], length: int) -> list[tuple[int, ...]]:
    """All ways to place `clues` groups into a line of `length`.
    Returns each placement as a tuple of per-cell states of length `length`."""
    if not clues:
        return [(EMPTY,) * length]
    out: list[tuple[int, ...]] = []
    total = sum(clues) + len(clues) - 1
    if total > length:
        return out

    def recurse(idx: int, pos: int, prefix: list[int]) -> None:
        run = clues[idx]
        remaining_after = sum(clues[idx + 1:]) + max(0, len(clues) - idx - 1)
        last_start = length - remaining_after - run
        for start in range(pos, last_start + 1):
            new_prefix = list(prefix)
            # Empties from `pos` up to `start`
            new_prefix.extend([EMPTY] * (start - pos))
            new_prefix.extend([FILLED] * run)
            if idx == len(clues) - 1:
                # Tail empties
                new_prefix.extend([EMPTY] * (length - len(new_prefix)))
                out.append(tuple(new_prefix))
            else:
                new_prefix.append(EMPTY)  # mandatory gap
                recurse(idx + 1, len(new_prefix), new_prefix)

    recurse(0, 0, [])
    return out


# The placement-enumerator is pure over (clues_tuple, length) so it's
# easy to cache. Most puzzles reuse the same clue shapes many times
# during propagation.
@lru_cache(maxsize=4096)
def _placements_cached(clues: tuple[int, ...], length: int) -> tuple[tuple[int, ...], ...]:
    return tuple(_enumerate_placements(clues, length))


def _filter_placements(
    placements: Iterable[tuple[int, ...]], known: list[int]
) -> list[tuple[int, ...]]:
    """Keep only placements compatible with already-known cells."""
    out: list[tuple[int, ...]] = []
    for p in placements:
        ok = True
        for i, k in enumerate(known):
            if k != UNKNOWN and p[i] != k:
                ok = False
                break
        if ok:
            out.append(p)
    return out


def _intersect(placements: list[tuple[int, ...]], length: int) -> list[int]:
    """Compute per-cell forced values: if all placements agree, that's
    the forced value; otherwise UNKNOWN."""
    if not placements:
        return [UNKNOWN] * length
    result = list(placements[0])
    for p in placements[1:]:
        for i in range(length):
            if result[i] != UNKNOWN and result[i] != p[i]:
                result[i] = UNKNOWN
    return result


def _line_propagate(clues: tuple[int, ...], known: list[int]) -> list[int] | None:
    """Return the strongest deductions we can make for one line, or None
    if the line is now impossible (no placement fits)."""
    placements = _placements_cached(clues, len(known))
    filtered = _filter_placements(placements, known)
    if not filtered:
        return None
    return _intersect(filtered, len(known))


def solve(
    row_clues: list[list[int]],
    col_clues: list[list[int]],
    initial: list[list[int]] | None = None,
    max_iters: int = 1000,
) -> list[list[int]] | None:
    """Solve a nonogram via line propagation + fallback search.
    Returns the full grid (FILLED/EMPTY) or the partial grid if it's not
    line-solvable. Returns None on contradiction.
    """
    h = len(row_clues)
    w = len(col_clues)
    grid: list[list[int]] = (
        [row[:] for row in initial] if initial is not None
        else [[UNKNOWN] * w for _ in range(h)]
    )
    row_tuples = [tuple(c) for c in row_clues]
    col_tuples = [tuple(c) for c in col_clues]

    changed = True
    iters = 0
    while changed and iters < max_iters:
        iters += 1
        changed = False
        # Rows
        for y in range(h):
            new = _line_propagate(row_tuples[y], grid[y])
            if new is None:
                return None
            for x in range(w):
                if new[x] != UNKNOWN and grid[y][x] != new[x]:
                    grid[y][x] = new[x]
                    changed = True
        # Columns
        for x in range(w):
            col = [grid[y][x] for y in range(h)]
            new = _line_propagate(col_tuples[x], col)
            if new is None:
                return None
            for y in range(h):
                if new[y] != UNKNOWN and grid[y][x] != new[y]:
                    grid[y][x] = new[y]
                    changed = True

    # If fully determined we're done.
    if all(grid[y][x] != UNKNOWN for y in range(h) for x in range(w)):
        return grid

    # Otherwise fall back to search: pick the UNKNOWN cell and try both.
    return _search(grid, row_tuples, col_tuples, w, h)


def _search(
    grid: list[list[int]],
    row_tuples: list[tuple[int, ...]],
    col_tuples: list[tuple[int, ...]],
    w: int,
    h: int,
) -> list[list[int]] | None:
    # Pick the first UNKNOWN cell — simple, good enough for small puzzles.
    target = None
    for y in range(h):
        for x in range(w):
            if grid[y][x] == UNKNOWN:
                target = (x, y)
                break
        if target:
            break
    if target is None:
        return grid
    x, y = target
    for guess in (FILLED, EMPTY):
        copy = [row[:] for row in grid]
        copy[y][x] = guess
        result = solve(
            [list(t) for t in row_tuples],
            [list(t) for t in col_tuples],
            initial=copy,
        )
        if result is not None and all(
            result[yy][xx] != UNKNOWN for yy in range(h) for xx in range(w)
        ):
            return result
    return None


# ---------- hint API -------------------------------------------------

def hint_cell(
    row_clues: list[list[int]],
    col_clues: list[list[int]],
    user_grid: list[list[int]],
) -> tuple[int, int, int] | None:
    """Find ONE forced cell that the user hasn't already filled in.

    We run a propagation step from the puzzle start (NOT the user state
    — that would propagate mistakes). Returns (x, y, state) where state
    is FILLED or EMPTY, or None if the puzzle is unsolvable or the user
    already has every deducible cell.
    """
    h = len(row_clues)
    w = len(col_clues)
    solved = solve(row_clues, col_clues)
    if solved is None:
        return None
    # Prefer FILLED hints — they're more visually interesting than EMPTY
    # reveals, and players tend to chase picture progress. Iterate in
    # row-major order but hand back the first *filled* hint we see;
    # fall back to empty otherwise.
    fallback: tuple[int, int, int] | None = None
    for y in range(h):
        for x in range(w):
            truth = solved[y][x]
            if truth == UNKNOWN:
                continue
            if user_grid[y][x] == truth:
                continue
            # A mismatched user cell (wrong fill) is more urgent than an
            # empty one — hint that first to stop the player before they
            # go further down a dead end.
            if user_grid[y][x] != UNKNOWN and user_grid[y][x] != truth:
                return (x, y, truth)
            if truth == FILLED:
                return (x, y, truth)
            if fallback is None:
                fallback = (x, y, truth)
    return fallback


# ---------- convenience ----------------------------------------------

def verify_solution(row_clues: list[list[int]], col_clues: list[list[int]],
                    grid: list[list[bool]]) -> bool:
    """Does `grid` (True=filled) satisfy all clues?"""
    from .puzzles import clues_from_grid
    rr, cc = clues_from_grid(grid)
    return rr == row_clues and cc == col_clues
