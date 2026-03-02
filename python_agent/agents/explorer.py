"""
Explorer Agent  --  curiosity-driven autonomous exploration to maximise
screen and feature coverage.

Unlike the Navigator (which follows specific step instructions from the
Planner), the Explorer decides *on its own* which elements to interact
with, prioritising areas that haven't been visited yet.  It builds a
heuristic coverage model and uses the LLM to pick the most promising
element to interact with next.

Enhanced with:
- Visual bug detection via VLM (screenshot analysis)
- Proactive scrolling to discover off-screen content
- Input field testing with various data types
- Comprehensive element interaction (click, long-press, checkboxes)
"""
from __future__ import annotations

import json
import random
import time
from typing import Any, Dict, List, Optional, Set

from .base import BaseAgent
from ..logging_config import get_logger
from ..appium_controller import AppiumController

logger = get_logger("agents.explorer")
from ..ui_extract import (
    extract_clickable_accessibility_ids,
    extract_clickable_resource_ids,
    extract_clickable_texts,
    extract_input_fields,
    extract_scrollable_containers,
    extract_all_interactive_elements,
)
from ..memory import state_signature_from_xml
from ..session_memory import SessionMemory

# Test data for filling input fields
_INPUT_TEST_DATA = {
    "email": ["bob@example.com", "invalid-email", ""],
    "password": ["10203040", "x", ""],
    "username": ["bob@example.com", "admin'; DROP TABLE users;--", ""],
    "search": ["shoes", "", "🔥emoji test"],
    "phone": ["+1234567890", "abc", ""],
    "name": ["Test User", "A" * 200, ""],
    "default": ["test input", "12345", ""],
}


class ExplorerAgent(BaseAgent):
    name = "explorer"
    system_role = (
        "You are a thorough mobile app QA explorer. "
        "Your goal is to maximise coverage -- visit every screen, interact "
        "with every element, scroll to find hidden content, fill input fields, "
        "and visually inspect each screen for bugs. Report anything unusual: "
        "broken layouts, overlapping elements, missing images, wrong text, "
        "unresponsive buttons, crashes, or unexpected behaviour."
    )

    def __init__(self, controller: AppiumController):
        super().__init__()
        self.controller = controller
        self._tried_elements: Set[str] = set()
        self._tried_inputs: Set[str] = set()
        self._screen_visit_count: Dict[str, int] = {}
        self._screens_scrolled: Set[str] = set()
        self._screens_visually_checked: Set[str] = set()
        self._visual_bugs: List[Dict[str, Any]] = []
        self._total_elements_found: int = 0
        self._consecutive_escapes: int = 0  # Track how many escapes in a row
        self._consecutive_scrolls: int = 0  # Track consecutive scroll actions
        self._last_screen_sig: str = ""
        self._loop_break_counter: int = 0  # Escalates loop-breaking strategy
        # Per-screen exploration plans: sig -> ordered list of element IDs
        self._screen_plans: Dict[str, List[str]] = {}
        self._screen_plan_index: Dict[str, int] = {}  # sig -> next index

    # ── Public API ───────────────────────────────────────────────────

    def pick_next_action(
        self,
        ui_context: Dict[str, Any],
        memory: SessionMemory,
    ) -> Dict[str, Any]:
        """
        Choose the best next exploratory action to maximise coverage.
        Uses session memory's screen graph + action log to avoid loops.

        Priority order:
        0. Detect action loop via memory -- break out immediately
        1. Scroll if this screen has scrollable content we haven't scrolled yet
        2. Fill input fields we haven't tested
        3. Click untried elements (LLM-guided)
        4. Long-press long-clickable elements
        5. Use memory's screen graph to navigate toward unvisited screens
        6. Escape (back/scroll) if everything tried
        """
        sig = ui_context.get("state_signature", "")
        self._screen_visit_count[sig] = self._screen_visit_count.get(sig, 0) + 1
        # Also use session memory's persistent visit count
        mem_visits = memory.get_screen_visit_count(sig)
        logger.debug(
            "pick_next_action  screen=%s  local_visit#%d  mem_visits=%d",
            sig[:16], self._screen_visit_count[sig], mem_visits,
        )

        acc_ids = ui_context.get("accessibility_ids", [])
        res_ids = ui_context.get("resource_ids", [])
        texts = ui_context.get("clickable_texts", [])
        page_source = ui_context.get("page_source", "")

        # Track total unique elements found
        all_ids = set(acc_ids + res_ids + texts)
        self._total_elements_found = max(self._total_elements_found, len(all_ids))

        # 0) Check session memory for action loops
        if memory.detect_action_loop(window=8):
            self._loop_break_counter += 1
            logger.warning(
                "Action loop detected via session memory (break attempt #%d)",
                self._loop_break_counter,
            )
            return self._break_loop(ui_context, memory, all_ids)
        else:
            # No loop -- reset escalation counter
            if self._loop_break_counter > 0:
                logger.info("Loop broken successfully after %d attempts", self._loop_break_counter)
            self._loop_break_counter = 0

        # If screen changed, reset escape counter and plan for new screen
        if sig != self._last_screen_sig:
            self._consecutive_escapes = 0
            self._consecutive_scrolls = 0
            self._last_screen_sig = sig

        # 1) Proactive scroll: scroll if this screen has scrollable content
        #    BUT skip if we've done 3+ consecutive scrolls (loop prevention)
        if (
            sig not in self._screens_scrolled
            and self._consecutive_scrolls < 3
            and extract_scrollable_containers(page_source)
        ):
            self._screens_scrolled.add(sig)
            return {
                "action": "scroll", "locator_type": None, "locator_value": None,
                "text": None, "direction": "down",
                "reason": "Proactive scroll to discover off-screen content",
            }

        # 2) Fill untried input fields
        input_fields = extract_input_fields(page_source)
        untried_inputs = [f for f in input_fields if f["locator_value"] not in self._tried_inputs]
        if untried_inputs:
            field = untried_inputs[0]
            self._tried_inputs.add(field["locator_value"] or field.get("bounds", ""))
            test_text = self._pick_input_data(field)
            return {
                "action": "input",
                "locator_type": field["locator_type"],
                "locator_value": field["locator_value"],
                "text": test_text,
                "direction": None,
                "cx": field.get("cx"),
                "cy": field.get("cy"),
                "reason": f"Testing input field: {field.get('hint', field['locator_value'])}",
            }

        # 3) Follow the screen plan if one exists
        plan_action = self._follow_screen_plan(sig, ui_context)
        if plan_action:
            return plan_action

        # 4) Click untried elements (deprioritise Critic-penalised ones)
        untried = all_ids - self._tried_elements
        penalised = memory.get_penalised_elements(threshold=-1.0)
        if penalised:
            preferred = untried - penalised
            if preferred:
                untried = preferred  # try non-penalised first
                logger.debug("Deprioritised %d Critic-penalised elements", len(penalised & (all_ids - self._tried_elements)))

        if self._screen_visit_count.get(sig, 0) > 4 and not untried:
            # If we keep returning to the same screen, use memory graph
            # to find a known transition toward a less-visited screen.
            if mem_visits > 6 and all_ids:
                nav_target = self._navigate_via_memory(ui_context, memory, all_ids)
                if nav_target:
                    return nav_target
                # Fallback: force-click random element
                chosen = random.choice(list(all_ids))
                logger.debug("Over-visited screen (%d mem visits) -- force-clicking %s", mem_visits, chosen)
                return self._make_click_action(chosen, ui_context)
            logger.debug("Screen over-visited with no untried elements, escaping")
            return self._escape_strategy(ui_context, memory, all_ids)

        if untried and len(untried) <= 50:
            return self._llm_pick(ui_context, list(untried), memory)

        if untried:
            chosen = random.choice(list(untried))
            return self._make_click_action(chosen, ui_context)

        # 4) Try long-press on long-clickable elements
        all_elements = extract_all_interactive_elements(page_source)
        long_pressable = [
            e for e in all_elements
            if e["long_clickable"] and (e["accessibility_id"] or e["resource_id"]) not in self._tried_elements
        ]
        if long_pressable:
            el = long_pressable[0]
            key = el["accessibility_id"] or el["resource_id"] or el["text"]
            self._tried_elements.add(key)
            return {
                "action": "long_press",
                "locator_type": "accessibility_id" if el["accessibility_id"] else "resource_id" if el["resource_id"] else "text",
                "locator_value": key,
                "text": None, "direction": None,
                "reason": f"Long-pressing element: {key}",
            }

        # 5) Use memory graph to navigate toward unvisited screens
        nav = self._navigate_via_memory(ui_context, memory, all_ids)
        if nav:
            return nav

        # 6) Nothing new -- escape
        return self._escape_strategy(ui_context, memory, all_ids)

    def on_app_relaunched(self):
        """Called when the app is relaunched after leaving the target app.

        Partially resets exploration state so the explorer can
        re-interact with the home screen instead of immediately
        escaping.
        """
        # Keep _tried_inputs (no need to re-fill same fields)
        # but wipe half of _tried_elements so it will re-click
        # product items and navigate deeper.
        keep = max(len(self._tried_elements) // 3, 5)
        kept = set(list(self._tried_elements)[:keep])
        cleared = len(self._tried_elements) - len(kept)
        self._tried_elements = kept
        self._screens_scrolled.clear()
        self._screen_plans.clear()
        self._screen_plan_index.clear()
        self._consecutive_escapes = 0
        self._consecutive_scrolls = 0
        self._loop_break_counter = 0
        logger.info("App relaunched -- cleared %d tried elements, reset scroll/plan state", cleared)

    def record_action_taken(self, action: Dict[str, Any]):
        """Tell the explorer which element was just interacted with."""
        lv = action.get("locator_value")
        if lv:
            self._tried_elements.add(lv)
        # Track consecutive scrolls to prevent scroll loops
        act = action.get("action", "")
        if act == "scroll":
            self._consecutive_scrolls += 1
        else:
            self._consecutive_scrolls = 0
        # Reset escape counter on non-escape actions
        if act not in ("back", "scroll"):
            self._consecutive_escapes = 0

    # ── Visual Bug Detection ─────────────────────────────────────────

    def visual_inspect_screen(
        self,
        screenshot_path: Optional[str],
        ui_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Use VLM to visually inspect a screenshot for UI bugs.

        Returns a list of visual bugs found (may be empty).
        """
        sig = ui_context.get("state_signature", "")
        if not screenshot_path or sig in self._screens_visually_checked:
            return []
        self._screens_visually_checked.add(sig)

        prompt = """You are a senior QA tester performing visual inspection of a mobile app screenshot.

Look for ANY of these visual bugs:
1. **Overlapping/truncated text**  --  text cut off, overlapping other elements
2. **Broken layout**  --  misaligned elements, uneven spacing, elements out of bounds
3. **Missing images**  --  blank/placeholder images, broken image icons
4. **Wrong colors/contrast**  --  text hard to read, inconsistent theme
5. **Empty states**  --  screens that look blank when they shouldn't be
6. **Distorted elements**  --  stretched images, squished buttons
7. **Duplicate content**  --  same item appearing multiple times incorrectly
8. **Accessibility**  --  text too small to read, touch targets too small
9. **Rendering glitches**  --  flickering, partial rendering, z-order issues
10. **Unexpected state**  --  error messages, loading forever, wrong screen

If you find bugs, return JSON array. If no visual bugs, return empty array.
Return ONLY JSON (no markdown):
[
    {
        "type": "<bug type from list above>",
        "severity": "critical" | "high" | "medium" | "low",
        "description": "<specific description of what's wrong>",
        "location": "<where on screen: top/middle/bottom, left/center/right>"
    }
]

If no visual bugs found, return: []"""

        try:
            raw = self.ask_vision_cached(screenshot_path, prompt, state_sig=sig)
            parsed = self.parse_json(raw)
            if isinstance(parsed, list):
                bugs = [b for b in parsed if isinstance(b, dict) and "description" in b]
                if bugs:
                    logger.warning("Visual inspection found %d bug(s) on screen %s", len(bugs), sig[:16])
                    for b in bugs:
                        b["screen_signature"] = sig
                        b["screenshot"] = screenshot_path
                    self._visual_bugs.extend(bugs)
                    return bugs
                return []
            return []
        except Exception as e:
            logger.debug("Visual inspection failed: %s", e)
            return []

    def detect_crash_or_error(self, ui_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Check if the current screen shows a crash dialog or error state."""
        page_source = ui_context.get("page_source", "")
        acc_ids = ui_context.get("accessibility_ids", [])
        texts = ui_context.get("clickable_texts", [])
        all_text = " ".join(acc_ids + texts).lower()

        # Only match specific crash dialog phrases -- NOT the generic word "error"
        crash_indicators = [
            "has stopped", "keeps stopping", "isn't responding",
            "unfortunately", "force close", "app has stopped",
            "app has crashed", "fatal exception",
        ]
        for indicator in crash_indicators:
            if indicator in all_text or indicator in page_source.lower():
                return {
                    "type": "crash",
                    "severity": "critical",
                    "description": f"App crash/error detected: '{indicator}' found on screen",
                    "screen_signature": ui_context.get("state_signature", ""),
                    "screenshot": ui_context.get("screenshot_path"),
                }
        return None

    # ── Coverage metrics ─────────────────────────────────────────────

    def coverage_stats(self) -> Dict[str, Any]:
        return {
            "elements_tried": len(self._tried_elements),
            "inputs_tested": len(self._tried_inputs),
            "unique_screens": len(self._screen_visit_count),
            "screens_scrolled": len(self._screens_scrolled),
            "screens_visually_checked": len(self._screens_visually_checked),
            "visual_bugs_found": len(self._visual_bugs),
            "total_screen_visits": sum(self._screen_visit_count.values()),
        }

    def get_visual_bugs(self) -> List[Dict[str, Any]]:
        """Return all visual bugs found during exploration."""
        return list(self._visual_bugs)

    # ── Internals ────────────────────────────────────────────────────

    def _pick_input_data(self, field: Dict[str, Any]) -> str:
        """Pick appropriate test data based on the field hint/name."""
        hint = (field.get("hint", "") + " " + field.get("locator_value", "")).lower()
        for keyword, values in _INPUT_TEST_DATA.items():
            if keyword in hint:
                return values[0]  # Use the primary valid value first
        return _INPUT_TEST_DATA["default"][0]

    def _llm_pick(
        self,
        ui_context: Dict[str, Any],
        untried: List[str],
        memory: SessionMemory,
    ) -> Dict[str, Any]:
        """Let the LLM choose the most interesting untried element."""
        coverage = memory.coverage_summary()
        recent = memory.recent_actions(5)
        history_str = self.format_action_history(recent)

        # Build screen visit info from memory
        sig = ui_context.get("state_signature", "")
        current_visits = memory.get_screen_visit_count(sig)
        least_visited = memory.get_least_visited_screens(5)
        least_visited_str = json.dumps(
            [{"sig": s["signature"][:20], "visits": s["visits"]} for s in least_visited]
        )

        # Get known transitions from this screen
        transition_hint = ""
        known_nav = memory.get_unvisited_transitions(sig)
        if known_nav:
            transition_hint = f"\nKNOWN TRANSITIONS from this screen that lead to LESS-VISITED screens:\n{json.dumps(known_nav[:5])}\nPrefer clicking elements from this list!\n"

        # Get Critic feedback weights (top rewarded + penalised)
        weight_hint = ""
        top_weighted = memory.get_top_weighted_elements(5)
        penalised_ids = memory.get_penalised_elements(threshold=-1.0)
        if top_weighted or penalised_ids:
            weight_hint = "\nCRITIC FEEDBACK (from previous step evaluations):"
            if top_weighted:
                weight_hint += f"\nHighly-rated elements: {json.dumps([w['element_id'] for w in top_weighted[:5]])}"
            if penalised_ids:
                weight_hint += f"\nPenalised elements (AVOID): {json.dumps(list(penalised_ids)[:5])}"
            weight_hint += "\n"

        prompt = f"""You are exploring a mobile app to find bugs and maximise test coverage.

UNTRIED ELEMENTS (never interacted with before):
{json.dumps(untried[:30])}

ALL VISIBLE ELEMENTS:
Accessibility IDs: {json.dumps(ui_context.get('accessibility_ids', [])[:25])}
Clickable Texts: {json.dumps(ui_context.get('clickable_texts', [])[:15])}

COVERAGE SO FAR:
{json.dumps(coverage)}

CURRENT SCREEN has been visited {current_visits} times.
LEAST-VISITED SCREENS: {least_visited_str}
{transition_hint}{weight_hint}
RECENT ACTIONS:
{history_str}

Pick the SINGLE most promising untried element to interact with.
Prefer elements that might:
- Navigate to LESS-VISITED or new screens (menu buttons, navigation items)
- Reveal new screens or features
- Trigger bugs (edge-case actions, unusual buttons)
- Be part of critical flows (login, cart, checkout, settings)
AVOID elements that would keep us on this already well-visited screen.

Return ONLY JSON:
{{
    "action": "click" | "input" | "scroll" | "long_press",
    "locator_type": "accessibility_id" | "resource_id" | "text",
    "locator_value": "<exact value from UNTRIED list>",
    "text": "<for input only>" | null,
    "direction": "down" | null,
    "reason": "<why this element is promising>"
}}"""

        screenshot = ui_context.get("screenshot_path")
        try:
            sig = ui_context.get("state_signature")
            raw = self.ask_vision_cached(screenshot, prompt, state_sig=sig) if screenshot else self.ask_text(prompt)
            parsed = self.parse_json_strict(raw, ["action", "locator_value"])
            if parsed and parsed.get("locator_value") in set(untried):
                return parsed
        except Exception:
            pass

        # Fallback: pick first untried
        return self._make_click_action(untried[0], ui_context)

    def _navigate_via_memory(
        self,
        ui_context: Dict[str, Any],
        memory: SessionMemory,
        all_ids: set,
        exclude: Optional[Set[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Use session memory's screen graph to click an element that
        leads to a less-visited or unvisited screen.

        Args:
            exclude: Set of element IDs to skip (e.g. elements that are
                     part of a detected loop).
        """
        sig = ui_context.get("state_signature", "")
        transition_targets = memory.get_unvisited_transitions(sig)
        skip = exclude or set()
        if transition_targets:
            for action_desc in transition_targets:
                if action_desc in skip:
                    continue
                if action_desc in all_ids:
                    logger.info(
                        "Memory graph: navigating to less-visited screen via '%s'",
                        action_desc,
                    )
                    return self._make_click_action(action_desc, ui_context)
        return None

    def _get_recent_loop_elements(self, memory: SessionMemory) -> Set[str]:
        """Build a set of element IDs used in recent actions -- these are
        likely part of the current loop and should be excluded."""
        recent = memory.recent_actions(10)
        return {a.get("locator", "") for a in recent if a.get("locator")} - {""}

    def _break_loop(
        self,
        ui_context: Dict[str, Any],
        memory: SessionMemory,
        all_ids: set,
    ) -> Dict[str, Any]:
        """Forcibly break out of a detected action loop.

        Uses an escalating strategy based on _loop_break_counter:
          1:   Navigate via memory graph, EXCLUDING loop elements
          2:   Open the menu (to change screen context)
          3:   Pick a specific menu destination
          4:   Reset the app (hard break)
          5+:  Clear all tried elements + reset app
        """
        loop_elements = self._get_recent_loop_elements(memory)
        counter = self._loop_break_counter
        logger.info(
            "_break_loop escalation level %d  (loop elements: %s)",
            counter, list(loop_elements)[:5],
        )

        acc_ids = set(ui_context.get("accessibility_ids", []))

        # ---- Level 1: memory-graph nav excluding loop elements ----
        if counter <= 1:
            nav = self._navigate_via_memory(
                ui_context, memory, all_ids, exclude=loop_elements,
            )
            if nav:
                return nav
            # Also try opening menu
            for menu_name in ("open menu", "Open Menu", "Menu"):
                if menu_name in acc_ids and menu_name not in loop_elements:
                    logger.info("Breaking loop -- opening menu")
                    return self._make_click_action(menu_name, ui_context)

        # ---- Level 2: pick a specific menu destination ----
        if counter <= 2:
            menu_items = [
                "menu item catalog", "menu item webview", "menu item drawing",
                "menu item geo location", "menu item about", "menu item log in",
                "menu item log out", "menu item reset app",
                "menu item api calls", "menu item sauce bot video",
            ]
            for mi in menu_items:
                if mi in acc_ids and mi not in loop_elements:
                    logger.info("Breaking loop via menu item: %s", mi)
                    return self._make_click_action(mi, ui_context)
            # Menu not visible -- try to open it
            for menu_name in ("open menu", "Open Menu", "Menu"):
                if menu_name in acc_ids:
                    return self._make_click_action(menu_name, ui_context)

        # ---- Level 3: force-click any non-loop element ----
        if counter <= 3:
            safe_ids = all_ids - loop_elements
            if safe_ids:
                chosen = random.choice(list(safe_ids))
                logger.info("Breaking loop (level %d) -- force-clicking: %s", counter, chosen)
                self._consecutive_escapes = 0
                return self._make_click_action(chosen, ui_context)

        # ---- Level 4+: HARD RESET -- restart the app ----
        logger.warning("Loop persisted through %d attempts -- requesting app reset", counter)
        self._loop_break_counter = 0  # reset for fresh start
        # Clear plans and partial tried-elements so we can explore fresh
        self._screen_plans.clear()
        self._screen_plan_index.clear()
        self._screens_scrolled.clear()
        if counter >= 5:
            # Full reset of tried elements to get completely fresh
            self._tried_elements.clear()
            logger.info("Full exploration state reset -- fresh start")
        return {
            "action": "__reset_app__", "locator_type": None,
            "locator_value": None, "text": None, "direction": None,
            "reason": f"Breaking persistent loop (level {counter}) -- resetting app",
        }

    def _escape_strategy(
        self,
        ui_context: Dict[str, Any],
        memory: SessionMemory,
        all_ids: set | None = None,
    ) -> Dict[str, Any]:
        """Escape a well-explored screen. Uses memory to make smart choices."""
        self._consecutive_escapes += 1
        recent = memory.recent_actions(6)
        recent_backs = sum(1 for a in recent if a.get("action") == "back")
        recent_scrolls = sum(1 for a in recent if a.get("action") == "scroll")

        # If stuck in a scroll loop (3+ consecutive scrolls), force a back
        if self._consecutive_scrolls >= 3:
            self._consecutive_scrolls = 0
            logger.debug("Breaking scroll loop -- pressing back")
            return {
                "action": "back", "locator_type": None, "locator_value": None,
                "text": None, "direction": None,
                "reason": "Breaking scroll loop -- navigating back",
            }

        # Try memory-guided navigation before random clicking
        if all_ids and self._consecutive_escapes > 2:
            nav = self._navigate_via_memory(ui_context, memory, all_ids)
            if nav:
                self._consecutive_escapes = 0
                return nav

        # If we've been stuck in escape loops (>4 consecutive), force-click
        if self._consecutive_escapes > 4 and all_ids:
            clickable = list(all_ids)
            if clickable:
                chosen = random.choice(clickable)
                self._consecutive_escapes = 0
                logger.debug("Breaking out of loop -- re-clicking: %s", chosen)
                return self._make_click_action(chosen, ui_context)

        # If we've been stuck even longer, try opening the menu
        if self._consecutive_escapes > 6:
            self._consecutive_escapes = 0
            return {
                "action": "click", "locator_type": "accessibility_id",
                "locator_value": "open menu",
                "text": None, "direction": None,
                "reason": "Breaking loop -- opening navigation menu",
            }

        # Normal escape: alternate back/scroll
        if recent_backs >= 2 or recent_scrolls < 1:
            return {
                "action": "scroll", "locator_type": None, "locator_value": None,
                "text": None, "direction": "down",
                "reason": "Scrolling to reveal hidden elements",
            }

        return {
            "action": "back", "locator_type": None, "locator_value": None,
            "text": None, "direction": None,
            "reason": "Screen fully explored -- navigating back",
        }

    # ---- Screen-level exploration planning ----

    def plan_for_new_screen(
        self,
        ui_context: Dict[str, Any],
        memory: SessionMemory,
    ):
        """Create an ordered exploration plan when a NEW screen is discovered.

        Called by the orchestrator whenever the state signature changes.
        Prioritises: navigation elements > input fields > action buttons > decorative.
        """
        sig = ui_context.get("state_signature", "")
        if not sig or sig in self._screen_plans:
            return  # already planned

        acc_ids = ui_context.get("accessibility_ids", [])
        res_ids = ui_context.get("resource_ids", [])
        texts = ui_context.get("clickable_texts", [])
        all_ids = list(dict.fromkeys(acc_ids + res_ids + texts))  # preserve order, dedupe

        # Categorise elements by navigation priority
        nav_keywords = {
            "menu", "catalog", "cart", "login", "log in", "sign",
            "checkout", "settings", "account", "profile", "back",
            "home", "webview", "drawing", "about", "geo",
        }
        nav_elements = []
        action_elements = []
        other_elements = []

        for eid in all_ids:
            if eid in self._tried_elements:
                continue
            eid_lower = eid.lower()
            if any(kw in eid_lower for kw in nav_keywords):
                nav_elements.append(eid)
            elif any(kw in eid_lower for kw in ("button", "add", "remove", "sort", "filter", "submit", "save")):
                action_elements.append(eid)
            else:
                other_elements.append(eid)

        # Build prioritised plan: nav first, then actions, then others
        # Within each group, sort by Critic weight (higher = more promising)
        def _weight_sort(items):
            return sorted(items, key=lambda eid: memory.get_element_weight(eid), reverse=True)

        plan = _weight_sort(nav_elements) + _weight_sort(action_elements) + _weight_sort(other_elements)
        self._screen_plans[sig] = plan
        self._screen_plan_index[sig] = 0

        if plan:
            logger.info(
                "New screen plan [%s]: %d elements (nav=%d, action=%d, other=%d)",
                sig[:12], len(plan), len(nav_elements),
                len(action_elements), len(other_elements),
            )

    def _follow_screen_plan(self, sig: str, ui_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Follow the pre-computed plan for this screen, if one exists."""
        plan = self._screen_plans.get(sig)
        if not plan:
            return None
        idx = self._screen_plan_index.get(sig, 0)
        # Find next untried element in plan
        while idx < len(plan):
            eid = plan[idx]
            idx += 1
            self._screen_plan_index[sig] = idx
            if eid not in self._tried_elements:
                return self._make_click_action(eid, ui_context)
        return None  # plan exhausted

    @staticmethod
    def _make_click_action(element_id: str, ui_context: Dict[str, Any]) -> Dict[str, Any]:
        """Build a click action for the given element, auto-detecting locator type."""
        acc_ids = set(ui_context.get("accessibility_ids", []))
        res_ids = set(ui_context.get("resource_ids", []))

        if element_id in acc_ids:
            lt = "accessibility_id"
        elif element_id in res_ids:
            lt = "resource_id"
        else:
            lt = "text"

        return {
            "action": "click", "locator_type": lt, "locator_value": element_id,
            "text": None, "direction": None,
            "reason": f"Exploring untried element: {element_id}",
        }
