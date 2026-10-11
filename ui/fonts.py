"""Font assets shared by the Qt and Pygame frontends."""

from pathlib import Path

FONT_FAMILY = "Source Han Serif CN"
FONT_DIRECTORY = Path(__file__).resolve().parent / "assets" / "fonts"


def font_path(*, bold: bool = False) -> Path:
    weight = "Bold" if bold else "Regular"
    return FONT_DIRECTORY / f"SourceHanSerifCN-{weight}.otf"


def pygame_font(size: int, *, bold: bool = False):
    import pygame

    return pygame.font.Font(str(font_path(bold=bold)), size)
