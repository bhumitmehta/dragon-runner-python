#!/usr/bin/env python3
"""
Manual test for hash logic - run from python_agent directory
"""

import sys
import os

# We need to be in the python_agent directory for relative imports to work
# The script should be run from: cd python_agent && python test_hash_runner.py

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

# Now import memory - relative imports will work because we're in the package
from memory import state_signature_from_xml, _should_skeletonize_list, _detect_repeated_structures
import xml.etree.ElementTree as ET

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

# Same products but scrolled (different items visible)
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
    print(f"  Scrolled products:   {hash2}")
    
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
    print("HASH LOGIC MANUAL TEST")
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
    sys.exit(0 if success else 1)
