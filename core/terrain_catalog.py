"""Map presentation metadata; collision and simulation rules remain separate."""

from __future__ import annotations


MAP_STYLES = ("tactical", "valley", "river")

_MAP_PRESENTATIONS = {
    "tactical": {"title": "战术网格", "background": "", "landmarks": ()},
    "valley": {
        "title": "山区河谷",
        "background": "terrain_valley.png",
        # Reference artwork is 1536 × 1024; store proportions for any map size.
        "landmarks": (
            ("青岚湖", "lake", 875 / 1536, 158 / 1024),
            ("河谷镇", "town", 546 / 1536, 484 / 1024),
            ("东岸镇", "town", 1084 / 1536, 492 / 1024),
            ("河谷大桥", "bridge", 739 / 1536, 398 / 1024),
            ("南谷桥", "bridge", 615 / 1536, 679 / 1024),
            ("河谷机场", "airfield", 1288 / 1536, 722 / 1024),
            ("西岸农田", "farmland", 385 / 1536, 634 / 1024),
            ("东岸农田", "farmland", 977 / 1536, 458 / 1024),
        ),
    },
    "river": {
        "title": "河谷城镇",
        "background": "terrain_river.png",
        "landmarks": (
            ("西河镇", "town", 0.24, 0.33),
            ("东河镇", "town", 0.75, 0.63),
            ("中央大桥", "bridge", 0.50, 0.45),
            ("南岸桥", "bridge", 0.55, 0.72),
            ("西岸田野", "farmland", 0.29, 0.73),
        ),
    },
}


def map_presentation(style: str, width: float, height: float) -> dict:
    """Return fresh QML-safe metadata with landmarks in world coordinates."""
    if not isinstance(style, str) or style not in MAP_STYLES:
        raise ValueError("地图样式必须为 tactical、valley 或 river")
    presentation = _MAP_PRESENTATIONS[style]
    return {
        "title": presentation["title"],
        "background": presentation["background"],
        "landmarks": [
            {"name": name, "kind": kind, "x": x_ratio * width, "y": y_ratio * height}
            for name, kind, x_ratio, y_ratio in presentation["landmarks"]
        ],
        "routes": [],
    }
