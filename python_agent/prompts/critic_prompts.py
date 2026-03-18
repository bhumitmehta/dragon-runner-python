"""
Prompt templates for the Critic Agent.

The Critic validates outputs from other agents -- checking for
hallucinated element IDs, action feasibility, and post-execution
correctness.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .builder import PromptBuilder


# ── System role ──────────────────────────────────────────────────────

CRITIC_SYSTEM_ROLE = (
    "You are a strict QA critic agent. "
    "Your job is to validate the output of other AI agents for correctness. "
    "You check that:\n"
    "1) Referenced UI elements actually exist on the screen.\n"
    "2) The proposed action is feasible given the current UI state.\n"
    "3) After execution, the claimed outcome matches reality.\n"
    "4) The other agent is not hallucinating element IDs, screens, or results.\n"
    "Always return a structured JSON verdict."
)

# ── Shared verdict schema ────────────────────────────────────────────

_VERDICT_SCHEMA = (
    '{\n'
    '    "verdict": "pass" | "warn" | "fail",\n'
    '    "reason": "<explanation>"\n'
    '}'
)


class CriticPrompts:
    """Factory for Critic agent prompts using the builder pattern."""

    SYSTEM_ROLE = CRITIC_SYSTEM_ROLE

    # ── Pre-execution action check ───────────────────────────────────

    @staticmethod
    def validate_action(
        action_plan: Dict[str, Any],
        ui_elements: Dict[str, List[str]],
    ) -> str:
        """Build prompt to validate a proposed action before execution."""
        return (
            PromptBuilder()
            .preamble("Validate whether this proposed action is feasible.")
            .section_json("PROPOSED ACTION", action_plan)
            .ui_elements(
                ui_elements.get("accessibility_ids", []),
                ui_elements.get("resource_ids", []),
                ui_elements.get("clickable_texts", []),
            )
            .section(
                "CHECK",
                "1. Does the referenced element exist in the lists above?\n"
                "2. Is the action type appropriate for the element?\n"
                "3. Is the locator_type correct for the locator_value?\n"
                "4. If it's an input action, does specifying text make sense?",
            )
            .json_output(_VERDICT_SCHEMA, preamble="Return ONLY JSON:")
            .build()
        )

    # ── Post-execution result check ──────────────────────────────────

    @staticmethod
    def validate_result(
        action_plan: Dict[str, Any],
        result: Dict[str, Any],
        ui_before: Dict[str, List[str]],
        ui_after: Dict[str, List[str]],
    ) -> str:
        """Build prompt to validate whether an action achieved its goal."""
        return (
            PromptBuilder()
            .preamble("Validate whether this action achieved its intended result.")
            .section_json("PLANNED ACTION", action_plan)
            .section_json("EXECUTION RESULT", result)
            .section(
                "UI BEFORE ACTION",
                f"Accessibility IDs: {json.dumps(ui_before.get('accessibility_ids', [])[:20])}\n"
                f"Clickable Texts: {json.dumps(ui_before.get('clickable_texts', [])[:15])}",
            )
            .section(
                "UI AFTER ACTION",
                f"Accessibility IDs: {json.dumps(ui_after.get('accessibility_ids', [])[:20])}\n"
                f"Clickable Texts: {json.dumps(ui_after.get('clickable_texts', [])[:15])}",
            )
            .section(
                "CHECK",
                "1. Did the UI state change as expected?\n"
                "2. Does the reported success/failure match reality?\n"
                "3. Are there signs of a crash, error dialog, or unexpected state?",
            )
            .json_output(_VERDICT_SCHEMA, preamble="Return ONLY JSON:")
            .build()
        )

    # ── Plan validation ──────────────────────────────────────────────

    @staticmethod
    def validate_plan(
        plan_dict: Dict[str, Any],
        ui_elements: Dict[str, List[str]],
    ) -> str:
        """Build prompt to validate a test plan for hallucinations."""
        plan_json = json.dumps(plan_dict, indent=2)[:3000]

        return (
            PromptBuilder()
            .preamble("Validate this test plan for hallucinations and feasibility.")
            .section("TEST PLAN (truncated)", plan_json)
            .section(
                "ACTUAL UI ELEMENTS ON HOME SCREEN",
                f"Accessibility IDs: {json.dumps(ui_elements.get('accessibility_ids', [])[:30])}\n"
                f"Resource IDs: {json.dumps(ui_elements.get('resource_ids', [])[:20])}\n"
                f"Clickable Texts: {json.dumps(ui_elements.get('clickable_texts', [])[:20])}",
            )
            .section(
                "CHECK",
                "1. Do the step descriptions reference elements that exist?\n"
                "2. Are the steps logically ordered?\n"
                "3. Are there unreachable or impossible tasks?\n"
                "4. Are IDs from the plan present in the UI element lists?",
            )
            .json_output(
                '{\n'
                '    "verdict": "pass" | "warn" | "fail",\n'
                '    "reason": "<explanation>",\n'
                '    "hallucinated_ids": ["<list any IDs in the plan that don\'t exist on screen>"]\n'
                '}',
                preamble="Return ONLY JSON:",
            )
            .build()
        )
