# Before vs After: Container Classification in Action

## Scenario 1: Product Catalog Exploration

### BEFORE (Naive Depth-First)
```
User opens e-commerce app → ProductList (50 items)

Explorer sees: 50 untried elements
Explorer thinks: "I must try all of them!"

Action sequence:
  1. Click Product1 → ProductDetailPage (iPhone) → sig_abc
  2. Back to list
  3. Click Product2 → ProductDetailPage (Samsung) → sig_def  
  4. Back to list
  5. Click Product3 → ProductDetailPage (Google) → sig_ghi
  ... repeats for all 50 products ...
  51. Back to list after Product50

Result:
- Exploration time: 250 seconds (5 sec per navigation)
- Screen count: 51 screens (50 unique ProductDetail + 1 List)
- Actual knowledge: "This app has a list and details pages"
- Efficiency: POOR - Explored product variations instead of new features
```

### AFTER (Intelligent Content-Aware)
```
User opens e-commerce app → ProductList (50 items)

Explorer's new pipeline:
1. analyze_new_screen_containers()
   ├─ Detects RecyclerView + [Image, Title, Price, Rating] repeated
   ├─ UIStructureAnalyzer extracts structural pattern
   └─ compute_structure_signature() → "PRODUCT_DETAIL_TEMPLATE"

2. container_classifier.classify()
   ├─ HeuristicClassifier scores text signals
   │  └─ Found: price(0.8) + rating(0.7) + "add to cart"(0.9) = 0.85 confidence
   ├─ Confidence > 0.6 → no need for LLM
   └─ Result: CONTENT_LIST with strategy "Sample 2-3 items only"

3. pick_next_action() applies classification
   ├─ Get untried elements from list
   ├─ Group by container
   ├─ See container is CONTENT_LIST
   └─ Sample only first 3 items: [Product1, Product2, Product3]

4. Interaction sequence:
   - Click Product1 → screen_abc (iPhone)
   - Back to list
   - Click Product2 → screen_def (Samsung)
   - Back to list
   - Click Product3 → screen_ghi (Google)
   - Back to list ← STOPS HERE, rest are low-priority

5. Template registration (Phase 4):
   - screen_abc + screen_def + screen_ghi → "template_xyz"
   - get_normalized_visit_count("screen_abc") → 3 (all samples under template)
   - Future scoring: knows ProductDetail space is explored

Result:
- Exploration time: 30 seconds (1/8th the time!)
- Actions: 3 product clicks (vs 50)
- Screen count: 3 actual variations grouped under 1 template
- Knowledge: "Product detail template fully sampled, can explore other features now"
- Efficiency: 8x better - time spent on new areas instead of variations
- Tokens saved: 0 (heuristic covered it, LLM not needed)

Example log output:
```
[Explorer] Screen 'ProductList' detected patterns:
  - PRODUCT_LIST (RecyclerView, repeat: Image+Title+Price+Rating, confidence=0.92)
[Explorer] Container 'ProductList#RecyclerView_0' classified:
  - Type: CONTENT_LIST
  - Strategy: Sample only 2-3 items
  - Source: heuristic (confidence=0.92)
[Explorer] Scoring candidates (50 untried in list):
  - Candidate #1: Product1 (score=1.1) [new_screen=0.5 | explore=0.4 | feature=0.2]
  - Candidate #2: Product2 (score=0.9) [new_screen=0.5 | explore=0.4 | feature=0.0]
  - Candidate #3: Product3 (score=0.8) [new_screen=0.5 | explore=0.3 | feature=0.0]
  - (Remaining 47 items scored <0.2 due to repetition penalty)
[Explorer] Selected action: Click Product1 (score=1.1)
[Explorer] Learned: 'Product1' navigates ProductList → ProductDetailPage
[Explorer] Screen 'ProductDetailPage' registered:
  - Template: template_xyz (structure signature match with Product2, Product3)
  - Cached in KB for future runs
```

---

## Scenario 2: Settings Menu Exploration

### BEFORE
```
User navigates to Settings menu with 10 items:
- Display Settings
- Notifications
- Privacy
- Account
- etc.

Explorer sees: 10 untried elements
Explorer thinks: "Same structure as Product list, maybe sample 3?"

Action taken:
  1. Click Display Settings → SettingsDisplayPage
  2. Back
  3. Click Notifications → SettingsNotificationsPage (different structure!)
  4. Back
  5. Skip remaining 8 items (low confidence decision)

Result:
- Uncertainty about whether to explore all
- May have missed important features
- Inconsistent strategy (should be "visit all")
```

### AFTER
```
User navigates to Settings menu with 10 items:
- Display Settings
- Notifications
- Privacy
- Account
- etc.

Explorer's new pipeline:
1. analyze_new_screen_containers()
   ├─ Detects LinearLayout, simple children (Icon + TextView)
   └─ No price/rating/product signals

2. container_classifier.classify()
   ├─ HeuristicClassifier finds nav keywords
   │  └─ "settings", "notifications", "privacy", "account" all matched
   │  └─ Confidence: 0.88 for NAVIGATION_LIST
   ├─ No LLM needed
   └─ Strategy: "Visit each item at least once, record all transitions"

3. pick_next_action() applies classification
   ├─ All 10 items included in candidates (not sampled)
   ├─ Scores apply to all items equally
   └─ Methodically visits each one

4. Result:
   - Visits all 10 menu items
   - Maps complete navigation graph
   - Discovers all features

Example log:
```
[Explorer] Container 'SettingsMenu#LinearLayout_0' classified:
  - Type: NAVIGATION_LIST
  - Strategy: Visit each item at least once, record screen transitions
  - Detected keywords: settings(1.0), notifications(0.9), privacy(0.8), account(0.8)
  - Source: heuristic (confidence=0.88)
[Explorer] Element selection strategy: EXPLORE_ALL (not sampled)
```

---

## Scenario 3: Filter/Sort Options

### BEFORE
```
User clicks "Sort" on a list:
- Sort Ascending
- Sort Descending

Explorer sees: 2 untried elements
Explorer might:
  - Click "Sort Ascending" → screen looks same but different data
  - Thinks it's a navigation element, treats as new screen
  - Wastes time exploring state changes
```

### AFTER
```
User clicks "Sort" on a list:
- Sort Ascending (RadioButton)
- Sort Descending (RadioButton) 

Explorer's pipeline:
1. analyze_new_screen_containers()
   ├─ Detects RadioButton children
   └─ Element type indicator

2. container_classifier.classify()
   ├─ HeuristicClassifier detects option elements
   │  └─ RadioButton detected → 0.95 confidence
   ├─ Keywords: "sort", "ascending", "descending" also match
   └─ Result: OPTION_LIST with 0.95 confidence

3. pick_next_action() applies strategy
   ├─ Knows these aren't navigation, don't visit all
   ├─ Scores them as state modifiers (lower priority)
   ├─ May toggle one or two, but marked as "not important"
   └─ Not treated as new screen discoveries

Example log:
```
[Explorer] Container 'SortOptions#RadioGroup_0' classified:
  - Type: OPTION_LIST
  - Detected element types: RadioButton(2) → 0.95 confidence
  - Strategy: Toggle each option, verify state changes, stay on current screen
  - Source: heuristic (confidence=0.95)
[Explorer] Element selection strategy: LOW_PRIORITY (state modifiers)
```

---

## Screen Template Example: Content List Handling

### Scenario: E-store, discover 3 product pages with different content

**Run 1 - Cold start:**
```
Action 1: Click "Product: iPhone 15 Pro"
  Before: ProductList (sig_abc12345)
  After: ProductDetail (sig_product_1)
  
  observe_action_result() called:
  ├─ Transition recorded: ProductList → sig_product_1
  ├─ analyze_new_screen_containers(sig_product_1, source)
  ├─ Screen template analyzer:
  │  ├─ Extracts structure (ignoring text "iPhone 15 Pro")
  │  └─ Signature: template_xyz = SHA256(normalized_structure)
  └─ New template created: template_xyz with [sig_product_1]

Action 2: Back, click "Product: Samsung Galaxy"
  Before: ProductList
  After: ProductDetail (sig_product_2)
  
  analyze_new_screen_containers(sig_product_2, source)
  ├─ Extract structure (ignoring text "Samsung Galaxy")
  ├─ Compute signature → compare with existing templates
  ├─ Jaccard similarity(template_xyz, new_structure) = 0.92 > 0.85 ✓
  └─ GROUP under template_xyz
  
  screen_template_registry:
  ├─ template_xyz now contains [sig_product_1, sig_product_2]
  └─ Cached in KB: template_xyz

Action 3: Back, click "Product: Google Pixel"
  Before: ProductList
  After: ProductDetail (sig_product_3)
  
  Same process:
  ├─ Extract structure, compare with template_xyz
  ├─ Similarity = 0.91 > 0.85 ✓
  └─ Add to template_xyz
  
  Final state:
  ├─ template_xyz = [sig_product_1, sig_product_2, sig_product_3]
  └─ All 3 product pages recognized as same template

Scoring for future actions on ProductList:
  ├─ Element "Product4": known target = sig_product_4 (unseen)
  ├─ get_normalized_visit_count(sig_product_4):
  │  ├─ Check registry: does sig_product_4 have template?
  │  ├─ No (first time seeing it)
  │  └─ Returns 0 (unvisited)
  ├─ With target_visits=0: +0.4 bonus (very undervisited)
  └─ High score, will try
  
  ├─ Element "Product1": known target = sig_product_1 (seen)
  ├─ get_normalized_visit_count(sig_product_1):
  │  ├─ Check registry: maps to template_xyz
  │  ├─ template_xyz.screen_sigs = {sig_product_1, sig_product_2, sig_product_3}
  │  └─ Returns 3 (aggregate template visits!)
  ├─ With target_visits=3: only +0.1 bonus (well-visited)
  └─ Lower score, skip in favor of new areas
```

**Result**:
- Explored 3 product variations
- Recognized as same template
- Future actions biased toward other features
- Prevents infinite cycling through product variations

---

## LLM Call Reduction

### First Run (Cold Start)
```
Containers encountered: 20

Heuristic classifier:
  - 12 containers classified with >0.8 confidence ✓ [0.0 LLM calls]
  - 5 containers with 0.5-0.8 confidence ? [5 → LLM]
  - 3 containers with <0.5 confidence ? [3 → LLM]

Total LLM calls: 8

Cost: 8 LLM classifications × ~100 tokens each = 800 tokens
```

### Subsequent Runs (Warm Start)
```
Same 20 containers + 5 new ones = 25 containers

Cache hits: 20 containers instantly loaded from KB ✓
  - No heuristics run
  - No LLM calls
  - Instant classification

New containers: 5
  - Heuristic classifier (free)
  - 4 classified with >0.8 confidence [0 LLM]
  - 1 ambiguous, calls LLM [1 LLM call]

Total LLM calls: 1

Cost: 90% reduction in LLM usage!
```

---

## Summary: The Three Layers in Action

| Layer | Input | Process | Output | Cost |
|-------|-------|---------|--------|------|
| **Structural** | XML layout | Extract elements, hierarchy, dimensions | Layout fingerprint | Free |
| **Heuristic** | Fingerprint + keywords | Pattern matching on known indicators | Classification 0.3-0.95 confidence | Free |
| **Behavioral** | Click results | Compare target screens | Classification confirmation | Free |
| **LLM** | All above + ambiguity | Dense reasoning | High-confidence classification | 100 tokens |
| **Memory** | Classification result | Store in KB | Instant future recall | Free |

**Key insight**: Deterministic layers cover ~90% of cases. LLM only used for true ambiguity. Cross-run learning makes LLM calls rare after first run.
