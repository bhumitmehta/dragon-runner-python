"""
Unit tests for the multi-agent testing system.

These tests validate the internal logic of each agent and supporting
module **without** requiring a real Appium connection, emulator, or LLM.
All external calls (VLM, Appium) are mocked.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from unittest import TestCase, mock

# ── Ensure the package is importable ────────────────────────────────
# When running from the repo root:  python -m pytest python_agent/tests/
_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# ── Mock heavy optional dependencies that may not be installed ──────
# torch / transformers are only needed by bug_localization and are
# optional for running the core agent tests.
_MOCK_MODULES = [
    "torch", "torch.nn", "torch.nn.functional", "torch.cuda",
    "transformers", "transformers.models",
    "nltk", "nltk.tokenize", "nltk.corpus",
]
for _mod_name in _MOCK_MODULES:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = mock.MagicMock()


# ════════════════════════════════════════════════════════════════════════
#  Logging configuration tests
# ════════════════════════════════════════════════════════════════════════

class TestLoggingConfig(TestCase):
    """Test the centralized logging module."""

    def test_get_logger_returns_logger(self):
        from python_agent.logging_config import get_logger
        lgr = get_logger("test_module")
        import logging
        self.assertIsInstance(lgr, logging.Logger)
        self.assertTrue(lgr.name.startswith("python_agent"))

    def test_get_logger_auto_prefix(self):
        from python_agent.logging_config import get_logger
        lgr = get_logger("myagent")
        self.assertEqual(lgr.name, "python_agent.myagent")

    def test_get_logger_no_double_prefix(self):
        from python_agent.logging_config import get_logger
        lgr = get_logger("python_agent.agents.nav")
        self.assertEqual(lgr.name, "python_agent.agents.nav")

    def test_log_file_created(self):
        from python_agent.logging_config import get_logger, _LOG_FILE
        lgr = get_logger("file_check")
        lgr.info("hello from test")
        self.assertTrue(_LOG_FILE.exists(), f"Log file {_LOG_FILE} should exist")


# ════════════════════════════════════════════════════════════════════════
#  BaseAgent tests
# ════════════════════════════════════════════════════════════════════════

class TestBaseAgent(TestCase):
    """Test BaseAgent utility methods (no LLM required)."""

    def _make_agent(self):
        from python_agent.agents.base import BaseAgent
        agent = BaseAgent()
        return agent

    # ── JSON parsing ─────────────────────────────────────────────────

    def test_parse_json_plain(self):
        agent = self._make_agent()
        result = agent.parse_json('{"action": "click", "target": "btn"}')
        self.assertEqual(result, {"action": "click", "target": "btn"})

    def test_parse_json_markdown_fenced(self):
        agent = self._make_agent()
        text = '```json\n{"action": "scroll"}\n```'
        result = agent.parse_json(text)
        self.assertEqual(result, {"action": "scroll"})

    def test_parse_json_embedded_in_text(self):
        agent = self._make_agent()
        text = 'Here is the plan:\n{"goals": [1,2,3]}\nDone.'
        result = agent.parse_json(text)
        self.assertEqual(result, {"goals": [1, 2, 3]})

    def test_parse_json_array(self):
        agent = self._make_agent()
        result = agent.parse_json('[1, 2, 3]')
        self.assertEqual(result, [1, 2, 3])

    def test_parse_json_garbage(self):
        agent = self._make_agent()
        result = agent.parse_json("no json here")
        self.assertIsNone(result)

    def test_parse_json_strict_missing_key(self):
        agent = self._make_agent()
        result = agent.parse_json_strict('{"a": 1}', ["a", "b"])
        self.assertIsNone(result)

    def test_parse_json_strict_ok(self):
        agent = self._make_agent()
        result = agent.parse_json_strict('{"verdict": "pass", "reason": "ok"}', ["verdict", "reason"])
        self.assertIsNotNone(result)
        self.assertEqual(result["verdict"], "pass")

    # ── Formatting ───────────────────────────────────────────────────

    def test_format_ui_elements(self):
        agent = self._make_agent()
        text = agent.format_ui_elements(["Login"], ["btn_ok"], ["Submit"])
        self.assertIn("Login", text)
        self.assertIn("btn_ok", text)
        self.assertIn("Submit", text)

    def test_format_action_history_empty(self):
        agent = self._make_agent()
        text = agent.format_action_history([])
        self.assertIn("no actions", text)

    def test_format_action_history_with_items(self):
        agent = self._make_agent()
        actions = [
            {"success": True, "action": "click", "summary": "Clicked login"},
            {"success": False, "action": "input", "summary": "Field not found"},
        ]
        text = agent.format_action_history(actions)
        self.assertIn("[OK]", text)
        self.assertIn("[FAIL]", text)


# ════════════════════════════════════════════════════════════════════════
#  CriticAgent structural check tests
# ════════════════════════════════════════════════════════════════════════

class TestCriticStructuralCheck(TestCase):
    """Test the fast structural check (no LLM)."""

    def _make_critic(self):
        from python_agent.agents.critic import CriticAgent
        return CriticAgent()

    def _ui(self, acc_ids=None, res_ids=None, texts=None):
        return {
            "accessibility_ids": acc_ids or [],
            "resource_ids": res_ids or [],
            "clickable_texts": texts or [],
        }

    def test_click_existing_element_passes(self):
        critic = self._make_critic()
        action = {"action": "click", "locator_type": "accessibility_id", "locator_value": "Login"}
        verdict = critic._structural_check(action, self._ui(acc_ids=["Login", "Cart"]))
        self.assertEqual(verdict["verdict"], "pass")

    def test_click_missing_element_fails(self):
        critic = self._make_critic()
        action = {"action": "click", "locator_type": "accessibility_id", "locator_value": "Nonexistent"}
        verdict = critic._structural_check(action, self._ui(acc_ids=["Login"]))
        self.assertEqual(verdict["verdict"], "fail")
        self.assertIn("HALLUCINATION", verdict["reason"])

    def test_click_case_mismatch_warns(self):
        critic = self._make_critic()
        action = {"action": "click", "locator_type": "text", "locator_value": "login"}
        verdict = critic._structural_check(action, self._ui(texts=["Login"]))
        self.assertEqual(verdict["verdict"], "warn")

    def test_back_action_always_passes(self):
        critic = self._make_critic()
        action = {"action": "back"}
        verdict = critic._structural_check(action, self._ui())
        self.assertEqual(verdict["verdict"], "pass")

    def test_scroll_action_always_passes(self):
        critic = self._make_critic()
        action = {"action": "scroll", "direction": "down"}
        verdict = critic._structural_check(action, self._ui())
        self.assertEqual(verdict["verdict"], "pass")


# ════════════════════════════════════════════════════════════════════════
#  AccessibilityAgent structural checks
# ════════════════════════════════════════════════════════════════════════

class TestAccessibilityChecks(TestCase):
    """Test structural accessibility checks (no LLM)."""

    def _make_agent(self):
        from python_agent.agents.accessibility import AccessibilityAgent
        return AccessibilityAgent()

    def test_missing_labels_detected(self):
        agent = self._make_agent()
        xml = textwrap.dedent("""\
        <hierarchy>
          <node class="android.widget.Button"
                clickable="true" focusable="true"
                content-desc="" text=""
                resource-id="btn_no_label" bounds="[0,0][100,100]" />
          <node class="android.widget.Button"
                clickable="true" focusable="true"
                content-desc="Submit" text=""
                resource-id="btn_submit" bounds="[0,0][100,100]" />
        </hierarchy>""")
        issues = agent._check_missing_labels(xml)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["rule"], "missing-label")

    def test_small_touch_target(self):
        agent = self._make_agent()
        xml = textwrap.dedent("""\
        <hierarchy>
          <node class="android.widget.ImageButton"
                clickable="true"
                content-desc="Tiny" text=""
                resource-id="tiny_btn" bounds="[0,0][30,30]" />
          <node class="android.widget.Button"
                clickable="true"
                content-desc="Big" text=""
                resource-id="big_btn" bounds="[0,0][100,100]" />
        </hierarchy>""")
        issues = agent._check_small_touch_targets(xml)
        self.assertEqual(len(issues), 1)
        self.assertIn("30x30", issues[0]["description"])

    def test_duplicate_labels(self):
        agent = self._make_agent()
        xml = textwrap.dedent("""\
        <hierarchy>
          <node class="android.widget.Button"
                clickable="true" content-desc="Add" text=""
                bounds="[0,0][100,100]" />
          <node class="android.widget.Button"
                clickable="true" content-desc="Add" text=""
                bounds="[100,0][200,100]" />
        </hierarchy>""")
        issues = agent._check_duplicated_labels(xml)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["rule"], "duplicate-label")

    def test_parse_bounds(self):
        agent = self._make_agent()
        self.assertEqual(agent._parse_bounds("[10,20][110,120]"), (100, 100))
        self.assertEqual(agent._parse_bounds("bad"), (0, 0))

    def test_audit_screen_produces_score(self):
        agent = self._make_agent()
        xml = '<hierarchy><node class="android.view.View" /></hierarchy>'
        result = agent.audit_screen(xml, screen_name="test")
        self.assertIn("score", result)
        self.assertIn("issues", result)
        self.assertIsInstance(result["score"], int)


# ════════════════════════════════════════════════════════════════════════
#  SecurityAgent payload selection
# ════════════════════════════════════════════════════════════════════════

class TestSecurityPayloads(TestCase):
    """Test payload selection logic (no LLM)."""

    def _make_agent(self):
        from python_agent.agents.security import SecurityAgent
        return SecurityAgent()

    def test_password_field_gets_sql_payloads(self):
        agent = self._make_agent()
        payloads = agent._select_payloads("password_field")
        self.assertTrue(any("OR" in p for p in payloads))

    def test_email_field_gets_xss(self):
        agent = self._make_agent()
        payloads = agent._select_payloads("email_input")
        self.assertTrue(any("<script>" in p or "xss" in p.lower() for p in payloads))

    def test_search_field_gets_xss(self):
        agent = self._make_agent()
        payloads = agent._select_payloads("search_query")
        self.assertTrue(len(payloads) > 0)

    def test_amount_field_gets_numbers(self):
        agent = self._make_agent()
        payloads = agent._select_payloads("price_amount")
        self.assertTrue(any(p in ("-1", "0", "NaN") for p in payloads))

    def test_generic_field(self):
        agent = self._make_agent()
        payloads = agent._select_payloads("some_field")
        self.assertTrue(len(payloads) > 0)

    def test_check_sensitive_data_finds_token(self):
        agent = self._make_agent()
        page = 'token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc"'
        issues = agent.check_sensitive_data(page, screen_name="test")
        self.assertTrue(len(issues) > 0)
        self.assertEqual(issues[0]["severity"], "critical")

    def test_check_sensitive_data_clean(self):
        agent = self._make_agent()
        issues = agent.check_sensitive_data("<hierarchy><node text='Hello'/></hierarchy>", screen_name="test")
        self.assertEqual(len(issues), 0)


# ════════════════════════════════════════════════════════════════════════
#  SessionMemory persistence tests
# ════════════════════════════════════════════════════════════════════════

class TestSessionMemory(TestCase):
    """Test crash-resilient session memory save/load cycle."""

    def test_create_and_persist(self):
        from python_agent.session_memory import SessionMemory, TestPlan, TestGoal, TestTask, TestStep, TaskStatus, BugEntry

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            mem = SessionMemory(path)

            # Set a plan
            step = TestStep(id="s1", description="Click login")
            task = TestTask(id="t1", name="Login", description="Login flow", steps=[step])
            goal = TestGoal(id="g1", name="Auth", description="Auth tests", tasks=[task])
            plan = TestPlan(goals=[goal], created_at="2024-01-01T00:00:00Z")
            mem.set_plan(plan)

            # Record a screen
            mem.record_screen("sig_home", ["Login", "Cart"])

            # Log an action
            mem.log_action({"action": "click", "success": True, "description": "Clicked login"})

            # Add a bug
            mem.add_bug(BugEntry(id="bug_1", description="Login button unresponsive"))

            # Mark feature
            mem.mark_feature_tested("Login")

            # Verify file was created
            self.assertTrue(path.exists())

            # Load and verify
            mem2 = SessionMemory.load(path)
            self.assertEqual(mem2.session_id, mem.session_id)
            self.assertEqual(len(mem2.plan.goals), 1)
            self.assertEqual(mem2.plan.goals[0].tasks[0].steps[0].description, "Click login")
            self.assertIn("sig_home", mem2.screens)
            self.assertEqual(len(mem2.action_log), 1)
            self.assertEqual(len(mem2.bugs), 1)
            self.assertTrue(mem2.tested_features.get("Login"))

    def test_load_nonexistent(self):
        from python_agent.session_memory import SessionMemory

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonexistent.json"
            mem = SessionMemory.load(path)
            # Should return a fresh memory object
            self.assertEqual(len(mem.plan.goals), 0)
            self.assertEqual(len(mem.action_log), 0)

    def test_get_next_task_priority(self):
        from python_agent.session_memory import SessionMemory, TestPlan, TestGoal, TestTask, TestStep, TaskStatus

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            mem = SessionMemory(path)

            low_task = TestTask(id="t1", name="Low", description="Low priority", priority="low",
                                steps=[TestStep(id="s1", description="step")])
            high_task = TestTask(id="t2", name="High", description="High priority", priority="high",
                                 steps=[TestStep(id="s2", description="step")])
            goal = TestGoal(id="g1", name="G", description="G", tasks=[low_task, high_task])
            plan = TestPlan(goals=[goal])
            mem.set_plan(plan)

            next_task = mem.get_next_task()
            self.assertEqual(next_task.id, "t2")  # High priority first

    def test_coverage_summary(self):
        from python_agent.session_memory import SessionMemory

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            mem = SessionMemory(path)
            mem.record_screen("sig1", ["a", "b"])
            mem.record_screen("sig2", ["c"])
            mem.mark_feature_tested("Login")

            cov = mem.coverage_summary()
            self.assertEqual(cov["screens_discovered"], 2)
            self.assertEqual(cov["features_tested"], 1)

    def test_plan_summary(self):
        from python_agent.session_memory import TestPlan, TestGoal, TestTask, TestStep, TaskStatus

        step1 = TestStep(id="s1", description="a", status=TaskStatus.COMPLETED.value)
        step2 = TestStep(id="s2", description="b")
        task = TestTask(id="t1", name="T", description="D", steps=[step1, step2])
        goal = TestGoal(id="g1", name="G", description="D", tasks=[task])
        plan = TestPlan(goals=[goal])

        summary = plan.summary()
        self.assertEqual(summary["steps"], 2)
        self.assertEqual(summary["steps_done"], 1)
        self.assertEqual(summary["tasks"], 1)


# ════════════════════════════════════════════════════════════════════════
#  ExplorerAgent coverage tracking
# ════════════════════════════════════════════════════════════════════════

class TestExplorerCoverage(TestCase):
    """Test explorer coverage metrics and action recording."""

    def test_coverage_stats_initial(self):
        # Explorer needs an AppiumController but we only test the stats
        from python_agent.agents.explorer import ExplorerAgent
        with mock.patch("python_agent.agents.explorer.AppiumController"):
            agent = ExplorerAgent(mock.MagicMock())
            stats = agent.coverage_stats()
            self.assertEqual(stats["elements_tried"], 0)
            self.assertEqual(stats["unique_screens"], 0)

    def test_record_action_tracks_elements(self):
        from python_agent.agents.explorer import ExplorerAgent
        with mock.patch("python_agent.agents.explorer.AppiumController"):
            agent = ExplorerAgent(mock.MagicMock())
            agent.record_action_taken({"locator_value": "Login"})
            agent.record_action_taken({"locator_value": "Cart"})
            agent.record_action_taken({"locator_value": "Login"})  # duplicate
            stats = agent.coverage_stats()
            self.assertEqual(stats["elements_tried"], 2)


# ════════════════════════════════════════════════════════════════════════
#  ReporterAgent template fallback
# ════════════════════════════════════════════════════════════════════════

class TestReporterTemplate(TestCase):
    """Test the deterministic template report (no LLM)."""

    def test_template_report_has_heading(self):
        from python_agent.agents.reporter import ReporterAgent

        agent = ReporterAgent()
        data = {
            "session_id": "test123",
            "mode": "explore",
            "user_task": None,
            "plan_summary": {"goals": 2, "tasks": 4, "tasks_done": 3, "steps": 10, "steps_done": 8, "progress_pct": 80},
            "bugs": [],
            "coverage": {"features_tested": 3, "features_total": 5, "screens_discovered": 6, "total_screen_visits": 12},
        }
        md = agent._template_report(data)
        self.assertTrue(md.startswith("# Test Session Report"))
        self.assertIn("test123", md)
        self.assertIn("80%", md)


# ════════════════════════════════════════════════════════════════════════
#  RecoveryAgent detection heuristics
# ════════════════════════════════════════════════════════════════════════

class TestRecoveryDetection(TestCase):
    """Test recovery heuristics (no Appium)."""

    def _make_agent(self):
        from python_agent.agents.recovery import RecoveryAgent
        return RecoveryAgent(mock.MagicMock())

    def test_detect_crash_dialog(self):
        agent = self._make_agent()
        ctx = {
            "accessibility_ids": [],
            "resource_ids": [],
            "clickable_texts": ["OK", "App has stopped"],
        }
        self.assertTrue(agent.needs_recovery(ctx))

    def test_detect_empty_screen(self):
        agent = self._make_agent()
        ctx = {
            "accessibility_ids": [],
            "resource_ids": [],
            "clickable_texts": [],
        }
        self.assertTrue(agent.needs_recovery(ctx))

    def test_healthy_screen(self):
        agent = self._make_agent()
        ctx = {
            "accessibility_ids": ["Login", "Cart"],
            "resource_ids": ["btn_ok"],
            "clickable_texts": ["Submit"],
        }
        self.assertFalse(agent.needs_recovery(ctx))


# ════════════════════════════════════════════════════════════════════════
#  PlannerAgent response parsing
# ════════════════════════════════════════════════════════════════════════

class TestPlannerParsing(TestCase):
    """Test the planner's JSON → TestPlan conversion."""

    def test_parse_valid_plan(self):
        from python_agent.agents.planner import PlannerAgent

        agent = PlannerAgent()
        raw = json.dumps({
            "goals": [{
                "id": "g1",
                "name": "Auth",
                "description": "Test authentication",
                "tasks": [{
                    "id": "t1",
                    "name": "Login",
                    "description": "Test login flow",
                    "priority": "high",
                    "steps": [
                        {"id": "s1", "description": "Click username field"},
                        {"id": "s2", "description": "Enter 'bob@example.com'"},
                    ],
                }],
            }],
        })
        plan = agent._parse_plan_response(raw)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.goals), 1)
        self.assertEqual(len(plan.goals[0].tasks[0].steps), 2)

    def test_parse_invalid_plan(self):
        from python_agent.agents.planner import PlannerAgent

        agent = PlannerAgent()
        plan = agent._parse_plan_response("not json at all")
        self.assertIsNone(plan)

    def test_parse_empty_goals(self):
        from python_agent.agents.planner import PlannerAgent

        agent = PlannerAgent()
        plan = agent._parse_plan_response('{"goals": []}')
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.goals), 0)

    def test_parse_list_of_goals(self):
        """gpt-oss sometimes returns a bare list of goals instead of {goals: [...]}."""
        from python_agent.agents.planner import PlannerAgent

        agent = PlannerAgent()
        raw = json.dumps([{
            "id": "g1", "name": "Auth", "description": "Login tests",
            "tasks": [{
                "id": "t1", "name": "Login", "description": "Test login",
                "priority": "high",
                "steps": [{"id": "s1", "description": "Click login"}],
            }],
        }])
        plan = agent._parse_plan_response(raw)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.goals), 1)

    def test_parse_nested_plan_key(self):
        """Handle {\"plan\": {\"goals\": [...]}} wrapping."""
        from python_agent.agents.planner import PlannerAgent

        agent = PlannerAgent()
        raw = json.dumps({"plan": {"goals": [{
            "id": "g1", "name": "Nav", "description": "Navigation",
            "tasks": [{
                "id": "t1", "name": "Menu", "description": "Open menu",
                "priority": "medium",
                "steps": [{"id": "s1", "description": "Click menu"}],
            }],
        }]}})
        plan = agent._parse_plan_response(raw)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.goals), 1)

    def test_parse_single_goal_with_tasks(self):
        """Handle response that is a single goal object with tasks (no goals wrapper)."""
        from python_agent.agents.planner import PlannerAgent

        agent = PlannerAgent()
        raw = json.dumps({
            "id": "g1", "name": "Auth", "description": "Login test",
            "tasks": [{
                "id": "t1", "name": "Login", "description": "Do login",
                "priority": "high",
                "steps": [{"id": "s1", "description": "Click login"}],
            }],
        })
        plan = agent._parse_plan_response(raw)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.goals), 1)
        self.assertEqual(plan.goals[0].name, "Auth")

    def test_parse_trailing_commas(self):
        """Handle JSON with trailing commas (common LLM mistake)."""
        from python_agent.agents.base import BaseAgent

        raw = '{"goals": [{"id": "g1", "name": "Test",}]}'
        obj = BaseAgent.parse_json(raw)
        self.assertIsNotNone(obj)
        self.assertIn("goals", obj)

    def test_parse_json_with_comments(self):
        """Handle JSON with // comments (common LLM mistake)."""
        from python_agent.agents.base import BaseAgent

        raw = '{\n"goals": [\n// Main goals\n{"id": "g1", "name": "Test"}\n]\n}'
        obj = BaseAgent.parse_json(raw)
        self.assertIsNotNone(obj)
        self.assertIn("goals", obj)

    def test_parse_json_markdown_wrapped(self):
        """Handle JSON wrapped in markdown code fences."""
        from python_agent.agents.base import BaseAgent

        raw = 'Here is the plan:\n```json\n{"goals": [{"id": "g1"}]}\n```\nLet me know!'
        obj = BaseAgent.parse_json(raw)
        self.assertIsNotNone(obj)
        self.assertIn("goals", obj)

    def test_parse_truncated_json(self):
        """Handle truncated JSON by repairing unmatched brackets."""
        from python_agent.agents.base import BaseAgent

        # Simulates a cloud model response truncated mid-way
        raw = '{"goals": [{"id": "g1", "name": "Auth", "tasks": [{"id": "t1", "name": "Login", "steps": [{"id": "s1", "description": "Click login"}'
        obj = BaseAgent.parse_json(raw)
        self.assertIsNotNone(obj)
        self.assertIn("goals", obj)

    def test_parse_truncated_json_mid_string(self):
        """Handle truncation inside a string value."""
        from python_agent.agents.base import BaseAgent

        raw = '{"goals": [{"id": "g1", "name": "Auth", "description": "Test authenti'
        obj = BaseAgent.parse_json(raw)
        # Should repair and at minimum get the goals key
        self.assertIsNotNone(obj)
        self.assertIn("goals", obj)


# ════════════════════════════════════════════════════════════════════════
#  VLM module — Ollama fallback logic
# ════════════════════════════════════════════════════════════════════════

class TestVLMFallback(TestCase):
    """Test VLM fallback logic (mock network calls)."""

    @mock.patch("python_agent.vlm.requests.get")
    def test_ollama_is_available(self, mock_get):
        from python_agent.vlm import _ollama_is_available
        mock_get.return_value = mock.MagicMock(status_code=200)
        self.assertTrue(_ollama_is_available())

    @mock.patch("python_agent.vlm.requests.get", side_effect=Exception("conn refused"))
    def test_ollama_is_not_available(self, mock_get):
        from python_agent.vlm import _ollama_is_available
        self.assertFalse(_ollama_is_available())

    def test_reset_gemini_session(self):
        import python_agent.vlm as vlm_mod
        vlm_mod._gemini_disabled_this_session = True
        vlm_mod.reset_gemini_session()
        self.assertFalse(vlm_mod._gemini_disabled_this_session)


# ════════════════════════════════════════════════════════════════════════
#  Integration-style: Orchestrator init (no network)
# ════════════════════════════════════════════════════════════════════════

class TestOrchestratorInit(TestCase):
    """Test OrchestratorAgent can be instantiated without crashing."""

    def test_instantiate(self):
        from python_agent.agents.orchestrator import OrchestratorAgent
        orch = OrchestratorAgent()
        self.assertIsNotNone(orch.planner)
        self.assertIsNotNone(orch.critic)
        self.assertIsNotNone(orch.reporter)
        self.assertIsNotNone(orch.accessibility)
        self.assertIsNotNone(orch.security)
        self.assertIsNone(orch.navigator)  # Not yet created (needs Appium)

    def test_fallback_plan(self):
        from python_agent.agents.orchestrator import OrchestratorAgent
        orch = OrchestratorAgent()
        plan = orch._fallback_plan("Test the login screen")
        self.assertEqual(len(plan.goals), 1)
        self.assertEqual(plan.goals[0].tasks[0].steps[0].description, "Test the login screen")
