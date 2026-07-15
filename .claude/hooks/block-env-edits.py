#!/usr/bin/env python3
"""PreToolUse hook: block edits to .env files (they contain secrets).

Receives JSON on stdin from Claude Code:
  {
    "session_id": "...",
    "hook_event_name": "PreToolUse",
    "tool_name": "Edit" | "Write" | "MultiEdit" | ...,
    "tool_input": { "file_path": "...", ... }
  }

Exit 0 → allow. Exit 2 → deny (stderr message shown to Claude).
"""
import json
import os
import sys

ALLOW_BASENAMES = {".env.example", ".env.sample", ".env.template", ".env.test"}
ALLOW_PATH_FRAGMENTS = {".env.example", ".env.sample", ".env.template", ".env.test"}


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return 0  # malformed input: don't block, let it through

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0

    # Normalize for comparison
    normalized = file_path.replace("\\", "/")
    basename = os.path.basename(normalized).lower()

    # Allow .env.example / .env.sample / .env.template
    if basename in ALLOW_BASENAMES or any(frag in normalized for frag in ALLOW_PATH_FRAGMENTS):
        return 0

    # Block any .env* file
    if basename.startswith(".env"):
        print(
            f"BLOCKED by PreToolUse hook: cannot {tool_name.lower()} '{file_path}'. "
            f".env files contain secrets (DB passwords, API keys) — edit manually "
            f"with your editor, not through Claude.",
            file=sys.stderr,
        )
        return 2

    # Block path fragments that look like nested .env (defense in depth)
    if "/.env" in normalized and not any(frag in normalized for frag in ALLOW_PATH_FRAGMENTS):
        print(
            f"BLOCKED by PreToolUse hook: cannot {tool_name.lower()} '{file_path}'.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
