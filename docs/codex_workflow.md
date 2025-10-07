# Codex Session Operations Guide

This guide compresses everything Codex agents need to keep tasks moving without losing context. Use it together with `docs/state_runbook.md` (state sync details) and `docs/task_backlog.md` (priorities / DoD).

## TL;DR Quickstart
1. **Read the ground truth.** Open `state.md` → note the active `Next Task`, open questions, approvals in flight. Jump to the matching anchor in `docs/task_backlog.md` to confirm DoD/priority.
2. **Pick or promote the task.** If the task is not under `In Progress`, run a dry-run of the start helper to validate anchors and dates:
   ```bash
   python3 scripts/manage_task_cycle.py --dry-run start-task \
       --anchor <docs/task_backlog.md#anchor> \
       --record-date <YYYY-MM-DD> --promote-date <YYYY-MM-DD> \
       --task-id <ID> --title "<Task Title>" \
       --state-note "<One-line status>" \
       --doc-note "<docs/todo_next.md note>" \
       --doc-section <Ready|In Progress|Pending Review>
   ```
   Remove `--dry-run` once the preview looks correct.
3. **Work in small slices.** After every substantive change: update docs, run targeted tests (see below), and log findings back in `state.md` / `docs/todo_next.md` before switching context.
4. **Wrap up.** Use `scripts/manage_task_cycle.py finish-task` (dry-run first) so `state.md`, `docs/todo_next.md`, and the backlog stay synchronized. Note any approvals granted/denied.

### Rapid test matrix
Run the smallest relevant tests before handing off a change. Keep these commands handy:

```
python3 -m pytest tests/test_run_sim_cli.py           # run_sim / CLI changes
python3 -m pytest tests/test_runner.py                # BacktestRunner core
python3 -m pytest tests/test_run_daily_workflow.py    # daily workflow pipeline
python3 -m pytest                                      # full sweep when time allows
```

## Session Loop (Expanded)

### 1. Pre-session
- Read `state.md` → `Next Task`, pending approvals, open questions.
- Cross-check `docs/task_backlog.md` (DoD) and `docs/todo_next.md` (current section). Keep anchors consistent.
- Duplicate templates when needed:
  - `docs/templates/next_task_entry.md` → new `state.md` entry.
  - `docs/templates/dod_checklist.md` → `docs/checklists/<task-slug>.md`.
- Confirm sandbox context from the IDE payload.

### 2. While implementing
- Default goal: P0/P1 backlog first. If new work emerges, add it to the backlog with priority before starting.
- Keep diffs tight; favour feature flags for risky refactors. Document flags in README/config comments.
- Record approvals in the active memo: command requested, reason, outcome.
- When touching data products (`runs/index.csv`, `reports/*`, `ops/state_archive/*`), log reproduction steps in the same commit notes and be prepared to explain in Japanese.

### 3. Wrap-up
- Update `state.md` (`Next Task` cleared or moved), `docs/todo_next.md` (archive/memo), and the backlog (remove finished tasks once archived elsewhere).
- Capture verification evidence (tests run, sample commands) directly in the session summary.
- Leave `docs/task_backlog.md` with only open tasks—completed entries should move into state/todo logs instead of lingering here.

## Sandbox & Approval Guardrails
- Default harness: `workspace-write` filesystem, `restricted` network, approvals `on-request`.
- Request approval before: installing packages, hitting external APIs, writing outside the repo, rerunning destructive git commands, or reissuing a command that failed due to sandboxing.
- Document every approval attempt (whether granted or not) in `state.md`.
- If the harness runs in read-only mode, plan changes as patches to share with the user; be explicit about files touched.

## Command Cheatsheet

| Purpose | Command |
| --- | --- |
| Start task (preview) | `python3 scripts/manage_task_cycle.py --dry-run start-task ...` |
| Start task (apply) | `python3 scripts/manage_task_cycle.py start-task ...` |
| Promote Ready → In Progress | `python3 scripts/manage_task_cycle.py promote ...` |
| Finish task (preview) | `python3 scripts/manage_task_cycle.py --dry-run finish-task ...` |
| Finish task (apply) | `python3 scripts/manage_task_cycle.py finish-task ...` |
| Sync state/todo manually | `python3 scripts/sync_task_docs.py record|promote|complete ...` |
| Quick pytest (CLI) | `python3 -m pytest tests/test_run_sim_cli.py` |
| Full pytest | `python3 -m pytest` |


## Reference Map
- `docs/state_runbook.md` — deep dive on state synchronization, archival rules, failure recovery.
- `docs/task_backlog.md` — authoritative list of active work and DoD; remove completed items promptly.
- `docs/todo_next.md` — near-term actions and parking-lot notes.
- `docs/codex_cloud_notes.md` — cloud sandbox tips, approval examples.
- `docs/checklists/*` — task-specific checklists (link from backlog entries as needed).
- `docs/development_roadmap.md` — phased improvement plan (immediate→long-term) tied back to backlog anchors.

Keep this document close at hand; if the process drifts, update it before starting more tasks so every Codex session inherits the same guardrails.
