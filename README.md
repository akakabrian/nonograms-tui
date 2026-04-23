# nonograms-tui

Terminal-native Nonograms (aka Picross, Griddlers, Paint-by-Numbers).
Mouse + keyboard, 39 vendored puzzles, pure-Python hint solver.

```
+------------------------------------+-------------+
|     columns clues                  | PUZZLE      |
|   +-----------------------------+  |  title      |
|rows|                             |  |  progress   |
|cls |     player grid (2x cells)  |  +-------------+
|    |                             |  | CONTROLS    |
|    +-----------------------------+  |  key hints  |
|  cursor (1,3)  empty                |             |
|  LOG: Hint at (4, 7)                |             |
+------------------------------------+-------------+
```

## Quick start

```
make all     # clone puzzle DB + create venv (~20s, first time)
make run     # boot the TUI with a random small puzzle
make run ARGS=webpbn-1   # specific puzzle by slug
make test    # 29-scenario headless Pilot QA
make test-solver   # verify solver against every vendored puzzle
```

Requires Python 3.10+. On macOS, install `python@3.12` from Homebrew so
`python3-config` is present (Apple's bundled Python ships without it).

## Controls

| Keys | Action |
|------|--------|
| `←↑→↓` / `hjkl`    | move cursor |
| `space` / `enter`  | fill / un-fill |
| `x`                | cross / un-cross |
| `c`                | clear cell |
| `h`                | hint (reveal one forced cell) |
| `u`                | undo |
| `r`                | restart this puzzle |
| `n`                | new random puzzle |
| `L`                | pick from list |
| `?`                | help |
| `q`                | quit |

Mouse: left-click fills, right-click crosses, drag-paint on either button.

## How the hint works

There's no magic. The vendored puzzle DB (`mikix/nonogram-db`, 39 puzzles,
GPL-3.0) stores puzzles in Steve Simpson's `.non` format. We parse those,
then a pure-Python line solver enumerates legal placements per row/column,
intersects them, and propagates until a fixed point. Any cell that flips
`UNKNOWN → FILLED` or `UNKNOWN → EMPTY` during propagation is eligible as
a hint; we prefer filled hints (more satisfying) and always correct a
mistake first (a filled cell that the solver says must be blank).

If the user has a mistake on the board, `h` undoes it and flashes a
warning instead of revealing a new cell.

## Layout

```
nonograms_tui/
  solver.py       line-propagation solver + hint API
  puzzles.py      .non parser + DB loader + clue-from-grid helper
  board.py        player state, undo stack, win detection
  app.py          Textual app, BoardView (ScrollView), modals
  tui.tcss        stylesheet

tests/
  qa.py           27 scenarios via Textual Pilot (end-to-end)
  solver_test.py  solver agreement check against every goal
  perf.py         render_line, full-frame, solver timings

vendor/
  nonogram-db/    git-cloned by `make bootstrap`; not committed
```

## Perf

```
[gnonograms-ubuntu]  35x35
  render_line (middle row)          mean  0.22 ms   median  0.26 ms
  full frame (all rows)             mean  5.49 ms   median  5.43 ms
```

Well under any human-visible budget. No ctypes tricks needed.

## Limitations

- Mono-color only. The `.non` format supports multi-color puzzles with
  letter-suffixed clue numbers (`3b,1d`); we coerce them to black for
  MVP and any non-`0` char in the `goal` string counts as filled.
- Seven of the 39 vendored puzzles aren't line-solvable by our simple
  propagator + fallback search within 15 s (`qnonograms-collection1-100`,
  `-105`, `-107`, `webpbn-16`, `-529`, `examples-sun`, `examples-tiger`).
  These still play fine; only the hint button has nothing to offer on
  them from a blank state. 32 puzzles work end-to-end with hints —
  comfortably above the 30-puzzle target.

## License

GPL-3.0, inherited from the vendored puzzle DB. See `LICENSE`.
