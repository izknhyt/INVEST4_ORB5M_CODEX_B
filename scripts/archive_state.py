#!/usr/bin/env python3
"""Archive state.json files for later restoration."""
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Archive state.json from runs directory")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--output", default="ops/state_archive")
    return p.parse_args(argv)


def archive(runs_dir: Path, output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    archives = 0
    for state_file in runs_dir.glob("**/state.json"):
        try:
            content = state_file.read_text(encoding="utf-8")
        except Exception:
            continue
        target = output_dir / f"{state_file.parent.name}_{now}.json"
        target.write_text(content, encoding="utf-8")
        archives += 1
    return archives


def main(argv=None) -> int:
    args = parse_args(argv)
    runs_dir = Path(args.runs_dir)
    output_dir = Path(args.output)
    count = archive(runs_dir, output_dir)
    print(json.dumps({"archived": count, "output": str(output_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
