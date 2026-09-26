from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

from type_crap.checker import CODES, check_source


def _excluded(p: Path, patterns: list[str]) -> bool:
    return any(
        fnmatch.fnmatch(p.as_posix(), pat) or any(fnmatch.fnmatch(part, pat) for part in p.parts)
        for pat in patterns
    )


def _iter_files(paths: list[Path], exclude: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(f for f in sorted(p.rglob("*.py")) if not _excluded(f, exclude))
        else:
            files.append(p)
    return files


def _codes(spec: str) -> set[str]:
    """`NU001,RD` -> codes; a bare prefix selects its whole family."""
    out: set[str] = set()
    for c in (c.strip().upper() for c in spec.split(",")):
        if c:
            out |= {k for k in CODES if k.startswith(c)}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="type-crap",
        description="Flag type annotations that lie (NU***) and code that re-implements what "
        "Python already does or ports patterns from other languages (RD***). See README.",
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
        default="",
        help="comma-separated codes or prefixes to report, e.g. NU,RD004 (default: all)",
    )
    ap.add_argument(
        "--ignore",
        default="",
        help="comma-separated codes or prefixes to skip, e.g. RD006,RD01",
    )
    ap.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="skip files/dirs matching this glob when walking directories (repeatable)",
    )
    ns = ap.parse_args(argv)
    selected = (_codes(ns.select) if ns.select else set(CODES)) - _codes(ns.ignore)

    files = _iter_files(ns.paths, ns.exclude)
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
