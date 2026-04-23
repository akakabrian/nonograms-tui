"""Perf baseline — hot paths for nonograms-tui.

Run:
    .venv/bin/python -m tests.perf

Targets:
- render_line on a medium puzzle (30x35) — expected < 1 ms/row
- full grid render (all rows) — expected < 30 ms / frame
- cursor move (triggers a refresh, measured as elapsed during one move)
- _row_satisfied / _column_satisfied hot calls
- solver line propagation per puzzle

Prints a table. Also records a baseline to tests/out/perf-baseline.txt
for later comparison.
"""

from __future__ import annotations

import time
from pathlib import Path
from statistics import mean, median

from nonograms_tui import solver
from nonograms_tui.app import NonogramsApp
from nonograms_tui.puzzles import find_puzzle


OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)


def _time_ms(fn, repeats: int = 50) -> tuple[float, float]:
    """Return (mean_ms, median_ms) over `repeats` invocations."""
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return mean(samples), median(samples)


def bench_solver_line_propagate() -> tuple[float, float]:
    """Solver inner loop — one propagation step on a 30-column line."""
    clues = (2, 3, 1, 2)
    known = [0] * 30
    from nonograms_tui.solver import _line_propagate
    return _time_ms(lambda: _line_propagate(clues, known[:]))


async def _make_app(slug: str) -> NonogramsApp:
    app = NonogramsApp(slug)
    return app


def bench_render_line(app: NonogramsApp) -> tuple[float, float]:
    """One render_line call on a mid-grid row."""
    bv = app.board_view
    y = bv._col_clue_height + app.board.puzzle.height // 2
    return _time_ms(lambda: bv.render_line(y), repeats=200)


def bench_full_frame(app: NonogramsApp) -> tuple[float, float]:
    """Render every row of the viewport once."""
    bv = app.board_view
    h = bv._total_height()
    def go():
        for y in range(h):
            bv.render_line(y)
    return _time_ms(go, repeats=30)


def bench_row_satisfied(app: NonogramsApp) -> tuple[float, float]:
    bv = app.board_view
    h = app.board.puzzle.height
    def go():
        for y in range(h):
            bv._row_satisfied(y)
    return _time_ms(go, repeats=50)


def bench_full_solve(slug: str) -> float:
    p = find_puzzle(slug)
    assert p is not None
    t0 = time.perf_counter()
    solver.solve(p.rows, p.columns)
    return (time.perf_counter() - t0) * 1000.0


async def run_all() -> None:
    lines: list[str] = []

    def row(label: str, mean_ms: float, med_ms: float) -> None:
        lines.append(f"  {label:<42}  mean {mean_ms:>8.3f} ms   median {med_ms:>8.3f} ms")

    lines.append("== Nonograms TUI — perf baseline ==")
    lines.append("")

    # Solver line propagate.
    m, md = bench_solver_line_propagate()
    row("solver._line_propagate (clues=4, len=30)", m, md)

    # App-level benchmarks on two sizes.
    for slug in ("webpbn-1", "gnonograms-ubuntu"):
        p = find_puzzle(slug)
        if p is None:
            continue
        app = NonogramsApp(slug)
        async with app.run_test(size=(160, 60)) as pilot:
            await pilot.pause()
            bv = app.board_view
            lines.append("")
            lines.append(f"  [{slug}]  {p.width}x{p.height}  "
                         f"gutter row_w={bv._row_clue_width} "
                         f"col_h={bv._col_clue_height}")
            m, md = bench_render_line(app)
            row("render_line (middle row)", m, md)
            m, md = bench_full_frame(app)
            row("full frame (all rows)", m, md)
            m, md = bench_row_satisfied(app)
            row("_row_satisfied × all rows", m, md)

    # Solver end-to-end on the line-solvable puzzles.
    lines.append("")
    lines.append("  solver.solve end-to-end (ms):")
    for slug in (
        "webpbn-1", "webpbn-26167", "gnonograms-spade",
        "gnonograms-ubuntu", "gnonograms-wikimedia",
    ):
        if find_puzzle(slug) is None:
            continue
        t = bench_full_solve(slug)
        lines.append(f"    {slug:<32}  {t:>8.2f} ms")

    out = "\n".join(lines)
    print(out)
    (OUT / "perf-baseline.txt").write_text(out + "\n")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_all())
