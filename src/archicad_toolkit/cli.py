"""Command-line entry point: ``archicad-toolkit <command> ...``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from archicad_toolkit.client import DEFAULT_URL, ArchicadError, TapirClient, http_transport
from archicad_toolkit.commands.duplicate_to_option import (
    DEFAULT_PROPERTY_GROUP,
    DEFAULT_PROPERTY_NAME,
    duplicate_to_option,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archicad-toolkit")
    parser.add_argument("--url", default=DEFAULT_URL, help="Archicad JSON API address")
    sub = parser.add_subparsers(dest="command", required=True)

    dup = sub.add_parser(
        "duplicate-to-option", help="Copy the selected elements into a design option"
    )
    dup.add_argument("option", help='Name of the new option, e.g. "Option B"')
    dup.add_argument(
        "--offset", nargs=3, type=float, default=(0.0, 0.0, 0.0), metavar=("X", "Y", "Z"),
        help="Move the copies by this vector in metres (default: copy in place)",
    )
    dup.add_argument("--property-group", default=DEFAULT_PROPERTY_GROUP)
    dup.add_argument("--property-name", default=DEFAULT_PROPERTY_NAME)
    dup.add_argument(
        "--tag-originals", metavar="NAME",
        help='Also tag the selected originals, e.g. "Option A"',
    )

    board = sub.add_parser("build-board", help="Build or rebuild a presentation board layout")
    board.add_argument("config", type=Path, help="Board config JSON, e.g. boards/pres-01/board.json")
    board.add_argument("--assets", type=Path, required=True, help="Folder with the prepared images")
    board.add_argument("--gsm", type=Path, required=True, help="Compiled PRES_Image2D.gsm")
    board.add_argument("--manifest", type=Path, help="Where to keep the element manifest (default: next to the config)")
    board.add_argument("--publish", type=Path, metavar="DIR", help="Also publish the layout to this folder")
    return parser


def main(argv: list[str] | None = None, client: TapirClient | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = client or TapirClient(http_transport(args.url))
    try:
        if args.command == "duplicate-to-option":
            result = duplicate_to_option(
                client,
                args.option,
                offset=tuple(args.offset),
                property_group=args.property_group,
                property_name=args.property_name,
                tag_originals=args.tag_originals,
            )
            print(
                f"Created {len(result.copy_guids)} element(s) in option '{result.option}'."
            )
            for warning in result.warnings:
                print(f"Warning: {warning}", file=sys.stderr)
        elif args.command == "build-board":
            from archicad_toolkit.presentation import build_board, publish_layout

            cfg = json.loads(args.config.read_text(encoding="utf-8"))
            manifest = args.manifest or args.config.with_name("manifest.json")
            board = build_board(client, cfg, assets_dir=args.assets, gsm=args.gsm, manifest_path=manifest)
            elements = sum(len(v) for v in board.created.values())
            print(f"Built {cfg['layout']['id']}: {elements} element(s), replaced {board.removed}.")
            for check in board.failed_checks:
                print(f"Check failed: {check}", file=sys.stderr)
            for warning in board.warnings:
                print(f"Warning: {warning}", file=sys.stderr)
            (manifest.with_name("checks.json")).write_text(json.dumps(board.checks, indent=2), encoding="utf-8")
            if args.publish:
                publish_layout(client, cfg["layout"]["publisher_set"], board.layout_navigator_id, args.publish)
                print(f"Published to {args.publish}")
    except (ArchicadError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
