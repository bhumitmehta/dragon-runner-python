from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple


_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
_VOLATILE_PATTERNS = [
    re.compile(r"\b\d{1,2}:\d{2}:\d{2}\b"),
    re.compile(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b", re.IGNORECASE),
    re.compile(r"\b\d+%\b"),
    re.compile(r"\b\d{6}\b"),
    re.compile(r"\b[a-f0-9]{32}\b", re.IGNORECASE),
    re.compile(r"\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b", re.IGNORECASE),
    re.compile(r"\btemp_\d+\b", re.IGNORECASE),
    re.compile(r"\brandom_[\w-]+\b", re.IGNORECASE),
]
_STATE_PATTERNS = [
    re.compile(r"\s*\(\s*(?:checked|unchecked|selected|unselected|on|off|enabled|disabled|focused|active|inactive)\s*\)\s*$", re.IGNORECASE),
    re.compile(r"^(?:selected|checked|enabled|disabled|focused|active|inactive):\s*", re.IGNORECASE),
    re.compile(r"\s*[✓✔☑☐●○]\s*$"),
]
_LOADING_TOKENS = {"loading", "please wait", "progress", "buffering"}
_OVERLAY_TEXT_TOKENS = {
    "allow",
    "deny",
    "permission",
    "later",
    "not now",
    "cancel",
    "ok",
    "update",
    "privacy",
    "cookie",
    "close",
}
_DIALOG_CLASS_TOKENS = ("dialog", "modal", "popup", "sheet", "alert")
_SCROLLABLE_CLASS_TOKENS = ("ScrollView", "RecyclerView", "ListView")


def _stable_hash(parts: Sequence[str]) -> str:
    payload = "::".join(part for part in parts if part)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _strip_package_prefix(value: str) -> str:
    return value.split("/")[-1] if value else ""


def _is_true(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value == "true"


@dataclass(frozen=True)
class Bounds:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    def contains_point(self, x: int, y: int) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def overlaps(self, other: "Bounds") -> bool:
        return not (
            self.x2 < other.x1
            or other.x2 < self.x1
            or self.y2 < other.y1
            or other.y2 < self.y1
        )

    def quantize(self, bucket_size: int = 10) -> "Bounds":
        def bucket(value: int) -> int:
            return (value // bucket_size) * bucket_size

        return Bounds(
            bucket(self.x1),
            bucket(self.y1),
            bucket(self.x2),
            bucket(self.y2),
        )


@dataclass
class UIElement:
    resource_id: str = ""
    accessibility_id: str = ""
    text: str = ""
    hint: str = ""
    class_name: str = ""
    package_name: str = ""
    clickable: bool = False
    long_clickable: bool = False
    checkable: bool = False
    scrollable: bool = False
    editable: bool = False
    enabled: bool = True
    visible: bool = True
    focused: bool = False
    selected: bool = False
    bounds: Optional[Bounds] = None
    z_index: int = 0
    depth: int = 0
    child_labels: List[str] = field(default_factory=list)
    parent_chain: List[str] = field(default_factory=list)
    child_count: int = 0
    text_blob: str = ""
    raw_bounds: str = ""

    @property
    def primary_identifier(self) -> str:
        return self.accessibility_id or self.resource_id or self.text or self.hint

    @property
    def interaction_types(self) -> Set[str]:
        types: Set[str] = set()
        if self.clickable:
            types.add("click")
        if self.long_clickable:
            types.add("long_click")
        if self.checkable:
            types.add("check")
        if self.scrollable:
            types.add("scroll")
        if self.editable:
            types.add("input")
        return types

    @property
    def visibility_state(self) -> str:
        if not self.visible:
            return "hidden"
        if not self.enabled:
            return "disabled"
        return "visible"

    def get_signature(self, include_volatile: bool = False) -> str:
        values = [self.class_name, self.primary_identifier, self.text_blob]
        if self.bounds:
            quantized = self.bounds if include_volatile else self.bounds.quantize()
            values.append(f"{quantized.x1},{quantized.y1},{quantized.x2},{quantized.y2}")
        return _stable_hash(values)

    def is_occluded_by(self, other: "UIElement") -> bool:
        if not self.bounds or not other.bounds:
            return False
        if other.z_index <= self.z_index or not other.visible:
            return False
        cx, cy = self.bounds.center
        return other.bounds.contains_point(cx, cy)


@dataclass
class OverlayInfo:
    overlay_type: str
    bounds: Bounds
    blocking: bool
    dismissible: bool
    priority: int
    has_backdrop: bool
    has_focus_trap: bool
    centered: bool
    small_relative_size: bool
    template_id: Optional[str] = None
    dismiss_actions: List[str] = field(default_factory=list)


@dataclass
class ScreenSignature:
    dom_structure_hash: str
    visual_hash: str
    interactive_set_hash: str
    anchor_tokens_hash: str
    timestamp: float
    element_count: int
    interactive_count: int
    has_overlays: bool
    raw_xml: Optional[str] = None
    normalized_xml: Optional[str] = None
    dom_tokens: Set[str] = field(default_factory=set)
    visual_tokens: Set[str] = field(default_factory=set)
    interactive_tokens: Set[str] = field(default_factory=set)
    anchor_tokens: Set[str] = field(default_factory=set)

    def _component_similarity(self, left: Set[str], right: Set[str]) -> float:
        if not left and not right:
            return 1.0
        if not left or not right:
            return 0.0
        return len(left & right) / max(1, len(left | right))

    def similarity_score(
        self,
        other: "ScreenSignature",
        weights: Tuple[float, float, float, float] = (0.4, 0.3, 0.2, 0.1),
    ) -> float:
        dom = self._component_similarity(self.dom_tokens, other.dom_tokens)
        visual = self._component_similarity(self.visual_tokens, other.visual_tokens)
        interactive = self._component_similarity(self.interactive_tokens, other.interactive_tokens)
        anchor = self._component_similarity(self.anchor_tokens, other.anchor_tokens)
        return (
            weights[0] * dom
            + weights[1] * visual
            + weights[2] * interactive
            + weights[3] * anchor
        )

    def is_same_screen(self, other: "ScreenSignature", threshold: float = 0.88) -> bool:
        return self.similarity_score(other) >= threshold

    def is_different_screen(self, other: "ScreenSignature", threshold: float = 0.72) -> bool:
        return self.similarity_score(other) <= threshold


@dataclass
class ComparisonResult:
    similarity_score: float
    verdict: str
    details: Dict[str, float]


@dataclass
class ParsedXML:
    elements: List[UIElement]
    screen_bounds: Optional[Bounds]
    metadata: Dict[str, Any]
    parse_error: bool = False


@dataclass
class ScreenState:
    signature: ScreenSignature
    elements: List[UIElement]
    overlays: List[OverlayInfo]
    scrollable: bool
    has_input_fields: bool
    activity_name: Optional[str]
    package_name: Optional[str]
    raw_xml: str = ""

    @cached_property
    def _visible_elements(self) -> List[UIElement]:
        return [element for element in self.elements if element.visible]

    @cached_property
    def _clickable_cache(self) -> List[UIElement]:
        return [element for element in self.elements if element.clickable and element.enabled]

    @cached_property
    def _editable_cache(self) -> List[UIElement]:
        return [element for element in self.elements if element.editable and element.enabled]

    def get_clickable_elements(self, include_disabled: bool = False) -> List[UIElement]:
        if include_disabled:
            return [element for element in self.elements if element.clickable]
        return list(self._clickable_cache)

    def get_editable_elements(self) -> List[UIElement]:
        return list(self._editable_cache)

    def get_visible_elements(self) -> List[UIElement]:
        return list(self._visible_elements)

    def find_element_by_text(self, text: str, fuzzy: bool = False) -> Optional[UIElement]:
        target = _normalize_spaces(text).lower()
        for element in self.elements:
            haystacks = [element.text, element.accessibility_id, *element.child_labels]
            for haystack in haystacks:
                normalized = _normalize_spaces(haystack).lower()
                if (fuzzy and target in normalized) or normalized == target:
                    return element
        return None

    def find_element_at_position(self, x: int, y: int) -> Optional[UIElement]:
        candidates = [element for element in self.elements if element.bounds and element.bounds.contains_point(x, y)]
        if not candidates:
            return None
        return max(candidates, key=lambda element: element.z_index)

    def get_action_candidates(
        self,
        exclude_occluded: bool = True,
        priority_order: bool = True,
    ) -> List[UIElement]:
        candidates = [
            element for element in self.elements
            if element.visible and element.enabled and element.interaction_types
        ]
        if exclude_occluded:
            checker = OcclusionChecker()
            candidates = [element for element in candidates if not checker.is_occluded(element, self.elements)]

        blocking_overlays = [overlay for overlay in self.overlays if overlay.blocking]
        if blocking_overlays:
            overlay_bounds = blocking_overlays[0].bounds
            candidates = [
                element for element in candidates
                if element.bounds and overlay_bounds.contains_point(*element.bounds.center)
            ]

        if not priority_order:
            return candidates

        def rank(element: UIElement) -> Tuple[int, int, int, int]:
            identifier = element.primary_identifier.lower()
            primary_button = int(any(token in identifier for token in ("allow", "ok", "continue", "submit", "next", "login", "close", "cancel")))
            input_field = int(element.editable)
            navigation = int(any(token in identifier for token in ("menu", "nav", "back", "home", "tab")))
            topness = -(element.bounds.y1 if element.bounds else 9999)
            return (primary_button, input_field, navigation, topness)

        return sorted(candidates, key=rank, reverse=True)


class XMLParser:
    def __init__(self, cache_size: int = 100):
        self.cache_size = max(0, cache_size)
        self._cache: Dict[str, ParsedXML] = {}
        self._cache_order: List[str] = []

    def parse(self, page_source: str) -> ParsedXML:
        if not page_source:
            return ParsedXML(elements=[], screen_bounds=None, metadata={"package": "", "activity": ""})

        key = _stable_hash([page_source])
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        try:
            root = ET.fromstring(page_source)
        except Exception:
            return ParsedXML(elements=[], screen_bounds=None, metadata={"package": "", "activity": ""}, parse_error=True)

        elements: List[UIElement] = []
        package_name = ""
        activity_name = ""

        def traverse(node: ET.Element, depth: int, parent_chain: List[str]) -> None:
            nonlocal package_name, activity_name
            attrib = node.attrib
            if not package_name:
                package_name = attrib.get("package", "")
            if not activity_name:
                activity_name = attrib.get("activity", "")

            class_name = attrib.get("class", "")
            bounds = _parse_bounds(attrib.get("bounds", ""))
            text = _normalize_spaces(attrib.get("text", ""))
            accessibility_id = _normalize_spaces(attrib.get("content-desc", ""))
            resource_id = _normalize_spaces(attrib.get("resource-id", ""))
            hint = _normalize_spaces(attrib.get("hint", "") or text)
            child_labels = _collect_child_labels(node)
            displayed = attrib.get("displayed") != "false"
            visible = displayed and (bounds is None or bounds.area > 0)
            editable = (
                "EditText" in class_name
                or (
                    _is_true(attrib.get("focusable"))
                    and _is_true(attrib.get("clickable"))
                    and "input" in accessibility_id.lower()
                )
            )
            text_blob = " | ".join(part for part in [text, accessibility_id, *child_labels] if part)

            elements.append(
                UIElement(
                    resource_id=resource_id,
                    accessibility_id=accessibility_id,
                    text=text,
                    hint=hint,
                    class_name=class_name,
                    package_name=attrib.get("package", ""),
                    clickable=_is_true(attrib.get("clickable")),
                    long_clickable=_is_true(attrib.get("long-clickable")),
                    checkable=_is_true(attrib.get("checkable")),
                    scrollable=_is_true(attrib.get("scrollable")) or any(token in class_name for token in _SCROLLABLE_CLASS_TOKENS),
                    editable=editable,
                    enabled=attrib.get("enabled") != "false",
                    visible=visible,
                    focused=_is_true(attrib.get("focused")),
                    selected=_is_true(attrib.get("selected")),
                    bounds=bounds,
                    z_index=len(elements),
                    depth=depth,
                    child_labels=child_labels,
                    parent_chain=list(parent_chain),
                    child_count=len(list(node)),
                    text_blob=text_blob,
                    raw_bounds=attrib.get("bounds", ""),
                )
            )

            next_chain = parent_chain + ([class_name] if class_name else [])
            for child in node:
                traverse(child, depth + 1, next_chain)

        traverse(root, 0, [])
        screen_bounds = _select_screen_bounds(elements)
        parsed = ParsedXML(
            elements=elements,
            screen_bounds=screen_bounds,
            metadata={"package": package_name, "activity": activity_name},
        )
        self._store(key, parsed)
        return parsed

    def _store(self, key: str, value: ParsedXML) -> None:
        if self.cache_size <= 0:
            return
        if key in self._cache:
            return
        self._cache[key] = value
        self._cache_order.append(key)
        while len(self._cache_order) > self.cache_size:
            old_key = self._cache_order.pop(0)
            self._cache.pop(old_key, None)


class Normalizer:
    animation_attrs = {
        "alpha",
        "rotation",
        "translationX",
        "translationY",
        "scaleX",
        "scaleY",
        "pivotX",
        "pivotY",
    }

    def normalize_text(self, text: str) -> str:
        value = _normalize_spaces(text)
        for pattern in _VOLATILE_PATTERNS:
            value = pattern.sub("<volatile>", value)
        for pattern in _STATE_PATTERNS:
            value = pattern.sub("", value)
        return _normalize_spaces(value)

    def normalize_identifier(self, value: str) -> str:
        return self.normalize_text(_strip_package_prefix(value)).lower()

    def normalize_element(self, element: UIElement) -> UIElement:
        child_labels = [self.normalize_text(label) for label in element.child_labels if self.normalize_text(label)]
        return replace(
            element,
            resource_id=self.normalize_identifier(element.resource_id),
            accessibility_id=self.normalize_identifier(element.accessibility_id),
            text=self.normalize_text(element.text),
            hint=self.normalize_text(element.hint),
            child_labels=child_labels,
            text_blob=self.normalize_text(element.text_blob),
        )

    def normalize_xml(self, xml_str: str) -> str:
        try:
            root = ET.fromstring(xml_str)
        except Exception:
            return ""
        for node in root.iter():
            for attr_name in list(node.attrib):
                attr_value = node.attrib.get(attr_name, "")
                if self.should_ignore_attribute(attr_name, attr_value):
                    node.attrib.pop(attr_name, None)
                    continue
                if attr_name in {"text", "content-desc", "resource-id", "hint"}:
                    node.attrib[attr_name] = self.normalize_text(attr_value)
            if node.text:
                node.text = self.normalize_text(node.text)
        return ET.tostring(root, encoding="unicode")

    def should_ignore_attribute(self, attr_name: str, attr_value: str) -> bool:
        if attr_name in self.animation_attrs:
            return True
        if attr_name in {"index"}:
            return True
        normalized = self.normalize_text(attr_value)
        return normalized == "<volatile>"


class FingerprintGenerator:
    def __init__(self, normalizer: Normalizer):
        self.normalizer = normalizer

    def generate_signature(
        self,
        elements: List[UIElement],
        metadata: Dict[str, Any],
        raw_xml: str = "",
        overlays: Optional[List[OverlayInfo]] = None,
    ) -> ScreenSignature:
        normalized_elements = [self.normalizer.normalize_element(element) for element in elements]
        dom_tokens = self._dom_tokens(normalized_elements)
        visual_tokens = self._visual_tokens(normalized_elements)
        interactive_tokens = self._interactive_tokens(normalized_elements)
        anchor_tokens = self._anchor_tokens(normalized_elements, metadata)
        return ScreenSignature(
            dom_structure_hash=_stable_hash(sorted(dom_tokens)),
            visual_hash=_stable_hash(sorted(visual_tokens)),
            interactive_set_hash=_stable_hash(sorted(interactive_tokens)),
            anchor_tokens_hash=_stable_hash(sorted(anchor_tokens)),
            timestamp=time.time(),
            element_count=len(elements),
            interactive_count=sum(1 for element in elements if element.interaction_types),
            has_overlays=bool(overlays),
            raw_xml=raw_xml or None,
            normalized_xml=self.normalizer.normalize_xml(raw_xml) if raw_xml else None,
            dom_tokens=dom_tokens,
            visual_tokens=visual_tokens,
            interactive_tokens=interactive_tokens,
            anchor_tokens=anchor_tokens,
        )

    def _dom_tokens(self, elements: List[UIElement]) -> Set[str]:
        tokens: Set[str] = set()
        for element in elements:
            bounds_token = ""
            if element.bounds:
                quantized = element.bounds.quantize()
                bounds_token = f"@{quantized.x1},{quantized.y1},{quantized.x2},{quantized.y2}"
            parent_suffix = "/".join(element.parent_chain[-3:])
            identifier = element.primary_identifier[:60].lower()
            tokens.add(f"{parent_suffix}>{element.class_name}{bounds_token}:{identifier}")
        return tokens

    def _visual_tokens(self, elements: List[UIElement]) -> Set[str]:
        tokens: Set[str] = set()
        for element in elements:
            if not element.visible or not element.bounds:
                continue
            quantized = element.bounds.quantize()
            descriptor = element.text or element.accessibility_id or element.hint or element.class_name
            tokens.add(
                f"{element.class_name}:{descriptor[:40].lower()}@{quantized.x1},{quantized.y1},{quantized.x2},{quantized.y2}"
            )
        return tokens

    def _interactive_tokens(self, elements: List[UIElement]) -> Set[str]:
        tokens: Set[str] = set()
        for element in elements:
            if not element.enabled or not element.interaction_types:
                continue
            descriptor = element.primary_identifier[:60].lower() or element.class_name.lower()
            interaction_key = ",".join(sorted(element.interaction_types))
            position = ""
            if element.bounds:
                quantized = element.bounds.quantize(25)
                position = f"@{quantized.x1},{quantized.y1}"
            tokens.add(f"{interaction_key}:{descriptor}{position}")
        return tokens

    def _anchor_tokens(self, elements: List[UIElement], metadata: Dict[str, Any]) -> Set[str]:
        tokens: Set[str] = set()
        activity = metadata.get("activity") or metadata.get("activity_name") or ""
        package = metadata.get("package") or metadata.get("package_name") or ""
        if activity:
            tokens.add(f"activity:{activity.lower()}")
        if package:
            tokens.add(f"package:{package.lower()}")
        top_texts = sorted(
            (
                element for element in elements
                if element.visible and element.bounds and (element.text or element.accessibility_id)
            ),
            key=lambda element: (element.bounds.y1, element.bounds.x1),
        )[:6]
        for element in top_texts:
            value = element.text or element.accessibility_id
            normalized = self.normalizer.normalize_text(value)
            if normalized:
                tokens.add(f"anchor:{normalized.lower()}")
        return tokens


class ScreenComparator:
    DEFAULT_WEIGHTS = (0.4, 0.3, 0.2, 0.1)
    THRESHOLD_SAME = 0.88
    THRESHOLD_DIFFERENT = 0.72

    def compare(
        self,
        sig1: ScreenSignature,
        sig2: ScreenSignature,
        weights: Optional[Tuple[float, float, float, float]] = None,
    ) -> ComparisonResult:
        chosen = weights or self.DEFAULT_WEIGHTS
        dom = self._jaccard_similarity(sig1.dom_tokens, sig2.dom_tokens)
        visual = self._jaccard_similarity(sig1.visual_tokens, sig2.visual_tokens)
        interactive = self._jaccard_similarity(sig1.interactive_tokens, sig2.interactive_tokens)
        anchor = self._jaccard_similarity(sig1.anchor_tokens, sig2.anchor_tokens)
        score = (
            chosen[0] * dom
            + chosen[1] * visual
            + chosen[2] * interactive
            + chosen[3] * anchor
        )
        verdict = "VARIANT"
        if score >= self.THRESHOLD_SAME:
            verdict = "SAME"
        elif score <= self.THRESHOLD_DIFFERENT:
            verdict = "DIFFERENT"
        return ComparisonResult(
            similarity_score=score,
            verdict=verdict,
            details={
                "dom": dom,
                "visual": visual,
                "interactive": interactive,
                "anchor": anchor,
            },
        )

    def _hamming_similarity(self, hash1: str, hash2: str) -> float:
        if not hash1 and not hash2:
            return 1.0
        if len(hash1) != len(hash2) or not hash1:
            return 0.0
        same = sum(1 for left, right in zip(hash1, hash2) if left == right)
        return same / len(hash1)

    def _jaccard_similarity(self, set1: Set[str], set2: Set[str]) -> float:
        if not set1 and not set2:
            return 1.0
        if not set1 or not set2:
            return 0.0
        return len(set1 & set2) / len(set1 | set2)


class OverlayDetector:
    def detect_overlays(
        self,
        elements: List[UIElement],
        screen_bounds: Optional[Bounds],
    ) -> List[OverlayInfo]:
        if not screen_bounds or screen_bounds.area <= 0:
            return []

        overlays: List[OverlayInfo] = []
        seen: Set[Tuple[int, int, int, int]] = set()
        for element in elements:
            if not element.visible or not element.bounds or element.child_count == 0:
                continue
            candidate = self._build_overlay(element, screen_bounds)
            if not candidate:
                continue
            key = (candidate.bounds.x1, candidate.bounds.y1, candidate.bounds.x2, candidate.bounds.y2)
            if key in seen:
                continue
            seen.add(key)
            overlays.append(candidate)

        overlays.sort(key=lambda overlay: (overlay.priority, overlay.bounds.area), reverse=True)
        return overlays

    def _build_overlay(self, element: UIElement, screen_bounds: Bounds) -> Optional[OverlayInfo]:
        assert element.bounds is not None
        relative_area = element.bounds.area / max(1, screen_bounds.area)
        cx, cy = element.bounds.center
        screen_cx, screen_cy = screen_bounds.center
        centered = abs(cx - screen_cx) <= screen_bounds.width * 0.2 and abs(cy - screen_cy) <= screen_bounds.height * 0.2
        small_relative_size = relative_area < 0.8
        combined = _normalize_spaces(" ".join([element.text_blob, element.primary_identifier])).lower()
        class_name = element.class_name.lower()
        has_dialog_keyword = any(token in class_name for token in _DIALOG_CLASS_TOKENS)
        has_overlay_text = any(token in combined for token in _OVERLAY_TEXT_TOKENS)
        banner_like = element.bounds.y1 > screen_bounds.y1 + int(screen_bounds.height * 0.6) and relative_area < 0.35
        centered_dialog = centered and 0.05 <= relative_area <= 0.85 and (has_overlay_text or has_dialog_keyword or element.child_count >= 2)
        if not (centered_dialog or banner_like):
            return None

        overlay_type = self.classify_overlay_type(element, centered, banner_like, combined)
        dismiss_actions = self.get_dismiss_actions(overlay_type, combined)
        blocking = overlay_type in {"PERMISSION", "MODAL", "LOGIN", "UPDATE"} or centered_dialog
        return OverlayInfo(
            overlay_type=overlay_type,
            bounds=element.bounds,
            blocking=blocking,
            dismissible=bool(dismiss_actions),
            priority=100 if blocking else 50,
            has_backdrop=centered_dialog,
            has_focus_trap=centered_dialog,
            centered=centered,
            small_relative_size=small_relative_size,
            template_id=self._template_id(combined),
            dismiss_actions=dismiss_actions,
        )

    def classify_overlay_type(self, element: UIElement, centered: bool, banner_like: bool, combined: str) -> str:
        if "permission" in combined or ("allow" in combined and "deny" in combined):
            return "PERMISSION"
        if "update" in combined:
            return "UPDATE"
        if "login" in combined or "sign in" in combined:
            return "LOGIN"
        if "cookie" in combined or "privacy" in combined:
            return "BANNER"
        if banner_like:
            return "BANNER"
        if centered:
            return "MODAL"
        return "TOAST"

    def get_dismiss_actions(self, overlay_type: str, combined: str) -> List[str]:
        actions: List[str] = []
        if any(token in combined for token in ("close", "cancel", "deny", "not now", "later")):
            actions.append("tap_close_or_cancel")
        if overlay_type in {"MODAL", "BANNER", "UPDATE", "LOGIN"}:
            actions.append("back")
        if overlay_type in {"BANNER", "MODAL"}:
            actions.append("tap_outside")
        return list(dict.fromkeys(actions))

    def _template_id(self, combined: str) -> Optional[str]:
        if "permission" in combined:
            return "permission_dialog"
        if "cookie" in combined or "privacy" in combined:
            return "cookie_banner"
        if "update" in combined:
            return "update_prompt"
        return None


class OcclusionChecker:
    def is_occluded(self, element: UIElement, all_elements: List[UIElement]) -> bool:
        if not element.bounds or not element.visible:
            return False
        cx, cy = element.bounds.center
        for other in all_elements:
            if other is element or not other.bounds or not other.visible:
                continue
            if other.z_index <= element.z_index:
                continue
            if other.bounds.contains_point(cx, cy) and other.bounds.area >= element.bounds.area:
                return True
        return False

    def get_visible_elements(self, elements: List[UIElement]) -> List[UIElement]:
        return [element for element in elements if not self.is_occluded(element, elements)]


class ElementExtractor:
    def __init__(self, cache_enabled: bool = True, cache_size: int = 100):
        self.parser = XMLParser(cache_size=cache_size if cache_enabled else 0)
        self.normalizer = Normalizer()

    def extract_elements(
        self,
        page_source: str,
        filter_fn: Optional[Callable[[UIElement], bool]] = None,
    ) -> List[UIElement]:
        elements = list(self.parser.parse(page_source).elements)
        if filter_fn is None:
            return elements
        return [element for element in elements if filter_fn(element)]

    def extract_by_type(self, page_source: str, *types: str) -> List[UIElement]:
        requested = set(types)
        return [
            element for element in self.parser.parse(page_source).elements
            if element.interaction_types & requested
        ]

    def find_element(self, page_source: str, **criteria: Any) -> Optional[UIElement]:
        for element in self.parser.parse(page_source).elements:
            if all(getattr(element, key, None) == value for key, value in criteria.items()):
                return element
        return None

    def extract_clickable_accessibility_ids(self, page_source: str) -> List[str]:
        values = {
            element.accessibility_id
            for element in self.parser.parse(page_source).elements
            if element.clickable and element.enabled and element.accessibility_id and len(element.accessibility_id) <= 80
        }
        return sorted(values)

    def extract_clickable_resource_ids(self, page_source: str) -> List[str]:
        values = {
            element.resource_id
            for element in self.parser.parse(page_source).elements
            if element.clickable and element.enabled and element.resource_id
        }
        return sorted(values)

    def extract_clickable_texts(self, page_source: str) -> List[str]:
        values: Set[str] = set()
        for element in self.parser.parse(page_source).elements:
            if not element.clickable or not element.enabled:
                continue
            text = element.text if element.text and len(element.text) <= 40 else ""
            if text:
                values.add(text)
                continue
            for label in element.child_labels:
                if len(label) <= 40:
                    values.add(label)
        return sorted(values)

    def extract_input_fields(self, page_source: str) -> List[dict]:
        fields: List[dict] = []
        for element in self.parser.parse(page_source).elements:
            if not element.editable:
                continue
            cx, cy = element.bounds.center if element.bounds else (None, None)
            if element.accessibility_id or element.resource_id or element.bounds:
                fields.append({
                    "accessibility_id": element.accessibility_id,
                    "resource_id": element.resource_id,
                    "hint": element.hint,
                    "locator_type": "accessibility_id" if element.accessibility_id else "resource_id",
                    "locator_value": element.accessibility_id or element.resource_id,
                    "cx": cx,
                    "cy": cy,
                    "bounds": element.raw_bounds,
                })
        return fields

    def extract_scrollable_containers(self, page_source: str) -> bool:
        return any(element.scrollable for element in self.parser.parse(page_source).elements)

    def extract_all_interactive_elements(self, page_source: str) -> List[dict]:
        elements: List[dict] = []
        seen: Set[str] = set()
        for element in self.parser.parse(page_source).elements:
            if not element.enabled or not element.interaction_types:
                continue
            key = element.primary_identifier
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            elements.append({
                "class": element.class_name,
                "accessibility_id": element.accessibility_id,
                "resource_id": element.resource_id,
                "text": element.text,
                "child_labels": list(element.child_labels),
                "clickable": element.clickable,
                "long_clickable": element.long_clickable,
                "checkable": element.checkable,
                "scrollable": element.scrollable,
                "bounds": element.raw_bounds,
            })
        return elements

    def extract_visible_texts_ordered(self, page_source: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for element in self.parser.parse(page_source).elements:
            if not element.visible or not (element.text or element.accessibility_id):
                continue
            y = element.bounds.y1 if element.bounds else 9999
            x = element.bounds.x1 if element.bounds else 9999
            items.append({
                "text": element.text,
                "content_desc": element.accessibility_id,
                "bounds_y": y,
                "bounds_x": x,
                "class": element.class_name,
            })
        items.sort(key=lambda item: (item["bounds_y"], item["bounds_x"]))
        return items

    def extract_labelled_data_items(self, page_source: str) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        try:
            root = ET.fromstring(page_source)
        except Exception:
            return items

        for node in root.iter():
            if _normalize_spaces(node.attrib.get("content-desc", "")) != "store item":
                continue
            item: Dict[str, str] = {}
            for child in node.iter():
                child_desc = _normalize_spaces(child.attrib.get("content-desc", ""))
                child_text = _normalize_spaces(child.attrib.get("text", ""))
                if child_desc == "store item text" and child_text:
                    item["name"] = child_text
                elif child_desc in {"store item price", "product price"} and child_text:
                    item["price"] = child_text
            bounds = _parse_bounds(node.attrib.get("bounds", ""))
            if item:
                item["_y"] = str(bounds.y1 if bounds else 9999)
                items.append(item)
        items.sort(key=lambda item: int(item.pop("_y", "9999")))
        return items

    def find_element_bounds(
        self,
        page_source: str,
        locator_type: str,
        locator_value: str,
    ) -> Optional[Tuple[int, int]]:
        if not page_source or not locator_value:
            return None

        attr_map = {
            "accessibility_id": "accessibility_id",
            "resource_id": "resource_id",
            "text": "text",
        }
        primary_attr = attr_map.get(locator_type, "resource_id")
        for element in self.parser.parse(page_source).elements:
            value = _normalize_spaces(getattr(element, primary_attr, ""))
            if value == locator_value or value.endswith("/" + locator_value):
                return element.bounds.center if element.bounds else None

        for element in self.parser.parse(page_source).elements:
            candidates = [element.resource_id, element.accessibility_id, element.text]
            if any(value and (value == locator_value or locator_value in value) for value in candidates):
                return element.bounds.center if element.bounds else None
        return None

    def find_input_field_bounds(self, page_source: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for element in self.parser.parse(page_source).elements:
            if not element.editable or not element.bounds:
                continue
            cx, cy = element.bounds.center
            results.append({
                "cx": cx,
                "cy": cy,
                "hint": element.hint,
                "resource_id": element.resource_id,
                "accessibility_id": element.accessibility_id,
                "bounds": element.raw_bounds,
            })
        return results


class ScreenAnalyzer:
    def __init__(
        self,
        cache_size: int = 100,
        enable_normalization: bool = True,
        similarity_weights: Optional[Tuple[float, float, float, float]] = None,
        parser: Optional[XMLParser] = None,
    ):
        self.parser = parser or XMLParser(cache_size)
        self.normalizer = Normalizer()
        self.enable_normalization = enable_normalization
        self.fingerprint_gen = FingerprintGenerator(self.normalizer)
        self.comparator = ScreenComparator()
        self.overlay_detector = OverlayDetector()
        self.occlusion_checker = OcclusionChecker()
        self.similarity_weights = similarity_weights or self.comparator.DEFAULT_WEIGHTS

    def analyze_screen(self, page_source: str, activity_name: str = "", package_name: str = "") -> ScreenState:
        parsed = self.parser.parse(page_source)
        metadata = dict(parsed.metadata)
        if activity_name:
            metadata["activity"] = activity_name
        if package_name:
            metadata["package"] = package_name
        overlays = self.overlay_detector.detect_overlays(parsed.elements, parsed.screen_bounds)
        signature = self.fingerprint_gen.generate_signature(parsed.elements, metadata, raw_xml=page_source, overlays=overlays)
        return ScreenState(
            signature=signature,
            elements=parsed.elements,
            overlays=overlays,
            scrollable=any(element.scrollable for element in parsed.elements),
            has_input_fields=any(element.editable for element in parsed.elements),
            activity_name=metadata.get("activity") or None,
            package_name=metadata.get("package") or None,
            raw_xml=page_source,
        )

    def compare_screens(
        self,
        page_source1: str,
        page_source2: str,
        activity1: str = "",
        activity2: str = "",
    ) -> ComparisonResult:
        screen1 = self.analyze_screen(page_source1, activity_name=activity1)
        screen2 = self.analyze_screen(page_source2, activity_name=activity2)
        return self.comparator.compare(screen1.signature, screen2.signature, self.similarity_weights)

    def is_stable(self, page_sources: List[str], min_polls: int = 2) -> bool:
        if len(page_sources) < max(1, min_polls):
            return False
        signatures = [self.analyze_screen(page_source).signature for page_source in page_sources[-min_polls:]]
        first = signatures[0]
        return all(self.comparator.compare(first, signature, self.similarity_weights).verdict == "SAME" for signature in signatures[1:])

    def extract_action_candidates(
        self,
        page_source: str,
        exclude_overlays: bool = False,
        only_visible: bool = True,
    ) -> List[UIElement]:
        screen = self.analyze_screen(page_source)
        candidates = screen.get_action_candidates(exclude_occluded=only_visible, priority_order=True)
        if exclude_overlays and screen.overlays:
            overlay_bounds = [overlay.bounds for overlay in screen.overlays]
            candidates = [
                element for element in candidates
                if not element.bounds or not any(bounds.contains_point(*element.bounds.center) for bounds in overlay_bounds)
            ]
        return candidates


def iter_xml_elements(page_source: str) -> Iterable[ET.Element]:
    if not page_source:
        return []
    try:
        root = ET.fromstring(page_source)
    except Exception:
        return []
    return root.iter()


def _collect_child_labels(element: ET.Element) -> List[str]:
    labels: List[str] = []
    seen: Set[str] = set()
    for child in element.iter():
        if child is element:
            continue
        text = _normalize_spaces(child.attrib.get("text", ""))
        if text and text not in seen and len(text) > 1 and len(text) <= 60 and any(char.isalnum() for char in text):
            labels.append(text)
            seen.add(text)
    return labels


def _parse_bounds(bounds_str: str) -> Optional[Bounds]:
    match = _BOUNDS_RE.match(bounds_str or "")
    if not match:
        return None
    return Bounds(int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4)))


def _bounds_center(bounds: Bounds) -> Tuple[int, int]:
    return bounds.center


def _select_screen_bounds(elements: List[UIElement]) -> Optional[Bounds]:
    candidates = [element.bounds for element in elements if element.bounds and element.bounds.area > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda bounds: bounds.area)


_DEFAULT_EXTRACTOR = ElementExtractor()
_DEFAULT_ANALYZER = ScreenAnalyzer(parser=_DEFAULT_EXTRACTOR.parser)


def extract_clickable_accessibility_ids(page_source: str) -> List[str]:
    return _DEFAULT_EXTRACTOR.extract_clickable_accessibility_ids(page_source)


def extract_clickable_resource_ids(page_source: str) -> List[str]:
    return _DEFAULT_EXTRACTOR.extract_clickable_resource_ids(page_source)


def extract_clickable_texts(page_source: str) -> List[str]:
    return _DEFAULT_EXTRACTOR.extract_clickable_texts(page_source)


def extract_input_fields(page_source: str) -> List[dict]:
    return _DEFAULT_EXTRACTOR.extract_input_fields(page_source)


def extract_scrollable_containers(page_source: str) -> bool:
    return _DEFAULT_EXTRACTOR.extract_scrollable_containers(page_source)


def extract_all_interactive_elements(page_source: str) -> List[dict]:
    return _DEFAULT_EXTRACTOR.extract_all_interactive_elements(page_source)


def extract_visible_texts_ordered(page_source: str) -> List[Dict[str, Any]]:
    return _DEFAULT_EXTRACTOR.extract_visible_texts_ordered(page_source)


def extract_labelled_data_items(page_source: str) -> List[Dict[str, str]]:
    return _DEFAULT_EXTRACTOR.extract_labelled_data_items(page_source)


def find_element_bounds(
    page_source: str,
    locator_type: str,
    locator_value: str,
) -> Optional[Tuple[int, int]]:
    return _DEFAULT_EXTRACTOR.find_element_bounds(page_source, locator_type, locator_value)


def find_input_field_bounds(page_source: str) -> List[Dict[str, Any]]:
    return _DEFAULT_EXTRACTOR.find_input_field_bounds(page_source)
