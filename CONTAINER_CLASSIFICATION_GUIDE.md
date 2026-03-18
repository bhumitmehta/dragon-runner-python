# Container Classification + Screen Template Integration

## Problem Statement

The explorer faced two cascading problems:

### 1. **Same Screen, Different Hashes**
```
ProductPage(iPhone)  →  hash_abc123
ProductPage(Samsung) →  hash_def456
ProductPage(Google)  →  hash_ghi789

Result: Explorer thinks 3 different screens, tries to visit all
Reality: Same template, only needs 2-3 samples
```

### 2. **Container Type Inference**
```
List with 50 items
├─ If content list (products):     Sample 2-3, skip rest
├─ If navigation menu:              Visit all
├─ If filter options:               Toggle each
└─ If unknown:                      Investigate!
```

---

## Solution Architecture

### Layer 1: Screen Template Matching (`screen_template_matcher.py`)

**Purpose**: Normalize screen identities by structure, not content

**How it works**:
1. Extract structural XML (tag hierarchy, not text/values)
2. Compute normalized "template signature" from structure
3. Group screens by >0.85 Jaccard similarity
4. Maps: screen_sig → template_sig

**Result**:
```
hash_abc123 ──→ template_xyz (ProductDetailTemplate)
hash_def456 ──→ template_xyz ✓ Same!
hash_ghi789 ──→ template_xyz ✓ Same!
```

**Benefits**:
- Visit count now applies across template variations
- Avoids re-exploring essentially identical screens
- 30-50% reduction in exploration steps

---

### Layer 2: Container Classification (`container_classifier.py`)

**Purpose**: Determine semantic type (content list / navigation menu / option list)

**Pipeline**:
```
Container XML
    ↓
1. Deterministic Heuristics (no cost)
   - Keyword matching (price, rating, settings, profile, etc.)
   - Element type detection (RadioButton, Checkbox → option list)
   - Repeating structure detection
   ↓ (confidence < 0.6?)
2. Behavioral Inference (gathered during exploration)
   - Did multiple items lead to same screen? → Content list
   - Different screens? → Navigation
   - State changed, same screen? → Options
   ↓ (still uncertain?)
3. LLM Classification (expensive, rare)
   - Last resort for ambiguous containers
   - Structured prompt for classification
   ↓
4. Cache Result (KB storage)
   - Next run: immediate classification from cache
```

**Output for Each Container**:
```json
{
  "container_type": "CONTENT_LIST",
  "confidence": 0.92,
  "reasoning": "Text signals (price, rating, product) + repeating structure",
  "strategy": "Sample 2-3 items only"
}
```

---

## Integration into Explorer

### Decision Flow Modification

**Before**:
```
pick_next_action()
  ├─ Get all untried elements
  ├─ Score each individually
  ├─ Select highest score
  └─ Click element
```

**After**:
```
pick_next_action()
  ├─ Get all untried elements
  ├─ Identify containers (Lists, Menus, etc.)
  ├─ Classify each container
  │  ├─ If CONTENT_LIST:
  │  │  └─ Sample only 2-3 items (add rest to backlog)
  │  ├─ If NAVIGATION_LIST:
  │  │  └─ Include all items in scoring
  │  └─ If OPTION_LIST:
  │     └─ Toggle each, but treat as low priority
  ├─ Apply Phase 1 scoring to candidate elements
  ├─ Score screens using template matching
  │  └─ If screen_sig maps to known template → use template visit count
  ├─ Select highest score
  └─ Execute action
```

---

## Code Integration Points

### 1. Explorer `__init__`

```python
def __init__(self, ...):
    # Existing initialization...
    
    # NEW: Container classification system
    from container_classifier import ContainerClassifier
    self.container_classifier = ContainerClassifier(
        vlm=vlm,  # For ambiguous cases
        knowledge_base=knowledge_base
    )
    
    # NEW: Screen template registry
    from screen_template_matcher import ScreenTemplateRegistry
    self.screen_template_registry = ScreenTemplateRegistry(
        knowledge_base=knowledge_base
    )
    self.screen_template_registry.load_from_kb()
```

### 2. Explorer `observe_new_screen()`

```python
def observe_new_screen(self, screen_sig, screen_source, description=""):
    """NEW/Enhanced: Register screen with template matching."""
    
    # Register with template system
    template_sig = self.screen_template_registry.register_screen(
        screen_sig, screen_source, description
    )
    
    # Existing SessionMemory registration still happens
    self.session_memory.record_screen(screen_sig, ...)
    
    # NEW: Analyze containers in this screen
    self._analyze_containers_in_screen(screen_sig, screen_source)
```

### 3. Explorer `_analyze_containers_in_screen()`

```python
def _analyze_containers_in_screen(self, screen_sig: str, screen_source: str):
    """NEW: Identify and classify all containers."""
    
    # Extract container XPaths/elements from screen
    containers = self._extract_containers(screen_source)
    
    for container_xpath, container_xml, element_texts in containers:
        # Try to classify
        classification = self.container_classifier.classify(
            container_sig=f"{screen_sig}#{container_xpath}",
            container_xml=container_xml,
            element_texts=element_texts,
            navigation_results=None  # Will update via observation
        )
        
        # Record classification decision
        if classification.container_type.value == "CONTENT_LIST":
            logger.info(f"Content list detected in {screen_sig}, will sample 2-3 items only")
        
        self._container_classifications[f"{screen_sig}#{container_xpath}"] = classification
```

### 4. Explorer `pick_next_action()` - MODIFIED

```python
def pick_next_action(self):
    """Enhanced with container-aware element selection."""
    
    current_screen = self.session_memory.get_current_screen()
    untried = self._get_untried_elements()
    
    if not untried:
        return None
    
    # NEW: Group elements by container
    elements_by_container = self._group_elements_by_container(untried)
    
    candidates = []
    for container_id, elements in elements_by_container.items():
        # Get classification for this container
        classification = self._container_classifications.get(container_id)
        
        if classification:
            container_type = classification.container_type.value
            
            if container_type == "CONTENT_LIST":
                # Sample only first 2-3 items from list
                sampled = elements[:3]
                candidates.extend(sampled)
                logger.debug(f"Content list: sampling {len(sampled)} of {len(elements)} items")
                
            elif container_type == "NAVIGATION_LIST":
                # Include all navigation items
                candidates.extend(elements)
                logger.debug(f"Navigation list: including all {len(elements)} items")
                
            elif container_type == "OPTION_LIST":
                # Include but lower priority
                candidates.extend(elements)
                logger.debug(f"Option list: including all {len(elements)} options")
            else:
                # Unknown - be conservative, sample 5
                candidates.extend(elements[:5])
        else:
            # No classification yet - include all for now
            candidates.extend(elements)
    
    # Phase 1: Score candidates
    scored = self._score_candidates(candidates, ...)
    
    if scored and scored[0][1] > -0.5:
        return self._create_click_action(scored[0][0])
    
    # Fallback
    return self._fallback_selection(candidates)
```

### 5. Explorer `record_transition()` - ENHANCED

```python
def record_transition(self, from_sig: str, element_id: str, to_sig: str):
    """Enhanced to update container classifications via behavior."""
    
    # Existing logic...
    self._element_target_screens[element_id].add(to_sig)
    
    # NEW: Gather behavioral evidence for classification updates
    container_id = self._get_container_for_element(element_id)
    
    if container_id not in self._container_observations:
        self._container_observations[container_id] = []
    
    # Record: "clicking element_id led to screen to_sig"
    self._container_observations[container_id].append({
        "element_id": element_id,
        "target_screen_sig": to_sig,
        "target_screen_desc": "..."  # Get from screen state
    })
    
    # If we have 3+ observations, try to reclassify
    if len(self._container_observations[container_id]) >= 3:
        self._attempt_behavioral_reclassification(container_id)
```

### 6. Explorer `_score_candidates()` - MODIFIED

```python
def _score_candidates(self, candidates, sig, memory, ui_context):
    """Modified to use template visit counts."""
    
    scores = []
    
    for element_id in candidates:
        score = 0.0
        
        # Get target screens for this element (from Phase 1)
        target_screens = self._element_target_screens.get(element_id, set())
        
        # Count visits using TEMPLATE MATCHING not direct sig
        template_visits = 0
        for target_sig in target_screens:
            template = self.screen_template_registry.get_template_for_screen(target_sig)
            if template:
                # All screens in template count as "visited"
                template_visits += len(template.screen_sigs)
            else:
                # No template → count direct visits
                template_visits += memory.get_screen_visit_count(target_sig)
        
        # Phase 1 scoring (existing formula)
        exploration_balance = max(0, 1.0 - (template_visits / 20))
        score += 0.3 * exploration_balance
        
        # ... rest of scoring factors ...
        
        scores.append((element_id, score))
    
    return sorted(scores, key=lambda x: x[1], reverse=True)
```

---

## Cross-Session Learning

### Knowledge Base Storage

**Table: `container_classifications`**
```json
{
  "sig": "screen_abc#RecyclerView_2",
  "type": "CONTENT_LIST",
  "confidence": 0.92,
  "reasoning": "...",
  "strategy": "..."
}
```

**Table: `screen_templates`**
```json
{
  "template_sig": "template_xyz_16h",
  "screen_sigs": ["hash_abc123", "hash_def456", "hash_ghi789"],
  "description": "ProductDetailTemplate: Header + ScrollView + Image + LinearLayout",
  "samples": ["iPhone 15 product page", "Samsung Galaxy product page"]
}
```

**Benefits**:
1. First run: Deterministic + LLM on ambiguous
2. Subsequent runs: Cache hit immediately
3. Learns which containers are truly products vs menus
4. Learns which screens are variations of same template

---

## Behavioral Reclassification

When explorer collects evidence, it can refine classifications:

```python
def _attempt_behavioral_reclassification(self, container_id):
    """Re-classify container based on collected behavior."""
    
    navigation_results = self._container_observations[container_id]
    
    # Run behavioral classifier
    behav_type, behav_conf, behav_reason = BehavioralClassifier.analyze_navigation_results(
        navigation_results
    )
    
    # If behavioral result differs from heuristic AND has higher confidence
    current = self._container_classifications.get(container_id)
    
    if behav_conf > current.confidence + 0.15:  # Significant improvement
        logger.info(f"Reclassifying {container_id}: {current.container_type.value} → {behav_type.value}")
        
        # Update classification
        new_classification = ContainerClassification(
            container_type=behav_type,
            confidence=behav_conf,
            reasoning=behav_reason,
            strategy=current.strategy,  # TODO: update strategy
            source="behavioral"
        )
        
        self._container_classifications[container_id] = new_classification
        
        # Update KB
        # ... save to DB ...
```

---

## Expected Impact

### Metric 1: Exploration Efficiency
- **Before**: Sample all items in list of 50 items → 50 clicks
- **After**: Detect content list → sample 2-3 → 3 clicks
- **Save**: 94% reduction for product catalogs

### Metric 2: Screen Discovery
- **Before**: hash_abc123, hash_def456, hash_ghi789 counted as 3 unique screens
- **After**: All grouped under ProductDetailTemplate → template_count = 3 visits
- **Impact**: Avoids "false positives" in coverage metrics

### Metric 3: Navigation Accuracy
- **Before**: Random menu selection
- **After**: Identified NAVIGATION_LIST → systematic visit each → complete map
- **Impact**: Better understanding of app structure

### Metric 4: LLM Token Usage
- **Before**: Classify every ambiguous container
- **After**: Heuristics first, LLM only on ~10% ambiguous cases
- **Save**: 90% fewer LLM calls after learning phase

---

## Configuration

### Sampling Strategy for Content Lists
```python
# explorer.py config
CONTENT_LIST_SAMPLE_SIZE = 3  # Sample 3 items typically
CONTENT_LIST_SAMPLE_SIZE_LARGE = 5  # Larger lists sample up to 5
CONTENT_LIST_PAGINATED_THRESHOLD = 10  # Test pagination sign
```

### LLM Classification Threshold
```python
CONFIDENCE_THRESHOLD_FOR_LLM = 0.60  # Call LLM if heuristics < 0.60
```

### Template Similarity
```python
STRUCTURE_SIMILARITY_THRESHOLD = 0.85  # Jaccard > 0.85 = same template
```

---

## Future Enhancements

### 1. Dynamic Resampling
If content list has pagination, sample first page, then 1-2 items from subsequent pages.

### 2. Smart Feature Detection
Combine container classification with feature clustering (Phase 5) to group products by feature area.

### 3. Semantic Link Prediction
"If user is on product list and clicks 'Filters', it's probably an option list" - use context.

### 4. Cross-App Transfer Learning
Store patterns across multiple apps - "Most product lists use RecyclerView + Image + Title + Price".

---

## Testing

### Unit Tests
```python
# test_container_classifier.py
def test_heuristic_classifier_product_list():
    xml = """<RecyclerView>...<Text>$999</Text>...</RecyclerView>"""
    typ, conf, _ = HeuristicClassifier.classify_heuristic(xml, ["iPhone", "$999", "rating"])
    assert typ == ContainerType.CONTENT_LIST
    assert conf > 0.7

def test_heuristic_classifier_menu():
    xml = """<LinearLayout>...<RadioButton>Settings</RadioButton>...</LinearLayout>"""
    typ, conf, _ = HeuristicClassifier.classify_heuristic(xml, ["Settings", "Profile", "Logout"])
    assert typ == ContainerType.NAVIGATION_LIST or ContainerType.OPTION_LIST  # Both valid
    assert conf > 0.7
```

### Integration Tests
```python
# test_screen_templates.py
def test_product_pages_grouped():
    registry = ScreenTemplateRegistry()
    
    sig1 = registry.register_screen("hash1", product_page_xml_1, "Product 1")
    sig2 = registry.register_screen("hash2", product_page_xml_2, "Product 2")
    
    assert sig1 == sig2  # Same template
    assert len(registry.get_all_screens_for_template("hash1")) == 2
```
