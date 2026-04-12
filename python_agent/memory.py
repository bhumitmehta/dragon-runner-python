import datetime
import hashlib
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple
from .vlm import get_text_response
from .logging_config import get_logger

logger = get_logger("memory")

# Cache for skeletonization decisions: structure_hash -> should_skeletonize
_skeletonization_cache: Dict[str, bool] = {}

# Configuration
SKELETONIZATION_ENABLED = True  # Can be disabled if needed
MAX_CACHE_SIZE = 1000  # Limit cache size to prevent memory issues


def clear_skeletonization_cache():
    """Clear the skeletonization decision cache."""
    global _skeletonization_cache
    _skeletonization_cache.clear()
    logger.info("Cleared skeletonization cache")


def get_skeletonization_stats() -> Dict[str, int]:
    """Get statistics about skeletonization cache."""
    true_count = sum(1 for v in _skeletonization_cache.values() if v)
    false_count = sum(1 for v in _skeletonization_cache.values() if not v)
    return {
        "cache_size": len(_skeletonization_cache),
        "skeletonize_true": true_count,
        "skeletonize_false": false_count
    }


def _detect_repeated_structures(root: ET.Element) -> List[Tuple[ET.Element, List[ET.Element]]]:
    """Detect containers with repeated child structures.
    
    Returns list of (container_element, [child_elements]) tuples.
    Enhanced detection considers:
    - Direct children with similar structure
    - Container attributes suggesting lists (recyclerview, listview, etc.)
    - Minimum 3 similar items required
    """
    repeated = []
    
    def traverse(element: ET.Element):
        children = list(element)
        if len(children) >= 3:  # Need at least 3 children
            
            # Check container attributes for list indicators
            container_attrs = ' '.join(element.attrib.values()).lower()
            is_list_container = any(indicator in container_attrs for indicator in [
                'recyclerview', 'listview', 'scrollview', 'recycler', 'list', 'grid'
            ])
            
            # Check if children have similar structure
            first_child_tags = [child.tag for child in children[0]]
            if not first_child_tags:  # Skip if no structure
                return
            similar_count = 0
            
            for child in children[:min(6, len(children))]:  # Check first 6 children
                child_tags = [c.tag for c in child]
                if not child_tags:
                    continue
                # Allow for minor variations (80% similarity)
                similarity = len(set(first_child_tags) & set(child_tags)) / len(first_child_tags)
                if similarity >= 0.8:
                    similar_count += 1
            
            # Consider it a list if: many similar items OR explicit list container
            min_similar = 3 if not is_list_container else 2
            if similar_count >= min_similar:
                repeated.append((element, children))
                logger.debug(f"Detected repeated structure: {element.tag} with {len(children)} children ({similar_count} similar)")
        
        # Continue traversing (but avoid going too deep to prevent false positives)
        if len(list(element)) <= 10:  # Only traverse containers with reasonable number of children
            for child in element:
                traverse(child)
    
    traverse(root)
    return repeated


def _should_skeletonize_list(container: ET.Element, children: List[ET.Element]) -> bool:
    """Determine if a list of items should be skeletonized for hashing.
    
    DETERMINISTIC approach: Distinguishes between scrollable data lists (products, messages)
    vs distinct option lists (menus, navigation) without using LLM.
    
    Returns True for SAME_TYPE lists (should skeletonize - produce same hash when scrolled)
    Returns False for DIFFERENT_OPTIONS lists (don't skeletonize - different hash per configuration)
    """
    # Create a more detailed hash of the structure for caching
    container_info = f"{container.tag}:{container.attrib.get('class', '')}:{container.attrib.get('resource-id', '')}"
    structure_desc = f"{container_info}:{[child.tag for child in children[0]]}:{len(children)}"
    structure_hash = hashlib.md5(structure_desc.encode()).hexdigest()[:12]
    
    # Check cache first
    if structure_hash in _skeletonization_cache:
        return _skeletonization_cache[structure_hash]
    
    # Manage cache size
    if len(_skeletonization_cache) >= MAX_CACHE_SIZE:
        items_to_remove = len(_skeletonization_cache) - MAX_CACHE_SIZE + 1
        for key in list(_skeletonization_cache.keys())[:items_to_remove]:
            del _skeletonization_cache[key]
    
    # ===== DETERMINISTIC HEURISTICS =====
    
    container_class = container.attrib.get('class', '').lower()
    container_id = container.attrib.get('resource-id', '').lower()
    is_scrollable = container.attrib.get('scrollable') == 'true'
    
    # HEURISTIC 1: Container class indicators
    # RecyclerView, ListView, GridView with scrollable=true are typically data lists
    data_list_indicators = ['recyclerview', 'listview', 'gridview', 'adapterview', 'scrollview']
    menu_list_indicators = ['navigation', 'nav', 'menu', 'tab', 'drawer', 'bottomnavigation']
    
    has_data_indicator = any(ind in container_class for ind in data_list_indicators)
    has_menu_indicator = any(ind in container_id or ind in container_class for ind in menu_list_indicators)
    
    # If explicitly a menu/navigation container, don't skeletonize
    if has_menu_indicator:
        _skeletonization_cache[structure_hash] = False
        logger.debug(f"Menu container detected (id/class indicator): {container_id}")
        return False
    
    # HEURISTIC 2: Analyze item text patterns
    # Data lists: items have similar text patterns (prices, dates, etc.)
    # Menu lists: items have distinct, unique text labels
    
    item_text_signatures = []
    for child in children[:min(5, len(children))]:
        # Collect all text from this item
        texts = []
        for el in child.iter():
            if el.text and el.text.strip():
                texts.append(el.text.strip().lower())
        
        # Create a signature based on text characteristics
        signature = {
            'count': len(texts),
            'has_price': any('$' in t or any(c.isdigit() for c in t) for t in texts),
            'has_short_label': any(len(t) < 20 and t.isalpha() for t in texts),
            'texts': texts
        }
        item_text_signatures.append(signature)
    
    # If we have enough items to analyze
    if len(item_text_signatures) >= 3:
        # Check for price patterns (strong indicator of product list)
        price_pattern_count = sum(1 for sig in item_text_signatures if sig['has_price'])
        if price_pattern_count >= len(item_text_signatures) * 0.6:
            # Most items have prices - likely a product list
            _skeletonization_cache[structure_hash] = True
            logger.debug(f"Product list detected (price pattern): {container_id}")
            return True
        
        # Check for unique short labels (menu items typically have these)
        all_texts = []
        for sig in item_text_signatures:
            all_texts.extend(sig['texts'])
        
        # Menu items: each has a unique, short label
        # Product items: may have similar text ("Add to cart", "$XX.XX")
        unique_texts = set(all_texts)
        if len(unique_texts) >= len(item_text_signatures) * 1.5:
            # Many unique texts suggests menu/navigation
            _skeletonization_cache[structure_hash] = False
            logger.debug(f"Menu list detected (unique labels): {container_id}")
            return False
    
    # HEURISTIC 3: Check resource IDs of items
    # Data list items often have sequential or no IDs
    # Menu items often have descriptive IDs
    item_ids = []
    for child in children[:min(4, len(children))]:
        rid = child.attrib.get('resource-id', '')
        if rid:
            item_ids.append(rid.lower())
    
    if item_ids:
        # Check for sequential numbering (item_1, item_2, etc.)
        has_sequential = any('_' in rid and rid.rsplit('_', 1)[-1].isdigit() for rid in item_ids)
        
        # Check for descriptive IDs (home, settings, profile, etc.)
        descriptive_patterns = ['home', 'settings', 'profile', 'account', 'menu', 'nav', 'tab']
        has_descriptive = any(any(p in rid for p in descriptive_patterns) for rid in item_ids)
        
        if has_descriptive and not has_sequential:
            _skeletonization_cache[structure_hash] = False
            logger.debug(f"Menu list detected (descriptive IDs): {container_id}")
            return False
        
        if has_sequential and not has_descriptive:
            _skeletonization_cache[structure_hash] = True
            logger.debug(f"Data list detected (sequential IDs): {container_id}")
            return True
    
    # HEURISTIC 4: Scrollable + data indicator = skeletonize
    # Non-scrollable or menu indicator = don't skeletonize
    if is_scrollable and has_data_indicator:
        _skeletonization_cache[structure_hash] = True
        logger.debug(f"Data list detected (scrollable + data indicator): {container_id}")
        return True
    
    # DEFAULT: Don't skeletonize if uncertain (safer for navigation detection)
    _skeletonization_cache[structure_hash] = False
    logger.debug(f"Default: not skeletonizing (uncertain): {container_id}")
    return False


def _skeletonize_container(container: ET.Element, children: List[ET.Element]):
    """Replace a list of similar items with a single skeleton item for hashing.
    
    Preserves structure but replaces variable content with placeholders.
    """
    if not children:
        return
    
    first_child = children[0]
    
    # Clear all children
    container.clear()
    
    # Add back a single skeletonized child
    skeleton = ET.SubElement(container, first_child.tag, first_child.attrib)
    
    # Copy the structure but replace variable content with placeholders
    def copy_skeleton(source: ET.Element, dest: ET.Element, depth=0):
        # Preserve structural attributes but clear variable ones
        dest.attrib = source.attrib.copy()
        for attr in ["text", "content-desc", "resource-id", "bounds"]:
            if attr in dest.attrib:
                # Use more specific placeholders based on attribute type
                if attr == "text":
                    dest.attrib[attr] = "[TEXT]"
                elif attr == "content-desc":
                    dest.attrib[attr] = "[DESC]"
                elif attr == "resource-id":
                    # Preserve the base pattern but replace variable parts
                    rid = dest.attrib[attr]
                    # Replace numbers and dynamic parts with placeholders
                    import re
                    rid = re.sub(r'\d+', '[N]', rid)
                    dest.attrib[attr] = rid
                else:
                    dest.attrib[attr] = "[VAR]"
        
        # Handle text content
        if source.text and source.text.strip():
            # Keep short structural text, replace variable content
            if len(source.text.strip()) <= 20 and not any(c.isdigit() for c in source.text):
                dest.text = source.text  # Preserve structural text like "Item" or "$"
            else:
                dest.text = "[CONTENT]"
        else:
            dest.text = source.text
        
        dest.tail = source.tail
        
        # Copy children but limit depth to prevent infinite recursion
        if depth < 4:
            for child in source:
                child_copy = ET.SubElement(dest, child.tag, child.attrib)
                copy_skeleton(child, child_copy, depth + 1)
    
    copy_skeleton(first_child, skeleton)
    logger.debug(f"Skeletonized container: kept 1 item, removed {len(children) - 1}")


def _apply_skeletonization(root: ET.Element):
    """Apply skeletonization to repeated structures in the XML.
    
    Enhanced with safety checks and better error handling.
    """
    if not SKELETONIZATION_ENABLED:
        return
        
    try:
        repeated_structures = _detect_repeated_structures(root)
        skeletonized_count = 0
        
        for container, children in repeated_structures:
            try:
                if _should_skeletonize_list(container, children):
                    _skeletonize_container(container, children)
                    skeletonized_count += 1
            except Exception as e:
                logger.warning(f"Failed to skeletonize container {container.tag}: {e}")
                continue
        
        if skeletonized_count > 0:
            logger.info(f"Applied skeletonization to {skeletonized_count} containers")
            
    except Exception as e:
        logger.warning(f"Skeletonization failed: {e}")
        # Continue without skeletonization if it fails


class Memory:
    def __init__(self):
        self.short_term_memory = []  # Stores (action, state) tuples for the current session
        self.long_term_memory = []   # Stores summaries of past sessions or critical findings

    def add_to_short_term(self, action, state_summary):
        """Adds an action and its resulting state to short-term memory."""
        timestamp = datetime.datetime.now()
        self.short_term_memory.append({
            "timestamp": timestamp,
            "action": action,
            "state_summary": state_summary
        })

    def add_state_signature(self, signature: str):
        # timestamp = datetime.datetime.now()
        self.short_term_memory.append({
            # "timestamp": timestamp,
            "action": {"action": "_state"},
            "state_summary": signature,
        })

    def get_short_term_history(self, last_n=5):
        """Retrieves the last N actions and states from short-term memory."""
        return self.short_term_memory[-last_n:]

    def has_been_in_loop(self, state_summary, lookback=3):
        """
        Checks if the agent has been in a loop by seeing if the same state
        has appeared multiple times recently.
        """
        if len(self.short_term_memory) < lookback:
            return False
        
        recent_states = [mem["state_summary"] for mem in self.short_term_memory[-lookback:]]
        return recent_states.count(state_summary) > 1

    def count_recent_state(self, signature: str, window: int = 10) -> int:
        recent = [m["state_summary"] for m in self.short_term_memory[-window:]]
        return recent.count(signature)

    def clear_short_term(self):
        """Clears the short-term memory, typically at the end of a session."""
        self.short_term_memory = []

    def add_to_long_term(self, finding):
        """Adds a significant finding (like a bug) to long-term memory."""
        timestamp = datetime.datetime.now()
        self.long_term_memory.append({
            "timestamp": timestamp,
            "finding": finding
        })


def state_signature_from_xml(page_source: str, activity: str = "") -> str:
    """
    Generate a semantic fingerprint for the current screen.
    
    DEPRECATED: This function now uses semantic fingerprinting instead of
    XML structure hashing. Pass the activity name for best results.
    
    Args:
        page_source: XML page source from Appium
        activity: Current Android activity name (recommended for accurate fingerprinting)
        
    Returns:
        16-character hex hash string
    """
    # Import here to avoid circular imports
    try:
        from semantic_fingerprint import SemanticFingerprint
        fp = SemanticFingerprint.from_xml(page_source, activity or "unknown")
        return fp.semantic_hash
    except ImportError:
        # Fallback to old implementation if semantic_fingerprint not available
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(page_source)
            _apply_skeletonization(root)
            
            for el in root.iter():
                for attr in [
                    "text", "content-desc", "resource-id", "bounds", "index", "checked", "selected", "focused", "scrollable", "password", "long-clickable", "enabled", "displayed"
                ]:
                    if attr in el.attrib:
                        el.attrib[attr] = ""
                el.text = ""
                el.tail = ""
            normalized = ET.tostring(root, encoding="utf-8", method="xml")
        except Exception:
            normalized = " ".join((page_source or "").split()).encode('utf-8')
        return hashlib.sha256(normalized).hexdigest()[:16]
