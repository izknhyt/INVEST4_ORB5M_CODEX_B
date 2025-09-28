import subprocess
import sys
from pathlib import Path

import pytest

from scripts import manage_task_cycle as manage

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "manage_task_cycle.py"


@pytest.mark.parametrize("anchor", ["docs/task_backlog.md#p9-99-test-task"])
def test_start_task_dry_run_outputs_commands(anchor: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dry-run",
            "start-task",
            "--anchor",
            anchor,
            "--record-date",
            "2024-06-25",
            "--promote-date",
            "2024-06-26",
            "--task-id",
            "P9-99",
            "--title",
            "Test Task",
            "--state-note",
            "Initial planning",
            "--doc-note",
            "Ready to start",
            "--doc-section",
            "Ready",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    stdout = result.stdout.strip().splitlines()
    assert any("sync_task_docs.py record" in line for line in stdout)
    assert any("sync_task_docs.py promote" in line for line in stdout)
    assert all(line.startswith("[dry-run]") for line in stdout if line)


def test_finish_task_dry_run_outputs_command() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dry-run",
            "finish-task",
            "--anchor",
            "docs/task_backlog.md#p9-99-test-task",
            "--date",
            "2024-06-27",
            "--note",
            "Completed validation",
            "--task-id",
            "P9-99",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    stdout = result.stdout.strip().splitlines()
    assert any("sync_task_docs.py complete" in line for line in stdout)
    assert all(line.startswith("[dry-run]") for line in stdout if line)


def test_start_task_passes_template_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(manage, "_run_commands", lambda commands, dry_run: None)

    def _fake_apply(anchor: str, **kwargs: object) -> None:
        captured["anchor"] = anchor
        captured.update(kwargs)

    monkeypatch.setattr(manage.sync, "apply_next_task_template", _fake_apply)

    manage.main(
        [
            "start-task",
            "--anchor",
            "docs/task_backlog.md#p9-99-test-task",
            "--record-date",
            "2024-06-25",
            "--promote-date",
            "2024-06-26",
            "--task-id",
            "P9-99",
            "--title",
            "Test Task",
            "--doc-section",
            "Ready",
            "--state-note",
            "Planning context",
            "--doc-note",
            "Docs memo",
            "--runbook-links",
            "[docs/custom_runbook.md](docs/custom_runbook.md)",
            "--pending-questions",
            "Validate rolling benchmark data freshness.",
        ]
    )

    assert captured["anchor"] == "docs/task_backlog.md#p9-99-test-task"
    assert captured["title"] == "Test Task"
    assert captured["task_id"] == "P9-99"
    assert captured["runbook_links"] == "[docs/custom_runbook.md](docs/custom_runbook.md)"
    assert captured["pending_questions"] == "Validate rolling benchmark data freshness."
