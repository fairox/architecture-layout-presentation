"""Command-line entry point: ``archicad-toolkit <command> ...``."""

from __future__ import annotations

import argparse
import sys

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
    except (ArchicadError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
