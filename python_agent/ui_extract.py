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


def _collect_child_labels(el: ET.Element) -> List[str]:
    """Collect meaningful text labels from descendants of an element.

    Used when a clickable element has no identifier of its own but its
    children contain descriptive text (e.g. product cards in a list).
    """
    labels: List[str] = []
    seen: Set[str] = set()
    for child in el.iter():
        if child is el:
            continue
        t = (child.attrib.get("text") or "").strip()
        if (
            t
            and t not in seen
            and len(t) > 1
            and len(t) <= 60
            and any(c.isalnum() for c in t)
        ):
            labels.append(t)
            seen.add(t)
    return labels


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
        else:
            # Clickable element with no direct text -- check children.
            # Common in list items (RecyclerView, ScrollView) where the
            # clickable container wraps an image + label.
            for child_text in _collect_child_labels(el):
                if len(child_text) <= 40:
                    texts.add(child_text)
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
    """Return ALL interactive elements with full info for comprehensive testing.

    For clickable elements that have no direct identifier, child text
    labels are collected and stored as ``child_labels``.  The first
    child label is used as the element's ``text`` key so it appears in
    exploration candidate lists.
    """
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
        child_labels: List[str] = []
        key = acc_id or res_id or text
        if not key and clickable:
            # Clickable element without any direct identifier -- use child text
            child_labels = _collect_child_labels(el)
            if child_labels:
                text = child_labels[0]  # use first child label as primary text
                key = text
        if not key or key in seen:
            continue
        seen.add(key)
        elements.append({
            "class": el.attrib.get("class", ""),
            "accessibility_id": acc_id,
            "resource_id": res_id,
            "text": text,
            "child_labels": child_labels,
            "clickable": clickable,
            "long_clickable": long_clickable,
            "checkable": checkable,
            "scrollable": scrollable,
            "bounds": el.attrib.get("bounds", ""),
        })
    return elements

def extract_visible_texts_ordered(page_source: str) -> List[Dict[str, Any]]:
    """Extract all visible text and content-desc values sorted by Y then X coordinate.

    Returns a list of dicts with keys: text, content_desc, bounds_y, bounds_x,
    class_name.  Useful for verifying display order (e.g. sort assertions).
    """
    items: List[Dict[str, Any]] = []
    for el in iter_xml_elements(page_source):
        if el.attrib.get("displayed") == "false":
            continue
        text = (el.attrib.get("text") or "").strip()
        desc = (el.attrib.get("content-desc") or "").strip()
        if not text and not desc:
            continue
        bounds = _parse_bounds(el.attrib.get("bounds", ""))
        y = bounds[1] if bounds else 9999
        x = bounds[0] if bounds else 9999
        items.append({
            "text": text,
            "content_desc": desc,
            "bounds_y": y,
            "bounds_x": x,
            "class": el.attrib.get("class", ""),
        })
    items.sort(key=lambda i: (i["bounds_y"], i["bounds_x"]))
    return items


def extract_labelled_data_items(page_source: str) -> List[Dict[str, str]]:
    """Extract product/data items from repeated 'store item' containers.

    Looks for ViewGroup elements with content-desc="store item" or similar
    repeating patterns, and collects their child text values grouped per item.
    Returns e.g. [{"name": "Sauce Labs Fleece Jacket", "price": "$49.99"}, ...].
    """
    items: List[Dict[str, str]] = []
    try:
        root = ET.fromstring(page_source)
    except Exception:
        return items

    for el in root.iter():
        desc = (el.attrib.get("content-desc") or "").strip()
        if desc != "store item":
            continue
        item: Dict[str, str] = {}
        for child in el.iter():
            child_desc = (child.attrib.get("content-desc") or "").strip()
            child_text = (child.attrib.get("text") or "").strip()
            if child_desc == "store item text" and child_text:
                item["name"] = child_text
            elif child_desc == "store item price" and child_text:
                item["price"] = child_text
            elif child_desc == "product price" and child_text:
                item["price"] = child_text
        if item:
            # Use Y-coordinate for ordering
            bounds = _parse_bounds(el.attrib.get("bounds", ""))
            item["_y"] = str(bounds[1]) if bounds else "9999"
            items.append(item)
    # Sort by Y position to get display order
    items.sort(key=lambda i: int(i.pop("_y", "9999")))
    return items


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