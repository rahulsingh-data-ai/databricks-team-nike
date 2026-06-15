"""Load prompt templates from markdown files.

Prompts live in ``backend/prompts/`` as ``{name}.md``. We cache them on
first read with a thread-safe lock so the pipeline never hits the disk
more than once per prompt for the lifetime of the process.
"""

from __future__ import annotations

import threading
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_cache: dict[str, str] = {}
_lock = threading.Lock()


def load_prompt(name: str) -> str:
    """Load a prompt from ``backend/prompts/{name}.md``."""
    with _lock:
        if name in _cache:
            return _cache[name]

    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")

    text = path.read_text(encoding="utf-8").strip()

    with _lock:
        _cache[name] = text
    return text
