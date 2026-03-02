"""
Reporter Agent  --  generates human-readable reports and insights from
the session data.

The Reporter can:
- Produce a Markdown summary of the test session
- Identify patterns across bugs (clustering, common root causes)
- Generate risk assessments based on coverage gaps
- Create executive summaries for non-technical stakeholders
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from ..logging_config import get_logger
from ..session_memory import SessionMemory

logger = get_logger("agents.reporter")


class ReporterAgent(BaseAgent):
    name = "reporter"
    system_role = (
        "You are a QA report-writing specialist. "
        "You transform raw session data (actions, bugs, coverage metrics) into "
        "clear, structured, human-readable reports in Markdown format. "
        "Be concise but thorough. Highlight critical findings prominently. "
        "Include actionable recommendations."
    )

    # ── Public API ───────────────────────────────────────────────────

    def generate_markdown_report(
        self,
        memory: SessionMemory,
        *,
        extra_stats: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate a full Markdown test report from the session memory.

        Returns the Markdown string (caller saves to disk).
        """
        raw_data = self._prepare_report_data(memory, extra_stats)
        prompt = self._build_report_prompt(raw_data)

        try:
            md = self.ask_text(prompt)
            # Ensure it starts with a heading
            if not md.strip().startswith("#"):
                md = f"# Test Session Report  --  {memory.session_id}\n\n{md}"
            logger.info("Generated Markdown report (%d chars)", len(md))
            return md
        except Exception as e:
            logger.warning("LLM report failed, using template: %s", e)
            # Fallback: produce a deterministic template report
            return self._template_report(raw_data)

    def generate_executive_summary(self, memory: SessionMemory) -> str:
        """Short 3-5 sentence summary for stakeholders."""
        data = self._prepare_report_data(memory)
        prompt = f"""Write a 3-5 sentence executive summary of this mobile app test session.

SESSION DATA:
{json.dumps(data, indent=2)}

Focus on:
1. Overall pass/fail status
2. Critical bugs found (if any)
3. Coverage percentage
4. Key recommendation

Write in plain English, no markdown formatting."""

        try:
            return self.ask_text(prompt).strip()
        except Exception:
            plan = data.get("plan_summary", {})
            bugs = data.get("bugs_count", 0)
            return (
                f"Test session {data['session_id']} completed {plan.get('tasks_done', 0)}"
                f"/{plan.get('tasks', 0)} tasks with {bugs} bug(s) found. "
                f"Overall progress: {plan.get('progress_pct', 0)}%."
            )

    def analyse_bug_patterns(self, memory: SessionMemory) -> Dict[str, Any]:
        """Ask the LLM to identify patterns across all bugs found."""
        if not memory.bugs:
            return {"patterns": [], "summary": "No bugs found."}

        bugs_data = [
            {
                "id": b.id,
                "description": b.description,
                "severity": b.severity,
                "screen": b.screen_signature,
                "task": b.task_id,
            }
            for b in memory.bugs
        ]

        prompt = f"""Analyse these bugs found during mobile app testing and identify patterns.

BUGS:
{json.dumps(bugs_data, indent=2)}

Return JSON:
{{
    "patterns": [
        {{
            "name": "<pattern name>",
            "bug_ids": ["<matching bug IDs>"],
            "description": "<what these bugs have in common>",
            "likely_root_cause": "<probable shared root cause>",
            "severity": "critical" | "high" | "medium" | "low"
        }}
    ],
    "risk_areas": ["<app areas that need more testing>"],
    "summary": "<one paragraph overall analysis>"
}}"""

        try:
            raw = self.ask_text(prompt)
            parsed = self.parse_json(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        return {
            "patterns": [],
            "risk_areas": [],
            "summary": f"{len(memory.bugs)} bugs found  --  manual analysis recommended.",
        }

    def coverage_risk_assessment(self, memory: SessionMemory) -> Dict[str, Any]:
        """Identify undertested areas and assess risk."""
        coverage = memory.coverage_summary()
        screens = {sig: {"visits": n.visit_count, "elements": len(n.elements_snapshot)}
                   for sig, n in memory.screens.items()}
        tested = list(memory.tested_features.keys())

        prompt = f"""Assess the testing coverage risk for this mobile app session.

COVERAGE METRICS:
{json.dumps(coverage, indent=2)}

SCREENS DISCOVERED (with visit counts):
{json.dumps(screens, indent=2)}

FEATURES TESTED:
{json.dumps(tested)}

Return JSON:
{{
    "overall_risk": "low" | "medium" | "high" | "critical",
    "undertested_areas": [
        {{
            "area": "<screen or feature>",
            "reason": "<why it's undertested>",
            "recommendation": "<what to test next>"
        }}
    ],
    "confidence_score": 0.0-1.0,
    "summary": "<one paragraph assessment>"
}}"""

        try:
            raw = self.ask_text(prompt)
            parsed = self.parse_json(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        return {
            "overall_risk": "medium",
            "undertested_areas": [],
            "confidence_score": 0.5,
            "summary": "Could not perform automated risk assessment.",
        }

    # ── Internals ────────────────────────────────────────────────────

    def _prepare_report_data(
        self,
        memory: SessionMemory,
        extra_stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        data = memory.full_report()
        data["recent_actions"] = memory.recent_actions(20)
        data["features_tested"] = list(memory.tested_features.keys())
        data["screen_count"] = len(memory.screens)
        data["bugs_count"] = len(memory.bugs)
        if extra_stats:
            data["agent_stats"] = extra_stats
        return data

    def _build_report_prompt(self, data: Dict[str, Any]) -> str:
        return f"""Generate a detailed Markdown test report from this session data.

SESSION DATA:
{json.dumps(data, indent=2, default=str)[:6000]}

Structure the report as:
# Test Session Report  --  {{session_id}}

## Summary
- Mode, duration, overall result

## Test Plan Progress
- Goals completed, tasks done, steps executed

## Bugs Found
- For each bug: severity, description, screen, recommended fix

## Coverage Analysis
- Screens visited, features tested, gaps identified

## Recommendations
- What to test next, risk areas, process improvements

Use tables for bug listings. Be specific and actionable."""

    def _template_report(self, data: Dict[str, Any]) -> str:
        """Deterministic fallback report when LLM is unavailable."""
        plan = data.get("plan_summary", {})
        bugs = data.get("bugs", [])
        coverage = data.get("coverage", {})

        lines = [
            f"# Test Session Report  --  {data.get('session_id', 'unknown')}",
            "",
            f"**Generated:** {datetime.utcnow().isoformat()}Z",
            f"**Mode:** {data.get('mode', 'n/a')}",
            f"**User Task:** {data.get('user_task', 'n/a')}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Goals | {plan.get('goals', 0)} |",
            f"| Tasks (done/total) | {plan.get('tasks_done', 0)}/{plan.get('tasks', 0)} |",
            f"| Steps (done/total) | {plan.get('steps_done', 0)}/{plan.get('steps', 0)} |",
            f"| Progress | {plan.get('progress_pct', 0)}% |",
            f"| Bugs Found | {len(bugs)} |",
            f"| Screens Discovered | {coverage.get('screens_discovered', 0)} |",
            "",
        ]

        if bugs:
            lines += [
                "## Bugs Found",
                "",
                "| ID | Severity | Description |",
                "|----|----------|-------------|",
            ]
            for b in bugs:
                lines.append(f"| {b.get('id', '?')} | {b.get('severity', '?')} | {b.get('description', '?')} |")
            lines.append("")

        lines += [
            "## Coverage",
            "",
            f"- Features tested: {coverage.get('features_tested', 0)}/{coverage.get('features_total', 0)}",
            f"- Total screen visits: {coverage.get('total_screen_visits', 0)}",
        ]

        return "\n".join(lines)

    def save_report(
        self,
        memory: SessionMemory,
        output_dir: Path,
        *,
        extra_stats: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """Generate and save the Markdown report to disk. Returns the file path."""
        md = self.generate_markdown_report(memory, extra_stats=extra_stats)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"report_{memory.session_id}.md"
        path.write_text(md, encoding="utf-8")
        return path
