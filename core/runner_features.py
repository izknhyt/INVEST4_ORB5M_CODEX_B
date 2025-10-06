"""Feature computation pipeline for :mod:`core.runner`.

The pipeline encapsulates the per-bar feature calculations and context
construction that previously lived directly on :class:`BacktestRunner`.
Keeping these responsibilities in a dedicated module makes it easier to
share sanitisation helpers and to reason about the state updates that occur
while processing each bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import MutableMapping as MutableMappingABC
import math
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Tuple

from core.feature_store import (
    atr as calc_atr,
    adx as calc_adx,
    opening_range,
    realized_vol,
    micro_zscore as calc_micro_zscore,
    micro_trend as calc_micro_trend,
    mid_price as calc_mid_price,
    trend_score as calc_trend_score,
    pullback as calc_pullback,
)


@dataclass
class RunnerContext(MutableMappingABC[str, Any]):
    """Dictionary-like container for runner context values."""

    values: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.values = dict(self.values)

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.values[key] = value

    def __delitem__(self, key: str) -> None:
        del self.values[key]

    def __contains__(self, key: object) -> bool:  # pragma: no cover - simple proxy
        return key in self.values

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:  # pragma: no cover - simple proxy
        return len(self.values)

    def items(self) -> Iterable[Tuple[str, Any]]:
        return self.values.items()

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def update(self, data: Mapping[str, Any]) -> None:
        self.values.update(data)

    def setdefault(self, key: str, default: Any = None) -> Any:
        return self.values.setdefault(key, default)

    def keys(self) -> Iterable[str]:
        return self.values.keys()

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.values)


@dataclass
class FeatureBundle:
    bar_input: Dict[str, Any]
    ctx: RunnerContext
    atr14: float
    adx14: float
    or_high: Optional[float]
    or_low: Optional[float]
    realized_vol: float
    micro_zscore: float = 0.0
    micro_trend: float = 0.0
    mid_price: float = 0.0
    trend_score: float = 0.0
    pullback: float = 0.0


class FeaturePipeline:
    """Compute feature bundles and runner context for a single bar."""

    WINDOW_LIMIT = 200
    RV_LOOKBACK = 12

    def __init__(
        self,
        *,
        rcfg: Any,
        window: List[Dict[str, Any]],
        session_bars: List[Dict[str, Any]],
        rv_hist: MutableMapping[str, Any],
        strategy_cfg: MutableMapping[str, Any],
        ctx_builder: Callable[..., Dict[str, Any]],
    ) -> None:
        self._rcfg = rcfg
        self._window = window
        self._session_bars = session_bars
        self._rv_hist = rv_hist
        self._strategy_cfg = strategy_cfg
        self._ctx_builder = ctx_builder

    def compute(
        self,
        bar: Mapping[str, Any],
        *,
        session: str,
        new_session: bool,
        calibrating: bool,
    ) -> Tuple[FeatureBundle, RunnerContext]:
        self._ingest_bar(bar, new_session=new_session)
        realized_vol_value = self._compute_realized_vol(session)
        atr14, adx14 = self._compute_atr_adx()
        or_high, or_low = opening_range(self._session_bars, n=self._rcfg.or_n)
        micro_features = self._compute_micro_features(bar)

        bar_input = self._build_bar_input(
            bar,
            new_session=new_session,
            atr14=atr14,
            micro_features=micro_features,
        )
        ctx_dict = self._ctx_builder(
            bar=bar,
            session=session,
            atr14=bar_input["atr14"],
            or_h=or_high if self._is_finite(or_high) else None,
            or_l=or_low if self._is_finite(or_low) else None,
            realized_vol_value=realized_vol_value,
        )
        if calibrating:
            threshold_override = float("-inf") if ctx_dict.get("ev_mode") == "off" else -1e9
            ctx_dict["threshold_lcb_pip"] = threshold_override
            ctx_dict["calibrating"] = True
        runner_ctx = RunnerContext(ctx_dict)
        self._strategy_cfg["ctx"] = runner_ctx.to_dict()

        feature_bundle = FeatureBundle(
            bar_input=bar_input,
            ctx=runner_ctx,
            atr14=atr14,
            adx14=adx14,
            or_high=or_high if self._is_finite(or_high) else None,
            or_low=or_low if self._is_finite(or_low) else None,
            realized_vol=realized_vol_value,
            micro_zscore=bar_input["micro_zscore"],
            micro_trend=bar_input["micro_trend"],
            mid_price=bar_input["mid_price"],
            trend_score=bar_input["trend_score"],
            pullback=bar_input["pullback"],
        )
        return feature_bundle, runner_ctx

    def _ingest_bar(self, bar: Mapping[str, Any], *, new_session: bool) -> None:
        self._window.append({key: bar[key] for key in ("o", "h", "l", "c")})
        if len(self._window) > self.WINDOW_LIMIT:
            del self._window[0]
        if new_session:
            self._session_bars.clear()
        self._session_bars.append({key: bar[key] for key in ("o", "h", "l", "c")})

    def _compute_realized_vol(self, session: str) -> float:
        rv_value = 0.0
        try:
            if len(self._window) >= self.RV_LOOKBACK + 1:
                window_slice = self._window[-(self.RV_LOOKBACK + 1) :]
            else:
                window_slice = None
            rv_computed = realized_vol(window_slice, n=self.RV_LOOKBACK)
        except Exception:
            rv_computed = None
        if rv_computed is not None:
            rv_value = self._sanitize(rv_computed)
        try:
            self._rv_hist[session].append(rv_value)
        except Exception:
            pass
        return 0.0 if math.isnan(rv_value) else rv_value

    def _compute_atr_adx(self) -> Tuple[float, float]:
        if len(self._window) >= 15:
            atr14 = calc_atr(self._window[-15:])
            adx14 = calc_adx(self._window[-15:])
        else:
            atr14 = float("nan")
            adx14 = float("nan")
        return atr14, adx14

    def _compute_micro_features(self, bar: Mapping[str, Any]) -> Dict[str, float]:
        micro_z = self._sanitize(calc_micro_zscore(self._window))
        micro_tr = self._sanitize(calc_micro_trend(self._window))
        mid_px = self._sanitize(calc_mid_price(bar))
        trend_val = self._sanitize(calc_trend_score(self._window))
        pullback_val = self._sanitize(calc_pullback(self._session_bars))
        return {
            "micro_zscore": micro_z,
            "micro_trend": micro_tr,
            "mid_price": mid_px,
            "trend_score": trend_val,
            "pullback": pullback_val,
        }

    def _build_bar_input(
        self,
        bar: Mapping[str, Any],
        *,
        new_session: bool,
        atr14: float,
        micro_features: Mapping[str, float],
    ) -> Dict[str, Any]:
        atr_value = atr14 if self._is_finite(atr14) else 0.0
        bar_input: Dict[str, Any] = {
            "o": bar["o"],
            "h": bar["h"],
            "l": bar["l"],
            "c": bar["c"],
            "atr14": atr_value,
            "window": self._session_bars[: self._rcfg.or_n],
            "new_session": new_session,
        }
        bar_input.update(micro_features)
        if "zscore" in bar:
            try:
                bar_input["zscore"] = float(bar["zscore"])
            except (TypeError, ValueError):
                bar_input["zscore"] = bar["zscore"]
        return bar_input

    @staticmethod
    def _sanitize(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(numeric):
            return 0.0
        return numeric

    @staticmethod
    def _is_finite(value: Optional[float]) -> bool:
        return value is not None and not math.isnan(value)
