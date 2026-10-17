"""Build or rebuild a presentation board layout from a JSON config.

The board is made of ordinary, editable Archicad elements on one layout:
linked Drawings for plans, sections and 3D documents, Text elements, fills,
lines, and a small 2D picture object (``PRES_Image2D``) for renders and photos,
because Tapir has no command for placing external images on a layout.

Repeat runs are safe. Every element the builder creates is put on the board's
own layer and recorded in a manifest. The next run deletes only elements that
are both listed in that manifest and still on that layer, then rebuilds, so
hand-made additions on the layout are left alone.

Steps:
1. Find the layout by its layout ID, or create it (and its subset and master).
2. Make sure the board layer exists.
3. Embed the prepared images and the picture object in the embedded library.
4. Remove the previous run's elements (manifest + layer check).
5. Create fills, images, drawings, linework and text on the layout.
6. Move everything onto the board layer and switch drawing titles off.
7. Read every element back and check it against its intended slot.
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archicad_toolkit.client import ArchicadError, TapirClient
from archicad_toolkit.presentation.geometry import (
    Page,
    circle_polygon,
    fit_ratio,
    place_drawing,
)

PICTURE_OBJECT = "PRES_Image2D"
TOLERANCE_M = 0.0015
# Average glyph advance as a fraction of text height, measured on the default
# layout font (boxWidth of a 128-character line at 3.7 mm).
GLYPH_WIDTH = 0.68


@dataclass
class BoardResult:
    layout_database_id: str
    layout_navigator_id: str
    created: dict[str, list[str]] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    removed: int = 0

    @property
    def failed_checks(self) -> list[dict[str, Any]]:
        return [c for c in self.checks if not c["ok"]]

    def manifest(self) -> dict[str, Any]:
        return {
            "layoutDatabaseId": self.layout_database_id,
            "layoutNavigatorItemId": self.layout_navigator_id,
            "elements": self.created,
        }


# -- helpers -------------------------------------------------------------------


def _ids(result: dict[str, Any], what: str) -> list[dict[str, Any]]:
    """Element ids from a Create* response; raise if any item failed."""
    out = []
    for item in result.get("elements", []):
        if "elementId" not in item:
            raise ArchicadError(f"Creating {what} failed: {item.get('error')}")
        out.append(item["elementId"])
    return out


def _walk(node: dict[str, Any]):
    node = node.get("navigatorItem", node)
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)


def _tree(client: TapirClient, map_id: str) -> list[dict[str, Any]]:
    return list(_walk(client.tapir("GetNavigatorItemTree", {"navigatorMapId": map_id})["navigatorItemTree"]))


def _attribute_index(client: TapirClient, attribute_type: str, name: str) -> dict[str, Any] | None:
    for a in client.tapir("GetAttributesByType", {"attributeType": attribute_type}).get("attributes", []):
        if a.get("name") == name:
            return a
    return None


def _wrap(text: str, width_mm: float, height_mm: float) -> str:
    """Hard-wrap text for a column; average glyph width is GLYPH_WIDTH x height."""
    chars = max(10, int(width_mm / (height_mm * GLYPH_WIDTH)))
    return "\n".join(textwrap.fill(p, chars) if p else "" for p in text.split("\n"))


# -- layout --------------------------------------------------------------------


def find_layout(client: TapirClient, layout_id: str) -> tuple[str, str] | None:
    """(navigator item guid, database guid) of the layout whose number is ``layout_id``."""
    for node in _tree(client, "LayoutBook"):
        if node.get("type") != "LayoutItem":
            continue
        nav = node["navigatorItemId"]
        settings = client.tapir(
            "GetLayoutSettings", {"layoutDatabaseIds": [{"navigatorItemId": nav}]}
        )["layoutSettings"][0]
        if settings.get("customLayoutNumber") == layout_id:
            db = client.tapir("GetDatabaseIdFromNavigatorItemId", {"navigatorItemIds": [{"navigatorItemId": nav}]})
            return nav["guid"], db["databases"][0]["databaseId"]["guid"]
    return None


def ensure_layout(client: TapirClient, cfg: dict[str, Any], warnings: list[str]) -> tuple[str, str]:
    lay = cfg["layout"]
    found = find_layout(client, lay["id"])
    if found:
        return found
    subset = next(
        (n for n in _tree(client, "LayoutBook") if n.get("type") == "SubSetItem" and n.get("name") == lay["subset"]),
        None,
    )
    if subset is None:
        client.tapir("CreateLayoutSubset", {"subsetsData": [{"name": lay["subset"]}]})
        subset = next(
            (n for n in _tree(client, "LayoutBook") if n.get("type") == "SubSetItem" and n.get("name") == lay["subset"]),
            None,
        )
    client.tapir(
        "CreateLayout",
        {
            "layoutsData": [
                {
                    "masterLayoutName": lay["master"],
                    "layoutName": lay["name"],
                    "layoutParameters": {
                        "horizontalSize": lay["width_mm"], "verticalSize": lay["height_mm"],
                        "leftMargin": 0, "topMargin": 0, "rightMargin": 0, "bottomMargin": 0,
                        "customLayoutNumber": lay["id"], "customLayoutNumbering": True,
                        "doNotIncludeInNumbering": True, "displayMasterLayoutBelow": True,
                    },
                }
            ]
        },
    )
    found = find_layout(client, lay["id"])
    if not found:
        raise ArchicadError(f"Layout {lay['id']} was not found after creating it.")
    if subset is not None:
        client.tapir(
            "MoveNavigatorItem",
            {"navigatorItemIdToMove": {"guid": found[0]}, "parentNavigatorItemId": subset["navigatorItemId"]},
        )
    else:
        warnings.append(f"Subset '{lay['subset']}' could not be found; the layout sits at the book root.")
    return find_layout(client, lay["id"]) or found


def ensure_layer(client: TapirClient, name: str) -> int:
    attr = _attribute_index(client, "Layer", name)
    if attr is None:
        client.tapir("CreateLayers", {"layerDataArray": [{"name": name}], "overwriteExisting": False})
        attr = _attribute_index(client, "Layer", name)
    if attr is None:
        raise ArchicadError(f"Layer '{name}' could not be created.")
    return int(attr["index"])


def ensure_pens(client: TapirClient, cfg: dict[str, Any]) -> None:
    """Write the palette into otherwise unused pens of the layout pen table."""
    table = _attribute_index(client, "PenTable", cfg["pen_table"])
    if table is None:
        raise ArchicadError(f"Pen table '{cfg['pen_table']}' not found.")
    pens = []
    for name, p in cfg["pens"].items():
        h = p["hex"].lstrip("#")
        pens.append({
            "index": p["index"],
            "color": {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255},
            "width": p["width_mm"],
            "description": f"{cfg['layout']['id']} {name}",
        })
    client.tapir(
        "CreatePenTables",
        {"penTableDataArray": [{"attributeId": table["attributeId"], "name": cfg["pen_table"], "pens": pens}],
         "overwriteExisting": True},
    )


def embed_assets(client: TapirClient, cfg: dict[str, Any], assets_dir: Path, gsm: Path) -> None:
    folder = cfg["layout"]["id"]
    files = [{"inputPath": str(gsm.resolve()), "outputPath": f"{folder}/{gsm.name}", "type": "Object"}]
    for img in cfg["images"]:
        path = (assets_dir / img["file"]).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Prepared image missing: {path}")
        files.append({"inputPath": str(path), "outputPath": f"{folder}/{img['file']}", "type": "Pict"})
    result = client.tapir("AddFilesToEmbeddedLibrary", {"files": files, "overwriteExisting": True})
    bad = [f["outputPath"] for f, r in zip(files, result.get("executionResults", [])) if not r.get("success")]
    if bad:
        raise ArchicadError(f"Could not embed: {', '.join(bad)}")
    client.tapir("ReloadLibraries")


def remove_previous(client: TapirClient, manifest: dict[str, Any] | None, db: str, layer: int) -> int:
    """Delete last run's elements that are still on the board layer of this layout."""
    if not manifest or manifest.get("layoutDatabaseId") != db:
        return 0
    wanted = {g for guids in manifest.get("elements", {}).values() for g in guids}
    present = [e["elementId"] for e in client.tapir("GetAllElements").get("elements", [])]
    present = [e for e in present if e["guid"] in wanted]
    if not present:
        return 0
    details = client.tapir("GetDetailsOfElements", {"elements": [{"elementId": e} for e in present], "fields": ["layerIndex"]})
    ours = [e for e, d in zip(present, details["detailsOfElements"]) if int(d.get("layerIndex", -1)) == layer]
    if ours:
        client.tapir("DeleteElements", {"elements": [{"elementId": e} for e in ours]})
    return len(ours)


def ensure_presentation_views(client: TapirClient, cfg: dict[str, Any], board_layer: str) -> dict[str, str]:
    """Copy each drawing's source view into a board-only View Map folder with a quieter layer set.

    The project's own views are left as they are. Returns {source guid: board view guid}.
    """
    spec = cfg.get("presentation_views")
    if not spec:
        return {}
    layers = client.tapir("GetAttributesByType", {"attributeType": "Layer"})["attributes"]
    hidden_prefixes = tuple(spec["hide_layer_prefixes"])
    combo = [{"attributeId": a["attributeId"],
              "isHidden": a["name"] != board_layer and a["name"].strip().startswith(hidden_prefixes),
              "isLocked": False, "isWireframe": False, "intersectionGroupNr": 0}
             for a in layers]
    client.tapir("CreateLayerCombinations", {"layerCombinationDataArray": [{"name": spec["layer_combination"], "layers": combo}],
                                             "overwriteExisting": True})
    for name in spec.get("show_board_layer_in", []):
        attr = _attribute_index(client, "LayerCombination", name)
        if attr is None:
            continue
        current = client.tapir("GetLayerCombinations", {"attributes": [{"attributeId": attr["attributeId"]}]})
        entry = current["layerCombinations"][0]
        entry = entry.get("layerCombination", entry)
        board = _attribute_index(client, "Layer", board_layer)
        rows = [dict(l, isHidden=False) if l["attributeId"] == board["attributeId"] else l for l in entry["layers"]]
        client.tapir("CreateLayerCombinations", {"layerCombinationDataArray": [
            {"attributeId": attr["attributeId"], "name": name, "layers": rows}], "overwriteExisting": True})

    def view_map():
        return _tree(client, "PublicViewMap")

    folder = next((n for n in view_map() if n.get("type") == "FolderItem" and n.get("name") == spec["folder"]), None)
    if folder is None:
        folder = {"navigatorItemId": client.tapir("CreateViewMapFolder", {"folderName": spec["folder"]})["navigatorItemId"]}
    folder_id = folder["navigatorItemId"]["guid"]
    existing = {}
    for node in view_map():
        if node["navigatorItemId"]["guid"] == folder_id:
            existing = {c.get("navigatorItem", c)["name"]: c.get("navigatorItem", c)["navigatorItemId"]["guid"]
                        for c in node.get("children") or []}
    project_source = {n["navigatorItemId"]["guid"]: (n.get("sourceNavigatorItemId") or {}).get("guid")
                      for n in view_map()}
    mapping = {}
    for d in cfg["drawings"]:
        if d.get("fit"):
            continue
        name = d["name"]
        guid = existing.get(name)
        original = client.tapir("GetViewSettings", {"navigatorItemIds": [{"navigatorItemId": {"guid": d["source"]}}]})
        settings = dict(original["viewSettings"][0])
        if guid is None:
            # New views are made from the Project Map item behind the saved view, then
            # given the saved view's own settings with the board's layer combination.
            r = client.tapir("CreateViewsInViewMap", {"viewsData": [{
                "navigatorItemId": {"guid": project_source.get(d["source"]) or d["source"]},
                "parentNavigatorItemId": {"guid": folder_id}, "name": name}]})
            item = r["navigatorItems"][0]
            if "navigatorItemId" not in item:
                raise ArchicadError(f"Could not create board view {name}: {item.get('error')}")
            guid = item["navigatorItemId"]["guid"]
        settings["layerCombination"] = spec["layer_combination"]
        if spec.get("pen_set"):
            settings["penSetName"] = spec["pen_set"]
        res = client.tapir("SetViewSettings", {"navigatorItemIdsWithViewSettings": [{
            "navigatorItemId": {"guid": guid}, "viewSettings": settings}]})
        if not all(x.get("success") for x in res.get("executionResults", [])):
            raise ArchicadError(f"Could not set view settings of {name}: {res}")
        mapping[d["source"]] = guid
    return mapping


# -- build ---------------------------------------------------------------------


def build_board(
    client: TapirClient,
    cfg: dict[str, Any],
    *,
    assets_dir: Path,
    gsm: Path,
    manifest_path: Path,
) -> BoardResult:
    page = Page(cfg["layout"]["width_mm"], cfg["layout"]["height_mm"])
    pen = {k: v["index"] for k, v in cfg["pens"].items()}
    size = cfg["type_mm"]
    warnings: list[str] = []

    nav, db = ensure_layout(client, cfg, warnings)
    result = BoardResult(db, nav, warnings=warnings)
    layer = ensure_layer(client, cfg["layer"])
    ensure_pens(client, cfg)
    embed_assets(client, cfg, assets_dir, gsm)
    views = ensure_presentation_views(client, cfg, cfg["layer"])
    solid = _attribute_index(client, "Fill", cfg["solid_fill"])
    if solid is None:
        raise ArchicadError(f"Fill '{cfg['solid_fill']}' not found.")

    client.tapir("ChangeWindow", {"windowType": "Layout", "databaseId": {"guid": db}})
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    result.removed = remove_previous(client, previous, db, layer)

    created = result.created
    expected: list[tuple[str, dict[str, Any], dict[str, float]]] = []  # (kind, elementId, target rect m)

    def add(key: str, ids: list[dict[str, Any]]) -> None:
        created.setdefault(key, []).extend(e["guid"] for e in ids)

    def target(x: float, y: float, w: float, h: float) -> dict[str, float]:
        o = page.rect_origin(x, y, h)
        return {"xMin": o["x"], "yMin": o["y"], "xMax": o["x"] + w / 1000, "yMax": o["y"] + h / 1000}

    # Fills: the hero title band and placeholder backgrounds.
    hero = cfg["panels"]["hero"]
    image_top = min(i["y"] for i in cfg["images"] if i["key"] == "hero")
    fills = [("title-band", hero["x"], hero["y"], hero["w"], image_top - hero["y"], "cream")]
    fills += [(f"placeholder-{p['key']}", p["x"], p["y"], p["w"], p["h"], "cream") for p in cfg["placeholders"]]
    r = client.tapir("CreateHatches", {"hatchesData": [
        {"coordinates": page.rect(x, y, w, h), "fillId": solid["attributeId"], "fillPenIndex": pen[c],
         "fillBackgroundPenIndex": pen[c], "contourPenIndex": pen[c]}
        for _, x, y, w, h, c in fills
    ]})
    for (key, *_), eid in zip(fills, _ids(r, "fills")):
        add(key, [eid])

    # Images through the 2D picture object.
    r = client.tapir("CreateObjects", {"objectsData": [
        {"libraryPartName": PICTURE_OBJECT, "coordinates": {**page.rect_origin(i["x"], i["y"], i["h"]), "z": 0},
         "dimensions": {"x": i["w"] / 1000, "y": i["h"] / 1000, "z": 0}, "angle": 0}
        for i in cfg["images"]
    ]})
    image_ids = _ids(r, "images")
    client.tapir("SetGDLParametersOfElements", {"elementsWithGDLParameters": [
        {"elementId": eid, "gdlParameters": [
            {"name": "picName", "value": i["file"]}, {"name": "A", "value": i["w"] / 1000},
            {"name": "B", "value": i["h"] / 1000}]}
        for i, eid in zip(cfg["images"], image_ids)
    ]})
    for i, eid in zip(cfg["images"], image_ids):
        add(f"image-{i['key']}", [eid])
        expected.append(("image", eid, target(i["x"], i["y"], i["w"], i["h"])))

    # Drawings: probe once, then place at a true scale (or fit, for 3D documents).
    drawing_ids = []
    for d in cfg["drawings"]:
        slot = d["slot"]
        d = dict(d, source=views.get(d["source"], d["source"]))
        probe_at = {"x": 0.0, "y": 0.0}

        def probe(ratio: float | None) -> dict[str, Any]:
            item = {"navigatorItemId": {"guid": d["source"]}, "layoutDatabaseId": {"guid": db},
                    "name": d["name"], "position": probe_at}
            if ratio is not None:
                item["scale"] = ratio
            pid = _ids(client.tapir("CreateDrawings", {"drawingsData": [item]}), d["key"])
            out = client.tapir("GetDetailsOfElements", {"elements": [{"elementId": pid[0]}], "fields": ["details"]})
            client.tapir("DeleteElements", {"elements": [{"elementId": pid[0]}]})
            return out["detailsOfElements"][0]["details"]

        det = probe(None)
        centre = page.centre(slot)
        if d.get("fit"):
            ratio = fit_ratio(det["bounds"], slot["w"] / 1000, slot["h"] / 1000)
            w = (det["bounds"]["xMax"] - det["bounds"]["xMin"]) * ratio
            h = (det["bounds"]["yMax"] - det["bounds"]["yMin"]) * ratio
            data = {"scale": ratio, "position": {"x": centre[0] - w / 2, "y": centre[1] - h / 2}}
        else:
            ratio = (1.0 / d["scale"]) / det["drawingScale"]
            det2 = probe(ratio)
            placement = place_drawing(
                view_scale=det["drawingScale"], target_scale=d["scale"],
                probe_position=(probe_at["x"], probe_at["y"]), probe_pos=(det2["pos"]["x"], det2["pos"]["y"]),
                probe_bounds=det2["bounds"], slot_centre=centre, probe_ratio=ratio,
                model_clip=tuple(d["model_clip"]) if d.get("model_clip") else None,
            )
            data = {"scale": placement.ratio, "position": placement.position}
            if placement.clip:
                data["clipPolygon"] = placement.clip
            w, h = placement.paper_size_m
            if w > slot["w"] / 1000 + TOLERANCE_M or h > slot["h"] / 1000 + TOLERANCE_M:
                warnings.append(f"{d['name']} at 1:{d['scale']} is {w*1000:.0f} x {h*1000:.0f} mm, larger than its slot.")
        eid = _ids(client.tapir("CreateDrawings", {"drawingsData": [{
            "navigatorItemId": {"guid": d["source"]}, "layoutDatabaseId": {"guid": db},
            "name": d["name"], **data}]}), d["key"])[0]
        add(f"drawing-{d['key']}", [eid])
        drawing_ids.append(eid)
        expected.append(("drawing", eid, target(slot["x"], slot["y"], slot["w"], slot["h"])))

    # Linework: border, context circle outline, principle icons, placeholder cross.
    b = cfg["border"]
    W, H = page.width_mm, page.height_mm
    border = page.rect(b["inset_x_mm"], b["inset_y_mm"], W - 2 * b["inset_x_mm"], H - 2 * b["inset_y_mm"])
    polylines = [("border", border + [border[0]], b["pen"], b["weight_mm"])]
    for p in cfg["placeholders"]:
        polylines.append((f"placeholder-{p['key']}", [page.point(p["x"], p["y"]), page.point(p["x"] + p["w"], p["y"] + p["h"])], "grey", 0.1))
        polylines.append((f"placeholder-{p['key']}", [page.point(p["x"], p["y"] + p["h"]), page.point(p["x"] + p["w"], p["y"])], "grey", 0.1))
    r = client.tapir("CreatePolylines", {"polylinesData": [
        {"coordinates": c, "linePenIndex": pen[k], "penWeightMm": w} for _, c, k, w in polylines
    ]})
    for (key, *_), eid in zip(polylines, _ids(r, "linework")):
        add(key, [eid])

    ctx = next(i for i in cfg["images"] if i["key"] == "context")
    circles = [("context-outline", page.point(ctx["x"] + ctx["w"] / 2, ctx["y"] + ctx["h"] / 2), ctx["w"] / 2000, "grey")]
    pr = cfg["panels"]["principles"]
    rows = cfg["project"]["principles"]
    pitch = pr["h"] / len(rows)
    for n in range(len(rows)):
        cy = pr["y"] + pitch * (n + 0.5)
        circles.append((f"principle-icon-{n + 1}", page.point(pr["x"] + 5, cy), 0.0045, "bluegrey"))
    r = client.tapir("CreateCircles", {"circlesData": [
        {"origin": o, "radius": rad, "linePenIndex": pen[k]} for _, o, rad, k in circles
    ]})
    for (key, *_), eid in zip(circles, _ids(r, "circles")):
        add(key, [eid])

    # Text.
    texts: list[tuple[str, dict[str, Any]]] = []

    def text(key, x, y, body, kind, colour="charcoal", width=None, bold=False, anchor="LeftTop"):
        style: dict[str, Any] = {"anchor": anchor, "fixedSize": True, "bold": bold, "justification": "Left"}
        if width:
            body = _wrap(body, width, size[kind])
        texts.append((key, {"coordinate": {**page.point(x, y), "z": 0}, "text": body,
                            "height": size[kind], "pen": pen[colour], "style": style}))

    info = cfg["panels"]["info"]
    text("title", hero["x"] + 10, hero["y"] + 8, "\n".join(cfg["project"]["title_lines"]), "title")
    text("location", hero["x"] + 10, hero["y"] + 8 + size["title"] * 1.6 * len(cfg["project"]["title_lines"]) + 2,
         cfg["project"]["location"], "location", "bluegrey")
    text("info", info["x"], info["y"], "\n".join(cfg["project"]["info_lines"]), "credit")
    for n, label in enumerate(rows):
        cy = pr["y"] + pitch * (n + 0.5)
        text(f"principle-number-{n + 1}", pr["x"] + 5, cy, str(n + 1), "credit", "bluegrey", anchor="MiddleMiddle")
        text(f"principle-{n + 1}", pr["x"] + 14, cy, label, "caption", anchor="LeftMiddle")
    ex = cfg["panels"]["explanation"]
    col_w = (ex["w"] - 10) / 2
    for n, para in enumerate(cfg["project"]["explanation"][:2]):
        text(f"explanation-{n + 1}", ex["x"] + n * (col_w + 10), ex["y"], para, "body", width=col_w)
    for d in cfg["drawings"]:
        s = d["slot"]
        text(f"caption-{d['key']}", s["x"], s["y"] + s["h"] + 3, d["caption"], "caption", "grey")
    for n, c in enumerate(cfg["captions"]):
        text(f"caption-extra-{n + 1}", c["x"], c["y"], c["text"], "caption", "grey")
    for p in cfg["placeholders"]:
        text(f"placeholder-{p['key']}-label", p["x"] + p["w"] / 2, p["y"] + p["h"] / 2, p["text"], "caption", "grey",
             anchor="MiddleMiddle")
        text(f"caption-{p['key']}", p["x"], p["y"] + p["h"] + 3, p["caption"], "caption", "grey")
    text("credit", info["x"], H - b["inset_y_mm"] - 6, cfg["project"]["credit"], "credit", "grey")
    for key, t in texts:
        if t["style"]["anchor"] == "MiddleMiddle":
            t["style"]["justification"] = "Center"
    r = client.tapir("CreateTexts", {"textsData": [t for _, t in texts]})
    for (key, _), eid in zip(texts, _ids(r, "texts")):
        add(key, [eid])

    # Everything onto the board layer; drawing titles off.
    every = [{"guid": g} for guids in created.values() for g in guids]
    client.tapir("SetDetailsOfElements", {"elementsWithDetails": [
        {"elementId": e, "details": {"layerIndex": layer}} for e in every
    ]})
    client.tapir("SetDetailsOfElements", {"elementsWithDetails": [
        {"elementId": e, "details": {"typeSpecificDetails": {"titleLibraryPartIndex": 0}}} for e in drawing_ids
    ]})
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result.manifest(), indent=2), encoding="utf-8")

    result.checks = verify_board(client, expected, page, cfg, layer)
    return result


def verify_board(client: TapirClient, expected, page: Page, cfg: dict[str, Any], layer: int) -> list[dict[str, Any]]:
    """Read every placed image and drawing back and compare with its slot."""
    b = cfg["border"]
    inner = {"xMin": b["inset_x_mm"] / 1000, "yMin": b["inset_y_mm"] / 1000,
             "xMax": (page.width_mm - b["inset_x_mm"]) / 1000, "yMax": (page.height_mm - b["inset_y_mm"]) / 1000}
    det = client.tapir("GetDetailsOfElements", {
        "elements": [{"elementId": e} for _, e, _ in expected], "fields": ["type", "layerIndex", "details"]})
    checks = []
    for (kind, eid, slot), d in zip(expected, det["detailsOfElements"]):
        dd = d.get("details", {})
        if kind == "image":
            o, dim = dd.get("origin", {}), dd.get("dimensions", {})
            box = {"xMin": o.get("x", 0), "yMin": o.get("y", 0),
                   "xMax": o.get("x", 0) + dim.get("x", 0), "yMax": o.get("y", 0) + dim.get("y", 0)}
            ok_angle = abs(dd.get("angle", 0)) < 1e-6
        else:
            clip = dd.get("clipPolygon")
            box = ({"xMin": min(p["x"] for p in clip), "yMin": min(p["y"] for p in clip),
                    "xMax": max(p["x"] for p in clip), "yMax": max(p["y"] for p in clip)} if clip else dd.get("bounds", {}))
            ok_angle = abs(dd.get("angle", 0)) < 1e-6
        inside = all(
            box.get(k, 0) >= slot[k] - TOLERANCE_M if k.endswith("Min") else box.get(k, 0) <= slot[k] + TOLERANCE_M
            for k in ("xMin", "yMin", "xMax", "yMax")
        ) if box else False
        in_border = all(
            box.get(k, 0) >= inner[k] if k.endswith("Min") else box.get(k, 0) <= inner[k]
            for k in ("xMin", "yMin", "xMax", "yMax")
        ) if box else False
        checks.append({
            "guid": eid["guid"], "kind": kind, "ok": inside and in_border and ok_angle
            and int(d.get("layerIndex", -1)) == layer,
            "box_mm": {k: round(v * 1000, 1) for k, v in box.items()},
            "ratio": dd.get("ratio"), "source": (dd.get("navigatorItemId") or {}).get("guid"),
        })
    return checks


def publish_layout(client: TapirClient, publisher_set: str, layout_navigator_id: str, out_dir: Path) -> None:
    """Publish only this layout from ``publisher_set`` (its format, e.g. PNG or PDF, comes from the set)."""
    tree = client.tapir("GetNavigatorItemTree", {"navigatorMapId": "PublisherSets", "publisherSetName": publisher_set})
    item = next(
        (n for n in _walk(tree["navigatorItemTree"])
         if (n.get("sourceNavigatorItemId") or {}).get("guid") == layout_navigator_id),
        None,
    )
    if item is None:
        raise ArchicadError(f"The layout is not in publisher set '{publisher_set}'.")
    out_dir.mkdir(parents=True, exist_ok=True)
    client.tapir("PublishPublisherSet", {
        "publisherSetName": publisher_set, "outputPath": str(out_dir.resolve()),
        "selectedNavigatorItemIds": [{"navigatorItemId": item["navigatorItemId"]}],
    })
