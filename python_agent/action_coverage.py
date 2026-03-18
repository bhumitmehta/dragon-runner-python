"""
Action-Based Coverage Model
============================

Replaces hash-based screen identity with action-based coverage tracking.

Core insight: The question isn't "have I seen this screen?" but 
"have I clicked every meaningful thing on this screen?"

This eliminates:
- Hash collisions
- Skeletonization complexity  
- Scroll/modal/drawer special cases
- Timestamp normalization
- List count heuristics

Usage:
    from action_coverage import ActionCoverageTracker, Action
    
    tracker = ActionCoverageTracker()
    
    # In your crawler loop
    while True:
        actions = tracker.get_available_actions(page_source, current_activity)
        unexplored = tracker.get_unexplored_actions(actions)
        
        if not unexplored:
            break  # Coverage complete for this area
            
        action = select_action(unexplored)  # Your logic here
        tracker.mark_explored(action)
        execute(action)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Set, Any
from datetime import datetime


@dataclass(frozen=True)
class Action:
    """
    Represents a single interactable element on a screen.
    
    Uniquely identified by activity + element_id combination.
    The element_id should be stable across visits (resource-id, content-desc, or text).
    """
    activity: str           # Android activity name (e.g., "com.example.app.MainActivity")
    element_id: str         # Stable identifier (resource-id, content-desc, or text)
    element_type: str       # "button", "link", "input", "checkbox", "menu_item", etc.
    bounds: Optional[str] = None  # "x,y,w,h" for disambiguation when IDs aren't unique
    
    @property
    def signature(self) -> str:
        """Unique signature for deduplication: ActivityName::element_id"""
        return f"{self.activity}::{self.element_id}"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Action:
        return cls(**data)


@dataclass
class ActionResult:
    """Tracks what happened when an action was executed."""
    action: Action
    timestamp: datetime
    success: bool
    new_activity: Optional[str] = None  # Activity we ended up on
    error_message: Optional[str] = None
    screenshot_path: Optional[str] = None


class ActionCoverageTracker:
    """
    Tracks which actions have been explored across the entire crawl.
    
    This is the core state - not "screens visited" but "actions explored".
    Two screens with the same activity name share the same action namespace,
    so opening a drawer doesn't create "new" actions to explore.
    """
    
    def __init__(self, persistence_path: Optional[str] = None):
        """
        Args:
            persistence_path: Optional path to save/load explored actions
        """
        self._explored: Set[str] = set()  # Set of action signatures
        self._action_results: Dict[str, ActionResult] = {}  # signature -> result
        self._activity_actions: Dict[str, Set[str]] = {}  # activity -> set of element_ids
        self._persistence_path = persistence_path
        
        if persistence_path:
            self._load()
    
    # ── Core API ─────────────────────────────────────────────────────
    
    def get_available_actions(self, page_source: str, current_activity: str) -> Set[Action]:
        """
        Extract all interactable elements from the current screen.
        
        Args:
            page_source: XML page source from Appium
            current_activity: Current Android activity name
            
        Returns:
            Set of Action objects representing all clickable elements
        """
        actions = set()
        elements = self._extract_interactive_elements(page_source)
        
        for el in elements:
            action = Action(
                activity=current_activity,
                element_id=el.get("identifier", ""),
                element_type=el.get("type", "unknown"),
                bounds=el.get("bounds")
            )
            if action.element_id:  # Skip elements without identifiers
                actions.add(action)
        
        # Track what actions are available on this activity
        if current_activity not in self._activity_actions:
            self._activity_actions[current_activity] = set()
        self._activity_actions[current_activity].update(a.element_id for a in actions)
        
        return actions
    
    def get_unexplored_actions(self, available_actions: Set[Action]) -> Set[Action]:
        """
        Return actions that haven't been explored yet.
        
        This is the key coverage check - not "is this a new screen?" but
        "are there actions here I haven't tried?"
        """
        return {a for a in available_actions if a.signature not in self._explored}
    
    def mark_explored(self, action: Action, result: Optional[ActionResult] = None):
        """
        Mark an action as explored.
        
        Call this AFTER executing the action.
        """
        self._explored.add(action.signature)
        if result:
            self._action_results[action.signature] = result
        
        if self._persistence_path:
            self._save()
    
    def is_explored(self, action: Action) -> bool:
        """Check if a specific action has been explored."""
        return action.signature in self._explored
    
    # ── Coverage Metrics ─────────────────────────────────────────────
    
    def get_coverage_stats(self) -> Dict[str, Any]:
        """
        Get coverage statistics.
        
        Returns:
            {
                "total_explored": int,
                "by_activity": Dict[str, int],
                "activities_seen": int,
                "success_rate": float
            }
        """
        total = len(self._explored)
        by_activity = {}
        
        for sig in self._explored:
            activity = sig.split("::")[0]
            by_activity[activity] = by_activity.get(activity, 0) + 1
        
        success_count = sum(
            1 for r in self._action_results.values() if r.success
        )
        
        return {
            "total_explored": total,
            "by_activity": by_activity,
            "activities_seen": len(self._activity_actions),
            "success_rate": success_count / total if total > 0 else 0.0
        }
    
    def get_activity_coverage(self, activity: str) -> Dict[str, Any]:
        """
        Get coverage details for a specific activity.
        
        Returns:
            {
                "activity": str,
                "total_actions": int,
                "explored": int,
                "unexplored": int,
                "coverage_percent": float,
                "unexplored_actions": List[str]
            }
        """
        all_actions = self._activity_actions.get(activity, set())
        explored = {
            sig.split("::")[1] 
            for sig in self._explored 
            if sig.startswith(f"{activity}::")
        }
        unexplored = all_actions - explored
        
        total = len(all_actions)
        return {
            "activity": activity,
            "total_actions": total,
            "explored": len(explored),
            "unexplored": len(unexplored),
            "coverage_percent": (len(explored) / total * 100) if total > 0 else 0.0,
            "unexplored_actions": list(unexplored)
        }
    
    def is_activity_fully_explored(self, activity: str) -> bool:
        """Check if all known actions on an activity have been explored."""
        coverage = self.get_activity_coverage(activity)
        return coverage["unexplored"] == 0 and coverage["total_actions"] > 0
    
    # ── Loop Detection ───────────────────────────────────────────────
    
    def detect_action_loop(self, recent_actions: List[Action], window: int = 8) -> bool:
        """
        Detect if we're stuck in an action loop.
        
        Args:
            recent_actions: List of recently executed actions (most recent last)
            window: Number of recent actions to check
            
        Returns:
            True if the same action appears 3+ times in window
        """
        if len(recent_actions) < 3:  # Need at least 3 actions to detect a loop
            return False
        
        # Look at last N actions
        recent = recent_actions[-min(window, len(recent_actions)):]
        signatures = [a.signature for a in recent]
        
        # Count occurrences of each signature
        from collections import Counter
        counts = Counter(signatures)
        
        # Loop if any signature appears 3+ times
        return any(c >= 3 for c in counts.values())
    
    # ── Persistence ──────────────────────────────────────────────────
    
    def _save(self):
        """Save explored actions to disk."""
        if not self._persistence_path:
            return
            
        data = {
            "explored": list(self._explored),
            "activity_actions": {k: list(v) for k, v in self._activity_actions.items()},
            "results": [
                {
                    "action": r.action.to_dict(),
                    "timestamp": r.timestamp.isoformat(),
                    "success": r.success,
                    "new_activity": r.new_activity,
                    "error_message": r.error_message
                }
                for r in self._action_results.values()
            ]
        }
        
        with open(self._persistence_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _load(self):
        """Load explored actions from disk."""
        import os
        if not os.path.exists(self._persistence_path):
            return
            
        try:
            with open(self._persistence_path, 'r') as f:
                data = json.load(f)
            
            self._explored = set(data.get("explored", []))
            self._activity_actions = {
                k: set(v) 
                for k, v in data.get("activity_actions", {}).items()
            }
            
            for r_data in data.get("results", []):
                action = Action.from_dict(r_data["action"])
                result = ActionResult(
                    action=action,
                    timestamp=datetime.fromisoformat(r_data["timestamp"]),
                    success=r_data["success"],
                    new_activity=r_data.get("new_activity"),
                    error_message=r_data.get("error_message")
                )
                self._action_results[action.signature] = result
                
        except Exception as e:
            print(f"Failed to load action coverage: {e}")
    
    # ── XML Extraction ────────────────────────────────────────────────
    
    def _extract_interactive_elements(self, page_source: str) -> List[Dict[str, Any]]:
        """
        Extract interactive elements from XML page source.
        
        Returns list of dicts with keys:
        - identifier: resource-id, content-desc, or text (in that priority)
        - type: element classification
        - bounds: "x,y,w,h" string
        - clickable: bool
        - scrollable: bool
        """
        import xml.etree.ElementTree as ET
        
        elements = []
        
        try:
            root = ET.fromstring(page_source)
        except ET.ParseError:
            return elements
        
        for el in root.iter():
            attrib = el.attrib
            
            # Skip non-clickable elements (unless they're inputs)
            clickable = attrib.get("clickable") == "true"
            long_clickable = attrib.get("long-clickable") == "true"
            checkable = attrib.get("checkable") == "true"
            editable = attrib.get("editable") == "true"
            
            if not (clickable or long_clickable or checkable or editable):
                continue
            
            # Get identifier (priority: resource-id > content-desc > text)
            identifier = (
                attrib.get("resource-id", "").split("/")[-1] or  # Remove package prefix
                attrib.get("content-desc", "") or
                attrib.get("text", "")
            )
            
            if not identifier:
                # Use bounds as fallback for elements without text/ids
                identifier = f"bounds:{attrib.get('bounds', '')}"
            
            # Determine element type
            class_name = attrib.get("class", "").split(".")[-1].lower()
            
            if "edit" in class_name or editable:
                el_type = "input"
            elif "check" in class_name or checkable:
                el_type = "checkbox"
            elif "button" in class_name:
                el_type = "button"
            elif "image" in class_name or "img" in class_name:
                el_type = "image_button" if clickable else "image"
            elif "text" in class_name:
                el_type = "text_button" if clickable else "text"
            elif "menu" in identifier.lower() or "nav" in identifier.lower():
                el_type = "menu_item"
            else:
                el_type = "unknown"
            
            elements.append({
                "identifier": identifier,
                "type": el_type,
                "bounds": attrib.get("bounds"),
                "clickable": clickable,
                "long_clickable": long_clickable,
                "scrollable": attrib.get("scrollable") == "true",
                "class": class_name
            })
        
        return elements


# ── Simple Crawler Example ─────────────────────────────────────────

def example_crawler_loop():
    """
    Example of how to use ActionCoverageTracker in a crawler.
    
    This replaces the hash-based approach with action-based coverage.
    """
    tracker = ActionCoverageTracker(persistence_path="coverage.json")
    
    # Mock functions - replace with your actual implementations
    def get_page_source() -> str:
        return "<xml>...</xml>"  # From Appium
    
    def get_current_activity() -> str:
        return "MainActivity"  # From Appium
    
    def select_action(actions: Set[Action]) -> Action:
        """Your prioritization logic here."""
        return min(actions, key=lambda a: a.element_type)  # Example: alphabetical
    
    def execute_action(action: Action) -> bool:
        """Execute the action and return success."""
        print(f"Executing: {action.signature}")
        return True
    
    # Main crawl loop
    max_iterations = 100
    for i in range(max_iterations):
        page_source = get_page_source()
        current_activity = get_current_activity()
        
        # Get available actions on current screen
        available = tracker.get_available_actions(page_source, current_activity)
        
        # Filter to unexplored actions
        unexplored = tracker.get_unexplored_actions(available)
        
        if not unexplored:
            print(f"Iteration {i}: No unexplored actions on {current_activity}")
            # Could navigate to different activity here
            break
        
        # Select and execute an unexplored action
        action = select_action(unexplored)
        success = execute_action(action)
        
        # Mark as explored
        result = ActionResult(
            action=action,
            timestamp=datetime.now(),
            success=success,
            new_activity=get_current_activity()
        )
        tracker.mark_explored(action, result)
        
        print(f"Iteration {i}: Explored {action.signature}")
    
    # Print coverage stats
    stats = tracker.get_coverage_stats()
    print(f"\nCoverage complete!")
    print(f"Total actions explored: {stats['total_explored']}")
    print(f"Activities seen: {stats['activities_seen']}")
    print(f"By activity: {stats['by_activity']}")


if __name__ == "__main__":
    example_crawler_loop()
