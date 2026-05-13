"""Monkey-patch for shioaji #179: session_down_callback_wrap arity mismatch.

The pysolace C++ binding calls ``SolClient.session_down_callback_wrap`` with
five positional arguments, but the Python wrapper accepts only ``self``. The
resulting ``TypeError`` propagates out of the C++ callback thread as
``pybind11::error_already_set`` → ``std::terminate`` → ``SIGABRT``/``SIGSEGV``,
killing the host process. We have observed ~88 restarts in 41 minutes on the
production VPS attributed to this path.

Upstream tracking: https://github.com/Sinotrade/Shioaji/issues/179

Fix: replace the wrapper with one that accepts ``*args, **kwargs`` and
delegates to the original. Idempotent and safe to call multiple times.
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

_PATCHED = False


def apply_shioaji_patch() -> bool:
    """Apply the ``session_down_callback_wrap`` arity patch.

    Returns ``True`` if the patch is in effect (already applied or applied
    this call), ``False`` if the target could not be located.
    """
    global _PATCHED
    if _PATCHED:
        return True
    try:
        from pysolace import SolClient  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("shioaji_patch_skipped_pysolace_not_importable")
        return False

    if not hasattr(SolClient, "session_down_callback_wrap"):
        logger.warning("shioaji_patch_skipped_no_target_method")
        return False

    _original = SolClient.session_down_callback_wrap

    def _patched_wrap(self, *args, **kwargs):
        """Absorb extra positional args from the C++ side; delegate to original.

        The original wrapper takes only ``self``. The C++ binding hands us
        five extra positional args (cf. shioaji#179) which trigger a
        ``TypeError`` and crash the process. We discard the extras and call
        the original with just ``self``. If the original genuinely needs the
        args, we fall back to passing them through; if that also fails we
        swallow the exception rather than terminate the process.
        """
        try:
            return _original(self)
        except TypeError:
            try:
                return _original(self, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — must not propagate
                logger.error(
                    "session_down_callback_failed_silently",
                    error=str(exc),
                    args_count=len(args),
                )
                return None
        except Exception as exc:  # noqa: BLE001 — must not propagate
            logger.error(
                "session_down_callback_unexpected_error",
                error=str(exc),
            )
            return None

    SolClient.session_down_callback_wrap = _patched_wrap
    _PATCHED = True
    logger.info("shioaji_patch_applied")
    return True
