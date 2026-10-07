"""Small platform helpers shared by local legacy tooling."""

from __future__ import annotations

import os
from pathlib import Path


def inference_environment(cache: Path, *, download: bool) -> dict[str, str]:
    """Keep OS startup paths while excluding provider tokens and Node options."""
    environment = {"PATH": os.environ.get("PATH", ""), "HOME": str(cache), "HF_HUB_OFFLINE": "0" if download else "1"}
    for key, value in os.environ.items():
        if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}:
            environment[key] = value
    return environment
