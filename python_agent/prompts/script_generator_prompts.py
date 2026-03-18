"""
Prompt templates for the ScriptGenerator Agent.

The ScriptGenerator produces verification test scripts and navigation
scripts as structured JSON action sequences.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .builder import PromptBuilder


# ── System role ──────────────────────────────────────────────────────

SCRIPT_GENERATOR_SYSTEM_ROLE = (
    "You are a mobile QA automation engineer. "
    "Given a feature description and the current UI elements, you generate "
    "a concrete test script as a JSON action sequence. Each step is a single "
    "UI action (click, input, scroll, back, assert_visible, assert_text, "
    "assert_order, assert_count). You must ONLY reference element IDs that "
    "appear in the provided lists."
)


class ScriptGeneratorPrompts:
    """Factory for ScriptGenerator agent prompts using the builder pattern."""

    SYSTEM_ROLE = SCRIPT_GENERATOR_SYSTEM_ROLE

    # ── Verification script ──────────────────────────────────────────

    @staticmethod
    def verification_script(
        feature: Dict[str, Any],
        ui_elements: Dict[str, List[str]],
        *,
        screen_graph_summary: str = "",
        nav_script_steps: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Build prompt for generating a feature verification script."""
        hints = feature.get("verification_hints", [])
        hints_str = "\n".join(f"  - {h}" for h in hints) if hints else "  (none provided)"
        feature_name = feature.get("name", "Unknown")
        feature_id = feature.get("id", "")

        builder = (
            PromptBuilder()
            .preamble("Generate a verification test script for this feature:")
            .section(
                "FEATURE",
                f"Name: {feature_name}\n"
                f"Description: {feature.get('description', '')}\n"
                f"Priority: {feature.get('priority', 'medium')}",
            )
            .section("VERIFICATION HINTS", hints_str)
        )

        if nav_script_steps:
            builder.section(
                "PRECONDITION NAVIGATION (already handled, starts from home)",
                json.dumps(nav_script_steps[:10], indent=2),
            )

        if screen_graph_summary:
            builder.section(
                "KNOWN SCREEN GRAPH",
                screen_graph_summary[:1500],
            )

        builder.ui_elements(
            ui_elements.get("accessibility_ids", []),
            ui_elements.get("resource_ids", []),
            ui_elements.get("clickable_texts", []),
            acc_limit=40,
            res_limit=25,
            txt_limit=25,
        )

        builder.json_output(
            '{\n'
            f'  "name": "Verify {feature_name}",\n'
            '  "description": "<what this script tests>",\n'
            f'  "feature_id": "{feature_id}",\n'
            '  "steps": [\n'
            '    {\n'
            '      "action": "click" | "input" | "scroll" | "back" | "wait",\n'
            '      "locator_type": "accessibility_id" | "resource_id" | "text" | "xpath",\n'
            '      "locator_value": "<element identifier>",\n'
            '      "text": "<text to input, only for input action>",\n'
            '      "description": "<human-readable description of this step>"\n'
            '    }\n'
            '  ],\n'
            '  "assertions": [\n'
            '    {\n'
            '      "type": "assert_visible" | "assert_text" | "assert_order" | "assert_count" | "assert_not_visible",\n'
            '      "locator_type": "accessibility_id" | "resource_id" | "text",\n'
            '      "locator_value": "<element to check>",\n'
            '      "expected": "<expected value or condition>",\n'
            '      "description": "<what this assertion verifies>"\n'
            '    }\n'
            '  ]\n'
            '}',
            preamble="Return a JSON object with this exact structure:",
        )

        builder.rules([
            "steps: 1-8 UI actions to set up the test scenario. Keep it SHORT.",
            "assertions: 1-3 checks that verify the feature works correctly.",
            "For the FIRST step: use an element ID that EXACTLY appears in the lists above.",
            "For LATER steps that happen AFTER the UI changes (e.g. a popup/modal/overlay appears "
            "after tapping a button): set locator_value to \"\" (empty) and write a CLEAR description. "
            "The executor will dynamically resolve the element at runtime against the actual screen.",
            "For assert_visible/assert_not_visible: locator_value should be a keyword likely to appear "
            "in the element's accessibility id, resource id, or text.",
            'For assert_order: expected should describe the ordering, e.g. "ascending by price".',
            'For assert_count: expected should be a number string, e.g. "1".',
            "For assert_text: expected is the text that should appear on the element.",
            'Use action "wait" with a "duration" field (in seconds) for pauses.',
            "The \"description\" field is CRITICAL  --  it must be a clear human-readable instruction "
            "that can be followed even without knowing the locator. The executor uses it as fallback.",
            "Return ONLY the JSON object, no explanation.",
        ])

        return builder.build()

    # ── Navigation script ────────────────────────────────────────────

    @staticmethod
    def nav_script(
        target_screen_name: str,
        ui_elements: Dict[str, List[str]],
        *,
        screen_graph_summary: str = "",
        action_history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Build prompt for generating a navigation script to reach a target screen."""
        builder = (
            PromptBuilder()
            .preamble(
                f'Generate a navigation script to reach the "{target_screen_name}" screen '
                "from the app home screen."
            )
        )

        if action_history:
            recent = action_history[-10:]
            lines = []
            for a in recent:
                status = "OK" if a.get("success") else "FAIL"
                lines.append(
                    f"  [{status}] {a.get('action', '?')}: "
                    f"{a.get('locator', '?')} -> {a.get('description', '')[:40]}"
                )
            builder.section(
                "RECENT ACTIONS THAT REACHED THIS SCREEN",
                "\n".join(lines),
            )

        if screen_graph_summary:
            builder.section("KNOWN SCREEN GRAPH", screen_graph_summary[:1500])

        builder.section(
            "CURRENT UI ELEMENTS (home screen)",
            f"Accessibility IDs: {json.dumps(ui_elements.get('accessibility_ids', [])[:40])}\n"
            f"Resource IDs: {json.dumps(ui_elements.get('resource_ids', [])[:25])}\n"
            f"Clickable Texts: {json.dumps(ui_elements.get('clickable_texts', [])[:25])}",
        )

        builder.json_output(
            '{\n'
            f'  "name": "Navigate to {target_screen_name}",\n'
            f'  "target_screen": "{target_screen_name}",\n'
            '  "steps": [\n'
            '    {\n'
            '      "action": "click" | "input" | "scroll" | "back" | "wait",\n'
            '      "locator_type": "accessibility_id" | "resource_id" | "text",\n'
            '      "locator_value": "<element>",\n'
            '      "text": "<optional input text>",\n'
            '      "description": "<what this step does>"\n'
            '    }\n'
            '  ]\n'
            '}',
            preamble="Return a JSON object:",
        )

        builder.rules([
            "Steps should be the SHORTEST path from the current screen (home) to the target screen.",
            "For the FIRST step: use an element ID that EXACTLY appears in the provided lists.",
            "For LATER steps where the UI has changed (popups, new screens): set locator_value to \"\" "
            "and write a CLEAR description of what to tap/click. The executor resolves it dynamically.",
            "The \"description\" field is CRITICAL  --  write clear human-readable instructions.",
            'Use action "wait" with a "duration" field for pauses (e.g. after animation).',
            "Maximum 8 steps.",
            "Return ONLY the JSON, no explanation.",
        ])

        return builder.build()
