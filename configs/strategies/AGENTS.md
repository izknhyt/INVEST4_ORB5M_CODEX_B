# Strategy Config Guidelines

- Follow the manifest specification in [`configs/strategies/README.md`](README.md) when adding or updating YAML files.
- Validate manifests with `python3 -m pytest tests/test_strategy_manifest.py` before committing.
- Link any configuration changes back to relevant items in [../../docs/task_backlog.md](../../docs/task_backlog.md) so reviewers understand the motivation.
