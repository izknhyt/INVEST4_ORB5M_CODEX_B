"""
Strategy API (Design v1.1 / ADR-012..025)
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Optional, Dict, Any, List

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

    @abstractmethod
    def on_start(self, cfg: Dict[str,Any], instruments: List[str], state_store: Dict[str,Any]) -> None:
        ...

    def on_bar(self, bar: Dict[str,Any]) -> None:
        ...

    def on_tick(self, tick: Dict[str,Any]) -> None:
        ...

    @abstractmethod
    def signals(self) -> Iterable[OrderIntent]:
        ...

    def eligibility(self, ctx: Dict[str,Any]) -> float:
        return 1.0

    def capacity(self, ctx: Dict[str,Any]) -> float:
        return 1.0

    def risk_overrides(self, ctx: Dict[str,Any]) -> Optional[Dict[str,Any]]:
        return None

    def on_stop(self) -> None:
        ...
