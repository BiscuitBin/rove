"""The prototype's state file: machine name, host port and the API token."""

import json
import os
from pathlib import Path
from typing import Any

# src/c4ai_proto/state.py -> prototypes/crawl4ai-smolmachine/src/c4ai_proto; parents[4] is the repo root.
DEFAULT_STATE_DIR = Path(__file__).resolve().parents[4] / "ai_tmp" / "c4ai-proto"


def path(state_dir: Path | None = None) -> Path:
    return (state_dir or DEFAULT_STATE_DIR) / "state.json"


def load(state_dir: Path | None = None) -> dict[str, Any] | None:
    p = path(state_dir)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save(data: dict[str, Any], state_dir: Path | None = None) -> Path:
    p = path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    # The file holds the bearer token: owner-only, including when it already exists.
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data, indent=2) + "\n")
    return p


def clear(state_dir: Path | None = None) -> None:
    p = path(state_dir)
    if p.exists():
        p.unlink()
