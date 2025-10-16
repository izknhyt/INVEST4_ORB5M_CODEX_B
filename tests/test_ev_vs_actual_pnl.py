from __future__ import annotations

import types
from pathlib import Path

import pytest


pytest.importorskip("pandas")

import scripts.ev_vs_actual_pnl as module


def test_entrypoints_use_shared_normalizer(monkeypatch):
    expand_calls = []

    def fake_expanduser(self):
        expand_calls.append(("expanduser", self))
        return self

    def fake_resolve(self):
        expand_calls.append(("resolve", self))
        return self

    monkeypatch.setattr(Path, "expanduser", fake_expanduser, raising=False)
    monkeypatch.setattr(Path, "resolve", fake_resolve, raising=False)

    original_normalize = module._normalize_path
    normalized_inputs = []

    def spy_normalize(value):
        normalized_inputs.append(value)
        return original_normalize(value)

    monkeypatch.setattr(module, "_normalize_path", spy_normalize)

    dummy_record = Path("/runs/dummy/records.csv")
    collect_inputs = []

    def fake_collect(runs_dir):
        collect_inputs.append(runs_dir)
        return [dummy_record]

    monkeypatch.setattr(module, "_collect_record_paths", fake_collect)
    monkeypatch.setattr(module, "_select_run", lambda paths, run_id: dummy_record)
    monkeypatch.setattr(module, "process_single_run", lambda *a, **k: {"run_id": "dummy"})
    monkeypatch.setattr(module, "_store_single_run", lambda *a, **k: None)
    monkeypatch.setattr(module, "process_all_runs", lambda *a, **k: {"runs": []})
    monkeypatch.setattr(module, "_store_all_runs", lambda *a, **k: None)

    module.store_run_summary("~/.runs", None, "~/out", store_daily=False)
    module.store_all_runs("~/.runs", "~/out")

    args = types.SimpleNamespace(
        runs_dir="~/runs",
        list_runs=False,
        all_runs=False,
        run_id=None,
        top_n=3,
        show_daily=False,
        store_daily=False,
        store_dir="~/store",
        quiet=True,
        output_json=None,
    )

    monkeypatch.setattr(module, "parse_args", lambda: args)

    module.main()

    assert normalized_inputs == [
        "~/.runs",
        "~/out",
        "~/.runs",
        "~/out",
        "~/runs",
        "~/store",
        None,
    ]

    assert len(expand_calls) == 12
    assert all(isinstance(value, Path) for _, value in expand_calls)
    assert collect_inputs == [
        Path("~/.runs"),
        Path("~/.runs"),
        Path("~/runs"),
    ]
