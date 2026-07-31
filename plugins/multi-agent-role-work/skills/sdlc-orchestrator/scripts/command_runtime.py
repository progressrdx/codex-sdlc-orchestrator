"""Shared compatibility runtime for independently packaged command modules."""

from __future__ import annotations

from typing import Any


def invoke(
    namespace: dict[str, Any],
    name: str,
    api: Any,
    args: Any,
) -> Any:
    """Bind missing workflow API names once, then invoke a local command."""
    for candidate in dir(api):
        if not candidate.startswith("_") and candidate not in namespace:
            namespace[candidate] = getattr(api, candidate)
    return namespace[name](args)
