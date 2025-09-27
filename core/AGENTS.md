# Core Module Guidelines

- Follow PEP 8 formatting and include type hints for new or modified code.
- Add or update unit tests that cover the affected modules; coordinate with [`tests/test_runner.py`](../tests/test_runner.py) and related suites.
- After changes, execute `python3 -m pytest` (or targeted subsets) to confirm the core logic passes.
- Reference the backlog at [../docs/task_backlog.md](../docs/task_backlog.md) to ensure core updates align with current priorities.
