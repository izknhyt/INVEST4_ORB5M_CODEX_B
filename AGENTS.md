# Repo Agent Guidelines

## Shared Principles
- Keep all code comments, design notes, and commit messages in **English**, while final status summaries for collaborators remain in **Japanese**.
- Always answer in Japanese and provide full terminal commands without ellipses when suggesting shell usage.
- Review the project README, key design docs, and [docs/task_backlog.md](docs/task_backlog.md) at the start of work, then state the chosen task and definition of done.

## Workflow Expectations
1. Select a task from the P0/P1 backlog, and jot down the intended deliverables (code, docs, reports) in English notes.
2. Inspect directory-level READMEs or design specs to identify dependencies and required tests before changing files.
3. After implementation, run `python3 -m pytest` and add targeted validations such as `python3 scripts/run_sim.py --manifest configs/strategies/day_orb_5m.yaml --csv validated/USDJPY/5m.csv` when needed.
4. Update [docs/task_backlog.md](docs/task_backlog.md) and any related documents to reflect the completed work, adding links or commentary.
5. Write commit messages and PR descriptions in English covering task context, major changes, and executed tests, then summarize the PR in Japanese.

## Documentation & Operations
- Remove finished items from the backlog, and add new tasks with priorities (English allowed).
- Record new operational flows or parameter changes in the README and relevant runbooks, and share a Japanese synopsis.
- When updating critical outputs such as `runs/index.csv`, `reports/*`, or `ops/state_archive/*`, document the reason and reproduction steps in commits/PRs and be prepared to explain them in Japanese.
- Use [docs/task_backlog.md](docs/task_backlog.md) as the hub for ongoing task tracking and link back to supporting docs like `docs/state_runbook.md` or `readme/` design notes as appropriate.
