"""
Recovery Agent  --  specialises in returning the app to a known-good state
after crashes, unexpected dialogs, wrong screens, or stuck situations.

The Recovery Agent maintains a small repertoire of recovery strategies
(back-press cascade, app reset, dismiss dialog) and selects the best one
based on the current screen state.  The Orchestrator calls it whenever
a step fails repeatedly or the Navigator reports an unrecognisable screen.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from ..logging_config import get_logger
from ..appium_controller import AppiumController

logger = get_logger("agents.recovery")
from ..ui_extract import (
    extract_clickable_accessibility_ids,
    extract_clickable_resource_ids,
    extract_clickable_texts,
)
from ..memory import state_signature_from_xml


# Common crash / error dialog indicators
_CRASH_KEYWORDS = {
    "has stopped", "keeps stopping", "isn't responding",
    "unfortunately", "crash", "error", "force close",
    "not responding", "anr",
}

_DIALOG_DISMISS_TEXTS = [
    "OK", "Close", "Dismiss", "Cancel", "Got it",
    "CLOSE", "CANCEL", "DISMISS", "Accept",
]


class RecoveryAgent(BaseAgent):
    name = "recovery"
    system_role = (
        "You are a mobile app recovery specialist. "
        "When the app is in a bad state (crash dialog, wrong screen, stuck), "
        "you determine the best recovery strategy and return a JSON action plan. "
        "Your goal is to bring the app back to a usable, known-good state "
        "with the fewest possible actions."
    )

    def __init__(self, controller: AppiumController):
        super().__init__()
        self.controller = controller
        self.recovery_count = 0
        self.session_restarts = 0

    # ── Session-level recovery ───────────────────────────────────────

    def repair_session_if_needed(self) -> bool:
        """Detect a dead UiAutomator2 session and restart the driver.

        Returns True if the session is usable (either it was already healthy
        or we successfully restarted it).
        """
        if self.controller.is_session_alive():
            return True

        logger.warning("UiAutomator2 session is dead -- restarting driver...")
        self.session_restarts += 1
        ok = self.controller.restart_driver()
        if ok:
            logger.info("Session repaired (restart #%d).", self.session_restarts)
        else:
            logger.error("Session repair FAILED (restart #%d).", self.session_restarts)
        return ok

    # ── Public API ───────────────────────────────────────────────────

    def needs_recovery(self, ui_context: Dict[str, Any]) -> bool:
        """Heuristic check: does the current screen look like a crash or stuck state?"""
        if self._detect_crash_dialog(ui_context):
            return True
        if self._detect_empty_screen(ui_context):
            return True
        return False

    def recover(
        self,
        ui_context: Dict[str, Any],
        *,
        target_signature: Optional[str] = None,
        max_attempts: int = 5,
    ) -> Dict[str, Any]:
        """
        Attempt to recover the app to a usable state.

        Parameters
        ----------
        ui_context : dict
            Current UI state from the Navigator.
        target_signature : str, optional
            If provided, try to return to this specific screen.
        max_attempts : int
            Maximum recovery actions before giving up and resetting the app.

        Returns
        -------
        dict with keys: ``recovered`` (bool), ``strategy`` (str), ``steps_taken`` (int)
        """
        logger.info("Starting recovery (attempt #%d)...", self.recovery_count + 1)
        self.recovery_count += 1

        # First, make sure the Appium session is alive
        if not self.repair_session_if_needed():
            logger.error("Cannot recover -- session repair failed")
            return {"recovered": False, "strategy": "session_dead", "steps_taken": 0}

        for attempt in range(max_attempts):
            # Re-read the screen
            page_source = self.controller.get_page_source() or ""
            acc_ids = extract_clickable_accessibility_ids(page_source)
            texts = extract_clickable_texts(page_source)
            sig = state_signature_from_xml(page_source)

            current_ctx = {
                "accessibility_ids": acc_ids,
                "resource_ids": extract_clickable_resource_ids(page_source),
                "clickable_texts": texts,
                "state_signature": sig,
                "page_source": page_source,
            }

            # ── Strategy 1: Dismiss crash/error dialog ───────────────
            if self._detect_crash_dialog(current_ctx):
                dismissed = self._dismiss_dialog(current_ctx)
                if dismissed:
                    logger.info("Dismissed dialog (attempt %d)", attempt + 1)
                    time.sleep(1.0)
                    continue     # Re-check state

            # ── Strategy 2: We're on a good screen ───────────────────
            if not self._detect_crash_dialog(current_ctx) and not self._detect_empty_screen(current_ctx):
                if target_signature and sig == target_signature:
                    logger.info("Reached target screen")
                    return {"recovered": True, "strategy": "navigation", "steps_taken": attempt + 1}
                elif not target_signature:
                    logger.info("Screen looks usable")
                    return {"recovered": True, "strategy": "auto", "steps_taken": attempt + 1}

            # ── Strategy 3: Press back ───────────────────────────────
            if attempt < max_attempts - 2:
                self.controller.press_back()
                logger.debug("Pressed back (attempt %d)", attempt + 1)
                time.sleep(1.0)
                continue

            # ── Strategy 4: LLM-guided recovery ─────────────────────
            if attempt == max_attempts - 2:
                llm_result = self._llm_recovery(current_ctx, target_signature)
                if llm_result.get("recovered"):
                    return llm_result

        # ── Strategy 5: Hard reset ───────────────────────────────────
        logger.warning("All strategies failed -- resetting app")
        self.controller.reset_app()
        time.sleep(2.0)
        return {"recovered": True, "strategy": "app_reset", "steps_taken": max_attempts}

    # ── Detection helpers ────────────────────────────────────────────

    def _detect_crash_dialog(self, ui_context: Dict[str, Any]) -> bool:
        """Check if the screen shows a crash / ANR / error dialog."""
        texts = ui_context.get("clickable_texts", [])
        acc_ids = ui_context.get("accessibility_ids", [])
        all_text = " ".join(texts + acc_ids).lower()
        return any(kw in all_text for kw in _CRASH_KEYWORDS)

    @staticmethod
    def _detect_empty_screen(ui_context: Dict[str, Any]) -> bool:
        """Screens with zero interactive elements are likely stuck / blank."""
        total = (
            len(ui_context.get("accessibility_ids", []))
            + len(ui_context.get("resource_ids", []))
            + len(ui_context.get("clickable_texts", []))
        )
        return total == 0

    # ── Recovery strategies ──────────────────────────────────────────

    def _dismiss_dialog(self, ui_context: Dict[str, Any]) -> bool:
        """Try to click a dismiss button on a dialog."""
        texts = ui_context.get("clickable_texts", [])
        acc_ids = ui_context.get("accessibility_ids", [])

        # Try known dismiss texts
        for dismiss_text in _DIALOG_DISMISS_TEXTS:
            if dismiss_text in texts:
                el = self.controller.find_by_android_uiautomator(
                    f'new UiSelector().text("{dismiss_text}")'
                )
                if el:
                    try:
                        el.click()
                        return True
                    except Exception:
                        pass
            if dismiss_text in acc_ids:
                el = self.controller.find_by_accessibility_id(dismiss_text)
                if el:
                    try:
                        el.click()
                        return True
                    except Exception:
                        pass
        return False

    def _llm_recovery(
        self,
        ui_context: Dict[str, Any],
        target_signature: Optional[str],
    ) -> Dict[str, Any]:
        """Ask the LLM for a recovery strategy when heuristics fail."""
        acc = json.dumps(ui_context.get("accessibility_ids", [])[:30])
        txt = json.dumps(ui_context.get("clickable_texts", [])[:20])

        target_hint = (
            f"Target screen signature: {target_signature}"
            if target_signature
            else "Return to the app's main/home screen."
        )

        prompt = f"""The mobile app is in an unexpected state and needs recovery.

CURRENT SCREEN:
Accessibility IDs: {acc}
Clickable Texts: {txt}

GOAL: {target_hint}

What sequence of actions should be taken to recover?
Return a JSON array of actions (max 3):
[
    {{
        "action": "click" | "back" | "scroll",
        "locator_type": "accessibility_id" | "text" | null,
        "locator_value": "<exact value>" | null,
        "direction": "up" | "down" | null,
        "reason": "<why>"
    }}
]"""

        try:
            raw = self.ask_text(prompt)
            actions = self.parse_json(raw)
            if not isinstance(actions, list):
                return {"recovered": False, "strategy": "llm", "steps_taken": 0}

            for act in actions[:3]:
                action = act.get("action", "")
                if action == "back":
                    self.controller.press_back()
                elif action == "click":
                    lt = act.get("locator_type")
                    lv = act.get("locator_value")
                    if lt == "accessibility_id" and lv:
                        el = self.controller.find_by_accessibility_id(lv)
                    elif lt == "text" and lv:
                        safe = lv.replace('"', '\\"')
                        el = self.controller.find_by_android_uiautomator(
                            f'new UiSelector().text("{safe}")'
                        )
                    else:
                        el = None
                    if el:
                        el.click()
                elif action == "long_press":
                    el = None
                    if lt == "accessibility_id" and lv:
                        el = self.controller.find_by_accessibility_id(lv)
                    elif lt == "text" and lv:
                        safe = lv.replace('"', '\\"')
                        el = self.controller.find_by_android_uiautomator(
                            f'new UiSelector().text("{safe}")'
                        )
                    if el:
                        self.controller.long_press(element=el)
                elif action == "scroll":
                    self.controller.scroll(act.get("direction", "down"))
                time.sleep(0.8)

            return {"recovered": True, "strategy": "llm", "steps_taken": len(actions)}
        except Exception as e:
            logger.error("LLM recovery failed: %s", e, exc_info=True)
            return {"recovered": False, "strategy": "llm", "steps_taken": 0}
