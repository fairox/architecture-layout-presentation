"""Page geometry for presentation boards.

Board configs describe panels in millimetres from the page's upper-left corner,
with y increasing downward, because that is how a board is designed. Archicad
layouts use metres with the origin at the lower-left corner of the paper and y
increasing upward. Everything in this module is pure arithmetic, so it is
tested without Archicad.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    width_mm: float
    height_mm: float

    def point(self, x_mm: float, y_mm: float) -> dict[str, float]:
        """Design point (mm, top-left origin) to layout point (m, bottom-left origin)."""
        return {"x": x_mm / 1000.0, "y": (self.height_mm - y_mm) / 1000.0}

    def rect_origin(self, x_mm: float, y_mm: float, h_mm: float) -> dict[str, float]:
        """Lower-left corner, in layout metres, of a design rectangle."""
        return self.point(x_mm, y_mm + h_mm)

    def rect(self, x_mm: float, y_mm: float, w_mm: float, h_mm: float) -> list[dict[str, float]]:
        """Closed-free corner list (counter-clockwise from lower-left) of a design rectangle."""
        return [
            self.point(x_mm, y_mm + h_mm),
            self.point(x_mm + w_mm, y_mm + h_mm),
            self.point(x_mm + w_mm, y_mm),
            self.point(x_mm, y_mm),
        ]

    def centre(self, slot: dict[str, float]) -> tuple[float, float]:
        p = self.point(slot["x"] + slot["w"] / 2.0, slot["y"] + slot["h"] / 2.0)
        return p["x"], p["y"]


def circle_polygon(cx: float, cy: float, r: float, segments: int = 72) -> list[dict[str, float]]:
    """A true circle approximated by ``segments`` points, in the same units as the inputs."""
    return [
        {"x": cx + r * math.cos(2 * math.pi * i / segments),
         "y": cy + r * math.sin(2 * math.pi * i / segments)}
        for i in range(segments)
    ]


@dataclass(frozen=True)
class DrawingPlacement:
    """Where to create a Drawing so it shows ``model_clip`` centred in a slot at 1:``scale``.

    Archicad reports two points for a Drawing: ``position`` (the lower-left of
    its extent, which CreateDrawings takes) and ``pos`` (where the model origin
    lands on the paper). Probing the Drawing once at ratio 1 gives the offset
    between them; at another ratio the offset scales by the same ratio. That
    measured offset is what lets the clip polygon be written in paper
    coordinates before the Drawing exists.
    """

    ratio: float
    position: dict[str, float]
    clip: list[dict[str, float]] | None
    paper_size_m: tuple[float, float]


def place_drawing(
    *,
    view_scale: float,
    target_scale: float,
    probe_position: tuple[float, float],
    probe_pos: tuple[float, float],
    probe_bounds: dict[str, float],
    slot_centre: tuple[float, float],
    model_clip: tuple[float, float, float, float] | None = None,
    probe_ratio: float = 1.0,
) -> DrawingPlacement:
    """Compute ratio, creation position and paper-space clip for one Drawing.

    ``view_scale`` is the source view's own scale as a fraction (0.01 for 1:100);
    ``target_scale`` is the denominator wanted on paper (750 for 1:750).
    ``probe_ratio`` is the ratio the probe was created at. Probing at the final
    ratio is the most reliable, because fixed-size annotation (markers, grid
    bubbles) does not scale with the ratio and can shift the extent.
    """
    paper_per_model = 1.0 / target_scale
    ratio = paper_per_model / view_scale
    k = ratio / probe_ratio
    off_x = (probe_pos[0] - probe_position[0]) * k
    off_y = (probe_pos[1] - probe_position[1]) * k
    cx, cy = slot_centre

    if model_clip is None:
        w = (probe_bounds["xMax"] - probe_bounds["xMin"]) * k
        h = (probe_bounds["yMax"] - probe_bounds["yMin"]) * k
        return DrawingPlacement(ratio, {"x": cx - w / 2, "y": cy - h / 2}, None, (w, h))

    x0, y0, x1, y1 = model_clip
    origin_x = cx - (x0 + x1) / 2 * paper_per_model
    origin_y = cy - (y0 + y1) / 2 * paper_per_model
    clip = [
        {"x": origin_x + x * paper_per_model, "y": origin_y + y * paper_per_model}
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    ]
    position = {"x": origin_x - off_x, "y": origin_y - off_y}
    size = ((x1 - x0) * paper_per_model, (y1 - y0) * paper_per_model)
    return DrawingPlacement(ratio, position, clip, size)


def fit_ratio(bounds: dict[str, float], slot_w_m: float, slot_h_m: float) -> float:
    """Uniform ratio that fits an unscaled extent inside a slot (for non-scaled views)."""
    w = bounds["xMax"] - bounds["xMin"]
    h = bounds["yMax"] - bounds["yMin"]
    if w <= 0 or h <= 0:
        raise ValueError("Drawing has an empty extent.")
    return min(slot_w_m / w, slot_h_m / h)
