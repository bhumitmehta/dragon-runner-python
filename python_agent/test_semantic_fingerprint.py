"""
Test Semantic Fingerprinting
============================

Tests the semantic fingerprinting approach using real XML dumps from the repo.
Demonstrates that content-desc based fingerprints survive scroll position changes
while still detecting genuinely different screens.
"""

import sys
sys.path.insert(0, 'c:\\Users\\20092\\Desktop\\prooject\\ai-projects\\dragon-runner-python\\python_agent')

from semantic_fingerprint import (
    SemanticFingerprint, 
    semantic_screen_fingerprint,
    SemanticScreenRegistry,
    are_screens_similar
)


def load_xml_file(filepath: str) -> str:
    """Load XML from file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: {filepath} not found, using synthetic data")
        return None


def test_real_xml_dumps():
    """Test with actual XML dumps from the repo."""
    print("=" * 70)
    print("TEST 1: Real XML Dumps (window_dump.xml vs window_dump1.xml)")
    print("=" * 70)
    
    # Load real XML dumps
    xml1 = load_xml_file('c:\\Users\\20092\\Desktop\\prooject\\ai-projects\\dragon-runner-python\\window_dump.xml')
    xml2 = load_xml_file('c:\\Users\\20092\\Desktop\\prooject\\ai-projects\\dragon-runner-python\\window_dump1.xml')
    
    if xml1 is None or xml2 is None:
        print("Skipping - XML files not available")
        return True
    
    activity = "com.saucelabs.mydemoapp.rn.MainActivity"
    
    # Create fingerprints
    fp1 = SemanticFingerprint.from_xml(xml1, activity)
    fp2 = SemanticFingerprint.from_xml(xml2, activity)
    
    print(f"\nScreen 1 (window_dump.xml):")
    print(f"  Semantic Hash: {fp1.semantic_hash}")
    print(f"  Content Descriptions: {len(fp1.content_descs)} unique")
    print(f"  Resource IDs: {len(fp1.resource_ids)} unique")
    print(f"  Stats: {fp1.raw_stats}")
    
    print(f"\nScreen 2 (window_dump1.xml):")
    print(f"  Semantic Hash: {fp2.semantic_hash}")
    print(f"  Content Descriptions: {len(fp2.content_descs)} unique")
    print(f"  Resource IDs: {len(fp2.resource_ids)} unique")
    print(f"  Stats: {fp2.raw_stats}")
    
    # Compare
    similarity = fp1.jaccard_similarity(fp2)
    is_same = fp1.is_similar_to(fp2)
    
    print(f"\nComparison:")
    print(f"  Jaccard Similarity: {similarity:.2%}")
    print(f"  Are Similar: {is_same}")
    
    # Show overlap
    overlap = fp1.content_descs & fp2.content_descs
    only_in_1 = fp1.content_descs - fp2.content_descs
    only_in_2 = fp2.content_descs - fp1.content_descs
    
    print(f"\nContent-desc Overlap: {len(overlap)} elements")
    print(f"  Only in Screen 1: {sorted(only_in_1)[:5]}...")  # Show first 5
    print(f"  Only in Screen 2: {sorted(only_in_2)[:5]}...")
    
    # These should be the same screen at different scroll positions
    assert is_same, "Expected same screen (different scroll positions)"
    assert similarity > 0.7, f"Expected high similarity, got {similarity:.2%}"
    
    print("\n✅ PASS: Same screen correctly identified despite scroll position\n")
    return True


def test_scroll_invariance():
    """Test that scroll position doesn't change fingerprint dramatically."""
    print("=" * 70)
    print("TEST 2: Scroll Invariance")
    print("=" * 70)
    
    activity = "ProductListActivity"
    
    # Simulate a list screen - initial view
    xml_initial = '''
    <hierarchy>
        <node content-desc="header" />
        <node content-desc="search bar" />
        <node content-desc="product_item_1" clickable="true" />
        <node content-desc="product_item_2" clickable="true" />
        <node content-desc="product_item_3" clickable="true" />
        <node content-desc="scrollable_list" scrollable="true" />
    </hierarchy>
    '''
    
    # Same screen, scrolled down (items 2,3,4 visible)
    xml_scrolled = '''
    <hierarchy>
        <node content-desc="header" />
        <node content-desc="search bar" />
        <node content-desc="product_item_2" clickable="true" />
        <node content-desc="product_item_3" clickable="true" />
        <node content-desc="product_item_4" clickable="true" />
        <node content-desc="scrollable_list" scrollable="true" />
    </hierarchy>
    '''
    
    fp_initial = SemanticFingerprint.from_xml(xml_initial, activity)
    fp_scrolled = SemanticFingerprint.from_xml(xml_scrolled, activity)
    
    print(f"Initial view hash: {fp_initial.semantic_hash}")
    print(f"Scrolled view hash: {fp_scrolled.semantic_hash}")
    
    similarity = fp_initial.jaccard_similarity(fp_scrolled)
    print(f"Similarity: {similarity:.2%}")
    
    # Should be similar (same screen, just scrolled)
    assert fp_initial.is_similar_to(fp_scrolled), \
        f"Expected similar screens, got {similarity:.2%} similarity"
    
    # But not identical (different viewport)
    assert fp_initial.semantic_hash != fp_scrolled.semantic_hash, \
        "Expected different hashes for different viewports"
    
    print("✅ PASS: Scroll position changes hash but screens are similar\n")
    return True


def test_dynamic_content_invariance():
    """Test that dynamic content (timestamps, prices) doesn't break fingerprint."""
    print("=" * 70)
    print("TEST 3: Dynamic Content Invariance")
    print("=" * 70)
    
    activity = "ChatActivity"
    
    # Chat screen at 10:30 AM
    xml_1030 = '''
    <hierarchy>
        <node content-desc="chat_header" />
        <node content-desc="message_list" scrollable="true" />
        <node text="10:30 AM" />  <!-- Dynamic timestamp -->
        <node content-desc="send_button" clickable="true" />
        <node content-desc="text_input" />
    </hierarchy>
    '''
    
    # Same screen at 10:31 AM (timestamp changed)
    xml_1031 = '''
    <hierarchy>
        <node content-desc="chat_header" />
        <node content-desc="message_list" scrollable="true" />
        <node text="10:31 AM" />  <!-- Changed timestamp -->
        <node content-desc="send_button" clickable="true" />
        <node content-desc="text_input" />
    </hierarchy>
    '''
    
    fp_1030 = SemanticFingerprint.from_xml(xml_1030, activity)
    fp_1031 = SemanticFingerprint.from_xml(xml_1031, activity)
    
    print(f"10:30 AM hash: {fp_1030.semantic_hash}")
    print(f"10:31 AM hash: {fp_1031.semantic_hash}")
    
    # Should be IDENTICAL (timestamps don't affect content-desc)
    assert fp_1030.semantic_hash == fp_1031.semantic_hash, \
        "Expected identical hashes - timestamps shouldn't affect fingerprint"
    
    print("✅ PASS: Dynamic text content doesn't affect semantic fingerprint\n")
    return True


def test_modal_handling():
    """Test that modal/drawer state is detected but handled gracefully."""
    print("=" * 70)
    print("TEST 4: Modal/Drawer Handling")
    print("=" * 70)
    
    activity = "MainActivity"
    
    # Normal state - more elements to establish base
    xml_normal = '''
    <hierarchy>
        <node content-desc="header" />
        <node content-desc="menu_button" clickable="true" />
        <node content-desc="content_area" />
        <node content-desc="footer" />
    </hierarchy>
    '''
    
    # Drawer open - reveals nav items but keeps base elements
    xml_drawer_open = '''
    <hierarchy>
        <node content-desc="header" />
        <node content-desc="menu_button" clickable="true" />
        <node content-desc="content_area" />
        <node content-desc="footer" />
        <node content-desc="nav_home" clickable="true" />
        <node content-desc="nav_settings" clickable="true" />
    </hierarchy>
    '''
    
    fp_normal = SemanticFingerprint.from_xml(xml_normal, activity)
    fp_drawer = SemanticFingerprint.from_xml(xml_drawer_open, activity)
    
    print(f"Normal state hash: {fp_normal.semantic_hash}")
    print(f"Drawer open hash: {fp_drawer.semantic_hash}")
    
    similarity = fp_normal.jaccard_similarity(fp_drawer)
    print(f"Similarity: {similarity:.2%}")
    
    # With 4 base elements + 2 new = 6 total, intersection = 4, similarity = 4/6 = 66%
    # Use lower threshold (0.5) for modal/drawer detection
    is_similar = fp_normal.is_similar_to(fp_drawer, threshold=0.5)
    assert is_similar, \
        f"Expected similar screens with threshold 0.5, got {similarity:.2%}"
    assert fp_normal.semantic_hash != fp_drawer.semantic_hash, \
        "Expected different hashes (drawer adds new elements)"
    
    # Check new elements
    new_elements = fp_normal.get_new_elements(fp_drawer)
    print(f"New elements when drawer opens: {new_elements}")
    
    assert "nav_home" in new_elements
    assert "nav_settings" in new_elements
    
    print("✅ PASS: Modal/drawer state detected but recognized as same screen\n")
    return True


def test_different_screens_detected():
    """Test that genuinely different screens are detected as different."""
    print("=" * 70)
    print("TEST 5: Different Screens Detection")
    print("=" * 70)
    
    # Home screen
    xml_home = '''
    <hierarchy>
        <node content-desc="home_header" />
        <node content-desc="featured_products" />
        <node content-desc="view_all_button" clickable="true" />
    </hierarchy>
    '''
    
    # Settings screen (completely different)
    xml_settings = '''
    <hierarchy>
        <node content-desc="settings_header" />
        <node content-desc="dark_mode_toggle" />
        <node content-desc="notifications_checkbox" />
        <node content-desc="logout_button" clickable="true" />
    </hierarchy>
    '''
    
    fp_home = SemanticFingerprint.from_xml(xml_home, "HomeActivity")
    fp_settings = SemanticFingerprint.from_xml(xml_settings, "SettingsActivity")
    
    print(f"Home screen hash: {fp_home.semantic_hash}")
    print(f"Settings screen hash: {fp_settings.semantic_hash}")
    
    similarity = fp_home.jaccard_similarity(fp_settings)
    print(f"Similarity: {similarity:.2%}")
    
    # Should NOT be similar
    assert not fp_home.is_similar_to(fp_settings), \
        f"Expected different screens, got {similarity:.2%} similarity"
    
    print("✅ PASS: Different screens correctly identified as different\n")
    return True


def test_screen_registry():
    """Test the SemanticScreenRegistry for crawling."""
    print("=" * 70)
    print("TEST 6: Screen Registry for Crawling")
    print("=" * 70)
    
    # Use lower threshold (0.5) for scroll detection
    registry = SemanticScreenRegistry(similarity_threshold=0.5)
    activity = "ProductActivity"
    
    # Simulate crawling: visit same screen multiple times with scrolls
    # Need at least 50% overlap for similarity
    # Base elements: header, search, footer (always present)
    visits = [
        # First visit - top of screen (6 elements: 3 base + 3 products)
        ['header', 'search', 'footer', 'product_1', 'product_2', 'scrollable_area'],
        # Scroll down - 5/6 overlap = 83% similar (header, search, footer, product_2, scrollable_area)
        ['header', 'search', 'footer', 'product_2', 'product_3', 'scrollable_area'],
        # Scroll down more - 5/6 overlap = 83% similar
        ['header', 'search', 'footer', 'product_3', 'product_4', 'scrollable_area'],
        # Back to top - 6/6 overlap = 100% similar
        ['header', 'search', 'footer', 'product_1', 'product_2', 'scrollable_area'],
    ]
    
    new_screen_count = 0
    for i, content_descs in enumerate(visits):
        # Build XML
        xml = '<hierarchy>' + ''.join(
            f'<node content-desc="{cd}" />' for cd in content_descs
        ) + '</hierarchy>'
        
        fp = SemanticFingerprint.from_xml(xml, activity)
        screen_hash, is_new = registry.register(fp)
        
        if is_new:
            new_screen_count += 1
            print(f"Visit {i+1}: NEW screen registered (hash: {screen_hash[:8]}...)")
        else:
            visit_count = registry.get_visit_count(fp)
            print(f"Visit {i+1}: Same screen (visit #{visit_count})")
    
    print(f"\nTotal 'new' screens detected: {new_screen_count}")
    print(f"Expected: 1 (all visits are same screen)")
    
    # All visits should be recognized as same screen
    assert new_screen_count == 1, \
        f"Expected 1 unique screen, got {new_screen_count}"
    
    stats = registry.get_coverage_stats()
    print(f"\nRegistry stats: {stats}")
    
    print("✅ PASS: Registry correctly tracks unique screens\n")
    return True


def test_convenience_functions():
    """Test the convenience functions."""
    print("=" * 70)
    print("TEST 7: Convenience Functions")
    print("=" * 70)
    
    activity = "TestActivity"
    xml = '''
    <hierarchy>
        <node content-desc="header" />
        <node content-desc="button1" clickable="true" />
        <node content-desc="button2" clickable="true" />
        <node content-desc="footer" />
    </hierarchy>
    '''
    
    # Test semantic_screen_fingerprint()
    hash1 = semantic_screen_fingerprint(xml, activity)
    hash2 = semantic_screen_fingerprint(xml, activity)
    
    print(f"Fingerprint: {hash1}")
    assert hash1 == hash2, "Expected deterministic hash"
    assert len(hash1) == 16, f"Expected 16-char hash, got {len(hash1)}"
    
    # Test are_screens_similar() - need 70% overlap
    # Original: header, button1, button2, footer (4 elements)
    # Similar: header, button1, button2, button3, footer (5 elements)
    # Intersection: 4, Union: 5, Similarity: 4/5 = 80% > 70%
    xml_similar = '''
    <hierarchy>
        <node content-desc="header" />
        <node content-desc="button1" clickable="true" />
        <node content-desc="button2" clickable="true" />
        <node content-desc="button3" clickable="true" />
        <node content-desc="footer" />
    </hierarchy>
    '''
    
    similar = are_screens_similar(xml, activity, xml_similar, activity)
    print(f"Screens similar: {similar}")
    assert similar, "Expected similar screens (80% overlap)"
    
    # Test not similar - different activity
    xml_different = '''
    <hierarchy>
        <node content-desc="header" />
        <node content-desc="button1" clickable="true" />
        <node content-desc="button2" clickable="true" />
        <node content-desc="footer" />
    </hierarchy>
    '''
    
    not_similar = are_screens_similar(xml, activity, xml_different, "OtherActivity")
    print(f"Different activities similar: {not_similar}")
    assert not not_similar, "Expected different activities to not be similar"
    
    print("✅ PASS: Convenience functions work correctly\n")
    return True


def test_state_normalization():
    """Test that state indicators (checked/selected) are normalized."""
    print("=" * 70)
    print("TEST 8: State Normalization (checked/selected filtering)")
    print("=" * 70)
    
    activity = "SettingsActivity"
    
    # Screen with checkbox unchecked
    xml_unchecked = '''
    <hierarchy>
        <node content-desc="header" />
        <node content-desc="notifications_checkbox (unchecked)" checkable="true" />
        <node content-desc="dark_mode_checkbox (unchecked)" checkable="true" />
        <node content-desc="save_button" clickable="true" />
    </hierarchy>
    '''
    
    # Same screen with checkbox checked
    xml_checked = '''
    <hierarchy>
        <node content-desc="header" />
        <node content-desc="notifications_checkbox (checked)" checkable="true" />
        <node content-desc="dark_mode_checkbox (checked)" checkable="true" />
        <node content-desc="save_button" clickable="true" />
    </hierarchy>
    '''
    
    fp_unchecked = SemanticFingerprint.from_xml(xml_unchecked, activity)
    fp_checked = SemanticFingerprint.from_xml(xml_checked, activity)
    
    print(f"Unchecked state hash: {fp_unchecked.semantic_hash}")
    print(f"Checked state hash: {fp_checked.semantic_hash}")
    print(f"Content descs (unchecked): {sorted(fp_unchecked.content_descs)}")
    print(f"Content descs (checked): {sorted(fp_checked.content_descs)}")
    
    # Hashes should be IDENTICAL after normalization
    assert fp_unchecked.semantic_hash == fp_checked.semantic_hash, \
        "Expected same hash after state normalization"
    
    # Content descs should be normalized (state indicators removed)
    assert "notifications_checkbox" in fp_unchecked.content_descs
    assert "dark_mode_checkbox" in fp_unchecked.content_descs
    assert "notifications_checkbox (unchecked)" not in fp_unchecked.content_descs
    assert "notifications_checkbox (checked)" not in fp_checked.content_descs
    
    print("✅ PASS: State indicators correctly normalized\n")
    return True


def test_selected_option_normalization():
    """Test that selected options produce same hash regardless of selection."""
    print("=" * 70)
    print("TEST 9: Selected Option Normalization")
    print("=" * 70)
    
    activity = "FormActivity"
    
    # Radio button group - first option selected
    xml_option1 = '''
    <hierarchy>
        <node content-desc="gender_label" />
        <node content-desc="selected: Male" checkable="true" />
        <node content-desc="Female" checkable="true" />
        <node content-desc="Other" checkable="true" />
        <node content-desc="submit_button" clickable="true" />
    </hierarchy>
    '''
    
    # Same radio button group - second option selected
    xml_option2 = '''
    <hierarchy>
        <node content-desc="gender_label" />
        <node content-desc="Male" checkable="true" />
        <node content-desc="selected: Female" checkable="true" />
        <node content-desc="Other" checkable="true" />
        <node content-desc="submit_button" clickable="true" />
    </hierarchy>
    '''
    
    fp1 = SemanticFingerprint.from_xml(xml_option1, activity)
    fp2 = SemanticFingerprint.from_xml(xml_option2, activity)
    
    print(f"Option 1 selected hash: {fp1.semantic_hash}")
    print(f"Option 2 selected hash: {fp2.semantic_hash}")
    print(f"Content descs (option 1): {sorted(fp1.content_descs)}")
    print(f"Content descs (option 2): {sorted(fp2.content_descs)}")
    
    # Hashes should be IDENTICAL - same form, different selection
    assert fp1.semantic_hash == fp2.semantic_hash, \
        "Expected same hash regardless of which option is selected"
    
    # Both should have normalized "Male" and "Female" (without "selected:" prefix)
    assert "Male" in fp1.content_descs
    assert "Female" in fp1.content_descs
    assert "selected: Male" not in fp1.content_descs
    assert "selected: Female" not in fp2.content_descs
    
    print("✅ PASS: Selected options correctly normalized\n")
    return True


def test_input_field_normalization():
    """Test that input fields with different text values produce same hash."""
    print("=" * 70)
    print("TEST 10: Input Field Normalization")
    print("=" * 70)
    
    activity = "LoginActivity"
    
    # Login form - empty
    xml_empty = '''
    <hierarchy>
        <node content-desc="email_input" />
        <node content-desc="password_input" password="true" />
        <node content-desc="login_button" clickable="true" />
    </hierarchy>
    '''
    
    # Same login form - with text entered (should be filtered out)
    # Note: In real Appium XML, text would be in the 'text' attribute which we already ignore
    # But if content-desc includes the value, we should normalize it
    xml_filled = '''
    <hierarchy>
        <node content-desc="email_input" text="user@example.com" />
        <node content-desc="password_input" password="true" text="secret123" />
        <node content-desc="login_button" clickable="true" />
    </hierarchy>
    '''
    
    fp_empty = SemanticFingerprint.from_xml(xml_empty, activity)
    fp_filled = SemanticFingerprint.from_xml(xml_filled, activity)
    
    print(f"Empty form hash: {fp_empty.semantic_hash}")
    print(f"Filled form hash: {fp_filled.semantic_hash}")
    
    # Password fields should be excluded entirely
    assert fp_empty.semantic_hash == fp_filled.semantic_hash, \
        "Expected same hash - password fields filtered, text attribute ignored"
    
    print("✅ PASS: Input fields correctly handled\n")
    return True


def test_empty_and_malformed_xml():
    """Test handling of edge cases."""
    print("=" * 70)
    print("TEST 8: Edge Cases (Empty/Malformed XML)")
    print("=" * 70)
    
    activity = "TestActivity"
    
    # Empty XML
    fp_empty = SemanticFingerprint.from_xml("", activity)
    print(f"Empty XML hash: {fp_empty.semantic_hash}")
    assert fp_empty.semantic_hash != ""
    
    # Malformed XML
    fp_malformed = SemanticFingerprint.from_xml("<not valid xml", activity)
    print(f"Malformed XML hash: {fp_malformed.semantic_hash}")
    assert fp_malformed.semantic_hash != ""
    
    # No content-desc
    xml_no_desc = '''
    <hierarchy>
        <node text="Hello" />
        <node class="android.widget.Button" />
    </hierarchy>
    '''
    fp_no_desc = SemanticFingerprint.from_xml(xml_no_desc, activity)
    print(f"No content-desc hash: {fp_no_desc.semantic_hash}")
    print(f"  Content descs: {fp_no_desc.content_descs}")
    print(f"  Resource IDs: {fp_no_desc.resource_ids}")
    
    print("✅ PASS: Edge cases handled gracefully\n")
    return True


def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("SEMANTIC FINGERPRINTING TESTS")
    print("=" * 70 + "\n")
    
    tests = [
        ("Real XML Dumps", test_real_xml_dumps),
        ("Scroll Invariance", test_scroll_invariance),
        ("Dynamic Content", test_dynamic_content_invariance),
        ("Modal Handling", test_modal_handling),
        ("Different Screens", test_different_screens_detected),
        ("Screen Registry", test_screen_registry),
        ("Convenience Functions", test_convenience_functions),
        ("State Normalization", test_state_normalization),
        ("Selected Option Normalization", test_selected_option_normalization),
        ("Input Field Normalization", test_input_field_normalization),
        ("Edge Cases", test_empty_and_malformed_xml),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except AssertionError as e:
            print(f"\n❌ {name} FAILED: {e}\n")
            failed += 1
        except Exception as e:
            print(f"\n💥 {name} ERROR: {e}\n")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
