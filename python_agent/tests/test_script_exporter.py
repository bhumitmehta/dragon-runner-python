from pathlib import Path

from python_agent.script_exporter import export_script_to_playwright


def test_export_playwright_script_creates_file(tmp_path: Path) -> None:
    script = {
        "name": "Verify login flow",
        "steps": [
            {
                "action": "click",
                "locator_type": "accessibility_id",
                "locator_value": "login_button",
                "description": "Tap the login button",
            },
            {
                "action": "input",
                "locator_type": "resource_id",
                "locator_value": "username_input",
                "text": "user@example.com",
                "description": "Enter the username",
            },
            {
                "action": "wait",
                "duration": 1.2,
                "description": "Wait for the login transition",
            },
        ],
        "assertions": [
            {
                "type": "assert_visible",
                "locator_type": "text",
                "locator_value": "Welcome",
                "description": "The welcome message should be visible",
            }
        ],
    }

    output_path = export_script_to_playwright(script, target_dir=tmp_path)
    assert output_path.exists(), "Generated Playwright script file must exist"
    contents = output_path.read_text(encoding="utf-8")
    assert "import { test, expect } from '@playwright/test'" in contents
    assert "Verify login flow" in contents
    assert "await clickTarget(page" in contents
    assert "assert_visible" not in contents
    assert "toBeVisible()" in contents
