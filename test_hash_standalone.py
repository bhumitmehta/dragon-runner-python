#!/usr/bin/env python3
"""
Standalone test for hash logic - copies relevant functions to avoid import issues
"""

import datetime
import hashlib
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

# Mock logger
class MockLogger:
    def debug(self, *args): pass
    def info(self, *args): pass
    def warning(self, *args): pass
    def error(self, *args): pass
    def exception(self, *args): pass

logger = MockLogger()

# Cache for skeletonization decisions: structure_hash -> should_skeletonize
_skeletonization_cache: Dict[str, bool] = {}

# Configuration
SKELETONIZATION_ENABLED = True
MAX_CACHE_SIZE = 1000

def _detect_repeated_structures(root: ET.Element) -> List[Tuple[ET.Element, List[ET.Element]]]:
    """Detect containers with repeated child structures."""
    repeated = []
    
    def traverse(element: ET.Element):
        children = list(element)
        if len(children) >= 3:
            structure_groups: Dict[str, List[ET.Element]] = {}
            for child in children:
                structure_key = _get_structure_signature(child)
                if structure_key not in structure_groups:
                    structure_groups[structure_key] = []
                structure_groups[structure_key].append(child)
            
            for structure_key, group in structure_groups.items():
                if len(group) >= 3:
                    repeated.append((element, group))
        
        for child in children:
            traverse(child)
    
    traverse(root)
    return repeated

def _get_structure_signature(element: ET.Element) -> str:
    """Get a signature representing element structure (not content)."""
    tag = element.tag
    attrib_keys = sorted(element.attrib.keys())
    attrib_str = ','.join(f"{k}" for k in attrib_keys)
    children_sig = ','.join(_get_structure_signature(c) for c in element)
    return f"{tag}[{attrib_str}]({children_sig})"

def _should_skeletonize_list(container: ET.Element, children: List[ET.Element]) -> bool:
    """DETERMINISTIC: Decide if a list should be skeletonized based on heuristics.
    
    Returns True for scrollable data lists (products, items) - should produce same hash when scrolled.
    Returns False for navigation menus - should produce different hash per configuration.
    """
    # Get container attributes
    container_class = container.get('class', '').lower()
    container_id = container.get('resource-id', '').lower()
    is_scrollable = container.get('scrollable', 'false').lower() == 'true'
    
    # Check for menu/navigation indicators (should NOT skeletonize)
    menu_indicators = ['navigation', 'nav', 'menu', 'tab', 'drawer', 'bottombar', 'toolbar']
    for indicator in menu_indicators:
        if indicator in container_class or indicator in container_id:
            logger.debug(f"Menu detected (indicator: {indicator}), NOT skeletonizing")
            return False
    
    # Check for scrollable containers with data-like names (should skeletonize)
    data_indicators = ['list', 'recycler', 'scroll', 'content', 'feed', 'grid']
    if is_scrollable:
        for indicator in data_indicators:
            if indicator in container_class or indicator in container_id:
                logger.debug(f"Scrollable data list detected (indicator: {indicator}), skeletonizing")
                return True
    
    # Analyze children for price patterns (products have prices)
    price_pattern_count = 0
    for child in children[:3]:  # Check first 3 children
        text = child.get('text', '')
        content_desc = child.get('content-desc', '')
        combined_text = f"{text} {content_desc}"
        
        # Look for price patterns like $19.99, €20, £15.50
        import re
        if re.search(r'[$€£]\s*\d+[.,]?\d*', combined_text) or re.search(r'\d+[.,]?\d*\s*[$€£]', combined_text):
            price_pattern_count += 1
    
    if price_pattern_count >= 2:
        logger.debug(f"Price patterns detected ({price_pattern_count}), skeletonizing as product list")
        return True
    
    # Analyze text uniqueness - menus have unique text per item
    texts = []
    for child in children[:5]:
        text = child.get('text', '') or child.get('content-desc', '')
        if text:
            texts.append(text.lower())
    
    if len(texts) >= 3:
        unique_texts = set(texts)
        uniqueness_ratio = len(unique_texts) / len(texts)
        
        # High uniqueness suggests menu/navigation (don't skeletonize)
        if uniqueness_ratio > 0.8:
            logger.debug(f"High text uniqueness ({uniqueness_ratio:.2f}), NOT skeletonizing")
            return False
    
    # Check resource-id patterns
    ids = []
    for child in children[:5]:
        child_id = child.get('resource-id', '')
        if child_id:
            ids.append(child_id)
    
    if len(ids) >= 3:
        # Check for sequential patterns (item_1, item_2) - suggests data
        sequential_count = 0
        for child_id in ids:
            if re.search(r'_\d+$', child_id) or re.search(r'\d+$', child_id):
                sequential_count += 1
        
        if sequential_count >= len(ids) * 0.6:
            logger.debug(f"Sequential IDs detected, skeletonizing")
            return True
        
        # Check for descriptive IDs (home, settings) - suggests menu
        descriptive_indicators = ['home', 'settings', 'profile', 'menu', 'nav', 'tab', 'about', 'help']
        descriptive_count = sum(1 for cid in ids if any(ind in cid.lower() for ind in descriptive_indicators))
        
        if descriptive_count >= len(ids) * 0.5:
            logger.debug(f"Descriptive IDs detected ({descriptive_count}), NOT skeletonizing")
            return False
    
    # Default: conservative - don't skeletonize if uncertain
    logger.debug(f"No clear indicators, defaulting to NOT skeletonize")
    return False

def _skeletonize_container(container: ET.Element, children: List[ET.Element]) -> None:
    """Replace repeated list items with a single skeleton element."""
    if not children:
        return
    
    # Keep the first child as template
    template = children[0]
    
    # Remove all children
    for child in children:
        container.remove(child)
    
    # Create skeleton element
    skeleton = ET.SubElement(container, template.tag)
    
    # Copy structural attributes (class, resource-id pattern)
    for key in ['class', 'clickable', 'focusable']:
        if key in template.attrib:
            skeleton.set(key, template.attrib[key])
    
    # Set resource-id to pattern (remove specific index)
    if 'resource-id' in template.attrib:
        orig_id = template.attrib['resource-id']
        # Replace trailing numbers with wildcard
        import re
        pattern_id = re.sub(r'_\d+$', '_*', orig_id)
        pattern_id = re.sub(r'\d+$', '*', pattern_id)
        skeleton.set('resource-id', pattern_id)
    
    # Mark as skeleton
    skeleton.set('skeleton', 'true')
    skeleton.set('item-count', str(len(children)))

def _apply_skeletonization(root: ET.Element) -> ET.Element:
    """Apply skeletonization to repeated structures."""
    if not SKELETONIZATION_ENABLED:
        return root
    
    repeated = _detect_repeated_structures(root)
    
    for container, children in repeated:
        # Create cache key
        structure_hash = hashlib.md5(
            ET.tostring(container, encoding='unicode').encode()
        ).hexdigest()[:16]
        
        if structure_hash not in _skeletonization_cache:
            _skeletonization_cache[structure_hash] = _should_skeletonize_list(container, children)
        
        if _skeletonization_cache[structure_hash]:
            _skeletonize_container(container, children)
    
    return root

def state_signature_from_xml(xml_string: str) -> str:
    """Generate a hash signature from XML string."""
    try:
        root = ET.fromstring(xml_string)
        root = _apply_skeletonization(root)
        canonical = _canonical_xml_string(root)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]
    except Exception as e:
        logger.exception(f"Error generating state signature: {e}")
        return hashlib.sha256(str(e).encode('utf-8')).hexdigest()[:16]

def _canonical_xml_string(element: ET.Element, level: int = 0) -> str:
    """Convert element to canonical string representation."""
    indent = "  " * level
    attribs = []
    for key in sorted(element.attrib.keys()):
        val = element.attrib[key]
        attribs.append(f'{key}="{val}"')
    
    attrib_str = " " + " ".join(attribs) if attribs else ""
    result = f"{indent}<{element.tag}{attrib_str}>"
    
    children = list(element)
    if children:
        result += "\n"
        for child in children:
            result += _canonical_xml_string(child, level + 1)
        result += f"{indent}</{element.tag}>\n"
    else:
        text = element.text or ""
        if text.strip():
            result += text
        result += f"</{element.tag}>\n"
    
    return result

# Test XMLs
PRODUCT_LIST_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
    <androidx.recyclerview.widget.RecyclerView class="androidx.recyclerview.widget.RecyclerView" resource-id="com.example:id/product_list" scrollable="true">
        <android.widget.LinearLayout class="android.widget.LinearLayout" resource-id="com.example:id/product_item_1">
            <android.widget.TextView class="android.widget.TextView" text="Product A" resource-id="com.example:id/product_name"/>
            <android.widget.TextView class="android.widget.TextView" text="$19.99" resource-id="com.example:id/product_price"/>
        </android.widget.LinearLayout>
        <android.widget.LinearLayout class="android.widget.LinearLayout" resource-id="com.example:id/product_item_2">
            <android.widget.TextView class="android.widget.TextView" text="Product B" resource-id="com.example:id/product_name"/>
            <android.widget.TextView class="android.widget.TextView" text="$29.99" resource-id="com.example:id/product_price"/>
        </android.widget.LinearLayout>
        <android.widget.LinearLayout class="android.widget.LinearLayout" resource-id="com.example:id/product_item_3">
            <android.widget.TextView class="android.widget.TextView" text="Product C" resource-id="com.example:id/product_name"/>
            <android.widget.TextView class="android.widget.TextView" text="$39.99" resource-id="com.example:id/product_price"/>
        </android.widget.LinearLayout>
    </androidx.recyclerview.widget.RecyclerView>
</hierarchy>'''

PRODUCT_LIST_SCROLLED_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
    <androidx.recyclerview.widget.RecyclerView class="androidx.recyclerview.widget.RecyclerView" resource-id="com.example:id/product_list" scrollable="true">
        <android.widget.LinearLayout class="android.widget.LinearLayout" resource-id="com.example:id/product_item_4">
            <android.widget.TextView class="android.widget.TextView" text="Product D" resource-id="com.example:id/product_name"/>
            <android.widget.TextView class="android.widget.TextView" text="$49.99" resource-id="com.example:id/product_price"/>
        </android.widget.LinearLayout>
        <android.widget.LinearLayout class="android.widget.LinearLayout" resource-id="com.example:id/product_item_5">
            <android.widget.TextView class="android.widget.TextView" text="Product E" resource-id="com.example:id/product_name"/>
            <android.widget.TextView class="android.widget.TextView" text="$59.99" resource-id="com.example:id/product_price"/>
        </android.widget.LinearLayout>
        <android.widget.LinearLayout class="android.widget.LinearLayout" resource-id="com.example:id/product_item_6">
            <android.widget.TextView class="android.widget.TextView" text="Product F" resource-id="com.example:id/product_name"/>
            <android.widget.TextView class="android.widget.TextView" text="$69.99" resource-id="com.example:id/product_price"/>
        </android.widget.LinearLayout>
    </androidx.recyclerview.widget.RecyclerView>
</hierarchy>'''

MENU_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
    <android.widget.LinearLayout class="android.widget.LinearLayout" resource-id="com.example:id/navigation_menu">
        <android.widget.Button class="android.widget.Button" resource-id="com.example:id/nav_home" text="Home"/>
        <android.widget.Button class="android.widget.Button" resource-id="com.example:id/nav_settings" text="Settings"/>
        <android.widget.Button class="android.widget.Button" resource-id="com.example:id/nav_profile" text="Profile"/>
        <android.widget.Button class="android.widget.Button" resource-id="com.example:id/nav_about" text="About"/>
    </android.widget.LinearLayout>
</hierarchy>'''

MENU_DIFFERENT_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
    <android.widget.LinearLayout class="android.widget.LinearLayout" resource-id="com.example:id/navigation_menu">
        <android.widget.Button class="android.widget.Button" resource-id="com.example:id/nav_home" text="Home"/>
        <android.widget.Button class="android.widget.Button" resource-id="com.example:id/nav_settings" text="Settings"/>
        <android.widget.Button class="android.widget.Button" resource-id="com.example:id/nav_profile" text="Profile"/>
        <android.widget.Button class="android.widget.Button" resource-id="com.example:id/nav_help" text="Help"/>
    </android.widget.LinearLayout>
</hierarchy>'''

def test_hash_consistency():
    """Test that the same XML produces the same hash every time."""
    print("\n=== Test 1: Hash Consistency ===")
    hashes = []
    for i in range(5):
        h = state_signature_from_xml(PRODUCT_LIST_XML)
        hashes.append(h)
        print(f"  Run {i+1}: {h}")
    
    if len(set(hashes)) == 1:
        print(f"  ✓ PASS: All hashes identical")
        return True
    else:
        print(f"  ✗ FAIL: Got {len(set(hashes))} different hashes")
        return False

def test_product_list_scrolling():
    """Test that scrolled product lists produce the same hash."""
    print("\n=== Test 2: Product List Scrolling ===")
    hash1 = state_signature_from_xml(PRODUCT_LIST_XML)
    hash2 = state_signature_from_xml(PRODUCT_LIST_SCROLLED_XML)
    
    print(f"  Original products: {hash1}")
    print(f"  Scrolled products: {hash2}")
    
    if hash1 == hash2:
        print("  ✓ PASS: Same hash for scrolled products (skeletonization working)")
        return True
    else:
        print("  ✗ FAIL: Different hashes for scrolled products")
        return False

def test_menu_different_configs():
    """Test that different menu configurations produce different hashes."""
    print("\n=== Test 3: Menu Different Configurations ===")
    hash1 = state_signature_from_xml(MENU_XML)
    hash2 = state_signature_from_xml(MENU_DIFFERENT_XML)
    
    print(f"  Menu with 'About': {hash1}")
    print(f"  Menu with 'Help':  {hash2}")
    
    if hash1 != hash2:
        print("  ✓ PASS: Different hashes for different menu configs")
        return True
    else:
        print("  ✗ FAIL: Same hash for different menu configs")
        return False

def test_determinism():
    """Test that results are consistent across multiple runs."""
    print("\n=== Test 4: Determinism Check ===")
    results = []
    for _ in range(3):
        h1 = state_signature_from_xml(PRODUCT_LIST_XML)
        h2 = state_signature_from_xml(PRODUCT_LIST_SCROLLED_XML)
        h3 = state_signature_from_xml(MENU_XML)
        results.append((h1, h2, h3))
    
    if len(set(results)) == 1:
        print("  ✓ PASS: Results are deterministic across runs")
        return True
    else:
        print(f"  ✗ FAIL: Got {len(set(results))} different result sets")
        for i, r in enumerate(results):
            print(f"    Run {i+1}: {r}")
        return False

def main():
    print("=" * 60)
    print("HASH LOGIC STANDALONE TEST")
    print("=" * 60)
    
    results = []
    results.append(("Hash Consistency", test_hash_consistency()))
    results.append(("Product List Scrolling", test_product_list_scrolling()))
    results.append(("Menu Different Configs", test_menu_different_configs()))
    results.append(("Determinism", test_determinism()))
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
    
    total = len(results)
    passed = sum(1 for _, p in results if p)
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return all(r[1] for r in results)

if __name__ == "__main__":
    success = main()
    import sys
    sys.exit(0 if success else 1)
