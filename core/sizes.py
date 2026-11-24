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


def get_size(key: str) -> MagnetSize:
    try:
        return MAGNET_SIZES[key]
    except KeyError:
        raise ValueError(f"Unknown magnet size: {key!r}. Options: {list(MAGNET_SIZES)}")
