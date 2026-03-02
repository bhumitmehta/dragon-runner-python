"""
Accessibility Agent  --  tests WCAG / mobile accessibility compliance.

Analyses each screen for:
- Missing content descriptions (accessibility labels)
- Touch targets that are too small (< 48 dp)
- Low contrast text (when vision model is available)
- Focusability / screen-reader traversal order
- Meaningful labelling of interactive elements

The agent works on the raw XML page source so it doesn't need the LLM
for structural checks, and only calls the LLM for subjective / visual
assessments.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from ..logging_config import get_logger

logger = get_logger("agents.accessibility")


# Android minimum touch target = 48dp (Material Design guideline)
_MIN_TOUCH_DP = 48


class AccessibilityAgent(BaseAgent):
    name = "accessibility"
    system_role = (
        "You are a mobile accessibility (a11y) specialist. "
        "You evaluate screenshots and UI trees against WCAG 2.1 mobile "
        "guidelines and Android accessibility best practices. "
        "Return structured JSON findings with severity ratings."
    )

    def __init__(self):
        super().__init__()
        self.findings: List[Dict[str, Any]] = []

    # ── Public API ───────────────────────────────────────────────────

    def audit_screen(
        self,
        page_source: str,
        *,
        screenshot_path: Optional[str] = None,
        screen_name: str = "unknown",
    ) -> Dict[str, Any]:
        """
        Run a full accessibility audit on a single screen.

        Returns a dict with ``issues`` (list) and ``score`` (0-100).
        """
        issues: List[Dict[str, Any]] = []
        logger.debug("Auditing screen: %s", screen_name)

        # Structural checks (fast, no LLM)
        issues.extend(self._check_missing_labels(page_source))
        issues.extend(self._check_small_touch_targets(page_source))
        issues.extend(self._check_duplicated_labels(page_source))
        issues.extend(self._check_focusable_non_interactive(page_source))

        # Visual checks via LLM (if screenshot available)
        if screenshot_path:
            visual = self._visual_accessibility_check(screenshot_path, page_source)
            issues.extend(visual)

        # Compute score: 100 minus deductions
        deductions = sum(
            {"critical": 20, "major": 10, "minor": 3, "info": 0}.get(i.get("severity", "info"), 5)
            for i in issues
        )
        score = max(0, 100 - deductions)

        result = {
            "screen": screen_name,
            "issues": issues,
            "issue_count": len(issues),
            "score": score,
        }
        self.findings.append(result)
        logger.info("A11y audit: screen=%s score=%d issues=%d", screen_name[:30], score, len(issues))
        return result

    def full_report(self) -> Dict[str, Any]:
        """Return aggregated findings across all audited screens."""
        total_issues = sum(f["issue_count"] for f in self.findings)
        avg_score = (
            sum(f["score"] for f in self.findings) / len(self.findings)
            if self.findings else 100
        )
        critical = sum(
            1 for f in self.findings for i in f["issues"]
            if i.get("severity") == "critical"
        )
        return {
            "screens_audited": len(self.findings),
            "total_issues": total_issues,
            "critical_issues": critical,
            "average_score": round(avg_score, 1),
            "per_screen": self.findings,
        }

    # ── Structural checks ────────────────────────────────────────────

    def _check_missing_labels(self, page_source: str) -> List[Dict[str, Any]]:
        """Find clickable/focusable elements without content descriptions."""
        issues = []
        for el in self._iter_elements(page_source):
            if el.attrib.get("clickable") != "true" and el.attrib.get("focusable") != "true":
                continue
            content_desc = (el.attrib.get("content-desc") or "").strip()
            text = (el.attrib.get("text") or "").strip()
            if not content_desc and not text:
                cls = el.attrib.get("class", "").split(".")[-1]
                rid = el.attrib.get("resource-id", "")
                issues.append({
                    "rule": "missing-label",
                    "severity": "major",
                    "element": rid or cls or el.tag,
                    "description": (
                        f"Interactive element <{cls}> (resource-id='{rid}') "
                        "has no content-desc or text -- screen readers cannot identify it."
                    ),
                    "guideline": "WCAG 1.1.1 / Android: contentDescription",
                })
        return issues

    def _check_small_touch_targets(self, page_source: str) -> List[Dict[str, Any]]:
        """Find clickable elements whose bounds are smaller than 48dp."""
        issues = []
        for el in self._iter_elements(page_source):
            if el.attrib.get("clickable") != "true":
                continue
            bounds = el.attrib.get("bounds", "")
            w, h = self._parse_bounds(bounds)
            if w > 0 and h > 0 and (w < _MIN_TOUCH_DP or h < _MIN_TOUCH_DP):
                label = (
                    el.attrib.get("content-desc")
                    or el.attrib.get("text")
                    or el.attrib.get("resource-id")
                    or el.tag
                )
                issues.append({
                    "rule": "small-touch-target",
                    "severity": "major",
                    "element": label,
                    "description": (
                        f"Touch target for '{label}' is {w}x{h}dp -- "
                        f"below the {_MIN_TOUCH_DP}dp minimum."
                    ),
                    "guideline": "WCAG 2.5.5 / Material Design 48dp minimum",
                })
        return issues

    def _check_duplicated_labels(self, page_source: str) -> List[Dict[str, Any]]:
        """Detect multiple interactive elements sharing the same label."""
        labels: Dict[str, int] = {}
        for el in self._iter_elements(page_source):
            if el.attrib.get("clickable") != "true":
                continue
            label = (el.attrib.get("content-desc") or el.attrib.get("text") or "").strip()
            if label:
                labels[label] = labels.get(label, 0) + 1

        issues = []
        for label, count in labels.items():
            if count > 1:
                issues.append({
                    "rule": "duplicate-label",
                    "severity": "minor",
                    "element": label,
                    "description": (
                        f"Label '{label}' is used on {count} interactive elements -- "
                        "screen reader users cannot distinguish them."
                    ),
                    "guideline": "WCAG 1.3.1 / Unique labelling",
                })
        return issues

    def _check_focusable_non_interactive(self, page_source: str) -> List[Dict[str, Any]]:
        """Find elements that are focusable but not clickable (confusing for a11y)."""
        issues = []
        for el in self._iter_elements(page_source):
            if (
                el.attrib.get("focusable") == "true"
                and el.attrib.get("clickable") != "true"
                and el.attrib.get("enabled") == "true"
            ):
                cls = el.attrib.get("class", "").split(".")[-1]
                # Skip known non-interactive focusable classes
                if cls in ("View", "ScrollView", "RecyclerView", "ViewGroup", "FrameLayout", "LinearLayout"):
                    continue
                rid = el.attrib.get("resource-id", "")
                issues.append({
                    "rule": "focusable-non-interactive",
                    "severity": "minor",
                    "element": rid or cls,
                    "description": (
                        f"Element <{cls}> is focusable but not clickable -- "
                        "may confuse screen reader navigation."
                    ),
                    "guideline": "Android a11y: focusable/clickable consistency",
                })
        return issues

    # ── Visual (LLM) checks ─────────────────────────────────────────

    def _visual_accessibility_check(
        self,
        screenshot_path: str,
        page_source: str,
    ) -> List[Dict[str, Any]]:
        """Use the vision model to spot visual accessibility issues."""
        prompt = """Analyse this mobile app screenshot for accessibility issues.

Check for:
1. Low-contrast text (text hard to read against background)
2. Information conveyed only by colour (no text/icon alternative)
3. Cluttered layouts that may confuse screen reader users
4. Missing visual focus indicators
5. Text that is too small to read comfortably

Return ONLY a JSON array of issues found (empty array if none):
[
    {
        "rule": "<short rule name>",
        "severity": "critical" | "major" | "minor" | "info",
        "description": "<what the issue is>",
        "guideline": "<which WCAG guideline is violated>"
    }
]"""

        try:
            # Use cached screen analysis when a state_sig is available
            raw = self.ask_vision_cached(screenshot_path, prompt,
                                         state_sig=getattr(self, '_current_state_sig', None))
            parsed = self.parse_json(raw)
            if isinstance(parsed, list):
                return [i for i in parsed if isinstance(i, dict)]
        except Exception:
            pass
        return []

    # ── Utilities ────────────────────────────────────────────────────

    @staticmethod
    def _iter_elements(page_source: str):
        if not page_source:
            return []
        try:
            root = ET.fromstring(page_source)
            return root.iter()
        except Exception:
            return []

    @staticmethod
    def _parse_bounds(bounds_str: str) -> tuple[int, int]:
        """Parse Android bounds string '[x1,y1][x2,y2]' → (width, height)."""
        try:
            parts = bounds_str.replace("][", ",").strip("[]").split(",")
            if len(parts) == 4:
                x1, y1, x2, y2 = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                return x2 - x1, y2 - y1
        except (ValueError, IndexError):
            pass
        return 0, 0
