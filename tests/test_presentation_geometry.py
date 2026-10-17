import math

import pytest

from archicad_toolkit.presentation.geometry import Page, circle_polygon, fit_ratio, place_drawing

PAGE = Page(600, 750)


def test_point_flips_y_and_converts_to_metres():
    assert PAGE.point(0, 0) == {"x": 0.0, "y": 0.75}
    assert PAGE.point(600, 750) == {"x": 0.6, "y": 0.0}


def test_rect_origin_is_lower_left():
    assert PAGE.rect_origin(171, 104, 376) == pytest.approx({"x": 0.171, "y": 0.27})


def test_circle_is_round():
    pts = circle_polygon(1.0, 2.0, 0.056)
    assert all(math.hypot(p["x"] - 1.0, p["y"] - 2.0) == pytest.approx(0.056) for p in pts)


def test_place_drawing_centres_model_clip_at_true_scale():
    # Numbers measured live: a 1:100 plan probed at ratio 1 at (0.1, 0.1)
    # reported its model origin at (0.4718, 0.5263).
    slot = {"x": 444, "y": 33.75, "w": 123, "h": 75}
    p = place_drawing(
        view_scale=0.01, target_scale=750,
        probe_position=(0.1, 0.1), probe_pos=(0.4718, 0.5263),
        probe_bounds={"xMin": 0.1, "yMin": 0.1, "xMax": 2.06, "yMax": 1.06},
        slot_centre=PAGE.centre(slot), model_clip=(-2, -4, 84.5, 37.5),
    )
    assert p.ratio == pytest.approx(100 / 750)
    w, h = p.paper_size_m
    assert w == pytest.approx(86.5 / 750)
    assert h == pytest.approx(41.5 / 750)
    xs = [c["x"] for c in p.clip]
    ys = [c["y"] for c in p.clip]
    cx, cy = PAGE.centre(slot)
    assert (min(xs) + max(xs)) / 2 == pytest.approx(cx)
    assert (min(ys) + max(ys)) / 2 == pytest.approx(cy)


def test_place_drawing_probe_at_final_ratio_uses_offset_unscaled():
    p = place_drawing(
        view_scale=0.01, target_scale=750, probe_ratio=100 / 750,
        probe_position=(0.0, 0.0), probe_pos=(0.05, 0.06),
        probe_bounds={"xMin": 0, "yMin": 0, "xMax": 0.2, "yMax": 0.1},
        slot_centre=(0.3, 0.3), model_clip=(0, 0, 75, 30),
    )
    origin_x = 0.3 - 37.5 / 750
    assert p.position["x"] == pytest.approx(origin_x - 0.05)
    assert p.clip[0]["x"] == pytest.approx(origin_x)


def test_place_drawing_without_clip_centres_extent():
    p = place_drawing(
        view_scale=0.01, target_scale=500,
        probe_position=(0, 0), probe_pos=(0.1, 0.1),
        probe_bounds={"xMin": 0, "yMin": 0, "xMax": 0.5, "yMax": 0.3},
        slot_centre=(0.1, 0.2),
    )
    assert p.clip is None
    assert p.paper_size_m == pytest.approx((0.1, 0.06))
    assert p.position == pytest.approx({"x": 0.05, "y": 0.17})


def test_fit_ratio_keeps_aspect():
    assert fit_ratio({"xMin": 0, "yMin": 0, "xMax": 1.5, "yMax": 0.8}, 0.132, 0.055) == pytest.approx(0.055 / 0.8)
    with pytest.raises(ValueError):
        fit_ratio({"xMin": 0, "yMin": 0, "xMax": 0, "yMax": 1}, 1, 1)
