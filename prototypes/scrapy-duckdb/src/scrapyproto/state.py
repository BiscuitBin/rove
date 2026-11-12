"""The prototype's state file: the machine name, its image and the Scrapy pin it holds."""

import json
import os
import sys
from pathlib import Path
from typing import Any

# src/scrapyproto/state.py -> prototypes/scrapy-duckdb/src/scrapyproto; parents[4] is the repo root.
DEFAULT_STATE_DIR = Path(__file__).resolve().parents[4] / "ai_tmp" / "scrapy-duckdb"


def path(state_dir: Path | None = None) -> Path:
    return (state_dir or DEFAULT_STATE_DIR) / "state.json"


def load(state_dir: Path | None = None) -> dict[str, Any] | None:
    p = path(state_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError) as exc:
        # As absent: nothing acts on an unreadable file, and nothing here deletes a machine.
        print(f"warning: ignoring unreadable state file {p}: {exc}", file=sys.stderr)
        return None
    return data if isinstance(data, dict) else None


def save(data: dict[str, Any], state_dir: Path | None = None) -> Path:
    """Write owner-only and atomically, so a crash mid-save leaves the previous file whole."""
    p = path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data, indent=2) + "\n")
    tmp.replace(p)
    return p


def clear(state_dir: Path | None = None) -> None:
    path(state_dir).unlink(missing_ok=True)
