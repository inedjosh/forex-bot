"""Lightweight .env loader and typed config access.

No external dependency (no python-dotenv needed). On import, this reads a `.env` file
from the project root (if present) into os.environ, without overriding variables that are
already set in the real environment. Then use env_float/env_int/env_str to read values
with defaults.

This is what lets you tune the formula without touching code: edit `.env`, re-run.
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"


def load_dotenv(path: Path = _ENV_PATH) -> None:
    """Parse a simple KEY=VALUE .env file into os.environ (no overrides)."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Strip inline comments (value not quoted): FOO=1  # note
        if "#" in value and not (raw.count('"') >= 2 or raw.count("'") >= 2):
            value = value.split("#", 1)[0].strip()
        if key and key not in os.environ:
            os.environ[key] = value


# Load once at import time.
load_dotenv()


def env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def update_env(updates: dict, path: Path = _ENV_PATH) -> None:
    """Write KEY=value pairs into .env, preserving comments/order and updating live env.

    Existing keys are updated in place (inline comments on those lines are dropped for
    safety); unknown keys are appended. Used by the web UI's "Save settings" button.
    """
    updates = {k: str(v) for k, v in updates.items()}
    lines = path.read_text().splitlines() if path.exists() else []
    seen = set()

    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            lines[idx] = f"{key}={updates[key]}"
            seen.add(key)

    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n")

    # Reflect immediately in the running process so later reads see new values.
    for key, value in updates.items():
        os.environ[key] = value
