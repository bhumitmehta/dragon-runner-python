"""
Test Action-Based Coverage Model
=================================

Demonstrates how action-based coverage handles edge cases that break hash-based approaches.
"""

import sys
sys.path.insert(0, 'c:\\Users\\20092\\Desktop\\prooject\\ai-projects\\dragon-runner-python\\python_agent')

from action_coverage import ActionCoverageTracker, Action


def test_basic_coverage():
    """Test basic action tracking."""
    print("=" * 60)
    print("TEST 1: Basic Action Coverage")
    print("=" * 60)
    
    tracker = ActionCoverageTracker()
    
    # Simulate a screen with 2 buttons
    xml = '''
    <hierarchy>
        <button resource-id="com.app:id/login" text="Login" clickable="true" />
        <button resource-id="com.app:id/signup" text="Sign Up" clickable="true" />
    </hierarchy>
    '''
    
    activity = "MainActivity"
    actions = tracker.get_available_actions(xml, activity)
    
    print(f"Activity: {activity}")
    print(f"Available actions: {len(actions)}")
    for action in actions:
        print(f"  - {action.signature} ({action.element_type})")
    
    unexplored = tracker.get_unexplored_actions(actions)
    print(f"Unexplored: {len(unexplored)}")
    
    # Mark one as explored
    login_action = next(a for a in actions if "login" in a.element_id.lower())
    tracker.mark_explored(login_action)
    
    unexplored = tracker.get_unexplored_actions(actions)
    print(f"After exploring 'login', unexplored: {len(unexplored)}")
    
    assert len(unexplored) == 1
    print("✅ PASS\n")


def test_scroll_handling():
    """Test that scroll doesn't create false 'new screen'."""
    print("=" * 60)
    print("TEST 2: Scroll Handling (Hash Breaks, Actions Work)")
    print("=" * 60)
    
    tracker = ActionCoverageTracker()
    activity = "ProductListActivity"
    
    # Screen 1: Initial view (items 1-3 visible)
    xml1 = '''
    <hierarchy>
        <list resource-id="com.app:id/product_list" scrollable="true">
            <item resource-id="com.app:id/product_1" text="Product 1" clickable="true" />
            <item resource-id="com.app:id/product_2" text="Product 2" clickable="true" />
            <item resource-id="com.app:id/product_3" text="Product 3" clickable="true" />
        </list>
    </hierarchy>
    '''
    
    # Screen 2: After scroll (items 2-4 visible)
    xml2 = '''
    <hierarchy>
        <list resource-id="com.app:id/product_list" scrollable="true">
            <item resource-id="com.app:id/product_2" text="Product 2" clickable="true" />
            <item resource-id="com.app:id/product_3" text="Product 3" clickable="true" />
            <item resource-id="com.app:id/product_4" text="Product 4" clickable="true" />
        </list>
    </hierarchy>
    '''
    
    actions1 = tracker.get_available_actions(xml1, activity)
    actions2 = tracker.get_available_actions(xml2, activity)
    
    print(f"Screen 1 actions: {len(actions1)}")
    print(f"Screen 2 actions: {len(actions2)}")
    
    # Hash approach would see these as different
    # Action approach sees overlap correctly
    overlap = actions1 & actions2
    new_in_screen2 = actions2 - actions1
    
    print(f"Overlap (same actions): {len(overlap)}")
    print(f"New in screen 2: {len(new_in_screen2)}")
    
    # Explore all from screen 1
    for action in actions1:
        tracker.mark_explored(action)
    
    # Check what's left in screen 2
    unexplored = tracker.get_unexplored_actions(actions2)
    print(f"After exploring screen 1, unexplored in screen 2: {len(unexplored)}")
    
    # Should only be product_4
    assert len(unexplored) == 1
    assert any("product_4" in a.element_id for a in unexplored)
    print("✅ PASS: Scroll correctly reveals only new actions\n")


def test_modal_handling():
    """Test that modal doesn't create false 'new screen'."""
    print("=" * 60)
    print("TEST 3: Modal Handling (Hash Breaks, Actions Work)")
    print("=" * 60)
    
    tracker = ActionCoverageTracker()
    activity = "MainActivity"
    
    # Screen 1: Normal state
    xml1 = '''
    <hierarchy>
        <button resource-id="com.app:id/settings" text="Settings" clickable="true" />
        <button resource-id="com.app:id/profile" text="Profile" clickable="true" />
    </hierarchy>
    '''
    
    # Screen 2: Modal opens (same activity!)
    xml2 = '''
    <hierarchy>
        <button resource-id="com.app:id/settings" text="Settings" clickable="true" />
        <button resource-id="com.app:id/profile" text="Profile" clickable="true" />
        <dialog resource-id="com.app:id/modal">
            <button resource-id="com.app:id/modal_ok" text="OK" clickable="true" />
            <button resource-id="com.app:id/modal_cancel" text="Cancel" clickable="true" />
        </dialog>
    </hierarchy>
    '''
    
    actions1 = tracker.get_available_actions(xml1, activity)
    actions2 = tracker.get_available_actions(xml2, activity)
    
    print(f"Screen 1 (normal) actions: {len(actions1)}")
    print(f"Screen 2 (modal open) actions: {len(actions2)}")
    
    # Explore settings from screen 1
    settings = next(a for a in actions1 if "settings" in a.element_id)
    tracker.mark_explored(settings)
    
    # Modal opens - settings should still be marked as explored
    # because same activity + same element_id
    unexplored = tracker.get_unexplored_actions(actions2)
    print(f"After exploring 'settings', unexplored in modal screen: {len(unexplored)}")
    
    # Should be profile, modal_ok, modal_cancel
    assert len(unexplored) == 3
    assert any("settings" not in a.element_id for a in unexplored)
    print("✅ PASS: Modal correctly shares action namespace\n")


def test_drawer_handling():
    """Test that drawer open/closed doesn't matter."""
    print("=" * 60)
    print("TEST 4: Drawer Handling (Same Activity = Same Actions)")
    print("=" * 60)
    
    tracker = ActionCoverageTracker()
    activity = "MainActivity"
    
    # Drawer closed
    xml_closed = '''
    <hierarchy>
        <button resource-id="com.app:id/menu_button" content-desc="Open Menu" clickable="true" />
        <text resource-id="com.app:id/content" text="Main Content" />
    </hierarchy>
    '''
    
    # Drawer open - reveals nav items
    xml_open = '''
    <hierarchy>
        <button resource-id="com.app:id/menu_button" content-desc="Close Menu" clickable="true" />
        <navigation resource-id="com.app:id/nav_drawer">
            <item resource-id="com.app:id/nav_home" text="Home" clickable="true" />
            <item resource-id="com.app:id/nav_settings" text="Settings" clickable="true" />
            <item resource-id="com.app:id/nav_about" text="About" clickable="true" />
        </navigation>
    </hierarchy>
    '''
    
    actions_closed = tracker.get_available_actions(xml_closed, activity)
    actions_open = tracker.get_available_actions(xml_open, activity)
    
    print(f"Drawer closed actions: {len(actions_closed)}")
    print(f"Drawer open actions: {len(actions_open)}")
    
    # Explore menu button in closed state
    menu = next(a for a in actions_closed if "menu" in a.element_id)
    tracker.mark_explored(menu)
    
    # Open drawer - menu button should still be explored
    unexplored_open = tracker.get_unexplored_actions(actions_open)
    print(f"After exploring menu button, unexplored with drawer open: {len(unexplored_open)}")
    
    # Menu button should not be in unexplored
    assert not any("menu" in a.element_id for a in unexplored_open)
    print("✅ PASS: Drawer state doesn't affect action tracking\n")


def test_timestamp_independence():
    """Test that timestamps don't affect action extraction."""
    print("=" * 60)
    print("TEST 5: Timestamp Independence")
    print("=" * 60)
    
    tracker = ActionCoverageTracker()
    activity = "ChatActivity"
    
    # Screen with timestamp
    xml1 = '''
    <hierarchy>
        <text resource-id="com.app:id/timestamp" text="10:30 AM" />
        <button resource-id="com.app:id/send" text="Send" clickable="true" />
        <button resource-id="com.app:id/attach" text="Attach" clickable="true" />
    </hierarchy>
    '''
    
    # Same screen, different timestamp
    xml2 = '''
    <hierarchy>
        <text resource-id="com.app:id/timestamp" text="10:31 AM" />
        <button resource-id="com.app:id/send" text="Send" clickable="true" />
        <button resource-id="com.app:id/attach" text="Attach" clickable="true" />
    </hierarchy>
    '''
    
    actions1 = tracker.get_available_actions(xml1, activity)
    actions2 = tracker.get_available_actions(xml2, activity)
    
    print(f"Screen 1 actions: {len(actions1)}")
    print(f"Screen 2 actions: {len(actions2)}")
    
    # Actions should be identical (timestamps aren't clickable)
    assert actions1 == actions2
    print("✅ PASS: Timestamps don't create different action sets\n")


def test_coverage_stats():
    """Test coverage statistics reporting."""
    print("=" * 60)
    print("TEST 6: Coverage Statistics")
    print("=" * 60)
    
    tracker = ActionCoverageTracker()
    
    # Simulate exploring multiple activities
    activities_data = [
        ("MainActivity", ['btn1', 'btn2', 'btn3']),
        ("SettingsActivity", ['option1', 'option2']),
        ("ProfileActivity", ['edit', 'save', 'cancel']),
    ]
    
    for activity, buttons in activities_data:
        xml = '<hierarchy>'
        for btn in buttons:
            xml += f'<button resource-id="com.app:id/{btn}" clickable="true" />'
        xml += '</hierarchy>'
        
        actions = tracker.get_available_actions(xml, activity)
        
        # Explore half the actions
        for i, action in enumerate(actions):
            if i % 2 == 0:
                tracker.mark_explored(action)
    
    stats = tracker.get_coverage_stats()
    print(f"Total explored: {stats['total_explored']}")
    print(f"Activities seen: {stats['activities_seen']}")
    print(f"By activity: {stats['by_activity']}")
    
    # Check individual activity coverage
    for activity, _ in activities_data:
        coverage = tracker.get_activity_coverage(activity)
        print(f"\n{coverage['activity']}:")
        print(f"  Total: {coverage['total_actions']}")
        print(f"  Explored: {coverage['explored']}")
        print(f"  Coverage: {coverage['coverage_percent']:.1f}%")
    
    print("\n✅ PASS\n")


def test_loop_detection():
    """Test action loop detection."""
    print("=" * 60)
    print("TEST 7: Loop Detection")
    print("=" * 60)
    
    tracker = ActionCoverageTracker()
    
    # Simulate action history
    actions = [
        Action("MainActivity", "btn1", "button"),
        Action("MainActivity", "btn2", "button"),
        Action("MainActivity", "btn1", "button"),  # Repeat
        Action("MainActivity", "btn2", "button"),  # Repeat
        Action("MainActivity", "btn1", "button"),  # Repeat - loop!
    ]
    
    is_loop = tracker.detect_action_loop(actions, window=8)
    print(f"Actions: {[a.signature for a in actions]}")
    print(f"Loop detected: {is_loop}")
    
    assert is_loop == True
    
    # No loop case
    actions_no_loop = [
        Action("MainActivity", "btn1", "button"),
        Action("MainActivity", "btn2", "button"),
        Action("SettingsActivity", "option1", "button"),
        Action("ProfileActivity", "edit", "input"),
    ]
    
    is_loop = tracker.detect_action_loop(actions_no_loop, window=8)
    print(f"\nNo-loop actions: {[a.signature for a in actions_no_loop]}")
    print(f"Loop detected: {is_loop}")
    
    assert is_loop == False
    print("✅ PASS\n")


def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("ACTION-BASED COVERAGE TESTS")
    print("=" * 60 + "\n")
    
    try:
        test_basic_coverage()
        test_scroll_handling()
        test_modal_handling()
        test_drawer_handling()
        test_timestamp_independence()
        test_coverage_stats()
        test_loop_detection()
        
        print("=" * 60)
        print("ALL TESTS PASSED ✅")
        print("=" * 60)
        return True
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return False
    except Exception as e:
        print(f"\n💥 ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
