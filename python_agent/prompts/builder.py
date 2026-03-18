"""
PromptBuilder -- fluent builder pattern for constructing structured LLM prompts.

Every agent prompt in the system follows a consistent layout:

    [System Role]

    [Context Sections]      -- UI elements, coverage, history, etc.
    [Rules / Constraints]
    [Output Format]         -- expected JSON schema or free-text instruction

The builder enforces this structure while keeping prompt construction
readable and composable.

Example
-------
    prompt = (
        PromptBuilder()
        .system("You are a QA tester.")
        .section("CURRENT UI ELEMENTS", ui_text)
        .section("COVERAGE", coverage_json)
        .rules([
            "Only use element IDs from the lists above.",
            "Never fabricate element identifiers.",
        ])
        .json_output({
            "action": "click | input | scroll",
            "locator_value": "<exact ID>",
        })
        .build()
    )
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union


class PromptBuilder:
    """Fluent builder for structured LLM prompts.

    Methods return ``self`` so calls can be chained.  Call ``.build()``
    at the end to produce the final prompt string.
    """

    def __init__(self):
        self._system_role: str = ""
        self._preamble: str = ""
        self._sections: List[tuple[str, str]] = []
        self._rules: List[str] = []
        self._json_schema: Optional[str] = None
        self._output_instruction: str = ""
        self._suffix: str = ""

    # ── Core setters (all return self for chaining) ──────────────────

    def system(self, role: str) -> "PromptBuilder":
        """Set the system-role preamble (prepended by BaseAgent.ask_*)."""
        self._system_role = role.strip()
        return self

    def preamble(self, text: str) -> "PromptBuilder":
        """Free-form opening paragraph before the structured sections."""
        self._preamble = text.strip()
        return self

    def section(self, heading: str, body: str) -> "PromptBuilder":
        """Add a labelled context section.

        Parameters
        ----------
        heading : str
            ALL-CAPS section label, e.g. ``"CURRENT UI ELEMENTS"``.
        body : str
            The content of the section (plain text, JSON dump, etc.).
        """
        self._sections.append((heading.strip(), body.strip()))
        return self

    def section_if(self, heading: str, body: str, condition: bool) -> "PromptBuilder":
        """Add a section only when *condition* is truthy."""
        if condition:
            self._sections.append((heading.strip(), body.strip()))
        return self

    def section_json(self, heading: str, data: Any, indent: int = 2) -> "PromptBuilder":
        """Add a section whose body is a JSON dump of *data*."""
        self._sections.append((heading.strip(), json.dumps(data, indent=indent, default=str)))
        return self

    def ui_elements(
        self,
        accessibility_ids: List[str],
        resource_ids: Optional[List[str]] = None,
        clickable_texts: Optional[List[str]] = None,
        *,
        acc_limit: int = 30,
        res_limit: int = 20,
        txt_limit: int = 20,
    ) -> "PromptBuilder":
        """Convenience: add a ``CURRENT UI ELEMENTS`` section from raw lists."""
        lines = [f"Accessibility IDs: {json.dumps(accessibility_ids[:acc_limit])}"]
        if resource_ids is not None:
            lines.append(f"Resource IDs: {json.dumps(resource_ids[:res_limit])}")
        if clickable_texts is not None:
            lines.append(f"Clickable Texts: {json.dumps(clickable_texts[:txt_limit])}")
        return self.section("CURRENT UI ELEMENTS", "\n".join(lines))

    def action_history(
        self,
        actions: List[Dict[str, Any]],
        last_n: int = 8,
    ) -> "PromptBuilder":
        """Convenience: add a ``RECENT ACTIONS`` section."""
        recent = actions[-last_n:]
        if not recent:
            return self.section("RECENT ACTIONS", "(no actions yet)")
        lines = []
        for a in recent:
            status = "OK" if a.get("success") else "FAIL"
            desc = a.get("summary", a.get("description", ""))
            lines.append(f"  [{status}] {a.get('action', '?')}: {desc}")
        return self.section("RECENT ACTIONS", "\n".join(lines))

    def rules(self, rule_list: List[str]) -> "PromptBuilder":
        """Set numbered rules / constraints."""
        self._rules = list(rule_list)
        return self

    def add_rule(self, rule: str) -> "PromptBuilder":
        """Append a single rule."""
        self._rules.append(rule)
        return self

    def json_output(
        self,
        schema: Union[str, Dict[str, Any]],
        *,
        preamble: str = "Return ONLY valid JSON (no markdown):",
    ) -> "PromptBuilder":
        """Set the expected JSON output schema.

        Parameters
        ----------
        schema : str or dict
            If a dict, it will be pretty-printed as a JSON example.
            If a str, used verbatim (allows ``|`` alternation in values).
        preamble : str
            Text before the schema block. Default: ``"Return ONLY valid JSON (no markdown):"``.
        """
        self._output_instruction = preamble
        if isinstance(schema, dict):
            self._json_schema = json.dumps(schema, indent=2)
        else:
            self._json_schema = schema
        return self

    def output(self, instruction: str) -> "PromptBuilder":
        """Free-form output instruction (alternative to ``json_output``)."""
        self._output_instruction = instruction.strip()
        self._json_schema = None
        return self

    def suffix(self, text: str) -> "PromptBuilder":
        """Append arbitrary text at the very end of the prompt."""
        self._suffix = text.strip()
        return self

    # ── Build ────────────────────────────────────────────────────────

    def build(self, *, include_system: bool = False) -> str:
        """Assemble the final prompt string.

        Parameters
        ----------
        include_system : bool
            If True, prepend the system role.  Usually False because
            ``BaseAgent.ask_text`` already prepends it.
        """
        parts: List[str] = []

        if include_system and self._system_role:
            parts.append(self._system_role)
            parts.append("")  # blank line separator

        if self._preamble:
            parts.append(self._preamble)
            parts.append("")

        for heading, body in self._sections:
            parts.append(f"{heading}:")
            parts.append(body)
            parts.append("")

        if self._rules:
            parts.append("RULES:")
            for i, rule in enumerate(self._rules, 1):
                parts.append(f"{i}. {rule}")
            parts.append("")

        if self._output_instruction:
            parts.append(self._output_instruction)
        if self._json_schema:
            parts.append(self._json_schema)

        if self._suffix:
            if parts and parts[-1] != "":
                parts.append("")
            parts.append(self._suffix)

        return "\n".join(parts).strip()

    # ── Clone / fork ─────────────────────────────────────────────────

    def clone(self) -> "PromptBuilder":
        """Return a shallow copy so you can fork a shared base prompt."""
        new = PromptBuilder()
        new._system_role = self._system_role
        new._preamble = self._preamble
        new._sections = list(self._sections)
        new._rules = list(self._rules)
        new._json_schema = self._json_schema
        new._output_instruction = self._output_instruction
        new._suffix = self._suffix
        return new

    def __repr__(self) -> str:
        nsec = len(self._sections)
        nrules = len(self._rules)
        return f"<PromptBuilder sections={nsec} rules={nrules} json={'yes' if self._json_schema else 'no'}>"
