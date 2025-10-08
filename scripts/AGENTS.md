# Scripts Guidelines

- Maintain CLI compatibility and avoid breaking existing arguments or defaults.
- Ensure usage examples referenced in `README.md` or script-specific docs continue to run as written.
- Run scenario-appropriate commands such as `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv` when validating changes.
- Check [../docs/task_backlog.md](../docs/task_backlog.md) for context on operational scripts that may need updates alongside code changes.
