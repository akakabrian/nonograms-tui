"""Rules text for the Rules modal."""

RULES_TEXT = """\
NONOGRAMS
=========

Solve Japanese picture logic puzzles by filling cells to match
the row and column hints.

Object
------
Fill every cell that's part of the hidden picture, and cross off
every cell that isn't, using only the numeric hints at the top
(column clues) and left (row clues).

Rules
-----
Each row and column has a sequence of numbers — each number is the
length of a contiguous run of filled cells in that line, separated
by at least one empty cell.

Example: a row labeled `3 2` means exactly one run of 3 filled
cells, then at least one empty cell, then exactly one run of 2
filled cells. No more, no less.

Strategy tips
-------------
  * Start with lines whose hints sum (+ gaps) to the full line
    length — these are forced.
  * Cross out cells you've proven empty; filled-vs-empty in
    adjacent lines often cascades.
  * When stuck, pick a plausible cell and propagate constraints;
    undo if a contradiction appears.

Controls summary
----------------
  ← → ↑ ↓     Move cursor
  Space       Fill current cell
  x           Mark current cell as empty (cross)
  z           Clear cell
  u           Undo
  R           Restart current puzzle
  p           Puzzle picker
  n           New random puzzle
  r           Rules (this screen)
  m           Music toggle
  ?           Help
  q           Quit
"""


def rules_text() -> str:
    return RULES_TEXT
