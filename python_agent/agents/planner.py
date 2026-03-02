"""
Planner Agent  --  analyses the application under test and produces a
hierarchical ``TestPlan`` (goals → tasks → steps).

It is independent of the Navigator  --  it only reasons about *what* to
test, never about *how* to execute the actions on the device.
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


class PlannerAgent(BaseAgent):
    name = "planner"
    system_role = (
        "You are a senior QA test-planning agent for a mobile application. "
        "You produce structured, hierarchical test plans in JSON. "
        "Each plan has high-level goals, mid-level tasks inside each goal, "
        "and fine-grained steps inside each task. "
        "Your plans must be concrete and actionable  --  each step should map to "
        "a single UI interaction (click, input, scroll, back, assert). "
        "Never hallucinate element IDs  --  only reference IDs provided in the context."
    )

    # ── Plan creation ────────────────────────────────────────────────

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

CURRENT UI ELEMENTS (home screen):
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
    def _dict_to_plan(data: Dict[str, Any]) -> TestPlan:
        goals: List[TestGoal] = []
        for gd in data.get("goals", []):
            tasks: List[TestTask] = []
            for td in gd.get("tasks", []):
                steps = [
                    TestStep(
                        id=sd.get("id", f"step_{i}"),
                        description=sd.get("description", ""),
                    )
                    for i, sd in enumerate(td.get("steps", []))
                ]
                tasks.append(
                    TestTask(
                        id=td.get("id", ""),
                        name=td.get("name", ""),
                        description=td.get("description", ""),
                        priority=td.get("priority", "medium"),
                        steps=steps,
                        depends_on=td.get("depends_on", []),
                    )
                )
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
