---
name: Developer-Attribute Screen Fingerprinting
overview: Replace the fragile XML-structure-hash fingerprinting with a developer-attribute-based approach that uses the sorted set of stable identifiers (content-desc, resource-id) already present in Appium XML to uniquely identify screens — the exact attributes app developers add for automation and accessibility.
todos:
  - id: new-fingerprint
    content: Implement screen_fingerprint_from_xml() in memory.py using sorted set of content-desc + resource-id values
    status: pending
  - id: activity-prefix
    content: Add get_current_activity() to AppiumController and use as coarse prefix in signature
    status: pending
  - id: dual-granularity
    content: Implement screen_id (coarse, for cache/graph) and state_id (fine, for Critic before/after) variants
    status: pending
  - id: update-callsites
    content: Update all 12 call sites across 7 files to use the new fingerprinting function
    status: pending
  - id: cleanup-dead-code
    content: Remove skeletonization logic and screen_template_matcher.py dead code
    status: pending
  - id: update-tests
    content: Update test_hash_runner.py with scroll-invariance, different-screen, modal, and no-identifier test cases
    status: pending
isProject: false
---

# Developer-Attribute Screen Fingerprinting

## Problem

The current `state_signature_from_xml()` in [memory.py](python_agent/memory.py) strips ALL dynamic attributes (including `resource-id` and `content-desc`) and hashes only the bare XML tag structure. This makes it **too coarse** — structurally similar screens (login vs registration) produce identical hashes. Yet the previous version was **too sensitive** — any scroll change produced a different hash. Four attempted solutions exist in the codebase, none integrated:

- `state_signature_from_xml()` — strips too much, hash collisions
- `screen_template_matcher.py` — Jaccard similarity with a broken comparison (compares hash to description string), never imported in main path
- `action_coverage.py` — right idea but never integrated; also doesn't solve VLM caching
- `PROBLEM_ANALYSIS_HASH_INCONSISTENCY.md` — documents the fundamental problem without a shipped fix

## Key Insight from Real Data

From the actual [window_dump.xml](window_dump.xml) and [window_dump1.xml](window_dump1.xml) — two dumps of the same screen at different scroll positions in the SauceLabs React Native app:

The `content-desc` attributes are **developer-assigned, stable, and semantic**:

- `"open menu"`, `"cart badge"`, `"product screen"`, `"product price"`, `"review star 1"` ... `"review star 5"`, `"Add To Cart button"`, `"counter minus button"`, `"counter plus button"`, `"product description"`

These identifiers are the same across scroll positions, across runs, across devices. They are the **ground truth** of screen identity because the developers put them there specifically for automation and accessibility.

## Proposed Approach: Sorted Identifier Set Hash

```
fingerprint = hash(sorted(
  content-desc values (non-empty) +
  resource-id values (non-empty, stripped of package prefix)
))
```

### Why this works

- **Deterministic**: Same set of identifiers = same hash, always
- **Scroll-invariant**: Scrolling reveals new content but the identifier set of the screen's semantic elements stays the same (the toolbar with "open menu", "cart badge" etc. is always present)
- **Semantically meaningful**: "product screen" + "Add To Cart button" + "review star 1..5" uniquely identifies a product detail page
- **Different across real screens**: Login screen has `"Username input field"`, `"Password input field"`, `"Login button"` — completely different set
- **No skeletonization needed**: We don't care about repeated items — we care about which *kinds* of interactive elements exist
- **No LLM calls**: Pure string operations

### Where it could fall short (and mitigations)

- **Screens with no identifiers**: Some poorly-built apps have no content-desc or resource-id on any element. Mitigation: fall back to class-hierarchy hash (the current approach, but only as fallback)
- **List items**: A product catalog might expose `"store item"` x 6, but a scrolled version might expose `"store item"` x 4. Mitigation: use the **set** (not list) of identifiers — `{"store item"}` is the same regardless of count
- **React Native specific**: RN apps use `testID` which maps to `content-desc`. Native apps tend to use `resource-id`. The approach handles both
- **Modals/drawers**: A drawer overlay adds new identifiers to the set, which changes the hash. This is **correct behavior** — a screen with an open drawer is a different state worth re-analyzing

## Implementation Plan

### Step 1: New fingerprinting function in `memory.py`

Replace `state_signature_from_xml()` with a new function:

```python
def screen_fingerprint_from_xml(page_source: str) -> str:
    root = ET.fromstring(page_source)
    identifiers: set[str] = set()

    for el in root.iter():
        desc = (el.attrib.get("content-desc") or "").strip()
        rid = (el.attrib.get("resource-id") or "").strip()
        # Strip package prefix from resource-id
        if "/" in rid:
            rid = rid.rsplit("/", 1)[-1]
        if desc:
            identifiers.add(f"d:{desc}")
        if rid:
            identifiers.add(f"r:{rid}")

    if not identifiers:
        # Fallback: use class-hierarchy hash for apps with no identifiers
        return _fallback_structure_hash(root)

    canonical = "\n".join(sorted(identifiers))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
```

### Step 2: Add Activity name as coarse prefix

Use Appium's `current_activity` (already available via `driver.current_activity`) as a coarse prefix. This prevents hash collisions between screens in different activities that happen to share similar elements:

```
signature = f"{activity_name}::{identifier_set_hash}"
```

This requires a small change to `AppiumController` to expose `get_current_activity()`.

### Step 3: Multi-granularity for different consumers

Provide two signatures to downstream consumers:

- `**screen_id**` (coarse): `activity + sorted identifier SET` — for VLM cache, screen graph, exploration "have I been here?"
- `**state_id**` (fine): `activity + sorted identifier SET + dynamic state attributes (checked, selected, focused, text of input fields)` — for Critic before/after comparison "did anything change?"

This prevents the Critic from thinking nothing changed when a checkbox was toggled (same identifiers, different `checked` state).

### Step 4: Update all call sites

Every call to `state_signature_from_xml(page_source)` needs to become `screen_fingerprint_from_xml(page_source)`. These are in:

- [agents/navigator.py](python_agent/agents/navigator.py) (3 call sites)
- [agents/explorer.py](python_agent/agents/explorer.py) (1 call site)
- [agents/script_executor.py](python_agent/agents/script_executor.py) (2 call sites)
- [agents/recovery.py](python_agent/agents/recovery.py) (1 call site)
- [agent.py](python_agent/agent.py) (2 call sites)
- [ai_tester.py](python_agent/ai_tester.py) (1 call site)
- [workflow_runner.py](python_agent/workflow_runner.py) (2 call sites)

### Step 5: Clean up dead code

Remove or deprecate:

- `_apply_skeletonization()`, `_should_skeletonize_list()`, `_skeletonize_container()`, `_detect_repeated_structures()` from [memory.py](python_agent/memory.py)
- [screen_template_matcher.py](python_agent/screen_template_matcher.py) — never integrated, contains broken comparison logic
- Skeletonization cache and heuristics

### Step 6: Update tests

Update [test_hash_runner.py](python_agent/test_hash_runner.py) to test the new fingerprinting with scenarios:

- Same screen at different scroll positions (should match)
- Different screens with different identifiers (should differ)
- Modal/drawer overlay on a screen (should differ)
- Screen with no identifiers (fallback behavior)

## Scope of Change

- **Core change**: ~50 lines in `memory.py` (new function + fallback)
- **Small addition**: ~5 lines in `appium_controller.py` (expose `current_activity`)
- **Mechanical updates**: ~12 call sites across 7 files (rename function)
- **Cleanup**: ~200 lines of dead skeletonization code removed
- **Tests**: update existing test file

## What This Does NOT Change

- The VLM cache mechanism in [vlm.py](python_agent/vlm.py) — it already keys on `state_sig`, it just gets a better key
- The KnowledgeBase or SessionMemory data structures — signatures are stored as opaque strings
- The Explorer / ExecutionEngine logic — they consume signatures, they don't produce them
- The action_coverage.py module — it remains available as an orthogonal exploration strategy

