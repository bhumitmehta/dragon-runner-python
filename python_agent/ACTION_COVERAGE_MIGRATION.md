# Action-Based Coverage Migration Guide

## Overview

This document compares the old hash-based approach with the new action-based coverage model.

## Key Differences

### Hash-Based (Old)
```python
# Question: "Have I seen this screen?"
signature = hash(normalized_xml)  # Fragile, endless edge cases
if signature in visited_screens:
    skip()  # Might miss unexplored actions!
```

**Problems:**
- Scroll position changes hash → same screen, "different" hash
- Modal overlay changes hash → same screen, "different" hash  
- Timestamps in UI change hash → same screen, "different" hash
- List count changes hash → same screen, "different" hash
- Drawer open/closed changes hash → same screen, "different" hash

### Action-Based (New)
```python
# Question: "Have I explored all actions on this screen?"
actions = get_available_actions(page_source, activity)
unexplored = actions - explored_actions
if not unexplored:
    skip()  # Actually done with this screen!
```

**Benefits:**
- Scroll reveals new actions → correctly explores them
- Modal/drawer is same activity → same action namespace → correctly deduplicated
- Timestamps don't affect action extraction → no special handling needed
- List items are individual actions → each explored independently

## Migration Path

### Step 1: Replace Screen Hash with Activity Name

**Before:**
```python
from memory import state_signature_from_xml

sig = state_signature_from_xml(page_source)
if sig in visited:
    return  # Skip "seen" screen
```

**After:**
```python
from action_coverage import ActionCoverageTracker

tracker = ActionCoverageTracker()
activity = get_current_activity()  # From Appium
actions = tracker.get_available_actions(page_source, activity)
unexplored = tracker.get_unexplored_actions(actions)

if not unexplored:
    return  # Actually done with this screen
```

### Step 2: Replace Element Tracking

**Before:**
```python
# Multiple tracking sets
_tried_elements: Set[str] = set()
_tried_inputs: Set[str] = set()
_screens_scrolled: Set[str] = set()

# Complex logic to decide what to do next
if sig not in _screens_scrolled:
    return scroll_action
if element_id not in _tried_elements:
    return click_action
```

**After:**
```python
# Single unified tracking
tracker: ActionCoverageTracker

# Simple logic: any unexplored action
unexplored = tracker.get_unexplored_actions(available)
if unexplored:
    return select_action(unexplored)
```

### Step 3: Simplify Loop Detection

**Before:**
```python
# Hash-based loop detection (fragile)
def detect_loop(recent_hashes):
    return len(set(recent_hashes[-8:])) < 3
```

**After:**
```python
# Action-based loop detection (robust)
def detect_loop(recent_actions):
    return tracker.detect_action_loop(recent_actions, window=8)
```

## Side-by-Side: Explorer Agent

### Hash-Based (Current explorer.py ~350 lines)
```python
class ExplorerAgent:
    def __init__(self):
        self._tried_elements: Set[str] = set()
        self._tried_inputs: Set[str] = set()
        self._screens_scrolled: Set[str] = set()
        self._screen_visit_count: Dict[str, int] = {}
        self._screen_plans: Dict[str, List[str]] = {}
        # ... more tracking sets
    
    def pick_next_action(self, ui_context, memory):
        sig = ui_context.get("state_signature")
        
        # 1. Check for action loops
        if memory.detect_action_loop(window=8):
            return self._break_loop(...)
        
        # 2. Proactive scroll (special case)
        if sig not in self._screens_scrolled:
            return scroll_action
        
        # 3. Input fields (special case)
        if field not in self._tried_inputs:
            return input_action
        
        # 4. Click untried elements
        for element in elements:
            if element not in self._tried_elements:
                return click_action
        
        # 5. Escape strategy
        return escape_action
```

### Action-Based (New ~100 lines)
```python
class ActionCoverageExplorer:
    def __init__(self):
        self.tracker = ActionCoverageTracker()
        self.recent_actions: List[Action] = []
    
    def pick_next_action(self, page_source, activity):
        # Get all available actions
        actions = self.tracker.get_available_actions(page_source, activity)
        
        # Filter to unexplored
        unexplored = self.tracker.get_unexplored_actions(actions)
        
        # Check for loops
        if self.tracker.detect_action_loop(self.recent_actions):
            return self._break_loop()
        
        # Prioritize by type (inputs first, then buttons, etc.)
        if unexplored:
            action = self._prioritize(unexplored)
            self.recent_actions.append(action)
            return action
        
        # Nothing left to explore here
        return self._navigate_elsewhere()
```

## Edge Case Comparison

| Scenario | Hash-Based | Action-Based |
|----------|-----------|--------------|
| **Scroll down** | New hash → "new screen" → re-explores | Same actions visible → no new actions → moves on |
| **Modal opens** | New hash → "new screen" → explores modal | Same activity → same action namespace → already tracked |
| **Drawer opens** | New hash → "new screen" | Same activity → actions already in set → correctly deduped |
| **List with 100 items** | Skeletonization complexity | Each item is an action → explores sample, moves on |
| **Timestamp in UI** | Must normalize → special rule | Not an action → ignored automatically |
| **Dynamic content** | Hash changes → false "new screen" | Actions may change → correctly detects new actions |

## When to Use Each Approach

### Use Action-Based Coverage When:
- You want to explore all interactive elements
- You're building a crawler/test generator
- Screens have dynamic content
- You need to handle modals/drawers
- You want simpler, more maintainable code

### Use Hash-Based (or Hybrid) When:
- You need to detect actual visual changes
- You're doing visual regression testing
- You need to verify screen layout hasn't changed
- You want to cache screenshots by "screen state"

**Recommendation:** Use action-based for exploration logic, minimal hash (activity name only) for coarse "where am I" checks.

## Testing the Migration

```python
# Test that action coverage works correctly
def test_action_coverage():
    tracker = ActionCoverageTracker()
    
    # Same activity, different "screen states"
    activity = "MainActivity"
    
    # Screen 1: Initial state
    xml1 = '<button resource-id="btn1" /><button resource-id="btn2" />'
    actions1 = tracker.get_available_actions(xml1, activity)
    assert len(actions1) == 2
    
    # Screen 2: After scroll (same buttons visible)
    xml2 = '<button resource-id="btn1" /><button resource-id="btn2" scrollable="true" />'
    actions2 = tracker.get_available_actions(xml2, activity)
    assert actions1 == actions2  # Same actions!
    
    # Screen 3: Modal opens (same activity)
    xml3 = '<button resource-id="btn1" /><button resource-id="btn2" /><button resource-id="modal_btn" />'
    actions3 = tracker.get_available_actions(xml3, activity)
    assert len(actions3) == 3  # New action detected
    
    # Explore modal button
    modal_action = [a for a in actions3 if "modal" in a.element_id][0]
    tracker.mark_explored(modal_action)
    
    # Back to screen 1 - modal button not available, but correctly tracked
    unexplored = tracker.get_unexplored_actions(actions1)
    assert len(unexplored) == 2  # btn1 and btn2 still unexplored
```

## Integration with Existing Code

The action-based tracker can coexist with the hash-based system during migration:

```python
class HybridExplorer:
    def __init__(self):
        self.hash_memory = SessionMemory()  # Old system
        self.action_tracker = ActionCoverageTracker()  # New system
    
    def pick_next_action(self, page_source, activity):
        # Use action-based for coverage decisions
        actions = self.action_tracker.get_available_actions(page_source, activity)
        unexplored = self.action_tracker.get_unexplored_actions(actions)
        
        if unexplored:
            action = select_action(unexplored)
            self.action_tracker.mark_explored(action)
            return action
        
        # Fall back to hash-based navigation
        return self.hash_memory.navigate_to_unvisited_screen()
```

## Files Changed

| File | Change |
|------|--------|
| `action_coverage.py` | **NEW** - Action-based coverage implementation |
| `memory.py` | Can remove `state_signature_from_xml()` |
| `agents/explorer.py` | Replace hash checks with action coverage |
| `session_memory.py` | Simplify - remove screen graph complexity |

## Summary

**Action-based coverage:**
- ✅ No hash collisions
- ✅ No skeletonization complexity
- ✅ No scroll/modal/drawer special cases
- ✅ Simpler, more maintainable code
- ✅ Actually answers "what haven't I explored?"

**Trade-off:**
- Loses ability to detect "same screen, different content" (but this was always fragile with hashes anyway)
- Requires activity name (but this is reliable from Appium)
