"""
Prompt templates for the Explorer Agent.

The Explorer autonomously navigates the app to maximise coverage.
These prompts guide: element picking, visual bug detection,
navigation classification, and screen planning.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .builder import PromptBuilder


# ── System role ──────────────────────────────────────────────────────

EXPLORER_SYSTEM_ROLE = (
    "You are a thorough mobile app QA explorer. "
    "Your goal is to maximise coverage -- visit every screen, interact "
    "with every element, scroll to find hidden content, fill input fields, "
    "and visually inspect each screen for bugs. Report anything unusual: "
    "broken layouts, overlapping elements, missing images, wrong text, "
    "unresponsive buttons, crashes, or unexpected behaviour."
)


class ExplorerPrompts:
    """Factory for Explorer agent prompts using the builder pattern."""

    SYSTEM_ROLE = EXPLORER_SYSTEM_ROLE

    # ── LLM element picker ───────────────────────────────────────────

    @staticmethod
    def pick_element(
        untried: List[str],
        ui_context: Dict[str, Any],
        coverage: Dict[str, Any],
        current_visits: int,
        least_visited: List[Dict[str, Any]],
        history_str: str,
        *,
        transition_hint: str = "",
        weight_hint: str = "",
        graph_hint: str = "",
    ) -> str:
        """Build the prompt that asks the LLM to choose the most
        promising untried element to interact with."""

        least_visited_str = json.dumps(
            [{"sig": s["signature"][:20], "visits": s["visits"]} for s in least_visited]
        )

        builder = (
            PromptBuilder()
            .preamble(
                "You are exploring a mobile app to find bugs and maximise test coverage."
            )
            .section(
                "UNTRIED ELEMENTS (never interacted with before)",
                json.dumps(untried[:30]),
            )
            .section(
                "ALL VISIBLE ELEMENTS",
                f"Accessibility IDs: {json.dumps(ui_context.get('accessibility_ids', [])[:25])}\n"
                f"Clickable Texts: {json.dumps(ui_context.get('clickable_texts', [])[:15])}",
            )
            .section_json("COVERAGE SO FAR", coverage)
            .section(
                "SCREEN VISIT INFO",
                f"Current screen has been visited {current_visits} times.\n"
                f"LEAST-VISITED SCREENS: {least_visited_str}",
            )
            .section_if("KNOWN TRANSITIONS", transition_hint, bool(transition_hint))
            .section_if("CRITIC FEEDBACK", weight_hint, bool(weight_hint))
            .section_if("GRAPH INTELLIGENCE", graph_hint, bool(graph_hint))
            .section("RECENT ACTIONS", history_str)
            .preamble("")  # clear -- already set above
        )

        builder.suffix(
            "Pick the SINGLE most promising untried element to interact with.\n"
            "Prefer elements that might:\n"
            "- Navigate to LESS-VISITED or new screens (menu buttons, navigation items)\n"
            "- Reveal new screens or features\n"
            "- Trigger bugs (edge-case actions, unusual buttons)\n"
            "- Be part of critical flows (login, cart, checkout, settings)\n"
            "AVOID elements that would keep us on this already well-visited screen."
        )

        builder.json_output(
            '{\n'
            '    "action": "click" | "input" | "scroll" | "long_press",\n'
            '    "locator_type": "accessibility_id" | "resource_id" | "text",\n'
            '    "locator_value": "<exact value from UNTRIED list>",\n'
            '    "text": "<for input only>" | null,\n'
            '    "direction": "down" | null,\n'
            '    "reason": "<why this element is promising>"\n'
            '}',
            preamble="Return ONLY JSON:",
        )

        return builder.build()

    # ── Visual bug detection ─────────────────────────────────────────

    @staticmethod
    def visual_inspect() -> str:
        """Build the prompt for VLM-based visual bug detection on a screenshot."""
        return (
            PromptBuilder()
            .preamble(
                "You are a senior QA tester performing visual inspection "
                "of a mobile app screenshot."
            )
            .section(
                "LOOK FOR ANY OF THESE VISUAL BUGS",
                "1. **Overlapping/truncated text**  --  text cut off, overlapping other elements\n"
                "2. **Broken layout**  --  misaligned elements, uneven spacing, elements out of bounds\n"
                "3. **Missing images**  --  blank/placeholder images, broken image icons\n"
                "4. **Wrong colors/contrast**  --  text hard to read, inconsistent theme\n"
                "5. **Empty states**  --  screens that look blank when they shouldn't be\n"
                "6. **Distorted elements**  --  stretched images, squished buttons\n"
                "7. **Duplicate content**  --  same item appearing multiple times incorrectly\n"
                "8. **Accessibility**  --  text too small to read, touch targets too small\n"
                "9. **Rendering glitches**  --  flickering, partial rendering, z-order issues\n"
                "10. **Unexpected state**  --  error messages, loading forever, wrong screen",
            )
            .json_output(
                '[\n'
                '    {\n'
                '        "type": "<bug type from list above>",\n'
                '        "severity": "critical" | "high" | "medium" | "low",\n'
                '        "description": "<specific description of what\'s wrong>",\n'
                '        "location": "<where on screen: top/middle/bottom, left/center/right>"\n'
                '    }\n'
                ']\n\n'
                'If no visual bugs found, return: []',
                preamble="If you find bugs, return JSON array. If no visual bugs, return empty array.\nReturn ONLY JSON (no markdown):",
            )
            .build()
        )

    # ── Navigation element classification ────────────────────────────

    @staticmethod
    def classify_nav_elements(elements: List[str]) -> str:
        """Build prompt to classify UI elements as nav/action/content."""
        return (
            PromptBuilder()
            .preamble(
                "Classify each UI element into one of these categories:\n"
                '- "nav": navigation elements that lead to OTHER screens '
                "(menus, tabs, links, drawer items, back buttons, screen titles that are clickable)\n"
                '- "action": elements that perform an action on the CURRENT screen '
                "(buttons, toggles, sort, filter, add/remove, submit)\n"
                '- "content": non-interactive or decorative elements (labels, images, text)'
            )
            .section("ELEMENTS TO CLASSIFY", json.dumps(elements))
            .json_output(
                '[{"id": "<element id>", "role": "nav" | "action" | "content"}]',
                preamble="Return ONLY a JSON array of objects:",
            )
            .suffix(
                'Be thorough -- anything that could navigate to a different screen is "nav".'
            )
            .build()
        )
