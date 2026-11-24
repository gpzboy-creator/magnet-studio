"""Arrange magnets on an A4 sheet with auto-orientation (best fit) and cut lines.

For each job we compare two orientations:
  A – magnets as given
  B – magnets rotated 90°
and pick the one that fits more magnets per page (e.g. 7.5x10 → 6 per page, 2x3, rotated).
"""
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from magnetstudio.core.sizes import A4_PX, DPI, cm_to_px

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
