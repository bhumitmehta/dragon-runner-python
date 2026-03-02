"""
Critic Agent  --  validates other agents' outputs for hallucinations,
feasibility, and correctness.

The Critic receives:
1. The *proposed* action/plan from another agent
2. The *actual* UI state (element lists, screenshot)
3. The *result* of the action (post-execution)

It then issues a verdict: PASS, WARN, or FAIL with a reason.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from ..logging_config import get_logger

logger = get_logger("agents.critic")


class Verdict:
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class CriticAgent(BaseAgent):
    name = "critic"
    system_role = (
        "You are a strict QA critic agent. "
        "Your job is to validate the output of other AI agents for correctness. "
        "You check that:\n"
        "1) Referenced UI elements actually exist on the screen.\n"
        "2) The proposed action is feasible given the current UI state.\n"
        "3) After execution, the claimed outcome matches reality.\n"
        "4) The other agent is not hallucinating element IDs, screens, or results.\n"
        "Always return a structured JSON verdict."
    )

    # ── Evaluate with memory feedback ────────────────────────────────

    def evaluate_and_update(
        self,
        action_plan: Dict[str, Any],
        result: Dict[str, Any],
        ui_before: Dict[str, List[str]],
        ui_after: Dict[str, List[str]],
        memory: Any,
    ) -> Dict[str, Any]:
        """Evaluate a step AND push the verdict into SessionMemory's action
        weights so the Explorer can learn from Critic feedback.

        This is the preferred entry point -- replaces bare
        ``validate_result`` calls in the Orchestrator.
        """
        verdict = self.validate_result(action_plan, result, ui_before, ui_after)

        # Feed the verdict back as a reward signal
        element_id = action_plan.get("locator_value", "") or ""
        if element_id and hasattr(memory, "update_action_weight"):
            memory.update_action_weight(element_id, verdict.get("verdict", ""))

        return verdict

    # ── Validate a proposed action ───────────────────────────────────

    def validate_action(
        self,
        action_plan: Dict[str, Any],
        ui_elements: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """
        Pre-execution check: is the action feasible with the current
        on-screen elements?

        Returns ``{"verdict": "pass"|"warn"|"fail", "reason": "..."}``
        """
        # Fast-path: structural check (no LLM)
        fast = self._structural_check(action_plan, ui_elements)
        if fast["verdict"] == Verdict.FAIL:
            logger.warning("Structural check FAIL: %s", fast['reason'])
            return fast

        # LLM deep check (catches semantic issues)
        prompt = self._build_action_check_prompt(action_plan, ui_elements)
        raw = self.ask_text(prompt)
        parsed = self.parse_json_strict(raw, ["verdict", "reason"])
        if parsed and parsed.get("verdict") in (Verdict.PASS, Verdict.WARN, Verdict.FAIL):
            logger.debug("Action verdict: %s -- %s", parsed['verdict'], parsed.get('reason', '')[:60])
            return parsed
        # If LLM response is garbage, trust the structural check
        return fast

    def validate_result(
        self,
        action_plan: Dict[str, Any],
        result: Dict[str, Any],
        ui_before: Dict[str, List[str]],
        ui_after: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """
        Post-execution check: did the action actually achieve what was claimed?
        """
        prompt = self._build_result_check_prompt(action_plan, result, ui_before, ui_after)
        raw = self.ask_text(prompt)
        parsed = self.parse_json_strict(raw, ["verdict", "reason"])
        if parsed and parsed.get("verdict") in (Verdict.PASS, Verdict.WARN, Verdict.FAIL):
            return parsed
        # Default: accept the result if we can't parse the critic
        return {"verdict": Verdict.PASS, "reason": "Critic could not parse -- defaulting to pass"}

    def validate_plan(
        self,
        plan_dict: Dict[str, Any],
        ui_elements: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """
        Validate a test plan for obvious hallucinations (e.g. element IDs
        that don't exist, unreachable screens).
        """
        prompt = self._build_plan_check_prompt(plan_dict, ui_elements)
        raw = self.ask_text(prompt)
        parsed = self.parse_json_strict(raw, ["verdict", "reason"])
        if parsed:
            return parsed
        return {"verdict": Verdict.WARN, "reason": "Could not validate plan"}

    # ── Structural (non-LLM) checks ─────────────────────────────────

    def _structural_check(
        self,
        action_plan: Dict[str, Any],
        ui_elements: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """
        Quick, deterministic checks that don't need an LLM call.
        """
        action = action_plan.get("action", "")
        locator_type = action_plan.get("locator_type")
        locator_value = action_plan.get("locator_value")

        # Actions that don't reference elements are always fine structurally
        if action in ("scroll", "back", "hide_keyboard", "press_enter", "done", "explore", "skip", "assert"):
            return {"verdict": Verdict.PASS, "reason": "Action does not reference a specific element"}

        if action in ("click", "input") and locator_value:
            # Check whether the locator_value actually exists
            all_ids: set[str] = set()
            all_ids.update(ui_elements.get("accessibility_ids", []))
            all_ids.update(ui_elements.get("resource_ids", []))
            all_ids.update(ui_elements.get("clickable_texts", []))

            if locator_value in all_ids:
                return {"verdict": Verdict.PASS, "reason": f"Element '{locator_value}' found on screen"}

            # Fuzzy: check case-insensitive
            lower_ids = {x.lower() for x in all_ids}
            if locator_value.lower() in lower_ids:
                return {
                    "verdict": Verdict.WARN,
                    "reason": f"Element '{locator_value}' found with case mismatch",
                }

            return {
                "verdict": Verdict.FAIL,
                "reason": (
                    f"HALLUCINATION: Element '{locator_value}' (type={locator_type}) "
                    f"does not exist on the current screen. "
                    f"Available: {json.dumps(list(all_ids)[:15])}"
                ),
            }

        return {"verdict": Verdict.PASS, "reason": "No structural issues detected"}

    # ── LLM prompt builders ──────────────────────────────────────────

    def _build_action_check_prompt(
        self,
        action_plan: Dict[str, Any],
        ui_elements: Dict[str, List[str]],
    ) -> str:
        return f"""Validate whether this proposed action is feasible.

PROPOSED ACTION:
{json.dumps(action_plan, indent=2)}

AVAILABLE UI ELEMENTS:
Accessibility IDs: {json.dumps(ui_elements.get('accessibility_ids', [])[:30])}
Resource IDs: {json.dumps(ui_elements.get('resource_ids', [])[:20])}
Clickable Texts: {json.dumps(ui_elements.get('clickable_texts', [])[:20])}

Check:
1. Does the referenced element exist in the lists above?
2. Is the action type appropriate for the element?
3. Is the locator_type correct for the locator_value?
4. If it's an input action, does specifying text make sense?

Return ONLY JSON:
{{
    "verdict": "pass" | "warn" | "fail",
    "reason": "<explanation>"
}}"""

    def _build_result_check_prompt(
        self,
        action_plan: Dict[str, Any],
        result: Dict[str, Any],
        ui_before: Dict[str, List[str]],
        ui_after: Dict[str, List[str]],
    ) -> str:
        return f"""Validate whether this action achieved its intended result.

PLANNED ACTION:
{json.dumps(action_plan, indent=2)}

EXECUTION RESULT:
{json.dumps(result, indent=2)}

UI BEFORE ACTION:
Accessibility IDs: {json.dumps(ui_before.get('accessibility_ids', [])[:20])}
Clickable Texts: {json.dumps(ui_before.get('clickable_texts', [])[:15])}

UI AFTER ACTION:
Accessibility IDs: {json.dumps(ui_after.get('accessibility_ids', [])[:20])}
Clickable Texts: {json.dumps(ui_after.get('clickable_texts', [])[:15])}

Check:
1. Did the UI state change as expected?
2. Does the reported success/failure match reality?
3. Are there signs of a crash, error dialog, or unexpected state?

Return ONLY JSON:
{{
    "verdict": "pass" | "warn" | "fail",
    "reason": "<explanation>"
}}"""

    def _build_plan_check_prompt(
        self,
        plan_dict: Dict[str, Any],
        ui_elements: Dict[str, List[str]],
    ) -> str:
        # Flatten all element references from the plan
        plan_json = json.dumps(plan_dict, indent=2)[:3000]
        return f"""Validate this test plan for hallucinations and feasibility.

TEST PLAN (truncated):
{plan_json}

ACTUAL UI ELEMENTS ON HOME SCREEN:
Accessibility IDs: {json.dumps(ui_elements.get('accessibility_ids', [])[:30])}
Resource IDs: {json.dumps(ui_elements.get('resource_ids', [])[:20])}
Clickable Texts: {json.dumps(ui_elements.get('clickable_texts', [])[:20])}

Check:
1. Do the step descriptions reference elements that exist?
2. Are the steps logically ordered?
3. Are there unreachable or impossible tasks?
4. Are IDs from the plan present in the UI element lists?

Return ONLY JSON:
{{
    "verdict": "pass" | "warn" | "fail",
    "reason": "<explanation>",
    "hallucinated_ids": ["<list any IDs in the plan that don't exist on screen>"]
}}"""
