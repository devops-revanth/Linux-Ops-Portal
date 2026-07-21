"""
Shared application utilities.
"""
from __future__ import annotations

# ── Environment display order ─────────────────────────────────────────────── #
# Controls the order environments appear in every UI surface: dashboard cards,
# dropdowns, filter bars, summary tables, and report charts.
# Keys are exact environment names as stored in the database.

_ENV_DISPLAY_ORDER: dict[str, int] = {
    "Development": 0,
    "Stage":       1,
    "Demo":        2,
    "Production":  3,
}


def sort_envs(envs, *, key=None):
    """Return *envs* sorted by the canonical display order.

    Parameters
    ----------
    envs:
        Any iterable of objects whose environment name can be extracted.
    key:
        Callable that extracts the environment *name* string from each item.
        Defaults to ``lambda e: e.name`` (suits SQLAlchemy Environment ORM
        objects).  For raw tuple rows, pass e.g. ``key=lambda r: r[0]``.
    """
    if key is None:
        key = lambda e: e.name  # noqa: E731
    return sorted(envs, key=lambda e: _ENV_DISPLAY_ORDER.get(key(e), 99))
