"""
ScriptExecutor Agent -- replays navigation scripts and runs verification
scripts on the live device via the Navigator + AppiumController.

It executes the structured action sequences produced by the ScriptGenerator
and evaluates assertions against the actual UI state.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from .navigator import NavigatorAgent
from ..logging_config import get_logger
from ..appium_controller import AppiumController
from ..ui_extract import (
    extract_clickable_accessibility_ids,
    extract_clickable_resource_ids,
    extract_clickable_texts,
    extract_all_interactive_elements,
)
from ..memory import state_signature_from_xml

logger = get_logger("agents.script_executor")


class ScriptExecutorAgent(BaseAgent):
    name = "script_executor"
    system_role = (
        "You are a test execution engine that runs UI test scripts step-by-step "
        "and evaluates assertions against the live application state."
    )

    def __init__(self, navigator: NavigatorAgent, controller: AppiumController):
        super().__init__()
        self.navigator = navigator
        self.controller = controller

    # ── Public API ───────────────────────────────────────────────────

    def execute_nav_script(self, nav_script: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replay a navigation script to reach a target screen.

        Returns: {success, steps_executed, final_signature, errors}
        """
        steps = nav_script.get("steps", [])
        logger.info("Executing nav script: %s (%d steps)", nav_script.get("name", "?"), len(steps))

        errors: List[str] = []
        steps_executed = 0

        for i, step in enumerate(steps):
            action = step.get("action", "")

            # Handle wait/sleep steps directly
            if action == "wait":
                wait_sec = step.get("duration", 1.5)
                try:
                    wait_sec = float(wait_sec)
                except (ValueError, TypeError):
                    wait_sec = 1.5
                wait_sec = min(wait_sec, 5.0)  # cap at 5s
                time.sleep(wait_sec)
                steps_executed += 1
                logger.debug("Nav step %d: waited %.1fs", i + 1, wait_sec)
                continue

            # Handle skip/noop
            if action in ("skip", "noop", ""):
                steps_executed += 1
                continue

            # Re-capture UI before each step so elements are fresh
            ui_ctx = self._capture_ui()
            result = self._execute_step_with_fallback(step, ui_ctx)
            steps_executed += 1

            if not result.get("success"):
                err = f"Step {i+1} failed: {step.get('description', '?')} -- {result.get('description', '?')}"
                errors.append(err)
                logger.warning(err)
            else:
                logger.debug("Nav step %d OK: %s", i + 1, step.get("description", "")[:60])
            time.sleep(0.5)

        final_sig = state_signature_from_xml(self.controller.get_page_source() or "")
        success = len(errors) == 0 or steps_executed > len(errors)

        return {
            "success": success,
            "steps_executed": steps_executed,
            "total_steps": len(steps),
            "final_signature": final_sig,
            "errors": errors,
        }

    def execute_verification_script(self, script: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a full verification script: action steps + assertions.

        Returns: {success, result ("pass"/"fail"/"error"), steps_executed,
                  assertions_passed, assertions_failed, details, bugs}
        """
        name = script.get("name", "Unknown test")
        logger.info("Executing verification script: %s", name)

        # Phase 1: Execute action steps
        steps = script.get("steps", [])
        step_errors: List[str] = []

        for i, step in enumerate(steps):
            action = step.get("action", "")

            # Handle wait/sleep steps directly
            if action == "wait":
                wait_sec = step.get("duration", 1.5)
                try:
                    wait_sec = float(wait_sec)
                except (ValueError, TypeError):
                    wait_sec = 1.5
                wait_sec = min(wait_sec, 5.0)
                time.sleep(wait_sec)
                logger.debug("Verification step %d: waited %.1fs", i + 1, wait_sec)
                continue

            if action in ("skip", "noop", ""):
                continue

            # Re-capture UI before each step
            ui_ctx = self._capture_ui()
            result = self._execute_step_with_fallback(step, ui_ctx)

            if not result.get("success"):
                err = f"Step {i+1} failed: {step.get('description', '?')}"
                step_errors.append(err)
                logger.warning(err)
            else:
                logger.debug("Step %d OK: %s", i + 1, step.get("description", "")[:60])
            time.sleep(0.5)

        # Phase 2: Evaluate assertions
        assertions = script.get("assertions", [])
        passed = []
        failed = []
        bugs: List[Dict[str, Any]] = []

        # Capture final UI state for assertion checking
        ui_ctx = self._capture_ui()
        page_source = ui_ctx.get("page_source", "")
        all_acc = ui_ctx.get("accessibility_ids", [])
        all_res = ui_ctx.get("resource_ids", [])
        all_txt = ui_ctx.get("clickable_texts", [])

        for assertion in assertions:
            a_result = self._evaluate_assertion(
                assertion, page_source, all_acc, all_res, all_txt
            )
            if a_result["passed"]:
                passed.append(a_result)
                logger.info("  PASS: %s", assertion.get("description", "?"))
            else:
                failed.append(a_result)
                logger.warning("  FAIL: %s -- %s",
                               assertion.get("description", "?"), a_result.get("reason", ""))
                bugs.append({
                    "type": "assertion_failure",
                    "description": f"[{name}] {assertion.get('description', '?')}: {a_result.get('reason', '')}",
                    "severity": "medium",
                    "screenshot": ui_ctx.get("screenshot_path"),
                    "screen_signature": ui_ctx.get("state_signature"),
                })

        # If steps failed and no assertions could run, mark as error
        if step_errors and not assertions:
            result_str = "error"
        elif failed:
            result_str = "fail"
        else:
            result_str = "pass"

        overall_success = result_str == "pass"

        return {
            "success": overall_success,
            "result": result_str,
            "script_name": name,
            "steps_executed": len(steps),
            "step_errors": step_errors,
            "assertions_total": len(assertions),
            "assertions_passed": len(passed),
            "assertions_failed": len(failed),
            "passed_details": passed,
            "failed_details": failed,
            "bugs": bugs,
            "screenshot": ui_ctx.get("screenshot_path"),
            "final_signature": ui_ctx.get("state_signature"),
        }

    def run_feature_test(
        self,
        nav_script: Optional[Dict[str, Any]],
        verification_script: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Full test: navigate to target screen, then run verification.

        Steps:
        1. If nav_script provided, replay it first to reach the screen.
        2. Execute the verification script.
        3. Return combined result.
        """
        nav_result = None
        if nav_script:
            nav_result = self.execute_nav_script(nav_script)
            if not nav_result.get("success"):
                logger.warning("Navigation failed, attempting verification anyway")

        v_result = self.execute_verification_script(verification_script)
        v_result["nav_result"] = nav_result
        return v_result

    # ── Internal helpers ─────────────────────────────────────────────

    def _execute_step_with_fallback(
        self, step: Dict[str, Any], ui_ctx: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a step with smart fallback:
        1. If no locator_value → go straight to LLM resolution.
        2. Try direct execution with the given locator.
        3. If direct fails AND the step has a description → retry with
           LLM resolution against the *current* UI (handles popups/modals
           where new elements appeared after the previous action).
        """
        desc = step.get("description", "")

        # No locator provided → LLM must resolve from description
        if not step.get("locator_value") and desc:
            return self.navigator.execute_step(desc, ui_ctx)

        # Try direct execution first (fast path)
        result = self.navigator.execute_action_direct(step, ui_ctx)

        if result.get("success"):
            return result

        # Direct failed  --  if we have a description, let the LLM re-resolve
        # against the *current* screen (which may be a popup/overlay/modal).
        if desc:
            logger.info(
                "Direct action failed (%s)  --  retrying with LLM resolution: %s",
                result.get("description", "")[:50],
                desc[:60],
            )
            # Re-capture UI because the screen may have changed since the
            # caller captured it (e.g. previous step opened a popup).
            fresh_ui = self._capture_ui()
            retry_result = self.navigator.execute_step(desc, fresh_ui)
            if retry_result.get("success"):
                return retry_result
            # Both attempts failed  --  return the retry result for a better
            # error message (it saw the actual screen).
            return retry_result

        return result

    def _capture_ui(self) -> Dict[str, Any]:
        """Capture current UI state."""
        page_source = self.controller.get_page_source() or ""
        screenshot = self.controller.take_screenshot(f"script_exec_{int(time.time())}.png")
        acc_ids = extract_clickable_accessibility_ids(page_source)
        res_ids = extract_clickable_resource_ids(page_source)
        texts = extract_clickable_texts(page_source)
        sig = state_signature_from_xml(page_source)
        return {
            "page_source": page_source,
            "screenshot_path": screenshot,
            "accessibility_ids": acc_ids,
            "resource_ids": res_ids,
            "clickable_texts": texts,
            "state_signature": sig,
        }

    def _evaluate_assertion(
        self,
        assertion: Dict[str, Any],
        page_source: str,
        acc_ids: List[str],
        res_ids: List[str],
        texts: List[str],
    ) -> Dict[str, Any]:
        """
        Evaluate a single assertion against the current UI state.

        Supported types:
        - assert_visible: check element is present
        - assert_not_visible: check element is absent
        - assert_text: check element shows expected text
        - assert_count: check number of matching elements
        - assert_order: use LLM to verify ordering
        """
        a_type = assertion.get("type", "")
        locator_type = assertion.get("locator_type", "")
        locator_value = assertion.get("locator_value", "")
        expected = assertion.get("expected", "")
        description = assertion.get("description", "")

        try:
            if a_type == "assert_visible":
                found = self._element_present(locator_type, locator_value,
                                               acc_ids, res_ids, texts, page_source)
                if found:
                    return {"passed": True, "description": description}
                return {"passed": False, "description": description,
                        "reason": f"Element not visible: {locator_value}"}

            elif a_type == "assert_not_visible":
                found = self._element_present(locator_type, locator_value,
                                               acc_ids, res_ids, texts, page_source)
                if not found:
                    return {"passed": True, "description": description}
                return {"passed": False, "description": description,
                        "reason": f"Element should not be visible: {locator_value}"}

            elif a_type == "assert_text":
                actual = self._get_element_text(locator_type, locator_value, page_source)
                if actual and expected.lower() in actual.lower():
                    return {"passed": True, "description": description}
                return {"passed": False, "description": description,
                        "reason": f"Expected '{expected}', got '{actual or 'NOT FOUND'}'"}

            elif a_type == "assert_count":
                count = self._count_elements(locator_type, locator_value, page_source)
                try:
                    expected_int = int(expected)
                except (ValueError, TypeError):
                    expected_int = -1
                if count == expected_int:
                    return {"passed": True, "description": description}
                return {"passed": False, "description": description,
                        "reason": f"Expected count {expected}, got {count}"}

            elif a_type == "assert_order":
                # Use LLM to evaluate ordering from current screen
                return self._evaluate_order_assertion(assertion, page_source, acc_ids, texts)

            else:
                return {"passed": False, "description": description,
                        "reason": f"Unknown assertion type: {a_type}"}

        except Exception as e:
            return {"passed": False, "description": description,
                    "reason": f"Error evaluating assertion: {e}"}

    def _element_present(
        self, locator_type: str, locator_value: str,
        acc_ids: List[str], res_ids: List[str], texts: List[str],
        page_source: str,
    ) -> bool:
        """Check if an element is present on the current screen."""
        val_lower = locator_value.lower()
        if locator_type == "accessibility_id":
            return any(val_lower in a.lower() for a in acc_ids)
        elif locator_type == "resource_id":
            return any(val_lower in r.lower() for r in res_ids)
        elif locator_type == "text":
            return any(val_lower in t.lower() for t in texts)
        else:
            # Fallback: search page source
            return val_lower in page_source.lower()

    def _get_element_text(self, locator_type: str, locator_value: str,
                          page_source: str) -> Optional[str]:
        """Extract text content of an element from page source."""
        # Simple XML search for text attribute near the locator
        val = re.escape(locator_value)
        # Try content-desc (accessibility id)
        pattern = rf'content-desc="{val}"[^>]*text="([^"]*)"'
        match = re.search(pattern, page_source, re.IGNORECASE)
        if match:
            return match.group(1)
        # Try resource-id
        pattern = rf'resource-id="[^"]*{val}[^"]*"[^>]*text="([^"]*)"'
        match = re.search(pattern, page_source, re.IGNORECASE)
        if match:
            return match.group(1)
        # Try finding text attribute near any match of the value
        pattern = rf'{val}[^>]*text="([^"]*)"'
        match = re.search(pattern, page_source, re.IGNORECASE)
        if match:
            return match.group(1)
        # Try exact text match
        if locator_type == "text":
            return locator_value if locator_value.lower() in page_source.lower() else None
        return None

    def _count_elements(self, locator_type: str, locator_value: str,
                        page_source: str) -> int:
        """Count how many elements match the locator."""
        val = re.escape(locator_value)
        if locator_type == "accessibility_id":
            return len(re.findall(rf'content-desc="{val}"', page_source, re.IGNORECASE))
        elif locator_type == "resource_id":
            return len(re.findall(rf'resource-id="[^"]*{val}[^"]*"', page_source, re.IGNORECASE))
        elif locator_type == "text":
            return len(re.findall(rf'text="{val}"', page_source, re.IGNORECASE))
        return 0

    def _evaluate_order_assertion(
        self,
        assertion: Dict[str, Any],
        page_source: str,
        acc_ids: List[str],
        texts: List[str],
    ) -> Dict[str, Any]:
        """Use LLM to evaluate an ordering assertion."""
        description = assertion.get("description", "")
        expected = assertion.get("expected", "")

        # Extract all visible text items for the LLM to evaluate
        prompt = f"""Evaluate whether the following UI elements are in the correct order.

EXPECTED ORDER: {expected}
ASSERTION: {description}

VISIBLE ELEMENTS (in display order):
Accessibility IDs: {json.dumps(acc_ids[:30])}
Visible Texts: {json.dumps(texts[:30])}

Answer with a JSON object:
{{"passed": true/false, "reason": "<explanation>"}}

Only return the JSON, no explanation.
"""
        try:
            raw = self.ask_text(prompt)
            result = self.parse_json(raw)
            if isinstance(result, dict) and "passed" in result:
                result.setdefault("description", description)
                return result
        except Exception as e:
            logger.warning("LLM order assertion failed: %s", e)

        return {"passed": False, "description": description,
                "reason": "Could not evaluate ordering assertion"}
