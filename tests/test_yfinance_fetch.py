from datetime import datetime, timezone

import pytest

from scripts import yfinance_fetch


class _FakeDatetimeModule:
    @staticmethod
    def utcnow():
        return datetime(2025, 10, 1, 4, 30)

    @staticmethod
    def fromtimestamp(value, tz=None):
        return datetime.fromtimestamp(value, tz=tz)


class _FakeIndex:
    def __init__(self, dt: datetime):
        self._dt = dt

    def to_pydatetime(self) -> datetime:
        return self._dt


class _FakeFrame:
    def __init__(self):
        self._rows = [
            (
                _FakeIndex(datetime(2025, 10, 1, 4, 0, tzinfo=timezone.utc)),
                {
                    "Open": 147.90,
                    "High": 147.95,
                    "Low": 147.85,
                    "Close": 147.92,
                    "Volume": 1000,
                },
            ),
            (
                _FakeIndex(datetime(2025, 10, 1, 4, 5, tzinfo=timezone.utc)),
                {
                    "Open": 147.95,
                    "High": 148.00,
                    "Low": 147.90,
                    "Close": 147.99,
                    "Volume": 1200,
                },
            ),
        ]
        self.columns = ["Open", "High", "Low", "Close", "Volume"]
        self.empty = False

    def dropna(self, **_kwargs):
        return self

    def iterrows(self):
        yield from self._rows


def test_fetch_bars_normalizes_rows(monkeypatch):
    ts_start = int(datetime(2025, 10, 1, 3, 40, tzinfo=timezone.utc).timestamp())
    ts_end = ts_start + 300
    chart_payload = {
        "timestamp": [ts_start, ts_end],
        "indicators": {
            "quote": [
                {
                    "open": [147.90, 147.95],
                    "high": [147.95, 148.0],
                    "low": [147.85, 147.90],
                    "close": [147.92, 147.99],
                    "volume": [1000, 1200],
                }
            ]
        },
    }

    def _mock_download(**kwargs):
        assert kwargs["ticker"] == "JPY=X"
        assert kwargs["interval"] == "5m"
        return chart_payload

    monkeypatch.setattr(yfinance_fetch, "_download_chart", _mock_download)
    monkeypatch.setattr(yfinance_fetch, "datetime", _FakeDatetimeModule)

    rows = list(
        yfinance_fetch.fetch_bars(
            "USDJPY",
            "5m",
            start=datetime(2025, 10, 1, 3, 35),
            end=datetime(2025, 10, 1, 3, 50),
        )
    )

    assert len(rows) == 2
    assert rows[0]["timestamp"] == "2025-10-01T03:40:00"
    assert rows[0]["symbol"] == "USDJPY"
    assert rows[0]["o"] == pytest.approx(147.90)
    assert rows[1]["v"] == pytest.approx(1200)


def test_fetch_bars_returns_empty_on_download_failure(monkeypatch):
    def raise_error(**_kwargs):
        raise RuntimeError("download failed")

    monkeypatch.setattr(yfinance_fetch, "_download_chart", raise_error)
    monkeypatch.setattr(yfinance_fetch, "datetime", _FakeDatetimeModule)

    rows = list(
        yfinance_fetch.fetch_bars(
            "USDJPY",
            "5m",
            start=datetime(2025, 10, 1, 3, 55),
            end=datetime(2025, 10, 1, 4, 10),
        )
    )

    assert rows == []


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
    ts_start = int(datetime(2025, 10, 1, 3, 40, tzinfo=timezone.utc).timestamp())
    chart_payload = {
        "timestamp": [ts_start],
        "indicators": {
            "quote": [
                {
                    "open": [147.90],
                    "high": [147.95],
                    "low": [147.85],
                    "close": [147.92],
                    "volume": [1000],
                }
            ]
        },
    }

    monkeypatch.setattr(yfinance_fetch, "_download_chart", lambda **_: chart_payload)
    monkeypatch.setattr(yfinance_fetch, "datetime", _FakeDatetimeModule)

    rows = list(
        yfinance_fetch.fetch_bars(
            "USDJPY",
            "5m",
            start=datetime(2024, 1, 1, 0, 0),
            end=datetime(2024, 1, 2, 0, 0),
        )
    )
    assert rows == []
