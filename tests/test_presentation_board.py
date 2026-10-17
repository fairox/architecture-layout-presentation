import itertools
import json
from pathlib import Path

import pytest

from archicad_toolkit.client import TapirClient
from archicad_toolkit.presentation import build_board, publish_layout
from fake_archicad import FakeArchicad

CONFIG = Path(__file__).parents[1] / "boards" / "pres-01" / "board.json"


class FakeBoardArchicad(FakeArchicad):
    """Enough of Tapir's layout, drawing and drafting commands for the board builder."""

    VIEW_SCALE = 0.01
    ORIGIN_OFFSET = (0.37, 0.43)  # model origin relative to a drawing's position, at ratio 1

    def __init__(self) -> None:
        super().__init__()
        self.layers = {"Drawing & Figure": 1}
        self.items: dict[str, dict] = {}  # guid -> {"type", "layer", "details"}
        self.layout_created = False
        self.library: list[str] = []
        self._guid = (f"g-{n}" for n in itertools.count(1))
        self.view_folder: list[dict] | None = None
        self.view_settings: dict[str, dict] = {}
        self.combinations: dict[str, list] = {}

    def _new(self, type_, details) -> dict:
        g = next(self._guid)
        self.items[g] = {"type": type_, "layer": 1, "details": details}
        return {"elementId": {"guid": g}}

    # navigator / layout
    def _tapir_GetNavigatorItemTree(self, p):
        if p["navigatorMapId"] == "PublisherSets":
            return {"navigatorItemTree": {"type": "FolderItem", "navigatorItemId": {"guid": "pub-root"}, "children": [
                {"navigatorItem": {"type": "LayoutItem", "navigatorItemId": {"guid": "pub-1"},
                                   "sourceNavigatorItemId": {"guid": "lay-nav"}}}]}}
        if p["navigatorMapId"] == "PublicViewMap":
            kids = []
            if self.view_folder is not None:
                kids.append({"navigatorItem": {"type": "FolderItem", "name": "PRES-01 Board Views",
                                               "navigatorItemId": {"guid": "views"},
                                               "children": [{"navigatorItem": v} for v in self.view_folder]}})
            return {"navigatorItemTree": {"type": "FolderItem", "navigatorItemId": {"guid": "vroot"}, "children": kids}}
        children = [{"navigatorItem": {"type": "SubSetItem", "name": "Presentation Boards",
                                       "navigatorItemId": {"guid": "sub-1"}}}]
        if self.layout_created:
            children.append({"navigatorItem": {"type": "LayoutItem", "name": "x", "navigatorItemId": {"guid": "lay-nav"}}})
        return {"navigatorItemTree": {"type": "UndefinedItem", "navigatorItemId": {"guid": "root"}, "children": children}}

    def _tapir_GetLayoutSettings(self, p):
        return {"layoutSettings": [{"customLayoutNumber": "PRES-01"}]}

    def _tapir_GetDatabaseIdFromNavigatorItemId(self, p):
        return {"databases": [{"databaseId": {"guid": "lay-db"}}]}

    def _tapir_CreateLayout(self, p):
        self.layout_created = True
        return {"databases": [{"databaseId": {"guid": "lay-db"}}]}

    def _tapir_MoveNavigatorItem(self, p):
        return {"success": True}

    def _tapir_ChangeWindow(self, p):
        return {"success": True}

    # views
    def _tapir_GetViewSettings(self, p):
        return {"viewSettings": [{"layerCombination": "", "penSetName": "x"} for _ in p["navigatorItemIds"]]}

    def _tapir_SetViewSettings(self, p):
        for v in p["navigatorItemIdsWithViewSettings"]:
            self.view_settings[v["navigatorItemId"]["guid"]] = v["viewSettings"]
        return {"executionResults": [{"success": True}]}

    def _tapir_CreateViewMapFolder(self, p):
        self.view_folder = []
        return {"navigatorItemId": {"guid": "views"}}

    def _tapir_CreateViewsInViewMap(self, p):
        out = []
        for v in p["viewsData"]:
            g = f"view-{len(self.view_folder) + 1}"
            self.view_folder.append({"type": "StoryItem", "name": v["name"], "navigatorItemId": {"guid": g}})
            out.append({"navigatorItemId": {"guid": g}})
        return {"navigatorItems": out}

    def _tapir_CreateLayerCombinations(self, p):
        for c in p["layerCombinationDataArray"]:
            self.combinations[c["name"]] = c["layers"]
        return {"attributeIds": []}

    # attributes
    def _tapir_GetAttributesByType(self, p):
        kind = p["attributeType"]
        if kind == "Layer":
            names = self.layers
        elif kind == "LayerCombination":
            names = {n: i for i, n in enumerate(self.combinations, 1)}
        elif kind == "PenTable":
            names = {"03 Architectural 100": 5}
        else:
            names = {"Foreground": 64}
        return {"attributes": [{"attributeId": {"guid": f"{kind}-{i}"}, "index": i, "name": n} for n, i in names.items()]}

    def _tapir_CreateLayers(self, p):
        for layer in p["layerDataArray"]:
            self.layers.setdefault(layer["name"], len(self.layers) + 1)
        return {"attributeIds": []}

    def _tapir_CreatePenTables(self, p):
        return {"attributeIds": [{"attributeId": p["penTableDataArray"][0]["attributeId"]}]}

    def _tapir_AddFilesToEmbeddedLibrary(self, p):
        self.library += [f["outputPath"] for f in p["files"]]
        return {"executionResults": [{"success": True} for _ in p["files"]]}

    def _tapir_ReloadLibraries(self, p):
        return {"success": True}

    # elements
    def _tapir_GetAllElements(self, p):
        return {"elements": [{"elementId": {"guid": g}} for g in self.items]}

    def _tapir_DeleteElements(self, p):
        for e in p["elements"]:
            self.items.pop(e["elementId"]["guid"], None)
        return {"executionResults": [{"success": True} for _ in p["elements"]]}

    def _tapir_CreateDrawings(self, p):
        out = []
        for d in p["drawingsData"]:
            ratio = d.get("scale", 1.0)
            pos = {"x": d["position"]["x"] + self.ORIGIN_OFFSET[0] * ratio,
                   "y": d["position"]["y"] + self.ORIGIN_OFFSET[1] * ratio}
            det = {"pos": pos, "ratio": ratio, "drawingScale": self.VIEW_SCALE, "angle": 0,
                   "navigatorItemId": {"guid": "src-" + d["navigatorItemId"]["guid"]},
                   "bounds": {"xMin": d["position"]["x"], "yMin": d["position"]["y"],
                              "xMax": d["position"]["x"] + 0.5 * ratio, "yMax": d["position"]["y"] + 0.3 * ratio}}
            if "clipPolygon" in d:
                det["clipPolygon"] = d["clipPolygon"]
            out.append(self._new("Drawing", det))
        return {"elements": out}

    def _create(self, type_, items, details):
        return {"elements": [self._new(type_, details(i)) for i in items]}

    def _tapir_CreateHatches(self, p):
        return self._create("Hatch", p["hatchesData"], lambda i: {})

    def _tapir_CreatePolylines(self, p):
        return self._create("PolyLine", p["polylinesData"], lambda i: {})

    def _tapir_CreateCircles(self, p):
        return self._create("Arc", p["circlesData"], lambda i: {})

    def _tapir_CreateTexts(self, p):
        return self._create("Text", p["textsData"], lambda i: {"text": i["text"]})

    def _tapir_CreateObjects(self, p):
        return self._create("Object", p["objectsData"], lambda i: {
            "origin": i["coordinates"], "dimensions": i["dimensions"], "angle": i.get("angle", 1.5708)})

    def _tapir_SetGDLParametersOfElements(self, p):
        return {"executionResults": [{"success": True}]}

    def _tapir_SetDetailsOfElements(self, p):
        for e in p["elementsWithDetails"]:
            if "layerIndex" in e["details"]:
                self.items[e["elementId"]["guid"]]["layer"] = e["details"]["layerIndex"]
        return {"executionResults": [{"success": True}]}

    def _tapir_GetDetailsOfElements(self, p):
        out = []
        for e in p["elements"]:
            item = self.items[e["elementId"]["guid"]]
            out.append({"type": item["type"], "layerIndex": item["layer"], "details": item["details"]})
        return {"detailsOfElements": out}

    def _tapir_PublishPublisherSet(self, p):
        self.published = p
        return {}


@pytest.fixture
def setup(tmp_path):
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    for img in cfg["images"]:
        (tmp_path / img["file"]).write_bytes(b"jpg")
    gsm = tmp_path / "PRES_Image2D.gsm"
    gsm.write_bytes(b"gsm")
    fake = FakeBoardArchicad()
    return fake, TapirClient(fake), cfg, tmp_path, gsm


def build(client, cfg, tmp_path, gsm):
    return build_board(client, cfg, assets_dir=tmp_path, gsm=gsm, manifest_path=tmp_path / "manifest.json")


def test_builds_board_on_its_own_layer_and_passes_checks(setup):
    fake, client, cfg, tmp_path, gsm = setup
    result = build(client, cfg, tmp_path, gsm)
    layer = fake.layers["PRES-01 Board"]
    assert fake.layout_created
    assert all(item["layer"] == layer for item in fake.items.values())
    assert result.failed_checks == []
    assert len([i for i in fake.items.values() if i["type"] == "Drawing"]) == len(cfg["drawings"])
    assert "PRES-01/PRES_Image2D.gsm" in fake.library


def test_plans_are_placed_at_a_true_scale(setup):
    fake, client, cfg, tmp_path, gsm = setup
    build(client, cfg, tmp_path, gsm)
    ratios = [i["details"]["ratio"] for i in fake.items.values()
              if i["type"] == "Drawing" and "clipPolygon" in i["details"]]
    assert ratios and all(r == pytest.approx(100 / 750) for r in ratios)


def test_rebuild_replaces_its_own_elements_and_keeps_hand_made_ones(setup):
    fake, client, cfg, tmp_path, gsm = setup
    build(client, cfg, tmp_path, gsm)
    count = len(fake.items)
    fake.items["hand-made"] = {"type": "Text", "layer": 1, "details": {}}
    result = build(client, cfg, tmp_path, gsm)
    assert result.removed == count
    assert len(fake.items) == count + 1
    assert "hand-made" in fake.items


def test_missing_image_stops_before_touching_the_layout(setup):
    fake, client, cfg, tmp_path, gsm = setup
    (tmp_path / cfg["images"][0]["file"]).unlink()
    with pytest.raises(FileNotFoundError):
        build(client, cfg, tmp_path, gsm)
    assert fake.items == {}


def test_publish_selects_only_this_layout(setup, tmp_path):
    fake, client, *_ = setup
    publish_layout(client, "1 - Layouts", "lay-nav", tmp_path / "out")
    assert fake.published["selectedNavigatorItemIds"] == [{"navigatorItemId": {"guid": "pub-1"}}]


def test_board_views_are_copies_with_their_own_layers(setup):
    fake, client, cfg, tmp_path, gsm = setup
    build(client, cfg, tmp_path, gsm)
    scaled = [d for d in cfg["drawings"] if not d.get("fit")]
    assert len(fake.view_folder) == len(scaled)
    assert all(v["layerCombination"] == "PRES-01 Presentation" for v in fake.view_settings.values())
    hidden = {row["attributeId"]["guid"] for row in fake.combinations["PRES-01 Presentation"] if row["isHidden"]}
    board = f"Layer-{fake.layers['PRES-01 Board']}"
    assert board not in hidden
    # A second build reuses the same views instead of making more.
    build(client, cfg, tmp_path, gsm)
    assert len(fake.view_folder) == len(scaled)
