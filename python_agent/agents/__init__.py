"""
Multi-Agent System for AI-powered mobile testing.

Agents
------
- **Orchestrator**: High-level coordinator; manages the session, delegates to
  specialist agents, decides when to re-plan or abort.
- **Planner**: Generates and maintains a hierarchical test plan (goals → tasks
  → steps).  Independent of navigation.
- **Navigator**: Interacts with the phone via Appium  --  clicks, types, scrolls,
  reads UI state.  Pure executor.
- **Critic**: Validates other agents' outputs  --  detects LLM hallucinations,
  verifies action feasibility, confirms assertions.
"""

from .orchestrator import OrchestratorAgent
from .planner import PlannerAgent
from .navigator import NavigatorAgent
from .critic import CriticAgent
from .recovery import RecoveryAgent
from .explorer import ExplorerAgent
from .reporter import ReporterAgent
from .accessibility import AccessibilityAgent
from .security import SecurityAgent

__all__ = [
    "OrchestratorAgent",
    "PlannerAgent",
    "NavigatorAgent",
    "CriticAgent",
    "RecoveryAgent",
    "ExplorerAgent",
    "ReporterAgent",
    "AccessibilityAgent",
    "SecurityAgent",
]
