from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from .config import ARTIFACTS_DIR
from .logging_config import get_logger

logger = get_logger("script_exporter")
SCRIPT_OUTPUT_DIR = ARTIFACTS_DIR / "playwright_tests"
SCRIPT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:120] or "script"


def _js_literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_locator(locator_type: str, locator_value: str) -> str:
    locator_object = {
        "type": locator_type,
        "value": locator_value,
    }
    return _js_literal(locator_object)


def _render_action_step(step: Dict[str, Any]) -> str:
    action = step.get("action", "click")
    desc = step.get("description", "").replace("\n", " ").strip()
    locator_type = step.get("locator_type", "text")
    locator_value = step.get("locator_value", "")
    text_value = step.get("text", "")
    locator_expr = _render_locator(locator_type, locator_value)
    comment = f"// {desc}" if desc else "// action step"

    if action == "wait":
        duration = step.get("duration", 1.0)
        return f"  {comment}\n  await page.waitForTimeout({float(duration) * 1000});"

    if action == "click":
        if locator_value:
            return f"  {comment}\n  await clickTarget(page, {locator_expr});"
        return f"  {comment}\n  await clickByDescription(page, {json.dumps(desc)});"

    if action == "input":
        args = _js_literal(text_value)
        if locator_value:
            return f"  {comment}\n  await fillTarget(page, {locator_expr}, {args});"
        return f"  {comment}\n  await fillByDescription(page, {json.dumps(desc)}, {args});"

    if action == "scroll":
        return f"  {comment}\n  await page.keyboard.press('PageDown');"

    if action == "back":
        return f"  {comment}\n  await page.goBack();"

    return f"  {comment}\n  await page.locator({json.dumps(locator_value)}).click();"


def _render_assertion(assertion: Dict[str, Any]) -> str:
    a_type = assertion.get("type", "assert_visible")
    desc = assertion.get("description", "").replace("\n", " ").strip()
    locator_type = assertion.get("locator_type", "text")
    locator_value = assertion.get("locator_value", "")
    expected = assertion.get("expected", "")
    comment = f"// {desc}" if desc else "// assertion"
    locator_expr = _render_locator(locator_type, locator_value)

    if a_type == "assert_visible":
        return f"  {comment}\n  await expect(findLocator(page, {locator_expr})).toBeVisible();"
    if a_type == "assert_not_visible":
        return f"  {comment}\n  await expect(findLocator(page, {locator_expr})).not.toBeVisible();"
    if a_type == "assert_text":
        escaped = json.dumps(expected)
        return (
            f"  {comment}\n"
            f"  await expect(findLocator(page, {locator_expr})).toContainText({escaped});"
        )
    if a_type == "assert_count":
        count = 0
        try:
            count = int(expected)
        except (TypeError, ValueError):
            count = 0
        return (
            f"  {comment}\n"
            f"  await expect(findLocator(page, {locator_expr})).toHaveCount({count});"
        )
    if a_type == "assert_order":
        return f"  {comment}\n  // TODO: verify ordering: {json.dumps(expected)}"

    return f"  {comment}\n  await expect(findLocator(page, {locator_expr})).toBeVisible();"


def _render_header(script_name: str) -> str:
    safe_name = script_name.replace('"', "\\\"")
    return (
        "import { test, expect } from '@playwright/test';\n\n"
        "async function findLocator(page, locator) {\n"
        "  const value = locator && locator.value ? locator.value.toString().trim() : '';\n"
        "  if (!value) { throw new Error('Locator text required'); }\n"
        "  switch (locator.type) {\n"
        "    case 'accessibility_id':\n"
        "      return page.getByLabel(value, { exact: false }).first();\n"
        "    case 'resource_id':\n"
        "      return page.locator(`[data-testid=\"${value}\"], [id=\"${value}\"], [name=\"${value}\"]`).first();\n"
        "    case 'text':\n"
        "      return page.getByText(value, { exact: false }).first();\n"
        "    default:\n"
        "      return page.locator(value).first();\n"
        "  }\n"
        "}\n\n"
        "async function clickTarget(page, locator) {\n"
        "  const element = await findLocator(page, locator);\n"
        "  await element.click();\n"
        "}\n\n"
        "async function fillTarget(page, locator, text) {\n"
        "  const element = await findLocator(page, locator);\n"
        "  await element.fill(text);\n"
        "}\n\n"
        "async function clickByDescription(page, description) {\n"
        "  return page.locator(`text=${description}`).first().click();\n"
        "}\n\n"
        "async function fillByDescription(page, description, text) {\n"
        "  return page.locator(`text=${description}`).first().fill(text);\n"
        "}\n\n"
        f"test({json.dumps(script_name)}, async ({{ page }}) => {{\n"
    )


def _render_footer() -> str:
    return "});\n"


def export_script_to_playwright(
    script: Dict[str, Any],
    target_dir: Optional[Path] = None,
    filename: Optional[str] = None,
) -> Path:
    target_dir = target_dir or SCRIPT_OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    script_name = script.get("name", "Generated Test")
    base_filename = filename or _sanitize_filename(script_name)
    output_path = target_dir / f"{base_filename}.spec.js"
    if output_path.exists():
        suffix = 1
        while (target_dir / f"{base_filename}_{suffix}.spec.js").exists():
            suffix += 1
        output_path = target_dir / f"{base_filename}_{suffix}.spec.js"

    lines = [
        _render_header(script_name),
    ]

    steps = script.get("steps", [])
    assertions = script.get("assertions", [])
    if steps:
        for step in steps:
            lines.append(_render_action_step(step))
    if assertions:
        lines.append("  // Assertions")
        for assertion in assertions:
            lines.append(_render_assertion(assertion))

    lines.append(_render_footer())
    contents = "\n".join(lines)
    output_path.write_text(contents, encoding="utf-8")
    logger.info("Exported Playwright script: %s", output_path)
    return output_path


def export_verification_script(script: Dict[str, Any], doc_id: Optional[int] = None) -> Path:
    filename = None
    if doc_id is not None:
        base = _sanitize_filename(script.get("name", "verification_script"))
        filename = f"{base}_{doc_id}"
    return export_script_to_playwright(script, filename=filename)
