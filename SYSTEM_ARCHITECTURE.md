# AI Mobile Testing Agent — System Architecture

## High-Level Architecture

The system is a **12-agent multi-agent framework** for autonomous mobile application testing on Android. It combines LLM-driven decision-making, Appium-based device automation, persistent cross-run memory (TinyDB), and on-the-fly script generation to test mobile apps intelligently.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        USER / CLI  (main.py)                            │
│  Modes: --task | --multiagent | --explorer | --smart-test | --workflow  │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR AGENT                               │
│  Coordinates all agents · Manages lifecycle · Produces reports          │
│                                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐     │
│  │ Planner  │  │Navigator │  │  Critic  │  │     Recovery         │     │
│  │ Agent    │  │ Agent    │  │  Agent   │  │     Agent            │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────────┘     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                               │
│  │ Explorer │  │ Reporter │  │Accessib- │                               │
│  │ Agent    │  │ Agent    │  │ility Agt │                               │
│  └──────────┘  └──────────┘  └──────────┘                               │
│  ┌──────────┐  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Security │  │ Doc         │  │ Script       │  │ Script       │      │
│  │ Agent    │  │ Ingestion   │  │ Generator    │  │ Executor     │      │
│  └──────────┘  └─────────────┘  └──────────────┘  └──────────────┘      │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                   ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐
│  VLM / LLM       │  │ Appium           │  │ Persistent Memory        │
│  (Ollama)        │  │ Controller       │  │                          │
│  gpt-oss:120b    │  │ + UiAutomator2   │  │ KnowledgeBase (TinyDB)   │
│                  │  │ + ADB            │  │ SessionMemory (in-proc)  │
└──────────────────┘  └──────────────────┘  └──────────────────────────┘
```

---

## Agent Hierarchy

### BaseAgent (`agents/base.py`)

Every specialist agent (except OrchestratorAgent) subclasses `BaseAgent`, which provides:

| Method | Purpose |
|--------|---------|
| `ask_text(prompt)` | Send a text-only prompt to the LLM and return the response |
| `ask_vision(image_path, prompt)` | Send a screenshot + prompt to the VLM |
| `parse_json(text)` | Extract JSON from LLM output (handles fences, truncation) |
| `parse_json_strict(text, expected_keys)` | Strict JSON parse requiring specific keys |
| `_sanitise_json(text)` | Strip markdown fences, fix smart quotes, em-dashes |
| `_repair_truncated_json(text)` | Attempt to close truncated JSON from large responses |
| `format_ui_elements(...)` | Format accessibility IDs, resource IDs, texts for prompts |
| `format_action_history(...)` | Format recent action history for context |

---

### 1. Orchestrator Agent (`agents/orchestrator.py`)

The top-level coordinator. **Not a BaseAgent subclass** — it does not call the LLM itself but delegates to specialist agents.

**Responsibilities:**
- Initialises Appium session, all child agents, memory layers
- Runs planning → execution → reporting lifecycle
- Manages the step loop with retry budgets and crash recovery
- Runs parallel accessibility + security audits
- Produces JSON + Markdown reports

**Execution Modes:**

| Method | Mode | Description |
|--------|------|-------------|
| `run_task(task, ...)` | Task | Execute a natural-language instruction with Planner → Navigator → Critic loop |
| `run_explore(...)` | Explore | Plan-driven autonomous exploration |
| `run_explore_with_explorer(...)` | Explorer | Curiosity-driven exploration using the Explorer agent's screen graph |
| `run_smart_test(docs_path, ...)` | Smart Test | Doc-driven pipeline: ingest → generate scripts → execute → report |

**Smart-Test Pipeline (inside Orchestrator):**

```
┌───────────────────────────────────────────────────────────────────────┐
│  run_smart_test()                                                     │
│                                                                       │
│  1. _smart_phase_ingest_docs(docs_path)                               │
│     ├── DocIngestionAgent reads files / directory                     │
│     ├── LLM extracts features with priority + expected_behavior       │
│     └── Features stored in KnowledgeBase                              │
│                                                                       │
│  2. _smart_phase_test_features(max_steps)                             │
│     For each feature (sorted by priority):                            │
│     ├── controller.reset_app()  (clean state)                         │
│     ├── ScriptGeneratorAgent generates nav + verification scripts     │
│     │   ├── First step: exact locator IDs from current UI             │
│     │   └── Later steps: empty locator_value + description            │
│     │       (resolved at runtime against fresh UI)                    │
│     ├── ScriptExecutorAgent replays scripts                           │
│     │   └── _execute_step_with_fallback():                            │
│     │       ├── Try 1: direct execution with locator                  │
│     │       └── Try 2: LLM re-resolves against FRESH UI snapshot     │
│     │           (handles popups, modals, dynamic elements)            │
│     ├── Results stored in KnowledgeBase                               │
│     └── Failed features re-tested once                                │
│                                                                       │
│  3. _generate_md_report() → Markdown summary                          │
│  4. _save_report()        → JSON report                               │
└───────────────────────────────────────────────────────────────────────┘
```

---

### 2. Planner Agent (`agents/planner.py`)

Decomposes a user task or exploration goal into a structured `TestPlan`.

**Input:** Natural-language task + current UI context (screenshot + elements)
**Output:** `TestPlan` containing `TestGoal`s → `TestTask`s → `TestStep`s

Used in `run_task()` and `run_explore()` modes. The Orchestrator falls back to a hardcoded plan if the LLM response cannot be parsed.

---

### 3. Navigator Agent (`agents/navigator.py`)

Executes individual UI actions on the device.

**Two execution paths:**

| Method | When Used | How It Works |
|--------|-----------|--------------|
| `execute_step(step_description, ui_context)` | LLM-resolved | Sends step + screenshot + UI elements to LLM; LLM returns `{action, locator_type, locator_value, text}` |
| `execute_action_direct(action_dict)` | Script-driven | Directly executes a pre-built action dict without LLM |

**`_do_action()` — Supported Actions:**

| Action | Details |
|--------|---------|
| `click` | Find element by locator → click; coordinate fallback via `find_element_bounds()` → `tap_at()` |
| `input` | Find element → `_safe_input()` (4-strategy: clear+send, set_value, click+send, coordinate `type_at_coordinates()`) |
| `scroll` | W3C Actions pointer (up/down/left/right) |
| `back` | `press_back()` |
| `long_press` | W3C Actions with configurable hold duration |
| `wait` | `time.sleep(2)` — lets animations/transitions settle |
| `assert_visible` | Check element is present on screen |
| `assert_not_visible` | Check element is absent |
| `noop` / `skip` | No-op, return success |

**Coordinate Fallback:** When element locators fail, `find_element_bounds()` / `find_input_field_bounds()` from `ui_extract.py` parse the XML source to extract `[x,y]` coordinates, then `tap_at()` or `type_at_coordinates()` on AppiumController perform the action.

---

### 4. Critic Agent (`agents/critic.py`)

Validates each step's result by comparing before/after screenshots + UI state.

**Input:** Pre-action screenshot, post-action screenshot, action performed, expected change
**Output:** `{success: bool, reason: str, suggestion: str}`

The Orchestrator uses the Critic's verdict to decide whether to proceed, retry, or escalate to Recovery.

---

### 5. Recovery Agent (`agents/recovery.py`)

Handles crash detection and session recovery.

**Triggers:**
- UiAutomator2 session crash (`WebDriverException`)
- App crash (detected via `is_session_alive()`)
- Repeated action failures exceeding retry budget

**Actions:**
- `restart_driver()` → re-establish Appium session
- `reset_app()` → terminate + re-launch app
- Skip and log unrecoverable steps

---

### 6. Explorer Agent (`agents/explorer.py`)

Curiosity-driven exploration that maximises screen coverage.

**Algorithm:**
1. Queries `SessionMemory.get_least_visited_screens()` for under-explored areas
2. Checks `get_unvisited_transitions()` for untried actions
3. Uses `detect_action_loop()` to break cycles
4. Asks LLM for the most novel action given current screen + memory graph

Records every screen and transition into SessionMemory for the navigation graph.

---

### 7. Reporter Agent (`agents/reporter.py`)

Generates structured test reports.

**Outputs:**
- JSON report: steps, bugs, screenshots, timing, pass/fail per task
- Markdown report: human-readable summary with bug screenshots

---

### 8. Accessibility Agent (`agents/accessibility.py`)

Runs accessibility audits on captured UI snapshots.

**Checks:**
- Missing content descriptions
- Touch target sizes (< 48dp)
- Colour contrast issues (via VLM analysis)
- Focus order problems

Runs in parallel with Security agent after the main test loop.

---

### 9. Security Agent (`agents/security.py`)

Analyses UI state for security concerns.

**Checks:**
- Password fields not masked
- Sensitive data visible in logs/toasts
- Insecure permission prompts
- Data leakage through screenshots

Also runs in parallel after the main test loop.

---

### 10. Doc Ingestion Agent (`agents/doc_ingestion.py`)

Reads app documentation and extracts a structured feature list.

**Methods:**

| Method | Input | Output |
|--------|-------|--------|
| `ingest_documentation(text)` | Raw text | List of `{name, description, priority, expected_behavior, test_steps}` |
| `ingest_from_file(path)` | File path | Same — reads file then calls above |
| `ingest_from_directory(path)` | Directory | Recursively reads `.md`, `.txt`, `.rst` files |
| `enrich_features_with_ui(features, ui_context)` | Features + live UI | Enhanced features with UI element mappings |

Features are stored in `KnowledgeBase.features` table.

---

### 11. Script Generator Agent (`agents/script_generator.py`)

Generates executable test scripts on-the-fly using LLM + live UI context.

**Key Design:**
- **First step:** uses exact element IDs from the live UI snapshot
- **Later steps:** uses empty `locator_value` with a clear `description` field — resolved at runtime by the LLM against fresh UI (handles popups, modals, dynamic content)

**Methods:**

| Method | Purpose |
|--------|---------|
| `generate_verification_script(feature, ui_context)` | Generates assertion steps that verify a feature works |
| `generate_nav_script(target_screen, ui_context)` | Generates navigation steps to reach a target screen |
| `generate_batch_scripts(features, ui_context)` | Batch-generates scripts for multiple features |

**Script Format:**
```json
{
  "name": "Verify sort options",
  "steps": [
    {
      "action": "click",
      "locator_type": "accessibility_id",
      "locator_value": "sort button",
      "description": "Tap the sort button to open options"
    },
    {
      "action": "click",
      "locator_type": "accessibility_id",
      "locator_value": "",
      "description": "Select 'Price - Ascending' from the popup"
    },
    {
      "action": "assert_visible",
      "locator_type": "text",
      "locator_value": "",
      "description": "Verify products are sorted by price ascending"
    }
  ]
}
```

---

### 12. Script Executor Agent (`agents/script_executor.py`)

Replays generated scripts on the device with intelligent fallback.

**Core Method: `_execute_step_with_fallback(step)`**

```
┌─────────────────────────────────────────────────┐
│  _execute_step_with_fallback(step)              │
│                                                  │
│  1. Has locator_value?                           │
│     YES → navigator.execute_action_direct(step)  │
│     ├── Success? → return ✓                      │
│     └── Fail? → go to step 2                     │
│                                                  │
│  2. Has description?                             │
│     YES → Capture FRESH UI snapshot              │
│         → navigator.execute_step(description)    │
│         → LLM resolves against current screen    │
│         → Handles popups/modals/dynamic UI       │
│     └── return result                            │
│                                                  │
│  3. Neither? → return failure                    │
└─────────────────────────────────────────────────┘
```

**Assertion Types:**

| Type | How Evaluated |
|------|---------------|
| `assert_visible` | `_element_present()` — tries accessibility_id, id, text, xpath |
| `assert_not_visible` | Inverse of above |
| `assert_text` | `_get_element_text()` checks element content |
| `assert_count` | `_count_elements()` checks number of matching elements |
| `assert_order` | `_evaluate_order_assertion()` — LLM-based ordering verification |

**Other Methods:**

| Method | Purpose |
|--------|---------|
| `execute_nav_script(script)` | Replay navigation script steps with fallback |
| `execute_verification_script(script)` | Replay verification steps + evaluate assertions |
| `run_feature_test(feature, nav_script, verification_script)` | End-to-end: navigate → verify → return pass/fail |

---

## Memory Architecture

### SessionMemory (`session_memory.py`) — In-Process

Ephemeral per-run memory. Tracks the current session's state.

**Data Structures:**

| Class | Purpose |
|-------|---------|
| `TestPlan` | Hierarchical plan: goals → tasks → steps |
| `TestGoal` | High-level objective with description |
| `TestTask` | Specific task within a goal |
| `TestStep` | Individual action step with status tracking |
| `ScreenNode` | Screen signature + elements + transitions |
| `BugEntry` | Recorded bug with severity, description, screenshot |
| `TaskStatus` | Enum: pending, running, passed, failed, skipped |

**Key Methods:**

| Method | Purpose |
|--------|---------|
| `add_screen(sig, elements)` | Record a visited screen |
| `add_transition(from_sig, action, to_sig)` | Record a navigation edge |
| `get_least_visited_screens(n)` | Screens with fewest visits (for Explorer) |
| `get_unvisited_transitions()` | Untried actions on known screens |
| `detect_action_loop(threshold)` | Detect if agent is stuck in a cycle |
| `get_screen_visit_count(sig)` | Visit count for a specific screen |
| `record_bug(...)` | Store a bug entry |
| `save(path)` / `load(path)` | Persist/resume session state |

---

### KnowledgeBase (`knowledge_base.py`) — Persistent Cross-Run

TinyDB-backed NoSQL storage at `artifacts/knowledge_base.db.json`. Survives across runs.

**Tables:**

| Table | Contents |
|-------|----------|
| `screens` | Screen signatures, elements, visit counts, timestamps |
| `nav_scripts` | Navigation scripts to reach specific screens |
| `verification_scripts` | Feature verification scripts with pass/fail history |
| `features` | Extracted app features with priority, test status |
| `discoveries` | Bugs, anomalies, interesting findings |
| `runs` | Run metadata (start/end time, steps, results) |
| `meta` | Schema version, last import timestamp |

**Key Methods:**

| Method | Purpose |
|--------|---------|
| `start_run()` / `end_run()` | Bracket a test session |
| `record_screen(sig, elements)` | Upsert screen data |
| `record_transition(from, action, to)` | Add navigation edge |
| `add_nav_script(name, target, steps)` | Store a navigation script |
| `add_verification_script(name, feature, steps)` | Store a verification script |
| `mark_script_result(name, passed, details)` | Record script pass/fail |
| `add_feature(name, description, priority)` | Register an app feature |
| `get_features_by_priority()` | Get features sorted by test priority |
| `mark_feature_tested(name, result)` | Record feature test outcome |
| `import_all_sessions(artifacts_dir)` | Import screens from all past session JSONs |
| `summary_for_llm()` | Compact summary for LLM context windows |
| `get_screen_graph_summary()` | Text-based graph of screen → transition → screen |

---

## Infrastructure Layer

### AppiumController (`appium_controller.py`)

WebDriver wrapper for Appium + UiAutomator2.

**Session Management:**

| Method | Purpose |
|--------|---------|
| `start_driver()` | Create Appium WebDriver session with Android capabilities |
| `stop_driver()` | Close session |
| `restart_driver()` | Stop + start (crash recovery) |
| `is_session_alive()` | Check if session is still valid |
| `reset_app()` | Terminate + activate app (clean state between features) |

**Element Operations:**

| Method | Purpose |
|--------|---------|
| `find_element(by, value)` | Find single element by strategy |
| `find_elements(by, value)` | Find all matching elements |
| `find_by_accessibility_id(id)` | Shorthand for accessibility ID lookup |
| `find_by_id(id)` | Shorthand for resource ID lookup |
| `find_by_android_uiautomator(selector)` | UiAutomator2 selector |
| `click_element(element)` | Click a found element |
| `input_text(element, text)` | Type text into element |

**Advanced Actions (W3C Actions API):**

| Method | Purpose |
|--------|---------|
| `scroll(direction)` | W3C pointer action scroll (up/down/left/right) |
| `swipe(start_x, start_y, end_x, end_y)` | Precise coordinate swipe |
| `long_press(element, x, y, duration_ms)` | W3C pointer hold action |
| `tap_at(x, y)` | Coordinate-based tap (no element needed) |
| `type_at_coordinates(x, y, text)` | Tap coordinates then type text |
| `scroll_to_text(text)` | UiAutomator2 scrollable container search |

**State Capture:**

| Method | Purpose |
|--------|---------|
| `get_page_source()` | XML UI hierarchy |
| `take_screenshot(filename)` | PNG screenshot to artifacts |

**Other:**

| Method | Purpose |
|--------|---------|
| `hide_keyboard()` | Dismiss on-screen keyboard |
| `press_back()` | Android back button |
| `press_enter()` | Enter key |
| `press_keycode(keycode)` | Arbitrary Android keycode |
| `is_keyboard_shown()` | Check keyboard visibility |

---

### VLM Module (`vlm.py`)

Vision-Language Model interface. Currently uses **Ollama** with `gpt-oss:120b-cloud`.

```
┌────────────────────────────────────────────────────────────────┐
│                         VLM Module                             │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  Primary Model: gpt-oss:120b-cloud (via Ollama)                │
│                                                                │
│  Functions:                                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  get_vlm_response(image_path, prompt)                    │  │
│  │  ├── Encodes image as base64                             │  │
│  │  ├── Sends to Ollama /api/generate                       │  │
│  │  └── Returns text analysis                               │  │
│  │                                                          │  │
│  │  get_text_response(prompt)                               │  │
│  │  ├── Text-only prompt to model                           │  │
│  │  └── Returns AI-generated response                       │  │
│  │                                                          │  │
│  │  Parallel Racing:                                        │  │
│  │  ├── Sends prompt to all PARALLEL_CLOUD_MODELS at once   │  │
│  │  ├── Returns first successful response                   │  │
│  │  └── Cancels remaining requests                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  Error Handling:                                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  VLMQuotaExceeded  → Quota limit reached                 │  │
│  │  VLMUnavailable    → Server unreachable or model missing │  │
│  │  MAX_RETRIES = 3   → Automatic retry on transient errors │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

---

### UI Extraction (`ui_extract.py`)

Parses Appium XML page source into structured element data.

**Functions:**

| Function | Purpose |
|----------|---------|
| `extract_ui_elements(xml_source)` | Returns `(acc_ids, res_ids, texts)` lists |
| `find_element_bounds(xml_source, identifier)` | Parse `bounds` attribute → `[x, y]` centre coordinates |
| `find_input_field_bounds(xml_source)` | Find first editable field → `[x, y]` coordinates |

Used by Navigator for coordinate fallback when standard locators fail.

---

### ADB Utilities (`adb.py`)

Android Debug Bridge helpers.

**Functions:**
- Device connectivity checks
- App install/uninstall
- Log capture (`logcat`)
- Emulator management

---

### Configuration (`config.py`)

Centralised config loaded from environment variables + `.env` file.

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_PACKAGE` | `com.saucelabs.mydemoapp.rn` | Android package name |
| `APP_ACTIVITY` | `.MainActivity` | Launch activity |
| `APK_PATH` | `app/android/...apk` | Path to APK file |
| `APPIUM_HOST` | `127.0.0.1` | Appium server host |
| `APPIUM_PORT` | `4723` | Appium server port |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3:8b` | Fallback local model |
| `OLLAMA_FALLBACK` | `1` | Enable Ollama fallback |
| `MAX_STEPS` | `30` | Default max steps |
| `MAX_SAME_STATE` | `3` | Loop detection threshold |
| `ACTION_RETRY_BUDGET` | `2` | Retries per failed action |
| `EMULATOR_AVD` | `Pixel_2_API_30` | Android emulator AVD name |
| `ADB_TARGET_DEVICE` | `emulator-5554` | Target device serial |

---

## Data Flow Diagrams

### Multi-Agent Task Execution

```
┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────┐
│   User   │    │  main.py │    │ Orchestrator │    │  Ollama  │
│          │    │          │    │              │    │ (LLM)    │
└────┬─────┘    └────┬─────┘    └──────┬───────┘    └────┬─────┘
     │               │                 │                  │
     │ --multiagent  │                 │                  │
     │ --task "..."  │                 │                  │
     │──────────────>│                 │                  │
     │               │                 │                  │
     │               │ run_task()      │                  │
     │               │────────────────>│                  │
     │               │                 │                  │
     │               │                 │ Planner: make    │
     │               │                 │ test plan        │
     │               │                 │─────────────────>│
     │               │                 │                  │
     │               │                 │ TestPlan         │
     │               │                 │<─────────────────│
     │               │                 │                  │
     │               │                 │ For each step:   │
     │               │                 │─┐                │
     │               │                 │ │ Navigator:     │
     │               │                 │ │ execute_step() │
     │               │                 │ │───────────────>│
     │               │                 │ │                │
     │               │                 │ │ action plan    │
     │               │                 │ │<───────────────│
     │               │                 │ │                │
     │               │                 │ │ Appium action  │
     │               │                 │ │ + screenshot   │
     │               │                 │ │                │
     │               │                 │ │ Critic: check  │
     │               │                 │ │───────────────>│
     │               │                 │ │                │
     │               │                 │ │ pass/fail      │
     │               │                 │ │<───────────────│
     │               │                 │─┘                │
     │               │                 │                  │
     │               │                 │ Accessibility +  │
     │               │                 │ Security audits  │
     │               │                 │ (parallel)       │
     │               │                 │                  │
     │               │ report path     │                  │
     │               │<────────────────│                  │
     │               │                 │                  │
     │ JSON + MD     │                 │                  │
     │ reports       │                 │                  │
     │<──────────────│                 │                  │
```

### Smart-Test Flow

```
┌──────┐  ┌──────────┐  ┌────────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐
│ User │  │ main.py  │  │Orchestrator│  │DocIngest │  │ScriptGen │  │ScriptEx│
└──┬───┘  └────┬─────┘  └─────┬──────┘  └────┬─────┘  └────┬─────┘  └───┬────┘
   │           │               │               │             │            │
   │--smart-   │               │               │             │            │
   │test --docs│               │               │             │            │
   │──────────>│               │               │             │            │
   │           │run_smart_test │               │             │            │
   │           │──────────────>│               │             │            │
   │           │               │               │             │            │
   │           │               │ ingest docs   │             │            │
   │           │               │──────────────>│             │            │
   │           │               │               │ LLM extract │            │
   │           │               │               │ features    │            │
   │           │               │ features list │             │            │
   │           │               │<──────────────│             │            │
   │           │               │               │             │            │
   │           │               │ store in KB   │             │            │
   │           │               │               │             │            │
   │           │               │ For each feature:           │            │
   │           │               │─┐             │             │            │
   │           │               │ │reset_app()  │             │            │
   │           │               │ │             │             │            │
   │           │               │ │ generate    │             │            │
   │           │               │ │ scripts     │             │            │
   │           │               │ │────────────────────────>│ │            │
   │           │               │ │             │             │            │
   │           │               │ │ nav +       │             │            │
   │           │               │ │ verify      │             │            │
   │           │               │ │ scripts     │             │            │
   │           │               │ │<────────────────────────│ │            │
   │           │               │ │             │             │            │
   │           │               │ │ execute scripts           │            │
   │           │               │ │───────────────────────────────────────>│
   │           │               │ │             │             │            │
   │           │               │ │             │   step with fallback     │
   │           │               │ │             │   (direct → LLM retry)  │
   │           │               │ │             │             │            │
   │           │               │ │ pass/fail   │             │            │
   │           │               │ │<──────────────────────────────────────│
   │           │               │ │             │             │            │
   │           │               │ │ store result in KB        │            │
   │           │               │─┘             │             │            │
   │           │               │               │             │            │
   │           │ MD + JSON     │               │             │            │
   │           │ reports       │               │             │            │
   │           │<──────────────│               │             │            │
   │           │               │               │             │            │
   │ reports   │               │               │             │            │
   │<──────────│               │               │             │            │
```

---

## File Structure

```
python_agent/
├── main.py                   # Entry point, CLI argument parsing
├── config.py                 # Centralised configuration (env vars + .env)
├── vlm.py                    # VLM/LLM interface (Ollama, parallel model racing)
├── appium_controller.py      # Appium WebDriver wrapper (W3C Actions, coordinates)
├── appium_server.py          # Appium server lifecycle management
├── adb.py                    # Android Debug Bridge utilities
├── ui_extract.py             # UI XML parsing, element/bounds extraction
├── session_memory.py         # In-process session state (plan, screens, bugs)
├── knowledge_base.py         # TinyDB persistent cross-run memory
├── memory.py                 # Legacy state signature utilities
├── navigation_memory.py      # Legacy persistent navigation tracking
├── logging_config.py         # Structured logging setup
├── requirements.txt          # Python dependencies
├── .env                      # Environment variables (API keys, model config)
│
├── agents/                   # Multi-agent system
│   ├── base.py               # BaseAgent — LLM interface, JSON parsing
│   ├── orchestrator.py       # Top-level coordinator (task/explore/smart-test)
│   ├── planner.py            # Decomposes tasks into TestPlans
│   ├── navigator.py          # Executes UI actions (click/input/scroll/assert)
│   ├── critic.py             # Validates step results (before/after comparison)
│   ├── recovery.py           # Crash detection + session recovery
│   ├── explorer.py           # Curiosity-driven screen coverage maximisation
│   ├── reporter.py           # JSON + Markdown report generation
│   ├── accessibility.py      # Accessibility audit agent
│   ├── security.py           # Security audit agent
│   ├── doc_ingestion.py      # Documentation → feature extraction
│   ├── script_generator.py   # LLM-generated nav + verification scripts
│   └── script_executor.py    # Script replay with LLM fallback
│
├── bug_localization/         # Bug-to-source-code mapping (optional)
│   ├── bug_localizer.py      # Main bug localization logic
│   ├── gui_data_extractor.py # GUI element data extraction
│   ├── preprocessor.py       # Source code preprocessing
│   ├── integration.py        # Integration with main agent
│   └── unixcoder.py          # UniXcoder code embedding model
│
├── workflows/                # Predefined JSON test scenarios
│   ├── sample_login_logout.json
│   └── comprehensive_test_scenarios.json
│
├── ai_tester.py              # Legacy monolithic AI tester (pre-multi-agent)
├── agent.py                  # Legacy single-agent runner
├── workflow_runner.py        # Static workflow JSON executor
├── workflow_spec.py          # Workflow JSON schema and parsing
│
└── artifacts/                # Output directory
    ├── knowledge_base.db.json  # TinyDB persistent storage
    ├── reports/                # JSON + Markdown test reports
    ├── screenshots/            # Step-by-step screenshots
    ├── logs/                   # Execution logs
    └── navigation_memory.json  # Legacy navigation graph
```

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Language** | Python 3.12 | Core implementation |
| **LLM** | Ollama + gpt-oss:120b-cloud | Vision + Text generation (primary) |
| **LLM (fallback)** | Google Gemini API | Available but currently disabled |
| **Persistent Storage** | TinyDB 4.8.2 | Cross-run NoSQL knowledge base |
| **Mobile Automation** | Appium 2.x | Mobile app control via WebDriver |
| **Android Driver** | UiAutomator2 | Android UI automation |
| **Device Management** | ADB | Emulator/device control |
| **Image Processing** | Pillow (PIL) | Screenshot handling + base64 encoding |
| **HTTP Client** | requests | Ollama API communication |
| **Env Management** | python-dotenv | .env file loading |
| **Test Apps** | React Native (SauceLabs MyDemoApp) | Demo application under test |

---

## Execution Modes Summary

| Mode | Command | Description |
|------|---------|-------------|
| **Smart Test** | `--smart-test --docs <path>` | Doc-driven: ingest docs → generate scripts → execute → cross-run memory |
| **Multi-Agent Task** | `--multiagent --task "..."` | LLM plans + executes a natural-language instruction |
| **Multi-Agent Explore** | `--multiagent` | Plan-driven autonomous exploration |
| **Explorer** | `--explorer` | Curiosity-driven exploration with screen graph |
| **Legacy Task** | `--task "..."` | Single-agent (AITester) task execution |
| **Legacy Explore** | `--explore` | Single-agent autonomous exploration |
| **Workflow** | `--workflow <file>` | Execute predefined JSON test steps |
| **Interactive** | `--interactive` | Real-time chat with agent |
| **Generate Tests** | `--generate-tests` | AI creates test scenario JSONs |

**Additional Flags:**

| Flag | Purpose |
|------|---------|
| `--max-steps N` | Maximum execution steps (default: 30) |
| `--resume <path>` | Resume a crashed/interrupted session from JSON |
| `--docs <path>` | Documentation path for smart-test mode |
| `--vision` | Enable visual checks during workflow runs |
| `--localize` | Enable bug-to-source localization (UniXcoder) |
| `--source-dir <path>` | Source code directory for localization |
