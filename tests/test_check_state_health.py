import json

import pytest

from scripts import check_state_health as module


class DummyResponse:
    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_build_warnings_triggers_expected_conditions():
    summary = {
        "ev_total_samples": 12.0,
        "ev_win_lcb": 0.4,
        "bucket_summaries": [
            {
                "bucket": "LDN",
                "samples": 5.0,
                "win_mean": 0.5,
                "win_lcb": 0.2,
            },
            {
                "bucket": "NY",
                "samples": 15.0,
                "win_mean": 0.6,
                "win_lcb": 0.34,
            },
        ],
        "slip_a": {
            "tight": 0.6,
            "wide": -0.2,
            "invalid": "oops",
        },
    }

    warnings = module.build_warnings(
        summary,
        min_global_sample=20.0,
        min_win_lcb=0.45,
        min_bucket_sample=10.0,
        min_bucket_win_lcb=0.35,
        max_slip=0.5,
    )

    assert any(w.startswith("global sample count low") for w in warnings)
    assert any(w.startswith("global win-rate LCB low") for w in warnings)
    assert any("bucket LDN" in w and "samples" in w for w in warnings)
    assert any("bucket NY" in w and "win_lcb" in w for w in warnings)
    assert any("slip coefficient tight" in w and "exceeds" in w for w in warnings)
    assert any("slip coefficient wide" in w and "negative" in w for w in warnings)
    assert any("slip coefficient invalid" in w and "invalid" in w for w in warnings)


def test_rotate_history_trims_to_limit():
    history = [
        {"checked_at": "t0"},
        {"checked_at": "t1"},
    ]
    new_record = {"checked_at": "t2"}

    rotated = module.rotate_history(history, new_record, limit=2)

    assert [entry["checked_at"] for entry in rotated] == ["t1", "t2"]
    assert [entry["checked_at"] for entry in history] == ["t0", "t1"]


@pytest.mark.usefixtures("tmp_path")
def test_main_posts_webhook_and_writes_history(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    history_path = tmp_path / "history.json"

    state = {
        "ev_global": {"alpha": 5.0, "beta": 3.0},
        "ev_buckets": {
            "LDN": {"alpha": 1.0, "beta": 1.0},
        },
        "slip": {"a": {"tight": 0.7}},
    }
    state_path.write_text(json.dumps(state))

    captures = []

    def fake_urlopen(req, timeout=5.0):
        payload = json.loads(req.data.decode("utf-8"))
        captures.append({
            "url": req.full_url,
            "payload": payload,
            "timeout": timeout,
        })
        return DummyResponse(status=204)

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    args = [
        f"--state={state_path}",
        f"--json-out={history_path}",
        "--min-global-sample=10.0",
        "--min-win-lcb=0.7",
        "--min-bucket-sample=5.0",
        "--min-bucket-win-lcb=0.6",
        "--max-slip=0.6",
        "--webhook=https://example.com/hook",
        "--history-limit=3",
    ]

    exit_code = module.main(args)
    assert exit_code == 0

    assert len(captures) == 1
    capture = captures[0]
    assert capture["url"] == "https://example.com/hook"
    assert capture["timeout"] == 5.0

    payload = capture["payload"]
    assert payload["event"] == "state_health_warning"
    assert payload["state_path"] == str(state_path)
    assert payload["metrics"]["ev_total_samples"] == pytest.approx(8.0)
    assert any(w.startswith("global sample count low") for w in payload["warnings"])
    assert any("slip coefficient tight" in w for w in payload["warnings"])

    history = json.loads(history_path.read_text())
    assert len(history) == 1
    saved = history[0]
    assert saved["warnings"] == payload["warnings"]
    assert saved["metrics"] == payload["metrics"]
    assert saved["webhook"][0]["url"] == "https://example.com/hook"
    assert saved["webhook"][0]["ok"] is True
    assert saved["webhook"][0]["detail"] == "status=204"
    assert saved["config"]["min_global_sample"] == 10.0
