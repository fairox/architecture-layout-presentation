"""Board packages: a board config that carries its own images.

The web configurator exports ``<layout id>.board.json``. It is an ordinary board
config (the same keys ``build_board`` reads) in which each image may also carry
``data``, a base64 ``data:`` URL of the already cropped picture. This module
checks a config before anything touches Archicad, writes the embedded images to
a folder, and compiles the ``PRES_Image2D`` picture object with Archicad's own
``LP_XMLConverter``, so a board can be built from that one file.

Nothing here talks to Archicad; it is tested without it.
"""

from __future__ import annotations

import base64
import binascii
import glob
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from archicad_toolkit.presentation.picture_object import PICTURE_OBJECT_XML

PACKAGE_FORMAT = "archicad-board"
PACKAGE_SUFFIX = ".board.json"
# Pens the builder refers to by name, and the panels and images it lays out around.
REQUIRED_PENS = ("charcoal", "grey", "cream", "bluegrey")
REQUIRED_PANELS = ("hero", "info", "principles", "explanation")
REQUIRED_IMAGES = ("hero", "context")
TYPE_KEYS = ("title", "location", "heading", "body", "caption", "credit")
MAX_IMAGE_BYTES = 25 * 1024 * 1024
SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\.(jpe?g|png)$", re.IGNORECASE)
GUID = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
DATA_URL = re.compile(r"^data:image/(jpeg|png);base64,(.*)$", re.DOTALL)
TOLERANCE_MM = 0.5


class BoardConfigError(ValueError):
    """The board config cannot be built; ``errors`` lists every problem found."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _rect_errors(where: str, r: Any, page: tuple[float, float]) -> list[str]:
    if not isinstance(r, dict) or not all(_num(r.get(k)) for k in ("x", "y", "w", "h")):
        return [f"{where} needs numeric x, y, w and h (mm)."]
    out = []
    if r["w"] <= 0 or r["h"] <= 0:
        out.append(f"{where} must have a positive width and height.")
    W, H = page
    if r["x"] < -TOLERANCE_MM or r["y"] < -TOLERANCE_MM or r["x"] + r["w"] > W + TOLERANCE_MM or r["y"] + r["h"] > H + TOLERANCE_MM:
        out.append(f"{where} runs off the {W:g} x {H:g} mm page.")
    return out


def _inside(r: dict[str, float], box: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = box
    return (r["x"] >= x0 - TOLERANCE_MM and r["y"] >= y0 - TOLERANCE_MM
            and r["x"] + r["w"] <= x1 + TOLERANCE_MM and r["y"] + r["h"] <= y1 + TOLERANCE_MM)


def drawing_paper_size_mm(d: dict[str, Any]) -> tuple[float, float] | None:
    """Paper size of a scaled drawing's model clip, or None when it is fitted or unclipped."""
    if d.get("fit") or not d.get("model_clip") or not _num(d.get("scale")) or d["scale"] <= 0:
        return None
    x0, y0, x1, y1 = d["model_clip"]
    return (x1 - x0) / d["scale"] * 1000.0, (y1 - y0) / d["scale"] * 1000.0


def validate_board(cfg: Any) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Any error means the builder would fail or misplace something."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(cfg, dict):
        return ["The board file is not a JSON object."], []

    lay = cfg.get("layout")
    if not isinstance(lay, dict):
        return ["Missing 'layout'."], []
    for key in ("id", "name", "subset", "master"):
        if not isinstance(lay.get(key), str) or not lay[key].strip():
            errors.append(f"layout.{key} must be a non-empty text.")
    if not (_num(lay.get("width_mm")) and _num(lay.get("height_mm")) and lay["width_mm"] > 0 and lay["height_mm"] > 0):
        return errors + ["layout.width_mm and layout.height_mm must be positive numbers."], warnings
    page = (float(lay["width_mm"]), float(lay["height_mm"]))
    if not isinstance(cfg.get("layer"), str) or not cfg["layer"].strip():
        errors.append("'layer' must name the board layer.")

    pens = cfg.get("pens")
    if not isinstance(pens, dict):
        errors.append("Missing 'pens'.")
        pens = {}
    seen: dict[int, str] = {}
    for name, p in pens.items():
        if not isinstance(p, dict):
            errors.append(f"Pen '{name}' must be an object.")
            continue
        if not isinstance(p.get("index"), int) or not 1 <= p["index"] <= 255:
            errors.append(f"Pen '{name}' needs an index from 1 to 255.")
        elif p["index"] in seen:
            errors.append(f"Pens '{seen[p['index']]}' and '{name}' both use pen {p['index']}.")
        else:
            seen[p["index"]] = name
        if not isinstance(p.get("hex"), str) or not HEX.match(p["hex"]):
            errors.append(f"Pen '{name}' needs a colour like #303637.")
        if not _num(p.get("width_mm")) or not 0 < p["width_mm"] <= 2:
            errors.append(f"Pen '{name}' needs a line weight between 0 and 2 mm.")
    for name in REQUIRED_PENS:
        if name not in pens:
            errors.append(f"The palette needs a pen named '{name}'.")

    sizes = cfg.get("type_mm") or {}
    for key in TYPE_KEYS:
        if not _num(sizes.get(key)) or sizes[key] <= 0:
            errors.append(f"type_mm.{key} must be a positive text height in mm.")

    border = cfg.get("border") or {}
    if not all(_num(border.get(k)) and border[k] >= 0 for k in ("inset_x_mm", "inset_y_mm", "weight_mm")):
        errors.append("border needs inset_x_mm, inset_y_mm and weight_mm.")
        inner = (0.0, 0.0, page[0], page[1])
    else:
        if border.get("pen") not in pens:
            errors.append(f"border.pen '{border.get('pen')}' is not in the palette.")
        inner = (border["inset_x_mm"], border["inset_y_mm"], page[0] - border["inset_x_mm"], page[1] - border["inset_y_mm"])
        if inner[2] <= inner[0] or inner[3] <= inner[1]:
            errors.append("The border insets leave no room on the page.")

    def check_rect(where: str, r: Any) -> bool:
        found = _rect_errors(where, r, page)
        errors.extend(found)
        if not found and not _inside(r, inner):
            warnings.append(f"{where} crosses the page border; the read-back check will flag it.")
        return not found

    panels = cfg.get("panels")
    if not isinstance(panels, dict):
        errors.append("Missing 'panels'.")
        panels = {}
    for name in REQUIRED_PANELS:
        if name not in panels:
            errors.append(f"Panel '{name}' is required by the builder.")
    for name, r in panels.items():
        errors.extend(_rect_errors(f"Panel '{name}'", r, page))

    images = cfg.get("images")
    if not isinstance(images, list):
        errors.append("'images' must be a list.")
        images = []
    keys, files = set(), set()
    for i, img in enumerate(images):
        where = f"Image '{img.get('key', i)}'" if isinstance(img, dict) else f"Image {i + 1}"
        if not isinstance(img, dict):
            errors.append(f"{where} must be an object.")
            continue
        if img.get("key") in keys:
            errors.append(f"{where} appears twice.")
        keys.add(img.get("key"))
        f = img.get("file")
        if not isinstance(f, str) or not SAFE_FILE.match(f):
            errors.append(f"{where} needs a plain .jpg or .png file name (letters, digits, - _ .).")
        elif f.lower() in files:
            errors.append(f"{where} reuses the file name {f}.")
        else:
            files.add(f.lower())
        check_rect(where, img)
        if "data" in img and not (isinstance(img["data"], str) and DATA_URL.match(img["data"][:64])):
            errors.append(f"{where} has embedded data that is not a JPEG or PNG data URL.")
    for key in REQUIRED_IMAGES:
        if key not in keys:
            errors.append(f"An image with key '{key}' is required by the builder.")
    hero = panels.get("hero")
    hero_img = next((i for i in images if isinstance(i, dict) and i.get("key") == "hero"), None)
    if isinstance(hero, dict) and hero_img and _num(hero.get("y")) and _num(hero_img.get("y")) and hero_img["y"] < hero["y"]:
        errors.append("The hero image starts above the hero panel, so the title band would have a negative height.")

    drawings = cfg.get("drawings")
    if not isinstance(drawings, list):
        errors.append("'drawings' must be a list.")
        drawings = []
    dkeys: set[str] = set()
    for i, d in enumerate(drawings):
        where = f"Drawing '{d.get('key', i)}'" if isinstance(d, dict) else f"Drawing {i + 1}"
        if not isinstance(d, dict):
            errors.append(f"{where} must be an object.")
            continue
        if not d.get("key") or d["key"] in dkeys:
            errors.append(f"{where} needs a unique key.")
        dkeys.add(d.get("key"))
        if not isinstance(d.get("name"), str) or not d["name"].strip():
            errors.append(f"{where} needs a view name.")
        if not isinstance(d.get("source"), str) or not GUID.match(d["source"]):
            errors.append(f"{where} needs the source view's navigator id (a GUID).")
        if not d.get("fit") and (not _num(d.get("scale")) or d["scale"] <= 0):
            errors.append(f"{where} needs a scale (e.g. 500 for 1:500) or fit: true.")
        clip = d.get("model_clip")
        if clip is not None and (not isinstance(clip, list) or len(clip) != 4 or not all(_num(v) for v in clip)
                                 or clip[2] <= clip[0] or clip[3] <= clip[1]):
            errors.append(f"{where} model_clip must be [x0, y0, x1, y1] in metres with x1 > x0 and y1 > y0.")
            clip = None
        if not isinstance(d.get("caption"), str):
            errors.append(f"{where} needs a caption (may be empty).")
        if check_rect(f"{where} slot", d.get("slot")) and clip is not None:
            size = drawing_paper_size_mm(d)
            if size and (size[0] > d["slot"]["w"] + TOLERANCE_MM or size[1] > d["slot"]["h"] + TOLERANCE_MM):
                warnings.append(f"{where} at 1:{d['scale']:g} needs {size[0]:.0f} x {size[1]:.0f} mm, "
                                f"more than its {d['slot']['w']:g} x {d['slot']['h']:g} mm slot.")

    for i, c in enumerate(cfg.get("captions") or []):
        if not isinstance(c, dict) or not isinstance(c.get("text"), str) or not (_num(c.get("x")) and _num(c.get("y"))):
            errors.append(f"Caption {i + 1} needs text, x and y.")
    for i, p in enumerate(cfg.get("placeholders") or []):
        where = f"Placeholder '{p.get('key', i)}'" if isinstance(p, dict) else f"Placeholder {i + 1}"
        if not isinstance(p, dict) or not all(isinstance(p.get(k), str) for k in ("key", "text", "caption")):
            errors.append(f"{where} needs key, text and caption.")
            continue
        check_rect(where, p)

    proj = cfg.get("project")
    if not isinstance(proj, dict):
        errors.append("Missing 'project' text.")
    else:
        for key in ("title_lines", "info_lines", "principles", "explanation"):
            v = proj.get(key)
            if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
                errors.append(f"project.{key} must be a list of lines.")
        if isinstance(proj.get("principles"), list) and not proj["principles"]:
            errors.append("project.principles needs at least one row.")
        for key in ("location", "credit"):
            if not isinstance(proj.get(key), str):
                errors.append(f"project.{key} must be text.")
    return errors, warnings


def require_valid(cfg: Any) -> list[str]:
    """Raise BoardConfigError on errors; return the warnings."""
    errors, warnings = validate_board(cfg)
    if errors:
        raise BoardConfigError(errors)
    return warnings


def has_embedded_images(cfg: dict[str, Any]) -> bool:
    return any(isinstance(i, dict) and i.get("data") for i in cfg.get("images", []))


def unpack_images(cfg: dict[str, Any], dest: Path) -> tuple[dict[str, Any], int]:
    """Write embedded images to ``dest``; return the config without image data, and the count written."""
    dest.mkdir(parents=True, exist_ok=True)
    written = 0
    images = []
    for img in cfg.get("images", []):
        img = dict(img)
        data = img.pop("data", None)
        if data:
            m = DATA_URL.match(data)
            name = img.get("file", "")
            if not m or not SAFE_FILE.match(name):
                raise BoardConfigError([f"Image '{img.get('key')}' has an unusable embedded file."])
            try:
                raw = base64.b64decode(m.group(2), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise BoardConfigError([f"Image '{img.get('key')}' data is not valid base64."]) from exc
            if len(raw) > MAX_IMAGE_BYTES:
                raise BoardConfigError([f"Image '{img.get('key')}' is larger than {MAX_IMAGE_BYTES // 2**20} MB."])
            (dest / Path(name).name).write_bytes(raw)
            written += 1
        images.append(img)
    return dict(cfg, images=images), written


def lp_xmlconverter_candidates() -> list[str]:
    """Places Archicad installs LP_XMLConverter, newest version first."""
    env = os.environ.get("LP_XMLCONVERTER")
    found = [env] if env else []
    if sys.platform.startswith("win"):
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), r"C:\Program Files"]
        for root in dict.fromkeys(roots):
            found += glob.glob(os.path.join(root, "GRAPHISOFT", "Archicad *", "LP_XMLConverter.exe"))
    elif sys.platform == "darwin":
        found += glob.glob("/Applications/GRAPHISOFT/Archicad */Archicad *.app/Contents/MacOS/"
                           "LP_XMLConverter.app/Contents/MacOS/LP_XMLConverter")
    return sorted(dict.fromkeys(found), key=lambda p: re.findall(r"Archicad (\d+)", p)[-1:] or [""], reverse=True)


def compile_picture_object(dest_dir: Path, converter: str | None = None) -> Path:
    """Write PRES_Image2D.xml to ``dest_dir`` and compile it to PRES_Image2D.gsm."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    xml = dest_dir / "PRES_Image2D.xml"
    gsm = dest_dir / "PRES_Image2D.gsm"
    xml.write_text(PICTURE_OBJECT_XML, encoding="utf-8")
    candidates = [converter] if converter else lp_xmlconverter_candidates()
    tool = next((c for c in candidates if c and os.path.exists(c)), None)
    if tool is None:
        raise FileNotFoundError(
            "LP_XMLConverter was not found. Give --gsm with a compiled PRES_Image2D.gsm, or set "
            "LP_XMLCONVERTER to the converter inside the Archicad install folder."
        )
    run = subprocess.run([tool, "xml2libpart", "-l", "UTF8", str(xml), str(gsm)], capture_output=True, text=True)
    if run.returncode != 0 or not gsm.exists():
        raise RuntimeError(f"LP_XMLConverter could not compile the picture object: {(run.stderr or run.stdout).strip()}")
    return gsm
