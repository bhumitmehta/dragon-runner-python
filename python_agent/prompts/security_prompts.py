"""
Prompt templates for the Security Agent.

The Security Agent probes the app for common mobile security weaknesses:
injection, auth bypass, sensitive data exposure, etc.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .builder import PromptBuilder


# ── System role ──────────────────────────────────────────────────────

SECURITY_SYSTEM_ROLE = (
    "You are a mobile application security tester. "
    "You examine UI elements, inputs, and screens for common "
    "security vulnerabilities. You generate hostile inputs, "
    "analyse responses for info leaks, and identify authentication "
    "weaknesses. Return structured JSON findings."
)


class SecurityPrompts:
    """Factory for Security agent prompts using the builder pattern."""

    SYSTEM_ROLE = SECURITY_SYSTEM_ROLE

    # ── LLM-guided security actions ──────────────────────────────────

    @staticmethod
    def generate_security_actions(
        ui_elements: Dict[str, List[str]],
    ) -> str:
        """Build prompt asking the LLM for app-specific security test vectors."""
        return (
            PromptBuilder()
            .preamble(
                "Analyse this mobile app screen for security test opportunities."
            )
            .section(
                "AVAILABLE ELEMENTS",
                f"Accessibility IDs: {json.dumps(ui_elements.get('accessibility_ids', [])[:25])}\n"
                f"Clickable Texts: {json.dumps(ui_elements.get('clickable_texts', [])[:15])}",
            )
            .suffix(
                "Suggest up to 3 security test actions specific to this screen.\n"
                "Consider: authentication bypass, privilege escalation, data leaks, injection."
            )
            .json_output(
                '[\n'
                '    {\n'
                '        "action": "click" | "input",\n'
                '        "locator_type": "accessibility_id" | "text",\n'
                '        "locator_value": "<exact ID from lists>",\n'
                '        "text": "<hostile input>" | null,\n'
                '        "reason": "<what vulnerability this tests>",\n'
                '        "test_type": "<injection|auth_bypass|data_leak|logic_flaw>"\n'
                '    }\n'
                ']',
                preamble="Return ONLY a JSON array:",
            )
            .build()
        )
