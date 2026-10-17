"""Crop the project's renders and aerial photo into the PRES-01 image slots.

Crops keep each source's proportions (crop, never stretch) and match the
slot aspect ratios in board.json. Needs Pillow.

    python boards/pres-01/prepare_images.py "<Project-Workspace folder>" "<output images folder>"
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

# (output, source, centre x, centre y, aspect w/h, max output width)
CROPS = [
    ("PRES01_hero.jpg", "Phomolong_Scheme_B_-_With_2K_20261016054242.jpg", 0.47, 0.5, 258 / 376, 1400),
    ("PRES01_site.jpg", "SITE-PHOMOLONG_1.jpg", 0.40, 0.55, 250 / 158, 2400),
    ("PRES01_street.jpg", "2026_-_CAPITAL_LINK_CCCA.jpg", 0.55, 0.5, 132 / 85, 1100),
]
# (output, source, centre x, centre y, share of the short side, size px)
CIRCLES = [("PRES01_context_circle.jpg", "SITE-PHOMOLONG_1.jpg", 0.40, 0.60, 0.62, 1400)]


def crop(src: Path, dst: Path, cx: float, cy: float, aspect: float, max_w: int) -> None:
    im = Image.open(src).convert("RGB")
    W, H = im.size
    w, h = (int(H * aspect), H) if W / H > aspect else (W, int(W / aspect))
    x = int(max(0, min(W - w, cx * W - w / 2)))
    y = int(max(0, min(H - h, cy * H - h / 2)))
    im = im.crop((x, y, x + w, y + h))
    if w > max_w:
        im = im.resize((max_w, int(max_w * h / w)), Image.LANCZOS)
    im.save(dst, quality=90)


def circle(src: Path, dst: Path, cx: float, cy: float, share: float, size: int) -> None:
    """Square crop masked to a circle on white, for a round context diagram."""
    im = Image.open(src).convert("RGB")
    W, H = im.size
    side = int(min(W, H) * share)
    x, y = int(cx * W - side / 2), int(cy * H - side / 2)
    im = im.crop((x, y, x + side, y + side)).resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGB", (size, size), (255, 255, 255))
    out.paste(im, (0, 0), mask)
    out.save(dst, quality=90)


def main(workspace: str, out: str) -> None:
    src, dst = Path(workspace), Path(out)
    dst.mkdir(parents=True, exist_ok=True)
    for name, source, *args in CROPS:
        crop(src / source, dst / name, *args)
    for name, source, *args in CIRCLES:
        circle(src / source, dst / name, *args)
    print(f"Wrote {len(CROPS) + len(CIRCLES)} images to {dst}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
