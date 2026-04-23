"""End-to-end pty playtest for nonograms-tui.

Boots the real `nonograms.py` entry point under a pseudo-terminal via
pexpect, exercises the UI with keystrokes (puzzle pick, fill, cross,
undo, hint, quit), and writes per-step SVG snapshots built from
App.run_test (pty capture of Textual's ANSI is unreliable — we use the
pilot to export SVGs alongside).

Run:  .venv/bin/python -m tests.playtest
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pexpect

from nonograms_tui.app import NonogramsApp
from nonograms_tui.board import CROSSED, FILLED
from nonograms_tui.puzzles import Puzzle, find_puzzle, list_puzzles

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)


# --- pty boot-and-quit sanity check ---------------------------------

def pty_boot_smoke() -> bool:
    """Boot the app under a real pty, wait for the title, then send 'q'
    and confirm clean exit. If this fails the TUI is broken at startup.
    """
    repo = Path(__file__).resolve().parent.parent
    cmd = f"{repo}/.venv/bin/python {repo}/nonograms.py webpbn-1"
    child = pexpect.spawn(cmd, timeout=10, dimensions=(40, 120), encoding="utf-8")
    try:
        # Title bar should show "Nonograms".
        child.expect("Nonograms", timeout=8)
        # Give the app a beat to finish mounting, then quit.
        child.send("q")
        child.expect(pexpect.EOF, timeout=6)
        return True
    except pexpect.exceptions.ExceptionPexpect as e:
        print(f"[playtest] pty boot failed: {e}", file=sys.stderr)
        try:
            child.close(force=True)
        except Exception:
            pass
        return False


# --- driven playtest via Textual Pilot ------------------------------
# run_test drives a real app instance; SVG snapshots are the artifact
# we ship. Each step below matches one item in the task checklist.

async def _driven(out_prefix: str) -> int:
    """Interactive play: pick puzzle, fill, cross, undo, hint, win."""
    # A tiny puzzle makes winning trivial to confirm without guessing.
    small = _smallest_puzzle()
    app = NonogramsApp(puzzle_slug=small.slug)
    errors = 0

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        _snap(app, f"{out_prefix}_01_boot")

        # --- left-click to fill cell (0,0) ---
        bv = app.board_view
        top = bv._col_clue_height
        left = bv._row_clue_width
        await pilot.click("BoardView", offset=(left, top))
        await pilot.pause()
        _snap(app, f"{out_prefix}_02_left_click_fill")
        if app.board.cells[0][0] != FILLED:
            print("[playtest] left-click did not fill (0,0)", file=sys.stderr)
            errors += 1

        # --- right-click to cross cell (1,0) ---
        await pilot.click("BoardView", offset=(left + 2, top), button=3)
        await pilot.pause()
        _snap(app, f"{out_prefix}_03_right_click_cross")
        if app.board.cells[0][1] != CROSSED:
            print("[playtest] right-click did not cross (1,0)", file=sys.stderr)
            errors += 1

        # --- undo reverses the cross ---
        await pilot.press("u")
        await pilot.pause()
        _snap(app, f"{out_prefix}_04_undo")
        if app.board.cells[0][1] == CROSSED:
            print("[playtest] undo did not revert cross", file=sys.stderr)
            errors += 1

        # --- hint fires: it will either fill a forced cell, correct a
        # mistake, or mark a crossed square. Any of those is a valid hint
        # response — we just need the board state to change OR the log to
        # reflect hint activity.
        snap_before = [row[:] for row in app.board.cells]
        log_len_before = len(app.message_log.lines)
        await pilot.press("h")
        await pilot.pause()
        _snap(app, f"{out_prefix}_05_hint")
        snap_after = [row[:] for row in app.board.cells]
        changed = snap_before != snap_after
        logged = len(app.message_log.lines) > log_len_before
        if not (changed or logged):
            print("[playtest] hint had no observable effect", file=sys.stderr)
            errors += 1

        # --- win detection: fill the rest of the goal ---
        goal = small.goal
        assert goal is not None, "smallest puzzle must have a goal"
        for y in range(small.height):
            for x in range(small.width):
                want = FILLED if goal[y][x] else 0
                app.board.set_cell(x, y, want)
        app.board_view.refresh()
        app.status_panel.refresh_panel()
        app._check_victory()
        await pilot.pause()
        _snap(app, f"{out_prefix}_06_win")
        if not app.board.won:
            print(f"[playtest] win not detected on {small.slug}", file=sys.stderr)
            errors += 1

        # --- quit (gracefully) ---
        await pilot.press("q")
        await pilot.pause()

    return errors


def _smallest_puzzle() -> Puzzle:
    pool = list_puzzles()
    # Puzzles are sorted easy→hard; first with a goal and small area wins.
    for p in pool:
        if p.has_goal and p.width * p.height <= 50:
            return p
    # Fallback: webpbn-1 (5x10 dancer).
    p = find_puzzle("webpbn-1")
    assert p is not None
    return p


def _snap(app: NonogramsApp, name: str) -> None:
    path = OUT / f"playtest_{name}.svg"
    svg = app.export_screenshot(title=name)
    path.write_text(svg, encoding="utf-8")


def main() -> int:
    print("[playtest] pty boot smoke …", end=" ", flush=True)
    ok = pty_boot_smoke()
    print("ok" if ok else "FAIL")
    if not ok:
        return 1

    print("[playtest] driven walkthrough …")
    errors = asyncio.run(_driven("walkthrough"))
    if errors:
        print(f"[playtest] {errors} assertion failure(s)")
        return errors
    print(f"[playtest] all checks passed — snapshots in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
