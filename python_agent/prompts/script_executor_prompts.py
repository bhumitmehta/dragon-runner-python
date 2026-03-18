"""
Prompt templates for the ScriptExecutor Agent.

The ScriptExecutor replays navigation and verification scripts on the
live device. It mostly delegates to the Navigator, but its system role
is defined here for consistency.
"""
from __future__ import annotations

from .builder import PromptBuilder


# ── System role ──────────────────────────────────────────────────────

SCRIPT_EXECUTOR_SYSTEM_ROLE = (
    "You are a test execution engine that runs UI test scripts step-by-step "
    "and evaluates assertions against the live application state."
)


class ScriptExecutorPrompts:
    """Namespace for ScriptExecutor agent system role.

    The ScriptExecutor does not generate standalone LLM prompts itself
    (it delegates to the Navigator for action resolution), but its
    system role is kept here for completeness and so all agent identities
    live in the prompts package.
    """

    SYSTEM_ROLE = SCRIPT_EXECUTOR_SYSTEM_ROLE
