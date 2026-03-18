"""
Prompt templates for the Accessibility Agent.

The Accessibility Agent tests WCAG / mobile accessibility compliance,
including visual checks via VLM for contrast, readability, and layout.
"""
from __future__ import annotations

from .builder import PromptBuilder


# ── System role ──────────────────────────────────────────────────────

ACCESSIBILITY_SYSTEM_ROLE = (
    "You are a mobile accessibility (a11y) specialist. "
    "You evaluate screenshots and UI trees against WCAG 2.1 mobile "
    "guidelines and Android accessibility best practices. "
    "Return structured JSON findings with severity ratings."
)


class AccessibilityPrompts:
    """Factory for Accessibility agent prompts using the builder pattern."""

    SYSTEM_ROLE = ACCESSIBILITY_SYSTEM_ROLE

    # ── Visual accessibility check (VLM) ─────────────────────────────

    @staticmethod
    def visual_check() -> str:
        """Build prompt for VLM-based visual accessibility inspection."""
        return (
            PromptBuilder()
            .preamble(
                "Analyse this mobile app screenshot for accessibility issues."
            )
            .section(
                "CHECK FOR",
                "1. Low-contrast text (text hard to read against background)\n"
                "2. Information conveyed only by colour (no text/icon alternative)\n"
                "3. Cluttered layouts that may confuse screen reader users\n"
                "4. Missing visual focus indicators\n"
                "5. Text that is too small to read comfortably",
            )
            .json_output(
                '[\n'
                '    {\n'
                '        "rule": "<short rule name>",\n'
                '        "severity": "critical" | "major" | "minor" | "info",\n'
                '        "description": "<what the issue is>",\n'
                '        "guideline": "<which WCAG guideline is violated>"\n'
                '    }\n'
                ']',
                preamble=(
                    "Return ONLY a JSON array of issues found (empty array if none):"
                ),
            )
            .build()
        )
