# AI Testing Agent - Capabilities

## Overview
This AI-powered mobile testing agent uses Google Gemini LLM to autonomously test Android applications through Appium.

---

## Execution Modes

### 1. Natural Language Task Execution (`--task`)
Execute any testing task described in plain English.

```bash
python -m python_agent.main --task "Your task description here"
```

**Examples:**
- `--task "Login with bob@example.com and password 10203040"`
- `--task "Add the first product to cart and proceed to checkout"`
- `--task "Sort products by price and verify the order"`
- `--task "Navigate to all menu items and check each screen"`
- `--task "If login doesn't work, logout first then try again"` (conditional logic)

**Capabilities:**
- Understands complex multi-step instructions
- Handles conditional logic ("if X then Y")
- Adapts to current screen state
- Discovers and uses app features (like autofill)
- Reports progress for each step

---

### 2. Autonomous Exploration (`--explore`)
AI explores the app independently to find bugs.

```bash
python -m python_agent.main --explore --max-steps 20
```

**Capabilities:**
- Visits all accessible screens
- Tests interactive elements (buttons, inputs, etc.)
- Detects UI/UX bugs automatically
- Reports visual anomalies
- Tracks screen coverage
- Prioritizes unexplored areas

---

### 3. Interactive Chat Mode (`--interactive`)
Real-time conversation with the AI agent.

```bash
python -m python_agent.main --interactive
```

**Capabilities:**
- Natural language commands in real-time
- Immediate feedback on actions
- Can ask questions about the app state
- Manual control when needed
- Type `quit` or `exit` to stop

---

### 4. Test Generation (`--generate-tests`)
AI analyzes the app and generates test scenarios.

```bash
python -m python_agent.main --generate-tests
```

**Capabilities:**
- Creates structured JSON test workflows
- Identifies key user flows
- Generates edge case scenarios
- Prioritizes tests by importance
- Outputs to `artifacts/reports/generated_tests.json`

---

### 5. Static Workflow Execution (`--workflow`)
Run predefined test scenarios from JSON files.

```bash
python -m python_agent.main --workflow python_agent/workflows/test_scenarios.json
python -m python_agent.main --workflow python_agent/workflows/test_scenarios.json --vision
```

**Capabilities:**
- Executes deterministic test scripts
- Variable substitution (`${username}`, `${password}`)
- Multiple assertion types
- Optional visual bug detection with `--vision`
- Continues through all workflows even if one fails
- Resets app between workflows

---

## Supported Actions

| Action | Description | Parameters |
|--------|-------------|------------|
| `click` | Tap on an element | `locator_strategy`, `locator_value` |
| `input` | Type text into a field | `locator_strategy`, `locator_value`, `text` |
| `scroll` | Scroll/swipe gesture | `direction` (up/down/left/right) |
| `wait` | Pause execution | `seconds` |
| `back` | Press Android back button | - |
| `reset` | Reset app to initial state | - |
| `visual_check` | AI visual bug detection | `note` |
| `assert_contains` | Verify text is visible | `assert_contains` |
| `hide_keyboard` | Dismiss on-screen keyboard | - |
| `press_enter` | Press Enter/Next key | - |

---

## Locator Strategies

| Strategy | Description | Example |
|----------|-------------|---------|
| `accessibility_id` | Accessibility ID (recommended) | `Login button` |
| `id` | Android resource ID | `com.app:id/login` |
| `xpath` | XPath selector | `//android.widget.Button[@text='Login']` |
| `text` | Exact text match | `Submit` |

---

## Bug Detection

### Automatic Bug Detection
The AI can detect:
- UI layout issues
- Misleading error messages
- Validation bugs
- Unexpected behavior
- Missing elements
- Broken navigation

### Visual Bug Detection (with `--vision`)
Using VLM (Vision Language Model):
- Visual alignment issues
- Color/contrast problems
- Overlapping elements
- Missing icons/images
- Text truncation

---

## Keyboard Handling

The agent automatically:
- Hides keyboard after text input
- Can press Enter/Next to move between fields
- Detects when keyboard is blocking UI elements

---

## Session Management

- **Auto-recovery**: Retries on rate limits
- **Session reports**: JSON reports with all actions, bugs, screenshots
- **Screenshot capture**: Every step is documented
- **State tracking**: Tracks visited screens and actions

---

## Environment Configuration

### Environment Variables
| Variable | Description | Default |
|----------|-------------|---------|
| `GOOGLE_API_KEY` | Gemini API key | Required |
| `VLM_MODEL_NAME` | Model to use | `gemini-2.5-flash` |
| `VLM_ENABLED` | Enable/disable AI | `1` |
| `MAX_STEPS` | Default max steps | `30` |
| `APPIUM_HOST` | Appium server host | `127.0.0.1` |
| `APPIUM_PORT` | Appium server port | `4723` |
| `AVD_NAME` | Android emulator name | `Pixel_2_API_30` |

---

## Output & Reports

All outputs are saved to `python_agent/artifacts/`:

```
artifacts/
├── reports/           # JSON test reports
│   ├── ai_session_*.json
│   ├── workflow_report_*.json
│   └── generated_tests.json
├── screenshots/       # Step-by-step screenshots
└── logs/             # Execution logs
```

### Report Contents
- Session ID and timestamp
- All actions taken with success/failure
- Bugs found with descriptions
- Screenshots for each step
- Screens visited
- Test coverage metrics

---

## CLI Options

| Option | Description |
|--------|-------------|
| `--task "text"` | Execute natural language task |
| `--explore` | Autonomous exploration mode |
| `--interactive` | Interactive chat mode |
| `--generate-tests` | Generate test scenarios |
| `--workflow <file>` | Run workflow JSON file |
| `--vision` | Enable visual checks (with workflow) |
| `--max-steps <n>` | Maximum steps (default: 30) |
| `--out <path>` | Custom output path |
