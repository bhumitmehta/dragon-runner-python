"""
Prompt templates for the Recovery Agent.

The Recovery Agent returns the app to a known-good state after crashes,
unexpected dialogs, wrong screens, or stuck situations.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .builder import PromptBuilder


# ── System role ──────────────────────────────────────────────────────

RECOVERY_SYSTEM_ROLE = (
    "You are a mobile app recovery specialist. "
    "When the app is in a bad state (crash dialog, wrong screen, stuck), "
    "you determine the best recovery strategy and return a JSON action plan. "
    "Your goal is to bring the app back to a usable, known-good state "
    "with the fewest possible actions."
)


class RecoveryPrompts:
    """Factory for Recovery agent prompts using the builder pattern."""

    SYSTEM_ROLE = RECOVERY_SYSTEM_ROLE

    # ── LLM-guided recovery ──────────────────────────────────────────

    @staticmethod
    def llm_recovery(
        ui_context: Dict[str, List[str]],
        target_signature: Optional[str] = None,
    ) -> str:
        """Build prompt for LLM-guided recovery when heuristics fail."""
        target_hint = (
            f"Target screen signature: {target_signature}"
            if target_signature
            else "Return to the app's main/home screen."
        )

        return (
            PromptBuilder()
            .preamble(
                "The mobile app is in an unexpected state and needs recovery."
            )
            .section(
                "CURRENT SCREEN",
                f"Accessibility IDs: {json.dumps(ui_context.get('accessibility_ids', [])[:30])}\n"
                f"Clickable Texts: {json.dumps(ui_context.get('clickable_texts', [])[:20])}",
            )
            .section("GOAL", target_hint)
            .json_output(
                '[\n'
                '    {\n'
                '        "action": "click" | "back" | "scroll",\n'
                '        "locator_type": "accessibility_id" | "text" | null,\n'
                '        "locator_value": "<exact value>" | null,\n'
                '        "direction": "up" | "down" | null,\n'
                '        "reason": "<why>"\n'
                '    }\n'
                ']',
                preamble="What sequence of actions should be taken to recover?\nReturn a JSON array of actions (max 3):",
            )
            .build()
        )
