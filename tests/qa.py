"""Headless QA driver for nonograms-tui.

Runs each scenario in a fresh `NonogramsApp` via `App.run_test()`, saves
an SVG screenshot, reports pass/fail. Exit code = number of failures.

    python -m tests.qa            # run all
    python -m tests.qa cursor     # subset by substring match
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from nonograms_tui import solver
from nonograms_tui.app import BoardView, NonogramsApp
from nonograms_tui.board import CROSSED, EMPTY, FILLED, Board
from nonograms_tui.puzzles import Puzzle, find_puzzle, list_puzzles

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

# Fixed seed / slug so scenarios are deterministic.
DEFAULT_SLUG = "webpbn-1"  # the classic 5x10 dancer — fast, small.


@dataclass
class Scenario:
    name: str
    fn: Callable[[NonogramsApp, Any], Awaitable[None]]


# ---------- helpers ----------

def cell(app: NonogramsApp, x: int, y: int) -> int:
    return app.board.cells[y][x]


async def fill_goal(app: NonogramsApp, pilot: Any) -> None:
    """Set the board's cells to the puzzle goal directly (no timing
    dependency on keyboard input). Useful for victory checks."""
    goal = app.board.puzzle.goal
    assert goal is not None, "puzzle has no goal for fill_goal"
    for y in range(app.board.puzzle.height):
        for x in range(app.board.puzzle.width):
            want = FILLED if goal[y][x] else EMPTY
            app.board.set_cell(x, y, want)
    await pilot.pause()


# ---------- scenarios ----------

async def s_mount_clean(app, pilot):
    assert app.board_view is not None
    assert app.status_panel is not None
    assert app.controls_panel is not None
    assert app.board is not None
    assert app.board.puzzle.slug == DEFAULT_SLUG
    assert app.board.puzzle.width > 0
    assert app.board.puzzle.height > 0


async def s_cursor_starts_origin(app, pilot):
    assert app.board_view.cursor_x == 0, app.board_view.cursor_x
    assert app.board_view.cursor_y == 0, app.board_view.cursor_y


async def s_cursor_moves(app, pilot):
    await pilot.press("right", "right", "down")
    assert app.board_view.cursor_x == 2, app.board_view.cursor_x
    assert app.board_view.cursor_y == 1, app.board_view.cursor_y


async def s_cursor_clamps(app, pilot):
    w = app.board.puzzle.width
    h = app.board.puzzle.height
    for _ in range(w + 10):
        await pilot.press("right")
    assert app.board_view.cursor_x == w - 1, app.board_view.cursor_x
    for _ in range(h + 10):
        await pilot.press("down")
    assert app.board_view.cursor_y == h - 1, app.board_view.cursor_y
    for _ in range(w + h + 10):
        await pilot.press("left")
        await pilot.press("up")
    assert app.board_view.cursor_x == 0, app.board_view.cursor_x
    assert app.board_view.cursor_y == 0, app.board_view.cursor_y


async def s_space_fills(app, pilot):
    assert cell(app, 0, 0) == EMPTY
    await pilot.press("space")
    assert cell(app, 0, 0) == FILLED
    await pilot.press("space")
    assert cell(app, 0, 0) == EMPTY


async def s_cross_marks(app, pilot):
    await pilot.press("x")
    assert cell(app, 0, 0) == CROSSED
    await pilot.press("x")
    assert cell(app, 0, 0) == EMPTY


async def s_clear_cell(app, pilot):
    await pilot.press("space")
    assert cell(app, 0, 0) == FILLED
    await pilot.press("c")
    assert cell(app, 0, 0) == EMPTY


async def s_undo_reverses_fill(app, pilot):
    await pilot.press("space")
    assert cell(app, 0, 0) == FILLED
    await pilot.press("u")
    assert cell(app, 0, 0) == EMPTY


async def s_restart_clears_board(app, pilot):
    await pilot.press("space", "right", "space", "down", "space")
    filled_before = sum(1 for row in app.board.cells for c in row if c == FILLED)
    assert filled_before == 3, filled_before
    await pilot.press("r")
    await pilot.pause()
    filled_after = sum(1 for row in app.board.cells for c in row if c == FILLED)
    assert filled_after == 0, filled_after


async def s_render_produces_nonempty_strip(app, pilot):
    """render_line must return a usable Strip for a typical visible row."""
    # The column-clue gutter is at y=0..col_clue_height-1; grab the first
    # grid row.
    scroll_y = int(app.board_view.scroll_offset.y)
    y = app.board_view._col_clue_height - scroll_y
    strip = app.board_view.render_line(y)
    segments = list(strip)
    assert len(segments) > 0, "render_line returned empty strip"
    text = "".join(seg.text for seg in segments)
    # Should at least contain the row clue digit(s) for row 0.
    clues = app.board.puzzle.rows[0]
    if clues:
        assert str(clues[0]) in text, f"row clue {clues[0]} missing: {text!r}"


async def s_clue_gutter_renders(app, pilot):
    """Top gutter row must show column-clue digits for at least one column."""
    strip = app.board_view.render_line(0)
    text = "".join(seg.text for seg in list(strip))
    # Some column clue digit should appear.
    any_digit = any(ch.isdigit() for ch in text)
    assert any_digit, f"no digits in column gutter row 0: {text!r}"


async def s_win_detection_fires_on_goal_fill(app, pilot):
    await fill_goal(app, pilot)
    assert app.board.won, "board not marked as won after filling to goal"


async def s_crosses_do_not_affect_win(app, pilot):
    """Filling correctly plus some extra crosses still counts as a win."""
    goal = app.board.puzzle.goal
    assert goal is not None
    for y in range(app.board.puzzle.height):
        for x in range(app.board.puzzle.width):
            if goal[y][x]:
                app.board.set_cell(x, y, FILLED)
            else:
                app.board.set_cell(x, y, CROSSED)
    assert app.board.won


async def s_victory_logs_message(app, pilot):
    await fill_goal(app, pilot)
    app._check_victory()
    assert app.status_panel.won_at is not None


async def s_hint_fills_a_forced_cell(app, pilot):
    """Hint action must set a correct cell. Pick a puzzle where the solver
    can deduce something on an empty board."""
    filled_before = sum(
        1 for row in app.board.cells for c in row if c == FILLED
    )
    crossed_before = sum(
        1 for row in app.board.cells for c in row if c == CROSSED
    )
    app.action_hint()
    await pilot.pause()
    filled_after = sum(
        1 for row in app.board.cells for c in row if c == FILLED
    )
    crossed_after = sum(
        1 for row in app.board.cells for c in row if c == CROSSED
    )
    delta = (filled_after - filled_before) + (crossed_after - crossed_before)
    assert delta >= 1, f"hint did not change any cell ({delta})"


async def s_hint_cell_matches_goal(app, pilot):
    """Whatever cell the hint set, must match the goal."""
    goal = app.board.puzzle.goal
    assert goal is not None
    app.action_hint()
    await pilot.pause()
    for y in range(app.board.puzzle.height):
        for x in range(app.board.puzzle.width):
            if app.board.cells[y][x] == FILLED:
                assert goal[y][x], (
                    f"hint filled ({x},{y}) but goal says blank"
                )
            if app.board.cells[y][x] == CROSSED:
                assert not goal[y][x], (
                    f"hint crossed ({x},{y}) but goal says filled"
                )


async def s_hint_corrects_mistake(app, pilot):
    """Filling a cell that should be blank, then asking for a hint, must
    clear that cell (mistake correction path)."""
    goal = app.board.puzzle.goal
    assert goal is not None
    # Find a cell that the solver knows must be blank.
    solved = solver.solve(app.board.puzzle.rows, app.board.puzzle.columns)
    assert solved is not None
    bad = None
    for y in range(app.board.puzzle.height):
        for x in range(app.board.puzzle.width):
            if solved[y][x] == solver.EMPTY:
                bad = (x, y)
                break
        if bad:
            break
    assert bad is not None, "no forced-empty cell found"
    app.board.set_cell(bad[0], bad[1], FILLED)
    assert app.board.cells[bad[1]][bad[0]] == FILLED
    app.action_hint()
    await pilot.pause()
    # The hint routine should have cleared the wrong fill.
    assert app.board.cells[bad[1]][bad[0]] != FILLED, (
        f"hint did not clear mistake at {bad}"
    )


async def s_new_random_swaps_puzzle(app, pilot):
    before = app.board.puzzle.slug
    app.action_new_random()
    await pilot.pause()
    after = app.board.puzzle.slug
    assert before != after, f"new_random did not change puzzle ({before})"


async def s_help_screen_opens_and_closes(app, pilot):
    await pilot.press("question_mark")
    await pilot.pause()
    assert len(app.screen_stack) >= 2, "help screen did not push"
    await pilot.press("escape")
    await pilot.pause()
    # Should be back to one screen.
    assert len(app.screen_stack) == 1, "help screen did not dismiss"


async def s_picker_opens(app, pilot):
    await pilot.press("L")
    await pilot.pause()
    assert len(app.screen_stack) >= 2, "picker did not open"
    await pilot.press("escape")
    await pilot.pause()
    assert len(app.screen_stack) == 1, "picker did not close"


async def s_mouse_click_fills(app, pilot):
    """Click on a grid cell: cursor moves, cell toggles."""
    # Screen-position of cell (2, 3): gutter + cell_x*CELL_W, col_height + cell_y.
    bv = app.board_view
    target_x = bv._row_clue_width + 2 * 2  # cell_x=2, CELL_W=2
    target_y = bv._col_clue_height + 3     # cell_y=3
    # Widget-relative offset (account for scroll — here scroll is 0).
    offset = (target_x - int(bv.scroll_offset.x),
              target_y - int(bv.scroll_offset.y))
    await pilot.click("BoardView", offset=offset)
    await pilot.pause()
    assert bv.cursor_x == 2, f"cursor_x={bv.cursor_x}"
    assert bv.cursor_y == 3, f"cursor_y={bv.cursor_y}"
    assert app.board.cells[3][2] == FILLED, (
        f"cell(2,3) = {app.board.cells[3][2]}, expected FILLED"
    )


async def s_mouse_right_click_crosses(app, pilot):
    bv = app.board_view
    target_x = bv._row_clue_width + 1 * 2
    target_y = bv._col_clue_height + 1
    offset = (target_x - int(bv.scroll_offset.x),
              target_y - int(bv.scroll_offset.y))
    await pilot.click("BoardView", offset=offset, button=3)
    await pilot.pause()
    assert app.board.cells[1][1] == CROSSED, (
        f"cell(1,1) = {app.board.cells[1][1]}, expected CROSSED"
    )


async def s_unknown_state_does_not_crash_render(app, pilot):
    """Robustness: inject an unexpected cell value and render_line must
    still return a Strip rather than KeyError."""
    # Temporarily sabotage one cell.
    saved = app.board.cells[0][0]
    try:
        # An out-of-range state; rendering should still work (or fall
        # through to EMPTY glyph).
        app.board.cells[0][0] = 99  # type: ignore[assignment]
        # GLYPH dict will KeyError if unguarded. We catch to confirm
        # behaviour — either it renders cleanly (preferred) or falls
        # through to a default; bug if it crashes.
        try:
            y = app.board_view._col_clue_height
            strip = app.board_view.render_line(y)
            assert len(list(strip)) > 0
        except KeyError:
            # Known brittleness — we'll harden in the robustness pass.
            raise AssertionError(
                "render_line KeyError on unexpected cell state"
            )
    finally:
        app.board.cells[0][0] = saved


async def s_retarget_board_switches_puzzle(app, pilot):
    pool = list_puzzles()
    other = next(p for p in pool if p.slug != app.board.puzzle.slug)
    app._setup_for(Board(other))
    await pilot.pause()
    assert app.board.puzzle.slug == other.slug
    assert app.board_view.board.puzzle.slug == other.slug
    # Cursor must not be out of bounds.
    assert 0 <= app.board_view.cursor_x < other.width
    assert 0 <= app.board_view.cursor_y < other.height


async def s_log_collapses_duplicates(app, pilot):
    """Logging the same message twice should collapse into one line with
    a ×N suffix rather than growing the log by 2."""
    app.message_log.clear()
    app._last_log_text = ""
    app._last_log_count = 0
    app.log_msg("hello world")
    app.log_msg("hello world")
    app.log_msg("hello world")
    await pilot.pause()
    lines = app.message_log.lines
    assert len(lines) == 1, f"expected 1 line with collapse, got {len(lines)}"


async def s_status_panel_updates(app, pilot):
    """Filling a cell that matches the goal should move the progress
    counter forward."""
    goal = app.board.puzzle.goal
    assert goal is not None
    # Find a cell where goal is True.
    target = None
    for y in range(app.board.puzzle.height):
        for x in range(app.board.puzzle.width):
            if goal[y][x]:
                target = (x, y)
                break
        if target:
            break
    assert target is not None
    before = app.board.progress()[0]
    app.board.set_cell(*target, FILLED)
    app.status_panel.refresh_panel()
    after = app.board.progress()[0]
    assert after == before + 1, f"progress {before} → {after}"


async def s_solver_agrees_with_board_on_win(app, pilot):
    """End-to-end: the solver's goal + the board's goal must agree. This
    prevents the class of bug where hints would disagree with win
    detection."""
    from nonograms_tui.puzzles import clues_from_grid
    goal = app.board.puzzle.goal
    assert goal is not None
    rr, cc = clues_from_grid(goal)
    assert rr == app.board.puzzle.rows
    assert cc == app.board.puzzle.columns


SCENARIOS: list[Scenario] = [
    Scenario("mount_clean", s_mount_clean),
    Scenario("cursor_starts_origin", s_cursor_starts_origin),
    Scenario("cursor_moves", s_cursor_moves),
    Scenario("cursor_clamps", s_cursor_clamps),
    Scenario("space_fills", s_space_fills),
    Scenario("cross_marks", s_cross_marks),
    Scenario("clear_cell", s_clear_cell),
    Scenario("undo_reverses_fill", s_undo_reverses_fill),
    Scenario("restart_clears_board", s_restart_clears_board),
    Scenario("render_produces_nonempty_strip", s_render_produces_nonempty_strip),
    Scenario("clue_gutter_renders", s_clue_gutter_renders),
    Scenario("win_detection_fires_on_goal_fill", s_win_detection_fires_on_goal_fill),
    Scenario("crosses_do_not_affect_win", s_crosses_do_not_affect_win),
    Scenario("victory_logs_message", s_victory_logs_message),
    Scenario("hint_fills_a_forced_cell", s_hint_fills_a_forced_cell),
    Scenario("hint_cell_matches_goal", s_hint_cell_matches_goal),
    Scenario("hint_corrects_mistake", s_hint_corrects_mistake),
    Scenario("new_random_swaps_puzzle", s_new_random_swaps_puzzle),
    Scenario("help_screen_opens_and_closes", s_help_screen_opens_and_closes),
    Scenario("picker_opens", s_picker_opens),
    Scenario("mouse_click_fills", s_mouse_click_fills),
    Scenario("mouse_right_click_crosses", s_mouse_right_click_crosses),
    Scenario("unknown_state_does_not_crash_render", s_unknown_state_does_not_crash_render),
    Scenario("retarget_board_switches_puzzle", s_retarget_board_switches_puzzle),
    Scenario("log_collapses_duplicates", s_log_collapses_duplicates),
    Scenario("status_panel_updates", s_status_panel_updates),
    Scenario("solver_agrees_with_board_on_win", s_solver_agrees_with_board_on_win),
]


# ---------- driver ----------

async def run_one(scn: Scenario) -> tuple[str, bool, str]:
    app = NonogramsApp(DEFAULT_SLUG)
    try:
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            try:
                await scn.fn(app, pilot)
            except AssertionError as e:
                app.save_screenshot(str(OUT / f"{scn.name}.FAIL.svg"))
                return (scn.name, False, f"AssertionError: {e}")
            except Exception as e:
                app.save_screenshot(str(OUT / f"{scn.name}.ERROR.svg"))
                return (scn.name, False,
                        f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            app.save_screenshot(str(OUT / f"{scn.name}.PASS.svg"))
            return (scn.name, True, "")
    except Exception as e:
        return (scn.name, False,
                f"harness error: {type(e).__name__}: {e}\n{traceback.format_exc()}")


async def main(pattern: str | None = None) -> int:
    scenarios = [s for s in SCENARIOS if not pattern or pattern in s.name]
    if not scenarios:
        print(f"no scenarios match {pattern!r}")
        return 2
    results = []
    for scn in scenarios:
        name, ok, msg = await run_one(scn)
        mark = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
        print(f"  {mark} {name}")
        if not ok:
            for line in msg.splitlines():
                print(f"      {line}")
        results.append((name, ok, msg))
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"\n{passed}/{len(results)} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    pattern = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(asyncio.run(main(pattern)))
