# Codex Cloud Operations Notes

This memo summarizes additional guardrails for Codex sessions running in
cloud or restricted environments (e.g., read-only filesystem, no network).
Leverage it alongside `docs/codex_workflow.md` when planning a new sprint.

## Environment Assumptions
- Filesystem may be read-only or limited to an overlay; treat write failures
  as expected and capture intended patches for manual application later.
- External network calls (API hits, package installs) can be blocked. Prefer
  dry-run simulations, mocks, or explicit TODO notes that describe required
  CLI execution outside the sandbox.
- Long-running jobs are discouraged; keep commands concise and reproducible.

## Task Planning Checklist
1. Confirm backlog priorities (`docs/task_backlog.md`) and mark blockers that
   require writable or network-enabled runs. Capture them as subtasks.
2. Draft deliverables in English (doc patches, design notes, diff snippets)
   so they can be applied manually when moving to a writable environment.
3. For each CLI mentioned in DoD, provide an alternative validation strategy:
   - reference existing run logs or snapshot JSONs;
   - supply command lines but annotate them as "execute locally";
   - include expected outputs or acceptance criteria in the task notes.
4. When creating new files, prefer ASCII and lightweight formatting so the
   diff is easy to copy.

## Documentation & Communication
- Update `state.md` and `docs/todo_next.md` even if changes are descriptive
  (no code edits). These logs keep subsequent sessions aligned.
- When commands cannot be executed, note the limitation explicitly and link
  to this memo so downstream operators understand the context.
- Mention fallback steps in checklists (e.g., "if webhook fails in sandbox,
  verify via log entries"), especially for alerting or external integrations.

## Handoff Template (per task)
- **Planned changes:** bullet list of code/doc updates with rationale.
- **Blocked/external steps:** commands or scripts requiring real environment.
- **Validation plan:** how to confirm success once the task runs on-prem.
- **Artifacts:** paths to design docs, checklists, or diffs created during the
  cloud session.

## Common Pitfalls
- Forgetting to re-run freshness or benchmark checks after switching to a
  writable machine. Always include `python3 scripts/check_benchmark_freshness.py`
  in the handoff notes when relevant.
- Overlooking secrets management: never paste keys into the repo. Instead,
  reference the expected secret names (`configs/api_keys.yml`) and note where
  to load them in production.
- Leaving backlog entries ambiguous. Ensure every "In Progress" item lists
  explicit next steps so the next session can resume without guesswork.

Refer back to this memo whenever the sandbox limitations change or new
constraints are introduced.
