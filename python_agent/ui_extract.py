from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List, Optional, Set, Tuple


def iter_xml_elements(page_source: str) -> Iterable[ET.Element]:
    if not page_source:
        return []
    try:
        root = ET.fromstring(page_source)
    except Exception:
        return []
    return root.iter()


def extract_clickable_accessibility_ids(page_source: str) -> List[str]:
    ids: Set[str] = set()
    for el in iter_xml_elements(page_source):
        if el.attrib.get("clickable") != "true":
            continue
        if el.attrib.get("enabled") == "false":
            continue
        val = (el.attrib.get("content-desc") or "").strip()
        if val:
            ids.add(val)
    out = [x for x in ids if len(x) <= 80]
    out.sort()
    return out


def extract_clickable_resource_ids(page_source: str) -> List[str]:
    ids: Set[str] = set()
    for el in iter_xml_elements(page_source):
        if el.attrib.get("clickable") != "true":
            continue
        if el.attrib.get("enabled") == "false":
            continue
        rid = (el.attrib.get("resource-id") or "").strip()
        if rid:
            ids.add(rid)
    out = list(ids)
    out.sort()
    return out


def extract_clickable_texts(page_source: str) -> List[str]:
    texts: Set[str] = set()
    for el in iter_xml_elements(page_source):
        if el.attrib.get("clickable") != "true":
            continue
        if el.attrib.get("enabled") == "false":
            continue
        txt = (el.attrib.get("text") or "").strip()
        if txt and len(txt) <= 40:
            texts.add(txt)
    out = list(texts)
    out.sort()
    return out


def extract_input_fields(page_source: str) -> List[dict]:
    """Return a list of input/editable fields with their identifiers and bounds."""
    fields: List[dict] = []
    for el in iter_xml_elements(page_source):
        class_name = el.attrib.get("class", "")
        is_edit = (
            "EditText" in class_name
            or el.attrib.get("focusable") == "true"
            and el.attrib.get("clickable") == "true"
            and "input" in (el.attrib.get("content-desc") or "").lower()
        )
        if not is_edit:
            continue
        acc_id = (el.attrib.get("content-desc") or "").strip()
        res_id = (el.attrib.get("resource-id") or "").strip()
        text_val = (el.attrib.get("text") or "").strip()
        hint = (el.attrib.get("hint") or text_val or "").strip()
        # Parse bounds for coordinate-based fallback
        bounds_str = el.attrib.get("bounds", "")
        bounds = _parse_bounds(bounds_str)
        cx, cy = _bounds_center(bounds) if bounds else (None, None)
        if acc_id or res_id or bounds:
            fields.append({
                "accessibility_id": acc_id,
                "resource_id": res_id,
                "hint": hint,
                "locator_type": "accessibility_id" if acc_id else "resource_id",
                "locator_value": acc_id or res_id,
                "cx": cx,
                "cy": cy,
                "bounds": bounds_str,
            })
    return fields


def extract_scrollable_containers(page_source: str) -> bool:
    """Return True if the current screen has scrollable content."""
    for el in iter_xml_elements(page_source):
        if el.attrib.get("scrollable") == "true":
            return True
        class_name = el.attrib.get("class", "")
        if "ScrollView" in class_name or "RecyclerView" in class_name or "ListView" in class_name:
            return True
    return False


def extract_all_interactive_elements(page_source: str) -> List[dict]:
    """Return ALL interactive elements with full info for comprehensive testing."""
    elements: List[dict] = []
    seen: Set[str] = set()
    for el in iter_xml_elements(page_source):
        if el.attrib.get("enabled") == "false":
            continue
        clickable = el.attrib.get("clickable") == "true"
        checkable = el.attrib.get("checkable") == "true"
        long_clickable = el.attrib.get("long-clickable") == "true"
        scrollable = el.attrib.get("scrollable") == "true"
        if not (clickable or checkable or long_clickable or scrollable):
            continue
        acc_id = (el.attrib.get("content-desc") or "").strip()
        res_id = (el.attrib.get("resource-id") or "").strip()
        text = (el.attrib.get("text") or "").strip()
        key = acc_id or res_id or text
        if not key or key in seen:
            continue
        seen.add(key)
        elements.append({
            "class": el.attrib.get("class", ""),
            "accessibility_id": acc_id,
            "resource_id": res_id,
            "text": text,
            "clickable": clickable,
            "long_clickable": long_clickable,
            "checkable": checkable,
            "scrollable": scrollable,
            "bounds": el.attrib.get("bounds", ""),
        })
    return elements

# ── Bounds-based element lookup ──────────────────────────────────

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def _parse_bounds(bounds_str: str) -> Optional[Tuple[int, int, int, int]]:
    """Parse '[x1,y1][x2,y2]' into (x1, y1, x2, y2)."""
    m = _BOUNDS_RE.match(bounds_str)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return None


def _bounds_center(bounds: Tuple[int, int, int, int]) -> Tuple[int, int]:
    x1, y1, x2, y2 = bounds
    return (x1 + x2) // 2, (y1 + y2) // 2


def find_element_bounds(
    page_source: str,
    locator_type: str,
    locator_value: str,
) -> Optional[Tuple[int, int]]:
    """
    Search the XML page source for an element matching the locator and
    return the (center_x, center_y) of its bounds.

    Works even when Appium ``find_element`` fails (WebView elements,
    stale references, etc.).
    """
    if not page_source or not locator_value:
        return None

    attr_map = {
        "accessibility_id": "content-desc",
        "resource_id": "resource-id",
        "text": "text",
    }
    primary_attr = attr_map.get(locator_type, "resource-id")

    for el in iter_xml_elements(page_source):
        val = (el.attrib.get(primary_attr) or "").strip()
        # Match exact or suffix (resource-id may be full-qualified)
        if val == locator_value or val.endswith("/" + locator_value):
            bounds = _parse_bounds(el.attrib.get("bounds", ""))
            if bounds:
                return _bounds_center(bounds)

    # Second pass: fuzzy match across all ID attributes
    for el in iter_xml_elements(page_source):
        for attr in ("resource-id", "content-desc", "text"):
            val = (el.attrib.get(attr) or "").strip()
            if val and (val == locator_value or locator_value in val):
                bounds = _parse_bounds(el.attrib.get("bounds", ""))
                if bounds:
                    return _bounds_center(bounds)

    return None


def find_input_field_bounds(page_source: str) -> List[Dict[str, any]]:
    """
    Return all EditText / input elements with their center coordinates.

    Each dict: { 'cx', 'cy', 'hint', 'resource_id', 'accessibility_id', 'bounds' }
    """
    results: List[Dict[str, any]] = []
    for el in iter_xml_elements(page_source):
        class_name = el.attrib.get("class", "")
        if "EditText" not in class_name:
            continue
        bounds = _parse_bounds(el.attrib.get("bounds", ""))
        if not bounds:
            continue
        cx, cy = _bounds_center(bounds)
        results.append({
            "cx": cx,
            "cy": cy,
            "hint": (el.attrib.get("hint") or el.attrib.get("text") or "").strip(),
            "resource_id": (el.attrib.get("resource-id") or "").strip(),
            "accessibility_id": (el.attrib.get("content-desc") or "").strip(),
            "bounds": el.attrib.get("bounds", ""),
        })
    return results