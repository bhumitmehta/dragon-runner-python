"""
Security Agent  --  probes the app for common mobile security weaknesses.

Tests include:
- Input validation (SQL injection, XSS, format strings, overflows)
- Authentication bypass attempts (empty creds, default creds)
- Sensitive data exposure in UI (passwords visible, tokens shown)
- Insecure data in page source / element attributes
- Deep-link / intent injection surface analysis

The agent generates hostile inputs via the LLM and uses the Navigator
pattern to inject them, then examines the result for signs of a
vulnerability.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from ..logging_config import get_logger

logger = get_logger("agents.security")


# ── Pre-built payloads (classic test vectors) ────────────────────────

_SQL_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE users;--",
    "1' UNION SELECT null,null--",
    "admin'--",
]

_XSS_PAYLOADS = [
    '<script>alert("xss")</script>',
    '"><img src=x onerror=alert(1)>',
    "javascript:alert(1)",
    "{{7*7}}",
]

_FORMAT_STRING_PAYLOADS = [
    "%s%s%s%s%s",
    "%x%x%x%x",
    "${7*7}",
    "#{7*7}",
]

_OVERFLOW_PAYLOADS = [
    "A" * 500,
    "A" * 10000,
    "\x00\x00\x00",
    "9" * 50,
]

_SPECIAL_CHAR_PAYLOADS = [
    "!@#$%^&*()",
    "../../etc/passwd",
    "\\r\\n\\r\\nHTTP/1.1 200 OK",
    "\t\n\r",
    "null",
    "undefined",
    "NaN",
    "",
    " ",
]

# Patterns that may indicate sensitive data leaking in UI/page source
#
# IMPORTANT: Android XML page source contains attributes like
#   password="false"  and  password="true"
# on *every* element.  Those are UI metadata, NOT leaked credentials.
# The regex below uses a negative lookahead to skip them.
_SENSITIVE_PATTERNS = [
    # Match "password = <value>" but NOT password="false" / password="true"
    (r'password\s*[:=]\s*["\']?(?!false|true\b)[^\s"\']{3,}', "Visible password in UI"),
    (r'token\s*[:=]\s*["\']?[A-Za-z0-9_\-]{20,}', "Auth token exposed"),
    (r'api[_-]?key\s*[:=]\s*["\']?[A-Za-z0-9_\-]{16,}', "API key exposed"),
    # Skip common Android XML attrs like focusable="true" / clickable="false"
    (r'secret\s*[:=]\s*["\']?(?!false|true\b)[^\s"\']{8,}', "Secret value exposed"),
    (r'Bearer\s+[A-Za-z0-9_\-\.]{20,}', "Bearer token in UI"),
    (r'eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+', "JWT token exposed"),
]


class SecurityAgent(BaseAgent):
    name = "security"
    system_role = (
        "You are a mobile application security tester. "
        "You examine UI elements, inputs, and screens for common "
        "security vulnerabilities. You generate hostile inputs, "
        "analyse responses for info leaks, and identify authentication "
        "weaknesses. Return structured JSON findings."
    )

    def __init__(self):
        super().__init__()
        self.findings: List[Dict[str, Any]] = []

    # ── Public API ───────────────────────────────────────────────────

    def generate_security_inputs(
        self,
        ui_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Examine the current screen and return a list of security test
        actions to try (hostile inputs, special clicks, etc.).

        Each action is a dict compatible with Navigator._do_action().
        """
        input_fields = self._find_input_fields(ui_context)
        if not input_fields:
            return []

        actions: List[Dict[str, Any]] = []

        # For each input field, generate hostile inputs
        for field in input_fields:
            field_name = (
                field.get("content-desc")
                or field.get("resource-id")
                or field.get("text", "")
            ).lower()

            payloads = self._select_payloads(field_name)
            for payload in payloads[:3]:  # Limit per field
                locator = field.get("content-desc") or field.get("resource-id")
                lt = "accessibility_id" if field.get("content-desc") else "resource_id"
                if not locator:
                    continue
                actions.append({
                    "action": "input",
                    "locator_type": lt,
                    "locator_value": locator,
                    "text": payload,
                    "direction": None,
                    "reason": f"Security test: injecting '{payload[:30]}...' into {locator}",
                    "test_type": "injection",
                })

        # Also ask LLM for app-specific security actions
        llm_actions = self._llm_security_actions(ui_context)
        actions.extend(llm_actions)

        return actions

    def check_sensitive_data(
        self,
        page_source: str,
        *,
        screen_name: str = "unknown",
    ) -> List[Dict[str, Any]]:
        """Scan the page source for leaked sensitive data (tokens, passwords, keys).

        Matches are deduplicated per (pattern-description, evidence) pair so
        that a single leaked credential is reported only once even if it
        appears in multiple XML nodes.
        """
        issues: List[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()  # (desc, evidence_prefix)

        for pattern, desc in _SENSITIVE_PATTERNS:
            matches = re.findall(pattern, page_source, re.IGNORECASE)
            for m in matches:
                key = (desc, m[:60])
                if key in seen:
                    continue
                seen.add(key)

                logger.critical("Sensitive data exposed on %s: %s", screen_name, desc)
                issue = {
                    "rule": "sensitive-data-exposure",
                    "severity": "critical",
                    "screen": screen_name,
                    "description": f"{desc}: '{m[:40]}...'",
                    "evidence": m[:60],
                }
                issues.append(issue)
                self.findings.append(issue)
        return issues

    def analyse_response(
        self,
        action: Dict[str, Any],
        pre_context: Dict[str, Any],
        post_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Analyse the app's response to a security test input.

        Returns a verdict dict with ``vulnerable`` (bool) and details.
        """
        pre_texts = set(pre_context.get("clickable_texts", []))
        post_texts = set(post_context.get("clickable_texts", []))
        new_texts = post_texts - pre_texts
        post_source = post_context.get("page_source", "")

        payload = action.get("text", "")
        verdict: Dict[str, Any] = {
            "action": action,
            "vulnerable": False,
            "severity": "info",
            "details": "No vulnerability detected",
        }

        # Check 1: Payload reflected in UI (XSS / injection echo)
        if payload and payload in " ".join(post_texts):
            verdict["vulnerable"] = True
            verdict["severity"] = "high"
            verdict["details"] = f"Payload reflected in UI text: '{payload[:50]}'"

        # Check 2: SQL/error messages visible
        error_patterns = [
            r"sql\s*(syntax|error|exception)",
            r"stack\s*trace",
            r"exception\s*in\s*thread",
            r"syntax\s*error",
            r"unhandled\s*(error|exception)",
            r"undefined\s*is\s*not",
        ]
        for ep in error_patterns:
            if re.search(ep, post_source, re.IGNORECASE):
                verdict["vulnerable"] = True
                verdict["severity"] = "critical"
                verdict["details"] = f"Error message exposed after injection (pattern: {ep})"
                break

        # Check 3: App crashed (empty screen)
        if (
            len(post_context.get("accessibility_ids", []))
            + len(post_context.get("clickable_texts", []))
        ) == 0:
            verdict["vulnerable"] = True
            verdict["severity"] = "critical"
            verdict["details"] = "App appears to have crashed after injection"

        # Check 4: Sensitive data newly visible
        leaks = self.check_sensitive_data(post_source, screen_name="post-injection")
        if leaks:
            verdict["vulnerable"] = True
            verdict["severity"] = "critical"
            verdict["details"] = f"Sensitive data exposed after injection: {leaks[0]['description']}"

        if verdict["vulnerable"]:
            self.findings.append(verdict)

        return verdict

    def audit_authentication_screen(
        self,
        ui_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Generate auth-specific security tests for login/register screens.
        """
        tests = []
        input_fields = self._find_input_fields(ui_context)

        # Detect if this looks like a login screen
        all_text = " ".join(
            ui_context.get("accessibility_ids", [])
            + ui_context.get("clickable_texts", [])
        ).lower()

        is_auth_screen = any(
            kw in all_text
            for kw in ("login", "sign in", "log in", "username", "password", "email", "register", "sign up")
        )

        if not is_auth_screen:
            return tests

        # Test: empty credentials submission
        submit_btn = None
        for txt in ui_context.get("clickable_texts", []):
            if txt.lower() in ("login", "sign in", "log in", "submit", "register", "sign up"):
                submit_btn = txt
                break

        if submit_btn:
            tests.append({
                "name": "empty_credentials",
                "severity": "high",
                "actions": [
                    {"action": "click", "locator_type": "text", "locator_value": submit_btn,
                     "reason": "Submit empty form to test validation"},
                ],
            })

        # Test: SQL injection in each field
        for field in input_fields:
            locator = field.get("content-desc") or field.get("resource-id")
            lt = "accessibility_id" if field.get("content-desc") else "resource_id"
            if locator:
                tests.append({
                    "name": f"sql_injection_{locator}",
                    "severity": "critical",
                    "actions": [
                        {"action": "input", "locator_type": lt, "locator_value": locator,
                         "text": "' OR '1'='1", "reason": "SQL injection in auth field"},
                    ],
                })

        return tests

    def full_report(self) -> Dict[str, Any]:
        """Aggregated security findings."""
        critical = sum(1 for f in self.findings if f.get("severity") == "critical")
        high = sum(1 for f in self.findings if f.get("severity") == "high")
        return {
            "total_findings": len(self.findings),
            "critical": critical,
            "high": high,
            "medium": sum(1 for f in self.findings if f.get("severity") == "medium"),
            "findings": self.findings,
            "risk_level": (
                "critical" if critical > 0 else
                "high" if high > 0 else
                "medium" if self.findings else
                "low"
            ),
        }

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _find_input_fields(ui_context: Dict[str, Any]) -> List[Dict[str, str]]:
        """Extract input fields from the page source (class contains EditText)."""
        import xml.etree.ElementTree as ET
        page_source = ui_context.get("page_source", "")
        if not page_source:
            return []
        try:
            root = ET.fromstring(page_source)
        except Exception:
            return []

        fields = []
        for el in root.iter():
            cls = el.attrib.get("class", "")
            if "EditText" in cls or el.attrib.get("password") == "true":
                fields.append({
                    "class": cls,
                    "resource-id": el.attrib.get("resource-id", ""),
                    "content-desc": el.attrib.get("content-desc", ""),
                    "text": el.attrib.get("text", ""),
                    "password": el.attrib.get("password", "false"),
                })
        return fields

    @staticmethod
    def _select_payloads(field_name: str) -> List[str]:
        """Select the most relevant payloads for a field based on its name."""
        payloads: List[str] = []

        if any(kw in field_name for kw in ("password", "passwd", "secret")):
            payloads.extend(_SQL_PAYLOADS[:2])
            payloads.extend(_OVERFLOW_PAYLOADS[:1])
        elif any(kw in field_name for kw in ("email", "user", "login", "name")):
            payloads.extend(_SQL_PAYLOADS[:2])
            payloads.extend(_XSS_PAYLOADS[:1])
        elif any(kw in field_name for kw in ("search", "query", "url", "link")):
            payloads.extend(_XSS_PAYLOADS[:2])
            payloads.extend(_FORMAT_STRING_PAYLOADS[:1])
        elif any(kw in field_name for kw in ("amount", "price", "quantity", "number")):
            payloads.extend(["-1", "0", "99999999", "NaN", "1e308"])
        else:
            # Generic mix
            payloads.extend(_SQL_PAYLOADS[:1])
            payloads.extend(_XSS_PAYLOADS[:1])
            payloads.extend(_SPECIAL_CHAR_PAYLOADS[:2])

        return payloads

    def _llm_security_actions(self, ui_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Ask the LLM for app-specific security test vectors."""
        acc = json.dumps(ui_context.get("accessibility_ids", [])[:25])
        txt = json.dumps(ui_context.get("clickable_texts", [])[:15])

        prompt = f"""Analyse this mobile app screen for security test opportunities.

AVAILABLE ELEMENTS:
Accessibility IDs: {acc}
Clickable Texts: {txt}

Suggest up to 3 security test actions specific to this screen.
Consider: authentication bypass, privilege escalation, data leaks, injection.

Return ONLY a JSON array:
[
    {{
        "action": "click" | "input",
        "locator_type": "accessibility_id" | "text",
        "locator_value": "<exact ID from lists>",
        "text": "<hostile input>" | null,
        "reason": "<what vulnerability this tests>",
        "test_type": "<injection|auth_bypass|data_leak|logic_flaw>"
    }}
]"""

        try:
            raw = self.ask_text(prompt)
            parsed = self.parse_json(raw)
            if isinstance(parsed, list):
                return [a for a in parsed if isinstance(a, dict) and "action" in a][:3]
        except Exception:
            pass
        return []
