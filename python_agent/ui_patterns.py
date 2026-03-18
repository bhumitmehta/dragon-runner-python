"""UI Pattern Recognition -- detect semantic meaning from UI structure.

Phase 3: Pre-interaction heuristics that look at UI structure to make educated
guesses about container semantics BEFORE behavioral sampling:

- Product catalogs: Image + title + price repeat
- Navigation menus: Icon + label with distinct links
- Option lists: RadioButton/CheckBox groups, Spinners
- Forms: Input fields with labels

No LLM needed -- pure structural pattern matching.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Set, Tuple

from .logging_config import get_logger

logger = get_logger("ui_patterns")


class UIPattern:
    """Pattern definition with name and structure rules."""
    
    def __init__(self, name: str, confidence: float, reason: str):
        self.name = name
        self.confidence = confidence  # 0.0 - 1.0
        self.reason = reason


class UIStructureAnalyzer:
    """Analyse XML page source to detect UI patterns."""
    
    # ── Structural patterns ──────────────────────────────────────────
    
    PRODUCT_INDICATORS = [
        # (required_tags, optional_tags, confidence_boost)
        (["ImageView", "TextView", "TextView"], ["priceView"], 0.8),  # image + 2x text
        (["Image", "title", "price"], [], 0.9),  # explicit product attrs
        (["img", "price", "title"], [], 0.8),
    ]
    
    NAVIGATION_INDICATORS = [
        # Menu: repeated icon + label items
        (["ImageView", "TextView"], [], 0.7),  # repeated icon+label
        (["icon", "label"], [], 0.8),          # explicit nav attrs
        (["DrawerLayout", "NavigationView"], [], 0.95),  # explicit android nav
    ]
    
    OPTION_INDICATORS = [
        # Options: RadioGroup, CheckBox groups, Spinners
        (["RadioButton"], [], 0.9),
        (["CheckBox"], [], 0.9),
        (["Spinner"], [], 0.85),
        (["RadioGroup"], [], 0.95),
    ]
    
    FORM_INDICATORS = [
        # Multiple input fields in sequence
        (["EditText", "EditText"], [], 0.8),
        (["input", "input"], [], 0.8),
        (["TextInputLayout"], [], 0.7),
    ]

    @staticmethod
    def extract_container_hierarchy(page_source: str) -> List[Tuple[ET.Element, int]]:
        """Extract container elements (view groups) with nesting depth.
        
        Returns list of (element, depth) tuples.
        """
        try:
            root = ET.fromstring(page_source)
        except Exception:
            return []
        
        containers = []
        
        def traverse(el: ET.Element, depth: int):
            # Consider elements with children as potential containers
            if len(el) > 1:  # has multiple children
                containers.append((el, depth))
            for child in el:
                traverse(child, depth + 1)
        
        traverse(root, 0)
        return containers
    
    @staticmethod
    def get_repeated_child_pattern(container: ET.Element) -> Optional[List[str]]:
        """If children follow a repeated structure, return the tag pattern.
        
        Example: container with 5 children, each containing [Image, TextView, TextView]
        would return ["ImageView", "TextView", "TextView"] with 5x repetition.
        """
        children = list(container)
        if len(children) < 2:
            return None
        
        # Get tag sequence of first child
        first_pattern = []
        first_child = children[0]
        for grandchild in first_child:
            first_pattern.append(grandchild.tag)
        
        if not first_pattern:
            return None
        
        # Check if other children follow same pattern
        matches = 1
        for child in children[1:5]:  # Check up to 5 children
            child_pattern = [gc.tag for gc in child]
            if child_pattern == first_pattern:
                matches += 1
        
        # If at least 2 children match, it's a pattern
        if matches >= 2:
            return first_pattern
        
        return None
    
    @staticmethod
    def match_pattern_list(tags: List[str], pattern_defs: List[Tuple]) -> Optional[float]:
        """Check if tag list matches any pattern definition.
        
        Returns confidence (0.0-1.0) or None if no match.
        """
        for required_tags, optional_tags, base_confidence in pattern_defs:
            # Check required tags are present
            remaining_tags = set(tags)
            
            for req_tag in required_tags:
                # Check for exact match or substring match
                found = False
                for tag in remaining_tags.copy():
                    if req_tag.lower() in tag.lower():
                        remaining_tags.discard(tag)
                        found = True
                        break
                
                if not found:
                    break
            else:
                # All required tags found
                # Check for bonus optional tags
                bonus = 0.0
                for opt_tag in optional_tags:
                    for tag in remaining_tags:
                        if opt_tag.lower() in tag.lower():
                            bonus += 0.1
                            break
                
                return min(1.0, base_confidence + bonus)
        
        return None
    
    @staticmethod
    def analyse_container(container: ET.Element, page_source_full: str = "") -> Optional[UIPattern]:
        """Analyse a single container to determine its semantic type.
        
        Returns UIPattern with detected type or None.
        """
        repeated_pattern = UIStructureAnalyzer.get_repeated_child_pattern(container)
        if not repeated_pattern:
            return None
        
        # Try to match against known patterns
        confidence = None
        pattern_type = None
        
        # Check product pattern
        prod_conf = UIStructureAnalyzer.match_pattern_list(
            repeated_pattern, UIStructureAnalyzer.PRODUCT_INDICATORS
        )
        if prod_conf and prod_conf > (confidence or 0):
            confidence = prod_conf
            pattern_type = "PRODUCT_LIST"
        
        # Check navigation pattern
        nav_conf = UIStructureAnalyzer.match_pattern_list(
            repeated_pattern, UIStructureAnalyzer.NAVIGATION_INDICATORS
        )
        if nav_conf and nav_conf > (confidence or 0):
            confidence = nav_conf
            pattern_type = "NAVIGATION_LIST"
        
        # Check option pattern
        opt_conf = UIStructureAnalyzer.match_pattern_list(
            repeated_pattern, UIStructureAnalyzer.OPTION_INDICATORS
        )
        if opt_conf and opt_conf > (confidence or 0):
            confidence = opt_conf
            pattern_type = "OPTION_LIST"
        
        # Check form pattern
        form_conf = UIStructureAnalyzer.match_pattern_list(
            repeated_pattern, UIStructureAnalyzer.FORM_INDICATORS
        )
        if form_conf and form_conf > (confidence or 0):
            confidence = form_conf
            pattern_type = "FORM"
        
        if pattern_type and confidence and confidence >= 0.5:
            reason = f"Structure: {' → '.join(repeated_pattern[:3])}"
            return UIPattern(pattern_type, confidence, reason)
        
        return None
    
    @staticmethod
    def analyse_page(page_source: str) -> List[Dict[str, Any]]:
        """Analyse entire page and return detected UI patterns.
        
        Returns list of {type, container_id, confidence, reason} dicts.
        """
        patterns = []
        containers = UIStructureAnalyzer.extract_container_hierarchy(page_source)
        
        for container, depth in containers:
            if depth > 6:  # Skip deeply nested (likely internal structure)
                continue
            
            pattern = UIStructureAnalyzer.analyse_container(container, page_source)
            if pattern:
                container_id = container.attrib.get("resource-id") or container.attrib.get("accessibility-id") or f"container_{depth}_{len(patterns)}"
                patterns.append({
                    "type": pattern.name,
                    "container_id": container_id,
                    "confidence": pattern.confidence,
                    "reason": pattern.reason,
                })
        
        return patterns


def should_sample_list_items(detected_type: str, item_count: int) -> Tuple[bool, int]:
    """Decide if we should sample all items in a list or just a few.
    
    Returns (should_sample_all, sample_count).
    
    Based on pattern type:
    - PRODUCT_LIST: Sample 2-3 (all similar, waste to test all)
    - NAVIGATION_LIST: Sample all (each item is distinct feature)
    - OPTION_LIST: Test all (state effects matter)
    - FORM: N/A (not applicable for forms)
    """
    if detected_type == "PRODUCT_LIST":
        # Similar items -- sample representative subset
        return (False, min(3, item_count))
    
    elif detected_type == "NAVIGATION_LIST":
        # Distinct destinations -- test all
        return (True, item_count)
    
    elif detected_type == "OPTION_LIST":
        # State changes -- test all
        return (True, item_count)
    
    else:
        # Unknown -- conservative: sample all
        return (True, item_count)


if __name__ == "__main__":
    # Test
    test_xml = """<hierarchy rotation="0">
    <node text="" width="1440" height="2960">
        <node text="" resource-id="com.example:id/list_container">
            <node text="Product 1" class="android.widget.LinearLayout">
                <node text="" class="android.widget.ImageView" />
                <node text="Product 1" class="android.widget.TextView" />
                <node text="$19.99" class="android.widget.TextView" />
            </node>
            <node text="Product 2" class="android.widget.LinearLayout">
                <node text="" class="android.widget.ImageView" />
                <node text="Product 2" class="android.widget.TextView" />
                <node text="$29.99" class="android.widget.TextView" />
            </node>
        </node>
    </node>
</hierarchy>"""
    
    patterns = UIStructureAnalyzer.analyse_page(test_xml)
    print(f"Detected {len(patterns)} patterns:")
    for p in patterns:
        print(f"  - {p['type']} (confidence={p['confidence']:.2f}): {p['reason']}")
