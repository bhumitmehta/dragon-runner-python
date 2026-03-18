"""
Prompt Builder & Templates for the multi-agent mobile testing system.

This package provides:
- ``PromptBuilder``:  A fluent builder for constructing LLM prompts
  with consistent structure (system role, context sections, rules,
  output format).
- Per-agent prompt template modules that return pre-configured builders
  or finished prompt strings.

Usage
-----
    from python_agent.prompts import PromptBuilder

    prompt = (
        PromptBuilder()
        .system("You are a QA tester.")
        .section("UI ELEMENTS", "Accessibility IDs: [...]")
        .rules(["Only use IDs from the lists above."])
        .json_output({"action": "click", "locator_value": "<id>"})
        .build()
    )
"""

from .builder import PromptBuilder

from .explorer_prompts import ExplorerPrompts
from .planner_prompts import PlannerPrompts
from .navigator_prompts import NavigatorPrompts
from .critic_prompts import CriticPrompts
from .recovery_prompts import RecoveryPrompts
from .reporter_prompts import ReporterPrompts
from .accessibility_prompts import AccessibilityPrompts
from .security_prompts import SecurityPrompts
from .doc_ingestion_prompts import DocIngestionPrompts
from .script_generator_prompts import ScriptGeneratorPrompts
from .script_executor_prompts import ScriptExecutorPrompts

__all__ = [
    "PromptBuilder",
    "ExplorerPrompts",
    "PlannerPrompts",
    "NavigatorPrompts",
    "CriticPrompts",
    "RecoveryPrompts",
    "ReporterPrompts",
    "AccessibilityPrompts",
    "SecurityPrompts",
    "DocIngestionPrompts",
    "ScriptGeneratorPrompts",
    "ScriptExecutorPrompts",
]
