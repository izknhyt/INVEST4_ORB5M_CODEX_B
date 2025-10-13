# Diff Artefact Guide

This directory collects machine-generated comparison artefacts for the Phase 4
Day ORB regression runs. The workflow mirrors the guard rails in
[docs/plans/phase4_sim_bugfix_plan.md](../../docs/plans/phase4_sim_bugfix_plan.md#w1--baseline-reproducibility)
and keeps reviewers from re-running long simulations just to inspect metric
changes.

## File layout conventions

| Path pattern | Contents | Notes |
| --- | --- | --- |
| `reports/diffs/<mode>_metrics.json` | Structured diff of two `metrics.json` files | Generated via `scripts/compare_metrics.py` and committed when a change exits code review. |
| `reports/diffs/<mode>_daily.json` | Optional diff of `*_daily.csv` aggregates | Use when daily win-rate deltas require explicit review context. |
| `reports/diffs/<mode>_*.log` | Captured stdout/stderr snippets | Attach excerpts when CLI output explains expected deltas (e.g., auto-state skips). |

Use ISO-like suffixes (e.g., `_20250805`) when multiple diff passes are needed
for the same mode.

## Recommended commands

1. Generate a metrics diff with tolerances that match the plan:
   ```bash
   python3 scripts/compare_metrics.py \
     --left runs/phase4/backtests/<gold>/metrics.json \
     --right runs/phase4/backtests/<candidate>/metrics.json \
     --ignore state_loaded --ignore state_saved \
     --abs-tolerance 0.0001 --rel-tolerance 0.0005 \
     --out-json reports/diffs/<mode>_metrics.json
   ```
2. When daily CSV changes require inspection, convert both CSV files to JSON
   maps keyed by timestamp before diffing. An inline helper works well for
   ad-hoc reviews:
   ```bash
   python3 - <<'PY_HELPER'
   import csv, json
   def convert(path):
       with open(path, newline='', encoding='utf-8') as handle:
           reader = csv.DictReader(handle)
           return {row['timestamp']: row for row in reader}
   payload = {
       'left': convert('reports/long_<mode>_daily.csv'),
       'right': convert('runs/phase4/backtests/<candidate>/daily.csv'),
   }
   for label, data in payload.items():
       with open(f'reports/diffs/{label}_daily_tmp.json', 'w', encoding='utf-8') as handle:
           json.dump(data, handle, indent=2, sort_keys=True)
   PY_HELPER
   python3 scripts/compare_metrics.py \
     --left reports/diffs/left_daily_tmp.json \
     --right reports/diffs/right_daily_tmp.json \
     --out-json reports/diffs/<mode>_daily.json
   ```
   Keep the intermediate JSON files until the review concludes so auditors can
   replay the conversion if needed. Repository-level `.gitignore` entries in this
   directory ignore `*_tmp.json` artefacts by default.

## Documentation checklist

- Link each saved diff from the corresponding entry in
  `docs/progress_phase4.md` (W1 Step 4) and cite the `reports/diffs/README.md`
  workflow when describing review evidence.
- Record SHA256 hashes for the source artefacts in `state.md` alongside the
  diff command so future sessions can revalidate without recomputing.
- Update `docs/task_backlog.md#p4-01-長期バックテスト改善` notes whenever new
  diff artefacts land to keep backlog reviewers aware of the comparison trail.

## Review expectations

A diff artefact may be committed with outstanding discrepancies only when:

1. Every `significant_differences` entry is explained in `docs/progress_phase4.md`.
2. The regression suite (`python3 -m pytest`) has been executed for the change.
3. The corresponding bug notebook row references the diff file path.

If these conditions are not met, stash the diff locally and repeat the analysis
after addressing the blocking issues.
