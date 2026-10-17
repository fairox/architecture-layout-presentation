"""BuildBoard: build a presentation board in the open Archicad project from a board file.

The web configurator exports ``<layout id>.board.json`` (the board config with its
cropped images inside). This script runs on the computer where Archicad and the
Tapir add-on run, reads that file and builds the layout through the JSON API on
127.0.0.1 only. The browser never connects to Archicad.

Usage (Python 3.9+, standard library only):
  python BuildBoard.py                          # newest *.board.json (file dialog, else Downloads)
  python BuildBoard.py PRES-01.board.json [--publish] [--yes]
  python BuildBoard.py PRES-01.board.json --check   # validate and unpack only; Archicad not needed
Options: --port N, --work DIR, --manifest FILE, --gsm FILE, --assets DIR, --converter PATH.

Work files go to Documents/Archicad Boards/<layout id>/ (images, the compiled picture
object, manifest.json, checks.json). Keep that folder: the manifest is how a rerun
replaces only what the previous run built.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from archicad_toolkit.client import ArchicadError, TapirClient, http_transport
from archicad_toolkit.presentation.board import build_board, publish_layout
from archicad_toolkit.presentation.package import (
    PACKAGE_SUFFIX,
    BoardConfigError,
    compile_picture_object,
    has_embedded_images,
    require_valid,
    unpack_images,
)

PORTS = range(19723, 19745)
MAX_FILE = 200 * 1024 * 1024
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")


def say(*a: object) -> None:
    print(*a, flush=True)


def interactive() -> bool:
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except (ValueError, OSError):
        return False


def pick_file() -> Path:
    """File dialog when one can open, else the newest board file in the working folder or Downloads."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askopenfilename(
            title="Board file", initialdir=str(Path.home() / "Downloads"),
            filetypes=[("Board file", "*" + PACKAGE_SUFFIX), ("JSON", "*.json")])
        root.destroy()
        if chosen:
            return Path(chosen)
    except Exception:
        pass
    found = [p for d in (Path.cwd(), Path.home() / "Downloads") if d.exists() for p in d.glob("*" + PACKAGE_SUFFIX)]
    if not found:
        raise SystemExit("No board file given and none found in Downloads. Export one from the configurator.")
    newest = max(found, key=lambda p: p.stat().st_mtime)
    say(f"Using the newest board file: {newest}")
    return newest


def alive(port: int, timeout: float = 0.6) -> bool:
    try:
        r = http_transport(f"http://127.0.0.1:{port}", timeout)({"command": "API.IsAlive"})
        return bool(r.get("succeeded") and r.get("result", {}).get("isAlive", True))
    except Exception:
        return False


def find_port(wanted: int | None) -> int:
    if wanted is not None:
        if wanted not in PORTS:
            raise SystemExit("Archicad listens on ports 19723-19744 only.")
        if not alive(wanted):
            raise SystemExit(f"Nothing answers on port {wanted}. Open Archicad with Tapir and close any open dialog.")
        return wanted
    ports = [p for p in PORTS if alive(p, 0.3)]
    if not ports:
        raise SystemExit("Archicad is not reachable on 127.0.0.1. Open the project in Archicad with Tapir and retry.")
    if len(ports) > 1:
        say("Several Archicad instances are open on ports " + ", ".join(map(str, ports)) + ".")
        if not interactive():
            raise SystemExit("Choose the target with --port N.")
        answer = input("Port of the project to build in: ").strip()
        if not answer.isdigit() or int(answer) not in ports:
            raise SystemExit("No such port.")
        return int(answer)
    return ports[0]


def parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="BuildBoard", description="Build a presentation board in Archicad from a board file.")
    ap.add_argument("file", nargs="?", help="board file exported by the configurator (*.board.json)")
    ap.add_argument("--check", action="store_true", help="validate and unpack only; do not connect to Archicad")
    ap.add_argument("--publish", action="store_true", help="also publish the layout with its publisher set")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    ap.add_argument("--port", type=int, help="Archicad JSON API port when several Archicad instances are open")
    ap.add_argument("--work", type=Path, help="work folder (default: Documents/Archicad Boards/<layout id>)")
    ap.add_argument("--manifest", type=Path, help="manifest of the previous build (default: in the work folder)")
    ap.add_argument("--gsm", type=Path, help="compiled PRES_Image2D.gsm (default: compile it with LP_XMLConverter)")
    ap.add_argument("--assets", type=Path, help="folder with the prepared images, when the file has none embedded")
    ap.add_argument("--converter", help="path to LP_XMLConverter")
    ap.add_argument("--host", help="passed by the Tapir palette; only this computer is accepted")
    args, _unknown = ap.parse_known_args(argv)  # the Tapir palette may pass extra arguments
    return args


def main(argv: list[str] | None = None, client: TapirClient | None = None) -> int:
    a = parse(argv)
    if a.host:
        host = a.host.split("://")[-1].rsplit(":", 1)
        if host[0] not in LOCAL_HOSTS:
            raise SystemExit("This script talks only to Archicad on this computer (127.0.0.1).")
        if a.port is None and len(host) == 2 and host[1].isdigit():
            a.port = int(host[1])

    path = Path(a.file) if a.file else pick_file()
    if not path.is_file():
        raise SystemExit(f"Board file not found: {path}")
    if path.stat().st_size > MAX_FILE:
        raise SystemExit("The board file is too large.")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        warnings = require_valid(doc)
    except json.JSONDecodeError as exc:
        say(f"The board file is not valid JSON: {exc}")
        return 2
    except BoardConfigError as exc:
        say("The board file cannot be built:")
        for e in exc.errors:
            say("  - " + e)
        return 2

    lay = doc["layout"]
    work = a.work or (Path.home() / "Documents" / "Archicad Boards" / lay["id"])
    work.mkdir(parents=True, exist_ok=True)
    if has_embedded_images(doc):
        assets = work / "images"
        cfg, count = unpack_images(doc, assets)
        say(f"Unpacked {count} image(s) to {assets}")
        for img in cfg["images"]:  # pictures not in the file may come from --assets
            extra = a.assets / img["file"] if a.assets else None
            if extra and extra.is_file() and not (assets / img["file"]).exists():
                shutil.copyfile(extra, assets / img["file"])
                say(f"Copied {img['file']} from {a.assets}")
    else:
        cfg = doc
        assets = a.assets or path.parent
    missing = [i["file"] for i in cfg["images"] if not (assets / i["file"]).exists()]
    if missing:
        say(f"Missing image(s) in {assets}: {', '.join(missing)}. Export them with the file or give --assets.")
        return 2

    say(f"Board     {lay['id']}  {lay['name']}  ({lay['width_mm']:g} x {lay['height_mm']:g} mm)")
    say(f"Content   {len(cfg['images'])} images, {len(cfg['drawings'])} drawings, {len(cfg.get('placeholders') or [])} placeholders")
    for w in warnings:
        say("Warning   " + w)
    fonts = (doc.get("fonts") or {})
    if fonts:
        say("Note      Tapir cannot set fonts; texts use the layout's default font. Wanted: "
            + ", ".join(f"{k} {v}" for k, v in fonts.items()))
    if a.check:
        say("Check passed; nothing was sent to Archicad.")
        return 0

    gsm = a.gsm
    if gsm is None:
        gsm = work / "PRES_Image2D.gsm"
        if not gsm.exists():
            try:
                gsm = compile_picture_object(work, a.converter)
                say(f"Compiled the picture object: {gsm}")
            except (FileNotFoundError, RuntimeError) as exc:
                say(str(exc))
                return 2
    manifest = a.manifest or (work / "manifest.json")

    try:
        if client is None:
            port = find_port(a.port)
            client = TapirClient(http_transport(f"http://127.0.0.1:{port}", 120.0))
            say(f"Archicad on port {port}")
        say("Rebuild   replaces the elements listed in " + str(manifest) if manifest.exists()
            else "Build     first build from this work folder (no manifest yet)")
        if not a.yes and interactive():
            if input("Build this board in the open project? [y/N] ").strip().lower() not in ("y", "yes"):
                say("Cancelled.")
                return 1
        result = build_board(client, cfg, assets_dir=assets, gsm=gsm, manifest_path=manifest)
        (work / "checks.json").write_text(json.dumps(result.checks, indent=2), encoding="utf-8")
        built = sum(len(v) for v in result.created.values())
        say(f"Built {lay['id']}: {built} element(s), replaced {result.removed}.")
        failed = result.failed_checks
        say(f"Checks    {len(result.checks) - len(failed)} of {len(result.checks)} placements inside their slots.")
        for c in failed:
            say(f"  failed  {c['kind']} {c['guid']} at {c['box_mm']}")
        for w in result.warnings:
            say("Warning   " + w)
        if a.publish:
            out = work / "preview"
            publish_layout(client, lay.get("publisher_set", ""), result.layout_navigator_id, out)
            say(f"Published to {out}")
    except (ArchicadError, FileNotFoundError, OSError, ValueError) as exc:
        say(f"Error: {exc}")
        return 1
    return 0 if not result.failed_checks else 3


if __name__ == "__main__":
    sys.exit(main())
