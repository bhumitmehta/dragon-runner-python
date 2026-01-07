from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import adb, appium_server, config
from .appium_controller import AppiumController
from .memory import state_signature_from_xml
from .navigation_memory import NavigationMemory
from .vlm import VLMQuotaExceeded, VLMUnavailable, get_vlm_response
from .ui_extract import (
    extract_clickable_accessibility_ids,
    extract_clickable_resource_ids,
    extract_clickable_texts,
)
from .workflow_spec import WorkflowFile, WorkflowStep, substitute_vars


def _utc_run_id() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


@dataclass
class StepResult:
    index: int
    action: str
    status: str  # passed|failed|skipped
    summary: str
    error: Optional[str] = None
    screenshot: Optional[str] = None
    state_signature: Optional[str] = None
    note: Optional[str] = None


class WorkflowRunner:
    def __init__(self, *, use_vision: bool = False):
        self.controller = AppiumController()
        self.appium_process = None
        self.use_vision = use_vision and config.VLM_ENABLED
        self.vision_enabled_session = self.use_vision

        self.nav_memory = NavigationMemory.load(config.NAVIGATION_MEMORY_FILE)

    def run_file(self, workflow_path: str | Path, *, out_path: Optional[str | Path] = None) -> Path:
        wf = WorkflowFile.load(workflow_path)
        run_id = _utc_run_id()

        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        if out_path is None:
            out_path = config.REPORTS_DIR / f"workflow_report_{run_id}.json"
        out_path = Path(out_path)

        report: Dict[str, Any] = {
            "run_id": run_id,
            "started_at": _now_iso(),
            "workflow_file": str(Path(workflow_path).resolve()),
            "use_vision": bool(self.use_vision),
            "device": config.ADB_TARGET_DEVICE,
            "appium_server_url": config.APPIUM_SERVER_URL,
            "app": {
                "package": config.APP_PACKAGE,
                "activity": config.APP_ACTIVITY,
            },
            "workflows": [],
            "navigation_memory_file": str(config.NAVIGATION_MEMORY_FILE),
        }

        actions_path: List[str] = []

        # Start emulator (best-effort)
        if not adb.start_emulator(config.EMULATOR_AVD, target_device=config.ADB_TARGET_DEVICE):
            report["fatal_error"] = "Emulator could not be started"
            out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            return out_path

        # Start Appium server (best-effort)
        try:
            self.appium_process = appium_server.start_appium_server(
                config.APPIUM_SERVER_URL, repo_root=config.REPO_ROOT, log_file=config.APPIUM_LOG_FILE
            )
        except Exception as exc:
            report["fatal_error"] = f"Could not start Appium server: {exc}"
            out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            return out_path

        self.controller.start_driver()
        if not self.controller.app_is_open:
            report["fatal_error"] = "Failed to start the app"
            out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            return out_path

        try:
            for workflow in wf.workflows:
                wf_entry: Dict[str, Any] = {
                    "name": workflow.name,
                    "status": "passed",
                    "steps": [],
                    "bugs": [],
                }

                # Reset app before each workflow (except the Reset workflow itself)
                if workflow.name != "Reset App State":
                    try:
                        self.controller.reset_app()
                        time.sleep(2)  # Wait for app to restart
                        actions_path.clear()
                    except Exception as reset_err:
                        print(f"Warning: Could not reset app before workflow '{workflow.name}': {reset_err}")

                # Run each step
                for idx, step in enumerate(workflow.steps, start=1):
                    step_result, bug = self._run_step(idx, step, wf.data, actions_path)
                    wf_entry["steps"].append(step_result.__dict__)
                    if bug is not None:
                        wf_entry["bugs"].append(bug)
                        wf_entry["status"] = "failed"
                    if step_result.status == "failed":
                        wf_entry["status"] = "failed"
                        # Continue to the next workflow instead of stopping completely
                        break

                report["workflows"].append(wf_entry)
                print(f"Workflow '{workflow.name}': {wf_entry['status'].upper()}")

        finally:
            # Always try to persist navigation memory and shut down cleanly.
            try:
                self.nav_memory.save()
            except Exception:
                pass

            try:
                self.controller.stop_driver()
            finally:
                try:
                    appium_server.stop_appium_server(self.appium_process)
                except Exception:
                    pass

        report["finished_at"] = _now_iso()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return out_path

    def _run_step(
        self,
        index: int,
        step: WorkflowStep,
        data: Dict[str, Any],
        actions_path: List[str],
    ) -> tuple[StepResult, Optional[Dict[str, Any]]]:
        action = step.action
        note = substitute_vars(step.note, data)

        # Capture before state
        screenshot_path = self.controller.take_screenshot(f"wf_step_{index:02d}_before.png")
        page_source = self.controller.get_page_source() or ""
        state_sig = state_signature_from_xml(page_source)

        # Record navigation memory: how we got here
        self.nav_memory.record_screen(screen_key=state_sig, state_signature=state_sig, actions=actions_path)

        # Expand vars
        locator_strategy = substitute_vars(step.locator_strategy, data)
        locator_value = substitute_vars(step.locator_value, data)
        element_id = substitute_vars(step.element_id, data)
        text = substitute_vars(step.text, data)

        # Normalise locator fields
        if not locator_strategy:
            if locator_value:
                locator_strategy = "accessibility_id"
            elif element_id:
                locator_strategy = "accessibility_id"
                locator_value = element_id

        if not locator_value and element_id:
            locator_value = element_id

        def clickable_hints() -> Dict[str, Any]:
            try:
                acc = extract_clickable_accessibility_ids(page_source)
                rid = extract_clickable_resource_ids(page_source)
                txt = extract_clickable_texts(page_source)
                return {
                    "clickable_accessibility_ids": acc[:40],
                    "clickable_resource_ids": rid[:40],
                    "clickable_texts": txt[:40],
                }
            except Exception:
                return {}

        def fail(msg: str, *, include_hints: bool = False) -> StepResult:
            return StepResult(
                index=index,
                action=action,
                status="failed",
                summary=f"{action}",
                error=(
                    msg
                    if not include_hints
                    else msg + " | hints=" + json.dumps(clickable_hints(), ensure_ascii=False)
                ),
                screenshot=screenshot_path,
                state_signature=state_sig,
                note=note,
            )

        # Perform action
        try:
            if action == "reset":
                self.controller.reset_app()
                actions_path.clear()
                actions_path.append("reset")
                return (
                    StepResult(
                        index=index,
                        action=action,
                        status="passed",
                        summary="App reset",
                        screenshot=screenshot_path,
                        state_signature=state_sig,
                        note=note,
                    ),
                    None,
                )
            elif action == "wait":
                seconds = float(step.seconds or 1.0)
                time.sleep(max(0.0, seconds))
                actions_path.append(f"wait {seconds}s")
                return (
                    StepResult(
                        index=index,
                        action=action,
                        status="passed",
                        summary=f"wait {seconds}s",
                        screenshot=screenshot_path,
                        state_signature=state_sig,
                        note=note,
                    ),
                    None,
                )

            elif action == "scroll":
                direction = substitute_vars(step.direction, data)
                if direction not in ("up", "down", "left", "right"):
                    return (fail(f"Invalid scroll direction: '{direction}'. Must be one of up, down, left, right."), None)

                self.controller.scroll(direction=direction)
                actions_path.append(f"scroll {direction}")
                return (
                    StepResult(
                        index=index,
                        action=action,
                        status="passed",
                        summary=f"scroll {direction}",
                        screenshot=screenshot_path,
                        state_signature=state_sig,
                        note=note,
                    ),
                    None,
                )

            elif action in ("click", "input"):
                if not locator_strategy or not locator_value:
                    return (fail("Missing locator (locator_strategy/locator_value or element_id)"), None)

                element = self._find_element(locator_strategy, locator_value)
                if not element:
                    return (
                        fail(
                            f"Element not found (strategy={locator_strategy}, value={locator_value})",
                            include_hints=True,
                        ),
                        None,
                    )

                if action == "click":
                    element.click()
                    actions_path.append(f"click {locator_strategy}:{locator_value}")
                else:
                    if text is None:
                        return (fail("Input action requires 'text'"), None)
                    # Best-effort focus + clear + type
                    try:
                        element.click()
                    except Exception:
                        pass
                    try:
                        element.clear()
                    except Exception:
                        pass
                    element.send_keys(text)
                    actions_path.append(f"input {locator_strategy}:{locator_value}='{text}'")

                # Success for click/input (post-step capture happens below)

            elif action == "assert_contains":
                expected = substitute_vars(step.assert_contains, data)
                if not expected:
                    return (fail("assert_contains requires assert_contains"), None)
                if expected not in page_source:
                    return (fail(f"assert_contains failed: '{expected}' not found in page_source"), None)
                actions_path.append(f"assert_contains '{expected}'")

                # Success (post-step capture happens below)

            elif action == "assert_text":
                expected = substitute_vars(step.assert_text, data)
                if not expected:
                    return (fail("assert_text requires assert_text"), None)
                if expected not in page_source:
                    return (fail(f"assert_text failed: '{expected}' not found in page_source"), None)
                actions_path.append(f"assert_text '{expected}'")

                # Success (post-step capture happens below)

            elif action == "visual_check":
                bug = self._visual_bug_check(screenshot_path, page_source)
                actions_path.append("visual_check")
                if bug is not None:
                    return (
                        StepResult(
                            index=index,
                            action=action,
                            status="failed",
                            summary="visual_check found a potential bug",
                            error="visual_bug",
                            screenshot=screenshot_path,
                            state_signature=state_sig,
                            note=note,
                        ),
                        bug,
                    )

                # No visual bug found (post-step capture happens below)

            else:
                return (fail(f"Unknown action: {action}"), None)

        except Exception as e:
            return (fail(str(e)), None)

        # Capture after state
        after_screenshot = self.controller.take_screenshot(f"wf_step_{index:02d}_after.png")
        after_source = self.controller.get_page_source() or page_source
        after_sig = state_signature_from_xml(after_source)
        self.nav_memory.record_screen(screen_key=after_sig, state_signature=after_sig, actions=actions_path)

        bug: Optional[Dict[str, Any]] = None

        # Always check for crash dialog strings
        if "has stopped" in after_source.lower() or "keeps stopping" in after_source.lower():
            bug = {
                "type": "crash_dialog",
                "title": "App crash dialog detected",
                "repro_steps": actions_path[-50:],
                "evidence": {"screenshot": after_screenshot},
            }

        # Optional vision after each step
        if self.use_vision and self.vision_enabled_session:
            vb = self._visual_bug_check(after_screenshot or screenshot_path, after_source)
            if vb is not None:
                bug = vb

        return (
            StepResult(
                index=index,
                action=action,
                status="passed" if bug is None else "failed",
                summary=f"{action} ok" if bug is None else f"{action} produced a bug",
                screenshot=after_screenshot or screenshot_path,
                state_signature=after_sig,
                note=note,
            ),
            bug,
        )

    def _find_element(self, strategy: str, value: str):
        if strategy == "accessibility_id":
            return self.controller.find_by_accessibility_id(value)
        if strategy == "id":
            return self.controller.find_by_id(value)
        if strategy == "uiautomator":
            return self.controller.find_by_android_uiautomator(value)
        return None

    def _visual_bug_check(self, screenshot_path: Optional[str], page_source: str) -> Optional[Dict[str, Any]]:
        if not screenshot_path:
            return None
        if not self.vision_enabled_session:
            return None

        prompt = (
            "You are a visual bug detector for a mobile app screenshot. "
            "Look for UI issues: overlapping elements, clipped text, misalignment, unreadable contrast, missing labels, broken layout. "
            "If you find a bug, output a short bug report with: Title, Steps (1-3), Expected, Actual, Severity. "
            "If none, output exactly: No bugs found"
        )

        try:
            bug_description = get_vlm_response(screenshot_path, prompt)
            if not bug_description:
                return None
            if "no bugs found" in bug_description.lower():
                return None
            return {
                "type": "visual",
                "title": "Potential visual/UI bug",
                "description": bug_description,
                "evidence": {"screenshot": screenshot_path},
            }
        except VLMQuotaExceeded:
            self.vision_enabled_session = False
            return None
        except VLMUnavailable:
            self.vision_enabled_session = False
            return None
        except Exception:
            return None
