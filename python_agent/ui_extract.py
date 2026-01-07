from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Iterable, List, Set


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
