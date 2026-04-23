"""Board state — player grid, undo stack, win detection."""

from __future__ import annotations

from dataclasses import dataclass, field

from .puzzles import Puzzle

EMPTY = 0
FILLED = 1
CROSSED = 2  # player marked "definitely not filled"


@dataclass
class Board:
    puzzle: Puzzle
    # Grid indexed [y][x]; 0=empty, 1=filled, 2=crossed
    cells: list[list[int]] = field(default_factory=list)
    # Stack of (x, y, old_value) for undo. Bounded to keep memory sane
    # in long sessions.
    _undo: list[tuple[int, int, int]] = field(default_factory=list)
    _undo_limit: int = 512
    won: bool = False

    def __post_init__(self) -> None:
        if not self.cells:
            self.reset()

    def reset(self) -> None:
        w, h = self.puzzle.width, self.puzzle.height
        self.cells = [[EMPTY] * w for _ in range(h)]
        self._undo.clear()
        self.won = False

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.puzzle.width and 0 <= y < self.puzzle.height

    def set_cell(self, x: int, y: int, value: int) -> bool:
        """Set a cell, recording undo. Returns True if state changed."""
        if not self.in_bounds(x, y):
            return False
        old = self.cells[y][x]
        if old == value:
            return False
        self._undo.append((x, y, old))
        if len(self._undo) > self._undo_limit:
            self._undo.pop(0)
        self.cells[y][x] = value
        self._check_win()
        return True

    def toggle_fill(self, x: int, y: int) -> bool:
        """Left-click semantics: EMPTY→FILLED, FILLED→EMPTY, CROSSED→FILLED."""
        if not self.in_bounds(x, y):
            return False
        cur = self.cells[y][x]
        new = EMPTY if cur == FILLED else FILLED
        return self.set_cell(x, y, new)

    def toggle_cross(self, x: int, y: int) -> bool:
        """Right-click / x-key: EMPTY→CROSSED, CROSSED→EMPTY, FILLED→CROSSED."""
        if not self.in_bounds(x, y):
            return False
        cur = self.cells[y][x]
        new = EMPTY if cur == CROSSED else CROSSED
        return self.set_cell(x, y, new)

    def clear_cell(self, x: int, y: int) -> bool:
        return self.set_cell(x, y, EMPTY)

    def undo(self) -> bool:
        if not self._undo:
            return False
        x, y, old = self._undo.pop()
        self.cells[y][x] = old
        self._check_win()
        return True

    # ---------- derivation ----------

    def filled_mask(self) -> list[list[bool]]:
        return [[c == FILLED for c in row] for row in self.cells]

    def _check_win(self) -> None:
        """A win requires the set of FILLED cells to match the puzzle.
        If the puzzle has an explicit goal we compare to that; otherwise
        we compare clues-derived-from-user-grid to puzzle clues.
        """
        if self.puzzle.has_goal:
            goal = self.puzzle.goal
            assert goal is not None
            for y in range(self.puzzle.height):
                for x in range(self.puzzle.width):
                    if (self.cells[y][x] == FILLED) != goal[y][x]:
                        self.won = False
                        return
            self.won = True
            return
        # Fallback: re-derive clues.
        from .puzzles import clues_from_grid
        rr, cc = clues_from_grid(self.filled_mask())
        self.won = (rr == self.puzzle.rows and cc == self.puzzle.columns)

    def progress(self) -> tuple[int, int]:
        """(filled_correctly, total_to_fill) — for the status panel.
        We define "filled_correctly" as FILLED cells that match the goal
        (if known); otherwise count all FILLED cells."""
        total = self.puzzle.goal_filled_count()
        if self.puzzle.has_goal:
            goal = self.puzzle.goal
            assert goal is not None
            right = 0
            for y in range(self.puzzle.height):
                for x in range(self.puzzle.width):
                    if self.cells[y][x] == FILLED and goal[y][x]:
                        right += 1
            return right, total
        return (sum(1 for row in self.cells for c in row if c == FILLED), total)

    def mistakes(self) -> int:
        """Count FILLED cells that should have been empty (only meaningful
        when the puzzle has a goal)."""
        if not self.puzzle.has_goal:
            return 0
        goal = self.puzzle.goal
        assert goal is not None
        bad = 0
        for y in range(self.puzzle.height):
            for x in range(self.puzzle.width):
                if self.cells[y][x] == FILLED and not goal[y][x]:
                    bad += 1
        return bad
