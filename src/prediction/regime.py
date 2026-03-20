"""HMM regime classifier mapping hidden states to market regimes."""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import structlog

logger = structlog.get_logger(__name__)

REGIME_LABELS = ("trending", "choppy", "volatile", "uncertain")


@dataclass
class RegimeMapping:
    """Maps HMM hidden state indices to regime labels based on learned statistics."""
    state_to_label: dict[int, str] = field(default_factory=dict)
    state_stats: dict[int, dict[str, float]] = field(default_factory=dict)


@dataclass
class StabilityReport:
    mean_duration: float
    switching_frequency: float
    state_durations: dict[int, float] = field(default_factory=dict)
    rapid_switching: bool = False


class RegimeClassifier:
    """HMM with 3-4 hidden states classifying market regimes."""

    def __init__(self, n_states: int = 4, n_iter: int = 100, random_state: int = 42) -> None:
        self.n_states = n_states
        self.n_iter = n_iter
        self.random_state = random_state
        self._model: Any = None
        self._mapping = RegimeMapping()

    def train(self, features: npt.NDArray[np.float64]) -> RegimeMapping:
        """Train HMM on returns, volatility, volume features."""
        from hmmlearn.hmm import GaussianHMM

        self._model = GaussianHMM(
            n_components=self.n_states,
            covariance_type="full",
            n_iter=self.n_iter,
            random_state=self.random_state,
        )
        self._model.fit(features)
        self._mapping = self._auto_map_states(features)
        return self._mapping

    def predict_states(self, features: npt.NDArray[np.float64]) -> npt.NDArray[np.int32]:
        """Predict hidden state sequence."""
        if self._model is None:
            raise RuntimeError("Model not trained")
        return np.asarray(self._model.predict(features), dtype=np.int32)

    def predict_regimes(self, features: npt.NDArray[np.float64]) -> list[str]:
        """Predict regime labels for each observation."""
        states = self.predict_states(features)
        return [self._mapping.state_to_label.get(int(s), "uncertain") for s in states]

    def predict_posteriors(self, features: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Return posterior probabilities for each state."""
        if self._model is None:
            raise RuntimeError("Model not trained")
        return np.asarray(self._model.predict_proba(features), dtype=np.float64)

    def trend_strength(self, features: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Derive trend_strength from max posterior probability. High = confident about state."""
        posteriors = self.predict_posteriors(features)
        return np.asarray(np.max(posteriors, axis=1), dtype=np.float64)

    def evaluate_stability(self, features: npt.NDArray[np.float64]) -> StabilityReport:
        """Measure average state duration and switching frequency."""
        states = self.predict_states(features)
        n = len(states)
        if n == 0:
            return StabilityReport(mean_duration=0.0, switching_frequency=0.0)

        switches = int(np.sum(np.diff(states) != 0))
        switching_freq = switches / max(n - 1, 1)

        durations: dict[int, list[int]] = {s: [] for s in range(self.n_states)}
        run_state = int(states[0])
        run_len = 1
        for i in range(1, n):
            if int(states[i]) == run_state:
                run_len += 1
            else:
                durations[run_state].append(run_len)
                run_state = int(states[i])
                run_len = 1
        durations[run_state].append(run_len)

        state_mean_dur = {
            s: float(np.mean(d)) if d else 0.0 for s, d in durations.items()
        }
        all_runs = [r for runs in durations.values() for r in runs]
        mean_dur = float(np.mean(all_runs)) if all_runs else 0.0
        rapid = switching_freq > 0.3

        return StabilityReport(
            mean_duration=mean_dur,
            switching_frequency=switching_freq,
            state_durations=state_mean_dur,
            rapid_switching=rapid,
        )

    def _auto_map_states(self, features: npt.NDArray[np.float64]) -> RegimeMapping:
        """Automatically map hidden states to regime labels based on state means."""
        states = self.predict_states(features)
        stats: dict[int, dict[str, float]] = {}
        for s in range(self.n_states):
            mask = states == s
            if int(mask.sum()) == 0:
                stats[s] = {"mean_return": 0.0, "volatility": 0.0, "count": 0.0}
                continue
            subset = features[mask]
            stats[s] = {
                "mean_return": float(np.mean(subset[:, 0])),
                "volatility": float(np.std(subset[:, 0])),
                "count": float(int(mask.sum())),
            }

        labels_available = list(REGIME_LABELS[:self.n_states])
        sorted_by_return = sorted(stats.keys(), key=lambda s: stats[s]["mean_return"])
        sorted_by_vol = sorted(
            stats.keys(), key=lambda s: stats[s]["volatility"], reverse=True,
        )

        mapping: dict[int, str] = {}
        assigned: set[str] = set()
        used_states: set[int] = set()

        if "trending" in labels_available:
            s = sorted_by_return[-1]
            mapping[s] = "trending"
            assigned.add("trending")
            used_states.add(s)

        if "volatile" in labels_available:
            for s in sorted_by_vol:
                if s not in used_states:
                    mapping[s] = "volatile"
                    assigned.add("volatile")
                    used_states.add(s)
                    break

        if "choppy" in labels_available:
            for s in sorted_by_return:
                if s not in used_states:
                    mapping[s] = "choppy"
                    assigned.add("choppy")
                    used_states.add(s)
                    break

        for s in range(self.n_states):
            if s not in used_states:
                mapping[s] = "uncertain"

        return RegimeMapping(state_to_label=mapping, state_stats=stats)

    @property
    def mapping(self) -> RegimeMapping:
        return self._mapping

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "model": self._model, "mapping": self._mapping,
                "n_states": self.n_states, "n_iter": self.n_iter,
                "random_state": self.random_state,
            }, f)

    @classmethod
    def load(cls, path: Path) -> RegimeClassifier:
        with open(path, "rb") as f:
            data: dict[str, Any] = pickle.load(f)  # noqa: S301
        obj = cls(n_states=data["n_states"], n_iter=data["n_iter"],
                  random_state=data["random_state"])
        obj._model = data["model"]
        obj._mapping = data["mapping"]
        return obj
