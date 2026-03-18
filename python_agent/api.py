"""
REST API for the Dragon Runner agent.

Provides endpoints for:
- App profile management (list / select / configure apps)
- Natural language task execution (chat with the agent)
- Screen graph visualisation (D3, Cytoscape, Mermaid)
- Test results dashboard (runs, bugs, coverage)
- Live agent status & control (start, stop, step count)

Start with:
    python -m python_agent.api            # default port 8000
    python -m python_agent.api --port 9000

Or import the ``app`` object for custom mounting.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from tinydb import Query as TinyQuery

from . import config
from .logging_config import get_logger
from .knowledge_base import KnowledgeBase
from .screen_graph import ScreenGraph

logger = get_logger("api")

# ── FastAPI app setup ────────────────────────────────────────────────

app = FastAPI(
    title="Dragon Runner Agent API",
    description="REST API for AI-powered mobile app testing agent",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Shared state (populated on startup) ──────────────────────────────

_kb: Optional[KnowledgeBase] = None
_agent_thread: Optional[threading.Thread] = None
_agent_status: Dict[str, Any] = {
    "state": "idle",        # idle | running | paused | error
    "current_step": 0,
    "max_steps": 0,
    "current_screen": "",
    "started_at": None,
    "error": None,
    "app_profile": None,
}


def _get_kb() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb


def _get_graph() -> ScreenGraph:
    """Return a fresh ScreenGraph rebuilt from KB data every time.

    Previously the graph was built once and cached forever, so screens
    discovered after startup never appeared in the frontend.
    """
    g = ScreenGraph()
    g.load_from_kb(_get_kb())
    return g


# ════════════════════════════════════════════════════════════════════
#  App Profiles
# ════════════════════════════════════════════════════════════════════

class AppProfileResponse(BaseModel):
    name: str
    description: str
    app_package: str
    source_code_dir: str


@app.get("/api/apps", tags=["Apps"])
def list_apps() -> List[AppProfileResponse]:
    """List all configured app profiles."""
    result = []
    for name, profile in config.APP_PROFILES.items():
        result.append(AppProfileResponse(
            name=name,
            description=profile.get("description", ""),
            app_package=profile.get("app_package", ""),
            source_code_dir=profile.get("source_code_dir", ""),
        ))
    return result


@app.get("/api/apps/active", tags=["Apps"])
def get_active_app():
    """Return the currently active app profile."""
    return {
        "app_package": config.APP_PACKAGE,
        "app_activity": config.APP_ACTIVITY,
        "apk_path": str(config.APK_PATH),
        "source_code_dir": str(config.SOURCE_CODE_DIR),
        "profile": _agent_status.get("app_profile"),
    }


class SelectAppRequest(BaseModel):
    profile_name: str


@app.post("/api/apps/select", tags=["Apps"])
def select_app(req: SelectAppRequest):
    """Activate an app profile for testing."""
    try:
        config.apply_app_profile(req.profile_name)
        _agent_status["app_profile"] = req.profile_name
        # Track the current app in KB so data gets tagged correctly
        profile = config.APP_PROFILES.get(req.profile_name, {})
        _get_kb().current_app_package = profile.get("app_package", "")
        return {"status": "ok", "message": f"Switched to '{req.profile_name}'"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class AddAppRequest(BaseModel):
    name: str
    app_package: str
    app_activity: str = ".MainActivity"
    apk_path: str
    source_code_dir: str = ""
    source_extensions: str = ".js,.ts,.tsx,.jsx"
    description: str = ""


@app.post("/api/apps/add", tags=["Apps"])
def add_app(req: AddAppRequest):
    """Register a new app profile at runtime and persist to TinyDB."""
    if req.name in config.APP_PROFILES:
        raise HTTPException(400, f"Profile '{req.name}' already exists")
    profile = {
        "app_package": req.app_package,
        "app_activity": req.app_activity,
        "apk_path": req.apk_path,
        "source_code_dir": req.source_code_dir,
        "source_extensions": req.source_extensions,
        "description": req.description,
    }
    config.APP_PROFILES[req.name] = profile
    # Persist so it survives backend restarts
    _get_kb().save_app_profile(req.name, profile)
    return {"status": "ok", "message": f"Profile '{req.name}' added and persisted"}


@app.delete("/api/apps/{name}", tags=["Apps"])
def delete_app(name: str):
    """Remove an app profile from config and database (keeps associated data)."""
    if name not in config.APP_PROFILES:
        raise HTTPException(404, f"Profile '{name}' not found")
    
    # Delete the profile from config
    del config.APP_PROFILES[name]
    
    # Delete the profile from database
    _get_kb().delete_app_profile(name)
    
    return {"status": "ok", "message": f"Profile '{name}' deleted (data preserved)"}


@app.delete("/api/apps/{name}/data", tags=["Apps"])
def delete_app_data(name: str):
    """Delete all data associated with an app profile (keeps the profile)."""
    if name not in config.APP_PROFILES:
        raise HTTPException(404, f"Profile '{name}' not found")
    
    # Get the app_package
    profile = config.APP_PROFILES[name]
    app_package = profile.get("app_package", "")
    
    if not app_package:
        return {"status": "ok", "message": "No app_package found, no data to delete"}
    
    # Delete all associated data for this app
    deleted_counts = _get_kb().delete_all_data_for_app(app_package)
    total_deleted = sum(deleted_counts.values())
    
    return {"status": "ok", "message": f"Data for '{name}' deleted ({total_deleted} records)", "data_deleted": deleted_counts}


class RunSmartTestRequest(BaseModel):
    docs_path: Optional[str] = None
    docs_content: Optional[str] = None  # Direct text content instead of file path
    max_steps: int = 60
    app_profile: Optional[str] = None


class RunTaskRequest(BaseModel):
    task: str
    mode: str = "task"              # task | explore | interactive
    max_steps: int = 30
    use_explorer: bool = False
    use_vision: bool = False
    app_profile: Optional[str] = None


@app.post("/api/agent/smart-test", tags=["Agent"])
def run_smart_test(req: RunSmartTestRequest):
    """Start smart-test mode: documentation-driven intelligent testing.
    
    Ingests docs (from file path or direct content), generates verification scripts,
    and tests features systematically with cross-run memory.
    """
    if _agent_status["state"] == "running":
        raise HTTPException(409, "Agent is already running")

    # Apply profile if specified
    if req.app_profile:
        try:
            config.apply_app_profile(req.app_profile)
            _agent_status["app_profile"] = req.app_profile
        except ValueError as e:
            raise HTTPException(400, str(e))

    _agent_status.update({
        "state": "running",
        "current_step": 0,
        "max_steps": req.max_steps,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "error": None,
        "mode": "smart_test",
    })

    def _run():
        try:
            # Lazy import
            from .agents.orchestrator import OrchestratorAgent
            
            orch = OrchestratorAgent()
            
            # Handle docs content - if provided directly, save to temp file
            docs_path = req.docs_path
            if req.docs_content and not docs_path:
                import tempfile
                import os
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    f.write(req.docs_content)
                    docs_path = f.name
                # Note: temp file will be cleaned up by the orchestrator or OS
            
            report_path = orch.run_smart_test(
                docs_path=docs_path,
                max_steps=req.max_steps,
            )
            
            _agent_status.update({
                "state": "idle",
                "current_step": req.max_steps,
                "report_path": str(report_path) if report_path else None,
            })
            
        except Exception as e:
            logger.error("Smart test error: %s", e, exc_info=True)
            _agent_status.update({
                "state": "error",
                "error": str(e),
            })

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    
    return {"status": "started", "message": "Smart test started", "max_steps": req.max_steps}


@app.post("/api/agent/run", tags=["Agent"])
def run_agent(req: RunTaskRequest):
    """Start the agent in the background to execute a natural-language task.

    This is the core endpoint for the frontend: the user types a command
    in natural language and the agent executes it on the device.
    """
    if _agent_status["state"] == "running":
        raise HTTPException(409, "Agent is already running")

    # Apply profile if specified
    if req.app_profile:
        try:
            config.apply_app_profile(req.app_profile)
            _agent_status["app_profile"] = req.app_profile
        except ValueError as e:
            raise HTTPException(400, str(e))

    _agent_status.update({
        "state": "running",
        "current_step": 0,
        "max_steps": req.max_steps,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "error": None,
    })

    def _run():
        try:
            # Lazy import to avoid circular deps and heavy loading
            from .main import _run_agent_core
            _run_agent_core(
                mode=req.mode,
                task=req.task,
                max_steps=req.max_steps,
                explorer=req.use_explorer,
                vision=req.use_vision,
                status_callback=_update_agent_status,
                kb=_get_kb(),  # share the same KB so the API sees live data
            )
            _agent_status["state"] = "completed"
        except Exception as e:
            logger.error("Agent run failed: %s", e, exc_info=True)
            _agent_status["state"] = "error"
            _agent_status["error"] = str(e)

    global _agent_thread
    _agent_thread = threading.Thread(target=_run, daemon=True)
    _agent_thread.start()

    return {"status": "started", "max_steps": req.max_steps}


@app.post("/api/agent/stop", tags=["Agent"])
def stop_agent():
    """Request the agent to stop gracefully."""
    if _agent_status["state"] != "running":
        return {"status": "not_running"}
    _agent_status["state"] = "stopping"
    # The agent checks _agent_status["state"] in its loop
    return {"status": "stop_requested"}


@app.get("/api/agent/status", tags=["Agent"])
def get_agent_status():
    """Return current agent state, step count, current screen, etc."""
    return _agent_status


def _update_agent_status(update: Dict[str, Any]):
    """Callback for the agent to push status updates."""
    _agent_status.update(update)


# ════════════════════════════════════════════════════════════════════
#  Screen Graph
# ════════════════════════════════════════════════════════════════════

def _build_app_graph(app: Optional[str]) -> ScreenGraph:
    """Build a ScreenGraph filtered to a specific app_package, or return the global one."""
    if not app:
        return _get_graph()
    # Build a temporary graph from only this app's screens
    kb = _get_kb()
    g = ScreenGraph()
    screens = kb.get_screens_for_app(app)
    for s in screens:
        sig = s.get("signature", "")
        if not sig:
            continue
        g.add_screen(
            sig,
            name=s.get("name", ""),
            elements=s.get("elements", []),
            input_fields=s.get("input_fields", []),
            screenshot=s.get("screenshot", ""),
            tags=s.get("tags", []),
        )
        # Replay stored transitions so edges appear in the graph
        for action_desc, target_sig in s.get("transitions", {}).items():
            g.add_transition(sig, target_sig, element_id=action_desc)
    return g


@app.get("/api/graph", tags=["Graph"])
def get_graph_d3(app: Optional[str] = Query(None)):
    """Return the screen graph in D3.js format (optionally filtered by app)."""
    return _build_app_graph(app).to_d3_json()


@app.get("/api/graph/cytoscape", tags=["Graph"])
def get_graph_cytoscape(app: Optional[str] = Query(None)):
    """Return the screen graph in Cytoscape.js format."""
    return _build_app_graph(app).to_cytoscape_json()


@app.get("/api/graph/mermaid", tags=["Graph"])
def get_graph_mermaid(app: Optional[str] = Query(None)):
    """Return the screen graph as Mermaid markdown."""
    return {"mermaid": _build_app_graph(app).to_mermaid()}


@app.get("/api/graph/stats", tags=["Graph"])
def get_graph_stats(app: Optional[str] = Query(None)):
    """Return graph statistics and coverage gaps."""
    g = _build_app_graph(app)
    gaps = g.coverage_gaps()
    hubs = g.hub_screens(5)
    return {
        "node_count": g.node_count,
        "edge_count": g.edge_count,
        "coverage_gaps": gaps,
        "hub_screens": [{"sig": s, "centrality": round(c, 3)} for s, c in hubs],
    }


@app.get("/api/graph/path", tags=["Graph"])
def get_path(
    from_sig: str = Query(..., alias="from"),
    to_sig: str = Query(..., alias="to"),
):
    """Find the shortest action path between two screens."""
    steps = _get_graph().shortest_action_path(from_sig, to_sig)
    if steps is None:
        raise HTTPException(404, "No path found between these screens")
    return {"path": steps, "length": len(steps)}


@app.get("/api/graph/unreachable", tags=["Graph"])
def get_unreachable(root: str = Query("")):
    """Return screens not reachable from the given root."""
    return {"unreachable": _get_graph().unreachable_screens(root)}


@app.get("/api/graph/cycles", tags=["Graph"])
def get_cycles():
    """Find navigation cycles (potential loop issues)."""
    return {"cycles": _get_graph().find_cycles()}


# ════════════════════════════════════════════════════════════════════
#  Screens
# ════════════════════════════════════════════════════════════════════

@app.get("/api/screens", tags=["Screens"])
def list_screens(app: Optional[str] = Query(None)):
    """List all discovered screens with summary info."""
    if app:
        return _get_kb().get_screens_for_app(app)
    return _get_graph().get_all_screens()


@app.get("/api/screens/{sig}", tags=["Screens"])
def get_screen(sig: str):
    """Get full details for a specific screen (elements, scripts, transitions)."""
    screen = _get_graph().get_screen(sig)
    if not screen:
        raise HTTPException(404, f"Screen '{sig}' not found")
    return screen


@app.get("/api/screens/{sig}/neighbors", tags=["Screens"])
def get_screen_neighbors(sig: str):
    """Get immediate predecessor and successor screens."""
    return _get_graph().get_neighbors(sig)


@app.get("/api/screens/{sig}/screenshot", tags=["Screens"])
def get_screen_screenshot(sig: str):
    """Serve the latest screenshot for a screen."""
    screen = _get_graph().get_screen(sig)
    if not screen or not screen.get("screenshot"):
        raise HTTPException(404, "No screenshot available")
    path = Path(screen["screenshot"])
    if not path.exists():
        raise HTTPException(404, "Screenshot file not found")
    return FileResponse(path, media_type="image/png")


# ════════════════════════════════════════════════════════════════════
#  Test Results / Dashboard
# ════════════════════════════════════════════════════════════════════

@app.get("/api/runs", tags=["Dashboard"])
def list_runs(app: Optional[str] = Query(None)):
    """List all agent runs (past and current)."""
    kb = _get_kb()
    if app:
        return kb.get_runs_for_app(app)
    return kb.runs.all()


@app.get("/api/bugs", tags=["Dashboard"])
def list_bugs(app: Optional[str] = Query(None)):
    """Return all bugs found across all sessions."""
    kb = _get_kb()
    if app:
        bug_discoveries = kb.get_bugs_for_app(app)
        all_scripts = kb.get_verification_scripts_for_app(app)
    else:
        bug_discoveries = [
            d for d in kb.discoveries.all()
            if d.get("type") in ("bug", "visual_bug", "crash")
        ]
        all_scripts = kb.verification_scripts.all()
    # Also collect bugs from verification scripts
    script_bugs = []
    for vs in all_scripts:
        for bug in vs.get("bugs_found", []):
            script_bugs.append({
                "source": "verification_script",
                "script_name": vs.get("name", ""),
                "description": bug,
            })
    
    # Add screen names to exploration bugs
    for bug in bug_discoveries:
        sig = bug.get("screen_signature")
        if sig:
            screen = kb.graph.get_screen(sig)
            if screen:
                bug["screen_name"] = screen.get("name", "")
    
    return {
        "exploration_bugs": bug_discoveries,
        "script_bugs": script_bugs,
        "total": len(bug_discoveries) + len(script_bugs),
    }


@app.get("/api/coverage", tags=["Dashboard"])
def get_coverage(app: Optional[str] = Query(None)):
    """Return coverage statistics for the dashboard."""
    kb = _get_kb()
    g = _build_app_graph(app)
    gaps = g.coverage_gaps()

    if app:
        all_features = kb.get_features_for_app(app)
        all_scripts = kb.get_verification_scripts_for_app(app)
    else:
        all_features = kb.get_all_features()
        all_scripts = kb.get_all_verification_scripts()
    tested_features = [f for f in all_features if f.get("tested")]
    passing = [s for s in all_scripts if s.get("last_result") == "pass"]

    return {
        "screens": {
            "discovered": g.node_count,
            "transitions": g.edge_count,
            "dead_ends": len(gaps["dead_ends"]),
            "untested": len(gaps["untested_screens"]),
        },
        "features": {
            "total": len(all_features),
            "tested": len(tested_features),
            "untested": len(all_features) - len(tested_features),
        },
        "scripts": {
            "total": len(all_scripts),
            "passing": len(passing),
            "failing": len(all_scripts) - len(passing),
        },
        "archetype": kb.get_app_archetype(),
    }


@app.get("/api/scripts", tags=["Dashboard"])
def list_scripts(app: Optional[str] = Query(None)):
    """Return all verification/test scripts."""
    kb = _get_kb()
    if app:
        return kb.get_verification_scripts_for_app(app)
    return kb.get_all_verification_scripts()


@app.get("/api/features", tags=["Dashboard"])
def list_features(app: Optional[str] = Query(None)):
    """Return all discovered/registered features."""
    kb = _get_kb()
    if app:
        return kb.get_features_for_app(app)
    return kb.get_all_features()


@app.get("/api/discoveries", tags=["Dashboard"])
def list_discoveries(limit: int = Query(50, ge=1, le=500), app: Optional[str] = Query(None)):
    """Return the most recent discoveries."""
    kb = _get_kb()
    if app:
        return kb.get_discoveries_for_app(app, limit)
    return kb.get_recent_discoveries(limit)


@app.get("/api/element-behaviors", tags=["Dashboard"])
def list_element_behaviors(screen_sig: Optional[str] = None, app: Optional[str] = Query(None)):
    """Return learned element behaviors, optionally filtered by screen and/or app."""
    kb = _get_kb()
    if app:
        results = kb.get_element_behaviors_for_app(app)
        if screen_sig:
            results = [r for r in results if r.get("screen_sig") == screen_sig]
        return results
    if screen_sig:
        from tinydb import Query as Q
        EB = Q()
        return kb.element_behaviors.search(EB.screen_sig == screen_sig)
    return kb.element_behaviors.all()


# ════════════════════════════════════════════════════════════════════
#  Health / Meta
# ════════════════════════════════════════════════════════════════════

@app.get("/api/health", tags=["Meta"])
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"}


@app.get("/api/kb/summary", tags=["Meta"])
def kb_summary():
    """Return the KnowledgeBase summary (same as the LLM sees)."""
    return {"summary": _get_kb().summary_for_llm()}


@app.post("/api/kb/clear", tags=["Meta"])
def clear_kb(keep_app_profiles: bool = Query(True)):
    """Clear all exploration/test data from TinyDB.
    App profiles are kept by default (pass ?keep_app_profiles=false to remove them too).
    """
    kb = _get_kb()
    removed = kb.clear_data(keep_app_profiles=keep_app_profiles)
    return {"status": "ok", "removed": removed, "app_profiles_kept": keep_app_profiles}


def _link_screenshots_to_screens(kb: KnowledgeBase):
    """Scan session action logs and report bugs to link screenshots to screen records.

    Strategy:
    1. From action_log entries: step_counter + screen_sig → explore_{step:04d}.png
    2. From report bugs: screen_signature + screenshot path
    """
    sessions_dir = config.ARTIFACTS_DIR / "sessions"
    reports_dir = config.ARTIFACTS_DIR / "reports"
    screenshots_dir = config.ARTIFACTS_DIR / "screenshots"
    if not screenshots_dir.exists():
        return

    sig_to_ss: dict = {}  # {sig: screenshot_path_str}

    # 1) Session action logs → step-based screenshot names
    if sessions_dir.exists():
        for sf in sorted(sessions_dir.glob("*.json")):
            try:
                data = json.loads(sf.read_text(encoding="utf-8"))
                for entry in data.get("action_log", []):
                    step = entry.get("step_counter", -1)
                    sig = entry.get("screen_sig", "")
                    if step < 0 or not sig or sig.startswith("__"):
                        continue
                    for pattern in (f"explore_{step:04d}.png",
                                    f"explore_{step:04d}_newscreen.png"):
                        ss_path = screenshots_dir / pattern
                        if ss_path.exists() and sig not in sig_to_ss:
                            sig_to_ss[sig] = str(ss_path)
            except Exception:
                pass

    # 2) Report bugs (higher-quality mapping, may overwrite step-based)
    if reports_dir.exists():
        for rf in sorted(reports_dir.glob("*.json")):
            try:
                report = json.loads(rf.read_text(encoding="utf-8"))
                for bug in report.get("bugs", []):
                    sig = bug.get("screen_signature", "")
                    ss = bug.get("screenshot", "")
                    if sig and ss and Path(ss).exists():
                        sig_to_ss[sig] = ss
            except Exception:
                pass

    # 3) Apply to KB screens that are missing screenshots
    linked = 0
    TQ = TinyQuery()
    for sig, ss_path in sig_to_ss.items():
        existing = kb.screens.search(TQ.signature == sig)
        if existing and not existing[0].get("screenshot"):
            kb.screens.update({"screenshot": ss_path}, TQ.signature == sig)
            linked += 1
    if linked:
        kb.flush()
        logger.info("Linked screenshots to %d screens", linked)


@app.post("/api/kb/import", tags=["Meta"])
def import_sessions():
    """Import screens, transitions, and bugs from existing session & report files into the KB."""
    kb = _get_kb()
    sessions_dir = config.ARTIFACTS_DIR / "sessions"
    reports_dir = config.ARTIFACTS_DIR / "reports"
    imported_screens = 0
    imported_bugs = 0

    # Import sessions (screens + transitions)
    if sessions_dir.exists():
        for f in sorted(sessions_dir.glob("*.json")):
            try:
                blob = json.loads(f.read_text(encoding="utf-8"))
                for sig, sdata in blob.get("screens", {}).items():
                    is_new = kb.record_screen(
                        sig, sdata.get("elements_snapshot", []),
                        name=sdata.get("name", ""),
                    )
                    if is_new:
                        imported_screens += 1
                    for action, target in sdata.get("transitions", {}).items():
                        kb.record_transition(sig, action, target)
                # Import bugs from session
                for bug in blob.get("bugs", []):
                    kb.record_bug(
                        bug.get("id", "unknown"),
                        bug.get("description", "Unknown bug"),
                        screenshot=bug.get("screenshot", ""),
                        screen_signature=bug.get("screen_signature", ""),
                        severity=bug.get("severity", "medium"),
                    )
                    imported_bugs += 1
            except Exception as e:
                logger.warning("Failed to import session %s: %s", f.name, e)

    # Import bugs from report files too (they have richer data)
    if reports_dir.exists():
        for f in sorted(reports_dir.glob("*.json")):
            try:
                report = json.loads(f.read_text(encoding="utf-8"))
                # Record a run entry
                session_id = report.get("session_id", f.stem)
                kb.runs.upsert(
                    {
                        "run_id": session_id,
                        "started_at": report.get("started_at", ""),
                        "status": "completed",
                        "mode": report.get("mode", "explore"),
                        "total_actions": report.get("total_actions", 0),
                        "screens_discovered": report.get("screens_discovered", 0),
                        "bugs_found": report.get("bugs_found", 0),
                        "app_package": kb.current_app_package,
                    },
                    TinyQuery().run_id == session_id,
                )
                # Match screenshot paths to screens from the report's bug data
                for bug in report.get("bugs", []):
                    sig = bug.get("screen_signature", "")
                    screenshot = bug.get("screenshot", "")
                    if sig and screenshot:
                        # Update the screen's screenshot if we have one
                        TQ = TinyQuery()
                        existing = kb.screens.search(TQ.signature == sig)
                        if existing and not existing[0].get("screenshot"):
                            kb.screens.update({"screenshot": screenshot}, TQ.signature == sig)
            except Exception as e:
                logger.warning("Failed to import report %s: %s", f.name, e)

    kb.flush()
    summary = kb.summary_for_llm()
    return {
        "status": "ok",
        "imported_screens": imported_screens,
        "imported_bugs": imported_bugs,
        "kb_summary": summary,
    }


# ── Startup / shutdown hooks ─────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    """Initialise shared resources."""
    logger.info("API starting up \u2014 loading KnowledgeBase")
    kb = _get_kb()
    loaded = kb.load_app_profiles_into_config()
    if loaded:
        logger.info("Restored %d app profile(s) from TinyDB", loaded)
    # Set the current app package so all imported data gets properly tagged
    kb.current_app_package = config.APP_PACKAGE or ""
    logger.info("KB current_app_package set to: %s", kb.current_app_package)
    # Auto-import any existing session data so the frontend shows historical runs
    try:
        sessions_dir = config.ARTIFACTS_DIR / "sessions"
        if sessions_dir.exists():
            kb.import_all_sessions(sessions_dir)
            logger.info("Auto-imported sessions into KB: %s", kb.summary_for_llm())
    except Exception as e:
        logger.warning("Session auto-import failed: %s", e)
    # Auto-import report files to populate runs table
    try:
        reports_dir = config.ARTIFACTS_DIR / "reports"
        if reports_dir.exists():
            for f in sorted(reports_dir.glob("*.json")):
                try:
                    report = json.loads(f.read_text(encoding="utf-8"))
                    session_id = report.get("session_id", f.stem)
                    kb.runs.upsert(
                        {
                            "run_id": session_id,
                            "started_at": report.get("started_at", ""),
                            "status": "completed",
                            "mode": report.get("mode", "explore"),
                            "total_actions": report.get("total_actions", 0),
                            "screens_discovered": report.get("screens_discovered", 0),
                            "bugs_found": report.get("bugs_found", 0),
                            "app_package": kb.current_app_package,
                        },
                        TinyQuery().run_id == session_id,
                    )
                except Exception as e:
                    logger.warning("Failed to import report %s: %s", f.name, e)
            kb.flush()
            logger.info("Auto-imported reports into KB runs table")
    except Exception as e:
        logger.warning("Report auto-import failed: %s", e)
    # Link screenshots to screens by scanning action logs + report bugs
    try:
        _link_screenshots_to_screens(kb)
    except Exception as e:
        logger.warning("Screenshot linking failed: %s", e)
    # Backfill any records that have empty app_package (from earlier imports)
    if kb.current_app_package:
        filled = kb.backfill_app_package(kb.current_app_package)
        if filled:
            logger.info("Backfilled app_package on %d records", filled)


@app.on_event("shutdown")
async def on_shutdown():
    """Flush and close KnowledgeBase."""
    if _kb:
        _kb.flush()
        _kb.close()
    logger.info("API shut down cleanly")


# ── Suppress noisy access logs for high-frequency polling endpoints ───

import logging

class _QuietAccessFilter(logging.Filter):
    """Drop uvicorn access-log lines for polling endpoints."""
    _QUIET_PATHS = ("/api/agent/status", "/api/health")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(p in msg for p in self._QUIET_PATHS)

logging.getLogger("uvicorn.access").addFilter(_QuietAccessFilter())


# ── CLI entry point ──────────────────────────────────────────────────

def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Dragon Runner Agent API")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=8000, help="Port")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    args = parser.parse_args()

    uvicorn.run(
        "python_agent.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
