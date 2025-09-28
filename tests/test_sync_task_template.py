from pathlib import Path

import scripts.sync_task_docs as sync


ANCHOR = "docs/task_backlog.md#p9-99-test-task"


def _write_state(path: Path) -> None:
    path.write_text(
        """# Work State Log

## Workflow Rule
- dummy

## Next Task
- [P9-99] 2024-06-25 Test Task — DoD: [docs/task_backlog.md#p9-99-test-task](docs/task_backlog.md#p9-99-test-task)

## Log
""",
        encoding="utf-8",
    )


def _write_docs(path: Path) -> None:
    path.write_text(
        """# 次のアクション

## Current Pipeline

### In Progress
- **Test Task** — `state.md` 2024-06-25 <!-- anchor: docs/task_backlog.md#p9-99-test-task -->
  - DoD チェックリスト: [docs/templates/dod_checklist.md](docs/templates/dod_checklist.md) を [docs/checklists/p9-99.md](docs/checklists/p9-99.md) にコピーし、進捗リンクを更新する。
""",
        encoding="utf-8",
    )


def _write_ready_docs(path: Path) -> None:
    path.write_text(
        """# 次のアクション

## Current Pipeline

### Ready
- **Test Task** — `state.md` 2024-06-25 <!-- anchor: docs/task_backlog.md#p9-99-test-task -->
  - DoD チェックリスト: [docs/templates/dod_checklist.md](docs/templates/dod_checklist.md) を [docs/checklists/p9-99.md](docs/checklists/p9-99.md) にコピーし、進捗リンクを更新する。
""",
        encoding="utf-8",
    )


def _write_template(path: Path) -> None:
    path.write_text(
        """  - Backlog Anchor: [{{TITLE}} ({{TASK_ID}})]({{BACKLOG_ANCHOR}})
  - Vision / Runbook References:
    - [docs/logic_overview.md](docs/logic_overview.md)
    - [docs/simulation_plan.md](docs/simulation_plan.md)
    - 主要ランブック: {{RUNBOOK_LINKS}}
  - Pending Questions:
    - [ ] {{PENDING_QUESTIONS}}
""",
        encoding="utf-8",
    )


def test_apply_next_task_template_updates_state_and_docs(tmp_path, monkeypatch):
    state_path = tmp_path / "state.md"
    docs_path = tmp_path / "todo_next.md"
    template_path = tmp_path / "next_task_template.md"

    _write_state(state_path)
    _write_docs(docs_path)
    _write_template(template_path)

    monkeypatch.setattr(sync, "STATE_PATH", state_path)
    monkeypatch.setattr(sync, "DOCS_PATH", docs_path)

    sync.apply_next_task_template(
        ANCHOR,
        title="Test Task",
        task_id="P9-99",
        template_path=template_path,
        runbook_links="[docs/state_runbook.md](docs/state_runbook.md)",
        pending_questions="Clarify EV guardrails.",
    )

    state_lines = state_path.read_text(encoding="utf-8").splitlines()
    docs_lines = docs_path.read_text(encoding="utf-8").splitlines()

    assert any("Backlog Anchor: [Test Task (P9-99)]" in line for line in state_lines)
    assert any("docs/logic_overview.md" in line for line in state_lines)
    assert any("Clarify EV guardrails." in line for line in state_lines)

    in_progress_index = docs_lines.index("### In Progress")
    block_lines = docs_lines[in_progress_index + 1 :]
    assert any("Backlog Anchor: [Test Task (P9-99)]" in line for line in block_lines)
    assert any("docs/simulation_plan.md" in line for line in block_lines)
    assert any("Clarify EV guardrails." in line for line in block_lines)

    # Idempotent re-run should not duplicate template sections
    sync.apply_next_task_template(
        ANCHOR,
        title="Test Task",
        task_id="P9-99",
        template_path=template_path,
        runbook_links="[docs/state_runbook.md](docs/state_runbook.md)",
        pending_questions="Clarify EV guardrails.",
    )

    state_lines_second = state_path.read_text(encoding="utf-8").splitlines()
    assert state_lines_second.count("  - Backlog Anchor: [Test Task (P9-99)](docs/task_backlog.md#p9-99-test-task)") == 1


def test_apply_next_task_template_defaults_ready_section(tmp_path, monkeypatch):
    state_path = tmp_path / "state.md"
    docs_path = tmp_path / "todo_next.md"
    template_path = tmp_path / "next_task_template.md"

    _write_state(state_path)
    _write_ready_docs(docs_path)
    _write_template(template_path)

    monkeypatch.setattr(sync, "STATE_PATH", state_path)
    monkeypatch.setattr(sync, "DOCS_PATH", docs_path)

    sync.apply_next_task_template(
        ANCHOR,
        title="Test Task",
        task_id="P9-99",
        template_path=template_path,
    )

    docs_lines = docs_path.read_text(encoding="utf-8").splitlines()
    ready_index = docs_lines.index("### Ready")
    block_lines = docs_lines[ready_index + 1 :]
    assert any(
        "[docs/state_runbook.md](docs/state_runbook.md)" in line for line in block_lines
    )
    assert any(
        "Clarify gating metrics, data dependencies, or open questions." in line
        for line in block_lines
    )
