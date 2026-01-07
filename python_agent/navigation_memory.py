from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class NavigationMemory:
    path: Path
    store: Dict[str, Any]

    @staticmethod
    def load(path: Path) -> "NavigationMemory":
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return NavigationMemory(path=path, store=raw)
            except Exception:
                pass
        return NavigationMemory(path=path, store={"version": 1, "screens": {}})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.store, indent=2), encoding="utf-8")

    def record_screen(self, screen_key: str, state_signature: str, actions: List[str]) -> None:
        screens = self.store.setdefault("screens", {})
        entry = screens.get(screen_key) or {}
        now = datetime.utcnow().isoformat() + "Z"

        entry["last_seen"] = now
        entry.setdefault("first_seen", now)
        entry["state_signature"] = state_signature
        entry["path"] = actions[-50:]
        screens[screen_key] = entry

    def get_path(self, screen_key: str) -> Optional[List[str]]:
        screens = self.store.get("screens")
        if not isinstance(screens, dict):
            return None
        entry = screens.get(screen_key)
        if not isinstance(entry, dict):
            return None
        path = entry.get("path")
        if isinstance(path, list) and all(isinstance(x, str) for x in path):
            return path
        return None
