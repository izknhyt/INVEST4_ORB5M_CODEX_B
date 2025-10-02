from datetime import datetime, timedelta, timezone

import pytest

from scripts import yfinance_fetch


class _FakeDatetime(datetime):
    @classmethod
    def utcnow(cls):
        return datetime(2025, 10, 1, 4, 30)


def _ts(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def test_fetch_bars_normalizes_rows(monkeypatch):
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "timestamp": [
                        _ts(datetime(2025, 10, 1, 4, 0)),
                        _ts(datetime(2025, 10, 1, 4, 5)),
                    ],
                    "indicators": {
                        "quote": [
                            {
                                "open": [147.90, 147.95],
                                "high": [147.95, 148.00],
                                "low": [147.85, 147.90],
                                "close": [147.92, 147.99],
                                "volume": [1000, 1200],
                            }
                        ]
                    },
                }
            ],
        }
    }

    captured = {}

    def fake_download(ticker, interval, start, end):
        captured["ticker"] = ticker
        captured["interval"] = interval
        captured["start"] = start
        captured["end"] = end
        return payload

    monkeypatch.setattr(yfinance_fetch, "_download_chart_json", fake_download)
    monkeypatch.setattr(yfinance_fetch, "datetime", _FakeDatetime)

    rows = list(
        yfinance_fetch.fetch_bars(
            "USDJPY",
            "5m",
            start=datetime(2025, 10, 1, 3, 20),
            end=datetime(2025, 10, 1, 4, 20),
        )
    )

    assert captured["ticker"] == "JPY=X"
    assert captured["interval"] == "5m"
    assert captured["end"] <= _FakeDatetime.utcnow()
    assert len(rows) == 2
    assert rows[0]["timestamp"] == "2025-10-01T04:00:00"
    assert rows[0]["symbol"] == "USDJPY"
    assert rows[0]["o"] == pytest.approx(147.90)
    assert rows[1]["v"] == pytest.approx(1200)


def test_fetch_bars_auto_adjust_scales_prices(monkeypatch):
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "timestamp": [_ts(datetime(2025, 10, 1, 4, 0))],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0],
                                "high": [110.0],
                                "low": [90.0],
                                "close": [105.0],
                                "volume": [500],
                            }
                        ],
                        "adjclose": [
                            {
                                "adjclose": [210.0],
                            }
                        ],
                    },
                }
            ],
        }
    }

    monkeypatch.setattr(yfinance_fetch, "_download_chart_json", lambda *args, **_: payload)
    monkeypatch.setattr(yfinance_fetch, "datetime", _FakeDatetime)

    rows = list(
        yfinance_fetch.fetch_bars(
            "USDJPY",
            "5m",
            start=datetime(2025, 10, 1, 3, 55),
            end=datetime(2025, 10, 1, 4, 5),
            auto_adjust=True,
        )
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["c"] == pytest.approx(210.0)
    assert row["o"] == pytest.approx(200.0)
    assert row["h"] == pytest.approx(220.0)
    assert row["l"] == pytest.approx(180.0)


def test_fetch_bars_rejects_invalid_interval():
    with pytest.raises(ValueError):
        list(
            yfinance_fetch.fetch_bars(
                "USDJPY",
                "2m",
                start=datetime(2025, 10, 1, 3, 55),
                end=datetime(2025, 10, 1, 4, 10),
            )
        )


def test_fetch_bars_returns_empty_when_out_of_range(monkeypatch):
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "timestamp": [_ts(datetime(2025, 10, 1, 4, 0))],
                    "indicators": {
                        "quote": [
                            {
                                "open": [147.9],
                                "high": [148.0],
                                "low": [147.8],
                                "close": [147.95],
                                "volume": [1000],
                            }
                        ]
                    },
                }
            ],
        }
    }

    monkeypatch.setattr(yfinance_fetch, "_download_chart_json", lambda *args, **_: payload)
    monkeypatch.setattr(yfinance_fetch, "datetime", _FakeDatetime)

    rows = list(
        yfinance_fetch.fetch_bars(
            "USDJPY",
            "5m",
            start=datetime(2025, 10, 2, 3, 55),
            end=datetime(2025, 10, 2, 4, 10),
        )
    )

    assert rows == []


def test_fetch_bars_raises_on_chart_error(monkeypatch):
    payload = {
        "chart": {
            "error": {"code": "Not Found"},
            "result": [],
        }
    }

    monkeypatch.setattr(yfinance_fetch, "_download_chart_json", lambda *args, **_: payload)
    monkeypatch.setattr(yfinance_fetch, "datetime", _FakeDatetime)

    with pytest.raises(RuntimeError) as excinfo:
        list(
            yfinance_fetch.fetch_bars(
                "USDJPY",
                "5m",
                start=datetime(2025, 10, 1, 3, 55),
                end=datetime(2025, 10, 1, 4, 10),
            )
        )

    assert "yahoo_chart_error" in str(excinfo.value)


def test_fetch_bars_skips_rows_with_missing_prices(monkeypatch):
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "timestamp": [
                        _ts(datetime(2025, 10, 1, 4, 0)),
                        _ts(datetime(2025, 10, 1, 4, 5)),
                    ],
                    "indicators": {
                        "quote": [
                            {
                                "open": [147.90, None],
                                "high": [147.95, 148.05],
                                "low": [147.85, 147.95],
                                "close": [147.92, 148.00],
                                "volume": [1000, 1200],
                            }
                        ]
                    },
                }
            ],
        }
    }

    monkeypatch.setattr(yfinance_fetch, "_download_chart_json", lambda *args, **_: payload)
    monkeypatch.setattr(yfinance_fetch, "datetime", _FakeDatetime)

    rows = list(
        yfinance_fetch.fetch_bars(
            "USDJPY",
            "5m",
            start=datetime(2025, 10, 1, 3, 55),
            end=datetime(2025, 10, 1, 4, 10),
        )
    )

    assert len(rows) == 1
    assert rows[0]["timestamp"] == "2025-10-01T04:00:00"


def test_fetch_bars_chunks_intraday_requests(monkeypatch):
    start = datetime(2025, 9, 25, 0, 0)
    end = datetime(2025, 10, 5, 0, 0)

    payload_one = {
        "chart": {
            "error": None,
            "result": [
                {
                    "timestamp": [
                        _ts(start),
                        _ts(start + timedelta(minutes=5)),
                    ],
                    "indicators": {
                        "quote": [
                            {
                                "open": [110.0, 111.0],
                                "high": [111.0, 112.0],
                                "low": [109.5, 110.5],
                                "close": [110.5, 111.5],
                                "volume": [900, 950],
                            }
                        ]
                    },
                }
            ],
        }
    }

    payload_two = {
        "chart": {
            "error": None,
            "result": [
                {
                    "timestamp": [
                        _ts(start + timedelta(minutes=5)),
                        _ts(start + timedelta(days=9)),
                    ],
                    "indicators": {
                        "quote": [
                            {
                                "open": [111.0, 118.0],
                                "high": [112.0, 119.0],
                                "low": [110.5, 117.5],
                                "close": [111.5, 118.5],
                                "volume": [950, 1200],
                            }
                        ]
                    },
                }
            ],
        }
    }

    payload_iter = iter([payload_one, payload_two])
    calls = []

    def fake_download(ticker, interval, window_start, window_end):
        calls.append((window_start, window_end))
        return next(payload_iter)

    class _ChunkDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return datetime(2025, 10, 10, 0, 0)

    monkeypatch.setattr(yfinance_fetch, "_download_chart_json", fake_download)
    monkeypatch.setattr(yfinance_fetch, "datetime", _ChunkDatetime)

    rows = list(
        yfinance_fetch.fetch_bars(
            "USDJPY",
            "5m",
            start=start,
            end=end,
        )
    )

    assert len(rows) == 3
    assert rows[-1]["timestamp"] == "2025-10-04T00:00:00"
    assert len(calls) == 2
    assert calls[0][0] == start
    assert calls[0][1] == datetime(2025, 10, 2, 0, 0)
    assert calls[1][0] == datetime(2025, 10, 2, 0, 0, 1)
    assert calls[1][1] == end
