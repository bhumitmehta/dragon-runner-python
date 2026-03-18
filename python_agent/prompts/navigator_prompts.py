"""
Prompt templates for the Navigator Agent.

The Navigator translates high-level step descriptions into concrete
Appium actions (click, input, scroll, etc.) by matching the step to
available on-screen elements.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .builder import PromptBuilder


# ── System role ──────────────────────────────────────────────────────

NAVIGATOR_SYSTEM_ROLE = (
    "You are a mobile UI navigator agent. "
    "Given a description of a UI action and the current screen elements, "
    "you produce the exact JSON command to execute. "
    "You must ONLY use element IDs that appear in the provided lists  --  "
    "never fabricate element identifiers."
)


class NavigatorPrompts:
    """Factory for Navigator agent prompts using the builder pattern."""

    SYSTEM_ROLE = NAVIGATOR_SYSTEM_ROLE

    # ── Action resolution ────────────────────────────────────────────

    @staticmethod
    def resolve_action(
        step_description: str,
        ui_elements: Dict[str, List[str]],
        history_str: str = "(no actions yet)",
    ) -> str:
        """Build the prompt to resolve a high-level step into a concrete action."""
        return (
            PromptBuilder()
            .preamble("Resolve this test step into a concrete UI action.")
            .section("STEP TO EXECUTE", step_description)
            .ui_elements(
                ui_elements.get("accessibility_ids", []),
                ui_elements.get("resource_ids", []),
                ui_elements.get("clickable_texts", []),
            )
            .section("RECENT ACTIONS", history_str)
            .rules([
                "ONLY use IDs from the lists above  --  never guess or fabricate.",
                'If the step cannot be executed (element not found), return action "skip" with a reason.',
                'For long press actions, use "long_press" action type.',
                "If you need to scroll to find an element, use \"scroll\" with direction first.",
                "For text input, always specify both locator_value AND text.",
            ])
            .json_output(
                '{\n'
                '    "action": "click" | "input" | "scroll" | "back" | "hide_keyboard" | "press_enter" | "skip" | "assert" | "long_press",\n'
                '    "locator_type": "accessibility_id" | "resource_id" | "text" | null,\n'
                '    "locator_value": "<exact ID from list>" | null,\n'
                '    "text": "<text for input>" | null,\n'
                '    "direction": "up" | "down" | "left" | "right" | null,\n'
                '    "reason": "<why this action matches the step>",\n'
                '    "bug_report": "<any bug noticed>" | null\n'
                '}',
                preamble="Return ONLY valid JSON (no markdown):",
            )
            .build()
        )
