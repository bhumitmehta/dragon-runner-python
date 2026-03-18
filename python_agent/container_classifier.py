"""
Container Classification System

Determines semantic type of UI containers (content list, navigation menu, option list)
using deterministic heuristics + LLM classification for ambiguous cases.

Pipeline:
  1. Extract container structure from UI tree
  2. Apply deterministic heuristics (text signals, structure patterns)
  3. Gather navigation evidence (if available)
  4. If confidence < threshold → call LLM for classification
  5. Store classification in KnowledgeBase for future runs
"""

import json
import logging
from typing import Optional, Dict, List, Set, Tuple
from dataclasses import dataclass
from enum import Enum
import re

logger = logging.getLogger(__name__)


class ContainerType(Enum):
    """Enum for container semantic types."""
    CONTENT_LIST = "CONTENT_LIST"
    NAVIGATION_LIST = "NAVIGATION_LIST"
    OPTION_LIST = "OPTION_LIST"
    UNKNOWN = "UNKNOWN"


@dataclass
class ContainerClassification:
    """Result of container classification."""
    container_type: ContainerType
    confidence: float  # 0.0-1.0
    reasoning: str
    strategy: str
    source: str  # "heuristic" or "llm"


class HeuristicClassifier:
    """Deterministic classification based on structure and text signals."""

    # Keywords indicating navigation list
    NAV_KEYWORDS = {
        "settings", "profile", "account", "home", "dashboard",
        "menu", "options", "help", "about", "logout", "login",
        "history", "favorites", "bookmarks", "search", "browse",
        "categories", "sections", "more", "explore"
    }

    # Keywords indicating content list
    CONTENT_KEYWORDS = {
        "price", "rating", "review", "add to cart", "buy", "purchase",
        "product", "item", "post", "article", "search result", "feed",
        "comment", "message", "notification", "like", "share", "stars",
        "sale", "discount", "offer", "stock", "availability"
    }

    # Keywords indicating option list
    OPTION_KEYWORDS = {
        "sort", "filter", "ascending", "descending", "asc", "desc",
        "display", "view", "mode", "theme", "language", "yes", "no",
        "on", "off", "enable", "disable", "show", "hide", "select"
    }

    # Element types indicating option list
    OPTION_ELEMENT_TYPES = {
        "radio_button", "checkbox", "switch", "toggle",
        "radio group", "segment control"
    }

    # Element types indicating navigation
    NAV_ELEMENT_TYPES = {
        "button", "text_button", "menu_item", "tab", "toolbar"
    }

    @staticmethod
    def extract_text_labels(container_xml: str) -> List[str]:
        """Extract text content from container."""
        labels = []
        # Simple regex to find text content
        text_pattern = r'<Text[^>]*>([^<]+)</Text>|text="([^"]*)"'
        matches = re.findall(text_pattern, container_xml)
        for match in matches:
            text = match[0] or match[1]
            if text.strip():
                labels.append(text.strip().lower())
        return labels

    @staticmethod
    def score_keyword_match(texts: List[str], keywords: Set[str]) -> float:
        """Score how well texts match keyword set."""
        if not texts:
            return 0.0
        matches = sum(1 for text in texts if any(kw in text for kw in keywords))
        return matches / len(texts)

    @staticmethod
    def detect_option_elements(container_xml: str) -> bool:
        """Detect presence of option-type elements (radio, checkbox, switch)."""
        option_types = ["RadioButton", "CheckBox", "Switch", "RadioGroup", "SegmentedControl"]
        return any(opt_type in container_xml for opt_type in option_types)

    @staticmethod
    def detect_repeating_structure(container_xml: str, min_repeats: int = 3) -> Tuple[bool, str]:
        """
        Detect if container has repeating child structure (indicator of list).
        Returns (has_repeating_structure, structure_description)
        """
        # Find child elements
        child_pattern = r'<(\w+)[^>]*>'
        child_types = re.findall(child_pattern, container_xml)

        if not child_types:
            return False, ""

        # Check if top-level element repeats
        from collections import Counter
        counts = Counter(child_types)
        most_common = counts.most_common(1)[0]

        if most_common[1] >= min_repeats:
            structure = f"Repeating {most_common[0]} ({most_common[1]} times)"
            return True, structure

        return False, ""

    @staticmethod
    def classify_heuristic(
        container_xml: str,
        element_texts: List[str]
    ) -> Tuple[ContainerType, float, str]:
        """
        Apply deterministic heuristics to classify container.

        Returns:
            (container_type, confidence, reasoning)
        """
        # Extract text labels if not provided
        if not element_texts:
            element_texts = HeuristicClassifier.extract_text_labels(container_xml)

        has_repeating, structure_desc = HeuristicClassifier.detect_repeating_structure(container_xml)

        # Check for option list indicators (highest priority - most specific)
        if HeuristicClassifier.detect_option_elements(container_xml):
            confidence = 0.95
            reasoning = f"Contains option elements (radio, checkbox, switch). {structure_desc}"
            return ContainerType.OPTION_LIST, confidence, reasoning

        # Score keyword matches
        nav_score = HeuristicClassifier.score_keyword_match(element_texts, HeuristicClassifier.NAV_KEYWORDS)
        content_score = HeuristicClassifier.score_keyword_match(element_texts, HeuristicClassifier.CONTENT_KEYWORDS)
        option_score = HeuristicClassifier.score_keyword_match(element_texts, HeuristicClassifier.OPTION_KEYWORDS)

        # Determine classification by highest score
        max_score = max(nav_score, content_score, option_score)

        if max_score < 0.2:
            # Low confidence - need LLM
            confidence = 0.3
            reasoning = f"Weak keyword signals. {structure_desc}. Nav={nav_score:.2f}, Content={content_score:.2f}, Option={option_score:.2f}"
            return ContainerType.UNKNOWN, confidence, reasoning

        if content_score == max_score and content_score > 0.3:
            confidence = min(0.7 + content_score * 0.2, 0.85)
            reasoning = f"Content list signals detected (price, rating, product keywords). {structure_desc}"
            return ContainerType.CONTENT_LIST, confidence, reasoning

        if nav_score == max_score and nav_score > 0.25:
            confidence = min(0.7 + nav_score * 0.2, 0.85)
            reasoning = f"Navigation list signals detected (settings, profile, menu keywords). {structure_desc}"
            return ContainerType.NAVIGATION_LIST, confidence, reasoning

        if option_score == max_score:
            confidence = min(0.65 + option_score * 0.2, 0.80)
            reasoning = f"Option list signals detected (sort, filter, toggle keywords). {structure_desc}"
            return ContainerType.OPTION_LIST, confidence, reasoning

        # Fallback
        confidence = 0.4
        reasoning = f"Ambiguous signals. {structure_desc}"
        return ContainerType.UNKNOWN, confidence, reasoning


class BehavioralClassifier:
    """Classification based on observed navigation behavior."""

    @staticmethod
    def analyze_navigation_results(
        navigation_results: List[Dict]
    ) -> Tuple[ContainerType, float, str]:
        """
        Analyze results of clicking items in a container.

        Navigation results format:
        [
            {"element_id": "item_1", "target_screen_sig": "abc123", "target_screen_desc": "..."},
            {"element_id": "item_2", "target_screen_sig": "def456", "target_screen_desc": "..."},
            ...
        ]

        Returns:
            (container_type, confidence, reasoning)
        """
        if not navigation_results or len(navigation_results) < 2:
            return ContainerType.UNKNOWN, 0.0, "Insufficient navigation data"

        # Extract unique target screens
        unique_targets = set(r.get("target_screen_sig") for r in navigation_results)
        screen_descriptions = [r.get("target_screen_desc", "") for r in navigation_results]

        num_items = len(navigation_results)
        num_unique_targets = len(unique_targets)

        # Pattern 1: All items lead to same screen (possibly different data)
        if num_unique_targets == 1:
            # Check if screen description is similar (indicates content list template)
            first_desc = screen_descriptions[0]
            if first_desc:
                # Simple similarity check - if descriptions mention same keywords
                desc_similarity = sum(
                    1 for desc in screen_descriptions
                    if desc and BehavioralClassifier._text_similarity(desc, first_desc) > 0.7
                ) / num_items
                if desc_similarity > 0.8:
                    confidence = 0.9
                    reasoning = f"All {num_items} items lead to same screen with similar structure. Content list."
                    return ContainerType.CONTENT_LIST, confidence, reasoning

        # Pattern 2: Each item leads to different screen (navigation)
        if num_unique_targets >= num_items * 0.8:  # 80%+ uniqueness = navigation
            confidence = 0.85
            reasoning = f"Clicked {num_items} items, got {num_unique_targets} unique screens. Navigation list."
            return ContainerType.NAVIGATION_LIST, confidence, reasoning

        # Pattern 3: Items lead to same screen but UI state changes
        # (This requires deeper inspection - for now, classify as option list)
        if num_unique_targets == 1:
            confidence = 0.7
            reasoning = f"All items stay on same screen. Likely option list (state changes not verified in this analysis)."
            return ContainerType.OPTION_LIST, confidence, reasoning

        # Pattern 4: Mixed - some unique, some not (unknown)
        confidence = 0.5
        reasoning = f"Mixed behavior: {num_items} items → {num_unique_targets} unique screens. Ambiguous."
        return ContainerType.UNKNOWN, confidence, reasoning

    @staticmethod
    def _text_similarity(text1: str, text2: str) -> float:
        """Simple Jaccard similarity between word sets."""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        return intersection / union if union > 0 else 0.0


class ContainerClassifier:
    """Main classifier orchestrating heuristic + LLM + behavioral analysis."""

    CONFIDENCE_THRESHOLD_FOR_LLM = 0.60  # Below this, call LLM if available

    def __init__(self, vlm=None, knowledge_base=None):
        """
        Initialize classifier.

        Args:
            vlm: VLM instance for LLM-based classification (optional)
            knowledge_base: KnowledgeBase instance for storing/retrieving classifications
        """
        self.vlm = vlm
        self.knowledge_base = knowledge_base

    def classify(
        self,
        container_sig: str,
        container_xml: str,
        element_texts: List[str],
        navigation_results: Optional[List[Dict]] = None,
    ) -> ContainerClassification:
        """
        Classify a container using multi-stage pipeline.

        Args:
            container_sig: Unique identifier for this container
            container_xml: XML structure of container
            element_texts: Text labels of items in container
            navigation_results: (Optional) observed navigation behavior

        Returns:
            ContainerClassification with type, confidence, reasoning, strategy
        """
        # Stage 1: Check KB for cached classification
        if self.knowledge_base:
            cached = self._get_cached_classification(container_sig)
            if cached:
                logger.info(f"Container {container_sig} classified from cache: {cached.container_type.value}")
                return cached

        # Stage 2: Apply heuristic classifier
        heur_type, heur_conf, heur_reasoning = HeuristicClassifier.classify_heuristic(
            container_xml, element_texts
        )

        # Stage 3: Use behavioral data if available
        if navigation_results:
            behav_type, behav_conf, behav_reasoning = BehavioralClassifier.analyze_navigation_results(
                navigation_results
            )
            # If behavioral data contradicts heuristic, trust behavioral
            if behav_conf > heur_conf:
                heur_type = behav_type
                heur_conf = behav_conf
                heur_reasoning = behav_reasoning

        # Stage 4: If still uncertain, call LLM
        if heur_conf < self.CONFIDENCE_THRESHOLD_FOR_LLM and self.vlm:
            logger.info(f"Container {container_sig} confidence {heur_conf:.2f} below threshold, calling LLM")
            llm_result = self._classify_with_llm(
                container_xml, element_texts, navigation_results, heur_reasoning
            )
            if llm_result:
                result = llm_result
                result.source = "llm"
            else:
                result = self._make_classification(
                    heur_type, heur_conf, heur_reasoning, "heuristic"
                )
        else:
            result = self._make_classification(
                heur_type, heur_conf, heur_reasoning, "heuristic"
            )

        # Stage 5: Cache result in KB
        if self.knowledge_base and result.confidence > 0.5:
            self._cache_classification(container_sig, result)

        logger.info(
            f"Container {container_sig} classified as {result.container_type.value} "
            f"(conf={result.confidence:.2f}, src={result.source})"
        )
        return result

    def _get_cached_classification(self, container_sig: str) -> Optional[ContainerClassification]:
        """Retrieve cached classification from KB."""
        try:
            from tinydb import Query
            Container = Query()
            result = self.knowledge_base.get_table("container_classifications").search(
                Container.sig == container_sig
            )
            if result:
                doc = result[0]
                return ContainerClassification(
                    container_type=ContainerType[doc["type"]],
                    confidence=doc.get("confidence", 0.8),
                    reasoning=doc.get("reasoning", ""),
                    strategy=doc.get("strategy", ""),
                    source="cache"
                )
        except Exception as e:
            logger.debug(f"Cache lookup failed: {e}")
        return None

    def _cache_classification(self, container_sig: str, result: ContainerClassification):
        """Store classification in KB."""
        try:
            from tinydb import Query
            table = self.knowledge_base.get_table("container_classifications")
            Container = Query()
            # Check if already cached
            existing = table.search(Container.sig == container_sig)
            if existing:
                table.update({
                    "type": result.container_type.value,
                    "confidence": result.confidence,
                    "reasoning": result.reasoning,
                    "strategy": result.strategy,
                }, Container.sig == container_sig)
            else:
                table.insert({
                    "sig": container_sig,
                    "type": result.container_type.value,
                    "confidence": result.confidence,
                    "reasoning": result.reasoning,
                    "strategy": result.strategy,
                })
            logger.debug(f"Classification cached for {container_sig}")
        except Exception as e:
            logger.debug(f"Cache write failed: {e}")

    def _classify_with_llm(
        self,
        container_xml: str,
        element_texts: List[str],
        navigation_results: Optional[List[Dict]],
        heuristic_reasoning: str
    ) -> Optional[ContainerClassification]:
        """Call LLM for semantic classification."""
        if not self.vlm:
            return None

        # Build prompt
        prompt = self._build_classification_prompt(
            container_xml, element_texts, navigation_results, heuristic_reasoning
        )

        try:
            response = self.vlm.query(prompt)
            classification = self._parse_llm_response(response)
            if classification:
                return classification
        except Exception as e:
            logger.warning(f"LLM classification failed: {e}")

        return None

    def _build_classification_prompt(
        self,
        container_xml: str,
        element_texts: List[str],
        navigation_results: Optional[List[Dict]],
        heuristic_reasoning: str
    ) -> str:
        """Build the LLM prompt for container classification."""
        nav_results_str = ""
        if navigation_results:
            nav_results_str = "Observed navigation results:\n"
            for i, result in enumerate(navigation_results[:5]):  # Limit to 5 examples
                nav_results_str += f"  {i+1}. Item '{result.get('element_id', '?')}' → Screen: {result.get('target_screen_desc', 'Unknown')}\n"

        prompt = f"""You are a mobile UI testing analyst.

Your task is to determine the semantic type of a UI container so that an automated testing agent can explore it efficiently.

A container may represent:

CONTENT_LIST: Repeating items with similar content (products, posts, search results). Clicking items usually leads to screens with similar structure. Strategy: Sample only 2-3 items, verify common actions, avoid exploring every item.

NAVIGATION_LIST: Menu entries that navigate to different features. Clicking items leads to different screens/modules. Strategy: Visit each item at least once, record screen transitions, map navigation graph.

OPTION_LIST: UI elements that modify current screen state (sort, filters, radio buttons). Clicking items doesn't navigate but changes UI state. Strategy: Toggle each option, verify state changes, stay on same screen.

UNKNOWN: Cannot classify confidently.

---ANALYSIS CONTEXT---

Heuristic pre-analysis found: {heuristic_reasoning}

Container structure (truncated):
{container_xml[:500]}

Element texts in container:
{', '.join(element_texts[:20])}

{nav_results_str}

---YOUR TASK---

Classify this container into one of: CONTENT_LIST, NAVIGATION_LIST, OPTION_LIST, or UNKNOWN.

Return ONLY valid JSON (no markdown, no extra text):
{{
  "container_type": "CONTENT_LIST | NAVIGATION_LIST | OPTION_LIST | UNKNOWN",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation",
  "strategy": "exploration strategy"
}}
"""
        return prompt

    def _parse_llm_response(self, response: str) -> Optional[ContainerClassification]:
        """Parse LLM JSON response."""
        try:
            # Extract JSON from response (may have extra text)
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if not json_match:
                return None

            data = json.loads(json_match.group(0))

            container_type = ContainerType[data.get("container_type", "UNKNOWN")]
            confidence = float(data.get("confidence", 0.5))
            reasoning = str(data.get("reasoning", ""))
            strategy = str(data.get("strategy", ""))

            return ContainerClassification(
                container_type=container_type,
                confidence=confidence,
                reasoning=reasoning,
                strategy=strategy,
                source="llm"
            )
        except Exception as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return None

    def _make_classification(
        self,
        container_type: ContainerType,
        confidence: float,
        reasoning: str,
        source: str
    ) -> ContainerClassification:
        """Create classification result with associated strategy."""
        strategies = {
            ContainerType.CONTENT_LIST: (
                "Sample 2-3 items only. Verify common actions. "
                "Treat as template - don't explore every item."
            ),
            ContainerType.NAVIGATION_LIST: (
                "Visit each item at least once. Record screen transitions. "
                "Map the navigation graph completely."
            ),
            ContainerType.OPTION_LIST: (
                "Toggle each option. Verify state changes without navigation. "
                "Stay on current screen."
            ),
            ContainerType.UNKNOWN: (
                "Explore small subset first. Observe behavior before deciding. "
                "Gather evidence for reclassification."
            ),
        }

        return ContainerClassification(
            container_type=container_type,
            confidence=confidence,
            reasoning=reasoning,
            strategy=strategies.get(container_type, "Unknown strategy"),
            source=source
        )


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test heuristic classifier
    print("=== Testing Heuristic Classifier ===\n")

    # Example 1: Product list
    product_list_xml = """
    <RecyclerView>
        <Item>
            <ImageView src="..." />
            <Text>iPhone 15</Text>
            <Text>$999</Text>
            <RatingBar rating="4.5" />
        </Item>
        <Item>
            <ImageView src="..." />
            <Text>Samsung Galaxy</Text>
            <Text>$899</Text>
            <RatingBar rating="4.2" />
        </Item>
    </RecyclerView>
    """
    product_labels = ["iPhone 15", "$999", "rating", "Samsung Galaxy", "$899"]
    product_type, product_conf, product_reason = HeuristicClassifier.classify_heuristic(
        product_list_xml, product_labels
    )
    print(f"Product List: {product_type.value} (conf={product_conf:.2f})")
    print(f"  Reasoning: {product_reason}\n")

    # Example 2: Navigation menu
    nav_menu_xml = """
    <LinearLayout orientation="vertical">
        <MenuItem>
            <Icon src="settings.png" />
            <Text>Settings</Text>
        </MenuItem>
        <MenuItem>
            <Icon src="profile.png" />
            <Text>Profile</Text>
        </MenuItem>
        <MenuItem>
            <Icon src="logout.png" />
            <Text>Logout</Text>
        </MenuItem>
    </LinearLayout>
    """
    nav_labels = ["Settings", "Profile", "Logout", "Account"]
    nav_type, nav_conf, nav_reason = HeuristicClassifier.classify_heuristic(
        nav_menu_xml, nav_labels
    )
    print(f"Navigation Menu: {nav_type.value} (conf={nav_conf:.2f})")
    print(f"  Reasoning: {nav_reason}\n")

    # Example 3: Option list
    option_list_xml = """
    <LinearLayout>
        <RadioButton>Ascending</RadioButton>
        <RadioButton>Descending</RadioButton>
        <Checkbox>Filter by price</Checkbox>
    </LinearLayout>
    """
    option_labels = ["Ascending", "Descending", "Filter", "Sort options"]
    option_type, option_conf, option_reason = HeuristicClassifier.classify_heuristic(
        option_list_xml, option_labels
    )
    print(f"Option List: {option_type.value} (conf={option_conf:.2f})")
    print(f"  Reasoning: {option_reason}\n")

    # Test behavioral classifier
    print("=== Testing Behavioral Classifier ===\n")

    nav_results = [
        {"element_id": "product_1", "target_screen_sig": "screen_abc", "target_screen_desc": "Product detail page with image, title, price, reviews"},
        {"element_id": "product_2", "target_screen_sig": "screen_xyz", "target_screen_desc": "Product detail page with image, title, price, reviews"},
        {"element_id": "product_3", "target_screen_sig": "screen_def", "target_screen_desc": "Product detail page with image, title, price, reviews"},
    ]
    behav_type, behav_conf, behav_reason = BehavioralClassifier.analyze_navigation_results(nav_results)
    print(f"Behavioral Analysis (3 similar products): {behav_type.value} (conf={behav_conf:.2f})")
    print(f"  Reasoning: {behav_reason}\n")
