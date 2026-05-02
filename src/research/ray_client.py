"""Ray client helper for offline research workloads.

This module is the ONLY place in the codebase that calls `ray.init`. Every
heavy MCP tool (run_parameter_sweep, run_monte_carlo, run_walk_forward,
run_sensitivity_check, run_stress_test, run_portfolio_walk_forward,
run_portfolio_optimization) should call `get_research_ray()` to obtain a
connected Ray runtime, then dispatch via `@ray.remote`.

Trust boundary (see .claude/plans/our-prod-server-constantly-expressive-whistle.md):

    1. Live trading on the prod VPS NEVER calls Ray. The systemd unit
       (scripts/deploy/quant-engine-api.service) sets QUANT_HOST_ROLE=production,
       which makes `get_research_ray()` raise immediately. This is defense in
       depth on top of the env-var gate.
    2. The dev/research host (WSL) sets QUANT_RAY_ADDRESS to point at the
       local Ray head. Ray is then used freely.
    3. If WSL is unreachable, `get_research_ray()` raises `RayUnavailable`
       within INIT_TIMEOUT_S. It NEVER blocks indefinitely and NEVER falls
       back to in-process execution silently.

Required env vars on the WSL host:
    QUANT_RAY_ADDRESS       e.g. ray://127.0.0.1:10001
    QUANT_RAY_TOKEN_PATH    file containing the Ray cluster auth token
                            (passed to ray.init as _redis_password)

Optional env vars:
    QUANT_RAY_NAMESPACE     default "quant-research"
    QUANT_RAY_INIT_TIMEOUT_S default 5
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

INIT_TIMEOUT_S_DEFAULT = 5
NAMESPACE_DEFAULT = "quant-research"

_init_lock = threading.Lock()
_initialized = False


class RayUnavailable(RuntimeError):
    """Raised when the Ray cluster cannot be reached or is disallowed.

    Callers MUST handle this and surface a clear "research-only feature
    unavailable" message. Never catch and silently fall back to local
    execution — that's how heavy compute ended up on the trading VPS.
    """


def _read_token(token_path: str) -> str:
    p = Path(token_path).expanduser()
    if not p.is_file():
        raise RayUnavailable(f"QUANT_RAY_TOKEN_PATH={token_path} does not exist")
    token = p.read_text().strip()
    if not token:
        raise RayUnavailable(f"QUANT_RAY_TOKEN_PATH={token_path} is empty")
    return token


def _refuse_on_production_host() -> None:
    role = os.getenv("QUANT_HOST_ROLE", "").strip().lower()
    if role == "production":
        raise RayUnavailable(
            "heavy compute disabled on production host (QUANT_HOST_ROLE=production). "
            "Run research workloads on the WSL Ray cluster instead."
        )


def get_research_ray():
    """Connect to the research Ray cluster, returning the imported `ray` module.

    Idempotent: subsequent calls return the same connected module without
    reinitializing.

    Raises:
        RayUnavailable: if QUANT_HOST_ROLE=production, if the env vars are
            missing, if the token file is missing/empty, if `ray` itself is
            not installed, or if `ray.init` fails / times out.
    """
    global _initialized

    _refuse_on_production_host()

    address = os.getenv("QUANT_RAY_ADDRESS", "").strip()
    if not address:
        raise RayUnavailable(
            "QUANT_RAY_ADDRESS is not set. Set it on the WSL host (e.g. "
            "ray://<wsl-tailnet-ip>:10001). It must remain unset on the prod VPS."
        )

    token_path = os.getenv("QUANT_RAY_TOKEN_PATH", "").strip()
    if not token_path:
        raise RayUnavailable(
            "QUANT_RAY_TOKEN_PATH is not set. Point it at a chmod-600 file "
            "containing the Ray cluster auth token."
        )

    try:
        import ray  # noqa: PLC0415 - lazy import, see module docstring
    except ImportError as e:
        raise RayUnavailable(
            f"the `ray` package is not installed in this environment ({e}). "
            "Install on the WSL host with `uv pip install 'ray[default]==2.x.y'`."
        ) from e

    with _init_lock:
        if _initialized and ray.is_initialized():
            return ray

        token = _read_token(token_path)
        namespace = os.getenv("QUANT_RAY_NAMESPACE", NAMESPACE_DEFAULT).strip() or NAMESPACE_DEFAULT
        timeout_s = _env_int("QUANT_RAY_INIT_TIMEOUT_S", INIT_TIMEOUT_S_DEFAULT)

        logger.info(
            "connecting to Ray cluster: address=%s namespace=%s timeout=%ds",
            address,
            namespace,
            timeout_s,
        )

        init_error: BaseException | None = None
        ready = threading.Event()

        def _do_init() -> None:
            nonlocal init_error
            try:
                ray.init(
                    address=address,
                    namespace=namespace,
                    _redis_password=token,
                    ignore_reinit_error=True,
                    log_to_driver=False,
                    configure_logging=False,
                )
            except BaseException as e:  # noqa: BLE001
                init_error = e
            finally:
                ready.set()

        t = threading.Thread(target=_do_init, name="ray-init", daemon=True)
        t.start()

        if not ready.wait(timeout=timeout_s):
            raise RayUnavailable(
                f"ray.init({address!r}) did not return within {timeout_s}s "
                "(WSL host probably not reachable or not running the Ray head)"
            )

        if init_error is not None:
            raise RayUnavailable(f"ray.init failed: {init_error}") from init_error

        _initialized = True
        logger.info("connected to Ray cluster: %s", address)
        return ray


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("invalid int for %s=%r; using default %d", name, raw, default)
        return default


__all__ = ["RayUnavailable", "get_research_ray"]
