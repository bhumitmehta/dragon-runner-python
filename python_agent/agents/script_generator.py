"""
ScriptGenerator Agent -- generates verification test scripts on-the-fly.

Given a feature to test (e.g. "sort products ascending"), the agent produces
a structured verification script: a sequence of actions + assertions that
can be executed by the ScriptExecutor.

Scripts are stored in the KnowledgeBase for reuse across runs.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from ..logging_config import get_logger

logger = get_logger("agents.script_generator")


class ScriptGeneratorAgent(BaseAgent):
    name = "script_generator"
    system_role = (
        "You are a mobile QA automation engineer. "
        "Given a feature description and the current UI elements, you generate "
        "a concrete test script as a JSON action sequence. Each step is a single "
        "UI action (click, input, scroll, back, assert_visible, assert_text, "
        "assert_order, assert_count). You must ONLY reference element IDs that "
        "appear in the provided lists."
    )

    # ── Public API ───────────────────────────────────────────────────

    def generate_verification_script(
        self,
        feature: Dict[str, Any],
        ui_elements: Dict[str, List[str]],
        *,
        screen_graph_summary: str = "",
        nav_script_steps: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a verification script for a feature.

        Returns a dict with keys:
            name, description, feature_id, precondition_steps, steps, assertions
        """
        acc = json.dumps(ui_elements.get("accessibility_ids", [])[:40])
        res = json.dumps(ui_elements.get("resource_ids", [])[:25])
        txt = json.dumps(ui_elements.get("clickable_texts", [])[:25])

        hints = feature.get("verification_hints", [])
        hints_str = "\n".join(f"  - {h}" for h in hints) if hints else "  (none provided)"

        nav_hint = ""
        if nav_script_steps:
            nav_hint = f"\nPRECONDITION NAVIGATION (already handled, starts from home):\n{json.dumps(nav_script_steps[:10], indent=2)}\n"

        graph_hint = ""
        if screen_graph_summary:
            graph_hint = f"\nKNOWN SCREEN GRAPH:\n{screen_graph_summary[:1500]}\n"

        prompt = f"""Generate a verification test script for this feature:

FEATURE: {feature.get('name', 'Unknown')}
DESCRIPTION: {feature.get('description', '')}
PRIORITY: {feature.get('priority', 'medium')}
VERIFICATION HINTS:
{hints_str}
{nav_hint}{graph_hint}
CURRENT UI ELEMENTS:
Accessibility IDs: {acc}
Resource IDs: {res}
Clickable Texts: {txt}

Return a JSON object with this exact structure:
{{
  "name": "Verify {feature.get('name', 'feature')}",
  "description": "<what this script tests>",
  "feature_id": "{feature.get('id', '')}",
  "steps": [
    {{
      "action": "click" | "input" | "scroll" | "back" | "wait",
      "locator_type": "accessibility_id" | "resource_id" | "text" | "xpath",
      "locator_value": "<element identifier>",
      "text": "<text to input, only for input action>",
      "description": "<human-readable description of this step>"
    }}
  ],
  "assertions": [
    {{
      "type": "assert_visible" | "assert_text" | "assert_order" | "assert_count" | "assert_not_visible",
      "locator_type": "accessibility_id" | "resource_id" | "text",
      "locator_value": "<element to check>",
      "expected": "<expected value or condition>",
      "description": "<what this assertion verifies>"
    }}
  ]
}}

RULES:
- steps: 1-8 UI actions to set up the test scenario. Keep it SHORT.
- assertions: 1-3 checks that verify the feature works correctly.
- For the FIRST step: use an element ID that EXACTLY appears in the lists above.
- For LATER steps that happen AFTER the UI changes (e.g. a popup/modal/overlay appears
  after tapping a button): set locator_value to "" (empty) and write a CLEAR description.
  The executor will dynamically resolve the element at runtime against the actual screen.
  Example: after clicking a sort button, a popup appears with new options  --  the next step
  should describe "Select the 'Price (Low to High)' option from the popup" with locator_value="".
- For assert_visible/assert_not_visible: locator_value should be a keyword likely to appear
  in the element's accessibility id, resource id, or text.
- For assert_order: expected should describe the ordering, e.g. "ascending by price".
- For assert_count: expected should be a number string, e.g. "1".
- For assert_text: expected is the text that should appear on the element.
- Use action "wait" with a "duration" field (in seconds) for pauses.
- The "description" field is CRITICAL  --  it must be a clear human-readable instruction
  that can be followed even without knowing the locator. The executor uses it as fallback.
- Return ONLY the JSON object, no explanation.
"""
        raw = self.ask_text(prompt)
        return self._parse_script(raw)

    def generate_nav_script(
        self,
        target_screen_name: str,
        ui_elements: Dict[str, List[str]],
        *,
        screen_graph_summary: str = "",
        action_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a navigation script to reach a target screen from home.
        """
        acc = json.dumps(ui_elements.get("accessibility_ids", [])[:40])
        res = json.dumps(ui_elements.get("resource_ids", [])[:25])
        txt = json.dumps(ui_elements.get("clickable_texts", [])[:25])

        history_hint = ""
        if action_history:
            recent = action_history[-10:]
            history_hint = "\nRECENT ACTIONS THAT REACHED THIS SCREEN:\n"
            for a in recent:
                status = "OK" if a.get("success") else "FAIL"
                history_hint += f"  [{status}] {a.get('action','?')}: {a.get('locator','?')} -> {a.get('description','')[:40]}\n"

        graph_hint = ""
        if screen_graph_summary:
            graph_hint = f"\nKNOWN SCREEN GRAPH:\n{screen_graph_summary[:1500]}\n"

        prompt = f"""Generate a navigation script to reach the "{target_screen_name}" screen from the app home screen.

{history_hint}{graph_hint}
CURRENT UI ELEMENTS (home screen):
Accessibility IDs: {acc}
Resource IDs: {res}
Clickable Texts: {txt}

Return a JSON object:
{{
  "name": "Navigate to {target_screen_name}",
  "target_screen": "{target_screen_name}",
  "steps": [
    {{
      "action": "click" | "input" | "scroll" | "back" | "wait",
      "locator_type": "accessibility_id" | "resource_id" | "text",
      "locator_value": "<element>",
      "text": "<optional input text>",
      "description": "<what this step does>"
    }}
  ]
}}

RULES:
- Steps should be the SHORTEST path from the current screen (home) to the target screen.
- For the FIRST step: use an element ID that EXACTLY appears in the provided lists.
- For LATER steps where the UI has changed (popups, new screens): set locator_value to ""
  and write a CLEAR description of what to tap/click. The executor resolves it dynamically.
- The "description" field is CRITICAL  --  write clear human-readable instructions.
- Use action "wait" with a "duration" field for pauses (e.g. after animation).
- Maximum 8 steps.
- Return ONLY the JSON, no explanation.
"""
        raw = self.ask_text(prompt)
        return self._parse_script(raw)

    def generate_batch_scripts(
        self,
        features: List[Dict[str, Any]],
        ui_elements: Dict[str, List[str]],
        *,
        screen_graph_summary: str = "",
        max_scripts: int = 5,
    ) -> List[Dict[str, Any]]:
        """Generate verification scripts for multiple features at once."""
        scripts = []
        for feat in features[:max_scripts]:
            try:
                script = self.generate_verification_script(
                    feat, ui_elements,
                    screen_graph_summary=screen_graph_summary,
                )
                if script:
                    scripts.append(script)
                    logger.info("Generated script: %s", script.get("name", "?"))
            except Exception as e:
                logger.warning("Failed to generate script for %s: %s",
                               feat.get("name", "?"), e)
        return scripts

    # ── Parsing ──────────────────────────────────────────────────────

    def _parse_script(self, raw: str) -> Optional[Dict[str, Any]]:
        obj = self.parse_json(raw)
        if isinstance(obj, dict) and ("steps" in obj or "assertions" in obj):
            return obj
        logger.warning("Could not parse script from LLM response (len=%d)", len(raw))
        return None
