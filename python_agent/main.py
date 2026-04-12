import argparse

# Lazy imports - heavy modules pulled in only when their mode is requested
# from .agent import Agent
# from .workflow_runner import WorkflowRunner
# from .ai_tester import AITester
from .agents.orchestrator import OrchestratorAgent
from .logging_config import get_logger
from . import config

logger = get_logger("main")


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        prog="python -m python_agent.main",
        description="AI-powered mobile app testing agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run static workflow tests
  python -m python_agent.main --workflow workflows/test_scenarios.json

  # Execute a natural language task
  python -m python_agent.main --task "Login with bob@example.com and password 10203040"

  # Autonomous exploration mode (AI finds bugs)
  python -m python_agent.main --explore

  # Interactive mode (chat with the agent)
  python -m python_agent.main --interactive

  # Generate test scenarios automatically
  python -m python_agent.main --generate-tests
        """
    )
    
    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--workflow",
        help="Path to workflow JSON file. Runs predefined test scenarios.",
        default=None,
    )
    mode_group.add_argument(
        "--task",
        help="Natural language task for the AI to execute (e.g., 'Add a product to cart')",
        default=None,
    )
    mode_group.add_argument(
        "--explore",
        action="store_true",
        help="Autonomous exploration mode - AI explores the app and finds bugs",
    )
    mode_group.add_argument(
        "--interactive",
        action="store_true", 
        help="Interactive mode - chat with the AI agent to control the app",
    )
    mode_group.add_argument(
        "--generate-tests",
        action="store_true",
        help="Generate test scenarios by analyzing the app",
    )
    
    # Additional options
    parser.add_argument(
        "--vision",
        action="store_true",
        help="Enable vision-based visual checks during workflow run",
    )
    parser.add_argument(
        "--out",
        help="Output report path (JSON). Default: auto-generated in artifacts/reports/",
        default=None,
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=30,
        help="Maximum steps for exploration/task mode (default: 30)",
    )
    parser.add_argument(
        "--localize",
        action="store_true",
        help="Enable bug localization (map detected bugs to source files using UniXcoder)",
    )
    parser.add_argument(
        "--source-dir",
        help="Path to the app source code directory for bug localization (default: demo-app/)",
        default=None,
    )
    parser.add_argument(
        "--multiagent",
        action="store_true",
        help="Use the multi-agent system (Orchestrator/Planner/Navigator/Critic) instead of the monolithic AITester",
    )
    parser.add_argument(
        "--explorer",
        action="store_true",
        help="Use the Explorer agent for curiosity-driven autonomous coverage maximisation (implies --multiagent)",
    )
    parser.add_argument(
        "--smart-test",
        action="store_true",
        help="Documentation-driven intelligent testing: ingest docs, generate verification scripts, remember across runs",
    )
    parser.add_argument(
        "--docs",
        help="Path to documentation file or directory for --smart-test mode",
        default=None,
    )
    parser.add_argument(
        "--resume",
        help="Path to a session JSON file to resume a crashed/interrupted multi-agent session",
        default=None,
    )
    parser.add_argument(
        "--app",
        help=(
            "Select a pre-configured application profile to test. "
            "Available profiles: " + ", ".join(config.APP_PROFILES.keys())
        ),
        default=None,
    )
    parser.add_argument(
        "--list-apps",
        action="store_true",
        help="List all available app profiles and exit",
    )

    args = parser.parse_args(argv)

    # ── Require explicit app profile ────────────────────────────────
    if not args.app and (not config.APP_PACKAGE or not config.APP_ACTIVITY):
        logger.error("No app profile selected. Use --app <profile> or set APP_PROFILE env var. Available: %s", ", ".join(config.APP_PROFILES.keys()))
        print("\nERROR: No app profile selected.\n\nPlease launch with --app <profile> or set APP_PROFILE env var.\nAvailable profiles:")
        for name in config.APP_PROFILES:
            print(f"  - {name}")
        return

    # ── Apply app profile ────────────────────────────────────────────
    if args.app:
        try:
            config.apply_app_profile(args.app)
            logger.info("Using app profile: %s (%s)", args.app, config.APP_PACKAGE)
        except ValueError as exc:
            logger.error(str(exc))
            return

    # Common kwargs for bug localization
    _loc_kwargs = {}
    if args.localize:
        _loc_kwargs["localize_bugs"] = True
    if args.source_dir:
        _loc_kwargs["source_code_dir"] = args.source_dir

    # Workflow mode (static tests)
    if args.workflow:
        from .workflow_runner import WorkflowRunner
        logger.info("Starting workflow run: %s", args.workflow)
        try:
            runner = WorkflowRunner(use_vision=bool(args.vision), **_loc_kwargs)
            out_path = runner.run_file(args.workflow, out_path=args.out)
            logger.info("Workflow report written to: %s", out_path)
        except Exception as e:
            logger.error("Error during workflow execution: %s", e, exc_info=True)
        return

    # ── Multi-agent modes ────────────────────────────────────────────
    if args.multiagent or args.resume or args.explorer or getattr(args, 'smart_test', False):
        orch = OrchestratorAgent(**_loc_kwargs)

        # Smart-test mode (doc-driven, script-generating, cross-run memory)
        if getattr(args, 'smart_test', False):
            logger.info("Starting smart test mode (doc-driven + cross-run memory)...")
            try:
                report = orch.run_smart_test(
                    docs_path=args.docs,
                    max_steps=args.max_steps,
                    resume_path=args.resume,
                )
                if report:
                    logger.info("Smart test report: %s", report)
            except Exception as e:
                logger.error("Smart test error: %s", e, exc_info=True)
            return

        # Explorer-driven exploration (curiosity-based)
        if args.explorer:
            logger.info("Starting explorer-driven autonomous exploration...")
            try:
                report = orch.run_explore_with_explorer(
                    max_steps=args.max_steps,
                    resume_path=args.resume,
                )
                if report:
                    logger.info("Explorer report: %s", report)
            except Exception as e:
                logger.error("Explorer error: %s", e, exc_info=True)
            return

        if args.task:
            logger.info("Starting multi-agent task execution...")
            try:
                report = orch.run_task(
                    args.task,
                    max_steps=args.max_steps,
                    resume_path=args.resume,
                )
                if report:
                    logger.info("Multi-agent report: %s", report)
            except Exception as e:
                logger.error("Multi-agent task error: %s", e, exc_info=True)
            return

        # Default multi-agent mode is explore
        logger.info("Starting multi-agent exploration...")
        try:
            report = orch.run_explore(
                max_steps=args.max_steps,
                resume_path=args.resume,
            )
            if report:
                logger.info("Multi-agent report: %s", report)
        except Exception as e:
            logger.error("Multi-agent explore error: %s", e, exc_info=True)
        return

    # Natural language task mode
    if args.task:
        from .ai_tester import AITester
        logger.info("Starting AI task execution...")
        try:
            tester = AITester(**_loc_kwargs)
            report = tester.execute_task(args.task, max_steps=args.max_steps)
            if report:
                logger.info("Task report written to: %s", report)
        except Exception as e:
            logger.error("Task execution error: %s", e, exc_info=True)
        return

    # Autonomous exploration mode
    if args.explore:
        from .ai_tester import AITester
        logger.info("Starting autonomous exploration...")
        try:
            tester = AITester(**_loc_kwargs)
            report = tester.explore(max_steps=args.max_steps)
            if report:
                logger.info("Exploration report written to: %s", report)
        except Exception as e:
            logger.error("Exploration error: %s", e, exc_info=True)
        return

    # Interactive mode
    if args.interactive:
        from .ai_tester import AITester
        logger.info("Starting interactive mode...")
        try:
            tester = AITester(**_loc_kwargs)
            tester.interactive_mode()
        except Exception as e:
            logger.error("Interactive mode error: %s", e, exc_info=True)
        return

    # Generate tests mode
    if args.generate_tests:
        from .ai_tester import AITester
        logger.info("Generating test scenarios...")
        try:
            tester = AITester(**_loc_kwargs)
            scenarios = tester.generate_tests()
            if scenarios:
                import json
                config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
                out_file = config.REPORTS_DIR / "generated_tests.json"
                out_file.write_text(json.dumps({
                    "version": 1,
                    "data": {},
                    "workflows": scenarios
                }, indent=2), encoding="utf-8")
                logger.info("Generated %d test scenarios: %s", len(scenarios), out_file)
        except Exception as e:
            logger.error("Test generation error: %s", e, exc_info=True)
        return

    # Default: original agent mode
    from .agent import Agent
    logger.info("Starting the visual testing agent (default exploration mode)...")
    logger.info("Tip: Use --help to see all available modes")
    try:
        agent = Agent(**_loc_kwargs)
        agent.run()
    except Exception as e:
        logger.error("Agent execution error: %s", e, exc_info=True)
    logger.info("Agent has finished its run.")


def _run_agent_core(
    *,
    mode: str = "task",
    task: str = "",
    max_steps: int = 30,
    explorer: bool = False,
    vision: bool = False,
    status_callback=None,
    kb=None,
) -> None:
    """
    Execute an agent run programmatically (called from the REST API).

    Parameters
    ----------
    mode : str
        "task" | "explore" | "interactive"
    task : str
        Natural language instruction (required when mode="task").
    max_steps : int
        Maximum UI interaction steps.
    explorer : bool
        Use the Explorer agent for curiosity-driven exploration.
    vision : bool
        Enable vision-based visual checks.
    status_callback : callable | None
        If provided, called with ``{"current_step": n, ...}`` dicts
        so the API can push live progress to the frontend.
    kb : KnowledgeBase | None
        If provided, the agent shares this KB instance with the API
        so frontend reads see live updates.
    """
    from .agents.orchestrator import OrchestratorAgent

    orch = OrchestratorAgent(kb=kb)

    # Inject the status callback so orchestrator can report progress
    if status_callback is not None:
        orch._api_status_callback = status_callback

    if mode == "explore" or explorer:
        logger.info("[API] Starting explorer-driven autonomous exploration, max_steps=%d", max_steps)
        orch.run_explore_with_explorer(max_steps=max_steps)
    elif mode == "task" and task:
        logger.info("[API] Starting multi-agent task: %s", task[:80])
        orch.run_task(task, max_steps=max_steps)
    elif mode == "interactive":
        logger.info("[API] Interactive mode not supported via API")
        raise ValueError("Interactive mode is not supported through the REST API. Use the CLI instead.")
    else:
        # Default: explore
        logger.info("[API] Starting multi-agent exploration, max_steps=%d", max_steps)
        orch.run_explore(max_steps=max_steps)


if __name__ == "__main__":
    main()

