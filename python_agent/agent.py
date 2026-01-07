from __future__ import annotations

import json
import random
import re
import time
from typing import Any, Dict, List, Optional

from .ui_extract import (
    extract_clickable_accessibility_ids,
    extract_clickable_resource_ids,
    extract_clickable_texts,
)

from . import adb, appium_server, config
from .appium_controller import AppiumController
from .memory import Memory, state_signature_from_xml
from .vlm import VLMQuotaExceeded, VLMUnavailable, get_vlm_response

class Agent:
    def __init__(self):
        self.appium_controller = AppiumController()
        self.memory = Memory()
        self.steps_taken = 0
        self.appium_process = None
        self.vlm_enabled = config.VLM_ENABLED

    def run(self):
        """Main loop for the agent."""
        # Start emulator (best-effort)
        if not adb.start_emulator(config.EMULATOR_AVD, target_device=config.ADB_TARGET_DEVICE):
            print("Emulator could not be started. Exiting.")
            return

        # Start Appium server (best-effort)
        try:
            self.appium_process = appium_server.start_appium_server(
                config.APPIUM_SERVER_URL, repo_root=config.REPO_ROOT, log_file=config.APPIUM_LOG_FILE
            )
        except Exception as exc:
            print(f"Could not start Appium server: {exc}")
            return

        self.appium_controller.start_driver()
        
        if not self.appium_controller.app_is_open:
            print("Failed to start the app. Exiting.")
            return

        while self.steps_taken < config.MAX_STEPS:
            print(f"\n--- Step {self.steps_taken + 1} ---")
            
            # 1. Fetch UI
            screenshot_path = self.appium_controller.take_screenshot(f"step_{self.steps_taken}.png")
            page_source = self.appium_controller.get_page_source()

            if not screenshot_path or not page_source:
                print("Could not get UI state. Exiting.")
                break

            state_sig = state_signature_from_xml(page_source)
            self.memory.add_state_signature(state_sig)

            # Loop breaker: same screen too many times
            if self.memory.count_recent_state(state_sig, window=10) >= config.MAX_SAME_STATE:
                print("Detected repeated screen state; attempting recovery.")
                if not self._recover_to_app():
                    print("Recovery failed; stopping.")
                    break
                # Refresh UI after recovery
                page_source = self.appium_controller.get_page_source()
                if not page_source:
                     break
                # Update sig for the refreshed page
                state_sig = state_signature_from_xml(page_source)
                self.memory.add_state_signature(state_sig)

            # 2. Process UI and Plan Action
            accessibility_ids = self._extract_clickable_accessibility_ids(page_source)
            resource_ids = self._extract_clickable_resource_ids(page_source)
            clickable_texts = self._extract_clickable_texts(page_source)
            
            # Plan action (VLM or Heuristic)
            action = self.plan_action(page_source, screenshot_path, accessibility_ids, resource_ids, clickable_texts)

            # 3. Execute Action
            if action:
                self.execute_action(action)
                self.memory.add_to_short_term(action, action.get("action_summary"))
            else:
                print("No action planned.")

            # 4. Detect Bugs
            self.detect_bugs(screenshot_path, page_source)

            self.steps_taken += 1
            time.sleep(2) # Wait a bit between steps

        self.appium_controller.stop_driver()
        appium_server.stop_appium_server(self.appium_process)
        print("\n--- Agent finished ---")

    def create_prompt(self, page_source: str, accessibility_ids: List[str]):
        """Creates a prompt for the VLM based on the current state."""
        history = self.memory.get_short_term_history()
        ids_block = "\n".join(f"- {x}" for x in accessibility_ids[:30])
        prompt = (
            "You are an expert mobile QA agent testing an Android app via Appium.\n"
            "Goal: find functional bugs and UI issues without leaving the app.\n\n"
            "Rules (guardrails):\n"
            "- Only interact with elements INSIDE the app.\n"
            "- Only choose element_id values from the provided Allowed accessibility IDs list.\n"
            "- Never press Home, open notifications, or use system UI.\n"
            "- Prefer exploring new screens; avoid repeating the same tap.\n\n"
            "Allowed accessibility IDs (subset):\n"
            f"{ids_block}\n\n"
            "Recent history:\n"
            f"{history}\n\n"
            "Return ONLY valid JSON with this schema:\n"
            "{\"action\": \"click\"|\"input\"|\"noop\", \"element_id\": string|null, \"text\": string|null, \"reason\": string}\n\n"
            "App UI XML (may be long):\n"
            f"{page_source[:8000]}\n"
        )
        return prompt

    def plan_action(
        self,
        page_source: str,
        screenshot_path: str,
        allowed_ids: List[str],
        resource_ids: List[str],
        clickable_texts: List[str],
    ):
        """Plans the next action using VLM or heuristic fallback."""
        if self.vlm_enabled:
            try:
                prompt = self.create_prompt(page_source, allowed_ids)
                vlm_response = get_vlm_response(screenshot_path, prompt)
                if vlm_response:
                    return self._parse_vlm_response(vlm_response, allowed_ids)
            except VLMQuotaExceeded:
                print("VLM quota exceeded. Disabling VLM for this session.")
                self.vlm_enabled = False
            except VLMUnavailable as e:
                print(f"VLM unavailable ({e}). Disabling VLM for this session.")
                self.vlm_enabled = False
            except Exception as e:
                print(f"Unexpected VLM error: {e}")

        # Fallback
        print("Using heuristic fallback for action planning.")
        return self._heuristic_action(allowed_ids, resource_ids, clickable_texts)

    def _parse_vlm_response(self, vlm_response: str, allowed_ids: List[str]):
        """Parses the VLM response to create an action plan."""
        try:
            # Clean the response to make it valid JSON
            clean_response = vlm_response.strip().replace("```json", "").replace("```", "")
            action_plan = json.loads(clean_response)
            if not isinstance(action_plan, dict):
                return None

            action = action_plan.get("action")
            element_id = action_plan.get("element_id")
            if action not in ("click", "input", "noop"):
                return None

            if action == "noop":
                action_plan["element_id"] = None
            else:
                if not element_id or element_id not in set(allowed_ids):
                    return None

            action_plan["action_summary"] = f"{action_plan.get('action')} on {action_plan.get('element_id')}"
            return action_plan
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Could not parse VLM response: {vlm_response}. Error: {e}")
            return None

    def _heuristic_action(
        self, allowed_ids: List[str], resource_ids: List[str], clickable_texts: List[str]
    ) -> Optional[Dict[str, Any]]:
        """A simple heuristic to explore the app without VLM."""
        # Prefer accessibility ids; fallback to resource-ids.
        targets: List[Dict[str, str]] = []
        for eid in allowed_ids:
            targets.append({"strategy": "accessibility_id", "value": eid})
        for rid in resource_ids:
            targets.append({"strategy": "id", "value": rid})
        for txt in clickable_texts:
            # Use UiSelector textContains to be a bit more resilient.
            safe = txt.replace('\\', '\\\\').replace('"', '\\"')
            targets.append({"strategy": "uiautomator", "value": f'new UiSelector().textContains("{safe}")'})

        if not targets:
            return {"action": "noop", "reason": "No clickable elements found to interact with.", "action_summary": "noop"}

        # Avoid re-clicking the last-clicked element
        history = self.memory.get_short_term_history(last_n=1)
        last_element_id = None
        
        if history:
            last_entry = history[0]
            action_data = last_entry.get("action", {})
            # Ensure it's a dict and has element_id
            if isinstance(action_data, dict):
                last_element_id = action_data.get("element_id")

        # Avoid re-clicking the last-clicked element_id when possible
        potential_targets = [t for t in targets if t["value"] != last_element_id]
        if not potential_targets:
            potential_targets = targets

        chosen = random.choice(potential_targets)
        element_id = chosen["value"]
        action = {
            "action": "click",
            "element_id": element_id,
            "locator_strategy": chosen["strategy"],
            "locator_value": chosen["value"],
            "text": None,
            "reason": "Heuristic: randomly selected a clickable element.",
            "action_summary": f"click on {element_id}",
        }
        return action

    def execute_action(self, action):
        """Executes the planned action using Appium."""
        action_type = action.get("action")
        # Handle noop
        if action_type == "noop":
            print(f"No-op: {action.get('reason')}")
            return

        locator_strategy = action.get("locator_strategy") or "accessibility_id"
        locator_value = action.get("locator_value") or action.get("element_id")
        text_to_input = action.get("text")

        if not self._ensure_in_app():
            print("Not in app; stopping.")
            self.steps_taken = config.MAX_STEPS
            return

        if not locator_value:
             print("Action requires an element_id, but none was provided.")
             return

        if locator_strategy == "accessibility_id":
            element = self.appium_controller.find_by_accessibility_id(locator_value)
        elif locator_strategy == "id":
            element = self.appium_controller.find_by_id(locator_value)
        elif locator_strategy == "uiautomator":
            element = self.appium_controller.find_by_android_uiautomator(locator_value)
        else:
            print(f"Unknown locator strategy: {locator_strategy}")
            return
        
        if not element:
            print(f"Element not found (strategy={locator_strategy}, value={locator_value}).")
            return

        if action_type == "click":
            print(f"Clicking on element: {locator_value}")
            self.appium_controller.click_element(element)
        elif action_type == "input" and text_to_input:
            print(f"Inputting '{text_to_input}' into element: {locator_value}")
            self.appium_controller.input_text(element, text_to_input)
        else:
            print(f"Unknown action type: {action_type}")

        # Post-action guardrail
        if not self._ensure_in_app():
            print("Action navigated outside app; recovering.")
            self._recover_to_app()

    def detect_bugs(self, screenshot_path: str, page_source: str):
        """Uses VLM to detect visual bugs on the screen."""
        # Quick functional heuristics
        if "has stopped" in (page_source or "").lower() or "keeps stopping" in (page_source or "").lower():
            self.memory.add_to_long_term("App crash dialog detected (text indicates 'has stopped').")
            print("Potential Crash Detected (page source).")
            return

        if not self.vlm_enabled:
            return

        prompt = (
            "You are a visual bug detector for a mobile app screenshot. "
            "Look for UI issues: overlapping elements, clipped text, misalignment, unreadable contrast, missing labels, broken layout. "
            "If you find a bug, output a short bug report with: Title, Steps (1-3), Expected, Actual, Severity. "
            "If none, output exactly: No bugs found"
        )
        try:
             bug_description = get_vlm_response(screenshot_path, prompt)
             if bug_description and "no bugs found" not in bug_description.lower():
                print(f"Potential Bug Found: {bug_description}")
                self.memory.add_to_long_term(bug_description)
        except (VLMQuotaExceeded, VLMUnavailable):
            print("VLM is not available for bug detection.")
            self.vlm_enabled = False
        except Exception as e:
            print(f"Error during bug detection: {e}")

    def _ensure_in_app(self) -> bool:
        if not self.appium_controller.driver:
            return False
        try:
            return self.appium_controller.driver.current_package == config.APP_PACKAGE
        except Exception:
            return False

    def _recover_to_app(self) -> bool:
        if not self.appium_controller.driver:
            return False
        try:
            self.appium_controller.driver.activate_app(config.APP_PACKAGE)
            return True
        except Exception:
            try:
                self.appium_controller.driver.start_activity(config.APP_PACKAGE, config.APP_ACTIVITY)
                return True
            except Exception:
                return False

    def _extract_clickable_accessibility_ids(self, page_source: str) -> List[str]:
        return extract_clickable_accessibility_ids(page_source)

    def _extract_clickable_resource_ids(self, page_source: str) -> List[str]:
        return extract_clickable_resource_ids(page_source)

    def _extract_clickable_texts(self, page_source: str) -> List[str]:
        return extract_clickable_texts(page_source)

if __name__ == "__main__":
    agent = Agent()
    agent.run()
