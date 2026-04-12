from __future__ import annotations

import sys

sys.path.insert(0, 'c:\\Users\\20092\\Desktop\\prooject\\ai-projects\\dragon-runner-python\\python_agent')

from ui_extract import (
    Bounds,
    ElementExtractor,
    ScreenAnalyzer,
    extract_all_interactive_elements,
    extract_clickable_accessibility_ids,
    extract_clickable_resource_ids,
    extract_clickable_texts,
    extract_input_fields,
)
from semantic_fingerprint import are_screens_similar, compute_semantic_fingerprint


SIMPLE_XML = """
<hierarchy>
    <node class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
        <node class="android.widget.TextView" text="Home" bounds="[32,40][220,100]" />
        <node class="android.widget.Button" content-desc="login_button" clickable="true" enabled="true" bounds="[40,220][300,320]" />
        <node class="android.widget.TextView" text="Buy now" clickable="true" enabled="true" bounds="[40,360][300,430]" />
        <node class="android.widget.EditText" resource-id="com.demo:id/email" hint="Email" bounds="[40,500][600,580]" />
    </node>
</hierarchy>
"""


VARIANT_XML = """
<hierarchy>
    <node class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
        <node class="android.widget.TextView" text="Home" bounds="[32,40][220,100]" />
        <node class="android.widget.Button" content-desc="login_button" clickable="true" enabled="true" bounds="[40,220][300,320]" />
        <node class="android.widget.TextView" text="Buy now" clickable="true" enabled="true" bounds="[40,360][300,430]" />
        <node class="android.widget.EditText" resource-id="com.demo:id/email" hint="Email" text="12:45 PM" bounds="[40,500][600,580]" />
    </node>
</hierarchy>
"""


DIFFERENT_XML = """
<hierarchy>
    <node class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
        <node class="android.widget.TextView" text="Settings" bounds="[32,40][260,100]" />
        <node class="android.widget.Switch" content-desc="notifications" clickable="true" enabled="true" bounds="[40,220][500,320]" />
    </node>
</hierarchy>
"""


OVERLAY_XML = """
<hierarchy>
    <node class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
        <node class="android.widget.Button" content-desc="base_cta" clickable="true" enabled="true" bounds="[80,1450][500,1560]" />
        <node class="android.app.Dialog" bounds="[160,520][920,1260]">
            <node class="android.widget.TextView" text="Permission required" bounds="[220,620][860,700]" />
            <node class="android.widget.Button" text="Allow" clickable="true" enabled="true" bounds="[240,1040][520,1140]" />
            <node class="android.widget.Button" text="Deny" clickable="true" enabled="true" bounds="[560,1040][840,1140]" />
        </node>
    </node>
</hierarchy>
"""


def test_bounds_quantize_and_overlap() -> None:
    left = Bounds(11, 19, 101, 209)
    right = Bounds(50, 100, 140, 260)

    assert left.quantize(10) == Bounds(10, 10, 100, 200)
    assert left.overlaps(right)
    assert left.contains_point(20, 20)


def test_legacy_extractor_api_still_works() -> None:
    assert extract_clickable_accessibility_ids(SIMPLE_XML) == ["login_button"]
    assert extract_clickable_resource_ids(SIMPLE_XML) == []
    assert extract_clickable_texts(SIMPLE_XML) == ["Buy now"]

    fields = extract_input_fields(SIMPLE_XML)
    assert len(fields) == 1
    assert fields[0]["resource_id"] == "com.demo:id/email"

    interactive = extract_all_interactive_elements(SIMPLE_XML)
    assert len(interactive) == 3


def test_screen_analyzer_detects_variant_vs_different() -> None:
    analyzer = ScreenAnalyzer()
    same_result = analyzer.compare_screens(SIMPLE_XML, VARIANT_XML, activity1="HomeActivity", activity2="HomeActivity")
    different_result = analyzer.compare_screens(SIMPLE_XML, DIFFERENT_XML, activity1="HomeActivity", activity2="SettingsActivity")

    assert same_result.verdict in {"SAME", "VARIANT"}
    assert same_result.similarity_score > 0.72
    assert different_result.verdict == "DIFFERENT"
    assert different_result.similarity_score < 0.72


def test_overlay_detection_prioritizes_overlay_actions() -> None:
    analyzer = ScreenAnalyzer()
    screen = analyzer.analyze_screen(OVERLAY_XML, activity_name="HomeActivity")

    assert screen.overlays
    assert screen.overlays[0].overlay_type == "PERMISSION"
    assert screen.overlays[0].blocking is True

    candidates = screen.get_action_candidates()
    candidate_labels = [candidate.primary_identifier or candidate.text for candidate in candidates]
    assert "Allow" in candidate_labels or "Deny" in candidate_labels
    assert "base_cta" not in candidate_labels


def test_element_extractor_finders_use_cached_parse() -> None:
    extractor = ElementExtractor()
    first = extractor.parser.parse(SIMPLE_XML)
    second = extractor.parser.parse(SIMPLE_XML)

    assert first is second
    assert extractor.find_element_bounds(SIMPLE_XML, "accessibility_id", "login_button") == (170, 270)


def test_semantic_fingerprint_helpers_accept_dicts_and_hashes() -> None:
    fp_one = compute_semantic_fingerprint(SIMPLE_XML, "HomeActivity")
    fp_two = compute_semantic_fingerprint(VARIANT_XML, "HomeActivity")
    fp_diff = compute_semantic_fingerprint(DIFFERENT_XML, "SettingsActivity")

    assert are_screens_similar(fp_one, fp_two)
    assert not are_screens_similar(fp_one, fp_diff)
    assert are_screens_similar(fp_one["semantic_hash"], fp_one["semantic_hash"])
