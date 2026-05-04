"""Ray-backed adapter that mimics concurrent.futures.ProcessPoolExecutor.

Why this exists:
    The MCP backtest tools were originally written against ProcessPoolExecutor:
        pool = _get_worker_pool()
        results = pool.map(worker, items)              # MC paths
        f = pool.submit(worker, args); f.result()      # optimizer trials
    Replacing those call sites with raw Ray APIs (`ray.remote`, `ray.get`,
    `ray.wait`) would touch dozens of lines across facade.py and the optimizer.
    A drop-in adapter keeps the existing call sites unchanged and concentrates
    the dispatch decision in one place: src/mcp_server/facade.py:_get_worker_pool().

API compatibility surface (only what the codebase actually uses):
    .submit(fn, *args, **kwargs)  -> concurrent.futures.Future
    .map(fn, iterable, chunksize=1) -> iterator of results, in input order
    .shutdown(wait=True)          -> release ray.remote wrapper cache

Compatibility with concurrent.futures.as_completed():
    submit() returns a real concurrent.futures.Future via ObjectRef.future()
    (Ray 2.x). Existing as_completed() callers don't need changes.

NOT implemented (raise AttributeError if called):
    .map(..., timeout=...) — Ray.get() takes timeout per-call, not per-iterator.
    Context manager protocol (__enter__/__exit__) — never used in this codebase.

Trust boundary:
    This module imports `ray` lazily through src.research.ray_client, which
    refuses to initialize on QUANT_HOST_ROLE=production. Importing this file
    does NOT pull in `ray` until you actually instantiate RayPool.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future
from typing import Any, Callable, Iterable, Iterator

logger = logging.getLogger(__name__)


class RayPool:
    """ProcessPoolExecutor-shaped adapter that dispatches to a Ray cluster."""

    def __init__(self, ray_module: Any, max_workers: int | None = None) -> None:
        self._ray = ray_module
        self._max_workers = max_workers
        self._remote_cache: dict[Callable[..., Any], Any] = {}

    def _wrap(self, fn: Callable[..., Any]) -> Any:
        cached = self._remote_cache.get(fn)
        if cached is None:
            cached = self._ray.remote(fn)
            self._remote_cache[fn] = cached
        return cached

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future:
        """Submit a single task. Returns a concurrent.futures.Future via ObjectRef.future().

        as_completed() and Future.result() work natively against this object.
        """
        remote_fn = self._wrap(fn)
        ref = remote_fn.remote(*args, **kwargs)
        return ref.future()

    def map(
        self,
        fn: Callable[..., Any],
        iterable: Iterable[Any],
        chunksize: int = 1,  # noqa: ARG002 - kept for ProcessPoolExecutor.map() API parity
    ) -> Iterator[Any]:
        """Apply ``fn`` to each item in ``iterable`` on Ray workers.

        ProcessPoolExecutor.map() calls fn(item) for each item. Ray equivalent
        is one .remote() per item. Results returned in input order, matching
        ProcessPoolExecutor.map() semantics. Synchronous: blocks until all
        results are available.
        """
        remote_fn = self._wrap(fn)
        refs = [remote_fn.remote(item) for item in iterable]
        if not refs:
            return iter([])
        return iter(self._ray.get(refs))

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:  # noqa: ARG002
        """Release the @ray.remote wrapper cache.

        Does NOT shut down the Ray cluster itself — that lives elsewhere
        (the WSL systemd-user unit owns the head). Safe to call multiple times.
        """
        self._remote_cache.clear()


__all__ = ["RayPool"]
