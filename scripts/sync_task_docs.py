"""Task documentation synchronizer.

This helper centralises updates to ``state.md`` and ``docs/todo_next.md`` so the
tracking workflow stays consistent.  The script understands task entries by the
``docs/task_backlog.md`` anchor (for example
``docs/task_backlog.md#p1-02-インシデントリプレイテンプレート``) and can
move the matching block across sections in both files.

Usage summary:

```
python3 scripts/sync_task_docs.py record \
    --task-id P1-02 \
    --title "インシデントリプレイテンプレート" \
    --date 2024-06-20 \
    --anchor docs/task_backlog.md#p1-02-インシデントリプレイテンプレート \
    --doc-note "Notebook テンプレ整備の初期設計" \
    --doc-section Ready

python3 scripts/sync_task_docs.py promote \
    --anchor docs/task_backlog.md#p1-02-インシデントリプレイテンプレート \
    --task-id P1-02 \
    --title "インシデントリプレイテンプレート" \
    --date 2024-06-21

python3 scripts/sync_task_docs.py complete \
    --anchor docs/task_backlog.md#p1-02-インシデントリプレイテンプレート \
    --date 2024-06-22 \
    --note "Notebook テンプレを整備し、incident 再現テストを保存"
```

- ``record`` registers a brand-new task in ``state.md`` (``## Next Task``) and
  adds a matching entry to the specified section in ``docs/todo_next.md``.
- ``promote`` is used when the next piece of work is selected.  It inserts or
  updates the task inside ``state.md`` and moves the docs entry into
  ``### In Progress``.
- ``complete`` migrates the task from ``state.md`` → ``## Log`` and from
  ``docs/todo_next.md`` → ``## Archive`` while stamping the completion date and
  summary.

The commands preserve anchors, dates, and surrounding notes so that downstream
automation (reports, checklists, runbooks) can rely on consistent formatting.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = REPO_ROOT / "state.md"
DOCS_PATH = REPO_ROOT / "docs" / "todo_next.md"
CHECKLIST_TEMPLATE = "docs/templates/dod_checklist.md"
CHECKLIST_DIR = "docs/checklists"
NEXT_TASK_TEMPLATE = "docs/templates/next_task_entry.md"


class SyncError(RuntimeError):
    """Raised when a synchronisation step fails."""


def read_lines(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8").splitlines()


def write_lines(path: Path, lines: Iterable[str]) -> None:
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")


def find_heading(lines: List[str], heading: str, level: int) -> int:
    prefix = "#" * level + " "
    for idx, line in enumerate(lines):
        if line.startswith(prefix) and line.strip() == f"{prefix.strip()} {heading}":
            return idx
    raise SyncError(f"Heading '{heading}' (level {level}) not found")


def section_bounds(lines: List[str], heading: str, level: int) -> Tuple[int, int]:
    start = find_heading(lines, heading, level) + 1
    for idx in range(start, len(lines)):
        line = lines[idx]
        if line.startswith("#") and line.count("#") <= level:
            return start, idx
    return start, len(lines)


def remove_state_entry(lines: List[str], anchor: str) -> Tuple[List[str], List[str]]:
    start, end = section_bounds(lines, "Next Task", 2)
    for idx in range(start, end):
        if anchor not in lines[idx]:
            continue
        block_start = idx
        block_end = idx + 1
        while block_end < end:
            line = lines[block_end]
            if not line.strip():
                block_end += 1
                break
            if line.startswith("  "):
                block_end += 1
                continue
            break
        # include trailing blank line if present for clean removal
        if block_end < len(lines) and not lines[block_end].strip():
            block_end += 1
        block = lines[block_start:block_end]
        del lines[block_start:block_end]

        # collapse multiple consecutive blank lines inside the section
        while (
            block_start < len(lines) - 1
            and block_start >= start
            and not lines[block_start].strip()
            and not lines[block_start + 1].strip()
        ):
            del lines[block_start]
        if (
            block_start > start
            and block_start <= len(lines) - 1
            and not lines[block_start - 1].strip()
            and (block_start == len(lines) or not lines[block_start].strip())
        ):
            del lines[block_start - 1]
        return lines, block
    raise SyncError(f"Task anchor '{anchor}' not present in state Next Task")


def insert_state_block(lines: List[str], block: List[str]) -> List[str]:
    if not block:
        return lines
    start, end = section_bounds(lines, "Next Task", 2)
    insertion = end
    if insertion > start and lines[insertion - 1].strip():
        lines.insert(insertion, "")
        insertion += 1
    block_to_insert = block[:]
    while block_to_insert and not block_to_insert[-1].strip():
        block_to_insert.pop()
    if block_to_insert and block_to_insert[-1].strip():
        block_to_insert.append("")
    lines[insertion:insertion] = block_to_insert
    return lines


def append_state_next(lines: List[str], entry: str | List[str]) -> List[str]:
    block = [entry] if isinstance(entry, str) else list(entry)
    return insert_state_block(lines, block)


def append_state_log(lines: List[str], entry: str) -> List[str]:
    start, end = section_bounds(lines, "Log", 2)
    insert_at = end
    if insert_at > start and lines[insert_at - 1].strip():
        lines.insert(insert_at, "")
        insert_at += 1
    lines.insert(insert_at, entry)
    return lines


def _strip_trailing_blank_lines(block: List[str]) -> List[str]:
    result = list(block)
    while result and not result[-1].strip():
        result.pop()
    return result


def _replace_section(
    block: List[str], header: str, new_lines: List[str], *, limit: int | None = None
) -> bool:
    if not new_lines:
        return False
    for idx, line in enumerate(block):
        if limit is not None and idx >= limit:
            break
        if line.strip().startswith(header):
            base_indent = len(line) - len(line.lstrip(" "))
            end = idx + 1
            while end < len(block):
                next_line = block[end]
                if not next_line.strip():
                    break
                indent = len(next_line) - len(next_line.lstrip(" "))
                if indent <= base_indent:
                    break
                end += 1
            block[idx:end] = new_lines
            return True
    return False


def _template_sections(template_lines: List[str]) -> List[tuple[str | None, List[str]]]:
    sections: List[tuple[str | None, List[str]]] = []
    idx = 0
    while idx < len(template_lines):
        line = template_lines[idx]
        if line.startswith("  - "):
            header = line.strip()
            label = header.split(":", 1)[0] + ":" if ":" in header else header
            j = idx + 1
            while j < len(template_lines) and template_lines[j].startswith("    "):
                j += 1
            sections.append((label, template_lines[idx:j]))
            idx = j
        else:
            sections.append((None, [line]))
            idx += 1
    return sections


def _merge_state_template(block: List[str], template_lines: List[str]) -> List[str]:
    merged = _strip_trailing_blank_lines(block)
    sections = _template_sections(template_lines)
    updated = False
    for header, lines in sections:
        if header is None:
            continue
        if _replace_section(merged, header, lines):
            updated = True
        else:
            merged.extend(lines)
            updated = True
    if not updated and template_lines:
        merged.extend(template_lines)
    return merged


def _merge_doc_template(block: List[str], template_lines: List[str]) -> List[str]:
    merged = _strip_trailing_blank_lines(block)
    try:
        dod_index = next(
            idx for idx, line in enumerate(merged) if "DoD チェックリスト" in line
        )
    except StopIteration:
        dod_index = len(merged)
    prefix = merged[:dod_index]
    suffix = merged[dod_index:]
    prefix = _merge_state_template(prefix, template_lines)
    result = prefix + suffix
    return result


def normalize_anchor(anchor: str) -> str:
    anchor = anchor.strip()
    if not anchor.startswith("docs/task_backlog.md#"):
        raise SyncError("Anchor must include 'docs/task_backlog.md#'")
    return anchor


def ensure_anchor_comment(line: str, anchor: str) -> str:
    if anchor in line:
        return line
    comment = f"<!-- anchor: {anchor} -->"
    if comment in line:
        return line
    if line.rstrip().endswith("-->"):
        return line
    return f"{line} {comment}".rstrip()


def doc_section_bounds(lines: List[str], heading: str) -> Tuple[int, int]:
    return section_bounds(lines, heading, 3 if heading != "Archive（達成済み）" else 2)


def find_doc_block(lines: List[str], start: int, end: int, anchor: str) -> Tuple[int, int]:
    for idx in range(start, end):
        if anchor in lines[idx]:
            block_start = idx
            while block_start > start and lines[block_start - 1].strip():
                block_start -= 1
            block_end = idx + 1
            while block_end < end and lines[block_end].strip():
                block_end += 1
            return block_start, block_end
    raise SyncError(f"Anchor '{anchor}' not found in docs section")


def remove_doc_block(lines: List[str], heading: str, anchor: str) -> Tuple[List[str], List[str]]:
    start, end = doc_section_bounds(lines, heading)
    block_start, block_end = find_doc_block(lines, start, end, anchor)
    block = lines[block_start:block_end]
    del lines[block_start:block_end]
    # remove trailing empty line created by deletion, keep a single blank separator
    if block_start < len(lines) and not lines[block_start].strip():
        # collapse multiple blank lines
        j = block_start + 1
        while j < len(lines) and not lines[j].strip():
            del lines[j]
    elif block_start > 0 and not lines[block_start - 1].strip():
        # ensure we don't leave two blank lines back-to-back
        j = block_start - 1
        while j > start and not lines[j - 1].strip():
            del lines[j - 1]
            j -= 1
    return lines, block


def insert_doc_block(lines: List[str], heading: str, block: List[str]) -> List[str]:
    start, end = doc_section_bounds(lines, heading)
    insertion = end
    # maintain single blank line separator before insertion when needed
    if insertion > start and lines[insertion - 1].strip():
        lines.insert(insertion, "")
        insertion += 1
    lines[insertion:insertion] = block + [""]
    return lines


def slugify_task_id(task_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task_id.lower()).strip("-")
    return slug or "task"


def ensure_checklist_note(block: List[str], task_id: str | None) -> List[str]:
    if not task_id:
        return block
    slug = slugify_task_id(task_id)
    target_path = f"{CHECKLIST_DIR}/{slug}.md"
    note = (
        f"  - DoD チェックリスト: [{CHECKLIST_TEMPLATE}]({CHECKLIST_TEMPLATE}) を"
        f" [{target_path}]({target_path}) にコピーし、進捗リンクを更新する。"
    )
    for line in block:
        if "DoD チェックリスト" in line:
            return block
    block.append(note)
    return block


def strike_archive_block(block: List[str], anchor: str, date: str) -> List[str]:
    if not block:
        return block
    first = block[0]
    first = ensure_anchor_comment(first, anchor)
    comment = ""
    if "<!--" in first:
        idx = first.index("<!--")
        comment = first[idx:].strip()
        first = first[:idx].rstrip()
    if "~~" not in first:
        first = re.sub(r"^- (\*\*[^*]+\*\*)", r"- ~~\1~~", first, count=1)
    if "✅" not in first:
        first = f"{first} ✅"

    def _append_dates(match: re.Match[str]) -> str:
        dates = [d.strip() for d in match.group(1).split(",") if d.strip()]
        if date not in dates:
            dates.append(date)
        return "`state.md` " + ", ".join(dates)

    first = re.sub(r"`state\.md` ([0-9,\s-]+)", _append_dates, first, count=1)
    if "✅" in first and " ✅" not in first:
        first = first.replace("✅", " ✅")
    if comment:
        first = f"{first} {comment}"
    block[0] = first.rstrip()
    return block


def build_state_line(task_id: str, title: str, date: str, anchor: str, note: str | None) -> str:
    # Input anchor already validated; we only need the fragment for the human-readable part
    fragment = anchor.split("#", 1)[1]
    base = f"- [{task_id}] {date} {title} — DoD: [{anchor}](docs/task_backlog.md#{fragment})"
    if note:
        base = f"{base} — {note}"
    return base


def parse_date(value: str) -> str:
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise SyncError(f"Invalid date '{value}': {exc}") from exc


@dataclass
class CommandContext:
    anchor: str
    date: str
    title: str | None = None
    task_id: str | None = None
    note: str | None = None
    doc_note: str | None = None
    doc_section: str = "Ready"


def cmd_record(ctx: CommandContext) -> None:
    if not ctx.title or not ctx.task_id:
        raise SyncError("'record' requires --title and --task-id")
    state_lines = read_lines(STATE_PATH)
    entry = build_state_line(ctx.task_id, ctx.title, ctx.date, ctx.anchor, ctx.note)
    state_lines = append_state_next(state_lines, entry)
    write_lines(STATE_PATH, state_lines)

    docs_lines = read_lines(DOCS_PATH)
    doc_entry = [
        ensure_anchor_comment(
            f"- **{ctx.title}** — `state.md` {ctx.date}", ctx.anchor
        ),
    ]
    if ctx.doc_note:
        doc_entry.append(f"  - {ctx.doc_note}")
    doc_entry = ensure_checklist_note(doc_entry, ctx.task_id)
    docs_lines = insert_doc_block(docs_lines, ctx.doc_section, doc_entry)
    write_lines(DOCS_PATH, docs_lines)


def cmd_promote(ctx: CommandContext) -> None:
    if not ctx.title or not ctx.task_id:
        raise SyncError("'promote' requires --title and --task-id")
    state_lines = read_lines(STATE_PATH)
    # If already present, do not duplicate
    try:
        state_lines, block = remove_state_entry(state_lines, ctx.anchor)
    except SyncError:
        block = []
    entry = build_state_line(ctx.task_id, ctx.title, ctx.date, ctx.anchor, ctx.note)
    if block:
        block[0] = entry
    else:
        block = [entry]
    state_lines = insert_state_block(state_lines, block)
    write_lines(STATE_PATH, state_lines)

    docs_lines = read_lines(DOCS_PATH)
    docs_lines, block = remove_doc_block(docs_lines, "Ready", ctx.anchor)
    block[0] = ensure_anchor_comment(block[0], ctx.anchor)
    block[0] = re.sub(
        r"(`state\.md` )\d{4}-\d{2}-\d{2}",
        rf"\g<1>{ctx.date}",
        block[0],
    )
    block = ensure_checklist_note(block, ctx.task_id)
    docs_lines = insert_doc_block(docs_lines, "In Progress", block)
    write_lines(DOCS_PATH, docs_lines)


def cmd_complete(ctx: CommandContext) -> None:
    if not ctx.note:
        raise SyncError("'complete' requires --note for the state log summary")
    state_lines = read_lines(STATE_PATH)
    state_lines, _ = remove_state_entry(state_lines, ctx.anchor)

    fragment = ctx.anchor.split("#", 1)[1]
    task_label = ctx.task_id
    if not task_label:
        parts = fragment.split("-", 2)
        if len(parts) >= 2 and parts[0].startswith("p") and parts[0][1:].isdigit() and parts[1].isdigit():
            task_label = f"{parts[0].upper()}-{parts[1]}"
        else:
            task_label = fragment
    log_line = (
        f"- [{task_label}] {ctx.date}: {ctx.note}. DoD: [{ctx.anchor}]({ctx.anchor})."
    )
    state_lines = append_state_log(state_lines, log_line)
    write_lines(STATE_PATH, state_lines)

    docs_lines = read_lines(DOCS_PATH)
    for section in ("In Progress", "Ready", "Pending Review"):
        try:
            docs_lines, block = remove_doc_block(docs_lines, section, ctx.anchor)
            break
        except SyncError:
            continue
    else:
        raise SyncError(
            f"Task anchor '{ctx.anchor}' not found in active docs sections"
        )
    block = strike_archive_block(block, ctx.anchor, ctx.date)
    docs_lines = insert_doc_block(docs_lines, "Archive（達成済み）", block)
    write_lines(DOCS_PATH, docs_lines)


def _render_template(template_lines: List[str], context: dict[str, str]) -> List[str]:
    rendered: List[str] = []
    for line in template_lines:
        text = line
        for key, value in context.items():
            text = text.replace(f"{{{{{key}}}}}", value)
        rendered.append(text)
    return rendered


def _resolve_template_path(template_path: Path | None) -> Path:
    template_file = template_path or (REPO_ROOT / NEXT_TASK_TEMPLATE)
    if not template_file.exists():
        raise SyncError(f"Template file '{template_file}' not found")
    return template_file


def _build_template_context(
    anchor: str,
    title: str,
    task_id: str,
    runbook_links: str | None,
    pending_questions: str | None,
) -> dict[str, str]:
    return {
        "TITLE": title,
        "TASK_ID": task_id,
        "BACKLOG_ANCHOR": anchor,
        "RUNBOOK_LINKS": runbook_links
        or "[docs/state_runbook.md](docs/state_runbook.md)",
        "PENDING_QUESTIONS": pending_questions
        or "Clarify gating metrics, data dependencies, or open questions.",
    }


def _pop_doc_block(
    lines: List[str], anchor: str
) -> tuple[List[str], List[str], str]:
    for heading in ("In Progress", "Ready", "Pending Review"):
        try:
            updated, block = remove_doc_block(lines, heading, anchor)
            return updated, block, heading
        except SyncError:
            continue
    raise SyncError(
        f"Task anchor '{anchor}' not found in docs/todo_next.md for template insertion"
    )


def apply_next_task_template(
    anchor: str,
    *,
    title: str,
    task_id: str,
    template_path: Path | None = None,
    runbook_links: str | None = None,
    pending_questions: str | None = None,
) -> None:
    template_file = _resolve_template_path(template_path)
    template_lines = template_file.read_text(encoding="utf-8").splitlines()
    context = _build_template_context(
        anchor,
        title,
        task_id,
        runbook_links,
        pending_questions,
    )
    rendered_template = _render_template(template_lines, context)
    state_template = list(rendered_template)
    docs_template = list(rendered_template)

    state_lines = read_lines(STATE_PATH)
    state_lines, state_block = remove_state_entry(state_lines, anchor)
    state_block = _merge_state_template(state_block, state_template)
    state_lines = insert_state_block(state_lines, state_block)
    write_lines(STATE_PATH, state_lines)

    docs_lines = read_lines(DOCS_PATH)
    docs_lines, doc_block, current_heading = _pop_doc_block(docs_lines, anchor)
    doc_block = ensure_checklist_note(doc_block, task_id)
    doc_block = _merge_doc_template(doc_block, docs_template)
    docs_lines = insert_doc_block(docs_lines, current_heading, doc_block)
    write_lines(DOCS_PATH, docs_lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronise state and docs tasks")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--anchor", required=True, help="Task DoD anchor")
        sub.add_argument(
            "--date",
            required=True,
            help="ISO date (YYYY-MM-DD) recorded for the operation",
        )

    record = subparsers.add_parser("record", help="Register a new task")
    add_common(record)
    record.add_argument("--note", help="Additional summary to append in state.md")
    record.add_argument("--title", required=True, help="Task title")
    record.add_argument("--task-id", required=True, help="Task ID")
    record.add_argument(
        "--doc-note",
        help="Optional bullet appended under the docs entry when recording",
    )
    record.add_argument(
        "--doc-section",
        default="Ready",
        choices=["In Progress", "Ready", "Pending Review"],
        help="Docs section used by the 'record' command",
    )

    promote = subparsers.add_parser("promote", help="Move a task into In Progress")
    add_common(promote)
    promote.add_argument("--note", help="Additional summary to append in state.md")
    promote.add_argument("--title", required=True, help="Task title")
    promote.add_argument("--task-id", required=True, help="Task ID")

    complete = subparsers.add_parser("complete", help="Mark a task as done")
    add_common(complete)
    complete.add_argument(
        "--note", required=True, help="Summary recorded in state.md and docs"
    )
    complete.add_argument("--task-id", help="Optional task ID for the state log")

    return parser


def main(argv: List[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    anchor = normalize_anchor(args.anchor)
    date = parse_date(args.date)
    ctx = CommandContext(
        anchor=anchor,
        date=date,
        title=getattr(args, "title", None),
        task_id=getattr(args, "task_id", None),
        note=args.note,
        doc_note=getattr(args, "doc_note", None),
        doc_section=getattr(args, "doc_section", "Ready"),
    )

    if args.command == "record":
        cmd_record(ctx)
    elif args.command == "promote":
        cmd_promote(ctx)
    elif args.command == "complete":
        cmd_complete(ctx)
    else:
        raise SyncError(f"Unknown command {args.command}")


if __name__ == "__main__":
    main()
