from datetime import datetime, timezone

import pytest

from scripts import yfinance_fetch


class _FakeDatetime(datetime):
    @classmethod
    def utcnow(cls):
        return datetime(2025, 10, 1, 4, 30)


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
    frame = _FakeFrame()

    class DummyModule:
        @staticmethod
        def download(**kwargs):
            assert kwargs["tickers"] == "JPY=X"
            assert kwargs["interval"] == "5m"
            assert kwargs["period"] == "7d"
            return frame

    monkeypatch.setattr(yfinance_fetch, "_ensure_module", lambda: DummyModule())
    monkeypatch.setattr(yfinance_fetch, "datetime", _FakeDatetime)

    rows = list(
        yfinance_fetch.fetch_bars(
            "USDJPY",
            "5m",
            start=datetime(2025, 10, 1, 3, 20),
            end=datetime(2025, 10, 1, 4, 20),
        )
    )

    assert len(rows) == 2
    assert rows[0]["timestamp"] == "2025-10-01T04:00:00"
    assert rows[0]["symbol"] == "USDJPY"
    assert rows[0]["o"] == pytest.approx(147.90)
    assert rows[1]["v"] == pytest.approx(1200)


def test_fetch_bars_requires_yfinance(monkeypatch):
    def raise_missing():
        raise RuntimeError("missing yfinance")

    monkeypatch.setattr(yfinance_fetch, "_ensure_module", raise_missing)

    with pytest.raises(RuntimeError):
        list(
            yfinance_fetch.fetch_bars(
                "USDJPY",
                "5m",
                start=datetime(2025, 10, 1, 3, 55),
                end=datetime(2025, 10, 1, 4, 10),
            )
        )


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
    class EmptyFrame:
        empty = True

        def dropna(self, **_kwargs):
            return self

    class DummyModule:
        @staticmethod
        def download(**kwargs):
            assert kwargs["period"] == "7d"
            return EmptyFrame()

    monkeypatch.setattr(yfinance_fetch, "_ensure_module", lambda: DummyModule())
    monkeypatch.setattr(yfinance_fetch, "datetime", _FakeDatetime)

    rows = list(
        yfinance_fetch.fetch_bars(
            "USDJPY",
            "5m",
            start=datetime(2024, 1, 1, 0, 0),
            end=datetime(2024, 1, 2, 0, 0),
        )
    )
    assert rows == []
