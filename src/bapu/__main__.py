"""``python -m bapu <tool> [args]``: run a tool without its console script."""

from __future__ import annotations

import sys

from . import __version__

TOOLS = {
    "gate": ("bapu.gate", "check OpenSpec delta specs clause by clause"),
    "seedred": ("bapu.seedred", "prove tests by planting the defect each one guards"),
    "findings": ("bapu.findings", "check that review findings quote their evidence"),
}

USAGE = "usage: python -m bapu {gate,seedred,findings} [args]\n\n" + "\n".join(
    f"  {name:<9} {summary}" for name, (_, summary) in TOOLS.items()
)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if args else 2
    if args[0] == "--version":
        print(f"bapu {__version__}")
        return 0
    if args[0] not in TOOLS:
        print(f"unknown tool {args[0]!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    module = __import__(TOOLS[args[0]][0], fromlist=["main"])
    return int(module.main(args[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
