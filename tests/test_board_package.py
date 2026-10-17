import base64
import copy
import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from archicad_toolkit.presentation.package import (
    BoardConfigError,
    compile_picture_object,
    require_valid,
    unpack_images,
    validate_board,
)
from archicad_toolkit.presentation.picture_object import PICTURE_OBJECT_XML
from test_presentation_board import FakeBoardArchicad

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "boards" / "pres-01" / "board.json"
SCRIPT = ROOT / "web" / "archicad" / "BuildBoard.py"
JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0 fake jpeg").decode()


@pytest.fixture
def cfg():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def package(cfg):
    pkg = copy.deepcopy(cfg)
    pkg.update(format="archicad-board", version=1)
    for img in pkg["images"]:
        img["data"] = JPEG
    return pkg


def test_pres01_config_is_valid(cfg):
    assert validate_board(cfg) == ([], [])


@pytest.mark.parametrize("mutate, message", [
    (lambda c: c["pens"].pop("grey"), "pen named 'grey'"),
    (lambda c: c["pens"]["cream"].update(index=c["pens"]["grey"]["index"]), "both use pen"),
    (lambda c: c.update(images=[i for i in c["images"] if i["key"] != "context"]), "key 'context'"),
    (lambda c: c["images"][0].update(file="../../evil.jpg"), "plain .jpg"),
    (lambda c: c["drawings"][0].update(source="x"), "navigator id"),
    (lambda c: c["panels"]["hero"].update(x=590), "runs off"),
    (lambda c: c["project"].update(principles=[]), "at least one row"),
])
def test_validation_stops_what_would_break_the_builder(cfg, mutate, message):
    mutate(cfg)
    with pytest.raises(BoardConfigError) as err:
        require_valid(cfg)
    assert any(message in e for e in err.value.errors)


def test_oversized_drawing_is_a_warning(cfg):
    cfg["drawings"][1]["scale"] = 400
    errors, warnings = validate_board(cfg)
    assert not errors and any("more than its" in w for w in warnings)


def test_unpack_writes_images_and_strips_data(cfg, tmp_path):
    out, count = unpack_images(package(cfg), tmp_path)
    assert count == len(cfg["images"])
    assert all("data" not in i for i in out["images"])
    assert (tmp_path / cfg["images"][0]["file"]).read_bytes().startswith(b"\xff\xd8")


def test_unpack_rejects_bad_data(cfg, tmp_path):
    pkg = package(cfg)
    pkg["images"][0]["data"] = "data:image/jpeg;base64,@@@"
    with pytest.raises(BoardConfigError):
        unpack_images(pkg, tmp_path)


def test_picture_object_source_matches_the_gdl_file():
    assert PICTURE_OBJECT_XML == (ROOT / "boards/pres-01/gdl/PRES_Image2D.xml").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform.startswith("win"), reason="uses a shell script as the converter")
def test_compile_picture_object_runs_the_converter(tmp_path):
    tool = tmp_path / "LP_XMLConverter"
    tool.write_text('#!/bin/sh\n[ "$1" = xml2libpart ] && cp "$4" "$5"\n')
    tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    gsm = compile_picture_object(tmp_path / "work", str(tool))
    assert gsm.name == "PRES_Image2D.gsm" and gsm.read_text(encoding="utf-8") == PICTURE_OBJECT_XML


def test_web_files_are_up_to_date():
    run = subprocess.run([sys.executable, str(ROOT / "tools" / "build_web.py"), "--check"], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.fixture
def bundle():
    spec = importlib.util.spec_from_file_location("BuildBoard", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["BuildBoard"] = mod  # dataclasses look their module up while the file runs
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop("BuildBoard", None)


def test_bundled_script_builds_and_rebuilds_from_a_board_file(cfg, tmp_path, bundle):
    board_file = tmp_path / "PRES-01.board.json"
    board_file.write_text(json.dumps(package(cfg)), encoding="utf-8")
    gsm = tmp_path / "PRES_Image2D.gsm"
    gsm.write_bytes(b"gsm")
    fake = FakeBoardArchicad()
    client = bundle.TapirClient(fake)
    args = [str(board_file), "--yes", "--work", str(tmp_path / "work"), "--gsm", str(gsm)]
    assert bundle.main(args, client=client) == 0
    manifest = json.loads((tmp_path / "work" / "manifest.json").read_text(encoding="utf-8"))
    count = sum(len(v) for v in manifest["elements"].values())
    assert count == len(fake.items)
    assert json.loads((tmp_path / "work" / "checks.json").read_text(encoding="utf-8"))
    # A second run replaces the first instead of adding to it.
    assert bundle.main(args, client=client) == 0
    assert len(fake.items) == count


def test_bundled_script_check_mode_needs_no_archicad(cfg, tmp_path, bundle, capsys):
    board_file = tmp_path / "b.board.json"
    board_file.write_text(json.dumps(package(cfg)), encoding="utf-8")
    assert bundle.main([str(board_file), "--check", "--work", str(tmp_path / "w")]) == 0
    assert "Check passed" in capsys.readouterr().out


def test_bundled_script_refuses_an_invalid_file(cfg, tmp_path, bundle, capsys):
    cfg["pens"].pop("cream")
    board_file = tmp_path / "b.board.json"
    board_file.write_text(json.dumps(cfg), encoding="utf-8")
    assert bundle.main([str(board_file), "--check", "--work", str(tmp_path / "w")]) == 2
    assert "pen named 'cream'" in capsys.readouterr().out


def test_bundled_script_only_talks_to_this_computer(tmp_path, bundle):
    with pytest.raises(SystemExit):
        bundle.main([str(tmp_path / "x.board.json"), "--host", "http://example.com:19723"])


def test_vercel_configs_agree():
    # vercel.json at the root serves web/ when the Vercel project's Root Directory is left
    # blank; web/vercel.json applies when it is set to web. Both must send the same headers.
    root = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    web = json.loads((ROOT / "web" / "vercel.json").read_text(encoding="utf-8"))
    assert root["outputDirectory"] == "web" and root["framework"] is None
    assert root["headers"] == web["headers"]
