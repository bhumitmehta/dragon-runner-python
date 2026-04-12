"""
Navigator Agent  --  executes a single UI step on the device.

The Navigator is a pure *executor*: it receives a step description
(e.g. ``"click the Login button"``), resolves it to a concrete Appium
action, executes it, and reports the outcome.  It never decides *what*
to test  --  that is the Planner's job.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from ..logging_config import get_logger
from ..appium_controller import AppiumController

logger = get_logger("agents.navigator")
from ..ui_extract import (
    extract_clickable_accessibility_ids,
    extract_clickable_resource_ids,
    extract_clickable_texts,
    find_element_bounds,
)
from ..memory import state_signature_from_xml


class NavigatorAgent(BaseAgent):
    name = "navigator"
    system_role = (
        "You are a mobile UI navigator agent. "
        "Given a description of a UI action and the current screen elements, "
        "you produce the exact JSON command to execute. "
        "You must ONLY use element IDs that appear in the provided lists  --  "
        "never fabricate element identifiers."
    )

    def __init__(self, controller: AppiumController):
        super().__init__()
        self.controller = controller

    # ── Public interface ─────────────────────────────────────────────

    def get_ui_context(self, screenshot_name: str = "nav") -> Dict[str, Any]:
        """Capture the current screen state."""
        logger.debug("Capturing UI context: %s", screenshot_name)
        page_source = self.controller.get_page_source() or ""
        screenshot_path = self.controller.take_screenshot(f"{screenshot_name}.png")
        acc_ids = extract_clickable_accessibility_ids(page_source)
        res_ids = extract_clickable_resource_ids(page_source)
        texts = extract_clickable_texts(page_source)
        
        # Get current activity for semantic fingerprinting
        current_activity = self.controller.get_current_activity()
        state_sig = state_signature_from_xml(page_source, current_activity)
        
        return {
            "page_source": page_source,
            "screenshot_path": screenshot_path,
            "accessibility_ids": acc_ids,
            "resource_ids": res_ids,
            "clickable_texts": texts,
            "state_signature": state_sig,
            "current_activity": current_activity,  # Added for semantic fingerprinting
        }

    def execute_step(
        self,
        step_description: str,
        ui_context: Dict[str, Any],
        *,
        action_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Translate a high-level step description into an Appium action and run it.

        Returns a dict with keys:
            action, locator_value, success, description, bug_report,
            screenshot, state_signature_before, state_signature_after.
        """
        action_plan = self._resolve_action(step_description, ui_context, action_history)
        if action_plan is None:
            logger.warning("Could not resolve step to action: %s", step_description)
            return {
                "action": "unknown",
                "locator_value": None,
                "success": False,
                "description": "Could not resolve step to an action",
                "bug_report": None,
                "screenshot": ui_context.get("screenshot_path"),
                "state_signature_before": ui_context.get("state_signature"),
                "state_signature_after": ui_context.get("state_signature"),
            }

        result = self._do_action(action_plan, ui_context)
        logger.debug("Action result: success=%s desc=%s", result.get('success'), result.get('description', '')[:80])

        # Capture post-action state
        time.sleep(0.5)
        post_source = self.controller.get_page_source() or ""
        current_activity = self.controller.get_current_activity()
        result["state_signature_after"] = state_signature_from_xml(post_source, current_activity)
        result["state_signature_before"] = ui_context.get("state_signature")
        return result

    def execute_action_direct(
        self,
        action_plan: Dict[str, Any],
        ui_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a pre-resolved action dict directly, bypassing LLM resolution.

        Used by the Explorer agent which already knows exactly what action
        to perform (click, input, scroll, etc.) and doesn't need the LLM
        to re-resolve it.
        """
        result = self._do_action(action_plan, ui_context)
        logger.debug(
            "Direct action result: success=%s desc=%s",
            result.get("success"),
            result.get("description", "")[:80],
        )

        # Capture post-action state
        time.sleep(0.5)
        post_source = self.controller.get_page_source() or ""
        post_screenshot = self.controller.take_screenshot(f"post_{ui_context.get('state_signature', 'unknown')}.png")
        post_acc_ids = extract_clickable_accessibility_ids(post_source)
        post_res_ids = extract_clickable_resource_ids(post_source)
        post_texts = extract_clickable_texts(post_source)
        current_activity = self.controller.get_current_activity()
        result["state_signature_after"] = state_signature_from_xml(post_source, current_activity)
        result["post_screenshot_path"] = post_screenshot
        result["post_accessibility_ids"] = post_acc_ids
        result["post_resource_ids"] = post_res_ids
        result["post_clickable_texts"] = post_texts
        result["post_page_source"] = post_source
        result["state_signature_before"] = ui_context.get("state_signature")
        return result

    # ── Action resolution via LLM ────────────────────────────────────

    def _resolve_action(
        self,
        step_description: str,
        ui_context: Dict[str, Any],
        action_history: Optional[List[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        """Ask the LLM to resolve a step description into a concrete action."""
        acc = json.dumps(ui_context.get("accessibility_ids", [])[:30])
        res = json.dumps(ui_context.get("resource_ids", [])[:20])
        txt = json.dumps(ui_context.get("clickable_texts", [])[:20])

        history_str = self.format_action_history(action_history or [])

        prompt = f"""Resolve this test step into a concrete UI action.

STEP TO EXECUTE: {step_description}

AVAILABLE UI ELEMENTS:
Accessibility IDs: {acc}
Resource IDs: {res}
Clickable Texts: {txt}

RECENT ACTIONS:
{history_str}

RULES:
1. ONLY use IDs from the lists above  --  never guess or fabricate.
2. If the step cannot be executed (element not found), return action "skip" with a reason.
3. For long press actions, use "long_press" action type.
4. If you need to scroll to find an element, use "scroll" with direction first.
5. For text input, always specify both locator_value AND text. Generate realistic test data appropriate for the field type (e.g., valid email for email fields, phone numbers for phone fields, names for name fields, addresses for address fields).

Return ONLY valid JSON (no markdown):
{{
    "action": "click" | "input" | "scroll" | "back" | "hide_keyboard" | "press_enter" | "skip" | "assert" | "long_press",
    "locator_type": "accessibility_id" | "resource_id" | "text" | null,
    "locator_value": "<exact ID from list>" | null,
    "text": "<text for input>" | null,
    "direction": "up" | "down" | "left" | "right" | null,
    "reason": "<why this action matches the step>",
    "bug_report": "<any bug noticed>" | null
}}"""

        # Try vision (with per-screen cache) if screenshot available
        screenshot = ui_context.get("screenshot_path")
        state_sig = ui_context.get("state_signature")
        if screenshot:
            raw = self.ask_vision_cached(screenshot, prompt, state_sig=state_sig)
        else:
            raw = self.ask_text(prompt)

        return self.parse_json_strict(raw, ["action"])

    # ── Low-level execution ──────────────────────────────────────────

    def _do_action(self, plan: Dict[str, Any], ui_context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a resolved action plan on the device via Appium."""
        action = plan.get("action", "")
        locator_type = plan.get("locator_type")
        locator_value = plan.get("locator_value")
        text = plan.get("text")
        direction = plan.get("direction")
        reason = plan.get("reason", "")
        bug_report = plan.get("bug_report")
        # Pre-computed coordinates from explorer (input fields)
        plan_cx = plan.get("cx")
        plan_cy = plan.get("cy")

        result: Dict[str, Any] = {
            "action": action,
            "locator_value": locator_value,
            "success": False,
            "description": reason,
            "bug_report": bug_report,
            "screenshot": ui_context.get("screenshot_path"),
        }

        try:
            if action == "click":
                element = self._find_element(locator_type, locator_value)
                if not element:
                    # Try scrolling to find the element
                    element = self._scroll_and_find(locator_type, locator_value)
                if element:
                    element.click()
                    result["success"] = True
                    result["description"] = f"Clicked {locator_value}"
                else:
                    # Coordinate fallback: extract bounds from XML and tap
                    page_src = ui_context.get("page_source", "")
                    coords = find_element_bounds(page_src, locator_type or "resource_id", locator_value or "")
                    if coords:
                        cx, cy = coords
                        ok = self.controller.tap_at(cx, cy)
                        if ok:
                            result["success"] = True
                            result["description"] = f"Clicked {locator_value} at ({cx},{cy})"
                        else:
                            result["description"] = f"Tap failed at ({cx},{cy}) for {locator_value}"
                    else:
                        result["description"] = f"Element not found: {locator_value}"

            elif action == "input":
                element = self._find_element(locator_type, locator_value)
                if not element:
                    # Try scrolling to find the element
                    element = self._scroll_and_find(locator_type, locator_value)
                if element and text:
                    input_ok = self._safe_input(element, text)
                    if input_ok:
                        result["success"] = True
                        result["description"] = f"Input '{text}' into {locator_value}"
                    else:
                        result["description"] = f"Could not input text into {locator_value}"
                elif not text:
                    result["description"] = "No text specified for input action"
                else:
                    # Coordinate fallback: try plan-supplied coords, then XML bounds
                    cx, cy = plan_cx, plan_cy
                    if not (cx and cy):
                        page_src = ui_context.get("page_source", "")
                        coords = find_element_bounds(page_src, locator_type or "resource_id", locator_value or "")
                        if coords:
                            cx, cy = coords
                    if cx and cy and text:
                        ok = self.controller.type_at_coordinates(cx, cy, text)
                        if ok:
                            result["success"] = True
                            result["description"] = f"Input '{text}' at ({cx},{cy}) for {locator_value}"
                        else:
                            result["description"] = f"Coordinate input failed at ({cx},{cy}) for {locator_value}"
                    else:
                        result["description"] = f"Input element not found: {locator_value}"

            elif action == "scroll":
                if direction:
                    ok = self.controller.scroll(direction)
                    result["success"] = ok if ok is not None else True
                    result["description"] = f"Scrolled {direction}"
                else:
                    result["description"] = "No scroll direction specified"

            elif action == "long_press":
                element = self._find_element(locator_type, locator_value)
                if not element:
                    element = self._scroll_and_find(locator_type, locator_value)
                if element:
                    ok = self.controller.long_press(element=element)
                    result["success"] = ok
                    result["description"] = f"Long pressed {locator_value}"
                else:
                    result["description"] = f"Element not found for long press: {locator_value}"

            elif action == "back":
                self.controller.press_back()
                result["success"] = True
                result["description"] = "Pressed back"

            elif action == "hide_keyboard":
                self.controller.hide_keyboard()
                result["success"] = True
                result["description"] = "Hide keyboard"

            elif action == "press_enter":
                self.controller.press_enter()
                result["success"] = True
                result["description"] = "Pressed enter"

            elif action == "skip":
                result["success"] = True
                result["description"] = f"Skipped: {reason}"

            elif action == "assert":
                # Assertions are validated by the Critic  --  just mark ok here
                result["success"] = True
                result["description"] = f"Assertion: {reason}"

            elif action in ("assert_visible", "assert_not_visible", "assert_text",
                           "assert_order", "assert_count"):
                # These are assertion types mistakenly placed in action steps.
                # Just mark as success; actual assertions are evaluated separately.
                result["success"] = True
                result["description"] = f"Assertion passthrough: {reason or locator_value}"

            elif action in ("wait", "noop"):
                # Wait or no-op  --  just sleep briefly
                result["success"] = True
                result["description"] = "Waited"
                time.sleep(1.0)

            else:
                result["description"] = f"Unknown action: {action}"

        except Exception as e:
            result["description"] = f"Error: {e}"
            logger.error("Action execution error: %s", e, exc_info=True)

        return result

    def _safe_input(self, element, text: str) -> bool:
        """Try multiple strategies to input text into an element."""
        # Strategy 1: click + clear + send_keys
        try:
            element.click()
            time.sleep(0.2)
            element.clear()
            element.send_keys(text)
            self.controller.hide_keyboard()
            return True
        except Exception:
            pass

        # Strategy 2: clear with empty send_keys then type
        try:
            element.send_keys("")
            element.clear()
            element.send_keys(text)
            self.controller.hide_keyboard()
            return True
        except Exception:
            pass

        # Strategy 3: Use set_value (UiAutomator2 specific)
        try:
            element.set_value(text)
            self.controller.hide_keyboard()
            return True
        except Exception:
            pass

        # Strategy 4: Tap coordinates + send_keys
        try:
            loc = element.location
            sz = element.size
            cx = loc['x'] + sz['width'] // 2
            cy = loc['y'] + sz['height'] // 2
            self.controller.driver.tap([(cx, cy)], 100)
            time.sleep(0.2)
            element.send_keys(text)
            self.controller.hide_keyboard()
            return True
        except Exception:
            pass

        logger.warning("All input strategies failed for element")
        return False

    def _scroll_and_find(self, locator_type, locator_value):
        """Scroll down up to 3 times to find an element not currently visible."""
        if not locator_value:
            return None
        # Try UiScrollable for text-based locators
        if locator_type == "text":
            el = self.controller.scroll_to_text(locator_value)
            if el:
                return el
        # Try scrolling down to find by any locator
        for _ in range(3):
            self.controller.scroll("down")
            time.sleep(0.3)
            el = self._find_element(locator_type, locator_value)
            if el:
                return el
        return None

    # ── Element lookup ───────────────────────────────────────────────

    def _find_element(self, locator_type: Optional[str], value: Optional[str]):
        if not locator_type or not value:
            return None
        if locator_type == "accessibility_id":
            return self.controller.find_by_accessibility_id(value)
        elif locator_type == "resource_id":
            return self.controller.find_by_id(value)
        elif locator_type == "text":
            safe = value.replace('"', '\\"')
            return self.controller.find_by_android_uiautomator(
                f'new UiSelector().text("{safe}")'
            )
        return None
