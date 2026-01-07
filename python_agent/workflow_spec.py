from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class WorkflowStep:
    action: str
    locator_strategy: Optional[str] = None
    locator_value: Optional[str] = None
    element_id: Optional[str] = None
    text: Optional[str] = None
    seconds: Optional[float] = None
    assert_text: Optional[str] = None
    assert_contains: Optional[str] = None
    direction: Optional[str] = None
    note: Optional[str] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "WorkflowStep":
        if not isinstance(d, dict):
            raise ValueError("Step must be an object")
        action = d.get("action")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("Step.action must be a non-empty string")

        return WorkflowStep(
            action=action.strip(),
            locator_strategy=d.get("locator_strategy"),
            locator_value=d.get("locator_value"),
            element_id=d.get("element_id"),
            text=d.get("text"),
            seconds=d.get("seconds"),
            assert_text=d.get("assert_text"),
            assert_contains=d.get("assert_contains"),
            direction=d.get("direction"),
            note=d.get("note"),
        )


@dataclass
class Workflow:
    name: str
    steps: List[WorkflowStep]

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Workflow":
        if not isinstance(d, dict):
            raise ValueError("Workflow must be an object")
        name = d.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Workflow.name must be a non-empty string")
        steps_raw = d.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValueError(f"Workflow '{name}' must have a non-empty steps array")
        steps = [WorkflowStep.from_dict(x) for x in steps_raw]
        return Workflow(name=name.strip(), steps=steps)


@dataclass
class WorkflowFile:
    version: int
    workflows: List[Workflow]
    data: Dict[str, Any]

    @staticmethod
    def load(path: str | Path) -> "WorkflowFile":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(str(p))
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Workflow file must be a JSON object")

        version = raw.get("version", 1)
        if not isinstance(version, int):
            raise ValueError("version must be an integer")

        data = raw.get("data") or {}
        if not isinstance(data, dict):
            raise ValueError("data must be an object")

        workflows_raw = raw.get("workflows")
        if not isinstance(workflows_raw, list) or not workflows_raw:
            raise ValueError("workflows must be a non-empty array")

        workflows = [Workflow.from_dict(x) for x in workflows_raw]
        return WorkflowFile(version=version, workflows=workflows, data=data)


def substitute_vars(template: Optional[str], data: Dict[str, Any]) -> Optional[str]:
    if template is None:
        return None
    if not isinstance(template, str):
        return template

    out = template
    for key, value in data.items():
        out = out.replace("${" + str(key) + "}", str(value))
    return out
