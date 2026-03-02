# AI Mobile Testing Agent — Capabilities

## Overview

A **12-agent multi-agent system** that autonomously tests Android applications through Appium. The system uses an LLM (`gpt-oss:120b-cloud` via Ollama) for reasoning, vision-based bug detection, on-the-fly script generation, and cross-run persistent memory backed by TinyDB.

---

## Architecture

```
Orchestrator
├── Planner          — breaks tasks into steps
├── Navigator        — executes UI actions on the device
├── Critic           — validates each step outcome
├── Recovery         — repairs crashed sessions / UiAutomator2
├── Explorer         — autonomously discovers all screens
├── Reporter         — generates Markdown test reports
├── Accessibility    — WCAG accessibility audits
├── Security         — sensitive-data & permission audits
├── DocIngestion     — reads app docs → extracts feature list
├── ScriptGenerator  — generates verification + navigation scripts on the fly
└── ScriptExecutor   — replays scripts on the device with LLM fallback
```

**Persistent storage:**
- `SessionMemory` — per-run action log, screen graph, loop detection
- `KnowledgeBase` (TinyDB) — cross-run screens, nav scripts, features, test results

---

## Execution Modes

### 1. Multi-Agent Task (`--multiagent --task`)

Execute a natural language testing task with the full agent team.

```bash
python -m python_agent.main --multiagent --task "Login with bob@example.com / 10203040, add the first product to cart, verify cart badge shows 1"
```

- Planner decomposes the task into steps
- Navigator executes each step on the device
- Critic validates outcomes (screenshot + XML)
- Recovery auto-repairs on crash
- Reporter produces a Markdown summary

### 2. Autonomous Explorer (`--explorer`)

AI explores the app to discover every reachable screen and interaction.

```bash
python -m python_agent.main --explorer --max-steps 80
```

- Visits all accessible screens via guided exploration
- Session memory tracks visited screens, avoids revisits
- Loop detection with escalating break strategies (new element → scroll → back → deep back)
- Records screen graph with transitions
- Persists session for future KB import

### 3. Smart Test (`--smart-test`)

Documentation-driven, script-generating, cross-run persistent testing.

```bash
# Auto-discover features from previous exploration data:
python -m python_agent.main --smart-test --max-steps 60

# Provide app documentation for targeted feature extraction:
python -m python_agent.main --smart-test --docs path/to/app_docs.md --max-steps 60
```

**How it works:**

1. **KB bootstrap** — imports all previous session data (screens, transitions)
2. **Feature extraction** — reads docs or infers features from known UI
3. **Per-feature testing** (by priority: high → medium → low):
   - Resets app to home screen
   - Generates a verification script (steps + assertions)
   - Generates or reuses a navigation script to reach the target screen
   - Executes: navigate → run verification → evaluate assertions
   - If a direct action fails (e.g. popup appeared), retries with LLM resolution against fresh UI
   - Records results, bugs, and nav paths in KB for reuse
4. **Re-tests previously failed features** on subsequent runs
5. **Accessibility + Security audits**
6. **Markdown report generation**

### 4. Single-Agent Task (`--task`)

Lightweight mode — one LLM loop, no sub-agents.

```bash
python -m python_agent.main --task "Open the side menu"
```

### 5. Workflow Execution (`--workflow`)

Run predefined JSON test scenarios.

```bash
python -m python_agent.main --workflow python_agent/workflows/test_scenarios.json
```

---

## Supported Actions

| Action | Description | Parameters |
|--------|-------------|------------|
| `click` | Tap an element (with coordinate fallback) | `locator_type`, `locator_value` |
| `input` | Type text (4-strategy fallback + coordinate typing) | `locator_type`, `locator_value`, `text` |
| `scroll` | W3C Actions swipe gesture | `direction` (up/down/left/right) |
| `long_press` | Long press via W3C Actions | `locator_type`, `locator_value` |
| `back` | Press Android back button | — |
| `wait` | Pause execution | `duration` (seconds) |
| `hide_keyboard` | Dismiss on-screen keyboard | — |
| `press_enter` | Press Enter/Next key | — |

**Smart execution:** When a scripted action fails (element not found because a popup/modal appeared), the executor **automatically retries with LLM resolution** against the current screen. This handles dynamic UI like sort popups, confirmation dialogs, and overlays without hardcoding.

---

## Locator Strategies

| Strategy | Description | Example |
|----------|-------------|---------|
| `accessibility_id` | Content description (preferred) | `open menu` |
| `resource_id` | Android resource ID | `com.app:id/login_btn` |
| `text` | Visible text match | `Login` |
| `xpath` | XPath selector (fallback) | `//android.widget.Button[@text='OK']` |
| Coordinate fallback | Extract bounds from XML, tap at center | Automatic |

---

## Assertion Types

Used by verification scripts in Smart Test mode:

| Type | Description |
|------|-------------|
| `assert_visible` | Element is present on screen |
| `assert_not_visible` | Element is absent |
| `assert_text` | Element contains expected text |
| `assert_count` | N elements match the locator |
| `assert_order` | LLM evaluates ordering (e.g. price ascending) |

---

## Bug Detection

### Automatic (all modes)
- Missing/broken navigation
- Element interaction failures
- Assertion failures with detailed reasons
- Crash detection (UiAutomator2 session loss)

### Visual (screenshot-based)
- Layout and alignment issues
- Overlapping elements
- Text truncation
- Color/contrast problems

### Accessibility Audit
- Missing content descriptions
- Touch target sizing
- Color contrast ratios
- WCAG compliance scoring (0-100)

### Security Audit
- Sensitive data exposure in UI
- Permission warnings
- Insecure input handling

---

## Cross-Run Memory (KnowledgeBase)

Backed by **TinyDB** (`artifacts/knowledge_base.db.json`):

| Table | What it stores |
|-------|---------------|
| `screens` | Signature, elements, transitions, visit counts |
| `nav_scripts` | Reusable navigation paths to reach specific screens |
| `verification_scripts` | Test scripts with pass/fail history |
| `features` | Feature registry with priority, test status, linked scripts |
| `discoveries` | Bug findings and observations |
| `runs` | Run metadata (timestamps, mode, results) |

**Key behaviors:**
- Imports all previous session files on startup
- Remembers how to navigate to every discovered screen
- Skips re-testing features that already passed
- Re-tests features that previously failed
- Accumulates knowledge across unlimited runs

---

## Input Handling

Four-strategy text input with automatic fallback:

1. `click → clear → send_keys` (standard)
2. `send_keys("") → clear → send_keys` (pre-focus)
3. `set_value` (Appium direct)
4. `tap_at(x, y) → ADB shell input` (coordinate-based)

Keyboard is auto-dismissed after input.

---

## Session Management

- **Per-run session files** — JSON logs of every action, screen visit, and bug
- **Auto-recovery** — detects UiAutomator2 crashes, restarts driver, relaunches app
- **Loop detection** — tracks repeated action patterns, escalates break strategy
- **App guard** — verifies the correct app is in foreground before each action
- **Screenshot capture** — every step is documented with a screenshot

---

## Environment Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `VLM_PROVIDER` | LLM provider | `ollama` |
| `VLM_MODEL` | Model name | `gpt-oss:120b-cloud` |
| `APPIUM_HOST` | Appium server host | `127.0.0.1` |
| `APPIUM_PORT` | Appium server port | `4723` |
| `APP_PACKAGE` | App under test | `com.saucelabs.mydemoapp.rn` |
| `APP_ACTIVITY` | Main activity | `.MainActivity` |

---

## Output & Reports

All outputs saved to `python_agent/artifacts/`:

```
artifacts/
├── knowledge_base.db.json    # Persistent cross-run TinyDB database
├── navigation_memory.json    # Legacy nav memory
├── reports/
│   ├── report_*.md           # Markdown test reports
│   └── multiagent_*.json     # Structured JSON reports
├── sessions/
│   ├── smart_*.json          # Smart test session logs
│   ├── explore_*.json        # Explorer session logs
│   └── session_*.json        # Task session logs
├── screenshots/              # Step-by-step screenshots
└── logs/
    └── agent.log             # Full debug log
```

---

## CLI Reference

| Option | Description |
|--------|-------------|
| `--task "text"` | Single-agent natural language task |
| `--multiagent` | Enable multi-agent orchestrator |
| `--explorer` | Autonomous exploration mode |
| `--smart-test` | Doc-driven smart testing mode |
| `--docs <path>` | App documentation file/directory (for `--smart-test`) |
| `--max-steps <n>` | Step budget (default: 60) |
| `--resume <path>` | Resume from a saved session file |
| `--workflow <file>` | Run predefined JSON workflow |
| `--vision` | Enable visual checks (with workflow) |
