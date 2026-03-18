"""
Planner Agent  --  analyses the application under test and produces a
hierarchical ``TestPlan`` (goals → tasks → steps).

It is independent of the Navigator  --  it only reasons about *what* to
test, never about *how* to execute the actions on the device.

Time horizon: SESSION-LEVEL.  The Planner owns long-term objectives
(which features to cover, in what order).  The Explorer owns
short-term, per-screen curiosity within the boundaries the Planner sets.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from ..logging_config import get_logger
from ..session_memory import (
    SessionMemory,
    TestGoal,
    TestPlan,
    TestStep,
    TestTask,
    TaskStatus,
)

logger = get_logger("agents.planner")


# ────────────────────────────────────────────────────────────────────────
#  Exploration Directive  (Planner → Explorer contract)
# ────────────────────────────────────────────────────────────────────────

class ExplorationDirective:
    """A session-level directive from the Planner that constrains the
    Explorer's curiosity.

    The Explorer may roam freely within a screen, but the directive
    tells it:
    - ``priority_screens``: which screens to prefer navigating toward
    - ``avoid_screens``: screens already well-covered (deprioritise)
    - ``focus_elements``: element keywords to prefer (e.g. "cart", "login")
    - ``avoid_elements``: element keywords to skip (already tested)
    - ``objective``: human-readable session goal
    - ``max_screen_dwell``: max steps on a single screen before moving on
    """

    def __init__(
        self,
        objective: str = "",
        priority_screens: Optional[List[str]] = None,
        avoid_screens: Optional[List[str]] = None,
        focus_elements: Optional[List[str]] = None,
        avoid_elements: Optional[List[str]] = None,
        max_screen_dwell: int = 8,
    ):
        self.objective = objective
        self.priority_screens = priority_screens or []
        self.avoid_screens = avoid_screens or []
        self.focus_elements = focus_elements or []
        self.avoid_elements = avoid_elements or []
        self.max_screen_dwell = max_screen_dwell

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "priority_screens": self.priority_screens,
            "avoid_screens": self.avoid_screens,
            "focus_elements": self.focus_elements,
            "avoid_elements": self.avoid_elements,
            "max_screen_dwell": self.max_screen_dwell,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExplorationDirective":
        return cls(**{k: v for k, v in d.items() if k in cls.__init__.__code__.co_varnames})


class PlannerAgent(BaseAgent):
    name = "planner"
    system_role = (
        "You are a QA test-planning agent for a mobile application. "
        "You produce structured, hierarchical test plans in JSON. "
        "Each plan has high-level goals, mid-level tasks inside each goal, "
        "and fine-grained steps inside each task. "
        "Your plans must be concrete and actionable  --  each step should map to "
        "a single UI interaction (click, input, scroll, back, assert). "
        "Never hallucinate element IDs  --  only reference IDs provided in the context."
    )

    # ── Plan creation ────────────────────────────────────────────────

    def generate_exploration_directive(
        self,
        memory: SessionMemory,
        ui_elements: Dict[str, List[str]],
        *,
        user_task: Optional[str] = None,
    ) -> ExplorationDirective:
        """Produce a session-level directive that constrains the Explorer.

        Uses coverage data to identify under-explored areas and
        well-covered screens, giving the Explorer a focused mandate
        instead of unbounded curiosity.
        """
        coverage = memory.coverage_summary()
        least_visited = memory.get_least_visited_screens(5)
        top_visited_sigs = [
            s.signature for s in sorted(
                memory.screens.values(), key=lambda s: s.visit_count, reverse=True
            )[:5]
        ]
        # Features already tested
        tested = [k for k, v in memory.tested_features.items() if v]

        prompt = f"""You are a QA test strategist. Given the current session coverage,
produce a JSON exploration directive that tells the Explorer agent where to focus.

SESSION COVERAGE:
{json.dumps(coverage, indent=2)}

LEAST-VISITED SCREENS (need more attention):
{json.dumps([{{"sig": s["signature"][:20], "visits": s["visits"]}} for s in least_visited])}

MOST-VISITED SCREENS (already well-covered):
{json.dumps(top_visited_sigs[:5])}

TESTED FEATURES: {json.dumps(tested[:10])}

CURRENT UI ELEMENTS:
Accessibility IDs: {json.dumps(ui_elements.get("accessibility_ids", [])[:25])}

{"USER TASK: " + user_task if user_task else "MODE: Autonomous exploration -- maximise coverage"}

Return ONLY JSON:
{{
    "objective": "<1-sentence session goal>",
    "priority_screens": ["<screen sigs or keywords to navigate toward>"],
    "avoid_screens": ["<over-visited screen sigs to deprioritise>"],
    "focus_elements": ["<element keywords to prefer, e.g. 'cart', 'settings'>"],
    "avoid_elements": ["<element keywords to skip>"],
    "max_screen_dwell": <int, max steps on one screen before moving on>
}}"""

        raw = self.ask_text(prompt)
        parsed = self.parse_json(raw)
        if isinstance(parsed, dict):
            directive = ExplorationDirective.from_dict(parsed)
            logger.info("Exploration directive: %s (focus=%s, avoid=%s, dwell=%d)",
                        directive.objective[:60],
                        directive.focus_elements[:3],
                        directive.avoid_screens[:2],
                        directive.max_screen_dwell)
            return directive

        # Fallback: sensible defaults
        return ExplorationDirective(
            objective=user_task or "Maximise screen and feature coverage",
            priority_screens=[s["signature"] for s in least_visited[:3]],
            avoid_screens=top_visited_sigs[:3],
            max_screen_dwell=8,
        )

    def create_plan(
        self,
        app_description: str,
        ui_elements: Dict[str, List[str]],
        *,
        user_task: Optional[str] = None,
        existing_coverage: Optional[Dict[str, Any]] = None,
    ) -> Optional[TestPlan]:
        """
        Ask the LLM to produce a full test plan in one shot.

        Parameters
        ----------
        app_description : str
            A short description of the app (can be auto-detected).
        ui_elements : dict
            Keys ``accessibility_ids``, ``resource_ids``, ``clickable_texts``.
        user_task : str, optional
            If given, the plan focuses on this specific task. Otherwise the
            planner generates a comprehensive exploration plan.
        existing_coverage : dict, optional
            Coverage report from ``SessionMemory.coverage_summary()`` so the
            planner can skip already-tested features.
        """
        prompt = self._build_plan_prompt(
            app_description, ui_elements, user_task, existing_coverage
        )
        raw = self.ask_text(prompt)
        return self._parse_plan_response(raw)

    def refine_plan(
        self,
        memory: SessionMemory,
        failure_context: str,
    ) -> Optional[TestPlan]:
        """
        Re-plan after a task failure or unexpected state.

        The planner receives the current plan summary, coverage, and the
        reason for re-planning, and returns an updated plan.
        """
        prompt = self._build_replan_prompt(memory, failure_context)
        raw = self.ask_text(prompt)
        return self._parse_plan_response(raw)

    # ── Internal prompts ─────────────────────────────────────────────

    def _build_plan_prompt(
        self,
        app_description: str,
        ui_elements: Dict[str, List[str]],
        user_task: Optional[str],
        coverage: Optional[Dict[str, Any]],
    ) -> str:
        acc = json.dumps(ui_elements.get("accessibility_ids", [])[:40])
        res = json.dumps(ui_elements.get("resource_ids", [])[:25])
        txt = json.dumps(ui_elements.get("clickable_texts", [])[:25])

        goal_hint = (
            f"Focus on this specific user task: {user_task}"
            if user_task
            else "Create a comprehensive plan to explore and test the entire application."
        )

        coverage_hint = ""
        if coverage:
            coverage_hint = (
                f"\nAlready-tested features: {json.dumps(coverage)}\n"
                "Skip or de-prioritize features that are already well-tested."
            )

        return f"""{goal_hint}

APPLICATION: {app_description}
{coverage_hint}

CURRENT UI ELEMENTS :
Accessibility IDs: {acc}
Resource IDs: {res}
Clickable Texts: {txt}

Return a JSON object with the following exact structure (no markdown, no explanation):
{{
  "goals": [
    {{
      "id": "goal_1",
      "name": "<short name>",
      "description": "<what area/feature is being tested>",
      "tasks": [
        {{
          "id": "task_1_1",
          "name": "<short name>",
          "description": "<what this task verifies>",
          "priority": "high" | "medium" | "low",
          "depends_on": [],
          "steps": [
            {{
              "id": "step_1_1_1",
              "description": "<single UI action, e.g. click element X>"
            }}
          ]
        }}
      ]
    }}
  ]
}}

RULES:
- Generate 2-5 goals, each with 1-4 tasks, each with 2-8 steps.
- Only reference element IDs from the lists above.
- Each step must be a single atomic UI action (click, input, scroll, back, assert).
- High-priority tasks should cover core flows (login, navigation, cart).
- Include negative test cases (invalid input, empty fields) as medium-priority tasks.
- Ensure steps are ordered logically and each task is self-contained.
"""

    def _build_replan_prompt(self, memory: SessionMemory, failure_context: str) -> str:
        summary = memory.plan.summary()
        bugs = [{"id": b.id, "description": b.description} for b in memory.bugs[-5:]]
        coverage = memory.coverage_summary()

        return f"""A test run encountered a problem and needs re-planning.

CURRENT PLAN PROGRESS:
{json.dumps(summary, indent=2)}

RECENT BUGS FOUND:
{json.dumps(bugs, indent=2)}

COVERAGE:
{json.dumps(coverage, indent=2)}

FAILURE REASON:
{failure_context}

Generate an UPDATED test plan that:
1. Skips tasks already completed
2. Retries or restructures the failed task
3. Adds new tasks if the failure reveals untested areas
4. Keeps the same JSON structure as before

Return the updated plan as JSON with the same schema:
{{
  "goals": [ ... ]
}}
"""

    # ── Response parsing ─────────────────────────────────────────────

    def _parse_plan_response(self, raw: str) -> Optional[TestPlan]:
        """Convert the LLM JSON response into a ``TestPlan`` object."""
        obj = self.parse_json(raw)

        # ── Normalise alternative LLM structures ────────────────────
        if obj is None:
            logger.warning(
                "Could not parse plan response (raw len=%d). First 500 chars: %s",
                len(raw), raw[:500],
            )
            return None

        # If the LLM returned a list of goals directly  → wrap it
        if isinstance(obj, list):
            obj = {"goals": obj}

        if isinstance(obj, dict):
            # Handle nesting like {"plan": {"goals": [...]}} or {"test_plan": {...}}
            if "goals" not in obj:
                for key in ("plan", "test_plan", "testPlan", "testing_plan"):
                    nested = obj.get(key, None)
                    if isinstance(nested, dict) and "goals" in nested:
                        obj = nested
                        break
                    if isinstance(nested, list):
                        obj = {"goals": nested}
                        break

            # If there's still no "goals" but there *is* a single goal-shaped entry
            # e.g. {"id": "goal_1", "name": ..., "tasks": [...]}
            if "goals" not in obj and "tasks" in obj:
                obj = {"goals": [obj]}

        if not isinstance(obj, dict) or "goals" not in obj:
            logger.warning(
                "Parsed JSON but no 'goals' key found (type=%s, keys=%s). First 500 chars: %s",
                type(obj).__name__,
                list(obj.keys()) if isinstance(obj, dict) else "N/A",
                raw[:500],
            )
            return None

        try:
            return self._dict_to_plan(obj)
        except Exception as e:
            logger.error("Error building TestPlan: %s", e, exc_info=True)
            return None

    @staticmethod
    def _dict_to_task(td: Dict[str, Any]) -> TestTask:
        """Recursively parse a task dict that may contain subtasks."""
        steps = [
            TestStep(
                id=sd.get("id", f"step_{i}"),
                description=sd.get("description", ""),
            )
            for i, sd in enumerate(td.get("steps", []))
        ]
        subtasks = [
            PlannerAgent._dict_to_task(st)
            for st in td.get("subtasks", [])
        ]
        return TestTask(
            id=td.get("id", ""),
            name=td.get("name", ""),
            description=td.get("description", ""),
            priority=td.get("priority", "medium"),
            steps=steps,
            subtasks=subtasks,
            depends_on=td.get("depends_on", []),
            complexity=td.get("complexity", 0),
            decomposed=td.get("decomposed", bool(subtasks)),
            doc_context=td.get("doc_context", ""),
        )

    @staticmethod
    def _dict_to_plan(data: Dict[str, Any]) -> TestPlan:
        goals: List[TestGoal] = []
        for gd in data.get("goals", []):
            tasks = [PlannerAgent._dict_to_task(td) for td in gd.get("tasks", [])]
            goals.append(
                TestGoal(
                    id=gd.get("id", ""),
                    name=gd.get("name", ""),
                    description=gd.get("description", ""),
                    tasks=tasks,
                )
            )
        from datetime import datetime
        return TestPlan(goals=goals, created_at=datetime.utcnow().isoformat() + "Z")

    # ── Multi-level decomposition ────────────────────────────────────

    def estimate_complexity(self, task: TestTask) -> int:
        """Estimate task complexity: 1=simple, 2=medium, 3=complex.

        Uses heuristics first (step count, description length, keywords).
        Only calls the LLM if heuristics are ambiguous.
        Passes ONLY the task name + description -- minimal LLM context.
        """
        # Fast heuristics (no LLM call)
        desc_lower = (task.description + " " + task.name).lower()
        complex_signals = ["then", "after", "verify", "multiple", "flow",
                           "checkout", "end to end", "complete", "navigate through"]
        signal_count = sum(1 for kw in complex_signals if kw in desc_lower)

        if len(task.steps) <= 2 and signal_count == 0:
            task.complexity = 1
            return 1
        if len(task.steps) >= 6 or signal_count >= 3:
            task.complexity = 3
            return 3
        if len(task.steps) >= 4 or signal_count >= 2:
            task.complexity = 2
            return 2

        # Ambiguous -- ask LLM with ONLY the task info (no plan tree)
        prompt = f"""Rate this mobile app test task's complexity as 1 (simple), 2 (medium), or 3 (complex).

Task: {task.name}
Description: {task.description}
Steps: {len(task.steps)}

Rules:
- 1 = single screen, 1-3 taps (e.g. "click a button")
- 2 = spans 2-3 screens or has conditional logic (e.g. "fill form and submit")
- 3 = multi-screen flow with verification (e.g. "login, browse, add to cart, checkout")

Return ONLY the number: 1, 2, or 3"""
        raw = self.ask_text(prompt).strip()
        try:
            c = int(raw[0])
            task.complexity = max(1, min(3, c))
        except (ValueError, IndexError):
            task.complexity = 2
        return task.complexity

    def decompose_task(
        self,
        task: TestTask,
        ui_elements: Dict[str, List[str]],
        *,
        doc_context: str = "",
        kb: Optional['KnowledgeBase'] = None,
        max_depth: int = 3,
        current_depth: int = 0,
    ) -> TestTask:
        """Recursively decompose a complex task into subtasks.

        KEY DESIGN: each LLM call receives ONLY:
        - the task name + description
        - the current UI elements (what's on screen right now)
        - optionally, a doc excerpt related to this task
        Nothing about the full plan tree, other goals, or sibling tasks.

        Parameters
        ----------
        task : TestTask
            The task to decompose.
        ui_elements : dict
            Current screen elements (accessibility_ids, resource_ids, clickable_texts).
        doc_context : str
            Documentation excerpt relevant to this specific task.
        max_depth : int
            Maximum nesting depth to prevent infinite recursion.
        current_depth : int
            Current depth in the recursion.
        """
        if task.decomposed or current_depth >= max_depth:
            return task

        # Estimate complexity if not done
        if task.complexity == 0:
            self.estimate_complexity(task)

        # Simple tasks don't need decomposition
        if task.complexity <= 1:
            task.decomposed = True
            return task

        logger.info(
            "Decomposing task '%s' (complexity=%d, depth=%d/%d)",
            task.name, task.complexity, current_depth, max_depth,
        )

        # Build minimal prompt -- ONLY this task + current UI
        acc = json.dumps(ui_elements.get("accessibility_ids", [])[:30])
        res = json.dumps(ui_elements.get("resource_ids", [])[:20])
        txt = json.dumps(ui_elements.get("clickable_texts", [])[:20])

        doc_hint = ""
        if doc_context or task.doc_context:
            ctx = doc_context or task.doc_context
            
            # Adaptive context length based on task complexity
            if task.complexity >= 3:
                max_ctx = 3000  # Complex tasks need more context
            elif task.complexity >= 2:
                max_ctx = 2000  # Medium complexity
            else:
                max_ctx = 1000  # Simple tasks need less
            
            # Try to get relevant context using keywords from task
            if hasattr(self, 'kb') and self.kb:
                keywords = [task.name, task.description]
                # Split description into words and add them as keywords
                desc_words = task.description.split()[:5]  # First 5 words
                keywords.extend(desc_words)
                relevant_ctx = self.kb.get_relevant_docs_context(keywords=keywords, max_length=max_ctx)
                if relevant_ctx:
                    doc_hint = f"\nDOCUMENTATION CONTEXT:\n{relevant_ctx}\n"
                else:
                    doc_hint = f"\nDOCUMENTATION CONTEXT:\n{ctx[:max_ctx]}\n"
            else:
                # Fallback to simple truncation if no KB available
                doc_hint = f"\nDOCUMENTATION CONTEXT:\n{ctx[:max_ctx]}\n"

        prompt = f"""Break this test task into smaller subtasks. Each subtask should be
independently executable on a mobile app.

TASK: {task.name}
DESCRIPTION: {task.description}
{doc_hint}
CURRENT UI ELEMENTS ON SCREEN:
Accessibility IDs: {acc}
Resource IDs: {res}
Clickable Texts: {txt}

Return ONLY JSON:
{{
    "subtasks": [
        {{
            "id": "{task.id}_sub1",
            "name": "<short subtask name>",
            "description": "<what this subtask does>",
            "priority": "{task.priority}",
            "complexity": 1 | 2 | 3,
            "steps": [
                {{"id": "s1", "description": "<atomic UI action>"}}
            ]
        }}
    ]
}}

RULES:
- Break into 2-5 subtasks, each with 1-4 atomic steps.
- Each subtask should target ONE screen or ONE logical action group.
- Only reference element IDs from the lists above.
- If a subtask needs elements not currently visible, its first step should navigate there.
- complexity: 1=simple (single screen), 2=medium (2-3 screens), 3=complex (needs further decomposition).
- Subtasks should be ordered logically (navigate first, then act, then verify).
"""

        raw = self.ask_text(prompt)
        parsed = self.parse_json(raw)

        if not isinstance(parsed, dict) or "subtasks" not in parsed:
            logger.warning("Decomposition failed for task '%s' -- keeping original steps", task.name)
            task.decomposed = True
            return task

        subtasks = [self._dict_to_task(st) for st in parsed["subtasks"]]
        if not subtasks:
            task.decomposed = True
            return task

        task.subtasks = subtasks
        task.decomposed = True
        logger.info(
            "Task '%s' decomposed into %d subtasks (depth %d)",
            task.name, len(subtasks), current_depth,
        )

        # Recurse into complex children (depth + 1)
        for st in task.subtasks:
            if st.complexity >= 3 and current_depth + 1 < max_depth:
                self.decompose_task(
                    st, ui_elements,
                    doc_context=doc_context,
                    kb=kb,
                    max_depth=max_depth,
                    current_depth=current_depth + 1,
                )

        return task

    def decompose_plan(
        self,
        plan: TestPlan,
        ui_elements: Dict[str, List[str]],
        *,
        doc_context: str = "",
        kb: Optional['KnowledgeBase'] = None,
        max_depth: int = 3,
    ) -> TestPlan:
        """Decompose all complex tasks in a plan. Returns the same plan, mutated.

        Only tasks with complexity >= 2 get decomposed. Simple tasks are
        left as-is. This means the LLM is called only for tasks that
        actually need breaking down.
        """
        for goal in plan.goals:
            for task in goal.tasks:
                if task.decomposed:
                    continue
                if task.complexity == 0:
                    self.estimate_complexity(task)
                if task.complexity >= 2:
                    self.decompose_task(
                        task, ui_elements,
                        doc_context=doc_context,
                        kb=kb,
                        max_depth=max_depth,
                    )
                else:
                    task.decomposed = True
        return plan
