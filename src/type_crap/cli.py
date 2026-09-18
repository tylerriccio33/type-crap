from __future__ import annotations

import argparse
import sys
from pathlib import Path

from type_crap.checker import check_source


def _iter_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.py")))
        else:
            files.append(p)
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="type-crap",
        description="Flag `X | None` params/returns that are lies: None-passthrough (NU001), "
        "params rejected on None (NU002), `| None` returns that can't return None (NU003), "
        "`| None` params dereferenced with no None check (NU004).",
    )
    ap.add_argument("paths", nargs="+", type=Path, help="files or directories")
    ap.add_argument(
        "--loose",
        action="store_true",
        help="treat unknown calls/attribute reads as non-None "
        "(more NU003 candidates, more false positives)",
    )
    ap.add_argument(
        "--select",
        default="NU001,NU002,NU003,NU004",
        help="comma-separated rule codes to report (default: all)",
    )
    ns = ap.parse_args(argv)
    selected = {c.strip().upper() for c in ns.select.split(",") if c.strip()}

    files = _iter_files(ns.paths)
    findings = []
    for f in files:
        try:
            findings.extend(
                x for x in check_source(f, f.read_text(), loose=ns.loose) if x.code in selected
            )
        except SyntaxError as e:
            print(f"{f}: skipped ({e})", file=sys.stderr)
    for x in findings:
        print(x)
    print(f"{len(findings)} finding(s) in {len(files)} file(s)", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
