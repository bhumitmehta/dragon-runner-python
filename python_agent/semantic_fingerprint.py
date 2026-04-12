"""
Semantic Screen Fingerprinting
==============================

Replaces fragile XML structure hashing with semantic fingerprinting using
developer-assigned accessibility attributes (content-desc, resource-id).

Core insight: Developers already provide stable identifiers for automation
via content-desc and resource-id. These survive:
- Scroll position changes
- Text content updates  
- Dynamic data (timestamps, prices)
- Modal/drawer state changes

The fingerprint is based on the SET of semantic identifiers present on screen,
not the XML structure or visual layout.

Usage:
    from semantic_fingerprint import semantic_screen_fingerprint, SemanticFingerprint
    
    # Get fingerprint for current screen
    fingerprint = semantic_screen_fingerprint(page_source, current_activity)
    
    # Or use the class-based API for more control
    fp = SemanticFingerprint.from_xml(page_source, current_activity)
    
    # Check if two screens are the same (despite scroll position)
    if fp1.is_similar_to(fp2):
        print("Same screen, different scroll position")
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union


# State patterns to filter out from content-desc for stable hashing
# These patterns indicate selected/checked/focused states that change dynamically
_STATE_PATTERNS = [
    # Boolean state indicators
    r'\s*\(\s*checked\s*\)\s*$',
    r'\s*\(\s*unchecked\s*\)\s*$',
    r'\s*\(\s*selected\s*\)\s*$',
    r'\s*\(\s*unselected\s*\)\s*$',
    r'\s*\(\s*on\s*\)\s*$',
    r'\s*\(\s*off\s*\)\s*$',
    r'\s*\(\s*enabled\s*\)\s*$',
    r'\s*\(\s*disabled\s*\)\s*$',
    r'\s*\(\s*focused\s*\)\s*$',
    r'\s*\(\s*active\s*\)\s*$',
    r'\s*\(\s*inactive\s*\)\s*$',
    # Prefix patterns
    r'^selected:\s*',
    r'^checked:\s*',
    r'^enabled:\s*',
    r'^disabled:\s*',
    r'^focused:\s*',
    r'^active:\s*',
    r'^inactive:\s*',
    # Suffix patterns with emojis or symbols
    r'\s*✓\s*$',
    r'\s*✔\s*$',
    r'\s*☑\s*$',
    r'\s*☐\s*$',
    r'\s*●\s*$',
    r'\s*○\s*$',
]

# Compiled regex patterns for efficiency
_STATE_REGEXES = [re.compile(p, re.IGNORECASE) for p in _STATE_PATTERNS]

# Input field patterns - these should be normalized to base form
_INPUT_FIELD_PATTERNS = [
    r'^(.*?)\s*input\s*$',
    r'^(.*?)\s*field\s*$',
    r'^(.*?)\s*text\s*$',
    r'^(.*?)\s*entry\s*$',
]
_INPUT_REGEXES = [re.compile(p, re.IGNORECASE) for p in _INPUT_FIELD_PATTERNS]


def _normalize_content_desc(content_desc: str) -> str:
    """
    Normalize content-desc by removing state indicators.
    
    This ensures that the same element produces the same hash
    regardless of its current state (checked/unchecked, selected/unselected).
    
    Args:
        content_desc: Raw content-desc attribute value
        
    Returns:
        Normalized content-desc with state indicators removed
    """
    normalized = content_desc.strip()
    
    # Remove state indicators
    for pattern in _STATE_REGEXES:
        normalized = pattern.sub('', normalized)
    
    # Normalize input fields to base form
    for pattern in _INPUT_REGEXES:
        match = pattern.match(normalized)
        if match:
            base = match.group(1).strip()
            if base:
                normalized = f"{base}_input"
            else:
                normalized = "input_field"
            break
    
    return normalized.strip()


def _is_state_only_element(attrib: Dict[str, str]) -> bool:
    """
    Check if an element is purely a state indicator with no stable identifiers.
    
    These elements should be excluded from the hash because they have no
    stable identifiers (no content-desc AND no resource-id) and their
    state changes dynamically.
    
    Args:
        attrib: Element attributes dictionary
        
    Returns:
        True if this element has no stable identifiers and should be skipped
    """
    has_content_desc = bool(attrib.get('content-desc', '').strip())
    has_resource_id = bool(attrib.get('resource-id', '').strip())
    
    # If element has no stable identifiers at all, skip it
    # (no content-desc AND no resource-id means it's not semantically meaningful)
    if not has_content_desc and not has_resource_id:
        return True
    
    # Check for password fields - these should be excluded entirely
    # as their content is sensitive and dynamic
    is_password = attrib.get('password') == 'true'
    if is_password:
        return True
    
    return False


@dataclass
class SemanticFingerprint:
    """
    A semantic fingerprint of a mobile app screen.
    
    Based on developer-assigned accessibility attributes rather than
    XML structure or visual appearance.
    
    Attributes:
        activity: Android activity name (e.g., "com.app.MainActivity")
        content_descs: Set of content-desc attribute values found on screen
        resource_ids: Set of resource-id values (package prefix stripped)
        semantic_hash: Deterministic hash of the semantic content
        raw_stats: Statistics about the XML structure (for debugging)
    """
    activity: str
    content_descs: Set[str] = field(default_factory=set)
    resource_ids: Set[str] = field(default_factory=set)
    semantic_hash: str = ""
    raw_stats: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Compute semantic hash if not provided."""
        if not self.semantic_hash:
            self.semantic_hash = self._compute_hash()
    
    def _compute_hash(self) -> str:
        """Compute deterministic hash from semantic content."""
        # Combine all semantic identifiers
        all_ids = []
        all_ids.extend(f"desc:{d}" for d in sorted(self.content_descs))
        all_ids.extend(f"id:{i}" for i in sorted(self.resource_ids))
        
        if not all_ids:
            # Fallback: hash activity name only
            return hashlib.sha256(self.activity.encode()).hexdigest()[:16]
        
        fingerprint_data = f"{self.activity}::" + "::".join(all_ids)
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]
    
    @classmethod
    def from_xml(cls, page_source: str, activity: str) -> SemanticFingerprint:
        """
        Create a fingerprint from Appium XML page source.
        
        Args:
            page_source: XML string from Appium driver.page_source
            activity: Current Android activity name
            
        Returns:
            SemanticFingerprint instance
        """
        content_descs: Set[str] = set()
        resource_ids: Set[str] = set()
        
        stats = {
            "total_nodes": 0,
            "clickable_nodes": 0,
            "nodes_with_content_desc": 0,
            "nodes_with_resource_id": 0,
            "scrollable_containers": 0
        }
        
        try:
            root = ET.fromstring(page_source)
        except ET.ParseError:
            return cls(
                activity=activity,
                content_descs=set(),
                resource_ids=set(),
                semantic_hash="",
                raw_stats={"parse_error": True}
            )
        
        for el in root.iter():
            stats["total_nodes"] += 1
            
            attrib = el.attrib
            
            # Track clickable nodes
            if attrib.get("clickable") == "true":
                stats["clickable_nodes"] += 1
            
            # Track scrollable containers
            if attrib.get("scrollable") == "true":
                stats["scrollable_containers"] += 1
            
            # Skip state-only elements (checkboxes, radio buttons without stable IDs)
            if _is_state_only_element(attrib):
                continue
            
            # Extract content-desc (highest priority - developer assigned)
            # Normalize to remove state indicators (checked/unchecked, selected/unselected)
            content_desc = attrib.get("content-desc", "").strip()
            if content_desc:
                normalized_desc = _normalize_content_desc(content_desc)
                if normalized_desc:  # Only add if not empty after normalization
                    content_descs.add(normalized_desc)
                    stats["nodes_with_content_desc"] += 1
            
            # Extract resource-id (second priority - Android native)
            resource_id = attrib.get("resource-id", "").strip()
            if resource_id:
                # Strip package prefix for stability across builds
                clean_id = resource_id.split("/")[-1]
                if clean_id:  # Skip empty strings
                    resource_ids.add(clean_id)
                    stats["nodes_with_resource_id"] += 1
        
        return cls(
            activity=activity,
            content_descs=content_descs,
            resource_ids=resource_ids,
            semantic_hash="",  # Will be computed in __post_init__
            raw_stats=stats
        )
    
    def is_similar_to(self, other: SemanticFingerprint, threshold: float = 0.7) -> bool:
        """
        Check if two fingerprints represent the same screen.
        
        Uses Jaccard similarity on the combined semantic identifier sets.
        
        Args:
            other: Another SemanticFingerprint to compare
            threshold: Minimum Jaccard similarity to consider same screen (0.0-1.0)
            
        Returns:
            True if screens are likely the same (just different scroll/viewport state)
        """
        if self.activity != other.activity:
            return False
        
        # Combine content_descs and resource_ids for comparison
        self_ids = self.content_descs | self.resource_ids
        other_ids = other.content_descs | other.resource_ids
        
        if not self_ids and not other_ids:
            return True  # Both empty - likely same blank/error screen
        
        if not self_ids or not other_ids:
            return False  # One has IDs, other doesn't
        
        # Jaccard similarity: |intersection| / |union|
        intersection = len(self_ids & other_ids)
        union = len(self_ids | other_ids)
        
        similarity = intersection / union if union > 0 else 0.0
        
        return similarity >= threshold
    
    def jaccard_similarity(self, other: SemanticFingerprint) -> float:
        """Compute Jaccard similarity between two fingerprints."""
        if self.activity != other.activity:
            return 0.0
        
        self_ids = self.content_descs | self.resource_ids
        other_ids = other.content_descs | other.resource_ids
        
        if not self_ids and not other_ids:
            return 1.0
        
        if not self_ids or not other_ids:
            return 0.0
        
        intersection = len(self_ids & other_ids)
        union = len(self_ids | other_ids)
        
        return intersection / union if union > 0 else 0.0
    
    def get_new_elements(self, other: SemanticFingerprint) -> Set[str]:
        """
        Get semantic identifiers present in other but not in self.
        
        Useful for detecting newly visible elements after scroll.
        """
        self_ids = self.content_descs | self.resource_ids
        other_ids = other.content_descs | other.resource_ids
        return other_ids - self_ids
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "activity": self.activity,
            "semantic_hash": self.semantic_hash,
            "content_descs": sorted(self.content_descs),
            "resource_ids": sorted(self.resource_ids),
            "stats": self.raw_stats
        }
    
    def __hash__(self) -> int:
        """Make fingerprint hashable for use in sets/dicts."""
        return hash(self.semantic_hash)
    
    def __eq__(self, other: object) -> bool:
        """Equality based on semantic hash."""
        if not isinstance(other, SemanticFingerprint):
            return False
        return self.semantic_hash == other.semantic_hash

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SemanticFingerprint":
        """Rehydrate a fingerprint from serialized storage."""
        return cls(
            activity=str(data.get("activity") or "unknown"),
            content_descs=set(data.get("content_descs") or []),
            resource_ids=set(data.get("resource_ids") or []),
            semantic_hash=str(data.get("semantic_hash") or ""),
            raw_stats=dict(data.get("stats") or data.get("raw_stats") or {}),
        )


def _looks_like_xml(value: str) -> bool:
    stripped = (value or "").lstrip()
    return stripped.startswith("<") and stripped.endswith(">")


def _looks_like_hash(value: str) -> bool:
    return bool(re.fullmatch(r"[a-f0-9]{16}", (value or "").strip(), re.IGNORECASE))


def _coerce_fingerprint(
    value: Union["SemanticFingerprint", Dict[str, Any], str, None],
    activity: str = "",
) -> Optional["SemanticFingerprint"]:
    if value is None:
        return None
    if isinstance(value, SemanticFingerprint):
        return value
    if isinstance(value, dict):
        if any(key in value for key in ("content_descs", "resource_ids", "semantic_hash")):
            return SemanticFingerprint.from_dict(value)
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if _looks_like_xml(stripped):
            return SemanticFingerprint.from_xml(stripped, activity or "unknown")
        if _looks_like_hash(stripped):
            return SemanticFingerprint(
                activity=activity or "unknown",
                content_descs=set(),
                resource_ids=set(),
                semantic_hash=stripped.lower(),
                raw_stats={"hash_only": True},
            )
    return None


# ── Convenience Functions ─────────────────────────────────────────

def semantic_screen_fingerprint(page_source: str, activity: str) -> str:
    """
    Get a semantic fingerprint hash for the current screen.
    
    This is a drop-in replacement for state_signature_from_xml().
    
    Args:
        page_source: XML from Appium driver.page_source
        activity: Current Android activity name
        
    Returns:
        16-character hex hash string (same format as old function)
    """
    fp = SemanticFingerprint.from_xml(page_source, activity)
    return fp.semantic_hash


def compute_semantic_fingerprint(page_source: str, activity: str = "") -> Dict[str, Any]:
    """Return a serializable semantic fingerprint payload for storage."""
    return SemanticFingerprint.from_xml(page_source, activity or "unknown").to_dict()


def are_screens_similar(
    screen1: Union[SemanticFingerprint, Dict[str, Any], str],
    activity1: Union[str, Dict[str, Any], SemanticFingerprint] = "",
    screen2: Optional[Union[SemanticFingerprint, Dict[str, Any], str]] = None,
    activity2: str = "",
    threshold: float = 0.7
) -> bool:
    """
    Compare two screens using XML, stored fingerprint dicts, objects, or hash strings.
    
    Args:
        screen1: First XML string, fingerprint dict/object, or semantic hash
        activity1: First activity name, or second fingerprint when using the two-arg form
        screen2: Second XML string, fingerprint dict/object, or semantic hash
        activity2: Second activity name
        threshold: Jaccard similarity threshold
        
    Returns:
        True if screens are likely the same
    """
    if screen2 is None and not isinstance(activity1, str):
        fp1 = _coerce_fingerprint(screen1)
        fp2 = _coerce_fingerprint(activity1)
    elif screen2 is None and isinstance(activity1, dict):
        fp1 = _coerce_fingerprint(screen1)
        fp2 = _coerce_fingerprint(activity1)
    elif screen2 is None:
        return False
    else:
        fp1 = _coerce_fingerprint(screen1, activity1 if isinstance(activity1, str) else "")
        fp2 = _coerce_fingerprint(screen2, activity2)

    if not fp1 or not fp2:
        return False

    hash_only = fp1.raw_stats.get("hash_only") or fp2.raw_stats.get("hash_only")
    if hash_only:
        return fp1.semantic_hash == fp2.semantic_hash

    if fp1.activity != fp2.activity and fp1.activity and fp2.activity:
        return False
    return fp1.is_similar_to(fp2, threshold)


# ── Screen Registry for Crawling ───────────────────────────────────

class SemanticScreenRegistry:
    """
    Registry for tracking visited screens during crawling.
    
    Uses semantic fingerprints to identify screens, with similarity
    matching to handle scroll position changes.
    """
    
    def __init__(self, similarity_threshold: float = 0.7):
        self.screens: Dict[str, SemanticFingerprint] = {}  # hash -> fingerprint
        self.visit_counts: Dict[str, int] = {}
        self.similarity_threshold = similarity_threshold
    
    def register(self, fingerprint: SemanticFingerprint) -> Tuple[str, bool]:
        """
        Register a screen visit.
        
        Args:
            fingerprint: Screen fingerprint
            
        Returns:
            Tuple of (screen_hash, is_new) where is_new indicates
            if this is a genuinely new screen or just a scroll/viewport change
        """
        # Check for similar existing screen
        for existing_hash, existing_fp in self.screens.items():
            if fingerprint.is_similar_to(existing_fp, self.similarity_threshold):
                # Same screen, increment visit count
                self.visit_counts[existing_hash] += 1
                return existing_hash, False
        
        # New screen
        self.screens[fingerprint.semantic_hash] = fingerprint
        self.visit_counts[fingerprint.semantic_hash] = 1
        return fingerprint.semantic_hash, True
    
    def get_visit_count(self, fingerprint: SemanticFingerprint) -> int:
        """Get number of times this screen (or similar) has been visited."""
        for existing_hash, existing_fp in self.screens.items():
            if fingerprint.is_similar_to(existing_fp, self.similarity_threshold):
                return self.visit_counts[existing_hash]
        return 0
    
    def get_coverage_stats(self) -> Dict[str, Any]:
        """Get crawling coverage statistics."""
        return {
            "unique_screens": len(self.screens),
            "total_visits": sum(self.visit_counts.values()),
            "most_visited": max(self.visit_counts.values()) if self.visit_counts else 0,
            "activities": list(set(fp.activity for fp in self.screens.values()))
        }


# ── Example Usage ──────────────────────────────────────────────────

if __name__ == "__main__":
    # Example with the SauceLabs demo app XML
    example_xml = '''
    <hierarchy>
        <node content-desc="open menu" clickable="true" />
        <node content-desc="cart badge" clickable="true" />
        <node content-desc="product screen" scrollable="true" />
        <node content-desc="product price" />
        <node content-desc="Add To Cart button" clickable="true" />
    </hierarchy>
    '''
    
    # Create fingerprint
    fp = SemanticFingerprint.from_xml(example_xml, "ProductDetailActivity")
    
    print(f"Activity: {fp.activity}")
    print(f"Semantic Hash: {fp.semantic_hash}")
    print(f"Content Descriptions: {sorted(fp.content_descs)}")
    print(f"Resource IDs: {sorted(fp.resource_ids)}")
    print(f"Stats: {fp.raw_stats}")
    
    # Compare with scrolled version (missing some elements)
    scrolled_xml = '''
    <hierarchy>
        <node content-desc="open menu" clickable="true" />
        <node content-desc="cart badge" clickable="true" />
        <node content-desc="product screen" scrollable="true" />
        <node content-desc="product price" />
        <!-- Add To Cart button scrolled off screen -->
    </hierarchy>
    '''
    
    fp_scrolled = SemanticFingerprint.from_xml(scrolled_xml, "ProductDetailActivity")
    
    print(f"\nScrolled version hash: {fp_scrolled.semantic_hash}")
    print(f"Similarity: {fp.jaccard_similarity(fp_scrolled):.2f}")
    print(f"Are same screen? {fp.is_similar_to(fp_scrolled)}")
    print(f"New elements visible: {fp.get_new_elements(fp_scrolled)}")
