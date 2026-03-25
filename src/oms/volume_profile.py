"""Intraday volume profile for VWAP execution scheduling."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VolumeProfile:
    """Normalized intraday volume distribution across time buckets."""
    bucket_weights: list[float] = field(default_factory=list)
    n_buckets: int = 10

    def __post_init__(self) -> None:
        if not self.bucket_weights:
            self.bucket_weights = [1.0 / self.n_buckets] * self.n_buckets
        total = sum(self.bucket_weights)
        if total > 0:
            self.bucket_weights = [w / total for w in self.bucket_weights]

    @classmethod
    def from_ohlcv(cls, volumes: list[float], n_buckets: int = 10) -> VolumeProfile:
        """Build profile from historical intraday volume observations."""
        if not volumes:
            return cls(n_buckets=n_buckets)
        bucket_size = max(1, len(volumes) // n_buckets)
        buckets: list[float] = []
        for i in range(n_buckets):
            start = i * bucket_size
            end = min(start + bucket_size, len(volumes))
            chunk = volumes[start:end]
            buckets.append(sum(chunk) if chunk else 0.0)
        return cls(bucket_weights=buckets, n_buckets=n_buckets)
