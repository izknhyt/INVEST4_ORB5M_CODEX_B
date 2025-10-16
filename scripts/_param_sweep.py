"""Shared helpers for Day ORB parameter sweep tooling."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.utils import yaml_compat as yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ensure_path_tokens(path_spec: str) -> Tuple[str, ...]:
    parts = [part.strip() for part in str(path_spec).split(".") if str(part).strip()]
    if not parts:
        raise ValueError("search space entries require a non-empty path")
    return tuple(parts)


@dataclass
class SearchDimension:
    """Configuration for a sweep dimension."""

    name: str
    path: Tuple[str, ...]
    kind: str
    values: Optional[List[Any]] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    precision: Optional[int] = None
    _cached_discrete: Optional[List[Any]] = field(default=None, init=False, repr=False)

    @classmethod
    def from_dict(cls, name: str, data: Mapping[str, Any]) -> "SearchDimension":
        if not isinstance(data, Mapping):  # pragma: no cover - defensive guard
            raise ValueError(f"search space entry '{name}' must be a mapping")
        kind_raw = str(data.get("type", "choice")).strip().lower()
        path = _ensure_path_tokens(data.get("path"))
        if kind_raw == "choice":
            values = data.get("values")
            if not isinstance(values, Sequence) or not values:
                raise ValueError(f"dimension '{name}' must define a non-empty values list")
            return cls(name=name, path=path, kind="choice", values=list(values))
        if kind_raw == "range":
            minimum = int(data.get("min"))
            maximum = int(data.get("max"))
            step = int(data.get("step", 1)) or 1
            return cls(name=name, path=path, kind="range", minimum=minimum, maximum=maximum, step=step)
        if kind_raw == "float_range":
            minimum = float(data.get("min"))
            maximum = float(data.get("max"))
            step = float(data.get("step", 0.1))
            precision = int(data.get("precision", 3))
            if step <= 0:
                raise ValueError(f"dimension '{name}' step must be > 0")
            return cls(
                name=name,
                path=path,
                kind="float_range",
                minimum=minimum,
                maximum=maximum,
                step=step,
                precision=precision,
            )
        raise ValueError(f"unsupported search dimension type '{kind_raw}' for '{name}'")

    def discrete_values(self) -> List[Any]:
        if self._cached_discrete is not None:
            return list(self._cached_discrete)
        if self.kind == "choice":
            self._cached_discrete = list(self.values or [])
            return list(self._cached_discrete)
        if self.kind == "range":
            assert self.minimum is not None and self.maximum is not None
            step = int(self.step or 1)
            values: List[int] = []
            current = int(self.minimum)
            while current <= int(self.maximum):
                values.append(current)
                current += step
            self._cached_discrete = values
            return list(values)
        if self.kind == "float_range":
            assert self.minimum is not None and self.maximum is not None and self.step is not None
            precision = self.precision if self.precision is not None else 3
            values: List[float] = []
            current = float(self.minimum)
            max_value = float(self.maximum)
            step = float(self.step)
            epsilon = step / 1000.0
            while current <= max_value + epsilon:
                values.append(round(current, precision))
                current += step
            self._cached_discrete = values
            return list(values)
        raise RuntimeError(f"unexpected dimension kind '{self.kind}'")

    def sample(self, rng) -> Any:
        candidates = self.discrete_values()
        if not candidates:
            raise RuntimeError(f"dimension '{self.name}' has no values to sample")
        return rng.choice(candidates)


@dataclass(frozen=True)
class BayesDimensionHint:
    """Hints describing how a dimension should be interpreted by Bayes search."""

    name: str
    mode: str
    transform: str = "identity"
    bounds: Optional[Tuple[float, float]] = None

    @classmethod
    def from_dict(cls, name: str, data: Mapping[str, Any]) -> "BayesDimensionHint":
        if not isinstance(data, Mapping):
            raise ValueError(f"bayes dimension hint '{name}' must be a mapping")
        mode = str(data.get("mode", "auto")).strip().lower()
        if mode not in {"auto", "continuous", "discrete", "categorical"}:
            raise ValueError(
                f"bayes dimension hint '{name}' mode must be one of auto/continuous/discrete/categorical"
            )
        transform = str(data.get("transform", "identity")).strip().lower()
        bounds_raw = data.get("bounds")
        bounds: Optional[Tuple[float, float]] = None
        if bounds_raw is not None:
            if (
                isinstance(bounds_raw, Sequence)
                and len(bounds_raw) == 2
                and all(isinstance(value, (int, float)) for value in bounds_raw)
            ):
                lower = float(bounds_raw[0])
                upper = float(bounds_raw[1])
                if upper <= lower:
                    raise ValueError(
                        f"bayes dimension hint '{name}' bounds must be strictly increasing"
                    )
                bounds = (lower, upper)
            else:
                raise ValueError(
                    f"bayes dimension hint '{name}' bounds must be a sequence of two numbers"
                )
        return cls(name=name, mode=mode, transform=transform, bounds=bounds)


@dataclass(frozen=True)
class BayesAcquisitionConfig:
    name: str
    parameters: Dict[str, Any]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BayesAcquisitionConfig":
        if not isinstance(data, Mapping):
            raise ValueError("bayes acquisition configuration must be a mapping")
        name_raw = data.get("name")
        if not name_raw:
            raise ValueError("bayes acquisition requires a name")
        name = str(name_raw)
        params = data.get("parameters") or {}
        if not isinstance(params, Mapping):
            raise ValueError("bayes acquisition parameters must be a mapping")
        return cls(name=name, parameters=dict(params))


@dataclass(frozen=True)
class BayesConfig:
    enabled: bool
    seed: Optional[int]
    acquisition: Optional[BayesAcquisitionConfig]
    exploration_upper_bound: Optional[int]
    initial_random_trials: int
    constraint_retry_limit: int
    transforms: Dict[str, BayesDimensionHint]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BayesConfig":
        if not isinstance(data, Mapping):
            raise ValueError("bayes configuration must be a mapping")
        enabled = bool(data.get("enabled", True))
        seed_raw = data.get("seed")
        seed = int(seed_raw) if seed_raw is not None else None
        acquisition_block = data.get("acquisition")
        acquisition = (
            BayesAcquisitionConfig.from_dict(acquisition_block)
            if acquisition_block
            else None
        )
        exploration_upper = data.get("exploration_upper_bound")
        exploration_upper_bound = int(exploration_upper) if exploration_upper is not None else None
        initial_random = int(data.get("initial_random_trials", 5))
        if initial_random < 0:
            raise ValueError("bayes.initial_random_trials must be >= 0")
        retry_limit = int(data.get("constraint_retry_limit", 0))
        if retry_limit < 0:
            raise ValueError("bayes.constraint_retry_limit must be >= 0")
        transforms_block = data.get("transforms") or {}
        if not isinstance(transforms_block, Mapping):
            raise ValueError("bayes.transforms must be a mapping")
        transforms = {
            name: BayesDimensionHint.from_dict(name, spec)
            for name, spec in transforms_block.items()
        }
        return cls(
            enabled=enabled,
            seed=seed,
            acquisition=acquisition,
            exploration_upper_bound=exploration_upper_bound,
            initial_random_trials=initial_random,
            constraint_retry_limit=retry_limit,
            transforms=transforms,
        )


@dataclass(frozen=True)
class SeasonalSlice:
    """Defines a seasonal evaluation window."""

    id: str
    start: date
    end: date

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SeasonalSlice":
        if not isinstance(data, Mapping):
            raise ValueError("seasonal slice entries must be mappings")
        slice_id = str(data.get("id") or "").strip()
        if not slice_id:
            raise ValueError("seasonal slices require an id")
        start_raw = str(data.get("start") or "").strip()
        end_raw = str(data.get("end") or "").strip()
        if not start_raw or not end_raw:
            raise ValueError(f"seasonal slice '{slice_id}' requires start/end")
        start = datetime.fromisoformat(start_raw).date()
        end = datetime.fromisoformat(end_raw).date()
        if end < start:
            raise ValueError(f"seasonal slice '{slice_id}' end precedes start")
        return cls(id=slice_id, start=start, end=end)


@dataclass(frozen=True)
class ConstraintConfig:
    id: str
    metric: str
    op: str
    threshold: float
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConstraintConfig":
        if not isinstance(data, Mapping):
            raise ValueError("constraint entries must be mappings")
        constraint_id = str(data.get("id") or "").strip()
        if not constraint_id:
            raise ValueError("constraints require an id")
        metric = str(data.get("metric") or "").strip()
        if not metric:
            raise ValueError(f"constraint '{constraint_id}' requires metric")
        op = str(data.get("op") or ">=").strip()
        threshold = float(data.get("threshold"))
        description = data.get("description")
        return cls(id=constraint_id, metric=metric, op=op, threshold=threshold, description=description)


@dataclass(frozen=True)
class ScoreTerm:
    metric: str
    goal: str
    weight: float

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScoreTerm":
        if not isinstance(data, Mapping):
            raise ValueError("score entries must be mappings")
        metric = str(data.get("metric") or "").strip()
        if not metric:
            raise ValueError("score entries require a metric")
        goal_raw = str(data.get("goal") or "max").strip().lower()
        goal = "max" if goal_raw in {"max", "maximize", "maximise"} else "min"
        weight = float(data.get("weight", 1.0))
        return cls(metric=metric, goal=goal, weight=weight)


@dataclass
class ScoreConfig:
    objectives: List[ScoreTerm] = field(default_factory=list)
    penalties: List[ScoreTerm] = field(default_factory=list)
    tie_breakers: List[ScoreTerm] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScoreConfig":
        if not data:
            return cls()
        objectives = [ScoreTerm.from_dict(entry) for entry in data.get("objectives", [])]
        penalties = [ScoreTerm.from_dict(entry) for entry in data.get("penalties", [])]
        tie_breakers = [ScoreTerm.from_dict(entry) for entry in data.get("tie_breakers", [])]
        return cls(objectives=objectives, penalties=penalties, tie_breakers=tie_breakers)

    @staticmethod
    def _resolve_metric(context: Mapping[str, Any], metric: str) -> Optional[float]:
        value = resolve_metric_path(context, metric)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _apply_goal(value: float, goal: str) -> float:
        return value if goal == "max" else -value

    def compute(self, context: Mapping[str, Any]) -> Tuple[float, List[Dict[str, Any]]]:
        total = 0.0
        breakdown: List[Dict[str, Any]] = []
        for category, terms in (("objective", self.objectives), ("penalty", self.penalties)):
            for term in terms:
                value = self._resolve_metric(context, term.metric)
                if value is None:
                    breakdown.append(
                        {
                            "metric": term.metric,
                            "goal": term.goal,
                            "weight": term.weight,
                            "value": None,
                            "contribution": 0.0,
                            "category": category,
                            "missing": True,
                        }
                    )
                    continue
                contribution = term.weight * self._apply_goal(value, term.goal)
                total += contribution
                breakdown.append(
                    {
                        "metric": term.metric,
                        "goal": term.goal,
                        "weight": term.weight,
                        "value": value,
                        "contribution": contribution,
                        "category": category,
                        "missing": False,
                    }
                )
        return total, breakdown

    def tie_breaker_key(self, context: Mapping[str, Any]) -> Tuple[float, ...]:
        key: List[float] = []
        for term in self.tie_breakers:
            value = self._resolve_metric(context, term.metric)
            if value is None:
                key.append(float("-inf"))
                continue
            key.append(self._apply_goal(value, term.goal))
        return tuple(key)

    def tie_breaker_values(self, context: Mapping[str, Any]) -> List[Dict[str, Any]]:
        values: List[Dict[str, Any]] = []
        for term in self.tie_breakers:
            raw = resolve_metric_path(context, term.metric)
            values.append({"metric": term.metric, "goal": term.goal, "value": raw})
        return values


@dataclass
class ExperimentConfig:
    path: Path
    identifier: str
    manifest_path: Path
    manifest_id: Optional[str]
    mode: Optional[str]
    base_output_dir: Path
    runner_cli: List[str]
    runner_equity: Optional[float]
    use_years_from_data: bool
    record_runtime: bool
    dimensions: List[SearchDimension]
    seasonal_slices: List[SeasonalSlice]
    constraints: List[ConstraintConfig]
    scoring: ScoreConfig
    history_enabled: bool
    history_notes: Optional[str]
    bayes: Optional[BayesConfig]

    def __post_init__(self) -> None:
        self._dimension_map: Dict[str, SearchDimension] = {dim.name: dim for dim in self.dimensions}

    @classmethod
    def from_dict(cls, path: Path, data: Mapping[str, Any]) -> "ExperimentConfig":
        if not isinstance(data, Mapping):
            raise ValueError("experiment configuration must be a mapping")
        manifest_path_raw = data.get("manifest_path")
        if not manifest_path_raw:
            raise ValueError("experiment configuration requires manifest_path")
        manifest_path = (REPO_ROOT / str(manifest_path_raw)).resolve()
        identifier = path.stem
        base_output = data.get("base_output_dir") or f"runs/sweeps/{identifier}"
        base_output_dir = (REPO_ROOT / str(base_output)).resolve()
        runner_block = data.get("runner") or {}
        base_cli = runner_block.get("base_cli") or []
        if not isinstance(base_cli, Sequence):
            raise ValueError("runner.base_cli must be a sequence")
        runner_cli = [str(token) for token in base_cli]
        runner_equity = runner_block.get("equity")
        equity_value = float(runner_equity) if runner_equity is not None else None
        use_years = bool(runner_block.get("use_years_from_data", True))
        record_runtime = bool(runner_block.get("record_runtime", False))
        search_space = data.get("search_space") or {}
        if not isinstance(search_space, Mapping):
            raise ValueError("search_space must be a mapping")
        dimensions = [SearchDimension.from_dict(name, spec) for name, spec in search_space.items()]
        seasonal = [SeasonalSlice.from_dict(entry) for entry in data.get("seasonal_slices", [])]
        constraints = [ConstraintConfig.from_dict(entry) for entry in data.get("constraints", [])]
        scoring = ScoreConfig.from_dict(data.get("scoring") or {})
        history_block = data.get("history") or {}
        history_enabled = bool(history_block.get("enabled", False))
        history_notes = history_block.get("notes")
        bayes_block = data.get("bayes")
        bayes = BayesConfig.from_dict(bayes_block) if bayes_block else None
        return cls(
            path=path,
            identifier=identifier,
            manifest_path=manifest_path,
            manifest_id=str(data.get("manifest_id") or "") or None,
            mode=str(data.get("mode") or "") or None,
            base_output_dir=base_output_dir,
            runner_cli=runner_cli,
            runner_equity=equity_value,
            use_years_from_data=use_years,
            record_runtime=record_runtime,
            dimensions=dimensions,
            seasonal_slices=seasonal,
            constraints=constraints,
            scoring=scoring,
            history_enabled=history_enabled,
            history_notes=str(history_notes) if history_notes else None,
            bayes=bayes,
        )

    @property
    def dimension_map(self) -> Mapping[str, SearchDimension]:
        return self._dimension_map

    def make_context(
        self,
        *,
        params: Optional[Mapping[str, Any]] = None,
        metrics: Optional[Mapping[str, Any]] = None,
        seasonal: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        context: Dict[str, Any] = {
            "metrics": dict(metrics or {}),
            "seasonal": dict(seasonal or {}),
        }
        if params is not None:
            context["params"] = dict(params)
        return context

    def search_space_size(self) -> int:
        sizes = [len(dim.discrete_values()) for dim in self.dimensions]
        if not sizes:
            return 0
        total = 1
        for size in sizes:
            total *= max(1, size)
        return total


def resolve_metric_path(data: Mapping[str, Any], path: str) -> Any:
    current: Any = data
    for token in [part for part in path.split(".") if part]:
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        else:
            return None
    return current


def evaluate_constraints(
    context: Mapping[str, Any], constraints: Iterable[ConstraintConfig]
) -> Tuple[Dict[str, Dict[str, Any]], bool]:
    results: Dict[str, Dict[str, Any]] = {}
    feasible = True
    for constraint in constraints:
        value = resolve_metric_path(context, constraint.metric)
        status = "pass"
        numeric_value: Optional[float]
        if value is None:
            status = "unknown"
            numeric_value = None
            feasible = False
        else:
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                status = "invalid"
                numeric_value = None
                feasible = False
        if numeric_value is not None:
            if constraint.op == ">=" and numeric_value < constraint.threshold:
                status = "fail"
                feasible = False
            elif constraint.op == "<=" and numeric_value > constraint.threshold:
                status = "fail"
                feasible = False
        results[constraint.id] = {
            "metric": constraint.metric,
            "op": constraint.op,
            "threshold": constraint.threshold,
            "value": numeric_value,
            "status": status,
            "description": constraint.description,
        }
    return results, feasible


def resolve_experiment_path(identifier: str | Path) -> Path:
    candidate = Path(identifier)
    if candidate.suffix and candidate.exists():
        return candidate.resolve()
    if candidate.exists():
        return candidate.resolve()
    experiments_dir = REPO_ROOT / "configs" / "experiments"
    if candidate.suffix:
        resolved = (REPO_ROOT / candidate).resolve()
        if resolved.exists():
            return resolved
    else:
        yaml_candidate = experiments_dir / f"{candidate}.yaml"
        if yaml_candidate.exists():
            return yaml_candidate.resolve()
        alt_candidate = (REPO_ROOT / candidate).with_suffix(".yaml")
        if alt_candidate.exists():
            return alt_candidate.resolve()
    raise FileNotFoundError(f"experiment configuration not found for '{identifier}'")


def load_experiment_config(identifier: str | Path) -> ExperimentConfig:
    path = resolve_experiment_path(identifier)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        raise ValueError(f"experiment configuration '{path}' is empty")
    return ExperimentConfig.from_dict(path, data)


__all__ = [
    "BayesAcquisitionConfig",
    "BayesConfig",
    "BayesDimensionHint",
    "ConstraintConfig",
    "ExperimentConfig",
    "ScoreConfig",
    "ScoreTerm",
    "SearchDimension",
    "SeasonalSlice",
    "evaluate_constraints",
    "load_experiment_config",
    "resolve_experiment_path",
    "resolve_metric_path",
]
