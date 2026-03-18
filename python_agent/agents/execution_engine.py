"""
Execution Engine  --  extracted from Orchestrator to separate
policy (what to do) from execution (how to do it).

The Orchestrator decides WHAT happens next (policy layer).
The ExecutionEngine handles HOW it happens (action dispatch,
Critic evaluation, recording, retry logic).

This eliminates the god-object anti-pattern: the Orchestrator
becomes a thin routing/decision layer while all action execution
flows through this engine.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, Optional

from ..logging_config import get_logger
from ..session_memory import (
    BugEntry,
    SessionMemory,
    TaskStatus,
    TestStep,
    TestTask,
)
from .. import config



logger = get_logger("execution_engine")


class ExecutionEngine:
    """Stateless action dispatcher  --  receives agents, executes actions,
    records outcomes, handles retries.

    The Orchestrator passes agents in at construction; the engine never
    owns or creates them.
    """

    def __init__(
        self,
        *,
        navigator,
        critic,
        recovery,
        explorer,
        memory: SessionMemory,
        kb,
        bug_integration=None,
        generate_screen_name=None,
    ):
        self.navigator = navigator
        self.critic = critic
        self.recovery = recovery
        self.explorer = explorer
        self.memory = memory
        self.kb = kb
        self.bug_integration = bug_integration
        self.generate_screen_name = generate_screen_name or self._default_generate_screen_name
        # Screen source cache (instance-level, shared via set_screen_cache)
        self._screen_sources: Dict[str, tuple] = {}

    # ── Single step execution (task mode) ────────────────────────────

    def execute_step(self, step: TestStep, task: TestTask, ui_ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Execute one planned step with Critic pre/post validation and
        automatic weight update.

        Returns the Navigator result dict.
        """
        ui_elements = self._extract_ui_elements(ui_ctx)

        # Record screen
        self.memory.record_screen(ui_ctx["state_signature"], ui_ctx["accessibility_ids"])

        # Cache screen source
        sig = ui_ctx["state_signature"]
        self._cache_screen(sig, ui_ctx)

        # Navigator resolves & executes
        result = self.navigator.execute_step(
            step.description,
            ui_ctx,
            action_history=self.memory.recent_actions(8),
        )

        # Critic post-check WITH feedback loop into SessionMemory weights
        if result["success"]:
            post_ctx = self.navigator.get_ui_context(f"post_{self.memory.step_counter:04d}")
            post_elements = self._extract_ui_elements(post_ctx)

            sig_before = result.get("state_signature_before", "")
            sig_after = result.get("state_signature_after", "")
            if sig_before and sig_after and sig_before != sig_after:
                self.memory.record_transition(sig_before, step.description, sig_after)
                self.memory.record_screen(sig_after, post_ctx["accessibility_ids"])
                name = self.generate_screen_name(post_ctx)
                self.kb.record_screen(sig_after, post_ctx["accessibility_ids"], screenshot=post_ctx.get("screenshot_path", ""), name=name)
                self.kb.record_transition(sig_before, step.description, sig_after)
                self._cache_screen(sig_after, post_ctx)

            # Critic evaluate_and_update pushes verdict into action weights
            from .critic import Verdict
            verdict = self.critic.evaluate_and_update(
                {"action": result["action"], "locator_value": result["locator_value"]},
                result,
                ui_elements,
                post_elements,
                self.memory,
            )
            if verdict["verdict"] == Verdict.FAIL:
                result["success"] = False
                result["description"] += f" [Critic: {verdict['reason']}]"

        # Log action
        self.memory.log_action({
            "task_id": task.id,
            "step_id": step.id,
            "action": result.get("action"),
            "locator": result.get("locator_value"),
            "success": result.get("success"),
            "description": result.get("description"),
        })

        # Bug localization trace
        self._trace_step(ui_ctx, result)

        return result

    # ── Explorer action execution (explore mode) ─────────────────────

    def execute_explorer_action(
        self,
        action: Dict[str, Any],
        ui_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute an explorer-chosen action with Critic weight feedback.

        Returns the Navigator result dict.
        """
        sig_before = ui_ctx.get("state_signature", "")
        result = self.navigator.execute_action_direct(action, ui_ctx)
        self.explorer.record_action_taken(action)

        # Critic feedback on explorer actions too
        action_type = action.get("action", "")
        locator_value = action.get("locator_value", "")
        if locator_value and result.get("success") is not None:
            verdict_str = "pass" if result.get("success") else "fail"
            self.memory.update_action_weight(locator_value, verdict_str)

        # Record transition
        sig_after = result.get("state_signature_after", "")
        if sig_before and sig_after and sig_before != sig_after:
            action_desc = locator_value or action_type
            self.memory.record_transition(sig_before, action_desc, sig_after)

        # Log action
        self.memory.log_action({
            "action": action_type,
            "locator": locator_value,
            "success": result.get("success"),
            "description": result.get("description"),
            "screen_sig": sig_before,
        })

        return result

    # ── Retry logic ──────────────────────────────────────────────────

    def retry_step(self, step: TestStep, task: TestTask, max_retries: int) -> bool:
        """Retry a failed step up to ``max_retries`` times."""
        for attempt in range(max_retries):
            logger.debug("Retry %d/%d...", attempt + 1, max_retries)
            time.sleep(1.0)
            result = self.execute_step(step, task)
            if result["success"]:
                self.memory.mark_step(step, TaskStatus.COMPLETED, result=result, retries=attempt + 1)
                logger.info("Retry OK -- %s", result['description'])
                return True
        return False

    # ── Health check ─────────────────────────────────────────────────

    def ensure_session_alive(self) -> bool:
        """Repair the Appium session if needed. Returns True if healthy."""
        return self.recovery.repair_session_if_needed()

    # ── Internal helpers ─────────────────────────────────────────────

    def set_screen_cache(self, cache: Dict[str, tuple]):
        """Share the orchestrator's screen source cache."""
        self._screen_sources = cache

    def _cache_screen(self, sig: str, ui_ctx: Dict[str, Any]):
        if sig and sig not in self._screen_sources:
            self._screen_sources[sig] = (
                ui_ctx.get("page_source", ""),
                ui_ctx.get("screenshot_path"),
            )

    @staticmethod
    def _extract_ui_elements(ui_ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "accessibility_ids": ui_ctx["accessibility_ids"],
            "resource_ids": ui_ctx["resource_ids"],
            "clickable_texts": ui_ctx["clickable_texts"],
        }

    def _trace_step(self, ui_ctx: Dict[str, Any], result: Dict[str, Any]):
        if self.bug_integration:
            self.bug_integration.add_trace_step(
                action={"action": result.get("action"), "locator": result.get("locator_value")},
                ui_state={
                    "accessibility_ids": ui_ctx.get("accessibility_ids", []),
                    "state_signature": ui_ctx.get("state_signature", ""),
                },
                screenshot_path=ui_ctx.get("screenshot_path"),
            )
