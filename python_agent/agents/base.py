"""
Base class & shared utilities for all agents in the multi-agent system.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..logging_config import get_logger
from ..vlm import (
    get_text_response,
    get_vlm_response,
    get_vlm_response_cached,
    VLMUnavailable,
    VLMQuotaExceeded,
)


class BaseAgent:
    """
    Thin wrapper around the LLM call with role-specific system context.

    Every specialist agent subclasses this and provides its own
    ``system_role`` and helper methods.
    """

    name: str = "base"
    system_role: str = "You are a helpful AI assistant."

    def __init__(self):
        self._call_count = 0
        self.logger = get_logger(f"agents.{self.name}")

    # ── LLM helpers ──────────────────────────────────────────────────

    def ask_text(self, prompt: str) -> str:
        """Send a text-only prompt prefixed with the system role."""
        full_prompt = f"{self.system_role}\n\n{prompt}"
        self._call_count += 1
        self.logger.debug("ask_text  call #%d  prompt_len=%d", self._call_count, len(prompt))
        try:
            response = get_text_response(full_prompt)
            self.logger.debug("ask_text  response_len=%d", len(response))
            return response
        except Exception as exc:
            self.logger.error("ask_text  failed: %s", exc, exc_info=True)
            raise

    def ask_vision(self, image_path: str, prompt: str) -> str:
        """Send an image + prompt prefixed with the system role."""
        full_prompt = f"{self.system_role}\n\n{prompt}"
        self._call_count += 1
        self.logger.debug("ask_vision  call #%d  image=%s  prompt_len=%d", self._call_count, image_path, len(prompt))
        try:
            response = get_vlm_response(image_path, full_prompt)
            self.logger.debug("ask_vision  response_len=%d", len(response))
            return response
        except Exception as exc:
            self.logger.error("ask_vision  failed: %s", exc, exc_info=True)
            raise

    def ask_vision_cached(self, image_path: str, prompt: str,
                          state_sig: str | None = None) -> str:
        """Vision call with per-screen caching.

        If *state_sig* is provided and the screen has been analysed before,
        the cached visual description is prepended and the request is
        answered by the fast *text-only* model.  Otherwise a real VLM
        call is made (and the result cached for next time).
        """
        full_prompt = f"{self.system_role}\n\n{prompt}"
        self._call_count += 1
        self.logger.debug(
            "ask_vision_cached  call #%d  sig=%s  image=%s",
            self._call_count, (state_sig or "")[:16], image_path,
        )
        try:
            response = get_vlm_response_cached(image_path, full_prompt,
                                               state_sig=state_sig)
            self.logger.debug("ask_vision_cached  response_len=%d", len(response))
            return response
        except Exception as exc:
            self.logger.error("ask_vision_cached  failed: %s -- falling back to text-only", exc)
            # Fallback: try text-only with whatever cached analysis exists
            try:
                from vlm import get_text_response
                fallback = get_text_response(full_prompt)
                self.logger.info("ask_vision_cached  text-only fallback succeeded (len=%d)", len(fallback))
                return fallback
            except Exception:
                raise exc  # re-raise original if fallback also fails

    # ── JSON parsing ─────────────────────────────────────────────────

    @staticmethod
    def parse_json(text: str) -> Optional[Any]:
        """Best-effort JSON extraction from an LLM response."""
        text = text.strip()
        # Try stripping markdown fences
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # ── Sanitise common LLM quirks ───────────────────────────────
        cleaned = BaseAgent._sanitise_json(text)

        if cleaned != text:
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

        # Last-resort: find the first { ... } or [ ... ]
        for opener, closer in [("{", "}"), ("[", "]")]:
            start = text.find(opener)
            end = text.rfind(closer)
            if start != -1 and end > start:
                candidate = text[start:end + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
                # Try cleaning the candidate too
                candidate_clean = BaseAgent._sanitise_json(candidate)
                try:
                    return json.loads(candidate_clean)
                except json.JSONDecodeError:
                    pass

        # ── Truncation repair: close unmatched brackets ──────────────
        # Cloud models sometimes have their output truncated mid-JSON.
        repaired = BaseAgent._repair_truncated_json(text)
        if repaired is not None:
            return repaired

        return None

    @staticmethod
    def _sanitise_json(text: str) -> str:
        """Remove comments, trailing commas, and other common LLM quirks."""
        cleaned = text
        # Remove single-line comments  (// ...)
        cleaned = re.sub(r'//[^\n]*', '', cleaned)
        # Remove trailing commas before } or ]
        cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
        # Replace single quotes with double quotes (rough heuristic)
        if '"' not in cleaned and "'" in cleaned:
            cleaned = cleaned.replace("'", '"')
        return cleaned

    @staticmethod
    def _repair_truncated_json(text: str) -> Optional[Any]:
        """
        Attempt to repair truncated JSON by closing unmatched brackets.

        This is useful when cloud LLM responses are cut off mid-stream,
        leaving syntactically incomplete but structurally valid JSON.
        """
        # Find the start of JSON
        start = -1
        for i, ch in enumerate(text):
            if ch in ('{', '['):
                start = i
                break
        if start == -1:
            return None

        # Work with cleaned text from JSON start
        candidate = BaseAgent._sanitise_json(text[start:])

        # Count unmatched brackets (ignoring those inside strings)
        stack: list[str] = []
        in_string = False
        escape_next = False
        last_valid_pos = 0

        for i, ch in enumerate(candidate):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in ('{', '['):
                stack.append('}' if ch == '{' else ']')
            elif ch in ('}', ']'):
                if stack and stack[-1] == ch:
                    stack.pop()
                    last_valid_pos = i
                # Mismatched close  --  ignore it

        if not stack:
            # JSON is balanced  --  nothing to repair
            return None

        # Truncate to the last complete value boundary and close brackets.
        # Find the last comma, colon, or complete value before the end.
        truncated = candidate.rstrip()

        # Remove any trailing partial value (e.g. a string missing its closing quote)
        if in_string:
            # We're in an unterminated string  --  drop back to just before it
            last_quote = truncated.rfind('"')
            if last_quote > 0:
                truncated = truncated[:last_quote]
                # Remove orphaned key-colon that preceded the value,
                # e.g.  ... , "description":   →  trim back to the comma
                truncated = truncated.rstrip()
                if truncated.endswith(':'):
                    truncated = truncated[:-1].rstrip()
                    # Strip the key itself (a quoted string)
                    if truncated.endswith('"'):
                        key_q = truncated.rfind('"', 0, len(truncated) - 1)
                        if key_q >= 0:
                            truncated = truncated[:key_q].rstrip().rstrip(',')
                else:
                    truncated = truncated.rstrip(',')

        # Remove trailing comma 
        truncated = truncated.rstrip().rstrip(',')

        # Close all remaining brackets
        closing = ''.join(reversed(stack))
        repaired = truncated + closing

        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        # Second attempt: more aggressive  --  chop back to last complete element
        # Look for last '}' or ']' that could be a complete value
        for trim_pos in range(len(truncated) - 1, max(0, len(truncated) - 200), -1):
            if truncated[trim_pos] in ('}', ']'):
                attempt = truncated[:trim_pos + 1]
                # Re-count stack for this substring
                sub_stack: list[str] = []
                sub_in_str = False
                sub_esc = False
                for ch in attempt:
                    if sub_esc:
                        sub_esc = False
                        continue
                    if ch == '\\' and sub_in_str:
                        sub_esc = True
                        continue
                    if ch == '"':
                        sub_in_str = not sub_in_str
                        continue
                    if sub_in_str:
                        continue
                    if ch in ('{', '['):
                        sub_stack.append('}' if ch == '{' else ']')
                    elif ch in ('}', ']'):
                        if sub_stack and sub_stack[-1] == ch:
                            sub_stack.pop()
                sub_closing = ''.join(reversed(sub_stack))
                try:
                    return json.loads(attempt + sub_closing)
                except json.JSONDecodeError:
                    continue

        return None

    @staticmethod
    def parse_json_strict(text: str, expected_keys: List[str]) -> Optional[Dict[str, Any]]:
        """Parse JSON and verify that expected keys are present."""
        obj = BaseAgent.parse_json(text)
        if not isinstance(obj, dict):
            return None
        if not all(k in obj for k in expected_keys):
            return None
        return obj

    # ── Formatting helpers ───────────────────────────────────────────

    @staticmethod
    def format_ui_elements(acc_ids: List[str], res_ids: List[str], texts: List[str]) -> str:
        return (
            f"Accessibility IDs: {json.dumps(acc_ids[:30])}\n"
            f"Resource IDs: {json.dumps(res_ids[:20])}\n"
            f"Clickable Texts: {json.dumps(texts[:20])}"
        )

    @staticmethod
    def format_action_history(actions: List[Dict[str, Any]], last_n: int = 8) -> str:
        recent = actions[-last_n:]
        if not recent:
            return "  (no actions yet)"
        lines = []
        for a in recent:
            status = "OK" if a.get("success") else "FAIL"
            lines.append(f"  [{status}] {a.get('action', '?')}: {a.get('summary', '')}")
        return "\n".join(lines)
