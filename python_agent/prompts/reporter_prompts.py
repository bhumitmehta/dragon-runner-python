"""
Prompt templates for the Reporter Agent.

The Reporter generates human-readable Markdown reports, executive
summaries, bug pattern analysis, and coverage risk assessments.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .builder import PromptBuilder


# ── System role ──────────────────────────────────────────────────────

REPORTER_SYSTEM_ROLE = (
    "You are a QA report-writing specialist. "
    "You transform raw session data (actions, bugs, coverage metrics) into "
    "clear, structured, human-readable reports in Markdown format. "
    "Be concise but thorough. Highlight critical findings prominently. "
    "Include actionable recommendations."
)


class ReporterPrompts:
    """Factory for Reporter agent prompts using the builder pattern."""

    SYSTEM_ROLE = REPORTER_SYSTEM_ROLE

    # ── Full Markdown report ─────────────────────────────────────────

    @staticmethod
    def markdown_report(session_data: Dict[str, Any]) -> str:
        """Build prompt for generating a detailed Markdown test report."""
        return (
            PromptBuilder()
            .preamble("Generate a detailed Markdown test report from this session data.")
            .section(
                "SESSION DATA",
                json.dumps(session_data, indent=2, default=str)[:6000],
            )
            .output(
                "Structure the report as:\n"
                "# Test Session Report  --  {session_id}\n\n"
                "## Summary\n"
                "- Mode, duration, overall result\n\n"
                "## Test Plan Progress\n"
                "- Goals completed, tasks done, steps executed\n\n"
                "## Bugs Found\n"
                "- For each bug: severity, description, screen, recommended fix\n\n"
                "## Coverage Analysis\n"
                "- Screens visited, features tested, gaps identified\n\n"
                "## Recommendations\n"
                "- What to test next, risk areas, process improvements\n\n"
                "Use tables for bug listings. Be specific and actionable."
            )
            .build()
        )

    # ── Executive summary ────────────────────────────────────────────

    @staticmethod
    def executive_summary(session_data: Dict[str, Any]) -> str:
        """Build prompt for a short 3-5 sentence executive summary."""
        return (
            PromptBuilder()
            .preamble(
                "Write a 3-5 sentence executive summary of this mobile app test session."
            )
            .section_json("SESSION DATA", session_data)
            .section(
                "FOCUS ON",
                "1. Overall pass/fail status\n"
                "2. Critical bugs found (if any)\n"
                "3. Coverage percentage\n"
                "4. Key recommendation",
            )
            .output("Write in plain English, no markdown formatting.")
            .build()
        )

    # ── Bug pattern analysis ─────────────────────────────────────────

    @staticmethod
    def bug_patterns(bugs: List[Dict[str, Any]]) -> str:
        """Build prompt for analysing patterns across discovered bugs."""
        return (
            PromptBuilder()
            .preamble(
                "Analyse these bugs found during mobile app testing and identify patterns."
            )
            .section_json("BUGS", bugs)
            .json_output(
                '{\n'
                '    "patterns": [\n'
                '        {\n'
                '            "name": "<pattern name>",\n'
                '            "bug_ids": ["<matching bug IDs>"],\n'
                '            "description": "<what these bugs have in common>",\n'
                '            "likely_root_cause": "<probable shared root cause>",\n'
                '            "severity": "critical" | "high" | "medium" | "low"\n'
                '        }\n'
                '    ],\n'
                '    "risk_areas": ["<app areas that need more testing>"],\n'
                '    "summary": "<one paragraph overall analysis>"\n'
                '}',
                preamble="Return JSON:",
            )
            .build()
        )

    # ── Coverage risk assessment ─────────────────────────────────────

    @staticmethod
    def coverage_risk(
        coverage: Dict[str, Any],
        screens: Dict[str, Any],
        tested_features: List[str],
    ) -> str:
        """Build prompt for assessing testing coverage risk."""
        return (
            PromptBuilder()
            .preamble(
                "Assess the testing coverage risk for this mobile app session."
            )
            .section_json("COVERAGE METRICS", coverage)
            .section_json("SCREENS DISCOVERED (with visit counts)", screens)
            .section("FEATURES TESTED", json.dumps(tested_features))
            .json_output(
                '{\n'
                '    "overall_risk": "low" | "medium" | "high" | "critical",\n'
                '    "undertested_areas": [\n'
                '        {\n'
                '            "area": "<screen or feature>",\n'
                '            "reason": "<why it\'s undertested>",\n'
                '            "recommendation": "<what to test next>"\n'
                '        }\n'
                '    ],\n'
                '    "confidence_score": "0.0-1.0",\n'
                '    "summary": "<one paragraph assessment>"\n'
                '}',
                preamble="Return JSON:",
            )
            .build()
        )
