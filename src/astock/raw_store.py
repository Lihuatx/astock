from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class JsonlRawStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def append(self, source: str, kind: str, payload: Any, received_at: datetime) -> Path:
        target_dir = self.root / source
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{received_at:%Y%m%d}.jsonl"
        record = {
            "received_at": received_at.isoformat(),
            "source": source,
            "kind": kind,
            "payload": payload,
        }
        with self._lock, target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str))
            handle.write("\n")
        return target

