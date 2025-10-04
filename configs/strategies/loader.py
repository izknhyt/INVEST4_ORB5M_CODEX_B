from __future__ import annotations

"""Loader + schema helpers for strategy manifests (configs/strategies/*.yaml)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.utils import yaml_compat as yaml

__all__ = [
    "CATEGORY_CHOICES",
    "StrategyManifest",
    "load_manifest",
    "load_manifests",
]

CATEGORY_CHOICES = {"scalping", "day", "swing"}


@dataclass
class InstrumentSpec:
    symbol: str
    timeframe: str
    mode: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InstrumentSpec":
        if not isinstance(data, dict):
            raise ValueError("instrument spec must be a mapping")
        symbol = str(data.get("symbol", "")).upper()
        tf = str(data.get("timeframe", "")).lower()
        if not symbol:
            raise ValueError("instrument.symbol is required")
        if not tf:
            raise ValueError("instrument.timeframe is required")
        mode = data.get("mode")
        if mode is not None:
            mode = str(mode)
        return cls(symbol=symbol, timeframe=tf, mode=mode)


@dataclass
class RouterSpec:
    allowed_sessions: tuple[str, ...] = ()
    allow_spread_bands: tuple[str, ...] = ()
    allow_rv_bands: tuple[str, ...] = ()
    max_latency_ms: Optional[float] = None
    category_cap_pct: Optional[float] = None
    tags: tuple[str, ...] = ()
    priority: float = 0.0
    max_gross_exposure_pct: Optional[float] = None
    max_correlation: Optional[float] = None
    correlation_tags: tuple[str, ...] = ()
    max_reject_rate: Optional[float] = None
    max_slippage_bps: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouterSpec":
        if not isinstance(data, dict):
            return cls()
        sessions = tuple(str(s).strip().upper() for s in data.get("allowed_sessions", []) if str(s).strip())
        spread_bands = tuple(str(s).strip().lower() for s in data.get("allow_spread_bands", []) if str(s).strip())
        rv_bands = tuple(str(s).strip().lower() for s in data.get("allow_rv_bands", []) if str(s).strip())
        tags = tuple(str(s).strip().lower() for s in data.get("tags", []) if str(s).strip())
        latency = data.get("max_latency_ms")
        latency_val = float(latency) if latency is not None else None
        cat_cap = data.get("category_cap_pct")
        cat_cap_val = float(cat_cap) if cat_cap is not None else None
        priority_val = float(data.get("priority", 0.0) or 0.0)
        gross_cap = data.get("max_gross_exposure_pct")
        gross_cap_val = float(gross_cap) if gross_cap is not None else None
        max_corr = data.get("max_correlation")
        max_corr_val = float(max_corr) if max_corr is not None else None
        corr_tags = tuple(str(s).strip().lower() for s in data.get("correlation_tags", []) if str(s).strip())
        max_reject = data.get("max_reject_rate")
        max_reject_val = float(max_reject) if max_reject is not None else None
        max_slip = data.get("max_slippage_bps")
        max_slip_val = float(max_slip) if max_slip is not None else None
        return cls(
            allowed_sessions=sessions,
            allow_spread_bands=spread_bands,
            allow_rv_bands=rv_bands,
            max_latency_ms=latency_val,
            category_cap_pct=cat_cap_val,
            tags=tags,
            priority=priority_val,
            max_gross_exposure_pct=gross_cap_val,
            max_correlation=max_corr_val,
            correlation_tags=corr_tags,
            max_reject_rate=max_reject_val,
            max_slippage_bps=max_slip_val,
        )


@dataclass
class RiskSpec:
    risk_per_trade_pct: float
    max_daily_dd_pct: Optional[float] = None
    notional_cap: Optional[float] = None
    max_concurrent_positions: int = 1
    warmup_trades: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskSpec":
        if not isinstance(data, dict):
            raise ValueError("risk spec is required")
        if "risk_per_trade_pct" not in data:
            raise ValueError("risk_per_trade_pct is required in risk block")
        return cls(
            risk_per_trade_pct=float(data.get("risk_per_trade_pct", 0.0)),
            max_daily_dd_pct=float(data["max_daily_dd_pct"]) if data.get("max_daily_dd_pct") is not None else None,
            notional_cap=float(data["notional_cap"]) if data.get("notional_cap") is not None else None,
            max_concurrent_positions=int(data.get("max_concurrent_positions", 1)),
            warmup_trades=int(data.get("warmup_trades", 0)),
        )


@dataclass
class FeatureSpec:
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FeatureSpec":
        if not isinstance(data, dict):
            return cls()
        req = tuple(sorted({str(x).strip() for x in data.get("required", []) if str(x).strip()}))
        opt = tuple(sorted({str(x).strip() for x in data.get("optional", []) if str(x).strip()}))
        return cls(required=req, optional=opt)


@dataclass
class RunnerDefaults:
    runner_config: Dict[str, Any] = field(default_factory=dict)
    cli_args: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunnerDefaults":
        if not isinstance(data, dict):
            return cls()
        rc = data.get("runner_config") or {}
        cli = data.get("cli_args") or {}
        if not isinstance(rc, dict):
            raise ValueError("runner.runner_config must be mapping")
        if not isinstance(cli, dict):
            raise ValueError("runner.cli_args must be mapping")
        return cls(runner_config=rc, cli_args=cli)


@dataclass
class StateSpec:
    archive_namespace: Optional[str] = None
    ev_profile: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StateSpec":
        if not isinstance(data, dict):
            return cls()
        archive_ns = data.get("archive_namespace")
        ev_profile = data.get("ev_profile")
        return cls(
            archive_namespace=str(archive_ns) if archive_ns else None,
            ev_profile=str(ev_profile) if ev_profile else None,
        )


@dataclass
class StrategySpec:
    class_path: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    instruments: tuple[InstrumentSpec, ...] = ()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategySpec":
        if not isinstance(data, dict):
            raise ValueError("strategy block is required")
        class_path = data.get("class_path")
        if not class_path:
            raise ValueError("strategy.class_path is required")
        params = data.get("parameters") or {}
        if not isinstance(params, dict):
            raise ValueError("strategy.parameters must be mapping")
        instruments_block = data.get("instruments") or []
        instruments: List[InstrumentSpec] = []
        for item in instruments_block:
            instruments.append(InstrumentSpec.from_dict(item))
        if not instruments:
            raise ValueError("strategy.instruments must contain at least one entry")
        return cls(
            class_path=str(class_path),
            parameters=params,
            instruments=tuple(instruments),
        )


@dataclass
class StrategyManifest:
    id: str
    name: str
    category: str
    class_path: str
    version: str = "1.0"
    description: str = ""
    tags: tuple[str, ...] = ()
    strategy: StrategySpec = field(default_factory=StrategySpec)
    router: RouterSpec = field(default_factory=RouterSpec)
    risk: RiskSpec = field(default_factory=lambda: RiskSpec(risk_per_trade_pct=0.0))
    features: FeatureSpec = field(default_factory=FeatureSpec)
    runner: RunnerDefaults = field(default_factory=RunnerDefaults)
    state: StateSpec = field(default_factory=StateSpec)
    raw: Dict[str, Any] = field(default_factory=dict)

    def ensure_valid(self) -> None:
        if self.category not in CATEGORY_CHOICES:
            raise ValueError(f"invalid category '{self.category}' (expected one of {sorted(CATEGORY_CHOICES)})")
        if not self.strategy.instruments:
            raise ValueError("at least one instrument must be defined")
        if self.risk.risk_per_trade_pct <= 0:
            raise ValueError("risk_per_trade_pct must be positive")

    @property
    def module(self) -> str:
        return self.class_path.rsplit(".", 1)[0]

    @property
    def class_name(self) -> str:
        return self.class_path.rsplit(".", 1)[-1]

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "category": self.category,
            "class_path": self.class_path,
            "tags": list(self.tags),
            "strategy": {
                "class_path": self.strategy.class_path,
                "parameters": self.strategy.parameters,
                "instruments": [vars(inst) for inst in self.strategy.instruments],
            },
            "router": {
                "allowed_sessions": list(self.router.allowed_sessions),
                "allow_spread_bands": list(self.router.allow_spread_bands),
                "allow_rv_bands": list(self.router.allow_rv_bands),
                "max_latency_ms": self.router.max_latency_ms,
                "category_cap_pct": self.router.category_cap_pct,
                "tags": list(self.router.tags),
            },
            "risk": {
                "risk_per_trade_pct": self.risk.risk_per_trade_pct,
                "max_daily_dd_pct": self.risk.max_daily_dd_pct,
                "notional_cap": self.risk.notional_cap,
                "max_concurrent_positions": self.risk.max_concurrent_positions,
                "warmup_trades": self.risk.warmup_trades,
            },
            "features": {
                "required": list(self.features.required),
                "optional": list(self.features.optional),
            },
            "runner": {
                "runner_config": self.runner.runner_config,
                "cli_args": self.runner.cli_args,
            },
            "state": {
                "archive_namespace": self.state.archive_namespace,
                "ev_profile": self.state.ev_profile,
            },
        }
        return data


def _read_yaml(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"manifest must be a mapping: {path}")
    return data


def _normalise_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(meta, dict):
        raise ValueError("meta block is required and must be a mapping")
    if "id" not in meta:
        raise ValueError("meta.id is required")
    if "name" not in meta:
        raise ValueError("meta.name is required")
    category = str(meta.get("category", "").strip().lower())
    if not category:
        raise ValueError("meta.category is required")
    tags = tuple(str(t).strip().lower() for t in meta.get("tags", []) if str(t).strip())
    description = str(meta.get("description", ""))
    version = str(meta.get("version", "1.0"))
    return {
        "id": str(meta["id"]),
        "name": str(meta["name"]),
        "category": category,
        "description": description,
        "version": version,
        "tags": tags,
    }


def load_manifest(path: str | Path) -> StrategyManifest:
    """Load a strategy manifest YAML file, returning a StrategyManifest instance."""
    path = Path(path)
    data = _read_yaml(path)
    meta_norm = _normalise_meta(data.get("meta", {}))
    strategy_block = StrategySpec.from_dict(data.get("strategy", {}))
    router_block = RouterSpec.from_dict(data.get("router", {}))
    risk_block = RiskSpec.from_dict(data.get("risk", {}))
    features_block = FeatureSpec.from_dict(data.get("features", {}))
    runner_block = RunnerDefaults.from_dict(data.get("runner", {}))
    state_block = StateSpec.from_dict(data.get("state", {}))

    manifest = StrategyManifest(
        id=meta_norm["id"],
        name=meta_norm["name"],
        category=meta_norm["category"],
        class_path=strategy_block.class_path,
        version=meta_norm["version"],
        description=meta_norm["description"],
        tags=meta_norm["tags"],
        strategy=strategy_block,
        router=router_block,
        risk=risk_block,
        features=features_block,
        runner=runner_block,
        state=state_block,
        raw=data,
    )
    manifest.ensure_valid()
    return manifest


def load_manifests(directory: str | Path) -> Dict[str, StrategyManifest]:
    """Load all manifests under the given directory (recursively)."""
    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"manifest directory not found: {directory}")
    manifests: Dict[str, StrategyManifest] = {}
    for path in sorted(directory.rglob("*.yaml")):
        manifest = load_manifest(path)
        if manifest.id in manifests:
            raise ValueError(f"duplicate manifest id '{manifest.id}' in {path}")
        manifests[manifest.id] = manifest
    return manifests


def iter_manifest_paths(paths: Iterable[str | Path]) -> Iterable[Path]:
    for p in paths:
        path = Path(p)
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from path.rglob("*.yaml")
