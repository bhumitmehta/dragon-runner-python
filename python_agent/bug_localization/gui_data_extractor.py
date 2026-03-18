"""
GUI Data Extractor for Bug Localization

Extracts Screen Component (SC) terms and GUI Screen (GS) terms from
execution traces to improve bug localization accuracy.

Supports **two** trace formats:

1. **Ladybug format** — ``Execution-1.json`` with
   ``steps[].screen.dynGuiComponents[].idXml`` and
   ``steps[].screen.activity``  (Android GUI-instrumentation tools).

2. **Appium / AI-Agent format** — our agent records each step with
   ``page_source`` (raw XML from UiAutomator2) plus metadata such as
   ``accessibility_ids``, ``resource_ids``, ``screen_name``, and
   ``activity``.

The adapter code converts Appium page-source XML into the same SC/GS
term lists that Ladybug's embedding pipeline expects.
"""

import json
import re
import xml.etree.ElementTree as ET
from typing import Optional


# ────────────────────────────────────────────────────────────────────
#  Appium XML → SC / GS terms
# ────────────────────────────────────────────────────────────────────

def _extract_sc_terms_from_appium_xml(page_source: str) -> set[str]:
    """Parse Appium page-source XML and return resource-ids & content-desc values."""
    terms: set[str] = set()
    if not page_source:
        return terms
    try:
        root = ET.fromstring(page_source)
    except ET.ParseError:
        return terms

    for node in root.iter():
        # resource-id  (e.g. "com.saucelabs.mydemoapp.rn:id/loginBtn")
        rid = node.attrib.get("resource-id", "")
        if rid:
            short = rid.rsplit("/", 1)[-1]  # keep only the id name
            if short and short not in ("", "NO_ID"):
                terms.add(short)
        # content-desc (accessibility label)
        cdesc = node.attrib.get("content-desc", "")
        if cdesc and len(cdesc) > 1:
            terms.add(cdesc)
        # text attribute (only meaningful short labels)
        txt = node.attrib.get("text", "")
        if txt and 2 < len(txt) < 40:
            terms.add(txt)
    return terms


def _extract_gs_terms_from_appium_xml(page_source: str) -> set[str]:
    """Extract Activity / package identifiers from Appium XML root attributes."""
    terms: set[str] = set()
    if not page_source:
        return terms
    try:
        root = ET.fromstring(page_source)
    except ET.ParseError:
        return terms

    # UiAutomator2 puts package on the root node
    pkg = root.attrib.get("package", "")
    if pkg:
        terms.add(pkg.rsplit(".", 1)[-1])  # e.g. "rn"

    # Some drivers add activity in the hierarchy
    for node in root.iter():
        activity = node.attrib.get("activity", "")
        if activity:
            # Strip java-style package prefix
            short = activity.rsplit(".", 1)[-1]
            if short:
                terms.add(short)
    return terms


# ────────────────────────────────────────────────────────────────────
#  Unified SC / GS extraction – handles BOTH formats
# ────────────────────────────────────────────────────────────────────


def extract_sc_terms(trace_data: Optional[str | dict]) -> list[str]:
    """
    Extract Screen Component terms from an execution trace.
    
    SC terms are the XML IDs / accessibility labels of UI components that
    were interacted with.  Supports:
    - Ladybug format (``steps[].screen.dynGuiComponents[].idXml``)
    - Appium/agent format (``steps[].page_source`` XML or explicit lists)
    
    Args:
        trace_data: JSON string or dict containing the execution trace
        
    Returns:
        List of screen component term strings
    """
    if trace_data is None:
        return []
        
    # Parse JSON if string
    if isinstance(trace_data, str):
        try:
            data = json.loads(trace_data)
        except json.JSONDecodeError:
            # Might be raw Appium XML – try that
            return list(_extract_sc_terms_from_appium_xml(trace_data))
    else:
        data = trace_data
        
    # Handle different trace formats
    steps = data.get("steps", data.get("trace", data.get("actions", [])))
    
    if not steps:
        return []
        
    # Get last 4 steps (buggy state area)
    last_4_steps = steps[-4:] if len(steps) >= 4 else steps
    sc_terms: set[str] = set()
    
    for step in last_4_steps:
        # ── Appium page_source XML (our agent format) ──
        page_source = step.get("page_source", "")
        if page_source:
            sc_terms.update(_extract_sc_terms_from_appium_xml(page_source))

        # ── Explicit resource-id / accessibility-id lists from our agent ──
        for rid in step.get("resource_ids", step.get("accessibility_ids", [])):
            if isinstance(rid, str) and rid:
                short = rid.rsplit("/", 1)[-1]
                if short:
                    sc_terms.add(short)

        # Handle different step formats
        screen = step.get("screen", step.get("ui_state", {}))
        
        # Format 1: dynGuiComponents from Ladybug
        dyn_gui_components = screen.get("dynGuiComponents", [])
        for component in dyn_gui_components:
            id_xml = component.get("idXml", "")
            if id_xml:
                # Extract ID after last "/"
                sc_term = id_xml.rsplit("/", 1)[-1]
                if sc_term:
                    sc_terms.add(sc_term)
                    
        # Format 2: UI elements from our AI agent
        ui_elements = step.get("ui_elements", step.get("elements", []))
        for element in ui_elements:
            # Resource ID
            resource_id = element.get("resource-id", element.get("resourceId", ""))
            if resource_id:
                sc_term = resource_id.rsplit("/", 1)[-1]
                if sc_term:
                    sc_terms.add(sc_term)
                    
            # Accessibility ID
            acc_id = element.get("accessibility-id", element.get("accessibilityId", ""))
            if acc_id:
                sc_terms.add(acc_id)
                
            # Content description
            content_desc = element.get("content-desc", element.get("contentDesc", ""))
            if content_desc and len(content_desc) > 2:
                sc_terms.add(content_desc)
                
        # Format 3: Direct action targets
        action = step.get("action", {})
        if isinstance(action, dict):
            target = action.get("target", action.get("element", {}))
            if isinstance(target, dict):
                for key in ['resource-id', 'resourceId', 'accessibility-id', 'accessibilityId',
                            'locator', 'locator_value']:
                    val = target.get(key, "")
                    if val:
                        sc_term = str(val).rsplit("/", 1)[-1]
                        if sc_term:
                            sc_terms.add(sc_term)
            # Also extract locator from action itself
            locator = action.get("locator", action.get("locator_value", ""))
            if locator and isinstance(locator, str):
                short = locator.rsplit("/", 1)[-1]
                if short and len(short) > 2:
                    sc_terms.add(short)
    
    # Remove unimportant/generic terms
    unimportant_words = {
        "NO_ID", "BACK_MODAL", "null", "undefined", "none", 
        "root", "content", "container", "layout", "view",
        "hierarchy", "android.widget.FrameLayout",
    }
    
    for word in unimportant_words:
        sc_terms.discard(word)
        
    return list(sc_terms)


def extract_gs_terms(trace_data: Optional[str | dict]) -> list[str]:
    """
    Extract GUI Screen terms from an execution trace.
    
    GS terms are the Activity/Fragment names representing screens.
    Supports:
    - Ladybug format (``steps[].screen.activity / .window``)
    - Appium/agent format (``steps[].activity``, ``steps[].screen_name``,
      or parsed from ``page_source`` XML)
    
    Args:
        trace_data: JSON string or dict containing the execution trace
        
    Returns:
        List of GUI screen term strings
    """
    if trace_data is None:
        return []
        
    # Parse JSON if string
    if isinstance(trace_data, str):
        try:
            data = json.loads(trace_data)
        except json.JSONDecodeError:
            # Might be raw XML
            return list(_extract_gs_terms_from_appium_xml(trace_data))
    else:
        data = trace_data
        
    # Handle different trace formats
    steps = data.get("steps", data.get("trace", data.get("actions", [])))
    
    if not steps:
        return []
        
    # Get last 4 steps
    last_4_steps = steps[-4:] if len(steps) >= 4 else steps
    gs_terms: set[str] = set()
    
    for step in last_4_steps:
        # ── Appium page_source XML ──
        page_source = step.get("page_source", "")
        if page_source:
            gs_terms.update(_extract_gs_terms_from_appium_xml(page_source))

        screen = step.get("screen", step.get("ui_state", {}))
        
        # Activity name (Android)
        activity = screen.get("activity", step.get("activity", ""))
        if activity:
            # Extract Activity name before "(Window..."
            gs_activity = re.search(r'(\w+)(\(Window.*\))', activity)
            if gs_activity:
                gs_terms.add(gs_activity.group(1))
            else:
                # Try to get last part of activity path
                activity_name = activity.rsplit(".", 1)[-1]
                if activity_name and activity_name not in ("Activity",):
                    gs_terms.add(activity_name)
                    
        # Window/Fragment name
        window = screen.get("window", screen.get("fragment", ""))
        if window:
            # Match FRAGMENT tag
            gs_window = re.search(r'FRAGMENT:(.+)', window)
            if gs_window and len(gs_window.group(1)) > 1:
                gs_terms.add(gs_window.group(1))
            else:
                # Extract fragment/view name
                window_name = window.rsplit(".", 1)[-1]
                if window_name and len(window_name) > 2:
                    gs_terms.add(window_name)
                    
        # Current screen name from our agent
        screen_name = step.get("screen_name", step.get("current_screen", ""))
        if screen_name:
            gs_terms.add(screen_name)

        # State signature can contain screen identifiers
        sig = step.get("state_signature", screen.get("state_signature", ""))
        if sig and isinstance(sig, str) and len(sig) > 3:
            if not sig.startswith("sig_"):
                gs_terms.add(sig)
            
    return list(gs_terms)


def check_if_term_exists(search_terms: list[str], file_content: str) -> bool:
    """
    Check if any search terms exist in file content.
    
    Args:
        search_terms: List of SC or GS terms to search for
        file_content: Content of a source file
        
    Returns:
        True if any term is found, False otherwise
    """
    for term in search_terms:
        if term in file_content:
            return True
    return False


def build_corpus(
    source_files: list[tuple[str, str, str]], 
    sc_terms: list[str],
    repo_info: Optional[dict] = None
) -> dict[str, bool]:
    """
    Build a corpus of files filtered by screen component terms.
    
    Files containing SC terms are prioritized as they're more likely
    to be related to the bug.
    
    Args:
        source_files: List of (path, filename, content) tuples
        sc_terms: Screen component terms to filter by
        repo_info: Optional repository information
        
    Returns:
        Dictionary mapping file paths to inclusion status
    """
    corpus = {}
    
    for file_path, filename, content in source_files:
        # Include file if it contains any SC terms
        if check_if_term_exists(sc_terms, content):
            corpus[str(file_path)] = True
        # Also include files that match GS terms by name
        elif any(term.lower() in filename.lower() for term in sc_terms):
            corpus[str(file_path)] = True
            
    return corpus


def get_boosted_files(
    source_files: list[tuple[str, str, str]], 
    gs_terms: list[str]
) -> list[str]:
    """
    Get list of files that should be boosted in rankings.
    
    Files matching GUI screen terms are boosted because they're
    more likely to contain the buggy code.
    
    Args:
        source_files: List of (path, filename, content) tuples
        gs_terms: GUI screen terms to match against
        
    Returns:
        List of file paths to boost
    """
    boosted = []
    
    for file_path, filename, content in source_files:
        # Boost files whose names contain GS terms
        for term in gs_terms:
            if term.lower() in filename.lower():
                boosted.append(str(file_path))
                break
            # Also check content for Activity/Fragment definitions
            if f"class {term}" in content or f"class {term}Activity" in content:
                boosted.append(str(file_path))
                break
                
    return boosted


class GUIDataExtractor:
    """
    Convenience class for extracting GUI-related data from execution traces.
    
    Designed to work with our AI agent's trace format as well as the 
    Ladybug format for compatibility.
    """
    
    def __init__(self, trace_data: Optional[str | dict] = None):
        """
        Initialize the extractor.
        
        Args:
            trace_data: Optional trace data to process immediately
        """
        self.trace_data = trace_data
        self._sc_terms: Optional[list[str]] = None
        self._gs_terms: Optional[list[str]] = None
        
    def load_trace(self, trace_data: str | dict):
        """
        Load trace data for extraction.
        
        Args:
            trace_data: JSON string or dict containing the trace
        """
        self.trace_data = trace_data
        self._sc_terms = None
        self._gs_terms = None
        
    def load_trace_from_file(self, file_path: str):
        """
        Load trace data from a JSON file.
        
        Args:
            file_path: Path to the trace JSON file
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            self.trace_data = json.load(f)
        self._sc_terms = None
        self._gs_terms = None
        
    @property
    def sc_terms(self) -> list[str]:
        """Get screen component terms (cached)."""
        if self._sc_terms is None:
            self._sc_terms = extract_sc_terms(self.trace_data)
        return self._sc_terms
    
    @property
    def gs_terms(self) -> list[str]:
        """Get GUI screen terms (cached)."""
        if self._gs_terms is None:
            self._gs_terms = extract_gs_terms(self.trace_data)
        return self._gs_terms
    
    @property
    def has_gui_data(self) -> bool:
        """Check if valid GUI data is available."""
        return bool(self.sc_terms or self.gs_terms)
        
    def filter_corpus(self, source_files: list[tuple]) -> dict:
        """
        Filter source files to build a focused corpus.
        
        Args:
            source_files: List of (path, filename, content) tuples
            
        Returns:
            Dictionary of files in the corpus
        """
        return build_corpus(source_files, self.sc_terms)
    
    def get_boosted_files(self, source_files: list[tuple]) -> list[str]:
        """
        Get files to boost in rankings.
        
        Args:
            source_files: List of (path, filename, content) tuples
            
        Returns:
            List of file paths to boost
        """
        return get_boosted_files(source_files, self.gs_terms)


if __name__ == "__main__":
    # Test with sample trace
    sample_trace = {
        "steps": [
            {
                "screen": {
                    "activity": "LoginActivity(Window-123)",
                    "window": "FRAGMENT:LoginFragment",
                    "dynGuiComponents": [
                        {"idXml": "com.app:id/username_input"},
                        {"idXml": "com.app:id/password_input"},
                        {"idXml": "com.app:id/submit_button"}
                    ]
                }
            },
            {
                "screen": {
                    "activity": "HomeActivity(Window-456)",
                    "window": "FRAGMENT:DashboardFragment"
                }
            }
        ]
    }
    
    print("Testing GUI Data Extractor...")
    extractor = GUIDataExtractor(sample_trace)
    
    print(f"SC Terms: {extractor.sc_terms}")
    print(f"GS Terms: {extractor.gs_terms}")
    print(f"Has GUI Data: {extractor.has_gui_data}")
