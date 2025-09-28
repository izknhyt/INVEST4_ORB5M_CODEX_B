#!/usr/bin/env python3
"""Prune old state archive files, keeping the latest N per leaf directory.

Leaf = ops/state_archive/<strategy>/<symbol>/<mode>/
Files are expected to be timestamp-prefixed JSON. We sort by filename and
remove older files beyond --keep.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List
import os


def list_leaf_dirs(base: Path) -> List[Path]:
    leaves: List[Path] = []
    if not base.exists():
        return leaves
    for strategy_dir in base.iterdir():
        if not strategy_dir.is_dir():
            continue
        for symbol_dir in strategy_dir.iterdir():
            if not symbol_dir.is_dir():
                continue
            for mode_dir in symbol_dir.iterdir():
                if mode_dir.is_dir():
                    leaves.append(mode_dir)
    return leaves


def prune_dir(leaf: Path, keep: int, dry_run: bool = False) -> int:
    files = sorted([p for p in leaf.glob("*.json") if p.is_file()])
    if len(files) <= keep:
        return 0
    to_delete = files[:-keep]
    removed = 0
    for f in to_delete:
        if dry_run:
            print(f"[prune] would remove {f}")
            removed += 1
            continue
        try:
            os.remove(f)
            print(f"[prune] removed {f}")
            removed += 1
        except OSError:
            pass
    return removed


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Prune old state archives, keep latest N per leaf")
    p.add_argument("--base", default="ops/state_archive", help="Base archive directory")
    p.add_argument("--keep", type=int, default=5, help="Number of latest files to keep per leaf (default 5)")
    p.add_argument("--dry-run", action="store_true", help="Do not delete; just print actions")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    base = Path(args.base)
    total_removed = 0
    for leaf in list_leaf_dirs(base):
        total_removed += prune_dir(leaf, args.keep, dry_run=args.dry_run)
    print({"removed": total_removed, "base": str(base), "keep": args.keep})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
