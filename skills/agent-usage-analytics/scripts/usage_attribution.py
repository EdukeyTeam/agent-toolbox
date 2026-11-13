"""Explicit historical routes, never inferred from today's credentials/settings."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from usage_common import safe_name


def attribution_rank(row: dict[str, Any]) -> int:
    return {"reported": 0, "recorded": 1, "user_override": 2}.get(row.get("model_attribution"), 0)


def apply_attribution(data: dict[str, Any], mapping: object) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        raise ValueError("Attribution map must contain agent:session keys and provider/model objects")
    clean = {}
    for key, route in mapping.items():
        if not isinstance(key, str) or ":" not in key or not isinstance(route, dict):
            raise ValueError("Attribution entries require agent:session (or agent:*) and a route object")
        if set(route) - {"provider", "model", "speed", "inference_geo", "service_tier"} or not route.get("provider"):
            raise ValueError("Attribution needs provider and optional model/billing dimensions only")
        if any(not isinstance(v, str) or safe_name(v) == "unknown" for v in route.values()):
            raise ValueError("Attribution values must be safe model/provider identifiers")
        clean[key] = route
    result = deepcopy(data)
    for row in result.get("usage", []) + result.get("contexts", []):
        route = clean.get(str(row.get("agent")) + ":" + str(row.get("session_id")))
        route = route or clean.get(str(row.get("agent")) + ":*")
        if route is None:
            continue
        row.setdefault("reported_model", row.get("model", "unknown"))
        row.update(route)
        row["provider"] = {"z.ai": "zai", "z-ai": "zai"}.get(route["provider"].lower(), route["provider"].lower())
        row["model"] = route.get("model", "unknown")
        row["model_attribution"] = "user_override"
    return result
