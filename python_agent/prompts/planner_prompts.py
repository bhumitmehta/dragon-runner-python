"""
Prompt templates for the Planner Agent.

The Planner produces hierarchical test plans (goals → tasks → steps),
exploration directives, task complexity estimates, and decomposition prompts.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .builder import PromptBuilder


# ── System role ──────────────────────────────────────────────────────

PLANNER_SYSTEM_ROLE = (
    "You are a senior QA test-planning agent for a mobile application. "
    "You produce structured, hierarchical test plans in JSON. "
    "Each plan has high-level goals, mid-level tasks inside each goal, "
    "and fine-grained steps inside each task. "
    "Your plans must be concrete and actionable  --  each step should map to "
    "a single UI interaction (click, input, scroll, back, assert). "
    "Never hallucinate element IDs  --  only reference IDs provided in the context."
)


class PlannerPrompts:
    """Factory for Planner agent prompts using the builder pattern."""

    SYSTEM_ROLE = PLANNER_SYSTEM_ROLE

    # ── Exploration directive ────────────────────────────────────────

    @staticmethod
    def exploration_directive(
        coverage: Dict[str, Any],
        least_visited: List[Dict[str, Any]],
        top_visited_sigs: List[str],
        tested_features: List[str],
        ui_elements: Dict[str, List[str]],
        user_task: Optional[str] = None,
    ) -> str:
        """Build prompt for generating an ExplorationDirective."""
        lv_data = [
            {"sig": s["signature"][:20], "visits": s["visits"]}
            for s in least_visited
        ]

        mode_line = (
            f"USER TASK: {user_task}"
            if user_task
            else "MODE: Autonomous exploration -- maximise coverage"
        )

        return (
            PromptBuilder()
            .preamble(
                "You are a QA test strategist. Given the current session coverage,\n"
                "produce a JSON exploration directive that tells the Explorer agent where to focus."
            )
            .section_json("SESSION COVERAGE", coverage)
            .section(
                "LEAST-VISITED SCREENS (need more attention)",
                json.dumps(lv_data),
            )
            .section(
                "MOST-VISITED SCREENS (already well-covered)",
                json.dumps(top_visited_sigs[:5]),
            )
            .section("TESTED FEATURES", json.dumps(tested_features[:10]))
            .section(
                "CURRENT UI ELEMENTS",
                f"Accessibility IDs: {json.dumps(ui_elements.get('accessibility_ids', [])[:25])}",
            )
            .section("OBJECTIVE", mode_line)
            .json_output(
                '{\n'
                '    "objective": "<1-sentence session goal>",\n'
                '    "priority_screens": ["<screen sigs or keywords to navigate toward>"],\n'
                '    "avoid_screens": ["<over-visited screen sigs to deprioritise>"],\n'
                '    "focus_elements": ["<element keywords to prefer, e.g. \'cart\', \'settings\'>"],\n'
                '    "avoid_elements": ["<element keywords to skip>"],\n'
                '    "max_screen_dwell": "<int, max steps on one screen before moving on>"\n'
                '}',
                preamble="Return ONLY JSON:",
            )
            .build()
        )

    # ── Plan creation ────────────────────────────────────────────────

    @staticmethod
    def create_plan(
        app_description: str,
        ui_elements: Dict[str, List[str]],
        user_task: Optional[str] = None,
        existing_coverage: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the prompt for generating a full test plan."""
        goal_hint = (
            f"Focus on this specific user task: {user_task}"
            if user_task
            else "Create a comprehensive plan to explore and test the entire application."
        )

        builder = (
            PromptBuilder()
            .preamble(goal_hint)
            .section("APPLICATION", app_description)
        )

        if existing_coverage:
            builder.section(
                "ALREADY-TESTED FEATURES",
                json.dumps(existing_coverage)
                + "\nSkip or de-prioritize features that are already well-tested.",
            )

        builder.ui_elements(
            ui_elements.get("accessibility_ids", []),
            ui_elements.get("resource_ids", []),
            ui_elements.get("clickable_texts", []),
            acc_limit=40,
            res_limit=25,
            txt_limit=25,
        )

        builder.json_output(
            '{\n'
            '  "goals": [\n'
            '    {\n'
            '      "id": "goal_1",\n'
            '      "name": "<short name>",\n'
            '      "description": "<what area/feature is being tested>",\n'
            '      "tasks": [\n'
            '        {\n'
            '          "id": "task_1_1",\n'
            '          "name": "<short name>",\n'
            '          "description": "<what this task verifies>",\n'
            '          "priority": "high" | "medium" | "low",\n'
            '          "depends_on": [],\n'
            '          "steps": [\n'
            '            {\n'
            '              "id": "step_1_1_1",\n'
            '              "description": "<single UI action, e.g. click element X>"\n'
            '            }\n'
            '          ]\n'
            '        }\n'
            '      ]\n'
            '    }\n'
            '  ]\n'
            '}',
            preamble="Return a JSON object with the following exact structure (no markdown, no explanation):",
        )

        builder.rules([
            "Generate 2-5 goals, each with 1-4 tasks, each with 2-8 steps.",
            "Only reference element IDs from the lists above.",
            "Each step must be a single atomic UI action (click, input, scroll, back, assert).",
            "High-priority tasks should cover core flows (login, navigation, cart).",
            "Include negative test cases (invalid input, empty fields) as medium-priority tasks.",
            "Ensure steps are ordered logically and each task is self-contained.",
        ])

        return builder.build()

    # ── Re-plan after failure ────────────────────────────────────────

    @staticmethod
    def replan(
        plan_summary: Dict[str, Any],
        recent_bugs: List[Dict[str, Any]],
        coverage: Dict[str, Any],
        failure_context: str,
    ) -> str:
        """Build the prompt for re-planning after a task failure."""
        return (
            PromptBuilder()
            .preamble("A test run encountered a problem and needs re-planning.")
            .section_json("CURRENT PLAN PROGRESS", plan_summary)
            .section_json("RECENT BUGS FOUND", recent_bugs)
            .section_json("COVERAGE", coverage)
            .section("FAILURE REASON", failure_context)
            .preamble("")
            .json_output(
                '{\n  "goals": [ ... ]\n}',
                preamble=(
                    "Generate an UPDATED test plan that:\n"
                    "1. Skips tasks already completed\n"
                    "2. Retries or restructures the failed task\n"
                    "3. Adds new tasks if the failure reveals untested areas\n"
                    "4. Keeps the same JSON structure as before\n\n"
                    "Return the updated plan as JSON with the same schema:"
                ),
            )
            .build()
        )

    # ── Complexity estimation ────────────────────────────────────────

    @staticmethod
    def estimate_complexity(task_name: str, task_description: str, step_count: int) -> str:
        """Build the prompt for LLM-based complexity estimation."""
        return (
            PromptBuilder()
            .preamble(
                "Rate this mobile app test task's complexity as "
                "1 (simple), 2 (medium), or 3 (complex)."
            )
            .section(
                "TASK",
                f"Name: {task_name}\n"
                f"Description: {task_description}\n"
                f"Steps: {step_count}",
            )
            .rules([
                '1 = single screen, 1-3 taps (e.g. "click a button")',
                '2 = spans 2-3 screens or has conditional logic (e.g. "fill form and submit")',
                '3 = multi-screen flow with verification (e.g. "login, browse, add to cart, checkout")',
            ])
            .output("Return ONLY the number: 1, 2, or 3")
            .build()
        )

    # ── Task decomposition ───────────────────────────────────────────

    @staticmethod
    def decompose_task(
        task_id: str,
        task_name: str,
        task_description: str,
        task_priority: str,
        ui_elements: Dict[str, List[str]],
        doc_context: str = "",
    ) -> str:
        """Build the prompt for decomposing a complex task into subtasks."""
        builder = (
            PromptBuilder()
            .preamble(
                "Break this test task into smaller subtasks. Each subtask should be\n"
                "independently executable on a mobile app."
            )
            .section(
                "TASK",
                f"Name: {task_name}\n"
                f"Description: {task_description}",
            )
        )

        if doc_context:
            builder.section("DOCUMENTATION CONTEXT", doc_context[:1500])

        builder.ui_elements(
            ui_elements.get("accessibility_ids", []),
            ui_elements.get("resource_ids", []),
            ui_elements.get("clickable_texts", []),
        )

        builder.json_output(
            '{\n'
            '    "subtasks": [\n'
            '        {\n'
            f'            "id": "{task_id}_sub1",\n'
            '            "name": "<short subtask name>",\n'
            '            "description": "<what this subtask does>",\n'
            f'            "priority": "{task_priority}",\n'
            '            "complexity": 1 | 2 | 3,\n'
            '            "steps": [\n'
            '                {"id": "s1", "description": "<atomic UI action>"}\n'
            '            ]\n'
            '        }\n'
            '    ]\n'
            '}',
            preamble="Return ONLY JSON:",
        )

        builder.rules([
            "Break into 2-5 subtasks, each with 1-4 atomic steps.",
            "Each subtask should target ONE screen or ONE logical action group.",
            "Only reference element IDs from the lists above.",
            "If a subtask needs elements not currently visible, its first step should navigate there.",
            "complexity: 1=simple (single screen), 2=medium (2-3 screens), 3=complex (needs further decomposition).",
            "Subtasks should be ordered logically (navigate first, then act, then verify).",
        ])

        return builder.build()
