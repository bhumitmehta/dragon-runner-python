import argparse

from .agent import Agent
from .workflow_runner import WorkflowRunner
from .ai_tester import AITester


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

    args = parser.parse_args(argv)

    # Workflow mode (static tests)
    if args.workflow:
        print(f"Starting workflow run: {args.workflow}")
        try:
            runner = WorkflowRunner(use_vision=bool(args.vision))
            out_path = runner.run_file(args.workflow, out_path=args.out)
            print(f"Workflow report written to: {out_path}")
        except Exception as e:
            print(f"An error occurred during workflow execution: {e}")
        return

    # Natural language task mode
    if args.task:
        print(f"Starting AI task execution...")
        try:
            tester = AITester()
            report = tester.execute_task(args.task, max_steps=args.max_steps)
            if report:
                print(f"Task report written to: {report}")
        except Exception as e:
            print(f"An error occurred: {e}")
        return

    # Autonomous exploration mode
    if args.explore:
        print(f"Starting autonomous exploration...")
        try:
            tester = AITester()
            report = tester.explore(max_steps=args.max_steps)
            if report:
                print(f"Exploration report written to: {report}")
        except Exception as e:
            print(f"An error occurred: {e}")
        return

    # Interactive mode
    if args.interactive:
        print(f"Starting interactive mode...")
        try:
            tester = AITester()
            tester.interactive_mode()
        except Exception as e:
            print(f"An error occurred: {e}")
        return

    # Generate tests mode
    if args.generate_tests:
        print(f"Generating test scenarios...")
        try:
            tester = AITester()
            scenarios = tester.generate_tests()
            if scenarios:
                import json
                from . import config
                config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
                out_file = config.REPORTS_DIR / "generated_tests.json"
                out_file.write_text(json.dumps({
                    "version": 1,
                    "data": {},
                    "workflows": scenarios
                }, indent=2), encoding="utf-8")
                print(f"Generated {len(scenarios)} test scenarios: {out_file}")
        except Exception as e:
            print(f"An error occurred: {e}")
        return

    # Default: original agent mode
    print("Starting the visual testing agent (default exploration mode)...")
    print("Tip: Use --help to see all available modes")
    try:
        agent = Agent()
        agent.run()
    except Exception as e:
        print(f"An error occurred during agent execution: {e}")
    print("Agent has finished its run.")


if __name__ == "__main__":
    main()

