"""Arrange magnets on printer sheets, with cut lines.

Two layouts:
- build_grid_sheets – the main one: a sheet (e.g. 15x20 = 6x8" on a dye-sub printer) split into
  rows × columns cells inside mm margins (2×2 → four 7.5x10 magnets). Each magnet is rotated to the
  cell's orientation and fitted inside it (never cropped – frame text stays whole).
- build_a4_sheets – A4 with auto-orientation: compares magnets as given vs rotated 90° and picks
  the one that fits more per page (7.5x10 → 6 per page, 2x3, rotated).
"""
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from magnetstudio.core.sizes import A4_PX, DEFAULT_PAPER, DPI, cm_to_px, get_paper, mm_to_px

DEFAULT_MARGIN_CM = 0.3   # printer safe area around the page
DEFAULT_GAP_CM = 0.2      # space between magnets
CUT_LINE_COLOR = (200, 200, 200)  # light gray hairline
CUT_LINE_WIDTH = 1


@dataclass(frozen=True)
class GridPlan:
    cols: int
    rows: int
    rotated: bool
    cell_px: tuple[int, int]   # size of one magnet on the page (after rotation)
    offset_px: tuple[int, int]  # top-left of the centered grid
    gap_px: int

    @property
    def per_page(self) -> int:
        return self.cols * self.rows


def _fit(cell: tuple[int, int], margin: int, gap: int, page=A4_PX) -> tuple[int, int]:
    usable_w, usable_h = page[0] - 2 * margin, page[1] - 2 * margin
    cols = max(0, (usable_w + gap) // (cell[0] + gap))
    rows = max(0, (usable_h + gap) // (cell[1] + gap))
    return cols, rows


def plan_grid(item_px: tuple[int, int], margin_cm: float = DEFAULT_MARGIN_CM,
              gap_cm: float = DEFAULT_GAP_CM, allow_rotate: bool = True) -> GridPlan:
    """Choose the orientation that fits the most magnets on A4, and center the grid."""
    margin, gap = cm_to_px(margin_cm), cm_to_px(gap_cm)
    w, h = item_px
    candidates = [(False, (w, h))]
    if allow_rotate and w != h:
        candidates.append((True, (h, w)))

    best = None
    for rotated, cell in candidates:
        cols, rows = _fit(cell, margin, gap)
        # tie-break: prefer the original orientation (no rotation)
        if best is None or cols * rows > best[0] * best[1]:
            best = (cols, rows, rotated, cell)

    cols, rows, rotated, cell = best
    if cols * rows == 0:
        raise ValueError(f"Magnet {item_px} does not fit on A4")

    grid_w = cols * cell[0] + (cols - 1) * gap
    grid_h = rows * cell[1] + (rows - 1) * gap
    offset = ((A4_PX[0] - grid_w) // 2, (A4_PX[1] - grid_h) // 2)
    return GridPlan(cols, rows, rotated, cell, offset, gap)


def build_a4_sheets(images: list[Image.Image], margin_cm: float = DEFAULT_MARGIN_CM,
                    gap_cm: float = DEFAULT_GAP_CM, crop_marks: bool = True,
                    allow_rotate: bool = True) -> list[Image.Image]:
    """Place images (all the same size) on as many A4 pages as needed."""
    if not images:
        return []
    plan = plan_grid(images[0].size, margin_cm, gap_cm, allow_rotate)
    cells = [_cell_positions(plan, i) for i in range(plan.per_page)]

    sheets = []
    for start in range(0, len(images), plan.per_page):
        page = Image.new("RGB", A4_PX, "white")
        batch = images[start:start + plan.per_page]
        if crop_marks:
            _draw_cut_lines(page, cells[:len(batch)], plan.cell_px)
        for img, (x, y) in zip(batch, cells):
            if img.size != images[0].size:
                raise ValueError("All images on a sheet must be the same size")
            if plan.rotated:
                img = img.rotate(90, expand=True)
            page.paste(img, (x, y))
        page.info["dpi"] = (DPI, DPI)
        sheets.append(page)
    return sheets


def save_sheet(page: Image.Image, path: str | Path) -> Path:
    """Save a sheet with exact 300 DPI metadata."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    page.save(path, dpi=(DPI, DPI), quality=95)
    return path


def _cell_positions(plan: GridPlan, index: int) -> tuple[int, int]:
    c, r = index % plan.cols, index // plan.cols
    return (plan.offset_px[0] + c * (plan.cell_px[0] + plan.gap_px),
            plan.offset_px[1] + r * (plan.cell_px[1] + plan.gap_px))


def _draw_cut_lines(page: Image.Image, cells: list[tuple[int, int]], cell: tuple[int, int]) -> None:
    """Light gray hairlines along every cut edge, edge-to-edge.

    Drawn before pasting the photos, so they show only in the gaps between
    magnets and in the margins – never on top of a photo.
    """
    draw = ImageDraw.Draw(page)
    w, h = cell
    # one pixel outside each photo edge, so the line stays visible next to it
    xs = sorted({x - 1 for x, _ in cells} | {x + w for x, _ in cells})
    ys = sorted({y - 1 for _, y in cells} | {y + h for _, y in cells})
    for x in xs:
        draw.line([(x, 0), (x, page.height)], fill=CUT_LINE_COLOR, width=CUT_LINE_WIDTH)
    for y in ys:
        draw.line([(0, y), (page.width, y)], fill=CUT_LINE_COLOR, width=CUT_LINE_WIDTH)


# ================================================================ grid sheets (rows × columns)

MARK_WIDTHS = {"thin": 1, "medium": 3, "thick": 6}   # px at 300 DPI
DEFAULT_MARGINS_MM = (1.5, 1.5, 1.5, 1.5)           # top, bottom, right, left


@dataclass(frozen=True)
class SheetSpec:
    paper: str = DEFAULT_PAPER
    rows: int = 2
    cols: int = 2
    margins_mm: tuple[float, float, float, float] = DEFAULT_MARGINS_MM   # top, bottom, right, left
    gap_mm: float = 0.0
    crop_marks: bool = False
    mark_width: str = "medium"

    @classmethod
    def from_opts(cls, opts: dict) -> "SheetSpec":
        known = {k: v for k, v in (opts or {}).items() if k in cls.__dataclass_fields__}
        if "margins_mm" in known:
            known["margins_mm"] = tuple(float(m) for m in known["margins_mm"])
        return cls(**known)

    @property
    def per_sheet(self) -> int:
        return max(1, self.rows) * max(1, self.cols)


def sheet_cells(spec: SheetSpec) -> list[tuple[int, int, int, int]]:
    """Cell rectangles (x, y, w, h) in px, row by row, right-to-left order is the caller's business."""
    pw, ph = get_paper(spec.paper).size_px
    top, bottom, right, left = (mm_to_px(m) for m in spec.margins_mm)
    gap = mm_to_px(spec.gap_mm)
    rows, cols = max(1, spec.rows), max(1, spec.cols)
    cw = (pw - left - right - gap * (cols - 1)) / cols
    ch = (ph - top - bottom - gap * (rows - 1)) / rows
    if cw < 10 or ch < 10:
        raise ValueError("Margins / grid leave no room for the magnets")
    return [(round(left + c * (cw + gap)), round(top + r * (ch + gap)), int(cw), int(ch))
            for r in range(rows) for c in range(cols)]


def auto_grid(magnet_px: tuple[int, int], paper: str = DEFAULT_PAPER) -> tuple[int, int]:
    """Rows × columns that fit the most whole magnets on the paper (either orientation).
    7.5x10 on 15x20 → (2, 2)."""
    pw, ph = get_paper(paper).size_px
    best = (1, 1)
    for w, h in {magnet_px, magnet_px[::-1]}:
        # 2% tolerance: a 7.5x10 magnet is "the same" as a 7.6x10.15 cell of a 15.2x20.3 sheet
        cols, rows = int(pw * 1.02 // w), int(ph * 1.02 // h)
        if cols * rows > best[0] * best[1]:
            best = (max(1, rows), max(1, cols))
    return best


def fit_into_cell(img: Image.Image, cell_w: int, cell_h: int) -> Image.Image:
    """Rotate to the cell's orientation, then scale to fit inside it (aspect kept, nothing cut off)."""
    if (img.width > img.height) != (cell_w > cell_h) and img.width != img.height:
        img = img.rotate(90, expand=True)
    scale = min(cell_w / img.width, cell_h / img.height)
    if abs(scale - 1) > 1e-3:
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                         Image.Resampling.LANCZOS)
    return img


def build_grid_sheets(images: list[Image.Image], spec: SheetSpec | None = None, **opts) -> list[Image.Image]:
    """Magnets (any mix of portrait / landscape) → sheets of rows × cols cells."""
    spec = spec or SheetSpec.from_opts(opts)
    if not images:
        return []
    cells = sheet_cells(spec)
    paper_px = get_paper(spec.paper).size_px
    sheets = []
    for start in range(0, len(images), len(cells)):
        page = Image.new("RGB", paper_px, "white")
        batch = images[start:start + len(cells)]
        if spec.crop_marks:
            _draw_grid_marks(page, cells, MARK_WIDTHS.get(spec.mark_width, 3))
        for img, (x, y, w, h) in zip(batch, cells):
            fitted = fit_into_cell(img.convert("RGB"), w, h)
            page.paste(fitted, (x + (w - fitted.width) // 2, y + (h - fitted.height) // 2))
        page.info["dpi"] = (DPI, DPI)
        sheets.append(page)
    return sheets


def _draw_grid_marks(page: Image.Image, cells, width: int) -> None:
    """Cut lines along every cell edge, edge to edge. Drawn before the photos are pasted, so they show
    in the margins and gaps only."""
    draw = ImageDraw.Draw(page)
    xs = sorted({x for x, _, _, _ in cells} | {x + w for x, _, w, _ in cells})
    ys = sorted({y for _, y, _, _ in cells} | {y + h for _, y, _, h in cells})
    for x in xs:
        draw.line([(x, 0), (x, page.height)], fill=CUT_LINE_COLOR, width=width)
    for y in ys:
        draw.line([(0, y), (page.width, y)], fill=CUT_LINE_COLOR, width=width)
