# Nonograms-TUI — engine & design decisions

## Engine

This game has no native "engine" like Micropolis; nonograms are pure logic.
Two concerns to vendor:

1. **Puzzle library + file format.** We use
   [`mikix/nonogram-db`](https://github.com/mikix/nonogram-db) (GPL-3.0).
   39 puzzles covering webpbn, gnonograms, and the qnonograms collection,
   all in Steve Simpson's `.non` format:
   ```
   width 5
   height 10
   rows
   2
   2,1
   ...
   columns
   2,1
   ...
   goal "0110001101..."
   ```
   The format supports multi-color puzzles via color characters after each
   clue number (e.g. `3b,1d`). We restrict ourselves to black-and-white
   puzzles for the first release — any clue with a color suffix is treated
   as black, and any `goal` character other than `0` counts as filled.

2. **Solver.** We write a compact pure-Python line solver rather than
   vendoring an existing one. Reasons:
   - The vendored candidates (`mprat/nonogram-solver`, `tsionyx/pynogram`)
     are general-purpose CLIs with their own data structures; integrating
     them as libraries adds friction.
   - Line-solving is ~150 lines and a standard algorithm — compute the set
     of valid placements for each line, intersect them, propagate what's
     forced, repeat until stable. This gives us hints (a single forced
     cell) with full control over quality.
   - No extra runtime dependencies.

   See `nonograms_tui/solver.py`. The solver returns a partial grid with
   cells marked FILLED / EMPTY / UNKNOWN. A "hint" is any one cell that
   went from UNKNOWN to FILLED/EMPTY during the last solver pass — we
   reveal it on the board to nudge the player.

## Cell states (player-facing)

Three states per cell (matches Picross convention):
- **EMPTY** — untouched / cleared
- **FILLED** — player believes this is part of the picture (left-click / space)
- **CROSSED** — player believes this cell is blank (right-click / x)

Win detection ignores CROSSED vs EMPTY; only the set of FILLED cells
needs to match `goal`.

## UI layout

Textual 4-panel, mirroring simcity-tui:

```
 +-----------------------------------------------+-----------+
 |                                               | PUZZLE    |
 |                 BOARD (clues + grid)          | STATE     |
 |                                               +-----------+
 |                                               | CONTROLS  |
 |                                               |           |
 +-----------------------------------------------+           |
 |              flash bar (one line)             |           |
 +-----------------------------------------------+-----------+
 |                 MESSAGE LOG                               |
 +-----------------------------------------------------------+
```

## Key bindings

- arrows / hjkl — move cursor
- space / enter — toggle FILLED
- x — toggle CROSSED
- c — clear cell
- h — hint (reveal one forced cell)
- u — undo
- n — new puzzle (random from pack)
- L — load specific puzzle
- r — restart current puzzle
- p — pause (stops the timer)
- ? — help

## Rendering

Each cell is two terminal cells wide (`██` filled, `░░` empty, `××` cross)
so the grid reads as square at typical 2:1 character aspect ratios. Clue
columns are rendered vertically to the left/top of the grid. 5-cell
blocks get a subtle gridline every 5 rows/cols for readability
(standard Picross).

## Why not build a solver-first "generator"?

The DB has enough puzzles (39) to hit the 30-puzzle target. We could
generate random unique-solution puzzles with our solver (build grid →
derive clues → verify unique via solver), but it's Phase E polish, not
MVP. We validate each shipped puzzle by running the solver against its
clues and checking the solution matches `goal`.
