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
from ..knowledge_base import KnowledgeBase

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
from ..ui_patterns import UIStructureAnalyzer, should_sample_list_items
from ..feature_detector import FeatureDetector
from ..container_classifier import ContainerClassifier, ContainerType
from ..screen_template_matcher import ScreenTemplateRegistry

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

    def __init__(self, controller: AppiumController, kb: Optional[KnowledgeBase] = None):
        super().__init__()
        self.controller = controller
        self._kb = kb  # cross-run knowledge base (learned nav elements)
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
        # Planner directive (session-level constraints)
        self._directive: Optional[Any] = None  # ExplorationDirective
        # Per-screen step counter (for max_screen_dwell enforcement)
        self._screen_step_count: Dict[str, int] = {}
        # Screens already classified for nav elements (avoid re-classifying)
        self._nav_classified_screens: Set[str] = set()
        # Discovery queue: interesting elements/screens found mid-task,
        # deferred so they don't interrupt the current execution flow.
        self._discovery_queue: List[Dict[str, Any]] = []
        
        # ── Phase 1: Action Priority Scoring ──────────────────────────
        # Track element interactions per session
        self._element_visit_count: Dict[str, int] = {}          # element_id → total clicks
        # Track what screens each element leads to
        self._element_target_screens: Dict[str, Set[str]] = {} # element_id → set(target_sigs)
        # Detect element type (cached from UI structure)
        self._element_type_map: Dict[str, str] = {}            # element_id → type (button|input|menu|...)
        # Visit count for edges (element, from_sig, to_sig)
        self._edge_visit_count: Dict[tuple, int] = {}          # (element, from_sig, to_sig) → count
        
        # ── Phase 3: UI Structure Hinting ─────────────────────────
        # Cache detected container types
        self._container_types: Dict[str, Dict[str, str]] = {}   # screen_sig → {container_id: type}
        # Track which lists we should sample vs test completely
        self._smart_list_sampling: Dict[str, bool] = {}        # element_id → should_sample_all
        
        # ── Phase 2: Container Semantic Classification ────────────
        # Cache of container classification results (element_id → type)
        self._container_classifications: Dict[str, str] = {}   # container_marker → "CONTENT_LIST"|"NAV_LIST"|"OPTION_LIST"
        # Track which containers we've already behaviorally classified
        self._classified_containers: Set[str] = set()
        
        # ── Phase 5: Feature Clustering ───────────────────────────
        # Cached feature clusters for scoring bias
        self._feature_clusters: Optional[List[Any]] = None  # List[FeatureCluster]
        self._last_cluster_computation: int = 0  # How many screens ago we recomputed
        
        # ── Container Classification + Screen Template Matching ─────
        # Multi-stage semantic understanding of UI containers
        self.container_classifier = ContainerClassifier(
            vlm=None,  # Will be set if LLM available
            knowledge_base=kb
        )
        
        # Screen template registry: groups content variations as same template
        self.screen_template_registry = ScreenTemplateRegistry(
            knowledge_base=kb
        )
        if kb:
            self.screen_template_registry.load_from_kb()
        
        # Per-screen container observations for behavioral classification
        self._container_observations: Dict[str, List[Dict[str, Any]]] = {}  # container_id → [observations]
        
        # Container classification cache: {screen_sig}#{container_xpath} → ContainerClassification
        self._container_class_cache: Dict[str, Any] = {}

    # ── Directive interface (Planner → Explorer) ─────────────────────

    def set_directive(self, directive):
        """Accept a session-level ExplorationDirective from the Planner.

        The directive constrains which screens/elements we prioritise
        and how long we dwell on a single screen.
        """
        self._directive = directive
        if directive:
            logger.info(
                "Explorer received directive: %s (dwell=%d, focus=%s)",
                getattr(directive, "objective", "")[:50],
                getattr(directive, "max_screen_dwell", 8),
                getattr(directive, "focus_elements", [])[:3],
            )

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

        # Track per-screen dwell steps (for Planner directive enforcement)
        self._screen_step_count[sig] = self._screen_step_count.get(sig, 0) + 1
        max_dwell = getattr(self._directive, "max_screen_dwell", 8) if self._directive else 8
        if self._screen_step_count.get(sig, 0) > max_dwell:
            logger.info(
                "Screen dwell limit (%d) reached for %s -- forcing move",
                max_dwell, sig[:16],
            )
            nav = self._navigate_via_memory(ui_context, memory, all_ids)
            if nav:
                return nav
            return self._escape_strategy(ui_context, memory, all_ids)

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
                # Fallback: force-click highest-scored element
                scored = self._score_candidates(list(all_ids), sig, memory, ui_context)
                if scored:
                    chosen = scored[0][0]
                    logger.debug("Over-visited screen (%d mem visits) -- clicking top-scored: %s", mem_visits, chosen)
                    return self._make_click_action(chosen, ui_context)
                chosen = random.choice(list(all_ids))
                logger.debug("Over-visited screen (%d mem visits) -- force-clicking random: %s", mem_visits, chosen)
                return self._make_click_action(chosen, ui_context)
            logger.debug("Screen over-visited with no untried elements, escaping")
            return self._escape_strategy(ui_context, memory, all_ids)

        # ── Phase 1: Scored element selection ──────────────────────
        if untried:
            if len(untried) > 100:
                # Too many untried -- ask LLM to narrow down
                return self._llm_pick(ui_context, list(untried)[:50], memory)
            
            # Score all candidates and pick the best
            scored = self._score_candidates(list(untried), sig, memory, ui_context)
            if scored and scored[0][1] > -0.5:  # Only if score is reasonable
                best_element = scored[0][0]
                logger.info(
                    "Phase1 scored pick: %s (score=%.3f)",
                    best_element[:30], scored[0][1]
                )
                return self._make_click_action(best_element, ui_context)
            
            # Fallback: use LLM if scoring gives low confidence
            if len(untried) <= 50:
                return self._llm_pick(ui_context, list(untried), memory)
            
            # Last resort: random
            chosen = random.choice(list(untried))
            logger.debug("Scoring fallback to random: %s", chosen[:30])
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
        self._screen_step_count.clear()
        self._consecutive_escapes = 0
        self._consecutive_scrolls = 0
        self._loop_break_counter = 0
        
        # Phase 1: Partially reset scoring data (keep cross-session insights)
        # Only wipe element_visit_count for cleared elements
        self._element_visit_count = {
            eid: count for eid, count in self._element_visit_count.items()
            if eid in kept
        }
        # Keep element_target_screens (cross-session knowledge)
        # Keep element_type_map (UI structure doesn't change)
        # Keep edge_visit_count (cross-session navigation patterns)
        
        logger.info("App relaunched -- cleared %d tried elements, kept phase1 cross-session data", cleared)

    def record_action_taken(self, action: Dict[str, Any]):
        """Tell the explorer which element was just interacted with."""
        lv = action.get("locator_value")
        if lv:
            self._tried_elements.add(lv)
            # Phase 1: Track element interactions
            self._element_visit_count[lv] = self._element_visit_count.get(lv, 0) + 1
        # Track consecutive scrolls to prevent scroll loops
        act = action.get("action", "")
        if act == "scroll":
            self._consecutive_scrolls += 1
        else:
            self._consecutive_scrolls = 0
        # Reset escape counter on non-escape actions
        if act not in ("back", "scroll"):
            self._consecutive_escapes = 0
    
    def record_transition(self, from_sig: str, element_id: str, to_sig: str):
        """Record that an element led to a specific target screen.
        
        Phase 1: Used for building element_target_screens map for scoring.
        Also gathers behavioral evidence for container classification.
        """
        if element_id:
            targets = self._element_target_screens.get(element_id, set())
            targets.add(to_sig)
            self._element_target_screens[element_id] = targets
            
            # Track edge visits for future enhancements
            edge_key = (element_id, from_sig, to_sig)
            self._edge_visit_count[edge_key] = self._edge_visit_count.get(edge_key, 0) + 1
    
    def analyze_new_screen_containers(self, screen_sig: str, screen_source: str, description: str = ""):
        """Analyze and classify containers in a newly discovered screen.
        
        Phase 2 (behavioral classification) + Phase 3 (structural hinting).
        
        This is called once per screen + helps decide sampling strategy.
        """
        try:
            # Register with template system for future "same screen, different hash" detection
            if self.screen_template_registry:
                template_sig = self.screen_template_registry.register_screen(
                    screen_sig, screen_source, description
                )
                logger.debug(f"Screen {screen_sig[:12]} → template {template_sig[:12]}")
            
            # Extract and analyze UI patterns (Phase 3)
            patterns = UIStructureAnalyzer.analyse_page(screen_source)
            if patterns:
                logger.debug(f"Screen {screen_sig[:12]}: detected {len(patterns)} patterns")
                self._container_types[screen_sig] = {p["container_id"]: p["type"] for p in patterns}
            
        except Exception as e:
            logger.debug(f"Container analysis failed for {screen_sig[:12]}: {e}")
    
    def get_normalized_visit_count(self, screen_sig: str, session_memory: SessionMemory) -> int:
        """Get visit count for a screen, accounting for template variations.
        
        If screen is part of a template (e.g., multiple ProductDetail pages),
        return the aggregate template count rather than just this screen's visits.
        
        This prevents "I visited 3 different product pages" from counting as
        discovering 3 new screens when they're all ProductDetailTemplate.
        """
        if self.screen_template_registry:
            template = self.screen_template_registry.get_template_for_screen(screen_sig)
            if template:
                # Return total screens visited under this template
                return len(template.screen_sigs)
        
        # Fallback: direct visit count from session memory
        return session_memory.get_screen_visit_count(screen_sig)

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

    def _score_candidates(
        self,
        candidates: List[str],
        current_sig: str,
        memory: SessionMemory,
        ui_context: Dict[str, Any],
    ) -> List[tuple]:
        """Score candidate elements with multi-factor priority formula.
        
        Returns list of (element_id, score) tuples sorted by score descending.
        
        Scoring factors:
        - new_screen_bonus: +0.5 if element leads to previously unseen screen
        - exploration_balance: 1.0 - (element_visit_count / max_element_visits)
        - screen_target_bonus: +0.3 per known target that is undervisited
        - kb_reliability: element's nav_count / click_count from KB (0-1)
        - critic_weight: element's cumulative Critic feedback (-1.5 to +1.0)
        - element_type_bonus: navigation elements (menu, back) +0.2, buttons +0.1
        - repetition_penalty: -0.1 * element_visit_count
        """
        if not candidates:
            return []
        
        # Gather baseline data
        least_visited = memory.get_least_visited_screens(5)
        least_visited_sigs = {s["signature"] for s in least_visited}
        max_visits = max(
            (memory.get_screen_visit_count(c) for c in candidates if c in {s["signature"] for s in memory.get_least_visited_screens(999)}),
            default=1
        ) or 1
        
        scores: List[tuple] = []
        
        for element_id in candidates:
            score = 0.0
            details = []
            
            # 1) Element novelty: how many times has this element been interacted with?
            element_visits = self._element_visit_count.get(element_id, 0)
            exploration_balance = 1.0 - min(element_visits / max(max_visits * 3, 1), 1.0)
            score += exploration_balance * 0.3
            details.append(f"explore={exploration_balance:.2f}")
            
            # 2) Does element lead to undervisited screens?
            known_targets = self._element_target_screens.get(element_id, set())
            target_bonus = 0.0
            for target_sig in known_targets:
                # Use template-normalized visit count (handles content list variations)
                target_visits = self.get_normalized_visit_count(target_sig, memory)
                if target_visits <= 2:  # Very undervisited
                    target_bonus += 0.4
                elif target_visits <= 5:  # Moderately undervisited
                    target_bonus += 0.2
            score += min(target_bonus, 0.5)  # Cap at 0.5
            details.append(f"targets={target_bonus:.2f}")
            
            # 3) KB reliability: does element reliably navigate?
            if self._kb:
                kb_behavior = self._kb.get_element_behavior(element_id, current_sig)
                if kb_behavior:
                    nav_count = kb_behavior.get("nav_count", 0)
                    click_count = kb_behavior.get("click_count", 1)
                    reliability = nav_count / max(click_count, 1)
                    score += reliability * 0.2
                    details.append(f"reliability={reliability:.2f}")
            
            # 3b) Phase 5: Feature cluster bonus
            feature_bonus = self._get_feature_cluster_bonus(
                element_id, known_targets, memory
            )
            score += feature_bonus
            details.append(f"feature={feature_bonus:.2f}")
            
            # 4) Critic feedback weights
            critic_weight = memory.get_element_weight(element_id)
            # Normalize critic weight (-1.5 to +1.0) to (-0.2 to +0.2) bonus/penalty
            normalized_weight = max(-0.2, min(0.2, critic_weight * 0.1))
            score += normalized_weight
            details.append(f"critic={normalized_weight:+.2f}")
            
            # 5) Element type bonus (navigation elements worth more)
            element_type = self._element_type_map.get(element_id, "unknown")
            type_bonus = 0.0
            if element_type in ("menu", "nav", "back", "drawer"):
                type_bonus = 0.15
            elif element_type in ("button", "link"):
                type_bonus = 0.05
            score += type_bonus
            details.append(f"type={element_type}")
            
            # 6) Repetition penalty: penalize heavily used elements
            repetition_penalty = -0.15 * min(element_visits / 5, 1.0)
            score += repetition_penalty
            details.append(f"repeat={repetition_penalty:+.2f}")
            
            # 7) Prefer elements that lead to new screens
            new_screen_bonus = 0.0
            if known_targets and any(t not in memory.screens for t in known_targets):
                new_screen_bonus = 0.5
            score += new_screen_bonus
            details.append(f"new_screen={new_screen_bonus:.2f}")
            
            scores.append((element_id, score, details))
        
        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # Log top 3 candidates
        for i, (eid, score, details) in enumerate(scores[:3]):
            logger.debug(
                "Candidate #%d: %s (score=%.3f) -- %s",
                i+1, eid[:30], score, " | ".join(details)
            )
        
        return [(eid, score) for eid, score, _ in scores]

    def _analyze_ui_patterns(
        self,
        page_source: str,
        current_sig: str,
    ) -> Dict[str, Dict[str, Any]]:
        """Phase 3: Analyse UI structure to classify container types.
        
        Returns dict of container_id → {type, confidence, reason}.
        
        Used to guide sampling decisions: product lists can sample fewer items,
        but navigation lists should be fully explored.
        """
        if current_sig in self._container_types:
            return self._container_types[current_sig]
        
        patterns = UIStructureAnalyzer.analyse_page(page_source)
        
        container_map = {}
        for pattern in patterns:
            container_id = pattern["container_id"]
            container_map[container_id] = {
                "type": pattern["type"],
                "confidence": pattern["confidence"],
                "reason": pattern["reason"],
            }
            logger.debug(
                "Phase3 UI pattern detected: %s (confidence=%.2f) -- %s",
                pattern["type"], pattern["confidence"], pattern["reason"]
            )
        
        # Cache for this screen
        self._container_types[current_sig] = container_map
        return container_map
    
    def get_container_classification(self, container_id: str) -> Optional[str]:
        """Get the cached classification for a container.
        
        Phase 2: Returns "PRODUCT_LIST", "NAVIGATION_LIST", "OPTION_LIST", or None.
        """
        return self._container_classifications.get(container_id)
    
    def _compute_feature_clusters(self, memory: SessionMemory):
        """Phase 5: Compute or refresh feature clusters.
        
        Recompute every N screens to keep up with discovery.
        """
        # Recompute every 5 new screens discovered
        if (
            self._feature_clusters is not None and
            len(memory.screens) - self._last_cluster_computation < 5
        ):
            return  # Use cached clusters
        
        self._feature_clusters = FeatureDetector.cluster_screens(memory)
        self._last_cluster_computation = len(memory.screens)
        logger.info(
            "Phase5: Computed %d feature clusters from %d screens",
            len(self._feature_clusters), len(memory.screens)
        )
    
    def _get_feature_cluster_bonus(
        self,
        element_id: str,
        known_targets: Set[str],
        memory: SessionMemory,
    ) -> float:
        """Phase 5: Get exploration bonus if element leads to underexplored feature cluster.
        
        Returns 0.0-0.3 bonus.
        """
        if not known_targets:
            return 0.0
        
        # Compute clusters if not cached
        if self._feature_clusters is None:
            self._compute_feature_clusters(memory)
        
        if not self._feature_clusters:
            return 0.0
        
        # Check if any target is in an underexplored cluster
        underexplored_bonuses = [
            FeatureDetector.get_feature_bias_score(target_sig, self._feature_clusters)
            for target_sig in known_targets
        ]
        
        if underexplored_bonuses:
            return max(underexplored_bonuses)  # Use best bonus
        
        return 0.0

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

        # Get graph intelligence: hub screens and coverage gaps
        graph_hint = ""
        if self._kb and hasattr(self._kb, "graph") and self._kb.graph.node_count > 1:
            graph = self._kb.graph
            gaps = graph.coverage_gaps()
            dead_ends = gaps.get("dead_ends", [])[:3]
            untested = gaps.get("untested_screens", [])[:3]
            low_out = gaps.get("low_outgoing", [])[:3]
            if dead_ends or untested or low_out:
                graph_hint = "\nGRAPH INTELLIGENCE (coverage gaps to prioritise):"
                if dead_ends:
                    graph_hint += f"\n  Dead-end screens (no outgoing transitions): {json.dumps(dead_ends)}"
                if untested:
                    graph_hint += f"\n  Untested screens (visited once, never tested): {json.dumps(untested)}"
                if low_out:
                    graph_hint += f"\n  Under-explored (few outgoing transitions): {json.dumps([s[:20] for s in low_out])}"
                graph_hint += "\nPrefer elements that might navigate TOWARD these screens!\n"

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
{graph_hint}
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
        """Use session memory AND the persistent ScreenGraph to click an
        element that leads to a less-visited or unvisited screen.

        Phase 4: Enhanced navigation that prioritises by:
        1) Reliability (nav_count / click_count from KB)
        2) Target underexploration (visit_count / avg_visits)
        3) Path length to unexcplored areas

        Strategy:
          1) Score all navigable elements visible on current screen
          2) Prefer reliable navigators leading to underexplored areas
          3) Use KB.graph multi-hop pathfinding to coverage gaps
        """
        sig = ui_context.get("state_signature", "")
        skip = exclude or set()

        # ---- Phase 4: Scored navigation ----
        # Get all known navigators on this screen (elements with nav_count > 0)
        if self._kb:
            known_navs = self._kb.get_known_navigators(sig)
            scored_navs = []
            
            for nav_info in known_navs:
                element_id = nav_info["element_id"]
                if element_id in skip or element_id not in all_ids:
                    continue
                
                reliability = nav_info["reliability"]
                known_targets = nav_info["known_targets"]
                
                # Score based on target underexploration
                target_score = 0.0
                best_target = None
                for target_sig in known_targets:
                    target_visits = memory.get_screen_visit_count(target_sig)
                    # Prefer very undervisited screens
                    if target_visits <= 1:
                        score_val = 1.0
                    elif target_visits <= 3:
                        score_val = 0.5
                    else:
                        score_val = 0.1
                    
                    if score_val > target_score:
                        target_score = score_val
                        best_target = target_sig
                
                # Combined score: reliability * target_underexploration
                combined_score = reliability * (target_score + 0.5)
                
                scored_navs.append({
                    'element_id': element_id,
                    'score': combined_score,
                    'reliability': reliability,
                    'target': best_target,
                    'known_targets': known_targets,
                })
            
            # Sort by combined score and try top candidates
            scored_navs.sort(key=lambda x: x['score'], reverse=True)
            for nav in scored_navs[:10]:  # Try top 10
                logger.debug(
                    "Phase4 nav candidate: %s (reliability=%.2f, combined_score=%.2f)",
                    nav['element_id'][:30], nav['reliability'], nav['score']
                )
                # Use KB's confirm_nav_element which ties it back to KB
                self._kb.confirm_nav_element(nav['element_id'], screen_sig=sig)
                logger.info(
                    "Phase4: Reliably navigating via '%s' to %s (score=%.3f)",
                    nav['element_id'][:30], nav['target'][:12] if nav['target'] else '?', nav['score']
                )
                return self._make_click_action(nav['element_id'], ui_context)

        # ---- Fallback 1: Session memory one-hop transitions ----
        transition_targets = memory.get_unvisited_transitions(sig)
        if transition_targets:
            for action_desc in transition_targets:
                if action_desc in skip:
                    continue
                if action_desc in all_ids:
                    logger.info(
                        "Memory graph: navigating to less-visited screen via '%s'",
                        action_desc,
                    )
                    if self._kb:
                        self._kb.confirm_nav_element(action_desc, screen_sig=sig)
                    return self._make_click_action(action_desc, ui_context)

        # ---- Fallback 2: Multi-hop ScreenGraph pathfinding to coverage gaps ----
        if self._kb and hasattr(self._kb, "graph"):
            graph = self._kb.graph
            gaps = graph.coverage_gaps()
            # Prioritise dead-ends (may have unexplored content) then untested
            targets = gaps.get("dead_ends", []) + gaps.get("untested_screens", [])
            for target_sig in targets:
                if target_sig == sig:
                    continue
                path = graph.shortest_action_path(sig, target_sig)
                if path and len(path) >= 1:
                    first_step = path[0]
                    first_element = first_step.get("element")
                    if first_element and first_element in all_ids and first_element not in skip:
                        logger.info(
                            "Graph pathfinding: %d-hop path to gap screen %s, first hop = '%s'",
                            len(path), target_sig[:16], first_element,
                        )
                        return self._make_click_action(first_element, ui_context)

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

        sig = ui_context.get("state_signature", "")

        # ---- Level 1: memory-graph nav excluding loop elements ----
        if counter <= 1:
            nav = self._navigate_via_memory(
                ui_context, memory, all_ids, exclude=loop_elements,
            )
            if nav:
                return nav
            # Try any element we've *previously learned* leads elsewhere
            known_nav = self._find_known_navigator(sig, acc_ids, loop_elements)
            if known_nav:
                logger.info("Breaking loop via learned navigator: '%s'", known_nav)
                return self._make_click_action(known_nav, ui_context)

        # ---- Level 2: click a known navigator (broaden to all IDs) ----
        if counter <= 2:
            known_nav = self._find_known_navigator(sig, all_ids, loop_elements)
            if known_nav:
                logger.info("Breaking loop via learned navigator (L2): %s", known_nav)
                return self._make_click_action(known_nav, ui_context)
            # No knowledge yet -- click something we've never tried at all
            never_tried = self._kb.get_untried_elements(sig, list(all_ids)) if self._kb else []
            never_tried = [e for e in never_tried if e not in loop_elements]
            if never_tried:
                chosen = never_tried[0]
                logger.info("Breaking loop -- trying never-clicked element: %s", chosen)
                return self._make_click_action(chosen, ui_context)

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
        self._screen_step_count.clear()
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

        # If we've been stuck even longer, use learned navigators to escape
        if self._consecutive_escapes > 6:
            sig = ui_context.get("state_signature", "")
            acc_ids = set(ui_context.get("accessibility_ids", []))
            known_nav = self._find_known_navigator(sig, acc_ids)
            if known_nav:
                self._consecutive_escapes = 0
                return self._make_click_action(known_nav, ui_context)
            # No learned navigators -- fall through to normal escape below

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

        Navigation elements are NOT hardcoded -- they are:
        1. Loaded from the KnowledgeBase (learned from previous runs)
        2. Classified semantically by the LLM for any new/unknown elements
        3. Saved back to KB so future runs benefit without re-classification
        """
        sig = ui_context.get("state_signature", "")
        if not sig or sig in self._screen_plans:
            return  # already planned

        acc_ids = ui_context.get("accessibility_ids", [])
        res_ids = ui_context.get("resource_ids", [])
        texts = ui_context.get("clickable_texts", [])
        all_ids = list(dict.fromkeys(acc_ids + res_ids + texts))  # preserve order, dedupe

        # Get learned nav element IDs from KB (cross-run knowledge)
        known_nav_ids = self._kb.get_nav_keywords() if self._kb else set()

        # Classify any unknown elements semantically (once per screen)
        if sig not in self._nav_classified_screens:
            self._classify_nav_elements(sig, all_ids, known_nav_ids)

        # Re-fetch after classification (new entries may have been added)
        known_nav_ids = self._kb.get_nav_keywords() if self._kb else set()
        if not self._kb:
            known_nav_ids = set()

        # Incorporate Planner directive focus/avoid keywords
        focus_kw = set()
        avoid_kw = set()
        if self._directive:
            focus_kw = {kw.lower() for kw in getattr(self._directive, "focus_elements", [])}
            avoid_kw = {kw.lower() for kw in getattr(self._directive, "avoid_elements", [])}

        nav_elements = []
        focus_elements = []  # Directive-prioritised
        action_elements = []
        other_elements = []

        for eid in all_ids:
            if eid in self._tried_elements:
                continue
            eid_lower = eid.lower()
            # Skip directive-avoided elements
            if avoid_kw and any(kw in eid_lower for kw in avoid_kw):
                continue
            # Directive-focused elements get top priority
            if focus_kw and any(kw in eid_lower for kw in focus_kw):
                focus_elements.append(eid)
            elif eid in known_nav_ids or eid_lower in known_nav_ids:
                nav_elements.append(eid)
            elif any(kw in eid_lower for kw in ("button", "add", "remove", "sort", "filter", "submit", "save")):
                action_elements.append(eid)
            else:
                other_elements.append(eid)

        # Build prioritised plan: directive-focus > nav > actions > others
        # Within each group, sort by Critic weight (higher = more promising)
        def _weight_sort(items):
            return sorted(items, key=lambda eid: memory.get_element_weight(eid), reverse=True)

        plan = _weight_sort(focus_elements) + _weight_sort(nav_elements) + _weight_sort(action_elements) + _weight_sort(other_elements)
        self._screen_plans[sig] = plan
        self._screen_plan_index[sig] = 0

        if plan:
            logger.info(
                "New screen plan [%s]: %d elements (focus=%d, nav=%d, action=%d, other=%d)",
                sig[:12], len(plan), len(focus_elements), len(nav_elements),
                len(action_elements), len(other_elements),
            )

    def _classify_nav_elements(
        self,
        screen_sig: str,
        all_ids: List[str],
        already_known: Set[str],
    ):
        """Ask the LLM to semantically classify which elements are
        navigation vs. action vs. content -- then store the results in KB.

        Only sends UNKNOWN elements to the LLM (ones not already in KB).
        This means the first run pays the classification cost, but all
        subsequent runs get instant lookups from KB.
        """
        self._nav_classified_screens.add(screen_sig)

        # Filter to only unknown elements (not in KB yet)
        unknown = [eid for eid in all_ids if eid not in already_known and eid.lower() not in already_known]
        if not unknown or len(unknown) < 2:
            return  # nothing to classify

        # Cap at 40 elements to keep prompt small
        to_classify = unknown[:40]

        prompt = f"""Classify each UI element into one of these categories:
- "nav": navigation elements that lead to OTHER screens (menus, tabs, links, drawer items, back buttons, screen titles that are clickable)
- "action": elements that perform an action on the CURRENT screen (buttons, toggles, sort, filter, add/remove, submit)
- "content": non-interactive or decorative elements (labels, images, text)

Elements to classify:
{json.dumps(to_classify)}

Return ONLY a JSON array of objects:
[{{"id": "<element id>", "role": "nav" | "action" | "content"}}]

Be thorough -- anything that could navigate to a different screen is "nav"."""

        try:
            raw = self.ask_text(prompt)
            parsed = self.parse_json(raw)
            if isinstance(parsed, list) and self._kb:
                nav_batch = []
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    eid = item.get("id", "")
                    role = item.get("role", "content")
                    if role == "nav" and eid:
                        nav_batch.append({
                            "element_id": eid,
                            "role": "nav",
                            "confidence": 0.8,
                        })
                if nav_batch:
                    self._kb.learn_nav_elements_batch(nav_batch, screen_sig=screen_sig)
                    logger.info(
                        "Classified %d/%d elements as nav on screen %s (saved to KB)",
                        len(nav_batch), len(to_classify), screen_sig[:12],
                    )
        except Exception as e:
            logger.debug("Nav classification failed: %s", e)

    # ---- Discovery queue (defer interesting finds) ----

    def queue_discovery(self, discovery: Dict[str, Any]):
        """Queue an interesting element/screen for later exploration.

        Called when the explorer notices something worth investigating
        but doesn't want to break the current task flow.

        Each discovery dict should have:
        - ``type``: "element" | "screen" | "feature"
        - ``id``: element ID or screen signature
        - ``reason``: why it's interesting
        - ``priority``: "high" | "medium" | "low"
        """
        # Deduplicate by (type, id)
        key = (discovery.get("type"), discovery.get("id"))
        if any((d.get("type"), d.get("id")) == key for d in self._discovery_queue):
            return
        self._discovery_queue.append(discovery)
        logger.debug("Queued discovery: %s %s -- %s",
                      discovery.get("type"), discovery.get("id", "")[:20],
                      discovery.get("reason", "")[:40])

    def drain_discovery_queue(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Pop up to ``limit`` discoveries from the queue (highest priority first).

        The orchestrator calls this between tasks to feed new
        discoveries back into the plan without interrupting the current
        task.
        """
        if not self._discovery_queue:
            return []
        prio_order = {"high": 0, "medium": 1, "low": 2}
        self._discovery_queue.sort(key=lambda d: prio_order.get(d.get("priority", "low"), 2))
        batch = self._discovery_queue[:limit]
        self._discovery_queue = self._discovery_queue[limit:]
        return batch

    def has_pending_discoveries(self) -> bool:
        return bool(self._discovery_queue)

    def _queue_unseen_elements(
        self,
        ui_context: Dict[str, Any],
        memory: SessionMemory,
    ):
        """Scan the current screen for elements that look interesting
        but are NOT part of the current task -- queue them for later.

        Called during exploration when we see something new while
        working on a specific task.
        """
        acc_ids = ui_context.get("accessibility_ids", [])
        known_nav_ids = self._kb.get_nav_keywords() if self._kb else set()

        for eid in acc_ids:
            if eid in self._tried_elements:
                continue
            eid_lower = eid.lower()
            # Queue elements that look like they lead to unexplored features
            if eid in known_nav_ids or eid_lower in known_nav_ids:
                # Check if the target screen is well-explored
                sig = ui_context.get("state_signature", "")
                transitions = memory.screens.get(sig)
                if transitions and hasattr(transitions, "transitions"):
                    target = transitions.transitions.get(eid)
                    if target and memory.get_screen_visit_count(target) > 3:
                        continue  # already well-visited
                self.queue_discovery({
                    "type": "element",
                    "id": eid,
                    "screen_sig": sig,
                    "reason": f"Known nav element not yet explored: {eid}",
                    "priority": "medium",
                })

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

    # ---- Learned behavior helpers (replaces hardcoded heuristics) ----

    def observe_action_result(
        self,
        action: Dict[str, Any],
        sig_before: str,
        sig_after: str,
        screen_source: str = "",
        screen_description: str = "",
    ):
        """Called after every action to learn what the element does.

        Compares the screen signature before and after the interaction
        and records the outcome in the KnowledgeBase so that on the
        *next* run (or even later in *this* run) the agent already knows
        what every button does -- no hardcoded patterns needed.
        
        NEW: Also analyzes containers in the target screen for Phase 2 classification.
        """
        if not self._kb:
            return
        element_id = action.get("locator_value")
        if not element_id or not sig_before:
            return

        action_type = action.get("action", "click")
        if sig_before != sig_after and sig_after:
            behavior = "navigates"
            # Also register in the nav_elements table for
            # backward-compat with get_nav_keywords()
            self._kb.confirm_nav_element(element_id, screen_sig=sig_before)
            # Phase 1: Record transition for action scoring  
            self.record_transition(sig_before, element_id, sig_after)
            
            # NEW: Analyze containers in target screen if available
            if screen_source:
                self.analyze_new_screen_containers(
                    sig_after, screen_source, screen_description
                )
            
            logger.debug(
                "Learned: '%s' navigates  %s -> %s",
                element_id, sig_before[:12], sig_after[:12],
            )
        else:
            behavior = "stays"

        self._kb.record_element_behavior(
            element_id,
            sig_before,
            behavior,
            target_screen_sig=sig_after if behavior == "navigates" else "",
            action_type=action_type,
        )

    def _find_known_navigator(
        self,
        screen_sig: str,
        visible_ids: set,
        exclude: Optional[Set[str]] = None,
    ) -> Optional[str]:
        """Find a visible element that we've PREVIOUSLY LEARNED navigates
        to a different screen.  Returns the best candidate or *None*.

        This replaces all hardcoded menu/drawer heuristics -- it works
        for ANY app because it's powered by observed behavior stored in
        the KnowledgeBase.
        """
        if not self._kb:
            return None
        skip = exclude or set()
        # 1) Screen-specific knowledge (most reliable)
        navigators = self._kb.get_known_navigators(screen_sig)
        for nav in navigators:
            eid = nav["element_id"]
            if eid in visible_ids and eid not in skip:
                return eid
        # 2) Cross-screen knowledge (element navigated on another screen)
        global_navs = self._kb.get_all_known_navigators()
        for eid in visible_ids:
            if eid in global_navs and eid not in skip:
                return eid
        return None

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
