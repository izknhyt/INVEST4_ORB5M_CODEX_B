"""
Strategy API (Design v1.1 / ADR-012..025)
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Optional, Dict, Any, List, Mapping

@dataclass
class OrderIntent:
    side: str                 # "BUY" or "SELL"
    qty: float
    price: Optional[float] = None
    tif: str = "IOC"          # IOC|FOK|GTC
    tag: str = ""
    oco: Optional[Dict[str, float]] = None  # {"tp_pips":.., "sl_pips":.., "trail_pips":..}

class Strategy(ABC):
    api_version = "1.0"

    def __init__(self) -> None:
        self._runtime_ctx: Dict[str, Any] = {}

    @abstractmethod
    def on_start(self, cfg: Dict[str,Any], instruments: List[str], state_store: Dict[str,Any]) -> None:
        ...

    def on_bar(self, bar: Dict[str,Any]) -> None:
        ...

    def on_tick(self, tick: Dict[str,Any]) -> None:
        ...

    @abstractmethod
    def signals(self, ctx: Optional[Mapping[str, Any]] = None) -> Iterable[OrderIntent]:
        ...

    @abstractmethod
    def get_pending_signal(self) -> Optional[Any]:
        """Return the latest unconfirmed signal produced by the strategy.

        The runner polls this accessor prior to executing entry/EV/sizing
        checks. Sub-classes may override to expose additional metadata or to
        normalise internal representations (e.g. mapping helper structs back to
        dictionaries). The default implementation returns ``None`` so template
        strategies that do not buffer signals can opt in lazily.
        """

        return None

    def update_context(self, ctx: Mapping[str, Any]) -> None:
        """Store the latest runtime context provided by the runner.

        Sub-classes overriding this method should call
        ``super().update_context(ctx)`` so the cached dictionary stays in sync
        with the runner pipeline while allowing per-strategy bookkeeping to
        hook into context changes.
        """

        self._runtime_ctx = dict(ctx)

    def resolve_runtime_context(
        self, ctx: Optional[Mapping[str, Any]] = None
    ) -> Dict[str, Any]:
        """Return the latest runtime context while syncing optional overrides."""

        if ctx is None:
            return self.get_context()
        self.update_context(ctx)
        return self.get_context()

    @property
    def runtime_ctx(self) -> Dict[str, Any]:
        return self._runtime_ctx

    def get_context(self) -> Dict[str, Any]:
        return dict(self._runtime_ctx)

    def eligibility(self, ctx: Dict[str,Any]) -> float:
        return 1.0

    def capacity(self, ctx: Dict[str,Any]) -> float:
        return 1.0

    def risk_overrides(self, ctx: Dict[str,Any]) -> Optional[Dict[str,Any]]:
        return None

    def on_stop(self) -> None:
        ...
