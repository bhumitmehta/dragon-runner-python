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
from typing import Any, Dict, List, Optional, Set

from tinydb import TinyDB, Query
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

from .logging_config import get_logger
from .screen_graph import ScreenGraph

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
        self.nav_elements = self._db.table("nav_elements")   # learned navigation elements
        self.element_behaviors = self._db.table("element_behaviors")  # observed element behaviors
        self.app_profiles = self._db.table("app_profiles")  # persisted app configurations

        # In-memory NetworkX graph, rebuilt from TinyDB on start_run()
        self.graph = ScreenGraph()

        self.run_id: str = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

        # Current app package being tested (set by start_run or externally)
        self.current_app_package: str = ""

    # ── Lifecycle ────────────────────────────────────────────────────

    # ── App profile persistence ───────────────────────────────────

    def save_app_profile(self, name: str, profile: Dict[str, Any]) -> None:
        """Persist an app profile to TinyDB so it survives restarts."""
        AP = Query()
        profile_doc = {"name": name, **profile,
                       "saved_at": datetime.utcnow().isoformat() + "Z"}
        existing = self.app_profiles.search(AP.name == name)
        if existing:
            self.app_profiles.update(profile_doc, AP.name == name)
        else:
            self.app_profiles.insert(profile_doc)
        self.flush()
        logger.info("App profile saved: %s", name)

    def get_all_app_profiles(self) -> List[Dict[str, Any]]:
        """Return all persisted app profiles."""
        return self.app_profiles.all()

    def delete_app_profile(self, name: str) -> bool:
        """Delete an app profile. Returns True if it existed."""
        AP = Query()
        removed = self.app_profiles.remove(AP.name == name)
        self.flush()
        return len(removed) > 0

    def delete_all_data_for_app(self, app_package: str) -> Dict[str, int]:
        """Delete all data associated with an app_package.
        Returns a dict of table names to number of records deleted."""
        Q = Query()
        deleted_counts = {}
        
        # Delete from all tables that have app_package field
        tables_to_clean = [
            ("screens", self.screens),
            ("nav_scripts", self.nav_scripts),
            ("verification_scripts", self.verification_scripts),
            ("features", self.features),
            ("discoveries", self.discoveries),
            ("runs", self.runs),
            ("nav_elements", self.nav_elements),
            ("element_behaviors", self.element_behaviors),
        ]
        
        for table_name, table in tables_to_clean:
            removed = table.remove(Q.app_package == app_package)
            deleted_counts[table_name] = len(removed)
        
        self.flush()
        logger.info("Deleted data for app %s: %s", app_package, deleted_counts)
        return deleted_counts

    def load_app_profiles_into_config(self) -> int:
        """Load all persisted profiles into config.APP_PROFILES.
        Returns the number of profiles loaded."""
        from . import config as cfg
        loaded = 0
        for doc in self.app_profiles.all():
            name = doc.get("name")
            if name and name not in cfg.APP_PROFILES:
                cfg.APP_PROFILES[name] = {
                    k: doc[k] for k in
                    ("app_package", "app_activity", "apk_path",
                     "source_code_dir", "source_extensions", "description")
                    if k in doc
                }
                loaded += 1
        return loaded

    # ── Filtered queries (per-app) ───────────────────────────────────

    def get_screens_for_app(self, app_package: str) -> List[Dict[str, Any]]:
        """Return screens tagged with a specific app_package."""
        S = Query()
        return self.screens.search(S.app_package == app_package)

    def get_runs_for_app(self, app_package: str) -> List[Dict[str, Any]]:
        """Return runs for a specific app."""
        R = Query()
        return self.runs.search(R.app_package == app_package)

    def get_all_runs(self) -> List[Dict[str, Any]]:
        """Return all runs."""
        return self.runs.all()

    def get_discoveries_for_app(self, app_package: str, n: int = 50) -> List[Dict[str, Any]]:
        """Return recent discoveries for a specific app."""
        D = Query()
        all_d = self.discoveries.search(D.app_package == app_package)
        return all_d[-n:]

    def get_features_for_app(self, app_package: str) -> List[Dict[str, Any]]:
        F = Query()
        return self.features.search(F.app_package == app_package)

    def get_verification_scripts_for_app(self, app_package: str) -> List[Dict[str, Any]]:
        VS = Query()
        return self.verification_scripts.search(VS.app_package == app_package)

    def get_bugs_for_app(self, app_package: str) -> List[Dict[str, Any]]:
        """Return bug discoveries for a specific app."""
        D = Query()
        return self.discoveries.search(
            (D.app_package == app_package) &
            (D.type.one_of(["bug", "visual_bug", "crash"]))
        )

    def get_all_bugs(self) -> List[Dict[str, Any]]:
        """Return all bug discoveries."""
        D = Query()
        return self.discoveries.search(D.type.one_of(["bug", "visual_bug", "crash"]))

    def get_element_behaviors_for_app(self, app_package: str) -> List[Dict[str, Any]]:
        EB = Query()
        return self.element_behaviors.search(EB.app_package == app_package)

    # ── Lifecycle ────────────────────────────────────────────────────

    def start_run(self, app_package: str = ""):
        if app_package:
            self.current_app_package = app_package
        self.run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        self.runs.insert({
            "run_id": self.run_id,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "status": "running",
            "app_package": self.current_app_package,
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
        # Rebuild the in-memory screen graph from all persisted data
        self.graph.load_from_kb(self)
        logger.info("KnowledgeBase run started: %s  (graph: %d nodes, %d edges)",
                     self.run_id, self.graph.node_count, self.graph.edge_count)

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

    def clear_data(self, keep_app_profiles: bool = True) -> Dict[str, int]:
        """Clear all exploration/test data but optionally keep app profiles.
        Returns a dict of table_name -> records_removed."""
        tables_to_clear = [
            ("screens", self.screens),
            ("nav_scripts", self.nav_scripts),
            ("verification_scripts", self.verification_scripts),
            ("features", self.features),
            ("discoveries", self.discoveries),
            ("runs", self.runs),
            ("meta", self.meta),
            ("nav_elements", self.nav_elements),
            ("element_behaviors", self.element_behaviors),
        ]
        if not keep_app_profiles:
            tables_to_clear.append(("app_profiles", self.app_profiles))

        removed = {}
        for name, table in tables_to_clear:
            count = len(table)
            table.truncate()
            removed[name] = count

        # Reset in-memory graph
        self.graph = ScreenGraph()
        self.flush()
        logger.info("KnowledgeBase cleared: %s (app_profiles kept=%s)", removed, keep_app_profiles)
        return removed

    # ── Screen catalog ───────────────────────────────────────────────

    def record_screen(self, sig: str, elements: List[str], *,
                      input_fields: Optional[List[str]] = None,
                      name: str = "",
                      screenshot: str = "",
                      description: str = "") -> bool:
        """Record a screen visit. Returns True if NEW screen."""
        Screen = Query()
        now = datetime.utcnow().isoformat() + "Z"
        existing = self.screens.search(Screen.signature == sig)

        if not existing:
            doc = {
                "signature": sig, "name": name,
                "elements": elements[:60],
                "input_fields": input_fields or [],
                "first_seen": now, "last_seen": now,
                "visit_count": 1, "transitions": {}, "tags": [],
                "app_package": self.current_app_package,
                "description": description,
            }
            if screenshot:
                doc["screenshot"] = screenshot
            self.screens.insert(doc)
            self._add_discovery("new_screen", f"New screen: {name or sig[:16]}",
                                {"sig": sig, "elements": elements[:20]})
            self.flush()
            # Keep in-memory graph in sync
            self.graph.add_screen(sig, name=name, elements=elements[:60],
                                  input_fields=input_fields or [],
                                  screenshot=screenshot,
                                  description=description)
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
            if screenshot:
                updates["screenshot"] = screenshot
            if description:
                updates["description"] = description
            self.screens.update(updates, Screen.signature == sig)
            self.flush()
            # Keep in-memory graph in sync
            self.graph.add_screen(sig, name=name, elements=elements[:60],
                                  input_fields=input_fields or [],
                                  screenshot=screenshot,
                                  description=description or doc.get("description", ""))
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
        # Keep in-memory graph in sync (even if the TinyDB already had it)
        self.graph.add_transition(from_sig, to_sig, element_id=action_desc)

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
                       steps: List[Dict[str, Any]], *, verified: bool = False,
                       script_path: str = "") -> int:
        """Store a navigation script. Returns the TinyDB doc_id."""
        doc_id = self.nav_scripts.insert({
            "name": name, "target_screen_sig": target_screen_sig,
            "steps": steps, "verified": verified,
            "script_path": script_path, "script_framework": "playwright",
            "last_verified": "", "created_at": datetime.utcnow().isoformat() + "Z",
            "success_count": 0, "fail_count": 0, "run_id": self.run_id,
            "app_package": self.current_app_package,
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
        script.setdefault("script_path", "")
        script.setdefault("script_framework", "playwright")
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
        feature.setdefault("app_package", self.current_app_package)
        doc_id = self.features.insert(feature)
        self.flush()
        return doc_id

    def get_all_features(self, app_package: str = "") -> List[Dict[str, Any]]:
        """Get all features for a specific app."""
        app_package = app_package or self.current_app_package
        F = Query()
        return self.features.search(F.app_package == app_package)

    def get_untested_features(self, app_package: str = "") -> List[Dict[str, Any]]:
        """Get untested features for a specific app."""
        return [f for f in self.get_all_features(app_package) if not f.get("tested")]

    def get_features_by_priority(self, app_package: str = "") -> List[Dict[str, Any]]:
        """Get features sorted by priority for a specific app."""
        order = {"high": 0, "medium": 1, "low": 2}
        feats = self.get_all_features(app_package)
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
            "app_package": self.current_app_package,
        })

    def record_bug(self, bug_id: str, description: str, *,
                   screenshot: str = "", screen_signature: str = "",
                   severity: str = "medium",
                   extra: Optional[Dict[str, Any]] = None) -> None:
        """Record a bug as a discovery so it appears in the frontend dashboard."""
        data = {"bug_id": bug_id, "severity": severity,
                "screen_signature": screen_signature}
        if screenshot:
            data["screenshot"] = screenshot
        if extra:
            data.update(extra)
        self._add_discovery("bug", description, data)
        self.flush()

    def get_recent_discoveries(self, n: int = 20) -> List[Dict[str, Any]]:
        all_d = self.discoveries.all()
        return all_d[-n:]

    # ── App documentation ────────────────────────────────────────────

    def store_app_documentation(self, doc_text: str, feature_list: List[Dict[str, Any]], app_package: str = "", docs_path: str = ""):
        """Store documentation and features for a specific app."""
        # Use current app if not specified
        app_package = app_package or self.current_app_package
        
        # Store in app-specific document
        existing = self.meta.search(Query().app_package == app_package)
        
        update = {
            "app_package": app_package,
            "app_documentation": doc_text,  # Store full documentation
            "app_feature_list": feature_list,
            "docs_path": docs_path,
            "doc_ingested_at": datetime.utcnow().isoformat() + "Z",
        }
        
        if existing:
            self.meta.update(update, Query().app_package == app_package)
        else:
            update.update({"total_runs": 0, "last_run": ""})
            self.meta.insert(update)
        self.flush()

    def get_app_documentation(self, app_package: str = "") -> str:
        """Get documentation for a specific app."""
        app_package = app_package or self.current_app_package
        docs = self.meta.search(Query().app_package == app_package)
        return docs[0].get("app_documentation", "") if docs else ""

    def get_app_feature_list(self, app_package: str = "") -> List[Dict[str, Any]]:
        """Get feature list for a specific app."""
        app_package = app_package or self.current_app_package
        docs = self.meta.search(Query().app_package == app_package)
        return docs[0].get("app_feature_list", []) if docs else []

    def get_app_docs_path(self, app_package: str = "") -> str:
        """Get documentation path for a specific app."""
        app_package = app_package or self.current_app_package
        docs = self.meta.search(Query().app_package == app_package)
        return docs[0].get("docs_path", "") if docs else ""

    def get_relevant_docs_context(self, app_package: str = "", keywords: List[str] = [], max_length: int = 2000) -> str:
        """Get relevant sections of documentation based on keywords."""
        app_package = app_package or self.current_app_package
        full_docs = self.get_app_documentation(app_package)
        
        if not full_docs or not keywords:
            return full_docs[:max_length] if full_docs else ""
        
        # Split into sections (by double newlines, headers, etc.)
        sections = []
        for section in full_docs.split('\n\n'):
            sections.append(section.strip())
        
        # Find sections containing keywords
        relevant_sections = []
        keyword_set = set(k.lower() for k in keywords)
        
        for section in sections:
            section_lower = section.lower()
            if any(keyword in section_lower for keyword in keyword_set):
                relevant_sections.append(section)
        
        if relevant_sections:
            # Combine relevant sections
            relevant_text = '\n\n'.join(relevant_sections)
            if len(relevant_text) <= max_length:
                return relevant_text
            else:
                # Truncate if still too long
                return relevant_text[:max_length]
        
        # Fallback to beginning of document
        return full_docs[:max_length]

    # ── Learned navigation elements ─────────────────────────────────

    def learn_nav_element(self, element_id: str, role: str, *,
                          screen_sig: str = "", confidence: float = 1.0):
        """Record an element that has been identified as a navigation element.

        ``role`` is a semantic category like "menu", "tab", "link",
        "back", "drawer", etc.  Stored per (element_id, screen) pair.
        Confidence accumulates: each confirmation adds +0.3 (cap 1.0).
        """
        Nav = Query()
        existing = self.nav_elements.search(
            (Nav.element_id == element_id) & (Nav.screen_sig == screen_sig)
        )
        if existing:
            new_conf = min(1.0, existing[0].get("confidence", 0.5) + 0.3)
            self.nav_elements.update(
                {"confidence": new_conf, "role": role,
                 "last_seen": datetime.utcnow().isoformat() + "Z"},
                (Nav.element_id == element_id) & (Nav.screen_sig == screen_sig),
            )
            self.flush()
        else:
            self.nav_elements.insert({
                "element_id": element_id,
                "role": role,
                "screen_sig": screen_sig,
                "confidence": confidence,
                "first_seen": datetime.utcnow().isoformat() + "Z",
                "last_seen": datetime.utcnow().isoformat() + "Z",
            })
            self.flush()

    def learn_nav_elements_batch(self, elements: List[Dict[str, Any]], screen_sig: str = ""):
        """Store multiple nav element classifications at once.

        Each dict should have ``element_id`` and ``role``.
        """
        for el in elements:
            self.learn_nav_element(
                el["element_id"], el["role"],
                screen_sig=screen_sig,
                confidence=el.get("confidence", 0.8),
            )
        self.flush()

    def get_nav_keywords(self) -> Set[str]:
        """Return the set of element IDs across all screens that have been
        confirmed as navigation elements (confidence >= 0.5).

        This replaces hardcoded keyword sets -- it's learned from the
        actual app being tested.
        """
        all_nav = self.nav_elements.all()
        return {
            doc["element_id"]
            for doc in all_nav
            if doc.get("confidence", 0) >= 0.5
        }

    def get_nav_roles(self) -> Dict[str, str]:
        """Return {element_id: role} for all confirmed nav elements."""
        all_nav = self.nav_elements.all()
        return {
            doc["element_id"]: doc["role"]
            for doc in all_nav
            if doc.get("confidence", 0) >= 0.5
        }

    def get_nav_elements_for_screen(self, screen_sig: str) -> List[Dict[str, Any]]:
        """Return learned nav elements for a specific screen."""
        Nav = Query()
        return self.nav_elements.search(
            (Nav.screen_sig == screen_sig) & (Nav.confidence >= 0.5)
        )

    def confirm_nav_element(self, element_id: str, screen_sig: str = ""):
        """Boost confidence of a nav element after it successfully navigated."""
        self.learn_nav_element(element_id, "confirmed", screen_sig=screen_sig, confidence=0.3)

    # ── App archetype detection ────────────────────────────────────

    # Known archetype patterns: keyword sets found in element IDs
    _ARCHETYPE_SIGNALS = {
        "ecommerce": {
            "keywords": {"cart", "add to cart", "checkout", "price", "product",
                         "catalog", "shop", "buy", "payment", "order", "shipping"},
            "screens": {"catalog", "product detail", "cart", "checkout", "order"},
        },
        "login_centric": {
            "keywords": {"login", "log in", "sign in", "sign up", "register",
                         "password", "email", "forgot password", "username", "auth"},
            "screens": {"login", "register", "forgot password", "profile"},
        },
        "media_browser": {
            "keywords": {"video", "play", "pause", "gallery", "photo", "image",
                         "camera", "album", "stream", "music", "podcast"},
            "screens": {"gallery", "player", "library", "browse"},
        },
        "form_enterprise": {
            "keywords": {"form", "submit", "save", "input", "dropdown", "select",
                         "date picker", "checkbox", "radio", "upload", "table"},
            "screens": {"form", "dashboard", "report", "settings", "admin"},
        },
        "social": {
            "keywords": {"feed", "post", "like", "comment", "share", "follow",
                         "profile", "message", "chat", "notification", "friend"},
            "screens": {"feed", "profile", "messages", "notifications"},
        },
        "navigation_heavy": {
            "keywords": {"map", "location", "directions", "navigate", "route",
                         "gps", "pin", "marker", "search", "nearby"},
            "screens": {"map", "search results", "directions", "place detail"},
        },
    }

    def detect_app_archetype(self) -> Dict[str, Any]:
        """Analyse all discovered screens/elements to classify the app.

        Returns a dict with:
        - ``primary``: strongest archetype match
        - ``secondary``: second-strongest (may be None)
        - ``scores``: full score breakdown
        - ``predicted_screens``: screens the archetype suggests exist
          but haven't been discovered yet
        """
        all_screens = self.screens.all()
        if not all_screens:
            return {"primary": "unknown", "secondary": None, "scores": {},
                    "predicted_screens": []}

        # Collect all element IDs across all screens (lowercased)
        all_elements: set = set()
        for scr in all_screens:
            for eid in scr.get("elements", []):
                all_elements.add(eid.lower())
            for eid in scr.get("input_fields", []):
                all_elements.add(eid.lower())

        # Score each archetype
        scores: Dict[str, float] = {}
        for archetype, signals in self._ARCHETYPE_SIGNALS.items():
            kw_hits = sum(1 for kw in signals["keywords"] if any(kw in eid for eid in all_elements))
            kw_total = len(signals["keywords"])
            scores[archetype] = kw_hits / kw_total if kw_total else 0.0

        # Sort by score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        primary = ranked[0] if ranked and ranked[0][1] > 0.1 else ("unknown", 0.0)
        secondary = ranked[1] if len(ranked) > 1 and ranked[1][1] > 0.1 else (None, 0.0)

        # Predict undiscovered screens based on archetype
        discovered_names = set()
        for scr in all_screens:
            name = (scr.get("name") or "").lower()
            for eid in scr.get("elements", [])[:10]:
                discovered_names.add(eid.lower())
            if name:
                discovered_names.add(name)

        predicted_screens = []
        if primary[0] != "unknown":
            expected = self._ARCHETYPE_SIGNALS[primary[0]]["screens"]
            for scr_name in expected:
                if not any(scr_name in d for d in discovered_names):
                    predicted_screens.append(scr_name)

        result = {
            "primary": primary[0],
            "primary_confidence": round(primary[1], 2),
            "secondary": secondary[0],
            "secondary_confidence": round(secondary[1], 2) if secondary[0] else 0.0,
            "scores": {k: round(v, 2) for k, v in scores.items()},
            "predicted_screens": predicted_screens,
        }

        # Persist archetype in meta
        meta = self.meta.all()
        if meta:
            self.meta.update({"app_archetype": result})
        else:
            self.meta.insert({"app_archetype": result, "total_runs": 0, "last_run": ""})
        self.flush()

        logger.info("App archetype: %s (%.0f%%) | secondary: %s (%.0f%%) | predicted screens: %s",
                     result["primary"], result["primary_confidence"] * 100,
                     result["secondary"] or "none",
                     result["secondary_confidence"] * 100,
                     result["predicted_screens"])
        return result

    def get_app_archetype(self) -> Optional[Dict[str, Any]]:
        """Return the cached archetype, or None."""
        meta = self.meta.all()
        return meta[0].get("app_archetype") if meta else None

    def get_predicted_screens(self) -> List[str]:
        """Return screen names the archetype predicts exist but haven't been found."""
        arch = self.get_app_archetype()
        return arch.get("predicted_screens", []) if arch else []

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
        # Include archetype info if available
        arch = self.get_app_archetype()
        if arch and arch.get("primary") != "unknown":
            lines.append(f"  App type: {arch['primary']} ({arch.get('primary_confidence', 0)*100:.0f}%)")
            if arch.get("predicted_screens"):
                lines.append(f"  Predicted undiscovered screens: {arch['predicted_screens']}")
        untested = self.get_untested_features()
        if untested:
            lines.append(f"  Untested features ({len(untested)}):")
            for f in untested[:8]:
                lines.append(f"    - [{f.get('priority','?')}] {f.get('name','?')}: "
                             f"{f.get('description','')[:50]}")
        return "\n".join(lines)

    # ── Learned element behaviors ──────────────────────────────────

    def record_element_behavior(
        self,
        element_id: str,
        screen_sig: str,
        behavior: str,
        *,
        target_screen_sig: str = "",
        action_type: str = "click",
    ):
        """Record what an element *actually did* when interacted with.

        ``behavior`` values:
        - "navigates"   : screen changed after interaction
        - "stays"       : screen stayed the same
        - "opens_dialog": a dialog/popup appeared (screen changed but
                          looks like an overlay)
        - "back"        : navigated backward in the screen graph

        This is the core learning loop: we observe every action result
        and build a persistent map of element → behavior so on the
        next run we already know what every button does.
        """
        EB = Query()
        existing = self.element_behaviors.search(
            (EB.element_id == element_id) & (EB.screen_sig == screen_sig)
        )
        now = datetime.utcnow().isoformat() + "Z"
        if existing:
            doc = existing[0]
            updates: Dict[str, Any] = {
                "last_seen": now,
                "click_count": doc.get("click_count", 0) + 1,
                "last_behavior": behavior,
                "action_type": action_type,
            }
            if behavior == "navigates":
                updates["nav_count"] = doc.get("nav_count", 0) + 1
                updates["last_target"] = target_screen_sig
                # Keep set of all known targets
                targets = set(doc.get("known_targets", []))
                if target_screen_sig:
                    targets.add(target_screen_sig)
                updates["known_targets"] = list(targets)
            elif behavior == "stays":
                updates["stay_count"] = doc.get("stay_count", 0) + 1
            self.element_behaviors.update(
                updates,
                (EB.element_id == element_id) & (EB.screen_sig == screen_sig),
            )
        else:
            doc = {
                "element_id": element_id,
                "screen_sig": screen_sig,
                "action_type": action_type,
                "last_behavior": behavior,
                "click_count": 1,
                "nav_count": 1 if behavior == "navigates" else 0,
                "stay_count": 1 if behavior == "stays" else 0,
                "known_targets": [target_screen_sig] if target_screen_sig and behavior == "navigates" else [],
                "last_target": target_screen_sig if behavior == "navigates" else "",
                "first_seen": now,
                "last_seen": now,
                "app_package": self.current_app_package,
            }
            self.element_behaviors.insert(doc)
        self.flush()

    def get_known_navigators(self, screen_sig: str) -> List[Dict[str, Any]]:
        """Return elements on ``screen_sig`` that are known to navigate
        to a different screen (nav_count > 0), sorted by nav reliability.

        Each dict has: element_id, nav_count, click_count, known_targets,
        reliability (nav_count / click_count).
        """
        EB = Query()
        docs = self.element_behaviors.search(
            (EB.screen_sig == screen_sig) & (EB.nav_count > 0)
        )
        results = []
        for d in docs:
            cc = d.get("click_count", 1)
            nc = d.get("nav_count", 0)
            results.append({
                "element_id": d["element_id"],
                "nav_count": nc,
                "click_count": cc,
                "reliability": nc / max(cc, 1),
                "known_targets": d.get("known_targets", []),
                "last_target": d.get("last_target", ""),
            })
        results.sort(key=lambda r: r["reliability"], reverse=True)
        return results

    def get_all_known_navigators(self) -> Set[str]:
        """Return element IDs that have *ever* navigated (across all screens)."""
        EB = Query()
        docs = self.element_behaviors.search(EB.nav_count > 0)
        return {d["element_id"] for d in docs}

    def get_element_behavior(self, element_id: str, screen_sig: str) -> Optional[Dict[str, Any]]:
        """Return the stored behavior record for a single element, or None."""
        EB = Query()
        docs = self.element_behaviors.search(
            (EB.element_id == element_id) & (EB.screen_sig == screen_sig)
        )
        return docs[0] if docs else None

    def get_untried_elements(self, screen_sig: str, visible_ids: List[str]) -> List[str]:
        """Return elements from ``visible_ids`` that have NEVER been
        interacted with on this screen (no behavior record at all).
        These are the highest-value exploration targets.
        """
        EB = Query()
        tried = {
            d["element_id"]
            for d in self.element_behaviors.search(EB.screen_sig == screen_sig)
        }
        return [eid for eid in visible_ids if eid not in tried]

    # ── Import from old session files ────────────────────────────────

    def backfill_app_package(self, app_package: str) -> int:
        """Update all records that have an empty app_package with the given value.
        Returns the total number of records updated."""
        updated = 0
        tables = [
            self.screens, self.runs, self.discoveries,
            self.features, self.verification_scripts,
            self.nav_scripts, self.element_behaviors,
        ]
        Empty = Query()
        for table in tables:
            matches = table.search(
                (Empty.app_package.exists()) & (Empty.app_package == "")
            )
            if matches:
                table.update({"app_package": app_package}, (Empty.app_package.exists()) & (Empty.app_package == ""))
                updated += len(matches)
            # Also update records that have no app_package field at all
            no_field = [doc for doc in table.all() if "app_package" not in doc]
            for doc in no_field:
                table.update({"app_package": app_package}, doc_ids=[doc.doc_id])
                updated += 1
        if updated:
            self.flush()
            logger.info("Backfilled app_package='%s' on %d records", app_package, updated)
        return updated

    def import_session(self, session_path: Path):
        """Import screens/transitions/bugs from an existing session JSON file."""
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
        # Import bugs from session memory
        for bug in blob.get("bugs", []):
            self.record_bug(
                bug.get("id", "unknown"),
                bug.get("description", "Unknown bug"),
                screenshot=bug.get("screenshot", ""),
                screen_signature=bug.get("screen_signature", ""),
                severity=bug.get("severity", "medium"),
            )
        if imported:
            logger.info("Imported %d new screens from %s", imported, session_path.name)

    def import_all_sessions(self, sessions_dir: Path):
        if not sessions_dir.exists():
            return
        for f in sorted(sessions_dir.glob("*.json")):
            self.import_session(f)
        self.flush()
