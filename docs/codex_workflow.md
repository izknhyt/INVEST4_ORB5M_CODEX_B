# Codex Session Operations Guide

This guide summarizes the routine Codex agents should follow to keep tasks moving continuously while maintaining alignment between `state.md`, `docs/task_backlog.md`, and `docs/todo_next.md`. It also highlights how to rely on `scripts/manage_task_cycle.py` so that each session preserves the same context.

## Core References
- **state.md** — Primary source for the latest `Next Task`, completion log, and operational notes. Always read and update it before and after work.
- **docs/task_backlog.md** — Lists priorities and definitions of done. Use its anchors from `state.md`/`docs/todo_next.md` to share progress links.
- **docs/todo_next.md** — Organizes practical next actions across In Progress, Ready, Pending Review, and Archive.
- **docs/templates/** — Home of reusable templates such as `next_task_entry.md` and `dod_checklist.md` that Codex applies automatically.
- **docs/checklists/p1-07_phase1_bug_refactor.md** — Checklist and tracking templates dedicated to Phase 1 bug investigations and refactoring planning. Use it to record module-level coverage, refactor candidates, and follow-up notes.
- **docs/state_runbook.md** — Baseline operational runbook for state synchronization and archive handling.
- **docs/codex_cloud_notes.md** — Additional guardrails when running in read-only or network-restricted cloud sandboxes.

## Pre-session Routine
1. **Review the current situation**  
   Read `state.md`, focusing on the `Next Task` entry and any outstanding questions or linked checklists.
2. **Confirm the backlog anchor**  
   Pick the target task from `docs/task_backlog.md`, record its DoD, and verify whether it is already marked Ready in `docs/todo_next.md`.
3. **Prepare templates**  
   When adding a new `Next Task`, start from `docs/templates/next_task_entry.md`. For Ready tasks, duplicate `docs/templates/dod_checklist.md` into `docs/checklists/<task-slug>.md`.
4. **Dry-run the start command**  
   Execute the following command with `--dry-run` to validate anchors and dates before making real changes.
   ```bash
   python3 scripts/manage_task_cycle.py --dry-run start-task \
       --anchor <docs/task_backlog.md#anchor> \
       --record-date <YYYY-MM-DD> \
       --promote-date <YYYY-MM-DD> \
       --task-id <ID> \
       --title "<Task Title>" \
       --state-note "<State entry memo>" \
       --doc-note "<docs/todo_next.md memo>" \
       --doc-section <Ready|In Progress> \
       [--runbook-links "<Markdown links for runbooks>"] \
       [--pending-questions "<Key questions to track>"]
   ```
   After confirming the preview, rerun the command without `--dry-run` to populate `state.md` and `docs/todo_next.md` with the appropriate template blocks.
   - Use `--runbook-links` to override the default `[docs/state_runbook.md](docs/state_runbook.md)` reference when another runbook is more relevant.
   - Provide `--pending-questions` to seed the checklist item that appears under "Pending Questions" in the template so the next session inherits the right context.

## Task Execution Loop
### 1. At task start
- Complete the template block inserted in `state.md` by summarizing context, external links, and open questions.
- Add references to related runbooks or specifications (for example, `docs/logic_overview.md`) when extra background is required.
- For any new subtasks, append anchor-backed notes to `docs/task_backlog.md` and cross-link them from `state.md`.

### 2. During implementation and validation
- Check the `AGENTS.md` file in each directory before editing to respect style and testing requirements.
- Record insights or unresolved issues in the active task memo inside `state.md`, or in the relevant entry within `docs/todo_next.md`.
- After significant changes, run `python3 -m pytest` or the appropriate CLI command. Capture the executed commands in your notes so the next session can reproduce them.
- For broad bug-review or refactoring sweeps, mirror your progress in `docs/checklists/p1-07_phase1_bug_refactor.md` so each session inherits the latest checklist status and candidate list.

### 3. Closing the task
1. Run `python3 scripts/manage_task_cycle.py --dry-run finish-task ...` to preview what will be moved into the log.
   ```bash
   python3 scripts/manage_task_cycle.py --dry-run finish-task \
       --anchor <docs/task_backlog.md#anchor> \
       --date <YYYY-MM-DD> \
       --note "<Completion summary for state.md log>" \
       --task-id <ID>
   ```
2. If the dry run looks correct, rerun without `--dry-run` so `state.md` (`## Log`) and `docs/todo_next.md` update in tandem.
3. Update the DoD checklist, archive it when done, and add links to `docs/task_backlog.md` or the relevant runbook.
4. Provide a Japanese summary in the final Codex response, including executed test commands and any follow-up actions.

## Ongoing Tips
- **Chaining tasks:** List candidate follow-up tasks in the memo section of `state.md`; reuse these notes when preparing the next `start-task` command.
- **Tracking questions:** Log open questions inside `docs/todo_next.md`. Move them to Archive once resolved so the conversation history stays searchable.
- **Updating scripts:** Whenever `scripts/manage_task_cycle.py` or `scripts/sync_task_docs.py` changes, capture new dry-run output samples in `docs/state_runbook.md` or related READMEs so Codex can adopt new flags.
- **Commits and PRs:** Keep commit messages and PR descriptions in English. Summaries sent back to collaborators should remain in Japanese per repo conventions.

## Quick Reference
| Action | Recommended command |
| --- | --- |
| Start task dry run | `python3 scripts/manage_task_cycle.py --dry-run start-task --anchor docs/task_backlog.md#<anchor> ...` |
| Finish task dry run | `python3 scripts/manage_task_cycle.py --dry-run finish-task --anchor docs/task_backlog.md#<anchor> ...` |
| Create DoD checklist | `cp docs/templates/dod_checklist.md docs/checklists/<task-slug>.md` |
| Review the state runbook | `open docs/state_runbook.md` |
| Run tests | `python3 -m pytest` |

Following this guide keeps `state.md` and the documents in `docs/` synchronized, preserving continuity and reproducibility across Codex sessions.
