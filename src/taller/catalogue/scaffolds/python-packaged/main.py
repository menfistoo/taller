"""%%name%%: the entry point. Importing this module runs nothing."""
# %%description%%

import argparse
import sys

VERSION = "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="%%name%%")
    parser.add_argument("--version", action="store_true", help="print the version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"%%name%% {VERSION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
