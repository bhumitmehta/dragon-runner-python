"""
Persistent Session Memory  --  crash-resilient state that survives mid-session failures.

Stores:
- Hierarchical test plan (goals → tasks → steps) with per-item status
- Coverage map (which screens/features have been tested)
- Action history checkpoint (so we can resume after a crash)
- Bug ledger (all bugs found across sessions)
- Screen graph (known screens and transitions)

The entire state is flushed to a JSON file after *every* mutation so that
the session can be resumed from disk if the process dies.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from .logging_config import get_logger

logger = get_logger("session_memory")


# ────────────────────────────────────────────────────────────────────────
#  Task / Plan data structures
# ────────────────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass
class TestStep:
    """Leaf-level action inside a task."""
    id: str
    description: str
    status: str = TaskStatus.NOT_STARTED.value
    action: Optional[Dict[str, Any]] = None      # resolved action JSON
    result: Optional[Dict[str, Any]] = None       # outcome after execution
    error: Optional[str] = None
    retries: int = 0
    timestamp: Optional[str] = None

    def mark(self, status: TaskStatus, **extra):
        self.status = status.value
        self.timestamp = datetime.utcnow().isoformat() + "Z"
        for k, v in extra.items():
            if hasattr(self, k):
                setattr(self, k, v)


@dataclass
class TestTask:
    """Mid-level task grouping several steps (e.g. 'Login with valid creds')."""
    id: str
    name: str
    description: str
    priority: str = "medium"   # high / medium / low
    status: str = TaskStatus.NOT_STARTED.value
    steps: List[TestStep] = field(default_factory=list)
    bugs_found: List[str] = field(default_factory=list)   # bug IDs
    depends_on: List[str] = field(default_factory=list)    # task IDs
    created_at: str = ""
    finished_at: Optional[str] = None

    def progress(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps if s.status in (TaskStatus.COMPLETED.value, TaskStatus.SKIPPED.value))
        return done / len(self.steps)

    def is_done(self) -> bool:
        return self.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.SKIPPED.value)


@dataclass
class TestGoal:
    """Top-level goal grouping several tasks (e.g. 'Test Authentication')."""
    id: str
    name: str
    description: str
    status: str = TaskStatus.NOT_STARTED.value
    tasks: List[TestTask] = field(default_factory=list)
    created_at: str = ""
    finished_at: Optional[str] = None

    def progress(self) -> float:
        if not self.tasks:
            return 0.0
        return sum(t.progress() for t in self.tasks) / len(self.tasks)

    def is_done(self) -> bool:
        return all(t.is_done() for t in self.tasks) if self.tasks else False


@dataclass
class TestPlan:
    """Root of the hierarchical plan: goals → tasks → steps."""
    goals: List[TestGoal] = field(default_factory=list)
    created_at: str = ""
    version: int = 1

    def overall_progress(self) -> float:
        if not self.goals:
            return 0.0
        return sum(g.progress() for g in self.goals) / len(self.goals)

    def summary(self) -> Dict[str, Any]:
        total_tasks = sum(len(g.tasks) for g in self.goals)
        done_tasks = sum(1 for g in self.goals for t in g.tasks if t.is_done())
        total_steps = sum(len(t.steps) for g in self.goals for t in g.tasks)
        done_steps = sum(
            1 for g in self.goals for t in g.tasks for s in t.steps
            if s.status in (TaskStatus.COMPLETED.value, TaskStatus.SKIPPED.value)
        )
        return {
            "goals": len(self.goals),
            "tasks": total_tasks,
            "tasks_done": done_tasks,
            "steps": total_steps,
            "steps_done": done_steps,
            "progress_pct": round(self.overall_progress() * 100, 1),
        }


# ────────────────────────────────────────────────────────────────────────
#  Screen graph node
# ────────────────────────────────────────────────────────────────────────

@dataclass
class ScreenNode:
    signature: str
    first_seen: str
    last_seen: str
    visit_count: int = 1
    elements_snapshot: List[str] = field(default_factory=list)
    transitions: Dict[str, str] = field(default_factory=dict)  # action_desc → target_sig


# ────────────────────────────────────────────────────────────────────────
#  Action priority weights  (Critic → Explorer feedback loop)
# ────────────────────────────────────────────────────────────────────────

@dataclass
class ActionWeight:
    """Tracks per-element reward signal from Critic verdicts.

    Positive weight → Critic-approved element (explore more like this).
    Negative weight → Critic-rejected / hallucinated element (deprioritise).
    """
    element_id: str
    weight: float = 0.0         # cumulative reward
    pass_count: int = 0
    fail_count: int = 0
    last_verdict: str = ""      # pass / warn / fail
    last_updated: str = ""


# ────────────────────────────────────────────────────────────────────────
#  Bug ledger entry
# ────────────────────────────────────────────────────────────────────────

@dataclass
class BugEntry:
    id: str
    description: str
    severity: str = "medium"
    screenshot: Optional[str] = None
    screen_signature: Optional[str] = None
    localization: Optional[Dict[str, Any]] = None
    detected_at: str = ""
    task_id: Optional[str] = None
    step_id: Optional[str] = None


# ────────────────────────────────────────────────────────────────────────
#  Session Memory (crash-resilient)
# ────────────────────────────────────────────────────────────────────────

class SessionMemory:
    """
    Persistent, crash-resilient session memory.

    Every mutation auto-saves to disk via ``_persist()``.
    On restart, call ``SessionMemory.load(path)`` to resume.
    """

    def __init__(self, path: Path):
        self.path = path
        self.session_id: str = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        self.started_at: str = datetime.utcnow().isoformat() + "Z"
        self.mode: str = ""
        self.user_task: Optional[str] = None

        # Plan
        self.plan = TestPlan(created_at=self.started_at)

        # Coverage
        self.screens: Dict[str, ScreenNode] = {}       # sig → ScreenNode
        self.tested_features: Dict[str, bool] = {}     # feature_key → tested?

        # Bug ledger
        self.bugs: List[BugEntry] = []

        # Action log (append-only)
        self.action_log: List[Dict[str, Any]] = []

        # Action priority weights (Critic feedback → Explorer bias)
        self.action_weights: Dict[str, ActionWeight] = {}

        # Checkpoint cursor - what we were doing when we last saved
        self.current_goal_id: Optional[str] = None
        self.current_task_id: Optional[str] = None
        self.current_step_id: Optional[str] = None
        self.step_counter: int = 0

    # ── Persistence ──────────────────────────────────────────────────

    def _persist(self):
        """Flush the full state to disk (called after every mutation)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug("Persisting session to %s", self.path.name)
        blob = {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "mode": self.mode,
            "user_task": self.user_task,
            "plan": asdict(self.plan),
            "screens": {k: asdict(v) for k, v in self.screens.items()},
            "tested_features": self.tested_features,
            "bugs": [asdict(b) for b in self.bugs],
            "action_log": self.action_log[-500:],   # keep last 500 to limit size
            "action_weights": {k: asdict(v) for k, v in self.action_weights.items()},
            "cursor": {
                "goal_id": self.current_goal_id,
                "task_id": self.current_task_id,
                "step_id": self.current_step_id,
                "step_counter": self.step_counter,
            },
            "saved_at": datetime.utcnow().isoformat() + "Z",
        }
        self.path.write_text(json.dumps(blob, indent=2, default=str), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "SessionMemory":
        """Load a session from disk, or create a fresh one if not found."""
        mem = cls(path)
        if not path.exists():
            return mem
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return mem

        mem.session_id = blob.get("session_id", mem.session_id)
        mem.started_at = blob.get("started_at", mem.started_at)
        mem.mode = blob.get("mode", "")
        mem.user_task = blob.get("user_task")
        mem.action_log = blob.get("action_log", [])
        mem.tested_features = blob.get("tested_features", {})

        # Restore action weights
        for eid, wdata in blob.get("action_weights", {}).items():
            mem.action_weights[eid] = ActionWeight(**wdata)

        # Restore plan
        plan_data = blob.get("plan", {})
        mem.plan = cls._rebuild_plan(plan_data)

        # Restore screens
        for sig, sdata in blob.get("screens", {}).items():
            mem.screens[sig] = ScreenNode(**sdata)

        # Restore bugs
        for bdata in blob.get("bugs", []):
            mem.bugs.append(BugEntry(**bdata))

        # Restore cursor
        cursor = blob.get("cursor", {})
        mem.current_goal_id = cursor.get("goal_id")
        mem.current_task_id = cursor.get("task_id")
        mem.current_step_id = cursor.get("step_id")
        mem.step_counter = cursor.get("step_counter", 0)

        logger.info("Session resumed from %s (step %d, %d actions logged)",
                     path.name, mem.step_counter, len(mem.action_log))
        return mem

    @staticmethod
    def _rebuild_plan(data: Dict) -> TestPlan:
        goals = []
        for gd in data.get("goals", []):
            tasks = []
            for td in gd.get("tasks", []):
                steps = [TestStep(**sd) for sd in td.get("steps", [])]
                td_copy = {k: v for k, v in td.items() if k != "steps"}
                tasks.append(TestTask(**td_copy, steps=steps))
            gd_copy = {k: v for k, v in gd.items() if k != "tasks"}
            goals.append(TestGoal(**gd_copy, tasks=tasks))
        return TestPlan(
            goals=goals,
            created_at=data.get("created_at", ""),
            version=data.get("version", 1),
        )

    # ── Plan helpers ─────────────────────────────────────────────────

    def set_plan(self, plan: TestPlan):
        self.plan = plan
        self._persist()

    def get_next_task(self) -> Optional[TestTask]:
        """Return the next task that is not done, respecting priority."""
        for goal in self.plan.goals:
            if goal.is_done():
                continue
            for task in sorted(goal.tasks, key=lambda t: {"high": 0, "medium": 1, "low": 2}.get(t.priority, 1)):
                if not task.is_done():
                    # Check deps
                    all_deps_done = all(
                        self._find_task(dep_id) is not None and self._find_task(dep_id).is_done()
                        for dep_id in task.depends_on
                    )
                    if all_deps_done:
                        return task
        return None

    def get_next_step(self, task: TestTask) -> Optional[TestStep]:
        for step in task.steps:
            if step.status == TaskStatus.NOT_STARTED.value:
                return step
        return None

    def _find_task(self, task_id: str) -> Optional[TestTask]:
        for g in self.plan.goals:
            for t in g.tasks:
                if t.id == task_id:
                    return t
        return None

    def mark_step(self, step: TestStep, status: TaskStatus, **extra):
        step.mark(status, **extra)
        self._persist()

    def mark_task(self, task: TestTask, status: TaskStatus):
        task.status = status.value
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED):
            task.finished_at = datetime.utcnow().isoformat() + "Z"
        self._persist()

    def mark_goal(self, goal: TestGoal, status: TaskStatus):
        goal.status = status.value
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED):
            goal.finished_at = datetime.utcnow().isoformat() + "Z"
        self._persist()

    def update_cursor(self, *, goal_id: str = None, task_id: str = None, step_id: str = None):
        if goal_id is not None:
            self.current_goal_id = goal_id
        if task_id is not None:
            self.current_task_id = task_id
        if step_id is not None:
            self.current_step_id = step_id
        self._persist()

    # ── Screen graph ─────────────────────────────────────────────────

    def record_screen(self, signature: str, elements: List[str]):
        now = datetime.utcnow().isoformat() + "Z"
        if signature in self.screens:
            node = self.screens[signature]
            node.last_seen = now
            node.visit_count += 1
            node.elements_snapshot = elements[:50]
        else:
            node = ScreenNode(
                signature=signature,
                first_seen=now,
                last_seen=now,
                visit_count=1,
                elements_snapshot=elements[:50],
            )
            self.screens[signature] = node
        self._persist()

    def record_transition(self, from_sig: str, action_desc: str, to_sig: str):
        if from_sig in self.screens:
            self.screens[from_sig].transitions[action_desc] = to_sig
            self._persist()

    # ── Coverage ─────────────────────────────────────────────────────

    def mark_feature_tested(self, feature_key: str):
        self.tested_features[feature_key] = True
        self._persist()

    def coverage_summary(self) -> Dict[str, Any]:
        tested = sum(1 for v in self.tested_features.values() if v)
        return {
            "features_total": len(self.tested_features),
            "features_tested": tested,
            "screens_discovered": len(self.screens),
            "total_screen_visits": sum(n.visit_count for n in self.screens.values()),
        }

    def get_least_visited_screens(self, n: int = 5) -> List[Dict[str, Any]]:
        """Return the N least-visited known screens."""
        nodes = sorted(self.screens.values(), key=lambda s: s.visit_count)
        return [
            {"signature": s.signature, "visits": s.visit_count,
             "elements": s.elements_snapshot[:10]}
            for s in nodes[:n]
        ]

    def get_screen_visit_count(self, sig: str) -> int:
        """Return how many times a screen has been visited."""
        node = self.screens.get(sig)
        return node.visit_count if node else 0

    def detect_action_loop(self, window: int = 8) -> bool:
        """Check if the recent N actions show a repeating loop pattern.

        Only considers interactive actions (click, input, long_press) --
        escape actions (back, scroll) are excluded since they are used
        to break out of loops and would cause false positives.

        Returns True if the last `window` interactive actions contain
        >=3 identical (action, screen) pairs.
        """
        recent = self.action_log[-window * 2:] if len(self.action_log) >= window else self.action_log
        if len(recent) < 4:
            return False
        # Only consider interactive actions, not escape/barrier actions
        escape_actions = {"back", "scroll", "__barrier__"}
        interactive = [
            r for r in recent
            if r.get("action", "") not in escape_actions
        ]
        # Take only the last `window` interactive actions
        interactive = interactive[-window:]
        if len(interactive) < 3:
            return False
        # Build (action_type, screen_sig) tuples
        pairs = [(r.get("action", ""), r.get("screen_sig", "")) for r in interactive]
        from collections import Counter
        counts = Counter(pairs)
        _, top_count = counts.most_common(1)[0]
        return top_count >= 3

    def get_unvisited_transitions(self, current_sig: str) -> List[str]:
        """Return element IDs that lead to less-visited screens."""
        node = self.screens.get(current_sig)
        if not node or not node.transitions:
            return []
        # Sort transitions by destination visit count (ascending)
        results = []
        for action_desc, target_sig in node.transitions.items():
            target_visits = self.get_screen_visit_count(target_sig)
            results.append((action_desc, target_visits))
        results.sort(key=lambda x: x[1])
        return [desc for desc, _ in results[:5]]

    # ── Action priority weights (Critic → Explorer) ────────────────

    _VERDICT_REWARDS = {"pass": +1.0, "warn": -0.3, "fail": -1.5}

    def update_action_weight(self, element_id: str, verdict: str):
        """Apply a Critic verdict as a reward signal on an element.

        Called by the Orchestrator after every Critic evaluation. The
        cumulative weight biases Explorer element selection.
        """
        if not element_id:
            return
        now = datetime.utcnow().isoformat() + "Z"
        reward = self._VERDICT_REWARDS.get(verdict, 0.0)

        w = self.action_weights.get(element_id)
        if w is None:
            w = ActionWeight(element_id=element_id)
            self.action_weights[element_id] = w

        w.weight += reward
        w.last_verdict = verdict
        w.last_updated = now
        if verdict == "pass":
            w.pass_count += 1
        elif verdict == "fail":
            w.fail_count += 1
        self._persist()

    def get_element_weight(self, element_id: str) -> float:
        """Return the cumulative Critic-derived weight for an element."""
        w = self.action_weights.get(element_id)
        return w.weight if w else 0.0

    def get_top_weighted_elements(self, n: int = 10) -> List[Dict[str, Any]]:
        """Return the N highest-weighted elements (Critic-rewarded)."""
        items = sorted(self.action_weights.values(),
                       key=lambda w: w.weight, reverse=True)
        return [
            {"element_id": w.element_id, "weight": w.weight,
             "pass": w.pass_count, "fail": w.fail_count}
            for w in items[:n]
        ]

    def get_penalised_elements(self, threshold: float = -1.0) -> set:
        """Return element IDs whose cumulative weight is below threshold.

        Explorer should deprioritise these -- Critic has repeatedly
        marked actions on them as failures or hallucinations.
        """
        return {
            eid for eid, w in self.action_weights.items()
            if w.weight <= threshold
        }

    # ── Bugs ─────────────────────────────────────────────────────────

    def add_bug(self, bug: BugEntry):
        self.bugs.append(bug)
        self._persist()

    # ── Action log ───────────────────────────────────────────────────

    def clear_loop_history(self):
        """Insert a barrier so loop detection ignores actions before this point.

        This is called after an app reset so the loop detector does not
        immediately re-trigger on stale action history.
        """
        # Insert several 'barrier' entries so the sliding window
        # in detect_action_loop() sees only non-interactive records.
        for _ in range(10):
            self.action_log.append({
                "action": "__barrier__",
                "screen_sig": "__reset__",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "step_counter": self.step_counter,
            })
        self._persist()

    def log_action(self, record: Dict[str, Any]):
        record.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")
        record.setdefault("step_counter", self.step_counter)
        self.action_log.append(record)
        self.step_counter += 1
        self._persist()

    def recent_actions(self, n: int = 10) -> List[Dict[str, Any]]:
        return self.action_log[-n:]

    # ── Reporting ────────────────────────────────────────────────────

    def full_report(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "mode": self.mode,
            "user_task": self.user_task,
            "plan_summary": self.plan.summary(),
            "coverage": self.coverage_summary(),
            "bugs_found": len(self.bugs),
            "bugs": [asdict(b) for b in self.bugs],
            "total_actions": len(self.action_log),
            "screens_discovered": len(self.screens),
        }
