"""
Orchestrator Agent  --  top-level coordinator that manages the entire
testing session using the specialist agents.

Lifecycle:
1. Setup Appium / emulator
2. Ask the **Planner** to create a ``TestPlan``
3. Have the **Critic** validate the plan
4. Iterate through tasks/steps:
   a. **Navigator** executes each step
   b. **Critic** validates the result
   c. On failure → ask Planner to re-plan and Critic to re-validate
5. Persist everything in **SessionMemory** (crash-resilient)
6. Produce a final report and tear down
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..logging_config import get_logger
from .. import adb, appium_server, config
from ..vlm import get_vlm_cache, reset_vlm_cache, get_text_response

logger = get_logger("agents.orchestrator")
from ..appium_controller import AppiumController
from ..session_memory import (
    BugEntry,
    SessionMemory,
    TaskStatus,
    TestPlan,
)
from ..bug_localization.integration import (
    BugLocalizationIntegration,
    create_bug_report_from_detection,
)

from .planner import PlannerAgent
from .navigator import NavigatorAgent
from .critic import CriticAgent, Verdict
from .recovery import RecoveryAgent
from .explorer import ExplorerAgent
from .reporter import ReporterAgent
from .accessibility import AccessibilityAgent
from .security import SecurityAgent
from .doc_ingestion import DocIngestionAgent
from .script_generator import ScriptGeneratorAgent
from .script_executor import ScriptExecutorAgent
from .execution_engine import ExecutionEngine
from ..knowledge_base import KnowledgeBase


class OrchestratorAgent:
    """
    Drives the multi-agent testing loop.

    Not a ``BaseAgent`` subclass  --  it doesn't call the LLM itself
    but delegates to the specialist agents.
    """

    def __init__(
        self,
        *,
        source_code_dir: Optional[str] = None,
        localize_bugs: Optional[bool] = None,
        kb: Optional[KnowledgeBase] = None,
    ):
        # Sub-agents (navigator & recovery created after Appium starts)
        self.planner = PlannerAgent()
        self.critic = CriticAgent()
        self.navigator: Optional[NavigatorAgent] = None
        self.recovery: Optional[RecoveryAgent] = None
        self.explorer: Optional[ExplorerAgent] = None
        self.reporter = ReporterAgent()
        self.accessibility = AccessibilityAgent()
        self.security = SecurityAgent()
        self.doc_ingestion = DocIngestionAgent()
        self.script_generator = ScriptGeneratorAgent()
        self.script_executor: Optional[ScriptExecutorAgent] = None

        # Execution engine (policy/execution separation)
        self.engine: Optional[ExecutionEngine] = None

        # Cross-run knowledge base (TinyDB) — shared with API when launched via REST
        self.kb = kb if kb is not None else KnowledgeBase()

        # Infrastructure
        self.controller = AppiumController()
        self.appium_process = None

        # Session memory
        self.memory: Optional[SessionMemory] = None

        # Cache page sources per unique screen for multi-screen a11y audit
        # {signature: (page_source, screenshot_path)}
        self._screen_sources: Dict[str, tuple] = {}

        # API stop/status callback (set by api.py via _run_agent_core)
        self._api_status_callback = None

        # Bug localization
        self.localize_bugs = localize_bugs if localize_bugs is not None else config.BUG_LOCALIZATION_ENABLED
        src_dir = source_code_dir or (str(config.SOURCE_CODE_DIR) if config.SOURCE_CODE_DIR else None)
        self.bug_integration: Optional[BugLocalizationIntegration] = None
        if self.localize_bugs and src_dir:
            self.bug_integration = BugLocalizationIntegration(
                source_code_dir=src_dir,
                file_extensions=config.SOURCE_CODE_EXTENSIONS,
            )

    # ════════════════════════════════════════════════════════════════
    #  API integration helpers
    # ════════════════════════════════════════════════════════════════

    @property
    def _stop_requested(self) -> bool:
        """Check whether the REST API has received a stop request."""
        if self._api_status_callback is None:
            return False
        # The API module sets _agent_status["state"] = "stopping"
        # We read it through the callback's closure.
        try:
            from ..api import _agent_status
            return _agent_status.get("state") == "stopping"
        except Exception:
            return False

    def _report_progress(self, step_num: int, max_steps: int, **extra):
        """Push a progress update to the API (if running via REST)."""
        if self._api_status_callback is not None:
            update = {"current_step": step_num, "max_steps": max_steps}
            if self.memory:
                update["current_screen"] = getattr(self.memory, "_last_screen_sig", "")
            update.update(extra)
            self._api_status_callback(update)

    # ════════════════════════════════════════════════════════════════
    #  Setup / teardown
    # ════════════════════════════════════════════════════════════════

    def _setup(self) -> bool:
        logger.info("Setting up multi-agent orchestrator...")
        if not adb.start_emulator(config.EMULATOR_AVD, target_device=config.ADB_TARGET_DEVICE):
            logger.error("Emulator could not be started.")
            return False
        try:
            self.appium_process = appium_server.start_appium_server(
                config.APPIUM_SERVER_URL,
                repo_root=config.REPO_ROOT,
                log_file=config.APPIUM_LOG_FILE,
            )
        except Exception as e:
            logger.error("Could not start Appium: %s", e, exc_info=True)
            return False

        self.controller.start_driver()
        if not self.controller.app_is_open:
            logger.error("Failed to start the app.")
            return False

        self.navigator = NavigatorAgent(self.controller)
        self.recovery = RecoveryAgent(self.controller)
        self.explorer = ExplorerAgent(self.controller, kb=self.kb)
        self.script_executor = ScriptExecutorAgent(self.navigator, self.controller)
        return True

    def _create_engine(self):
        """Create the ExecutionEngine once memory + agents are ready."""
        self.engine = ExecutionEngine(
            navigator=self.navigator,
            critic=self.critic,
            recovery=self.recovery,
            explorer=self.explorer,
            memory=self.memory,
            kb=self.kb,
            bug_integration=self.bug_integration,
            generate_screen_name=self._generate_screen_name,
        )
        self.engine.set_screen_cache(self._screen_sources)

    def _teardown(self):
        # Log VLM cache stats before shutting down
        try:
            logger.info(get_vlm_cache().stats())
        except Exception:
            pass
        try:
            self.controller.stop_driver()
        finally:
            try:
                appium_server.stop_appium_server(self.appium_process)
            except Exception:
                pass

    # ════════════════════════════════════════════════════════════════
    #  Public entry points
    # ════════════════════════════════════════════════════════════════

    def run_task(self, task: str, *, max_steps: int = 30, resume_path: Optional[str] = None) -> Path:
        """Execute a natural language task using the full multi-agent loop."""
        return self._run(
            mode="task",
            user_task=task,
            max_steps=max_steps,
            resume_path=resume_path,
        )

    def run_explore(self, *, max_steps: int = 50, resume_path: Optional[str] = None) -> Path:
        """Autonomous exploration: discover screens and find bugs."""
        return self._run(
            mode="explore",
            user_task=None,
            max_steps=max_steps,
            resume_path=resume_path,
        )

    # ════════════════════════════════════════════════════════════════
    #  Core loop
    # ════════════════════════════════════════════════════════════════

    def _run(
        self,
        mode: str,
        user_task: Optional[str],
        max_steps: int,
        resume_path: Optional[str],
    ) -> Optional[Path]:
        logger.info("="*60)
        logger.info("MULTI-AGENT ORCHESTRATOR -- %s mode", mode.upper())
        if user_task:
            logger.info("Task: %s", user_task)
        logger.info("="*60)

        if not self._setup():
            return None

        # ── Session memory (resume or create) ────────────────────────
        mem_path = Path(resume_path) if resume_path else (
            config.ARTIFACTS_DIR / "sessions" / f"session_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        self.memory = SessionMemory.load(mem_path)
        self.memory.mode = mode
        self.memory.user_task = user_task

        # Create execution engine (policy/execution separation)
        self._create_engine()

        if self.bug_integration:
            self.bug_integration.start_trace()

        # ── KnowledgeBase lifecycle ──────────────────────────────────
        self.kb.current_app_package = config.APP_PACKAGE or ""
        self.kb.start_run(app_package=self.kb.current_app_package)

        try:
            # ── Phase 1: Planning ────────────────────────────────────
            if not self.memory.plan.goals:
                self._planning_phase(user_task)

            # ── Phase 2: Execution ───────────────────────────────────
            self._execution_phase(max_steps)

            # ── Phase 3: Specialist audits (run in parallel) ────────
            self._run_parallel_audits()

        except KeyboardInterrupt:
            logger.warning("Interrupted -- session saved for resume.")
        except Exception as e:
            logger.critical("Fatal error: %s", e, exc_info=True)
        finally:
            self.kb.end_run()
            report_path = self._save_report()
            # Generate Markdown report via Reporter agent
            self._generate_md_report()
            self._teardown()

        logger.info("Session saved to: %s", mem_path)
        logger.info("Report saved to:  %s", report_path)
        return report_path

    # ── Planning phase ───────────────────────────────────────────────

    def _planning_phase(self, user_task: Optional[str]):
        logger.info("[Phase 1] Planning...")

        # Gather initial UI state
        ui_ctx = self.navigator.get_ui_context("plan_initial")
        ui_elements = {
            "accessibility_ids": ui_ctx["accessibility_ids"],
            "resource_ids": ui_ctx["resource_ids"],
            "clickable_texts": ui_ctx["clickable_texts"],
        }

        # Record initial screen
        self.memory.record_screen(ui_ctx["state_signature"], ui_ctx["accessibility_ids"])
        name = self._generate_screen_name(ui_ctx)
        # Analyze screenshot for description
        description = ""
        screenshot_path = ui_ctx.get("screenshot_path", "")
        if screenshot_path:
            try:
                from ..vlm import analyze_screen_once
                description = analyze_screen_once(screenshot_path, ui_ctx["state_signature"])
            except Exception as e:
                logger.warning(f"VLM screen description failed: {e}")
        self.kb.record_screen(
            ui_ctx["state_signature"], ui_ctx["accessibility_ids"],
            screenshot=screenshot_path,
            name=name,
            description=description,
        )

        # Create plan
        app_desc = f"SauceLabs MyDemoApp (package: {config.APP_PACKAGE})"
        plan = self.planner.create_plan(
            app_description=app_desc,
            ui_elements=ui_elements,
            user_task=user_task,
            existing_coverage=self.memory.coverage_summary(),
        )

        if plan is None:
            logger.warning("Planner failed to produce a plan -- falling back to single-goal plan.")
            plan = self._fallback_plan(user_task)

        # Critic validates the plan
        from dataclasses import asdict
        plan_dict = asdict(plan)
        verdict = self.critic.validate_plan(plan_dict, ui_elements)
        logger.info("Critic plan verdict: %s -- %s", verdict['verdict'], verdict['reason'])

        if verdict["verdict"] == Verdict.FAIL:
            logger.warning("Plan rejected by critic -- requesting re-plan...")
            plan2 = self.planner.refine_plan(self.memory, verdict["reason"])
            if plan2:
                plan = plan2

        self.memory.set_plan(plan)

        # ── Multi-level decomposition ──
        # Break complex tasks into subtask trees. Only tasks with
        # complexity >= 2 get decomposed; simple ones stay as-is.
        # Each LLM call receives ONLY the specific task + current UI
        # (not the entire plan tree), keeping prompts focused.
        # NOTE: ui_elements here are from the initial/home screen.
        # Decomposition prompts include them as context; tasks targeting
        # other screens may produce approximate subtasks.  This is
        # acceptable because the Navigator re-resolves at execution time.
        logger.info("Decomposing complex tasks...")
        self.planner.decompose_plan(plan, ui_elements, kb=self.kb)
        self.memory._persist()   # save expanded subtask tree

        summary = plan.summary()
        logger.info(
            "Plan ready: %d goals, %d tasks (depth %d), %d steps",
            summary['goals'], summary['tasks'], summary.get('max_depth', 0), summary['steps'],
        )

    def _generate_screen_name(self, ui_context: Dict[str, Any]) -> str:
        """Generate a human-readable name for a screen based on extracted UI elements using LLM."""
        indicators = {
            "login": ["login", "sign in", "log in"],
            "home": ["home", "dashboard", "main"],
            "menu": ["menu", "navigation"],
            "settings": ["settings", "preferences"],
            "profile": ["profile", "account"],
            "cart": ["cart", "basket", "checkout"],
            "search": ["search"],
            "product": ["product", "item"],
        }
        
        # Use extracted UI elements (same as agents use)
        clickable_texts = ui_context.get("clickable_texts", [])
        accessibility_ids = ui_context.get("accessibility_ids", [])
        resource_ids = ui_context.get("resource_ids", [])
        
        if not clickable_texts and not accessibility_ids and not resource_ids:
            return "Screen"

        # Use LLM to generate screen name from extracted elements
        elements_summary = f"Clickable texts: {', '.join(clickable_texts[:10])}\nAccessibility IDs: {', '.join(accessibility_ids[:10])}\nResource IDs: {', '.join(resource_ids[:10])}"
        prompt = f"""Analyze these mobile app UI elements and suggest a concise screen name (e.g., 'Login Screen', 'Home Screen').
Focus on the main purpose or content visible. Keep it to 2-3 words ending with 'Screen'.

UI Elements:
{elements_summary}

Screen name:"""

        try:
            response = get_text_response(prompt).strip()
            # Clean the response
            if response and not response.endswith("Screen"):
                response += " Screen"
            # Ensure it's not too long
            if len(response.split()) > 4:
                response = " ".join(response.split()[:3]) + " Screen"
            return response or "Screen"
        except Exception as e:
            logger.warning(f"LLM screen name generation failed: {e}")
            # Fallback to text-based
            texts = ui_context.get("clickable_texts", [])
            for screen_type, keywords in indicators.items():
                for text in texts:
                    if any(kw.lower() in text.lower() for kw in keywords):
                        return f"{screen_type.title()} Screen"
            for text in texts[:3]:
                if len(text) > 3 and text.isalnum():
                    return f"{text} Screen"
            return "Screen"

    # ── Execution phase ──────────────────────────────────────────────

    def _execution_phase(self, max_steps: int):
        logger.info("[Phase 2] Execution (max %d steps)...", max_steps)
        steps_taken = 0

        while steps_taken < max_steps:
            # ── Check for API stop request ──
            if self._stop_requested:
                logger.info("Stop requested via API -- halting execution.")
                break

            self._report_progress(steps_taken, max_steps)

            task = self.memory.get_next_task()
            if task is None:
                logger.info("All tasks completed.")
                break

            self.memory.mark_task(task, TaskStatus.IN_PROGRESS)
            self.memory.update_cursor(task_id=task.id)
            logger.info("Task [%s]: %s", task.priority, task.name)

            task_failed = False
            # Use all_leaf_steps() for leaf tasks (no subtasks) to get
            # the correct step list. Container tasks with subtasks will
            # only have their own pre-steps here -- subtasks are returned
            # as separate tasks by get_next_task().
            for step in task.steps:
                if step.status in (TaskStatus.COMPLETED.value, TaskStatus.SKIPPED.value):
                    continue
                if steps_taken >= max_steps:
                    break

                # ── Health check: restart session if instrumentation crashed ──
                if not self.recovery.repair_session_if_needed():
                    logger.critical("Cannot repair Appium session  --  aborting.")
                    return

                self.memory.mark_step(step, TaskStatus.IN_PROGRESS)
                self.memory.update_cursor(step_id=step.id)
                logger.debug("Step %s: %s", step.id, step.description)

                result = self._execute_single_step(step, task)
                steps_taken += 1

                if result["success"]:
                    self.memory.mark_step(step, TaskStatus.COMPLETED, result=result)
                    logger.info("Step OK -- %s", result['description'])
                else:
                    # Repair session before retrying if it died during the step
                    if not self.recovery.repair_session_if_needed():
                        logger.critical("Cannot repair Appium session  --  aborting.")
                        return

                    retry_ok = self._retry_step(step, task, result, max_retries=config.ACTION_RETRY_BUDGET)
                    if not retry_ok:
                        # Ensure session is still alive before deeper recovery
                        self.recovery.repair_session_if_needed()
                        # Ask Recovery agent to fix the state
                        recovery_ctx = self.navigator.get_ui_context(f"recovery_{self.memory.step_counter:04d}")
                        if self.recovery.needs_recovery(recovery_ctx):
                            rec = self.recovery.recover(recovery_ctx)
                            logger.info("Recovery: %s (%d steps)", rec['strategy'], rec['steps_taken'])
                        self.memory.mark_step(step, TaskStatus.FAILED, error=result["description"])
                        logger.warning("Step FAIL -- %s", result['description'])
                        task_failed = True
                        # NOTE: don't increment steps_taken here -- already counted above

                # Handle bug reports
                if result.get("bug_report"):
                    self._record_bug(result, task, step)

            # Finalise task
            if task_failed:
                self.memory.mark_task(task, TaskStatus.FAILED)
                # Ask planner to re-plan around the failure
                self._handle_task_failure(task)
            else:
                self.memory.mark_task(task, TaskStatus.COMPLETED)
                # Mark associated features as tested
                self.memory.mark_feature_tested(task.name)

            # Check if containing goal is done
            for goal in self.memory.plan.goals:
                if goal.is_done() and goal.status != TaskStatus.COMPLETED.value:
                    self.memory.mark_goal(goal, TaskStatus.COMPLETED)
                    logger.info("Goal completed: %s", goal.name)

            # ── Drain discovery queue between tasks ──
            if self.explorer and self.explorer.has_pending_discoveries():
                discoveries = self.explorer.drain_discovery_queue(limit=5)
                if discoveries:
                    logger.info("Draining %d queued discoveries between tasks", len(discoveries))
                    for disc in discoveries:
                        self.memory.record_screen(
                            disc.get("screen_sig", "unknown"),
                            disc.get("element_ids", []),
                        )

        progress = self.memory.plan.summary()
        logger.info("Execution finished -- %d/%d tasks done, %d/%d steps done",
                     progress['tasks_done'], progress['tasks'],
                     progress['steps_done'], progress['steps'])

    def _execute_single_step(self, step, task) -> Dict[str, Any]:
        """Execute one step via the ExecutionEngine (delegated from policy layer)."""
        # Get UI context and record screen to KB with generated name
        ui_ctx = self.navigator.get_ui_context(f"step_{self.memory.step_counter:04d}")
        ui_ctx["screen_name"] = self._generate_screen_name(ui_ctx)
        # Analyze screenshot for description
        description = ""
        screenshot_path = ui_ctx.get("screenshot_path", "")
        if screenshot_path:
            try:
                from ..vlm import analyze_screen_once
                description = analyze_screen_once(screenshot_path, ui_ctx["state_signature"])
            except Exception as e:
                logger.warning(f"VLM screen description failed: {e}")
        self.kb.record_screen(
            ui_ctx["state_signature"], ui_ctx["accessibility_ids"],
            screenshot=screenshot_path,
            name=ui_ctx["screen_name"],
            description=description,
        )
        
        if self.engine:
            return self.engine.execute_step(step, task, ui_ctx)
        else:
            # Fallback: direct execution
            ui_elements = {
                "accessibility_ids": ui_ctx["accessibility_ids"],
                "resource_ids": ui_ctx["resource_ids"],
                "clickable_texts": ui_ctx["clickable_texts"],
            }

            # Record screen to memory (KB already done above)
            self.memory.record_screen(ui_ctx["state_signature"], ui_ctx["accessibility_ids"])

        # Cache page source for multi-screen a11y audit (one snapshot per unique sig)
        sig = ui_ctx["state_signature"]
        if sig not in self._screen_sources:
            self._screen_sources[sig] = (ui_ctx.get("page_source", ""), ui_ctx.get("screenshot_path"))

        # Navigator resolves & executes
        result = self.navigator.execute_step(
            step.description,
            ui_ctx,
            action_history=self.memory.recent_actions(8),
        )

        # Critic post-check
        if result["success"]:
            post_ctx = self.navigator.get_ui_context(f"post_{self.memory.step_counter:04d}")
            post_elements = {
                "accessibility_ids": post_ctx["accessibility_ids"],
                "resource_ids": post_ctx["resource_ids"],
                "clickable_texts": post_ctx["clickable_texts"],
            }

            # Record screen transition
            sig_before = result.get("state_signature_before", "")
            sig_after = result.get("state_signature_after", "")
            if sig_before and sig_after and sig_before != sig_after:
                self.memory.record_transition(sig_before, step.description, sig_after)
                self.memory.record_screen(sig_after, post_ctx["accessibility_ids"])
                self.kb.record_transition(sig_before, step.description, sig_after)
                name = self._generate_screen_name(post_ctx)
                self.kb.record_screen(
                    sig_after, post_ctx["accessibility_ids"],
                    screenshot=post_ctx.get("screenshot_path", ""),
                    name=name,
                )
                # Cache post-action screen for a11y
                if sig_after not in self._screen_sources:
                    self._screen_sources[sig_after] = (
                        post_ctx.get("page_source", ""), post_ctx.get("screenshot_path")
                    )

            verdict = self.critic.validate_result(
                {"action": result["action"], "locator_value": result["locator_value"]},
                result,
                ui_elements,
                post_elements,
            )
            if verdict["verdict"] == Verdict.FAIL:
                result["success"] = False
                result["description"] += f" [Critic: {verdict['reason']}]"

        # Log action
        self.memory.log_action({
            "task_id": task.id,
            "step_id": step.id,
            "action": result.get("action"),
            "locator": result.get("locator_value"),
            "success": result.get("success"),
            "description": result.get("description"),
        })

        # Bug localization trace — include page_source so SC/GS extraction works
        if self.bug_integration:
            # Grab the raw Appium page-source XML when available
            _page_xml = ""
            try:
                if self.controller and self.controller.driver:
                    _page_xml = self.controller.driver.page_source or ""
            except Exception:
                pass
            self.bug_integration.add_trace_step(
                action={
                    "action": result.get("action"),
                    "locator": result.get("locator_value"),
                },
                ui_state={
                    "accessibility_ids": ui_ctx.get("accessibility_ids", []),
                    "resource_ids": ui_ctx.get("resource_ids", []),
                    "state_signature": ui_ctx.get("state_signature", ""),
                },
                screenshot_path=ui_ctx.get("screenshot_path"),
                page_source=_page_xml,
                screen_name=ui_ctx.get("screen_name", ""),
                activity=ui_ctx.get("activity", ""),
            )

        return result

    def _retry_step(self, step, task, first_result: Dict, max_retries: int) -> bool:
        """Retry a failed step up to ``max_retries`` times."""
        # Get fresh UI context for retry
        ui_ctx = self.navigator.get_ui_context(f"retry_{self.memory.step_counter:04d}")
        if self.engine:
            return self.engine.retry_step(step, task, max_retries, ui_ctx)
        # Fallback: direct retry
        for attempt in range(max_retries):
            logger.debug("Retry %d/%d...", attempt + 1, max_retries)
            time.sleep(1.0)
            result = self._execute_single_step(step, task)
            if result["success"]:
                self.memory.mark_step(step, TaskStatus.COMPLETED, result=result, retries=attempt + 1)
                logger.info("Retry OK -- %s", result['description'])
                return True
        return False

    def _handle_task_failure(self, task):
        """Ask the Planner to re-plan after a task failure."""
        logger.info("Re-planning around failed task: %s", task.name)
        failure_ctx = f"Task '{task.name}' failed. Steps completed: {task.progress()*100:.0f}%"
        new_plan = self.planner.refine_plan(self.memory, failure_ctx)
        if new_plan and new_plan.goals:
            # Merge: keep completed goals/tasks, add new ones
            existing_ids = {t.id for g in self.memory.plan.goals for t in g.tasks}
            for goal in new_plan.goals:
                for t in goal.tasks:
                    if t.id not in existing_ids:
                        # Append to the first incomplete goal
                        for g in self.memory.plan.goals:
                            if not g.is_done():
                                g.tasks.append(t)
                                break
            self.memory._persist()
            logger.info("Plan updated with %d new/modified goals", len(new_plan.goals))

    # ── Bug handling ─────────────────────────────────────────────────

    def _record_bug(self, result: Dict[str, Any], task, step):
        bug_id = f"bug_{len(self.memory.bugs) + 1}"
        bug_desc = result.get("bug_report", "Unknown bug")
        logger.warning("BUG detected: %s", bug_desc)

        localization = None
        if self.bug_integration:
            # Attempt to grab live page-source for richer analysis
            _page_xml = ""
            try:
                if self.controller and self.controller.driver:
                    _page_xml = self.controller.driver.page_source or ""
            except Exception:
                pass
            analysis = self.bug_integration.analyze_detected_bug(
                bug_report=bug_desc,
                page_source=_page_xml,
                screenshot_path=result.get("screenshot"),
            )
            localization = analysis.get("localization", {})
            top = localization.get("top_files", [])
            if top:
                logger.info("Bug localized to: %s (score=%.4f)", top[0]['path'], top[0]['score'])

        bug_entry = BugEntry(
            id=bug_id,
            description=bug_desc,
            screenshot=result.get("screenshot"),
            screen_signature=result.get("state_signature_before"),
            localization=localization,
            detected_at=datetime.utcnow().isoformat() + "Z",
            task_id=task.id,
            step_id=step.id,
        )
        self.memory.add_bug(bug_entry)
        self.kb.record_bug(
            bug_id, bug_desc,
            screenshot=bug_entry.screenshot or "",
            screen_signature=bug_entry.screen_signature or "",
        )

    # ── Reporting ────────────────────────────────────────────────────

    def _save_report(self) -> Optional[Path]:
        if not self.memory:
            return None

        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = config.REPORTS_DIR / f"multiagent_{self.memory.session_id}.json"

        if self.bug_integration:
            self.bug_integration.end_trace()

        report = self.memory.full_report()
        report["agent_stats"] = {
            "planner_calls": self.planner._call_count,
            "navigator_calls": self.navigator._call_count if self.navigator else 0,
            "critic_calls": self.critic._call_count,
            "recovery_calls": self.recovery.recovery_count if self.recovery else 0,
            "session_restarts": self.recovery.session_restarts if self.recovery else 0,
            "explorer_calls": self.explorer._call_count if self.explorer else 0,
            "reporter_calls": self.reporter._call_count,
            "accessibility_screens": len(self.accessibility.findings),
            "security_findings": len(self.security.findings),
        }

        if self.bug_integration and self.bug_integration.localization_results:
            report["bug_localization"] = {
                "bugs_analyzed": len(self.bug_integration.localization_results),
                "localizations": self.bug_integration.localization_results,
            }

        # Attach specialist reports
        if self.accessibility.findings:
            report["accessibility"] = self.accessibility.full_report()
        if self.security.findings:
            report["security"] = self.security.full_report()
        if self.explorer:
            report["explorer_stats"] = self.explorer.coverage_stats()

        # Action weights summary (Critic feedback)
        if self.memory and self.memory.action_weights:
            top = self.memory.get_top_weighted_elements(10)
            penalised = list(self.memory.get_penalised_elements())[:10]
            report["critic_feedback"] = {
                "total_weighted_elements": len(self.memory.action_weights),
                "top_rewarded": top[:5],
                "most_penalised": penalised[:5],
            }

        # App archetype
        archetype = self.kb.get_app_archetype()
        if archetype:
            report["app_archetype"] = archetype

        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

        # Save trace
        if self.bug_integration:
            config.TRACES_DIR.mkdir(parents=True, exist_ok=True)
            trace_path = config.TRACES_DIR / f"trace_{self.memory.session_id}.json"
            self.bug_integration.save_trace(str(trace_path))

        return report_path

    # ════════════════════════════════════════════════════════════════
    #  Specialist audit phases
    # ════════════════════════════════════════════════════════════════

    def _run_parallel_audits(self):
        """Run accessibility and security audits in parallel using threads."""
        logger.info("[Phase 3] Running specialist audits in parallel...")
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="audit") as pool:
            a11y_future = pool.submit(self._run_accessibility_audit)
            sec_future = pool.submit(self._run_security_audit)

            # Wait for both to complete, log errors
            for name, fut in [("accessibility", a11y_future), ("security", sec_future)]:
                try:
                    fut.result(timeout=300)
                except Exception as e:
                    logger.error("Parallel %s audit failed: %s", name, e, exc_info=True)

    def _run_accessibility_audit(self):
        """Run the Accessibility Agent on each unique screen visited during the session.

        We iterate over every page source snapshot cached in
        ``self._screen_sources`` (populated during execution) so the
        audit covers the full breadth of screens, not just the final one.
        If no snapshots were cached (e.g. old-style run) we fall back to
        auditing the current screen.
        """
        if not self.navigator:
            return
        logger.info("[Phase 3a] Accessibility audit...")

        # Repair session before audit to avoid 'session terminated' errors
        if self.recovery:
            try:
                self.recovery.repair_session_if_needed()
            except Exception as e:
                logger.warning("Session repair before a11y audit failed: %s", e)

        sources = getattr(self, "_screen_sources", {})

        # Fallback: audit current screen if no snapshots were recorded
        if not sources:
            try:
                ui_ctx = self.navigator.get_ui_context("a11y_audit")
                sig = ui_ctx.get("state_signature", "current")
                sources = {sig: (ui_ctx.get("page_source", ""), ui_ctx.get("screenshot_path"))}
            except Exception as e:
                logger.error("Accessibility audit failed: %s", e, exc_info=True)
                return

        for sig, (page_src, screenshot) in sources.items():
            try:
                # Provide state_sig so the a11y agent can reuse cached VLM analysis
                self.accessibility._current_state_sig = sig
                result = self.accessibility.audit_screen(
                    page_src,
                    screenshot_path=screenshot,
                    screen_name=sig,
                )
                logger.info("Accessibility score: %d/100 (%d issues) -- screen %s",
                            result['score'], result['issue_count'], sig[:16])
                for issue in result["issues"][:5]:
                    logger.info("  [%s] %s: %s", issue['severity'], issue['rule'],
                                issue['description'][:80])
            except Exception as e:
                logger.error("Accessibility audit failed on screen %s: %s", sig[:16], e, exc_info=True)

    def _run_security_audit(self):
        """Run the Security Agent on all cached screens (input scanning + data leak check).

        Like the accessibility audit, this iterates over every page source
        snapshot cached during execution so the security scan covers the
        full breadth of discovered screens.
        """
        if not self.navigator:
            return

        # ── Session recovery before security audit ──────────────────
        if self.recovery:
            self.recovery.repair_session_if_needed()

        logger.info("[Phase 3b] Security audit...")

        sources = getattr(self, "_screen_sources", {})

        # Fallback: audit current screen if no snapshots were recorded
        if not sources:
            try:
                ui_ctx = self.navigator.get_ui_context("sec_audit")
                sig = ui_ctx.get("state_signature", "current")
                sources = {sig: (ui_ctx.get("page_source", ""), ui_ctx.get("screenshot_path"))}
            except Exception as e:
                logger.error("Security audit failed (no page source): %s", e, exc_info=True)
                return

        for sig, (page_src, _screenshot) in sources.items():
            try:
                # Check for leaked sensitive data on this screen
                leaks = self.security.check_sensitive_data(
                    page_src,
                    screen_name=sig,
                )
                if leaks:
                    for leak in leaks:
                        logger.critical("Security: %s", leak['description'])
            except Exception as e:
                logger.error("Security audit failed on screen %s: %s", sig[:16], e, exc_info=True)

        # Run auth & input tests on the current live screen (if session alive)
        try:
            ui_ctx = self.navigator.get_ui_context("sec_audit_live")
            auth_tests = self.security.audit_authentication_screen(ui_ctx)
            if auth_tests:
                logger.info("Found %d auth security test vectors", len(auth_tests))

            sec_inputs = self.security.generate_security_inputs(ui_ctx)
            if sec_inputs:
                logger.info("Generated %d security test inputs", len(sec_inputs))
        except Exception as e:
            logger.warning("Security live-screen checks skipped (session may be dead): %s", e)

        report = self.security.full_report()
        logger.info("Security risk level: %s (%d findings)", report['risk_level'], report['total_findings'])

    def _generate_md_report(self):
        """Use the Reporter agent to produce a Markdown report."""
        if not self.memory:
            return
        logger.info("[Phase 4] Generating Markdown report...")
        try:
            stats = {
                "planner": self.planner._call_count,
                "navigator": self.navigator._call_count if self.navigator else 0,
                "critic": self.critic._call_count,
                "recovery": self.recovery.recovery_count if self.recovery else 0,
                "explorer_coverage": self.explorer.coverage_stats() if self.explorer else {},
                "a11y_report": self.accessibility.full_report(),
                "security_report": self.security.full_report(),
            }
            md_path = self.reporter.save_report(
                self.memory,
                config.REPORTS_DIR,
                extra_stats=stats,
            )
            logger.info("Markdown report: %s", md_path)
        except Exception as e:
            logger.error("Markdown report generation failed: %s", e, exc_info=True)

    # ════════════════════════════════════════════════════════════════
    #  Explorer-augmented exploration
    # ════════════════════════════════════════════════════════════════

    def run_explore_with_explorer(
        self,
        *,
        max_steps: int = 50,
        resume_path: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Fully autonomous exploration driven by the Explorer Agent
        (curiosity-based coverage maximisation) instead of the Planner.

        Enhanced with:
        - Direct action execution (bypass LLM re-resolution)
        - Visual bug detection via VLM per screen
        - Crash/error detection
        - Frequent accessibility audits (every 5 steps)
        - Input field testing via explorer
        """
        logger.info("="*60)
        logger.info("MULTI-AGENT ORCHESTRATOR -- EXPLORER mode (comprehensive)")
        logger.info("="*60)

        if not self._setup():
            return None

        mem_path = Path(resume_path) if resume_path else (
            config.ARTIFACTS_DIR / "sessions" / f"explore_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        self.memory = SessionMemory.load(mem_path)
        self.memory.mode = "explorer"

        # Create execution engine
        self._create_engine()

        if self.bug_integration:
            self.bug_integration.start_trace()

        # ── KnowledgeBase lifecycle ──────────────────────────────────
        self.kb.current_app_package = config.APP_PACKAGE or ""
        self.kb.start_run(app_package=self.kb.current_app_package)

        _consecutive_crash_detections = 0  # Prevent infinite crash-recovery loops
        _archetype_detected = False        # Detect app archetype once mid-run
        _directive_refresh_interval = 20   # Re-issue Planner directive every N steps

        try:
            # ── Generate initial Planner directive (session-level strategy) ──
            try:
                init_ctx = self.navigator.get_ui_context("directive_init")
                init_elements = {
                    "accessibility_ids": init_ctx["accessibility_ids"],
                    "resource_ids": init_ctx["resource_ids"],
                    "clickable_texts": init_ctx["clickable_texts"],
                }
                directive = self.planner.generate_exploration_directive(
                    self.memory, init_elements,
                )
                self.explorer.set_directive(directive)
            except Exception as e:
                logger.warning("Could not generate initial directive: %s", e)

            for step_num in range(max_steps):
                # ── Check for API stop request ──
                if self._stop_requested:
                    logger.info("Stop requested via API -- halting explorer.")
                    break

                self._report_progress(step_num + 1, max_steps)
                logger.info("--- Explorer step %d/%d ---", step_num + 1, max_steps)

                # ------ Session health check (restart if UiAutomator2 crashed) ------
                if not self.recovery.repair_session_if_needed():
                    logger.error("Session repair failed at step %d -- skipping", step_num + 1)
                    time.sleep(2)
                    continue

                ui_ctx = self.navigator.get_ui_context(f"explore_{step_num:04d}")

                # If page source is empty after a UI capture, the session may
                # have died mid-step.  Attempt one more repair before moving on.
                if not ui_ctx.get("page_source"):
                    logger.warning("Empty page source -- attempting session repair")
                    if self.recovery.repair_session_if_needed():
                        ui_ctx = self.navigator.get_ui_context(f"explore_{step_num:04d}_retry")
                    if not ui_ctx.get("page_source"):
                        logger.error("Still no page source after repair -- skipping step")
                        time.sleep(1)
                        continue

                self.memory.record_screen(
                    ui_ctx["state_signature"], ui_ctx["accessibility_ids"]
                )
                # Analyze screenshot for description
                description = ""
                screenshot_path = ui_ctx.get("screenshot_path", "")
                if screenshot_path:
                    try:
                        from ..vlm import analyze_screen_once
                        description = analyze_screen_once(screenshot_path, ui_ctx["state_signature"])
                    except Exception as e:
                        logger.warning(f"VLM screen description failed: {e}")
                self.kb.record_screen(
                    ui_ctx["state_signature"], ui_ctx["accessibility_ids"],
                    screenshot=screenshot_path,
                    description=description,
                )

                # Cache screen sources for end-of-session audits
                sig_now = ui_ctx.get("state_signature", "")
                if sig_now and sig_now not in self._screen_sources:
                    self._screen_sources[sig_now] = (
                        ui_ctx.get("page_source", ""),
                        ui_ctx.get("screenshot_path"),
                    )

                # Plan exploration for newly discovered screens
                self.explorer.plan_for_new_screen(ui_ctx, self.memory)

                # ------ Guard: ensure we're still in the target app ------
                page_src = ui_ctx.get("page_source", "")
                if config.APP_PACKAGE and config.APP_PACKAGE not in page_src:
                    logger.warning(
                        "Left target app (%s) -- relaunching", config.APP_PACKAGE
                    )
                    try:
                        self.controller.driver.activate_app(config.APP_PACKAGE)
                        time.sleep(1.5)
                    except Exception:
                        self.controller.reset_app()
                        time.sleep(2)
                    # After relaunching, clear some explorer state so
                    # it can re-interact with the home screen.
                    self.explorer.on_app_relaunched()
                    continue

                # ------ Visual inspection (once per unique screen) ------
                visual_bugs = self.explorer.visual_inspect_screen(
                    ui_ctx.get("screenshot_path"), ui_ctx
                )
                for vb in visual_bugs:
                    self._record_visual_bug(vb, ui_ctx)

                # ------ Crash / error detection ------
                crash = self.explorer.detect_crash_or_error(ui_ctx)
                if crash:
                    _consecutive_crash_detections += 1
                    if _consecutive_crash_detections <= 3:
                        self._record_visual_bug(crash, ui_ctx)
                        # Try to dismiss crash dialog
                        self.recovery.recover(ui_ctx)
                        continue
                    else:
                        # Stuck on crash screen -- force navigate away
                        logger.warning(
                            "Crash detected %d times in a row -- forcing app restart",
                            _consecutive_crash_detections,
                        )
                        _consecutive_crash_detections = 0
                        self.controller.reset_app()
                        time.sleep(2)
                        continue
                else:
                    _consecutive_crash_detections = 0

                # ------ Accessibility audit (every 5 steps) ------
                if step_num % 5 == 0:
                    self.accessibility.audit_screen(
                        ui_ctx.get("page_source", ""),
                        screenshot_path=ui_ctx.get("screenshot_path"),
                        screen_name=ui_ctx.get("state_signature", ""),
                    )

                # ------ App archetype detection (once, after 10 screens) ------
                if not _archetype_detected and len(self.memory.screens) >= 6:
                    _archetype_detected = True
                    try:
                        archetype = self.kb.detect_app_archetype()
                        predicted = archetype.get("predicted_screens", [])
                        if predicted:
                            logger.info(
                                "Archetype predicts undiscovered screens: %s",
                                predicted,
                            )
                    except Exception as e:
                        logger.debug("Archetype detection failed: %s", e)

                # ------ Refresh Planner directive periodically ------
                if step_num > 0 and step_num % _directive_refresh_interval == 0:
                    try:
                        dir_ctx = self.navigator.get_ui_context(f"directive_{step_num}")
                        dir_elems = {
                            "accessibility_ids": dir_ctx["accessibility_ids"],
                            "resource_ids": dir_ctx["resource_ids"],
                            "clickable_texts": dir_ctx["clickable_texts"],
                        }
                        directive = self.planner.generate_exploration_directive(
                            self.memory, dir_elems,
                        )
                        self.explorer.set_directive(directive)
                        logger.info("Refreshed exploration directive at step %d", step_num)
                    except Exception as e:
                        logger.debug("Directive refresh failed: %s", e)

                # ------ Security: check for data leaks ------
                self.security.check_sensitive_data(
                    ui_ctx.get("page_source", ""),
                    screen_name=ui_ctx.get("state_signature", ""),
                )

                # ------ Recovery check ------
                if self.recovery.needs_recovery(ui_ctx):
                    self.recovery.recover(ui_ctx)
                    continue

                # ------ Explorer picks the next action ------
                action = self.explorer.pick_next_action(ui_ctx, self.memory)
                action_type = action.get("action", "unknown")
                logger.info(
                    "Explorer action: %s -- %s",
                    action_type, action.get("reason", "")[:60],
                )

                # ------ Handle special actions ------
                if action_type == "__reset_app__":
                    logger.warning("Explorer requested app reset to break persistent loop")
                    self.controller.reset_app()
                    time.sleep(2)
                    self.explorer.on_app_relaunched()
                    self.memory.clear_loop_history()
                    continue

                # ------ Execute action directly (bypass LLM) ------
                sig_before = ui_ctx.get("state_signature", "")
                if self.engine:
                    result = self.engine.execute_explorer_action(action, ui_ctx)
                else:
                    result = self.navigator.execute_action_direct(action, ui_ctx)
                    self.explorer.record_action_taken(action)

                # Record transition in the screen graph
                sig_after = result.get("state_signature_after", "")

                # ---- Learn what this element does (persist to KB) ----
                self.explorer.observe_action_result(action, sig_before, sig_after)

                if sig_before and sig_after and sig_before != sig_after:
                    action_desc = action.get("locator_value") or action_type
                    self.memory.record_transition(sig_before, action_desc, sig_after)
                    self.kb.record_transition(sig_before, action_desc, sig_after)

                    # New screen discovered -- replan!
                    try:
                        post_ctx = {
                            "page_source": result.get("post_page_source", ""),
                            "screenshot_path": result.get("post_screenshot_path", ""),
                            "accessibility_ids": result.get("post_accessibility_ids", []),
                            "resource_ids": result.get("post_resource_ids", []),
                            "clickable_texts": result.get("post_clickable_texts", []),
                            "state_signature": sig_after,
                        }
                        self.explorer.plan_for_new_screen(post_ctx, self.memory)
                        # Analyze screenshot for description
                        description = ""
                        screenshot_path = post_ctx.get("screenshot_path", "")
                        if screenshot_path:
                            try:
                                from ..vlm import analyze_screen_once
                                description = analyze_screen_once(screenshot_path, sig_after)
                            except Exception as e:
                                logger.warning(f"VLM screen description failed: {e}")
                        self.kb.record_screen(
                            sig_after, post_ctx.get("accessibility_ids", []),
                            screenshot=screenshot_path,
                            description=description,
                        )
                        # Cache new screen sources for audit phase
                        if sig_after not in self._screen_sources:
                            self._screen_sources[sig_after] = (
                                post_ctx.get("page_source", ""),
                                post_ctx.get("screenshot_path"),
                            )
                    except Exception as e:
                        logger.debug("Could not plan for new screen: %s", e)

                if not self.engine:
                    self.memory.log_action({
                        "action": action_type,
                        "locator": action.get("locator_value"),
                        "success": result.get("success"),
                        "description": result.get("description"),
                        "screen_sig": sig_before,
                    })

                if result.get("bug_report"):
                    self._record_bug_simple(result)

                logger.info(
                    "Explorer result: %s -- %s",
                    "OK" if result["success"] else "FAIL",
                    result["description"],
                )
                time.sleep(0.3)

        except KeyboardInterrupt:
            logger.warning("Interrupted -- session saved.")
        except Exception as e:
            logger.critical("Explorer error: %s", e, exc_info=True)
        finally:
            self._run_parallel_audits()
            self.kb.end_run()
            report_path = self._save_report()
            self._generate_md_report()
            self._teardown()

        stats = self.explorer.coverage_stats()
        visual_bug_count = stats.get("visual_bugs_found", 0)
        logger.info("Explorer stats: %s", stats)
        logger.info("Visual bugs found: %d", visual_bug_count)
        logger.info("Report: %s", report_path)
        return report_path

    def _record_visual_bug(self, bug: Dict[str, Any], ui_ctx: Dict[str, Any]):
        """Record a visual bug detected by the explorer."""
        bug_id = f"visual_bug_{len(self.memory.bugs) + 1}"
        severity = bug.get("severity", "medium")
        desc = f"[{severity.upper()}] {bug.get('type', 'visual')}: {bug.get('description', 'Visual abnormality detected')}"
        if bug.get("location"):
            desc += f" (Location: {bug['location']})"
        logger.warning("VISUAL BUG: %s", desc)

        localization = None
        if self.bug_integration:
            analysis = self.bug_integration.analyze_detected_bug(
                bug_report=desc,
                page_source=ui_ctx.get("page_source", ""),
                screenshot_path=bug.get("screenshot") or ui_ctx.get("screenshot_path"),
            )
            localization = analysis.get("localization", {})

        bug_entry = BugEntry(
            id=bug_id,
            description=desc,
            screenshot=bug.get("screenshot") or ui_ctx.get("screenshot_path"),
            screen_signature=bug.get("screen_signature") or ui_ctx.get("state_signature"),
            localization=localization,
            detected_at=datetime.utcnow().isoformat() + "Z",
        )
        self.memory.add_bug(bug_entry)
        self.kb.record_bug(
            bug_id, desc,
            screenshot=bug_entry.screenshot or "",
            screen_signature=bug_entry.screen_signature or "",
            severity=severity,
        )

    def _record_bug_simple(self, result: Dict[str, Any]):
        """Record a bug without task/step context (explorer mode)."""
        bug_id = f"bug_{len(self.memory.bugs) + 1}"
        bug_desc = result.get("bug_report", "Unknown bug")
        logger.warning("BUG (explorer): %s", bug_desc)

        localization = None
        if self.bug_integration:
            analysis = self.bug_integration.analyze_detected_bug(
                bug_report=bug_desc,
                page_source="",
                screenshot_path=result.get("screenshot"),
            )
            localization = analysis.get("localization", {})

        bug_entry = BugEntry(
            id=bug_id,
            description=bug_desc,
            screenshot=result.get("screenshot"),
            screen_signature=result.get("state_signature_before"),
            localization=localization,
            detected_at=datetime.utcnow().isoformat() + "Z",
        )
        self.memory.add_bug(bug_entry)
        self.kb.record_bug(
            bug_id, bug_desc,
            screenshot=bug_entry.screenshot or "",
            screen_signature=bug_entry.screen_signature or "",
        )

    # ════════════════════════════════════════════════════════════════
    #  Smart Test mode  --  doc-driven, script-generating, memory-persistent
    # ════════════════════════════════════════════════════════════════

    def run_smart_test(
        self,
        *,
        docs_path: Optional[str] = None,
        max_steps: int = 60,
        resume_path: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Documentation-driven intelligent testing:

        1. Load KnowledgeBase (cross-run memory from TinyDB).
        2. Import knowledge from any previous session files.
        3. Ingest app documentation → extract features.
        4. For each untested feature (by priority):
           a. Generate a verification script (ScriptGenerator).
           b. Generate / reuse a nav script to reach the target screen.
           c. Execute: navigate → run verification → record results.
           d. Record navigation path in KB for future reuse.
        5. Persist everything in KB + session memory.
        6. Produce report.
        
        """
        logger.info("=" * 60)
        logger.info("MULTI-AGENT ORCHESTRATOR -- SMART TEST mode")
        logger.info("=" * 60)

        if not self._setup():
            return None

        # ── Session memory ───────────────────────────────────────────
        mem_path = Path(resume_path) if resume_path else (
            config.ARTIFACTS_DIR / "sessions"
            / f"smart_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        self.memory = SessionMemory.load(mem_path)
        self.memory.mode = "smart_test"

        # ── KnowledgeBase lifecycle ──────────────────────────────────
        self.kb.start_run()

        # Import old sessions into KB
        sessions_dir = config.ARTIFACTS_DIR / "sessions"
        self.kb.import_all_sessions(sessions_dir)
        logger.info("KB after import: %s", self.kb.summary_for_llm())

        if self.bug_integration:
            self.bug_integration.start_trace()

        try:
            # ── Phase 1: Doc ingestion ───────────────────────────────
            self._smart_phase_ingest_docs(docs_path)

            # ── Phase 2: Generate & run tests per feature ────────────
            self._smart_phase_test_features(max_steps)

            # ── Phase 3: Audits ──────────────────────────────────────
            self._run_parallel_audits()

        except KeyboardInterrupt:
            logger.warning("Interrupted -- session saved for resume.")
        except Exception as e:
            logger.critical("Smart test error: %s", e, exc_info=True)
        finally:
            self.kb.end_run()
            self.kb.close()
            report_path = self._save_report()
            self._generate_md_report()
            self._teardown()

        logger.info("Session:  %s", mem_path)
        logger.info("Report:   %s", report_path)
        logger.info("KB stats: %s", self.kb.summary_for_llm())
        return report_path

    # ── Smart-test phases ────────────────────────────────────────────

    def _smart_phase_ingest_docs(self, docs_path: Optional[str]):
        """Phase 1: Ingest documentation and register features in KB."""
        logger.info("[Smart Phase 1] Ingesting documentation...")

        # Check if docs already ingested
        existing_features = self.kb.get_all_features()
        if existing_features:
            logger.info("KB already has %d features -- skipping full re-ingest",
                        len(existing_features))
            return

        # Determine documentation source
        doc_text = ""
        if docs_path:
            dp = Path(docs_path)
            if dp.is_file():
                features = self.doc_ingestion.ingest_from_file(dp, app_name=config.APP_PACKAGE)
                doc_text = dp.read_text(encoding="utf-8", errors="replace")[:5000]
            elif dp.is_dir():
                features = self.doc_ingestion.ingest_from_directory(dp, app_name=config.APP_PACKAGE)
            else:
                logger.warning("Docs path not found: %s", docs_path)
                features = []
        else:
            # No explicit docs -- auto-generate feature list from KB screen graph
            # + initial UI scan
            logger.info("No docs provided -- generating features from UI exploration")
            ui_ctx = self.navigator.get_ui_context("smart_init")
            screen_summary = self.kb.get_screen_graph_summary()
            doc_text = f"App: {config.APP_PACKAGE}\nKnown screens:\n{screen_summary}"
            features = self.doc_ingestion.ingest_documentation(
                doc_text,
                app_name=config.APP_PACKAGE,
                existing_features=[],
            )

        if not features:
            logger.warning("No features extracted -- falling back to basic exploration")
            return

        # Enrich features with actual UI elements
        ui_ctx = self.navigator.get_ui_context("smart_enrich")
        ui_elements = {
            "accessibility_ids": ui_ctx["accessibility_ids"],
            "resource_ids": ui_ctx["resource_ids"],
            "clickable_texts": ui_ctx["clickable_texts"],
        }
        features = self.doc_ingestion.enrich_features_with_ui(features, ui_elements)

        # Store in KB
        self.kb.store_app_documentation(doc_text, features, docs_path=docs_path)
        for feat in features:
            feat.setdefault("id", f"feat_{len(self.kb.get_all_features()) + 1}")
            self.kb.add_feature(feat)
            logger.info("Feature registered: [%s] %s", feat.get("priority", "?"), feat.get("name", "?"))

        logger.info("Phase 1 complete: %d features registered", len(features))

        # Decompose complex features into subtask hierarchies
        # immediately, so the execution phase has a detailed tree.
        self._smart_decompose_feature_tasks(features, ui_elements, doc_text)

    def _smart_decompose_feature_tasks(
        self,
        features: List[Dict[str, Any]],
        ui_elements: Dict[str, List[str]],
        doc_text: str,
    ):
        """Decompose each feature into a hierarchical subtask tree.

        Creates a TestPlan from the feature list, then runs the Planner's
        multi-level decomposition on it.  This way the execution phase gets
        a fully expanded task tree instead of flat one-shot steps.
        """
        from ..session_memory import TestGoal, TestTask, TestStep, TestPlan
        goals = []
        for feat in features:
            # Build a task per feature, with verification hints as steps
            steps = [
                TestStep(id=f"{feat.get('id', 'f')}_s{i}", description=hint)
                for i, hint in enumerate(feat.get("verification_hints", []))
            ]
            task = TestTask(
                id=feat.get("id", ""),
                name=feat.get("name", ""),
                description=feat.get("description", ""),
                priority=feat.get("priority", "medium"),
                steps=steps,
                doc_context=feat.get("description", ""),
            )
            goal = TestGoal(
                id=f"goal_{feat.get('id', '')}", name=feat.get("name", ""),
                description=feat.get("description", ""), tasks=[task],
            )
            goals.append(goal)

        if not goals:
            return

        plan = TestPlan(goals=goals, created_at=datetime.utcnow().isoformat() + "Z")

        self.planner.decompose_plan(plan, ui_elements, doc_context=doc_text, kb=self.kb)

        self.memory.set_plan(plan)
        summary = plan.summary()
        logger.info(
            "Smart-test plan: %d goals, %d tasks (depth %d), %d steps",
            summary['goals'], summary['tasks'], summary.get('max_depth', 0), summary['steps'],
        )

    def _smart_phase_test_features(self, max_steps: int):
        """Phase 2: Generate scripts and test each feature."""
        logger.info("[Smart Phase 2] Testing features...")

        features = self.kb.get_features_by_priority()
        # Re-test failed features AND test untested ones
        to_test = [f for f in features if not f.get("tested") or f.get("test_result") == "fail"]
        if not to_test:
            logger.info("All features passed -- nothing to re-test!")
            return

        logger.info("%d features to test (%d untested, %d previously failed)",
                    len(to_test),
                    sum(1 for f in to_test if not f.get("tested")),
                    sum(1 for f in to_test if f.get("test_result") == "fail"))

        steps_used = 0
        features_tested = 0

        for feat in to_test:
            if steps_used >= max_steps:
                logger.info("Step budget exhausted (%d/%d)", steps_used, max_steps)
                break

            feat_name = feat.get("name", "?")
            feat_id = feat.get("id", "?")
            logger.info("--- Testing feature: [%s] %s ---", feat.get("priority", "?"), feat_name)

            # Health check
            if not self.recovery.repair_session_if_needed():
                logger.error("Session repair failed -- skipping feature")
                continue

            try:
                # ── Step 2a: Reset app to home screen + fresh UI ─────
                try:
                    self.controller.reset_app()
                    time.sleep(2.5)  # wait for app to fully restart
                except Exception as e:
                    logger.warning("App reset failed: %s -- continuing", e)

                ui_ctx = self.navigator.get_ui_context(f"smart_feat_{features_tested}")
                ui_elements = {
                    "accessibility_ids": ui_ctx["accessibility_ids"],
                    "resource_ids": ui_ctx["resource_ids"],
                    "clickable_texts": ui_ctx["clickable_texts"],
                }
                self.memory.record_screen(ui_ctx["state_signature"], ui_ctx["accessibility_ids"])
                self.kb.record_screen(ui_ctx["state_signature"], ui_ctx["accessibility_ids"])

                # ── Step 2b: Generate verification script ────────────
                screen_graph = self.kb.get_screen_graph_summary()
                v_script = self.script_generator.generate_verification_script(
                    feat, ui_elements,
                    screen_graph_summary=screen_graph,
                )
                if not v_script:
                    logger.warning("Could not generate script for %s -- skipping", feat_name)
                    continue

                # Store in KB
                v_script["feature_id"] = feat_id
                v_doc_id = self.kb.add_verification_script(v_script)
                self.kb.link_feature_to_script(feat_id, v_doc_id)
                logger.info("Generated verification script: %s (%d steps, %d assertions)",
                            v_script.get("name", "?"),
                            len(v_script.get("steps", [])),
                            len(v_script.get("assertions", [])))

                # ── Step 2c: Navigate to target screen ───────────────
                # Check if we have a cached nav script
                target_screens = feat.get("expected_screens", [])
                nav_script = None
                if target_screens:
                    for ts in target_screens:
                        # Search KB for existing nav script
                        all_screens = self.kb.get_all_screens()
                        matching = [s for s in all_screens if ts.lower() in (s.get("name") or "").lower()]
                        if matching:
                            nav = self.kb.get_nav_script_for_screen(matching[0]["signature"])
                            if nav:
                                nav_script = nav
                                break

                # If no cached nav script, try to generate one
                if not nav_script and target_screens:
                    nav_data = self.script_generator.generate_nav_script(
                        target_screens[0], ui_elements,
                        screen_graph_summary=screen_graph,
                    )
                    if nav_data:
                        nav_script = nav_data

                # ── Step 2d: Execute navigation + verification ───────
                exec_result = self.script_executor.run_feature_test(
                    nav_script, v_script
                )

                steps_in_script = (
                    len(v_script.get("steps", []))
                    + (len(nav_script.get("steps", [])) if nav_script else 0)
                )
                steps_used += max(steps_in_script, 1)

                # ── Step 2e: Record results ──────────────────────────
                test_result = exec_result.get("result", "error")
                self.kb.mark_script_result(v_doc_id, test_result)
                self.kb.mark_feature_tested(feat_id, test_result)

                # Record nav script if navigation succeeded
                nav_res = exec_result.get("nav_result")
                if nav_script and nav_res:
                    final_sig = nav_res.get("final_signature", "")
                    if final_sig:
                        nav_doc_id = self.kb.add_nav_script(
                            f"Navigate to {feat_name}",
                            final_sig,
                            nav_script.get("steps", []),
                            verified=nav_res.get("success", False),
                        )
                        logger.info("Stored nav script (doc_id=%d, verified=%s)",
                                    nav_doc_id, nav_res.get("success", False))

                # Record post-execution screen in KB
                post_sig = exec_result.get("final_signature", "")
                if post_sig:
                    post_ctx = self.navigator.get_ui_context(f"smart_post_{features_tested}")
                    self.kb.record_screen(post_sig, post_ctx["accessibility_ids"])
                    self.memory.record_screen(post_sig, post_ctx["accessibility_ids"])

                # Record bugs
                for bug in exec_result.get("bugs", []):
                    self._record_smart_bug(bug, feat_name)

                # Log result
                logger.info("Feature [%s] result: %s (assertions: %d/%d passed)",
                            feat_name, test_result,
                            exec_result.get("assertions_passed", 0),
                            exec_result.get("assertions_total", 0))

                features_tested += 1

                # Log action
                self.memory.log_action({
                    "action": "smart_test",
                    "feature": feat_name,
                    "result": test_result,
                    "assertions_passed": exec_result.get("assertions_passed", 0),
                    "assertions_total": exec_result.get("assertions_total", 0),
                    "success": test_result == "pass",
                })

            except Exception as e:
                logger.error("Error testing feature %s: %s", feat_name, e, exc_info=True)
                self.memory.log_action({
                    "action": "smart_test",
                    "feature": feat_name,
                    "result": "error",
                    "success": False,
                    "description": str(e),
                })

        logger.info("Phase 2 complete: %d features tested, %d steps used",
                     features_tested, steps_used)

    def _record_smart_bug(self, bug: Dict[str, Any], feature_name: str):
        """Record a bug found during smart testing."""
        bug_id = f"smart_bug_{len(self.memory.bugs) + 1}"
        desc = f"[{feature_name}] {bug.get('description', 'Unknown')}"
        logger.warning("BUG (smart test): %s", desc)

        localization = None
        if self.bug_integration:
            analysis = self.bug_integration.analyze_detected_bug(
                bug_report=desc,
                page_source="",
                screenshot_path=bug.get("screenshot"),
            )
            localization = analysis.get("localization", {})

        bug_entry = BugEntry(
            id=bug_id,
            description=desc,
            severity=bug.get("severity", "medium"),
            screenshot=bug.get("screenshot"),
            screen_signature=bug.get("screen_signature"),
            localization=localization,
            detected_at=datetime.utcnow().isoformat() + "Z",
        )
        self.memory.add_bug(bug_entry)
