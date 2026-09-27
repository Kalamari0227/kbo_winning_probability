from __future__ import annotations

import json
from pathlib import Path

from .schemas import Snapshot


def load_snapshot(path: Path) -> Snapshot:
    """Load a normalized JSON snapshot and validate every nested record."""

    with path.open("r", encoding="utf-8") as stream:
        return Snapshot.model_validate(json.load(stream))


def save_snapshot(snapshot: Snapshot, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
