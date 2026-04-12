"""
AI-powered testing agent that can:
1. Explore the app autonomously and find bugs
2. Execute natural language commands from users
3. Generate and run dynamic test scenarios
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import adb, appium_server, config
from .appium_controller import AppiumController
from .memory import state_signature_from_xml
from .semantic_fingerprint import semantic_screen_fingerprint
from .ui_extract import (
    extract_clickable_accessibility_ids,
    extract_clickable_resource_ids,
    extract_clickable_texts,
)
from .vlm import VLMQuotaExceeded, VLMUnavailable, get_vlm_response, get_text_response
from .bug_localization.integration import (
    BugLocalizationIntegration,
    create_bug_report_from_detection,
)


@dataclass
class TestResult:
    """Result of an AI-driven test action."""
    action: str
    success: bool
    description: str
    screenshot: Optional[str] = None
    bug_found: Optional[Dict[str, Any]] = None


@dataclass
class ExplorationSession:
    """Tracks an AI exploration session."""
    session_id: str
    started_at: str
    mode: str  # "explore" | "task" | "auto_test"
    user_task: Optional[str] = None
    actions_taken: List[Dict[str, Any]] = field(default_factory=list)
    bugs_found: List[Dict[str, Any]] = field(default_factory=list)
    screens_visited: List[str] = field(default_factory=list)
    test_coverage: Dict[str, bool] = field(default_factory=dict)


class AITester:
    """
    An AI-powered testing agent that uses LLM to:
    - Understand natural language commands
    - Dynamically explore and test the application
    - Generate test scenarios on the fly
    - Find bugs through intelligent exploration
    """

    def __init__(self, *, source_code_dir: Optional[str] = None, localize_bugs: Optional[bool] = None):
        self.controller = AppiumController()
        self.appium_process = None
        self.session: Optional[ExplorationSession] = None
        self.vlm_enabled = config.VLM_ENABLED

        # Bug localization
        self.localize_bugs = localize_bugs if localize_bugs is not None else config.BUG_LOCALIZATION_ENABLED
        src_dir = source_code_dir or (str(config.SOURCE_CODE_DIR) if config.SOURCE_CODE_DIR else None)
        self.bug_integration: Optional[BugLocalizationIntegration] = None
        if self.localize_bugs and src_dir:
            self.bug_integration = BugLocalizationIntegration(
                source_code_dir=src_dir,
                file_extensions=config.SOURCE_CODE_EXTENSIONS,
            )

    def _start_session(self, mode: str, user_task: Optional[str] = None) -> ExplorationSession:
        """Initialize a new testing session."""
        session_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        self.session = ExplorationSession(
            session_id=session_id,
            started_at=datetime.utcnow().isoformat() + "Z",
            mode=mode,
            user_task=user_task,
        )
        # Start bug localization trace
        if self.bug_integration:
            self.bug_integration.start_trace()
        return self.session

    def _get_ui_context(self) -> Dict[str, Any]:
        """Get the current UI state and available elements."""
        page_source = self.controller.get_page_source() or ""
        screenshot_path = self.controller.take_screenshot(
            f"ai_test_{len(self.session.actions_taken):03d}.png"
        )
        
        acc_ids = extract_clickable_accessibility_ids(page_source)
        res_ids = extract_clickable_resource_ids(page_source)
        texts = extract_clickable_texts(page_source)
        
        # Get activity name for semantic fingerprinting
        activity = ""
        try:
            activity = self.controller.get_current_activity() or ""
        except Exception:
            pass
        
        # Use semantic fingerprinting for robust screen identity
        state_sig = state_signature_from_xml(page_source, activity)
        semantic_fp = semantic_screen_fingerprint(page_source, activity)

        return {
            "page_source": page_source,
            "screenshot_path": screenshot_path,
            "accessibility_ids": acc_ids,
            "resource_ids": res_ids,
            "clickable_texts": texts,
            "state_signature": state_sig,
            "activity": activity,
            "semantic_fingerprint": semantic_fp,
        }

    def _create_action_prompt(self, ui_context: Dict[str, Any], goal: str) -> str:
        """Create a prompt for the LLM to decide the next action."""
        acc_ids = ui_context["accessibility_ids"][:30]
        res_ids = ui_context["resource_ids"][:20]
        texts = ui_context["clickable_texts"][:20]
        
        recent_actions = self.session.actions_taken[-5:] if self.session else []
        history_str = "\n".join([
            f"  - {a.get('action', 'unknown')}: {a.get('summary', '')}" 
            for a in recent_actions
        ]) or "  (no actions yet)"

        prompt = f"""You are an AI mobile app tester. Your goal: {goal}

CURRENT UI ELEMENTS (use ONLY these exact IDs):
Accessibility IDs: {json.dumps(acc_ids)}
Resource IDs: {json.dumps(res_ids)}
Clickable Texts: {json.dumps(texts)}

RECENT ACTIONS:
{history_str}

RULES:
1. Only use element IDs from the lists above
2. For "click" action, use accessibility_id, resource_id, or text locator
3. For "input" action, specify the element and text to type
4. For "scroll" action, specify direction (up/down/left/right)
5. Use "done" when the goal is achieved
6. Use "explore" to discover new screens
7. Report any bugs or issues you notice

KEYBOARD HANDLING (IMPORTANT):
- After typing in a text field, the keyboard stays open and may cover UI elements
- Use "hide_keyboard" action to dismiss the keyboard before clicking other elements
- Use "press_enter" action to move to the next input field (like pressing Next on keyboard)
- If elements seem missing or unclickable, the keyboard might be covering them - hide it first

Return ONLY valid JSON:
{{
    "action": "click" | "input" | "scroll" | "back" | "explore" | "done" | "hide_keyboard" | "press_enter",
    "locator_type": "accessibility_id" | "resource_id" | "text" | null,
    "locator_value": "<exact value from list>" | null,
    "text": "<text to input>" | null,
    "direction": "up" | "down" | "left" | "right" | null,
    "reason": "<why this action>",
    "bug_report": "<describe any bug noticed>" | null,
    "goal_progress": "<how this helps achieve the goal>"
}}"""
        return prompt

    def _create_exploration_prompt(self, ui_context: Dict[str, Any]) -> str:
        """Create a prompt for autonomous exploration."""
        return self._create_action_prompt(
            ui_context,
            "Explore the app thoroughly to find bugs. Visit all screens, test all features, look for UI issues, crashes, and unexpected behavior. Prioritize untested areas."
        )

    def _create_test_generation_prompt(self, ui_context: Dict[str, Any]) -> str:
        """Create a prompt for generating test scenarios."""
        acc_ids = ui_context["accessibility_ids"]
        page_xml = ui_context["page_source"][:5000]
        
        screens_visited = list(set(self.session.screens_visited)) if self.session else []

        prompt = f"""You are an AI test engineer analyzing a mobile app.

CURRENT SCREEN ELEMENTS:
{json.dumps(acc_ids[:40])}

SCREENS ALREADY VISITED: {len(screens_visited)}

Analyze this screen and generate test scenarios. Consider:
1. What user flows start from this screen?
2. What edge cases should be tested?
3. What validation/error scenarios exist?
4. What accessibility concerns are there?

Return a JSON array of test scenarios:
[
    {{
        "name": "<test name>",
        "description": "<what this tests>",
        "priority": "high" | "medium" | "low",
        "steps": [
            {{"action": "click", "locator": "<id>", "note": "<purpose>"}},
            {{"action": "input", "locator": "<id>", "text": "<value>", "note": "<purpose>"}},
            {{"action": "assert", "check": "<what to verify>"}},
            ...
        ]
    }},
    ...
]

Generate 3-5 relevant test scenarios for this screen."""
        return prompt

    def _parse_action_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse the LLM's action response."""
        try:
            clean = response.strip()
            # Remove markdown code blocks if present
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0]
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0]
            
            return json.loads(clean)
        except (json.JSONDecodeError, IndexError) as e:
            print(f"Failed to parse LLM response: {e}")
            return None

    def _execute_action(self, action_plan: Dict[str, Any], ui_context: Dict[str, Any]) -> TestResult:
        """Execute an action planned by the AI."""
        action = action_plan.get("action", "")
        locator_type = action_plan.get("locator_type")
        locator_value = action_plan.get("locator_value")
        text = action_plan.get("text")
        direction = action_plan.get("direction")
        reason = action_plan.get("reason", "")
        bug_report = action_plan.get("bug_report")

        print(f"  AI Action: {action} - {reason}")

        result = TestResult(
            action=action,
            success=False,
            description=reason,
            screenshot=ui_context.get("screenshot_path"),
        )

        try:
            if action == "click":
                element = self._find_element(locator_type, locator_value)
                if element:
                    element.click()
                    result.success = True
                    result.description = f"Clicked {locator_value}"
                else:
                    result.description = f"Element not found: {locator_value}"

            elif action == "input":
                element = self._find_element(locator_type, locator_value)
                if element and text:
                    try:
                        element.click()
                        element.clear()
                    except:
                        pass
                    element.send_keys(text)
                    # Auto-hide keyboard after input to prevent UI obstruction
                    import time
                    time.sleep(0.3)
                    self.controller.hide_keyboard()
                    result.success = True
                    result.description = f"Input '{text}' into {locator_value}"
                else:
                    result.description = f"Could not input text"

            elif action == "scroll":
                if direction:
                    self.controller.scroll(direction)
                    result.success = True
                    result.description = f"Scrolled {direction}"

            elif action == "back":
                if self.controller.driver:
                    self.controller.driver.back()
                    result.success = True
                    result.description = "Pressed back button"

            elif action == "hide_keyboard":
                if self.controller.hide_keyboard():
                    result.success = True
                    result.description = "Keyboard hidden"
                else:
                    result.success = True  # Not a failure if keyboard wasn't shown
                    result.description = "Keyboard was not visible"

            elif action == "press_enter":
                if self.controller.press_enter():
                    result.success = True
                    result.description = "Pressed Enter/Next key"
                else:
                    result.description = "Failed to press Enter key"

            elif action == "explore":
                # AI decided to explore - pick a random unexplored element
                result.success = True
                result.description = "Exploration mode"

            elif action == "done":
                result.success = True
                result.description = "Goal achieved"

            else:
                result.description = f"Unknown action: {action}"

        except Exception as e:
            result.description = f"Error: {str(e)}"

        # Record bug if AI noticed one
        if bug_report:
            bug = {
                "type": "ai_detected",
                "description": bug_report,
                "screenshot": ui_context.get("screenshot_path"),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            # Run bug localization if enabled
            if self.bug_integration:
                analysis = self.bug_integration.analyze_detected_bug(
                    bug_report=bug_report,
                    page_source=ui_context.get("page_source"),
                    screenshot_path=ui_context.get("screenshot_path"),
                )
                bug["localization"] = analysis.get("localization", {})
                top_files = analysis.get("localization", {}).get("top_files", [])
                if top_files:
                    print(f"  Bug localized to: {top_files[0]['path']} (score={top_files[0]['score']:.4f})")
            result.bug_found = bug
            if self.session:
                self.session.bugs_found.append(bug)

        # Record action in session
        action_record = {
            "action": action,
            "locator": locator_value,
            "summary": result.description,
            "success": result.success,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        if self.session:
            self.session.actions_taken.append(action_record)

        # Track step in bug localization trace
        if self.bug_integration:
            self.bug_integration.add_trace_step(
                action=action_record,
                ui_state={
                    "accessibility_ids": ui_context.get("accessibility_ids", []),
                    "resource_ids": ui_context.get("resource_ids", []),
                    "state_signature": ui_context.get("state_signature", ""),
                },
                screenshot_path=ui_context.get("screenshot_path"),
            )

        return result

    def _find_element(self, locator_type: Optional[str], value: Optional[str]):
        """Find an element using the specified locator strategy."""
        if not locator_type or not value:
            return None
        
        if locator_type == "accessibility_id":
            return self.controller.find_by_accessibility_id(value)
        elif locator_type == "resource_id":
            return self.controller.find_by_id(value)
        elif locator_type == "text":
            # Use UiAutomator for text-based lookup
            safe_value = value.replace('"', '\\"')
            return self.controller.find_by_android_uiautomator(
                f'new UiSelector().text("{safe_value}")'
            )
        return None

    def _setup(self) -> bool:
        """Setup emulator, Appium, and driver."""
        print("Setting up AI Tester...")
        
        if not adb.start_emulator(config.EMULATOR_AVD, target_device=config.ADB_TARGET_DEVICE):
            print("Emulator could not be started.")
            return False

        try:
            self.appium_process = appium_server.start_appium_server(
                config.APPIUM_SERVER_URL,
                repo_root=config.REPO_ROOT,
                log_file=config.APPIUM_LOG_FILE
            )
        except Exception as e:
            print(f"Could not start Appium: {e}")
            return False

        self.controller.start_driver()
        if not self.controller.app_is_open:
            print("Failed to start the app.")
            return False

        return True

    def _teardown(self):
        """Clean up resources."""
        try:
            self.controller.stop_driver()
        finally:
            try:
                appium_server.stop_appium_server(self.appium_process)
            except:
                pass

    def _save_session_report(self) -> Path:
        """Save the session report to a JSON file."""
        if not self.session:
            return None

        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = config.REPORTS_DIR / f"ai_session_{self.session.session_id}.json"

        # End bug localization trace
        if self.bug_integration:
            self.bug_integration.end_trace()

        report = {
            "session_id": self.session.session_id,
            "started_at": self.session.started_at,
            "finished_at": datetime.utcnow().isoformat() + "Z",
            "mode": self.session.mode,
            "user_task": self.session.user_task,
            "total_actions": len(self.session.actions_taken),
            "bugs_found": len(self.session.bugs_found),
            "screens_visited": len(set(self.session.screens_visited)),
            "actions": self.session.actions_taken,
            "bugs": self.session.bugs_found,
        }

        # Include bug localization report if available
        if self.bug_integration and self.bug_integration.localization_results:
            report["bug_localization"] = {
                "source_code_dir": self.bug_integration.source_code_dir,
                "bugs_analyzed": len(self.bug_integration.localization_results),
                "localizations": self.bug_integration.localization_results,
            }

        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        # Save execution trace for later analysis
        if self.bug_integration:
            config.TRACES_DIR.mkdir(parents=True, exist_ok=True)
            trace_path = config.TRACES_DIR / f"trace_{self.session.session_id}.json"
            self.bug_integration.save_trace(str(trace_path))

        return report_path

    # ========================
    # PUBLIC INTERFACE
    # ========================

    def execute_task(self, task: str, max_steps: int = 20) -> Path:
        """
        Execute a natural language task.
        
        Example tasks:
        - "Login with username bob@example.com and password 10203040"
        - "Add the first product to the cart"
        - "Sort products by price and take a screenshot"
        - "Navigate to the webview section"
        """
        print(f"\n{'='*60}")
        print(f"AI TESTER - Executing Task")
        print(f"Task: {task}")
        print(f"{'='*60}\n")

        if not self._setup():
            return None

        self._start_session("task", user_task=task)

        try:
            for step in range(max_steps):
                print(f"\n--- Step {step + 1}/{max_steps} ---")
                
                ui_context = self._get_ui_context()
                self.session.screens_visited.append(ui_context["state_signature"])

                # Ask LLM what to do
                prompt = self._create_action_prompt(ui_context, f"Complete this task: {task}")
                
                try:
                    response = get_vlm_response(ui_context["screenshot_path"], prompt)
                    action_plan = self._parse_action_response(response)
                except (VLMQuotaExceeded, VLMUnavailable) as e:
                    print(f"VLM unavailable: {e}")
                    break

                if not action_plan:
                    print("Could not parse action plan")
                    continue

                # Check if done
                if action_plan.get("action") == "done":
                    print(f"\n✅ Task completed: {action_plan.get('reason', '')}")
                    break

                # Execute the action
                result = self._execute_action(action_plan, ui_context)
                print(f"  Result: {'✓' if result.success else '✗'} {result.description}")

                time.sleep(1)

        finally:
            report_path = self._save_session_report()
            self._teardown()

        print(f"\nSession report saved to: {report_path}")
        return report_path

    def explore(self, max_steps: int = 50) -> Path:
        """
        Autonomously explore the app to find bugs.
        The AI will visit different screens, try various interactions,
        and report any issues it finds.
        """
        print(f"\n{'='*60}")
        print(f"AI TESTER - Autonomous Exploration Mode")
        print(f"Max Steps: {max_steps}")
        print(f"{'='*60}\n")

        if not self._setup():
            return None

        self._start_session("explore")

        try:
            for step in range(max_steps):
                print(f"\n--- Exploration Step {step + 1}/{max_steps} ---")
                
                ui_context = self._get_ui_context()
                self.session.screens_visited.append(ui_context["state_signature"])

                # Ask LLM to explore
                prompt = self._create_exploration_prompt(ui_context)
                
                try:
                    response = get_vlm_response(ui_context["screenshot_path"], prompt)
                    action_plan = self._parse_action_response(response)
                except (VLMQuotaExceeded, VLMUnavailable) as e:
                    print(f"VLM unavailable: {e}")
                    break

                if not action_plan:
                    print("Could not parse action plan, using heuristic")
                    # Fallback: click a random element
                    if ui_context["accessibility_ids"]:
                        import random
                        action_plan = {
                            "action": "click",
                            "locator_type": "accessibility_id",
                            "locator_value": random.choice(ui_context["accessibility_ids"]),
                            "reason": "Heuristic exploration",
                        }
                    else:
                        continue

                # Execute the action
                result = self._execute_action(action_plan, ui_context)
                print(f"  Result: {'✓' if result.success else '✗'} {result.description}")
                
                if result.bug_found:
                    print(f"  🐛 BUG FOUND: {result.bug_found.get('description', '')}")

                time.sleep(1)

        finally:
            report_path = self._save_session_report()
            self._teardown()

        print(f"\n{'='*60}")
        print(f"Exploration Complete!")
        print(f"Actions taken: {len(self.session.actions_taken)}")
        print(f"Bugs found: {len(self.session.bugs_found)}")
        print(f"Unique screens: {len(set(self.session.screens_visited))}")
        if self.bug_integration and self.bug_integration.localization_results:
            print(f"Bugs localized: {len(self.bug_integration.localization_results)}")
        print(f"Report: {report_path}")
        print(f"{'='*60}\n")

        return report_path

    def generate_tests(self) -> List[Dict[str, Any]]:
        """
        Analyze the app and generate test scenarios dynamically.
        Returns a list of test scenarios that can be saved to a workflow file.
        """
        print(f"\n{'='*60}")
        print(f"AI TESTER - Generating Test Scenarios")
        print(f"{'='*60}\n")

        if not self._setup():
            return []

        self._start_session("auto_test")
        all_scenarios = []

        try:
            screens_to_visit = ["home"]
            visited = set()

            while screens_to_visit and len(all_scenarios) < 20:
                current_screen = screens_to_visit.pop(0)
                
                ui_context = self._get_ui_context()
                state_sig = ui_context["state_signature"]
                
                if state_sig in visited:
                    continue
                visited.add(state_sig)

                print(f"\nAnalyzing screen ({len(visited)} visited)...")
                
                # Generate tests for this screen
                prompt = self._create_test_generation_prompt(ui_context)
                
                try:
                    response = get_text_response(prompt)
                    scenarios = self._parse_test_scenarios(response)
                    if scenarios:
                        all_scenarios.extend(scenarios)
                        print(f"  Generated {len(scenarios)} test scenarios")
                except (VLMQuotaExceeded, VLMUnavailable) as e:
                    print(f"VLM unavailable: {e}")
                    break

                # Navigate to discover more screens
                for acc_id in ui_context["accessibility_ids"][:5]:
                    if "menu" in acc_id.lower() or "button" in acc_id.lower():
                        element = self.controller.find_by_accessibility_id(acc_id)
                        if element:
                            try:
                                element.click()
                                time.sleep(1)
                                screens_to_visit.append(acc_id)
                            except:
                                pass
                            # Go back to explore more
                            self.controller.reset_app()
                            time.sleep(1)
                            break

        finally:
            self._teardown()

        print(f"\nGenerated {len(all_scenarios)} total test scenarios")
        return all_scenarios

    def _parse_test_scenarios(self, response: str) -> List[Dict[str, Any]]:
        """Parse test scenarios from LLM response."""
        try:
            clean = response.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0]
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0]
            
            scenarios = json.loads(clean)
            if isinstance(scenarios, list):
                return scenarios
            return []
        except (json.JSONDecodeError, IndexError):
            return []

    def interactive_mode(self):
        """
        Start an interactive session where the user can give commands in natural language.
        """
        print(f"\n{'='*60}")
        print(f"AI TESTER - Interactive Mode")
        print(f"Type commands in natural language or 'quit' to exit")
        print(f"Examples:")
        print(f"  - 'click on the menu'")
        print(f"  - 'scroll down'")
        print(f"  - 'type hello in the search box'")
        print(f"  - 'go back'")
        print(f"  - 'what do you see on screen?'")
        print(f"{'='*60}\n")

        if not self._setup():
            return

        self._start_session("interactive")

        try:
            while True:
                user_input = input("\n🤖 Your command: ").strip()
                
                if user_input.lower() in ("quit", "exit", "q"):
                    print("Ending interactive session...")
                    break

                if not user_input:
                    continue

                ui_context = self._get_ui_context()

                # Special command: describe screen
                if "what do you see" in user_input.lower() or "describe" in user_input.lower():
                    print(f"\n📱 Current Screen:")
                    print(f"  Clickable elements: {len(ui_context['accessibility_ids'])}")
                    print(f"  Available actions:")
                    for aid in ui_context['accessibility_ids'][:10]:
                        print(f"    - {aid}")
                    continue

                # Ask LLM to interpret the command
                prompt = self._create_action_prompt(ui_context, f"Execute this user command: {user_input}")
                
                try:
                    response = get_vlm_response(ui_context["screenshot_path"], prompt)
                    action_plan = self._parse_action_response(response)
                except (VLMQuotaExceeded, VLMUnavailable) as e:
                    print(f"❌ VLM unavailable: {e}")
                    continue

                if not action_plan:
                    print("❌ Could not understand the command. Try rephrasing.")
                    continue

                result = self._execute_action(action_plan, ui_context)
                print(f"{'✅' if result.success else '❌'} {result.description}")
                
                if result.bug_found:
                    print(f"🐛 Bug noticed: {result.bug_found.get('description', '')}")

                time.sleep(1)

        finally:
            report_path = self._save_session_report()
            self._teardown()

        print(f"\nSession report: {report_path}")
