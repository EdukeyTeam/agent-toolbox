#!/usr/bin/env python3
"""Refresh local Context7 after an agent tool call or at the end of a turn."""
import json
from pathlib import Path
import sys

import local_context7 as local


def handle(event: dict) -> dict | None:
    name = event.get("hook_event_name")
    if name not in {"PostToolUse", "Stop", "AfterTool", "AfterAgent", "afterFileEdit", "afterShellExecution", "stop"}:
        return None
    # Never refresh a different checkout based on paths or commands in input.
    working = event.get("cwd")
    if not working and name in {"afterFileEdit", "afterShellExecution", "stop"}:
        # Cursor supplies workspace_roots rather than cwd for these events.
        roots = event.get("workspace_roots", [])
        if not isinstance(roots, list) or str(local.ROOT) not in roots:
            return None
        working = str(local.ROOT)
    if not isinstance(working, str) or not Path(working).resolve().is_relative_to(local.ROOT):
        return None
    runtime = local.runtime_path()
    result = local.refresh(local.load_backend(runtime), runtime)
    if not result["refreshed"]:
        return None
    message = f'Local Context7 refreshed: {result["changed"]} changed, {result["deleted"]} deleted; library {local.LIBRARY_ID}.'
    if name in {"afterFileEdit", "afterShellExecution", "stop"}:
        # Cursor expects event-specific output; no followup_message/loop request.
        return None
    if name in {"PostToolUse", "AfterTool"}:
        return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": message}}
    return {"systemMessage": message}


def main() -> int:
    try:
        payload = sys.stdin.read(1_048_577)
        if len(payload) > 1_048_576:
            raise ValueError("Hook payload exceeds 1 MiB; run local_context7.py refresh manually")
        event = json.loads(payload)
        if not isinstance(event, dict):
            raise ValueError("Expected a hook JSON object")
        output = handle(event)
        if output:
            print(json.dumps(output))
        return 0
    except Exception as exc:
        print(f"Local Context7 hook failed: {exc}. Run python tools/local_context7.py refresh before local search.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
