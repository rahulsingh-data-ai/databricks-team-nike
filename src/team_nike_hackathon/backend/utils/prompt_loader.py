"""Load prompt templates from markdown files."""

import os
import threading
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_cache: dict[str, str] = {}
_lock = threading.Lock()


def load_prompt(name: str) -> str:
    """Load a prompt from backend/prompts/{name}.md with thread-safe caching."""
    with _lock:
        if name in _cache:
            return _cache[name]

    path = os.path.join(_PROMPTS_DIR, f"{name}.md")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Prompt not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()

    with _lock:
        _cache[name] = text
    return text
