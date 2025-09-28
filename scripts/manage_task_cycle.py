"""CLI helper orchestrating task lifecycle updates.

This utility wraps ``scripts/sync_task_docs.py`` and provides higher-level
operations for day-to-day task management.  The ``start-task`` command records a
new entry (if missing) and promotes it into "In Progress", while
``finish-task`` marks completion.  All parameters are validated and the
underlying commands are echoed so operators can confirm the actions before
execution.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import sync_task_docs as sync


SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_task_docs.py"


class InputError(RuntimeError):
    """Raised when a required interactive value is missing."""


@dataclass
class StartParams:
    anchor: str
    record_date: str
    promote_date: str
    task_id: str
    title: str
    state_note: str | None
    doc_note: str | None
    doc_section: str
    skip_record: bool
    runbook_links: str | None
    pending_questions: str | None


@dataclass
class FinishParams:
    anchor: str
    date: str
    note: str
    task_id: str | None


def _parse_date(value: str) -> str:
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:  # pragma: no cover - argparse handles this
        raise argparse.ArgumentTypeError(str(exc))


def _validate_anchor(value: str) -> str:
    try:
        return sync.normalize_anchor(value)
    except sync.SyncError as exc:  # pragma: no cover - argparse handles this
        raise argparse.ArgumentTypeError(str(exc))


def _prompt(text: str, default: str | None = None, optional: bool = False) -> str | None:
    prompt = text
    if default:
        prompt = f"{prompt} [{default}]"
    prompt = f"{prompt}: "
    while True:
        try:
            raw = input(prompt)
        except EOFError as exc:
            raise InputError("Interactive input cancelled") from exc
        value = raw.strip()
        if not value:
            if default is not None:
                return default
            if optional:
                return None
            print("Value required. Please provide an input.")
            continue
        return value


def _prompt_date(label: str, default: str | None = None) -> str:
    while True:
        raw = _prompt(label, default=default)
        assert raw is not None
        try:
            return _parse_date(raw)
        except argparse.ArgumentTypeError as exc:
            print(f"Invalid date: {exc}. Expected format YYYY-MM-DD.")


def _prompt_anchor(default: str | None = None) -> str:
    while True:
        raw = _prompt("Task anchor (docs/task_backlog.md#...)", default=default)
        assert raw is not None
        try:
            return _validate_anchor(raw)
        except argparse.ArgumentTypeError as exc:
            print(f"Invalid anchor: {exc}")


def _anchor_in_state(anchor: str) -> bool:
    try:
        lines = sync.read_lines(sync.STATE_PATH)
    except FileNotFoundError:
        return False
    try:
        start, end = sync.section_bounds(lines, "Next Task", 2)
    except sync.SyncError:
        return False
    return any(anchor in line for line in lines[start:end])


def _anchor_in_docs(anchor: str) -> bool:
    try:
        lines = sync.read_lines(sync.DOCS_PATH)
    except FileNotFoundError:
        return False
    return any(anchor in line for line in lines)


def _build_command(*parts: Iterable[str]) -> List[str]:
    cmd: List[str] = []
    for segment in parts:
        if isinstance(segment, str):
            cmd.append(segment)
        else:
            cmd.extend(segment)
    return cmd


def _run_commands(commands: Sequence[List[str]], dry_run: bool) -> None:
    for cmd in commands:
        rendered = shlex.join(cmd)
        if dry_run:
            print(f"[dry-run] {rendered}")
            continue
        print(f"Executing: {rendered}")
        subprocess.run(cmd, check=True)


def _collect_start_params(args: argparse.Namespace) -> StartParams:
    today = dt.date.today().isoformat()
    anchor = args.anchor or _prompt_anchor()
    anchor = _validate_anchor(anchor)

    record_date = args.record_date or _prompt_date("Record date (YYYY-MM-DD)", default=today)
    promote_default = args.promote_date or record_date
    promote_date = args.promote_date or _prompt_date("Promote date (YYYY-MM-DD)", default=promote_default)

    task_id = args.task_id or _prompt("Task ID")
    title = args.title or _prompt("Task title")
    state_note = args.state_note or _prompt("State note (optional)", optional=True)
    doc_note = args.doc_note or _prompt("Docs note (optional)", optional=True)

    doc_section = args.doc_section
    if doc_section is None:
        doc_section = _prompt(
            "Docs section for initial record [Ready/In Progress/Pending Review]",
            default="Ready",
        )
    doc_section = doc_section.strip()
    if doc_section not in {"Ready", "In Progress", "Pending Review"}:
        raise InputError("Docs section must be one of Ready, In Progress, Pending Review")

    skip_record = bool(args.skip_record)
    runbook_links = args.runbook_links
    pending_questions = args.pending_questions
    return StartParams(
        anchor=anchor,
        record_date=_parse_date(record_date),
        promote_date=_parse_date(promote_date),
        task_id=task_id,
        title=title,
        state_note=state_note,
        doc_note=doc_note,
        doc_section=doc_section,
        skip_record=skip_record,
        runbook_links=runbook_links,
        pending_questions=pending_questions,
    )


def _collect_finish_params(args: argparse.Namespace) -> FinishParams:
    today = dt.date.today().isoformat()
    anchor = args.anchor or _prompt_anchor()
    anchor = _validate_anchor(anchor)
    date = args.date or _prompt_date("Completion date (YYYY-MM-DD)", default=today)
    note = args.note or _prompt("Completion summary note")
    task_id = args.task_id or _prompt("Task ID override (optional)", optional=True)
    return FinishParams(
        anchor=anchor,
        date=_parse_date(date),
        note=note,
        task_id=task_id,
    )


def _build_start_commands(params: StartParams) -> List[List[str]]:
    commands: List[List[str]] = []
    anchor_present = _anchor_in_state(params.anchor) or _anchor_in_docs(params.anchor)

    if params.skip_record:
        print("Skipping record step (requested via --skip-record).")
    elif anchor_present:
        print("Anchor already present; skipping record step to avoid duplicates.")
    else:
        record_cmd = _build_command(
            [sys.executable, str(SYNC_SCRIPT), "record"],
            ["--anchor", params.anchor],
            ["--date", params.record_date],
            ["--task-id", params.task_id],
            ["--title", params.title],
        )
        if params.state_note:
            record_cmd.extend(["--note", params.state_note])
        if params.doc_note:
            record_cmd.extend(["--doc-note", params.doc_note])
        if params.doc_section and params.doc_section != "Ready":
            record_cmd.extend(["--doc-section", params.doc_section])
        commands.append(record_cmd)

    promote_cmd = _build_command(
        [sys.executable, str(SYNC_SCRIPT), "promote"],
        ["--anchor", params.anchor],
        ["--date", params.promote_date],
        ["--task-id", params.task_id],
        ["--title", params.title],
    )
    if params.state_note:
        promote_cmd.extend(["--note", params.state_note])
    commands.append(promote_cmd)
    return commands


def _build_finish_commands(params: FinishParams) -> List[List[str]]:
    complete_cmd = _build_command(
        [sys.executable, str(SYNC_SCRIPT), "complete"],
        ["--anchor", params.anchor],
        ["--date", params.date],
        ["--note", params.note],
    )
    if params.task_id:
        complete_cmd.extend(["--task-id", params.task_id])
    return [complete_cmd]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage task lifecycle across state.md and docs/todo_next.md")
    parser.add_argument("--dry-run", action="store_true", help="Print the generated commands without executing them")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start-task", help="Record and promote a task")
    start.add_argument("--anchor", help="Task DoD anchor (docs/task_backlog.md#...)")
    start.add_argument("--record-date", help="Date used when recording the task")
    start.add_argument("--promote-date", help="Date used for promotion into In Progress")
    start.add_argument("--task-id", help="Task identifier (e.g., P1-01)")
    start.add_argument("--title", help="Human-readable task title")
    start.add_argument("--state-note", help="Optional note appended to state.md entries")
    start.add_argument("--doc-note", help="Optional docs bullet appended under the task block")
    start.add_argument("--doc-section", choices=["Ready", "In Progress", "Pending Review"], help="Docs section used when recording")
    start.add_argument("--skip-record", action="store_true", help="Skip the record step even if the anchor is missing")
    start.add_argument(
        "--runbook-links",
        help=(
            "Optional Markdown list overriding the default runbook references in the next-task template"
        ),
    )
    start.add_argument(
        "--pending-questions",
        help=(
            "Optional text used for the pending-questions checklist in the next-task template"
        ),
    )

    finish = subparsers.add_parser("finish-task", help="Mark a task as completed")
    finish.add_argument("--anchor", help="Task DoD anchor (docs/task_backlog.md#...)")
    finish.add_argument("--date", help="Completion date (YYYY-MM-DD)")
    finish.add_argument("--note", help="Summary note stored in the archive/log")
    finish.add_argument("--task-id", help="Optional override for the task ID in the log entry")

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "start-task":
            params = _collect_start_params(args)
            commands = _build_start_commands(params)
            _run_commands(commands, dry_run=args.dry_run)
            if not args.dry_run:
                sync.apply_next_task_template(
                    params.anchor,
                    title=params.title,
                    task_id=params.task_id,
                    runbook_links=params.runbook_links,
                    pending_questions=params.pending_questions,
                )
        elif args.command == "finish-task":
            params = _collect_finish_params(args)
            commands = _build_finish_commands(params)
            _run_commands(commands, dry_run=args.dry_run)
        else:  # pragma: no cover - argparse prevents this
            parser.error(f"Unsupported command {args.command}")
    except InputError as exc:
        parser.error(str(exc))
    except sync.SyncError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
