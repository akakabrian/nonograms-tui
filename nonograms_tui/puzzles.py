"""Puzzle loader — parses Steve Simpson's .non format from the
mikix/nonogram-db vendored tree (GPL-3.0).

We only support black-and-white puzzles. Multi-color clues (``3b,1d``
with color suffixes) are coerced to black (all numbers kept, colors
dropped). The ``goal`` string is interpreted as "any char != '0' is
filled" so multi-color goals still give us something checkable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# Root of the vendored puzzle database.
REPO = Path(__file__).resolve().parent.parent
VENDOR_DB = REPO / "vendor" / "nonogram-db" / "db"


@dataclass
class Puzzle:
    """Parsed .non puzzle. Clues are lists-of-lists of positive ints."""

    slug: str
    title: str
    author: str
    width: int
    height: int
    # rows[y] = clue numbers for row y (top→bottom)
    # columns[x] = clue numbers for col x (left→right)
    rows: list[list[int]]
    columns: list[list[int]]
    # Solution grid — True = filled, False = blank. May be None when the
    # source puzzle omitted a goal (rare). Used for win detection fallback.
    goal: list[list[bool]] | None = None
    source: str = ""
    license_str: str = ""

    @property
    def has_goal(self) -> bool:
        return self.goal is not None

    def goal_filled_count(self) -> int:
        if self.goal is None:
            return sum(sum(r) for r in self.rows)
        return sum(sum(1 for c in row if c) for row in self.goal)


# ---------- parser ----------

_QUOTED = re.compile(r'"([^"]*)"')


def _strip_colors(nums: str) -> list[int]:
    """Parse ``"3b,1d,2"`` → ``[3, 1, 2]``. Zero means no clue — drop it
    (some tools emit a single ``0`` for an empty row)."""
    out: list[int] = []
    for tok in nums.split(","):
        tok = tok.strip()
        if not tok:
            continue
        # Strip trailing non-digit color characters.
        digits = "".join(ch for ch in tok if ch.isdigit())
        if not digits:
            continue
        n = int(digits)
        if n > 0:
            out.append(n)
    return out


def parse_non(text: str, slug: str = "", source: str = "") -> Puzzle:
    """Parse a .non file body into a Puzzle.

    We're deliberately forgiving: unknown keys are ignored, blank lines
    are treated as section terminators (per the spec), and the
    rows/columns sections are whitespace- or comma-separated.
    """
    title = "Untitled"
    author = ""
    width = 0
    height = 0
    license_str = ""

    rows: list[list[int]] = []
    cols: list[list[int]] = []
    goal_str: str | None = None

    # Tokenise the file into (key, payload) pairs with multi-line
    # rows/columns sections. The format is very simple; a state machine
    # over lines is the clearest parse.
    section: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        # Keep blank lines — they terminate rows/columns sections.
        if not line.strip():
            section = None
            continue
        stripped = line.strip()
        # Leading keyword?
        first = stripped.split(None, 1)[0]
        lowered = first.lower()

        if section in ("rows", "columns"):
            # Inside a multi-line clue section.
            # First word is the row/col clue if it's numeric; but if it's
            # a new keyword we fall through.
            if _looks_like_clue(stripped):
                nums = _strip_colors(stripped)
                (rows if section == "rows" else cols).append(nums)
                continue
            # Fall through — treat as a new section header.
            section = None

        if lowered == "width":
            width = int(stripped.split()[1])
        elif lowered == "height":
            height = int(stripped.split()[1])
        elif lowered == "title":
            m = _QUOTED.search(stripped)
            title = m.group(1) if m else title
        elif lowered == "by":
            m = _QUOTED.search(stripped)
            author = m.group(1) if m else stripped[3:].strip()
        elif lowered == "license":
            parts = stripped.split(None, 1)
            license_str = parts[1] if len(parts) > 1 else ""
        elif lowered == "rows":
            section = "rows"
            # Same-line payload? "rows 2,3,1" — rare but valid.
            rest = stripped[len(first):].strip()
            if rest and _looks_like_clue(rest):
                rows.append(_strip_colors(rest))
        elif lowered == "columns":
            section = "columns"
            rest = stripped[len(first):].strip()
            if rest and _looks_like_clue(rest):
                cols.append(_strip_colors(rest))
        elif lowered == "goal":
            m = _QUOTED.search(stripped)
            if m:
                goal_str = m.group(1)
            else:
                parts = stripped.split(None, 1)
                goal_str = parts[1].strip() if len(parts) > 1 else None
        # Unknown keys are silently ignored per spec.

    # Normalise: some puzzles omit explicit "0" rows — if a row has no
    # clues in the section the author intended it as empty (clue = []).
    # Fill in missing rows/cols to match dimensions with empty clues.
    while len(rows) < height:
        rows.append([])
    while len(cols) < width:
        cols.append([])
    rows = rows[:height]
    cols = cols[:width]

    goal: list[list[bool]] | None = None
    if goal_str is not None and len(goal_str) >= width * height:
        # Any non-'0' char is filled. Multi-color goals → monochrome.
        flat = [c != "0" for c in goal_str[: width * height]]
        goal = [flat[y * width:(y + 1) * width] for y in range(height)]

    return Puzzle(
        slug=slug, title=title, author=author,
        width=width, height=height,
        rows=rows, columns=cols, goal=goal,
        source=source, license_str=license_str,
    )


def _looks_like_clue(s: str) -> bool:
    """True if the line is a comma/whitespace clue ("2,3" or "0" or "1 1")."""
    s = s.strip()
    if not s:
        return False
    # At least one digit; otherwise all allowed chars are digits, commas,
    # spaces, and color letters a-z (single chars).
    if not any(c.isdigit() for c in s):
        return False
    for tok in re.split(r"[,\s]+", s):
        if not tok:
            continue
        digits = "".join(c for c in tok if c.isdigit())
        suffix = tok[len(digits):]
        if not digits:
            return False
        if suffix and not re.fullmatch(r"[A-Za-z]?", suffix):
            return False
    return True


# ---------- puzzle pack ----------

# Order puzzles in the pack easy→hard. Our rough proxy is the total
# filled-cell count (smaller = easier) combined with grid area.
def _difficulty_key(p: Puzzle) -> tuple[int, int]:
    filled = p.goal_filled_count()
    return (p.width * p.height, filled)


_cache: list[Puzzle] | None = None


def list_puzzles() -> list[Puzzle]:
    """All puzzles available in the vendored DB, sorted easy→hard.
    Cached so repeated calls from tests don't reparse."""
    global _cache
    if _cache is not None:
        return _cache
    out: list[Puzzle] = []
    if not VENDOR_DB.exists():
        return out
    for path in sorted(VENDOR_DB.rglob("*.non")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            slug = _slug_for(path)
            src = str(path.relative_to(VENDOR_DB))
            p = parse_non(text, slug=slug, source=src)
            if p.width == 0 or p.height == 0:
                continue
            out.append(p)
        except Exception:
            # Malformed puzzle — skip with a warning in stderr so the
            # game can still boot on partial DB damage.
            import sys
            print(f"[puzzles] skip {path.name}: parse error", file=sys.stderr)
            continue
    out.sort(key=_difficulty_key)
    _cache = out
    return out


def _slug_for(path: Path) -> str:
    """Derive a stable human-friendly slug from a path under the DB."""
    rel = path.relative_to(VENDOR_DB)
    parts = list(rel.parts)
    parts[-1] = parts[-1].removesuffix(".non")
    return "-".join(parts).replace("/", "-")


def find_puzzle(slug: str) -> Puzzle | None:
    """Look up a puzzle by slug. Case-insensitive substring match as a
    fallback — `find_puzzle("dancer")` finds `webpbn-1` titled "Dancer"."""
    pool = list_puzzles()
    for p in pool:
        if p.slug == slug:
            return p
    lc = slug.lower()
    for p in pool:
        if lc in p.slug.lower() or lc in p.title.lower():
            return p
    return None


# ---------- generator (for tests + offline puzzles) ----------

def clues_from_grid(grid: Iterable[Iterable[bool]]) -> tuple[list[list[int]], list[list[int]]]:
    """Compute row + column clues from a known solution grid. Handy in
    tests and as a sanity-check for any puzzles we generate."""
    grid = [list(row) for row in grid]
    h = len(grid)
    w = len(grid[0]) if h else 0

    def line_clues(line: list[bool]) -> list[int]:
        out: list[int] = []
        run = 0
        for v in line:
            if v:
                run += 1
            else:
                if run:
                    out.append(run)
                run = 0
        if run:
            out.append(run)
        return out

    rows = [line_clues(grid[y]) for y in range(h)]
    cols = [line_clues([grid[y][x] for y in range(h)]) for x in range(w)]
    return rows, cols
