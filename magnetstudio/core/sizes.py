"""Magnet sizes and cm <-> pixel conversions. All pixel math lives here."""
from dataclasses import dataclass

DPI = 300
CM_PER_INCH = 2.54


def cm_to_px(cm: float, dpi: int = DPI) -> int:
    return round(cm / CM_PER_INCH * dpi)


def px_to_cm(px: int, dpi: int = DPI) -> float:
    return px / dpi * CM_PER_INCH


@dataclass(frozen=True)
class MagnetSize:
    key: str
    width_cm: float
    height_cm: float

    @property
    def label(self) -> str:
        w = f"{self.width_cm:g}"
        h = f"{self.height_cm:g}"
        return f"{w}x{h} cm" + (" (סטריפ)" if "strip" in self.key else "")

    @property
    def size_px(self) -> tuple[int, int]:
        return cm_to_px(self.width_cm), cm_to_px(self.height_cm)


MAGNET_SIZES: dict[str, MagnetSize] = {
    "7.5x10": MagnetSize("7.5x10", 7.5, 10),
    "10x10": MagnetSize("10x10", 10, 10),
    "15x20": MagnetSize("15x20", 15, 20),
    "5x15_strip": MagnetSize("5x15_strip", 5, 15),  # photo-booth strip
}

A4_CM = (21.0, 29.7)
A4_PX = (cm_to_px(A4_CM[0]), cm_to_px(A4_CM[1]))  # 2480 x 3508


@dataclass(frozen=True)
class PaperSize:
    """A printer sheet (portrait). Dye-sub event printers (e.g. Mitsubishi CP-D80DW) use 15x20 = 6x8"."""
    key: str
    width_cm: float
    height_cm: float
    inches: str = ""

    @property
    def label(self) -> str:
        return f"{self.width_cm:g}x{self.height_cm:g}" + (f' ({self.inches}")' if self.inches else "")

    @property
    def size_px(self) -> tuple[int, int]:
        return cm_to_px(self.width_cm), cm_to_px(self.height_cm)


PAPER_SIZES: dict[str, PaperSize] = {
    "15x20": PaperSize("15x20", 15.2, 20.3, "6x8"),
    "10x15": PaperSize("10x15", 10.2, 15.2, "4x6"),
    "13x18": PaperSize("13x18", 12.7, 17.8, "5x7"),
    "20x25": PaperSize("20x25", 20.3, 25.4, "8x10"),
    "A4": PaperSize("A4", A4_CM[0], A4_CM[1]),
}
DEFAULT_PAPER = "15x20"


def get_paper(key: str) -> PaperSize:
    try:
        return PAPER_SIZES[key]
    except KeyError:
        raise ValueError(f"Unknown paper size: {key!r}. Options: {list(PAPER_SIZES)}")


def mm_to_px(mm: float, dpi: int = DPI) -> int:
    return cm_to_px(mm / 10, dpi)


def get_size(key: str) -> MagnetSize:
    try:
        return MAGNET_SIZES[key]
    except KeyError:
        raise ValueError(f"Unknown magnet size: {key!r}. Options: {list(MAGNET_SIZES)}")
