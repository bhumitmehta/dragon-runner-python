"""
KnowledgeBase -- persistent cross-run memory backed by TinyDB.

Unlike SessionMemory (per-session, crash-resilient state), the KnowledgeBase
persists **across sessions**.  It remembers:

- **Screen catalog**: every screen the agent has ever seen
- **Navigation scripts**: verified action sequences to reach known screens
- **Verification scripts**: dynamic test scripts for specific behaviours
- **Feature registry**: features from docs or discovered at runtime
- **Discovery log**: timestamped log so repeat runs skip known areas

Storage: TinyDB (pure-Python document-oriented NoSQL, file-based).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from tinydb import TinyDB, Query
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

from .logging_config import get_logger

logger = get_logger("knowledge_base")

_DEFAULT_DB_PATH = Path(__file__).resolve().parent / "artifacts" / "knowledge_base.db.json"


class KnowledgeBase:
    """Persistent cross-run knowledge store backed by TinyDB."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = TinyDB(
            str(self.db_path),
            storage=CachingMiddleware(JSONStorage),
            indent=2,
        )

        # Separate tables
        self.screens = self._db.table("screens")
        self.nav_scripts = self._db.table("nav_scripts")
        self.verification_scripts = self._db.table("verification_scripts")
        self.features = self._db.table("features")
        self.discoveries = self._db.table("discoveries")
        self.runs = self._db.table("runs")
        self.meta = self._db.table("meta")

        self.run_id: str = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    # ── Lifecycle ────────────────────────────────────────────────────

    def start_run(self):
        self.run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        self.runs.insert({
            "run_id": self.run_id,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "status": "running",
        })
        meta = self.meta.all()
        if meta:
            self.meta.update({
                "total_runs": meta[0].get("total_runs", 0) + 1,
                "last_run": self.run_id,
            })
        else:
            self.meta.insert({"total_runs": 1, "last_run": self.run_id})
        self.flush()
        logger.info("KnowledgeBase run started: %s", self.run_id)

    def end_run(self):
        Run = Query()
        self.runs.update(
            {"status": "completed", "ended_at": datetime.utcnow().isoformat() + "Z"},
            Run.run_id == self.run_id,
        )
        self.flush()
        logger.info("KnowledgeBase run ended: %s", self.run_id)

    def flush(self):
        self._db.storage.flush()

    def close(self):
        self._db.close()

    # ── Screen catalog ───────────────────────────────────────────────

    def record_screen(self, sig: str, elements: List[str], *,
                      input_fields: Optional[List[str]] = None,
                      name: str = "") -> bool:
        """Record a screen visit. Returns True if NEW screen."""
        Screen = Query()
        now = datetime.utcnow().isoformat() + "Z"
        existing = self.screens.search(Screen.signature == sig)

        if not existing:
            self.screens.insert({
                "signature": sig, "name": name,
                "elements": elements[:60],
                "input_fields": input_fields or [],
                "first_seen": now, "last_seen": now,
                "visit_count": 1, "transitions": {}, "tags": [],
            })
            self._add_discovery("new_screen", f"New screen: {name or sig[:16]}",
                                {"sig": sig, "elements": elements[:20]})
            self.flush()
            return True
        else:
            doc = existing[0]
            updates: Dict[str, Any] = {
                "last_seen": now,
                "visit_count": doc.get("visit_count", 0) + 1,
                "elements": elements[:60],
            }
            if input_fields:
                updates["input_fields"] = input_fields
            if name and not doc.get("name"):
                updates["name"] = name
            self.screens.update(updates, Screen.signature == sig)
            self.flush()
            return False

    def record_transition(self, from_sig: str, action_desc: str, to_sig: str):
        Screen = Query()
        existing = self.screens.search(Screen.signature == from_sig)
        if existing:
            transitions = existing[0].get("transitions", {})
            if transitions.get(action_desc) != to_sig:
                transitions[action_desc] = to_sig
                self.screens.update({"transitions": transitions}, Screen.signature == from_sig)
                self._add_discovery("new_transition",
                    f"{from_sig[:12]} --[{action_desc}]--> {to_sig[:12]}",
                    {"from": from_sig, "action": action_desc, "to": to_sig})
                self.flush()

    def get_screen(self, sig: str) -> Optional[Dict[str, Any]]:
        Screen = Query()
        results = self.screens.search(Screen.signature == sig)
        return results[0] if results else None

    def get_all_screens(self) -> List[Dict[str, Any]]:
        return self.screens.all()

    def get_least_visited_screens(self, n: int = 10) -> List[Dict[str, Any]]:
        all_s = self.screens.all()
        all_s.sort(key=lambda s: s.get("visit_count", 0))
        return all_s[:n]

    def get_screen_graph_summary(self) -> str:
        """Concise text summary of the screen graph for LLM context."""
        all_s = self.screens.all()
        if not all_s:
            return "No screens discovered yet."
        lines = [f"Known screens ({len(all_s)}):"]
        for s in sorted(all_s, key=lambda x: x.get("visit_count", 0), reverse=True)[:15]:
            name = s.get("name") or s.get("signature", "?")[:16]
            trans = s.get("transitions", {})
            lines.append(f"  - {name} (visited {s.get('visit_count', 0)}x, "
                         f"{len(s.get('elements', []))} elements, {len(trans)} transitions)")
            for action, target in list(trans.items())[:3]:
                target_scr = self.get_screen(target)
                target_name = (target_scr.get("name") if target_scr else None) or target[:12]
                lines.append(f"      -> [{action}] -> {target_name}")
        return "\n".join(lines)

    # ── Navigation scripts ───────────────────────────────────────────

    def add_nav_script(self, name: str, target_screen_sig: str,
                       steps: List[Dict[str, Any]], *, verified: bool = False) -> int:
        """Store a navigation script. Returns the TinyDB doc_id."""
        doc_id = self.nav_scripts.insert({
            "name": name, "target_screen_sig": target_screen_sig,
            "steps": steps, "verified": verified,
            "last_verified": "", "created_at": datetime.utcnow().isoformat() + "Z",
            "success_count": 0, "fail_count": 0, "run_id": self.run_id,
        })
        self._add_discovery("nav_script", f"Nav script: {name}",
                            {"doc_id": doc_id, "target": target_screen_sig})
        self.flush()
        return doc_id

    def get_nav_script_for_screen(self, target_sig: str) -> Optional[Dict[str, Any]]:
        Nav = Query()
        verified = self.nav_scripts.search(
            (Nav.target_screen_sig == target_sig) & (Nav.verified == True)
        )
        if verified:
            return max(verified, key=lambda d: d.get("success_count", 0))
        any_script = self.nav_scripts.search(Nav.target_screen_sig == target_sig)
        return any_script[0] if any_script else None

    def get_all_nav_scripts(self) -> List[Dict[str, Any]]:
        return self.nav_scripts.all()

    def mark_nav_script_result(self, doc_id: int, success: bool):
        doc = self.nav_scripts.get(doc_id=doc_id)
        if doc:
            updates: Dict[str, Any] = {}
            if success:
                updates["success_count"] = doc.get("success_count", 0) + 1
                updates["verified"] = True
                updates["last_verified"] = datetime.utcnow().isoformat() + "Z"
            else:
                updates["fail_count"] = doc.get("fail_count", 0) + 1
            self.nav_scripts.update(updates, doc_ids=[doc_id])
            self.flush()

    # ── Verification scripts ─────────────────────────────────────────

    def add_verification_script(self, script: Dict[str, Any]) -> int:
        script.setdefault("created_at", datetime.utcnow().isoformat() + "Z")
        script.setdefault("run_count", 0)
        script.setdefault("pass_count", 0)
        script.setdefault("fail_count", 0)
        script.setdefault("last_result", "")
        script.setdefault("last_run", "")
        script.setdefault("bugs_found", [])
        doc_id = self.verification_scripts.insert(script)
        self._add_discovery("verification_script", f"Test: {script.get('name', '?')}",
                            {"doc_id": doc_id})
        self.flush()
        return doc_id

    def get_verification_script(self, doc_id: int) -> Optional[Dict[str, Any]]:
        return self.verification_scripts.get(doc_id=doc_id)

    def get_all_verification_scripts(self) -> List[Dict[str, Any]]:
        return self.verification_scripts.all()

    def get_untested_scripts(self) -> List[Dict[str, Any]]:
        return [s for s in self.verification_scripts.all()
                if s.get("run_count", 0) == 0 or s.get("last_result") == "error"]

    def get_scripts_for_feature(self, feature_id: str) -> List[Dict[str, Any]]:
        VS = Query()
        return self.verification_scripts.search(VS.feature_id == feature_id)

    def mark_script_result(self, doc_id: int, result: str, *, bugs: Optional[List[str]] = None):
        doc = self.verification_scripts.get(doc_id=doc_id)
        if doc:
            updates: Dict[str, Any] = {
                "run_count": doc.get("run_count", 0) + 1,
                "last_run": datetime.utcnow().isoformat() + "Z",
                "last_result": result,
            }
            if result == "pass":
                updates["pass_count"] = doc.get("pass_count", 0) + 1
            else:
                updates["fail_count"] = doc.get("fail_count", 0) + 1
            if bugs:
                updates["bugs_found"] = doc.get("bugs_found", []) + bugs
            self.verification_scripts.update(updates, doc_ids=[doc_id])
            self.flush()

    # ── Feature registry ─────────────────────────────────────────────

    def add_feature(self, feature: Dict[str, Any]) -> int:
        feature.setdefault("source", "documentation")
        feature.setdefault("priority", "medium")
        feature.setdefault("screens", [])
        feature.setdefault("verification_script_ids", [])
        feature.setdefault("tested", False)
        feature.setdefault("test_result", "")
        feature.setdefault("bugs", [])
        doc_id = self.features.insert(feature)
        self.flush()
        return doc_id

    def get_all_features(self) -> List[Dict[str, Any]]:
        return self.features.all()

    def get_untested_features(self) -> List[Dict[str, Any]]:
        return [f for f in self.features.all() if not f.get("tested")]

    def get_features_by_priority(self) -> List[Dict[str, Any]]:
        order = {"high": 0, "medium": 1, "low": 2}
        feats = self.features.all()
        feats.sort(key=lambda f: order.get(f.get("priority", "medium"), 1))
        return feats

    def mark_feature_tested(self, feature_id: str, result: str, *, bugs: Optional[List[str]] = None):
        Feat = Query()
        matches = self.features.search(Feat.id == feature_id)
        if matches:
            updates: Dict[str, Any] = {"tested": True, "test_result": result}
            if bugs:
                updates["bugs"] = matches[0].get("bugs", []) + bugs
            self.features.update(updates, Feat.id == feature_id)
            self.flush()

    def link_feature_to_script(self, feature_id: str, script_doc_id: int):
        Feat = Query()
        matches = self.features.search(Feat.id == feature_id)
        if matches:
            existing = matches[0].get("verification_script_ids", [])
            if script_doc_id not in existing:
                existing.append(script_doc_id)
                self.features.update({"verification_script_ids": existing}, Feat.id == feature_id)
                self.flush()

    # ── Discovery log ────────────────────────────────────────────────

    def _add_discovery(self, dtype: str, description: str, data: Optional[Dict[str, Any]] = None):
        self.discoveries.insert({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "run_id": self.run_id, "type": dtype,
            "description": description, "data": data or {},
        })

    def get_recent_discoveries(self, n: int = 20) -> List[Dict[str, Any]]:
        all_d = self.discoveries.all()
        return all_d[-n:]

    # ── App documentation ────────────────────────────────────────────

    def store_app_documentation(self, doc_text: str, feature_list: List[Dict[str, Any]]):
        meta = self.meta.all()
        update = {
            "app_documentation": doc_text[:10000],
            "app_feature_list": feature_list,
            "doc_ingested_at": datetime.utcnow().isoformat() + "Z",
        }
        if meta:
            self.meta.update(update)
        else:
            update.update({"total_runs": 0, "last_run": ""})
            self.meta.insert(update)
        self.flush()

    def get_app_documentation(self) -> str:
        meta = self.meta.all()
        return meta[0].get("app_documentation", "") if meta else ""

    def get_app_feature_list(self) -> List[Dict[str, Any]]:
        meta = self.meta.all()
        return meta[0].get("app_feature_list", []) if meta else []

    # ── Summary for LLM context ──────────────────────────────────────

    def summary_for_llm(self) -> str:
        meta = self.meta.all()
        total_runs = meta[0].get("total_runs", 0) if meta else 0
        all_vs = self.verification_scripts.all()
        all_feat = self.features.all()

        lines = [
            f"Knowledge Base (run #{total_runs + 1}):",
            f"  Screens: {len(self.screens)}",
            f"  Nav scripts: {len(self.nav_scripts)} "
            f"({sum(1 for n in self.nav_scripts.all() if n.get('verified'))} verified)",
            f"  Verification scripts: {len(all_vs)} "
            f"({sum(1 for v in all_vs if v.get('last_result') == 'pass')} passing)",
            f"  Features: {len(all_feat)} "
            f"({sum(1 for f in all_feat if f.get('tested'))} tested)",
        ]
        untested = self.get_untested_features()
        if untested:
            lines.append(f"  Untested features ({len(untested)}):")
            for f in untested[:8]:
                lines.append(f"    - [{f.get('priority','?')}] {f.get('name','?')}: "
                             f"{f.get('description','')[:50]}")
        return "\n".join(lines)

    # ── Import from old session files ────────────────────────────────

    def import_session(self, session_path: Path):
        """Import screens/transitions from an existing session JSON file."""
        try:
            blob = json.loads(session_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Cannot import session %s: %s", session_path, e)
            return
        imported = 0
        for sig, sdata in blob.get("screens", {}).items():
            is_new = self.record_screen(sig, sdata.get("elements_snapshot", []),
                                        name=sdata.get("name", ""))
            if is_new:
                imported += 1
            for action, target in sdata.get("transitions", {}).items():
                self.record_transition(sig, action, target)
        if imported:
            logger.info("Imported %d new screens from %s", imported, session_path.name)

    def import_all_sessions(self, sessions_dir: Path):
        if not sessions_dir.exists():
            return
        for f in sorted(sessions_dir.glob("*.json")):
            self.import_session(f)
        self.flush()
