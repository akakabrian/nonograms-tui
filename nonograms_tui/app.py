"""Textual TUI for Nonograms."""

from __future__ import annotations

import random
import time

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Footer, Header, RichLog, Static

from . import solver
from .board import Board, CROSSED, EMPTY, FILLED
from .puzzles import Puzzle, find_puzzle, list_puzzles

# Each board cell is rendered as a 2-character slot so the grid reads as
# square at the typical 2:1 terminal aspect ratio.
CELL_W = 2

# Glyphs for the three player-cell states.
GLYPH = {
    EMPTY:   "  ",
    FILLED:  "██",
    CROSSED: "··",
}

# Styles per state. Kept dim/empty so that FILLED pops.
STYLE_EMPTY   = Style.parse("on rgb(24,26,32)")
STYLE_FILLED  = Style.parse("bold rgb(240,240,240) on rgb(240,240,240)")
STYLE_CROSSED = Style.parse("dim rgb(120,120,130) on rgb(24,26,32)")

# Cursor overlay: inverted amber so it always reads over any state.
STYLE_CURSOR  = Style.parse("bold rgb(30,20,0) on rgb(240,200,90)")
STYLE_CURSOR_ROW = Style.parse("on rgb(30,34,44)")  # lane highlight
STYLE_CURSOR_COL = Style.parse("on rgb(30,34,44)")

# Gridlines every 5 cells (Picross convention).
STYLE_GRIDLINE = Style.parse("rgb(120,140,180)")

# Clues.
STYLE_CLUE = Style.parse("rgb(200,210,230)")
STYLE_CLUE_BG = Style.parse("on rgb(18,20,28)")
STYLE_CLUE_DONE = Style.parse("dim rgb(110,120,140) on rgb(18,20,28)")

# Hint-reveal cell — a brief amber glow on hinted cells.
STYLE_HINT = Style.parse("bold rgb(255,220,120) on rgb(80,60,10)")


class BoardView(ScrollView):
    """Renders clue gutters + the grid. Supports mouse click + drag."""

    cursor_x: reactive[int] = reactive(0)
    cursor_y: reactive[int] = reactive(0)

    class CellAction(Message):
        """Posted when a cell is clicked or activated via keyboard."""
        def __init__(self, x: int, y: int, button: int) -> None:
            self.x, self.y, self.button = x, y, button
            super().__init__()

    def __init__(self, board: Board) -> None:
        super().__init__()
        self.board = board
        self._drag_last: tuple[int, int] | None = None
        self._drag_button: int = 0
        # Remember what action the drag is performing (fill-on-empty,
        # empty-on-fill) so the drag behaves consistently.
        self._drag_action: int | None = None
        # Cells whose hint-glow is still active — fades after N frames.
        self._hint_cells: set[tuple[int, int]] = set()
        self._row_clue_width: int = 0
        self._col_clue_height: int = 0
        self._recompute_gutters()
        self.virtual_size = Size(self._total_width(), self._total_height())

    # --- layout helpers -------------------------------------------------

    def _recompute_gutters(self) -> None:
        """Determine how many characters we need for the row/column clue
        gutters, based on the longest clue sequence in each direction."""
        p = self.board.puzzle
        # Row gutter: each row's clue string's length, plus one space
        # separator. Max of those.
        self._row_clue_width = max(
            (len(" ".join(str(n) for n in clues)) for clues in p.rows),
            default=1,
        ) + 1  # trailing space
        # Column gutter: height = longest col clue list.
        self._col_clue_height = max(
            (len(clues) for clues in p.columns),
            default=1,
        )

    def _total_width(self) -> int:
        return self._row_clue_width + self.board.puzzle.width * CELL_W

    def _total_height(self) -> int:
        return self._col_clue_height + self.board.puzzle.height

    def retarget_board(self, board: Board) -> None:
        """Swap to a new Board (puzzle switch) and reset scroll/cursor."""
        self.board = board
        self.cursor_x = 0
        self.cursor_y = 0
        self._hint_cells.clear()
        self._recompute_gutters()
        self.virtual_size = Size(self._total_width(), self._total_height())
        self.refresh()

    # --- rendering ------------------------------------------------------

    def render_line(self, y: int) -> Strip:
        """Textual calls this once per visible row. Our "row" y includes
        the column-clue gutter at the top and the grid rows below it.
        """
        width = self.size.width
        scroll_x, scroll_y = self.scroll_offset
        line_y = y + int(scroll_y)

        if line_y < 0 or line_y >= self._total_height():
            return Strip.blank(width)

        # Top gutter — column-clue row.
        if line_y < self._col_clue_height:
            return self._render_col_clue_line(line_y, width, int(scroll_x))

        # Grid row.
        tile_y = line_y - self._col_clue_height
        return self._render_grid_line(tile_y, width, int(scroll_x))

    def _render_col_clue_line(self, line_y: int, width: int, scroll_x: int) -> Strip:
        """Render one row of the column-clue gutter. The gutter is laid
        out bottom-up: the bottom row (line_y = col_height-1) shows the
        LAST clue of each column. Earlier rows show earlier clues,
        blank-padded on top."""
        p = self.board.puzzle
        cursor_x = self.cursor_x
        col_h = self._col_clue_height
        # Padded clue list indexed by row: we want clues aligned to the
        # bottom of the gutter, so row (col_h-1) = clue[-1].
        segments: list[Segment] = []
        # Empty block corresponding to the row-clue gutter in the top-left.
        segments.append(Segment(" " * self._row_clue_width, STYLE_CLUE_BG))
        # For each column, emit a 2-char slot holding the clue digit for
        # this gutter-row, or spaces.
        for x in range(p.width):
            clues = p.columns[x]
            # Align clues to the bottom.
            idx = line_y - (col_h - len(clues))
            if idx < 0:
                digit_text = "  "
            else:
                n = clues[idx]
                digit_text = f"{n:>2}" if n < 100 else f"{n:>3}"[:2]
            style = STYLE_CLUE_BG + STYLE_CLUE
            if x == cursor_x:
                style = STYLE_CURSOR_COL + STYLE_CLUE
            if self._column_satisfied(x):
                style = STYLE_CLUE_DONE
                if x == cursor_x:
                    style = style + STYLE_CURSOR_COL
            segments.append(Segment(digit_text, style))
        # Pad to the right.
        line_cells = self._row_clue_width + p.width * CELL_W
        if line_cells < width:
            segments.append(Segment(" " * (width - line_cells), STYLE_CLUE_BG))
        strip = Strip(segments, line_cells if line_cells >= width else width)
        if scroll_x:
            strip = strip.crop(scroll_x, scroll_x + width)
        return strip

    def _render_grid_line(self, tile_y: int, width: int, scroll_x: int) -> Strip:
        """Render one grid row: row-clue gutter, then cells."""
        p = self.board.puzzle
        b = self.board
        segments: list[Segment] = []

        # Row-clue gutter (right-aligned text in a fixed-width slot).
        clues = p.rows[tile_y]
        clue_text = " ".join(str(n) for n in clues) if clues else "0"
        pad = self._row_clue_width - len(clue_text) - 1
        pad_s = " " * max(0, pad)
        style = STYLE_CLUE_BG + STYLE_CLUE
        if tile_y == self.cursor_y:
            style = STYLE_CURSOR_ROW + STYLE_CLUE
        if self._row_satisfied(tile_y):
            style = STYLE_CLUE_DONE
            if tile_y == self.cursor_y:
                style = style + STYLE_CURSOR_ROW
        segments.append(Segment(pad_s + clue_text + " ", style))

        # Cells.
        for x in range(p.width):
            state = b.cells[tile_y][x]
            # Unknown cell state: render as empty rather than KeyError.
            # Keeps any future state-value bugs from crashing the paint
            # path. Magenta-looking default would be loud, but we opt
            # for silent EMPTY here since the state enum is tiny and
            # dev will notice board logic issues fast.
            glyph = GLYPH.get(state, GLYPH[EMPTY])
            # 5-cell gridline accent was considered but disabled — a pipe
            # between cells breaks the 2-char alignment and a tinted cell
            # background conflicts with the cursor/hint styles. The clue
            # gutter spacing already conveys the 5-block rhythm.
            if state == FILLED:
                cell_style = STYLE_FILLED
            elif state == CROSSED:
                cell_style = STYLE_CROSSED
            else:
                cell_style = STYLE_EMPTY
                # Subtly tint empty cells in the cursor's row/column so
                # the player can easily see where they are.
                if x == self.cursor_x:
                    cell_style = STYLE_CURSOR_COL
                if tile_y == self.cursor_y:
                    cell_style = STYLE_CURSOR_ROW if x != self.cursor_x else cell_style
            # Hint glow.
            if (x, tile_y) in self._hint_cells:
                cell_style = STYLE_HINT
                glyph = "▒▒" if state != FILLED else glyph
            # Cursor.
            if x == self.cursor_x and tile_y == self.cursor_y:
                cell_style = STYLE_CURSOR
                # Preserve glyph (so the cursor cell still shows state).
            segments.append(Segment(glyph, cell_style))

        total = self._total_width()
        if total < width:
            segments.append(Segment(" " * (width - total)))
        strip = Strip(segments, total if total >= width else width)
        if scroll_x:
            strip = strip.crop(scroll_x, scroll_x + width)
        return strip

    # --- derived facts -------------------------------------------------

    def _row_satisfied(self, y: int) -> bool:
        """Does the row's current FILLED pattern match its clue list?"""
        from .puzzles import clues_from_grid
        row = [c == FILLED for c in self.board.cells[y]]
        rr, _ = clues_from_grid([row])
        return rr[0] == self.board.puzzle.rows[y]

    def _column_satisfied(self, x: int) -> bool:
        from .puzzles import clues_from_grid
        col = [self.board.cells[y][x] == FILLED for y in range(self.board.puzzle.height)]
        rr, _ = clues_from_grid([col])
        return rr[0] == self.board.puzzle.columns[x]

    # --- cursor watchers -----------------------------------------------

    def watch_cursor_x(self, old: int, new: int) -> None:
        if not self.is_mounted:
            return
        self.refresh()
        self._scroll_to_cursor()

    def watch_cursor_y(self, old: int, new: int) -> None:
        if not self.is_mounted:
            return
        self.refresh()
        self._scroll_to_cursor()

    def _scroll_to_cursor(self) -> None:
        from textual.geometry import Region
        # Screen row of the cursor = col_clue_height + cursor_y
        screen_y = self._col_clue_height + self.cursor_y
        screen_x = self._row_clue_width + self.cursor_x * CELL_W
        self.scroll_to_region(
            Region(screen_x - 2, screen_y - 1, CELL_W + 4, 3),
            animate=False,
            force=True,
        )

    # --- mouse ----------------------------------------------------------

    def _screen_to_cell(self, event: events.MouseEvent) -> tuple[int, int] | None:
        """Convert a widget-local mouse event to a (cell_x, cell_y) tuple,
        or None if the click is in a clue gutter (no-op)."""
        ex = event.x + int(self.scroll_offset.x)
        ey = event.y + int(self.scroll_offset.y)
        if ey < self._col_clue_height:
            return None
        if ex < self._row_clue_width:
            return None
        cell_x = (ex - self._row_clue_width) // CELL_W
        cell_y = ey - self._col_clue_height
        if 0 <= cell_x < self.board.puzzle.width and 0 <= cell_y < self.board.puzzle.height:
            return (cell_x, cell_y)
        return None

    def on_mouse_down(self, event: events.MouseDown) -> None:
        spot = self._screen_to_cell(event)
        if spot is None:
            return
        x, y = spot
        self.cursor_x = x
        self.cursor_y = y
        self.capture_mouse()
        self._drag_last = spot
        self._drag_button = event.button
        cur = self.board.cells[y][x]
        if event.button == 3:
            # Right-click toggles cross; the drag action sets crosses on
            # empty cells, clears them on crossed cells.
            self._drag_action = CROSSED if cur != CROSSED else EMPTY
        else:
            # Left-click toggles fill.
            self._drag_action = FILLED if cur != FILLED else EMPTY
        self.post_message(self.CellAction(x, y, event.button))

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag_last is None:
            return
        spot = self._screen_to_cell(event)
        if spot is None or spot == self._drag_last:
            return
        x, y = spot
        self.cursor_x = x
        self.cursor_y = y
        if self._drag_action is not None:
            self.board.set_cell(x, y, self._drag_action)
            self.refresh()
        self._drag_last = spot

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag_last is not None:
            self._drag_last = None
            self._drag_action = None
            self.release_mouse()

    # --- hint glow ------------------------------------------------------

    def mark_hint(self, x: int, y: int) -> None:
        self._hint_cells.add((x, y))
        self.refresh()

    def clear_hints(self) -> None:
        if self._hint_cells:
            self._hint_cells.clear()
            self.refresh()


# ---------------- side panels ----------------

class StatusPanel(Static):
    def __init__(self) -> None:
        super().__init__()
        self.border_title = "PUZZLE"
        self.puzzle: Puzzle | None = None
        self.board: Board | None = None
        self.start_time: float = time.monotonic()
        self.won_at: float | None = None

    def set_board(self, board: Board) -> None:
        self.board = board
        self.puzzle = board.puzzle
        self.start_time = time.monotonic()
        self.won_at = None

    def refresh_panel(self) -> None:
        if self.puzzle is None or self.board is None:
            return
        p = self.puzzle
        right, total = self.board.progress()
        mistakes = self.board.mistakes()
        elapsed = (self.won_at or time.monotonic()) - self.start_time
        t = Text()
        t.append(f"{p.title}\n", style="bold")
        t.append(f"by {p.author or '?'}\n", style="dim")
        t.append(f"{p.width} × {p.height}\n\n")
        t.append("Progress  ")
        bar_w = 14
        filled = int(bar_w * right / max(total, 1))
        t.append("█" * filled, style="rgb(140,200,255)")
        t.append("░" * (bar_w - filled), style="rgb(60,70,90)")
        t.append(f"  {right}/{total}\n")
        if mistakes:
            t.append(f"Mistakes     {mistakes}\n", style="bold red")
        else:
            t.append("Mistakes      0\n", style="dim")
        m, s = divmod(int(elapsed), 60)
        t.append(f"Time        {m:>2d}:{s:02d}\n")
        if self.board.won:
            t.append("\n✓ SOLVED!\n", style="bold green")
        self.update(t)


class ControlsPanel(Static):
    def __init__(self) -> None:
        super().__init__()
        self.border_title = "CONTROLS"

    def refresh_panel(self) -> None:
        t = Text.from_markup(
            "[bold]Grid[/]\n"
            "  [bold]←↑→↓ / hjkl[/]   move\n"
            "  [bold]space / enter[/] fill\n"
            "  [bold]x[/]             cross\n"
            "  [bold]c[/]             clear\n\n"
            "[bold]Puzzle[/]\n"
            "  [bold]h[/]             hint\n"
            "  [bold]u[/]             undo\n"
            "  [bold]r[/]             restart\n"
            "  [bold]n[/]             new random\n"
            "  [bold]L[/]             pick from list\n"
            "  [bold]?[/]             help\n"
            "  [bold]q[/]             quit\n\n"
            "[dim]Mouse: left-fill, right-cross,\n"
            "drag to paint.[/]\n"
        )
        self.update(t)


# ---------------- help / pick screens ----------------

from textual.screen import ModalScreen


class HelpScreen(ModalScreen[None]):
    """Modal help screen. Dismiss with any key or click."""

    BINDINGS = [Binding("escape,q,question_mark,space,enter", "dismiss", "close", priority=True)]

    def compose(self) -> ComposeResult:
        yield Static(Text.from_markup(
            "[bold cyan]Nonograms — how to play[/]\n\n"
            "Numbers along a row or column describe consecutive groups of\n"
            "filled cells in that line. '3 1' means a run of 3 filled,\n"
            "then at least one blank, then a run of 1.\n\n"
            "Deduce which cells must be filled and which must be blank.\n"
            "[bold]Left-click / space[/] fills; [bold]right-click / x[/] crosses;\n"
            "[bold]c[/] clears. [bold]h[/] reveals one forced cell.\n\n"
            "Numbers turn [dim]grey[/] once their line is satisfied.\n\n"
            "[dim]press any key to close[/]"
        ), id="help-box")

    def on_key(self, event: events.Key) -> None:
        self.dismiss(None)

    def on_click(self, event: events.Click) -> None:
        self.dismiss(None)


class PickerScreen(ModalScreen[str | None]):
    """List-based puzzle picker. +/- moves selection; enter picks."""

    BINDINGS = [
        Binding("escape", "cancel", "close", priority=True),
        Binding("plus,j,down", "down", "down", priority=True),
        Binding("minus,k,up", "up", "up", priority=True),
        Binding("enter", "pick", "pick", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.puzzles = list_puzzles()
        self.selected: int = 0

    def compose(self) -> ComposeResult:
        yield Static(id="picker-box")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        t = Text()
        t.append("PICK A PUZZLE  (+/- move, enter pick, esc cancel)\n\n",
                 style="bold cyan")
        # Scrollable region — show 20 around selection.
        start = max(0, self.selected - 10)
        end = min(len(self.puzzles), start + 22)
        for i in range(start, end):
            p = self.puzzles[i]
            prefix = "▶ " if i == self.selected else "  "
            style = "bold reverse" if i == self.selected else ""
            t.append(f"{prefix}{p.slug:<22}  {p.width:>2}×{p.height:<2}  ",
                     style=style)
            t.append(f"{p.title}\n", style=style)
        box = self.query_one("#picker-box", Static)
        box.update(t)

    def action_down(self) -> None:
        if self.selected < len(self.puzzles) - 1:
            self.selected += 1
            self._refresh()

    def action_up(self) -> None:
        if self.selected > 0:
            self.selected -= 1
            self._refresh()

    def action_pick(self) -> None:
        if self.puzzles:
            self.dismiss(self.puzzles[self.selected].slug)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------- main app ----------------

class NonogramsApp(App):
    CSS_PATH = "tui.tcss"
    TITLE = "Nonograms — Terminal"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
        # Grid navigation (priority so the ScrollView doesn't eat arrows).
        Binding("up",    "move(0,-1)", "↑", show=False, priority=True),
        Binding("down",  "move(0,1)",  "↓", show=False, priority=True),
        Binding("left",  "move(-1,0)", "←", show=False, priority=True),
        Binding("right", "move(1,0)",  "→", show=False, priority=True),
        Binding("k", "move(0,-1)", show=False, priority=True),
        Binding("j", "move(0,1)",  show=False, priority=True),
        Binding("h_move", "move(-1,0)", show=False),  # 'h' is hint — see below
        Binding("l_move", "move(1,0)",  show=False),
        Binding("space", "fill", "fill", priority=True),
        Binding("enter", "fill", show=False, priority=True),
        Binding("x", "cross", "cross"),
        Binding("c", "clear_cell", "clear"),
        Binding("h", "hint", "hint"),
        Binding("u", "undo", "undo"),
        Binding("r", "restart", "restart"),
        Binding("n", "new_random", "new"),
        Binding("L", "pick", "pick"),
    ]

    def __init__(self, puzzle_slug: str | None = None) -> None:
        super().__init__()
        self.board_view: BoardView
        self.status_panel = StatusPanel()
        self.controls_panel = ControlsPanel()
        self.message_log = RichLog(
            id="log", highlight=False, markup=True, wrap=False, max_lines=200,
        )
        self.message_log.border_title = "LOG"
        self.flash_bar = Static(" ", id="flash-bar")
        self._flash_timer = None
        self._initial_slug = puzzle_slug
        self._last_log_text: str = ""
        self._last_log_count: int = 0
        self._hint_timer = None
        # Resolve the starting puzzle.
        self.board = self._pick_puzzle(puzzle_slug)
        self.board_view = BoardView(self.board)

    # --- puzzle selection ----------------------------------------------

    def _pick_puzzle(self, slug: str | None) -> Board:
        pool = list_puzzles()
        if not pool:
            raise RuntimeError(
                "No puzzles found. Run 'make bootstrap' to fetch the "
                "vendored nonogram-db."
            )
        if slug:
            p = find_puzzle(slug)
            if p is None:
                print(f"[nonograms] puzzle '{slug}' not found; picking random")
                p = random.choice(pool)
        else:
            # Prefer the smallest 5 puzzles when we randomise without a
            # slug — gives a gentler intro than a random 30×35.
            small = [q for q in pool if q.width * q.height <= 200]
            p = random.choice(small or pool)
        return Board(p)

    # --- layout ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            with Vertical(id="board-col"):
                yield self.board_view
                yield self.flash_bar
                yield self.message_log
            with Vertical(id="side"):
                yield self.status_panel
                yield self.controls_panel
        yield Footer()

    async def on_mount(self) -> None:
        self._setup_for(self.board)
        self.controls_panel.refresh_panel()
        self.log_msg(f"Loaded [bold]{self.board.puzzle.title}[/] "
                     f"({self.board.puzzle.width}×{self.board.puzzle.height})")
        self.log_msg("[dim]press ? for help[/]", level="info")
        # 1-second timer for the live clock / progress panel.
        self.set_interval(1.0, self._tick_status)

    def _setup_for(self, board: Board) -> None:
        self.board = board
        self.board_view.retarget_board(board)
        self.status_panel.set_board(board)
        self.status_panel.refresh_panel()
        self.board_view.border_title = (
            f"{board.puzzle.title}  ·  {board.puzzle.width}×{board.puzzle.height}"
        )
        self._update_flash()

    def _tick_status(self) -> None:
        self.status_panel.refresh_panel()

    # --- flash + log ---------------------------------------------------

    def flash(self, msg: str, seconds: float = 1.5) -> None:
        self.flash_bar.update(Text.from_markup(msg))
        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = self.set_timer(seconds, self._update_flash)

    def _update_flash(self) -> None:
        self._flash_timer = None
        x, y = self.board_view.cursor_x, self.board_view.cursor_y
        state = self.board.cells[y][x]
        label = {EMPTY: "empty", FILLED: "filled", CROSSED: "crossed"}[state]
        self.flash_bar.update(Text.from_markup(
            f"cursor ({x+1},{y+1})  [bold]{label}[/]"
        ))

    def log_msg(self, msg: str, level: str = "info") -> None:
        icons = {"info": "ℹ", "success": "✓", "warn": "⚠", "error": "✗",
                 "win": "★", "hint": "◆"}
        colors = {"info": "cyan", "success": "green", "warn": "yellow",
                  "error": "red", "win": "bold magenta", "hint": "yellow"}
        icon = icons.get(level, "ℹ")
        color = colors.get(level, "cyan")
        line = f"[{color}]{icon}[/] {msg}"
        if msg == self._last_log_text and self._last_log_count >= 1:
            self._last_log_count += 1
            try:
                self.message_log.lines.pop()
            except (IndexError, AttributeError):
                pass
            self.message_log.write(f"{line} [dim]×{self._last_log_count}[/]")
        else:
            self._last_log_text = msg
            self._last_log_count = 1
            self.message_log.write(line)

    # --- actions --------------------------------------------------------

    def action_move(self, dx: str, dy: str) -> None:
        b = self.board
        nx = max(0, min(b.puzzle.width - 1, self.board_view.cursor_x + int(dx)))
        ny = max(0, min(b.puzzle.height - 1, self.board_view.cursor_y + int(dy)))
        self.board_view.cursor_x = nx
        self.board_view.cursor_y = ny
        self._update_flash()

    def action_fill(self) -> None:
        x, y = self.board_view.cursor_x, self.board_view.cursor_y
        self.board.toggle_fill(x, y)
        self.board_view.clear_hints()
        self.board_view.refresh()
        self.status_panel.refresh_panel()
        self._update_flash()
        self._check_victory()

    def action_cross(self) -> None:
        x, y = self.board_view.cursor_x, self.board_view.cursor_y
        self.board.toggle_cross(x, y)
        self.board_view.clear_hints()
        self.board_view.refresh()
        self.status_panel.refresh_panel()
        self._update_flash()

    def action_clear_cell(self) -> None:
        x, y = self.board_view.cursor_x, self.board_view.cursor_y
        self.board.clear_cell(x, y)
        self.board_view.refresh()
        self.status_panel.refresh_panel()
        self._update_flash()

    def action_undo(self) -> None:
        if self.board.undo():
            self.board_view.refresh()
            self.status_panel.refresh_panel()
            self.flash("[dim]undo[/]", seconds=0.6)
        else:
            self.flash("[dim]nothing to undo[/]", seconds=0.6)

    def action_restart(self) -> None:
        self.board.reset()
        self.board_view.clear_hints()
        self.board_view.refresh()
        self.status_panel.set_board(self.board)
        self.status_panel.refresh_panel()
        self.flash("[yellow]restarted[/]")

    def action_new_random(self) -> None:
        pool = list_puzzles()
        choices = [p for p in pool if p.slug != self.board.puzzle.slug]
        if not choices:
            return
        new_p = random.choice(choices)
        self._setup_for(Board(new_p))
        self.log_msg(f"New puzzle: [bold]{new_p.title}[/] ({new_p.slug})")
        self.flash(f"[green]new: {new_p.title}[/]")

    def action_pick(self) -> None:
        def _after(slug: str | None) -> None:
            if not slug:
                return
            p = find_puzzle(slug)
            if p is None:
                self.flash("[red]puzzle not found[/]")
                return
            self._setup_for(Board(p))
            self.log_msg(f"Loaded [bold]{p.title}[/] ({p.slug})")
        self.push_screen(PickerScreen(), _after)

    def action_hint(self) -> None:
        user_grid = [
            [solver.FILLED if c == FILLED else
             solver.EMPTY if c == CROSSED else solver.UNKNOWN
             for c in row]
            for row in self.board.cells
        ]
        h = solver.hint_cell(self.board.puzzle.rows,
                             self.board.puzzle.columns, user_grid)
        if h is None:
            self.flash("[yellow]no hint available[/]", seconds=1.5)
            self.log_msg("Puzzle may be unsolvable from current state.",
                         level="warn")
            return
        x, y, state = h
        current = self.board.cells[y][x]
        # If the player had a wrong guess, undo it and flash a mistake
        # warning.
        if current == FILLED and state == solver.EMPTY:
            self.board.set_cell(x, y, EMPTY)
            self.flash(f"[red]✗ ({x+1},{y+1}) should be blank — cleared[/]",
                       seconds=2.5)
            self.log_msg(f"Corrected mistake at ({x+1},{y+1})", level="warn")
        else:
            # Reveal as FILLED or a cross (to help the player see blanks).
            new_state = FILLED if state == solver.FILLED else CROSSED
            self.board.set_cell(x, y, new_state)
            self.flash(f"[yellow]◆ hint: ({x+1},{y+1})[/]", seconds=2.0)
            self.log_msg(f"Hint at ({x+1},{y+1})", level="hint")
        self.board_view.mark_hint(x, y)
        # Auto-clear the hint glow after 3 s so it doesn't linger.
        if self._hint_timer is not None:
            self._hint_timer.stop()
        self._hint_timer = self.set_timer(3.0, self.board_view.clear_hints)
        self.status_panel.refresh_panel()
        self._check_victory()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    # --- victory --------------------------------------------------------

    def _check_victory(self) -> None:
        if self.board.won and self.status_panel.won_at is None:
            self.status_panel.won_at = time.monotonic()
            elapsed = self.status_panel.won_at - self.status_panel.start_time
            m, s = divmod(int(elapsed), 60)
            self.log_msg(
                f"SOLVED [bold]{self.board.puzzle.title}[/] in "
                f"[bold]{m}:{s:02d}[/] — press [bold]n[/] for a new puzzle.",
                level="win",
            )
            self.flash(f"[bold magenta]★ solved in {m}:{s:02d}![/]",
                       seconds=4.0)

    # --- mouse relay ----------------------------------------------------

    def on_board_view_cell_action(self, message: BoardView.CellAction) -> None:
        if message.button == 3:
            # on_mouse_down already set the drag_action to CROSSED (or
            # EMPTY from crossed); apply that.
            action = self.board_view._drag_action
            if action is not None:
                self.board.set_cell(message.x, message.y, action)
        else:
            action = self.board_view._drag_action
            if action is not None:
                self.board.set_cell(message.x, message.y, action)
        self.board_view.clear_hints()
        self.board_view.refresh()
        self.status_panel.refresh_panel()
        self._update_flash()
        self._check_victory()


def run(puzzle_slug: str | None = None) -> None:
    app = NonogramsApp(puzzle_slug)
    try:
        app.run()
    finally:
        import sys
        sys.stdout.write(
            "\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l\033[?25h"
        )
        sys.stdout.flush()
