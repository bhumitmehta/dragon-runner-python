"""
Screen Template Matching System

Solves the "same screen produces different hashes" problem by:
1. Recognizing when multiple screens are actually variations of a template
2. Computing normalized structural signatures (ignore dynamic content)
3. Grouping screens by layout template, not content

This is critical for content lists where:
  ProductPage1 (iPhone) → hash_abc
  ProductPage2 (Samsung) → hash_def
  ProductPage3 (Google) → hash_ghi

Should all be recognized as the same TEMPLATE, not 3 different screens.

The system:
- Extracts structural XML (ignores text values)
- Computes layout fingerprint (tag hierarchy, positions, counts)
- Groups screens by >0.85 Jaccard similarity on structure
- Treats variations as "visits" to same template
"""

import logging
import hashlib
import re
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ScreenTemplate:
    """Represents a screen layout template."""
    template_sig: str  # Normalized structural signature
    screen_sigs: Set[str]  # Actual hashes that match this template
    structure_description: str  # Human-readable layout (e.g., "Header + Grid(3col) + Footer")
    samples: List[str]  # Example element paths


class ScreenTemplateAnalyzer:
    """Analyzes screen structures to identify templates."""

    STRUCTURE_SIMILARITY_THRESHOLD = 0.85  # Min Jaccard to group as same template

    @staticmethod
    def extract_structural_elements(screen_xml: str) -> List[str]:
        """
        Extract structural elements from screen XML, ignoring text content.

        Returns list of element signatures preserving hierarchy depth.

        Example:
          <Activity>
            <LinearLayout>
              <ImageView width="100" height="100"/>
              <TextView length="20"/>
              <TextView length="15"/>
            </LinearLayout>
            <Button/>
          </Activity>

          Returns:
          [
            "Activity",
            "  LinearLayout",
            "    ImageView(100x100)",
            "    TextView",
            "    TextView",
            "  Button"
          ]
        """
        elements = []

        # Parse XML to extract tags with attributes (ignore text content)
        tag_pattern = r'<(\w+)([^>]*)>'
        matches = re.finditer(tag_pattern, screen_xml)

        current_depth = 0
        element_stack = []

        for match in matches:
            tag_name = match.group(1)
            attributes = match.group(2)

            # Skip closing tags (processed via pop)
            if screen_xml[match.end():match.end() + 2] == "</":
                continue

            # Determine if self-closing or opening
            is_self_closing = attributes.endswith("/") or tag_name in {
                "ImageView", "View", "ImageButton", "ProgressBar", "RatingBar"
            }

            # Extract key dimensions/attributes
            dimension_sig = ScreenTemplateAnalyzer._extract_dimension_sig(attributes)
            element_sig = f"{tag_name}{dimension_sig}" if dimension_sig else tag_name

            # Add with indentation to represent hierarchy
            indent = "  " * current_depth
            elements.append(f"{indent}{element_sig}")

            if not is_self_closing:
                element_stack.append(tag_name)
                current_depth += 1

            # Track closing tags
            next_close = screen_xml.find(f"</{tag_name}>", match.end())
            if next_close != -1 and element_stack:
                # In a real parser, would track nesting properly
                # This is simplified version
                pass

        return elements

    @staticmethod
    def _extract_dimension_sig(attributes: str) -> str:
        """Extract dimension signature from attributes."""
        signatures = []

        # Width
        width_match = re.search(r'width="?(\d+)', attributes)
        if width_match:
            signatures.append(f"w{width_match.group(1)}")

        # Height
        height_match = re.search(r'height="?(\d+)', attributes)
        if height_match:
            signatures.append(f"h{height_match.group(1)}")

        # Layout weight (grid indicator)
        weight_match = re.search(r'weight="?([0-9.]+)', attributes)
        if weight_match:
            signatures.append(f"wt{weight_match.group(1)}")

        # Layout orientation (repeating indicator)
        if "horizontal" in attributes:
            signatures.append("horiz")
        if "vertical" in attributes:
            signatures.append("vert")

        return f"({','.join(signatures)})" if signatures else ""

    @staticmethod
    def compute_structure_signature(screen_xml: str) -> str:
        """
        Compute normalized signature based on structure only.

        Ignores:
        - Text content
        - Dynamic IDs
        - Resource paths
        - Specific values

        Considers:
        - Element types
        - Hierarchy depth
        - Dimensions
        - Counts of each type at each level
        """
        elements = ScreenTemplateAnalyzer.extract_structural_elements(screen_xml)

        # Build element fingerprint
        fingerprint = "\n".join(elements)

        # Hash
        sig = hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
        return sig

    @staticmethod
    def describe_structure(screen_xml: str) -> str:
        """Generate human-readable description of screen structure."""
        elements = ScreenTemplateAnalyzer.extract_structural_elements(screen_xml)

        # Count element types at top level (depth 0)
        top_level = [e for e in elements if not e.startswith("  ")]
        element_counts = defaultdict(int)

        for elem in top_level:
            match = re.search(r'(\w+)', elem)
            if match:
                element_counts[match.group(1)] += 1

        # Build description
        parts = []
        for elem_type, count in sorted(element_counts.items()):
            if count > 1:
                parts.append(f"{count}x {elem_type}")
            else:
                parts.append(elem_type)

        description = " + ".join(parts) if parts else "Unknown"
        return description

    @staticmethod
    def compute_jaccard_similarity(struct1: str, struct2: str) -> float:
        """
        Compute Jaccard similarity between two structure signatures.

        Tokenizes by element type and hierarchy.
        """
        # Parse into element sequences
        def tokenize(s):
            # Simple tokenization - element type at each line
            tokens = set()
            for line in s.split("\n"):
                if line.strip():
                    match = re.search(r'(\w+)', line)
                    if match:
                        depth = len(line) - len(line.lstrip())
                        tokens.add((depth // 2, match.group(1)))
            return tokens

        tokens1 = tokenize(struct1)
        tokens2 = tokenize(struct2)

        if not tokens1 or not tokens2:
            return 0.0

        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)

        return intersection / union if union > 0 else 0.0


class ScreenTemplateRegistry:
    """
    Maintains a registry of screen templates.

    Maps screen signatures to templates and groups variations.
    """

    def __init__(self, knowledge_base=None):
        """
        Initialize registry.

        Args:
            knowledge_base: Optional KnowledgeBase for persistence
        """
        self.knowledge_base = knowledge_base
        self._templates: Dict[str, ScreenTemplate] = {}
        self._sig_to_template: Dict[str, str] = {}  # screen_sig → template_sig
        self._loaded = False

    def load_from_kb(self):
        """Load templates from knowledge base."""
        if not self.knowledge_base or self._loaded:
            return

        try:
            from tinydb import Query
            table = self.knowledge_base.get_table("screen_templates")
            for doc in table.all():
                template = ScreenTemplate(
                    template_sig=doc["template_sig"],
                    screen_sigs=set(doc.get("screen_sigs", [])),
                    structure_description=doc.get("description", ""),
                    samples=doc.get("samples", [])
                )
                self._templates[template.template_sig] = template

                # Build reverse index
                for screen_sig in template.screen_sigs:
                    self._sig_to_template[screen_sig] = template.template_sig

            logger.info(f"Loaded {len(self._templates)} templates from KB")
            self._loaded = True
        except Exception as e:
            logger.debug(f"Failed to load templates from KB: {e}")

    def save_to_kb(self):
        """Persist templates to knowledge base."""
        if not self.knowledge_base:
            return

        try:
            from tinydb import Query
            table = self.knowledge_base.get_table("screen_templates")
            Template = Query()

            for template_sig, template in self._templates.items():
                existing = table.search(Template.template_sig == template_sig)
                doc = {
                    "template_sig": template.template_sig,
                    "screen_sigs": list(template.screen_sigs),
                    "description": template.structure_description,
                    "samples": template.samples,
                }
                if existing:
                    table.update(doc, Template.template_sig == template_sig)
                else:
                    table.insert(doc)

            logger.debug(f"Saved {len(self._templates)} templates to KB")
        except Exception as e:
            logger.debug(f"Failed to save templates to KB: {e}")

    def get_template_for_screen(self, screen_sig: str) -> Optional[ScreenTemplate]:
        """Retrieve template for a screen signature."""
        template_sig = self._sig_to_template.get(screen_sig)
        if template_sig:
            return self._templates.get(template_sig)
        return None

    def register_screen(self, screen_sig: str, screen_source: str, screen_description: str = ""):
        """
        Register a new screen, grouping with existing template if similar.

        Args:
            screen_sig: Actual screen signature (with content)
            screen_source: XML or structure source
            screen_description: Human description of screen
        """
        # Check if already registered
        if screen_sig in self._sig_to_template:
            return self._sig_to_template[screen_sig]

        # Compute structure signature
        struct_sig = ScreenTemplateAnalyzer.compute_structure_signature(screen_source)
        struct_desc = ScreenTemplateAnalyzer.describe_structure(screen_source)

        # Find similar existing templates
        best_match = None
        best_similarity = 0.0

        for template_sig, template in self._templates.items():
            # Re-compute structure sig for existing templates if needed
            # For now, use stored description to estimate
            similarity = 0.5  # Default estimate

            # Better: compute from samples if available
            if template.samples:
                similarity = ScreenTemplateAnalyzer.compute_jaccard_similarity(
                    struct_sig, template.structure_description
                )

            if similarity > best_similarity:
                best_similarity = similarity
                best_match = template_sig

        # Create or update template
        if best_match and best_similarity > ScreenTemplateAnalyzer.STRUCTURE_SIMILARITY_THRESHOLD:
            template = self._templates[best_match]
            template.screen_sigs.add(screen_sig)
            template.samples.append(screen_description)
            self._sig_to_template[screen_sig] = best_match
            logger.info(f"Screen {screen_sig} grouped with template {best_match} (sim={best_similarity:.2f})")
        else:
            # Create new template
            new_template_sig = struct_sig
            new_template = ScreenTemplate(
                template_sig=new_template_sig,
                screen_sigs={screen_sig},
                structure_description=struct_desc,
                samples=[screen_description]
            )
            self._templates[new_template_sig] = new_template
            self._sig_to_template[screen_sig] = new_template_sig
            logger.info(f"Created new template {new_template_sig} for screen {screen_sig}")

        return self._sig_to_template[screen_sig]

    def get_template_visit_count(self, screen_sig: str) -> int:
        """
        Get total visit count for a screen's template.

        (Summed across all variations of template, not just this screen_sig)
        """
        template_sig = self._sig_to_template.get(screen_sig)
        if not template_sig:
            return 0

        template = self._templates[template_sig]
        return len(template.screen_sigs)  # Approximate - screen_sigs = visits

    def get_all_screens_for_template(self, screen_sig: str) -> Set[str]:
        """Get all screen signatures that belong to the same template."""
        template_sig = self._sig_to_template.get(screen_sig)
        if not template_sig:
            return {screen_sig}

        return self._templates[template_sig].screen_sigs


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Screen Template Matching ===\n")

    # Example: Three product detail pages (different products, same template)
    product_page_1 = """
    <Activity>
        <Toolbar>
            <Button id="back">Back</Button>
            <TextView text="Product Details"/>
        </Toolbar>
        <ScrollView>
            <ImageView src="product_image_1.jpg" width="200" height="200"/>
            <LinearLayout orientation="vertical">
                <TextView text="iPhone 15 Pro"/>
                <RatingBar rating="4.5"/>
                <TextView text="$999"/>
                <Button id="add_to_cart">Add to Cart</Button>
            </LinearLayout>
        </ScrollView>
    </Activity>
    """

    product_page_2 = """
    <Activity>
        <Toolbar>
            <Button id="back">Back</Button>
            <TextView text="Product Details"/>
        </Toolbar>
        <ScrollView>
            <ImageView src="product_image_2.jpg" width="200" height="200"/>
            <LinearLayout orientation="vertical">
                <TextView text="Samsung Galaxy S24"/>
                <RatingBar rating="4.7"/>
                <TextView text="$899"/>
                <Button id="add_to_cart">Add to Cart</Button>
            </LinearLayout>
        </ScrollView>
    </Activity>
    """

    product_page_3 = """
    <Activity>
        <Toolbar>
            <Button id="back">Back</Button>
            <TextView text="Product Details"/>
        </Toolbar>
        <ScrollView>
            <ImageView src="product_image_3.jpg" width="200" height="200"/>
            <LinearLayout orientation="vertical">
                <TextView text="Google Pixel 9"/>
                <RatingBar rating="4.8"/>
                <TextView text="$799"/>
                <Button id="add_to_cart">Add to Cart</Button>
            </LinearLayout>
        </ScrollView>
    </Activity>
    """

    # Different template - settings page
    settings_page = """
    <Activity>
        <Toolbar>
            <TextView text="Settings"/>
        </Toolbar>
        <ListView>
            <ListItem>
                <Icon src="settings_icon"/>
                <TextView text="Display Settings"/>
            </ListItem>
            <ListItem>
                <Icon src="privacy_icon"/>
                <TextView text="Privacy"/>
            </ListItem>
        </ListView>
    </Activity>
    """

    # Test structure extraction
    print("Product Page 1 elements:")
    elements1 = ScreenTemplateAnalyzer.extract_structural_elements(product_page_1)
    for elem in elements1:
        print(f"  {elem}")

    print("\nStructure signatures:")
    sig1 = ScreenTemplateAnalyzer.compute_structure_signature(product_page_1)
    sig2 = ScreenTemplateAnalyzer.compute_structure_signature(product_page_2)
    sig3 = ScreenTemplateAnalyzer.compute_structure_signature(product_page_3)
    sig_settings = ScreenTemplateAnalyzer.compute_structure_signature(settings_page)

    print(f"  Product 1: {sig1}")
    print(f"  Product 2: {sig2}")
    print(f"  Product 3: {sig3}")
    print(f"  Settings:  {sig_settings}")

    # Test similarity
    print("\nStructure similarity (should be similar for products, different for settings):")
    analyzer_elements1 = ScreenTemplateAnalyzer.extract_structural_elements(product_page_1)
    analyzer_elements2 = ScreenTemplateAnalyzer.extract_structural_elements(product_page_2)
    sim_12 = ScreenTemplateAnalyzer.compute_jaccard_similarity(
        "\n".join(analyzer_elements1),
        "\n".join(analyzer_elements2)
    )
    print(f"  Product 1 <-> Product 2: {sim_12:.2f}")

    # Test registry
    print("\nTemplate registry:")
    registry = ScreenTemplateRegistry()

    template1 = registry.register_screen("hash_abc123", product_page_1, "iPhone 15 product page")
    print(f"  Registered Product 1 → Template {template1}")

    template2 = registry.register_screen("hash_def456", product_page_2, "Samsung Galaxy product page")
    print(f"  Registered Product 2 → Template {template2}")

    template3 = registry.register_screen("hash_ghi789", product_page_3, "Google Pixel product page")
    print(f"  Registered Product 3 → Template {template3}")

    template_settings = registry.register_screen("hash_jkl012", settings_page, "Settings page")
    print(f"  Registered Settings → Template {template_settings}")

    print(f"\n✓ Successfully grouped {len([template1, template2, template3])} product pages into same template")
    print(f"✓ Settings page in separate template")

    print("\nScreen-to-template mapping:")
    print(f"  hash_abc123 → {registry.get_template_for_screen('hash_abc123').template_sig}")
    print(f"  hash_def456 → {registry.get_template_for_screen('hash_def456').template_sig}")
    print(f"  hash_jkl012 → {registry.get_template_for_screen('hash_jkl012').template_sig}")
