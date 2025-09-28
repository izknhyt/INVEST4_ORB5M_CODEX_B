import subprocess
import sys
from pathlib import Path

import pytest

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
