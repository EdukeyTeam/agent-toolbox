"""Content-free interchange helpers. No network or credential access."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any

SCHEMA_VERSION = 1
LISTS = ("usage", "contexts", "tools", "quotas", "sessions", "sources", "warnings")
COUNTS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens")


def dataset() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, **{key: [] for key in LISTS}}


def digest(*parts: object) -> str:
    return sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def timestamp(value: object) -> str | None:
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            dt = datetime.fromtimestamp(value / 1000 if value > 10**11 else value, timezone.utc)
        elif isinstance(value, str) and value:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return None
        else:
            return None
        return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None


def safe_name(value: object, default: str = "unknown") -> str:
    """Only machine identifiers; never accept a command/URL as a tool name."""
    if not isinstance(value, str) or not re.fullmatch(r"[\w.():/@+ -]{1,160}", value):
        return default
    if re.search(r"(?i)(?:bearer |sk-(?:proj-|ant-)?[a-z0-9]{12}|https?://|[\\])", value):
        return default
    return value


def warn(data: dict[str, Any], code: str, source_id: str, line: int | None = None) -> None:
    data["warnings"].append({"id": digest(code, source_id, line), "code": code,
                             "source_id": source_id, "line": line})


def source_info(path: Path, agent: str, device: str = "local", origin: str = "local") -> dict[str, Any]:
    return {"id": digest(agent, str(path.resolve())), "agent": agent, "device": safe_name(device),
            "origin": origin, "contract": "observed-local", "files_seen": 1,
            "files_parsed": 0, "rows_seen": 0, "malformed_rows": 0}


def jsonl(path: Path, data: dict[str, Any], source: dict[str, Any]):
    """Stream one source; invalid lines never enter error messages."""
    try:
        with path.open(encoding="utf-8-sig", errors="strict") as stream:
            for index, line in enumerate(stream, 1):
                source["rows_seen"] += 1
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("not an object")
                except (ValueError, RecursionError):
                    source["malformed_rows"] += 1
                    warn(data, "malformed_or_partial_line", source["id"], index)
                    continue
                yield index, row
        source["files_parsed"] = 1
    except (OSError, UnicodeError):
        warn(data, "source_unreadable", source["id"])


def text_chars(value: object) -> int:
    """Count visible text, excluding image/base64/encrypted payloads."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(text_chars(v) for v in value)
    if isinstance(value, dict):
        kind = value.get("type", "")
        if kind in ("image", "image_url", "input_image", "audio", "input_audio"):
            return 0
        return sum(text_chars(value[key]) for key in ("text", "content", "output", "summary") if key in value)
    return 0


def classify_text(text: str, role: str = "user") -> dict[str, int]:
    """Partition recorded text using visible injected tags, without retaining it."""
    mapping = {"skills_instructions": "skill_catalog", "plugins_instructions": "plugin_instructions",
               "user_instructions": "instructions", "INSTRUCTIONS": "instructions",
               "environment_context": "environment", "tools": "tool_schemas"}
    counts: dict[str, int] = {}
    consumed = 0
    pattern = r"<(" + "|".join(mapping) + r")(?:\s[^>]*)?>[\s\S]*?</\1>"
    for match in re.finditer(pattern, text):
        key = mapping[match.group(1)]
        counts[key] = counts.get(key, 0) + len(match.group())
        consumed += len(match.group())
    key = "instructions" if role in ("system", "developer") else (
        "assistant_messages" if role == "assistant" else "user_messages")
    counts[key] = counts.get(key, 0) + len(text) - consumed
    return counts


def context_observation(agent: str, session_id: str, observed_at: str | None,
                        chars: dict[str, int], used_tokens: int | None,
                        window_tokens: int | None, compactions: int = 0,
                        model: str = "unknown", **extra: Any) -> dict[str, Any]:
    ratio = 3.1 if re.search(r"claude-(?:.*-5|.*-4-[789])", model) else 4.0
    categories = [{"name": name, "characters": count, "estimated_tokens": round(count / ratio),
                   "lower_tokens": round(count / 6), "upper_tokens": round(count / 2),
                   "quality": "estimated"} for name, count in sorted(chars.items()) if count]
    visible = sum(row["estimated_tokens"] for row in categories)
    return {"id": digest("context", agent, session_id, observed_at, compactions), "agent": agent,
            "session_id": session_id, "observed_at": observed_at, "used_tokens": used_tokens,
            "window_tokens": window_tokens, "basis": "input_plus_output" if agent == "codex" else "input_only",
            "provider_percent": None, "computed_percent": (100 * used_tokens / window_tokens
                if used_tokens is not None and window_tokens else None),
            "categories": categories, "visible_estimated_tokens": visible,
            "unattributed_tokens": used_tokens - visible if used_tokens is not None else None,
            "compactions": compactions, "model": model, "quality": "reported" if used_tokens is not None else "unavailable",
            "estimation_method": f"visible characters / {ratio}; range characters / 6 to / 2",
            "retention_status": "recorded-visible-history", **extra}
