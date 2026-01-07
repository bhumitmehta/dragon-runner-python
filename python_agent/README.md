# Dragon Runner Python Agent

An AI-powered mobile app testing agent that uses vision language models and LLMs to autonomously test, explore, and find bugs in mobile applications.

## Features

- **🤖 AI-Powered Exploration**: Autonomously explores your app, discovers screens, and finds bugs
- **🗣️ Natural Language Tasks**: Give commands in plain English like "Login with bob@example.com"
- **📝 Static Workflow Tests**: Run predefined test scenarios from JSON files
- **🔍 Visual Bug Detection**: Uses Google Gemini VLM to detect UI/UX issues
- **🧪 Test Generation**: Automatically generates test scenarios by analyzing the app
- **💬 Interactive Mode**: Chat with the AI agent in real-time

## Installation

```bash
cd python_agent
pip install -r requirements.txt
```

## Configuration

Set your Google API key for VLM features:

```bash
# Windows
set GOOGLE_API_KEY=your_api_key

# Linux/Mac  
export GOOGLE_API_KEY=your_api_key
```

## Usage

### 1. Static Workflow Tests (Predefined Scenarios)

Run test scenarios from a JSON file:

```bash
# Run the default test scenarios
python -m python_agent.main --workflow workflows/test_scenarios.json

# Run comprehensive tests
python -m python_agent.main --workflow workflows/comprehensive_test_scenarios.json

# Enable visual bug detection
python -m python_agent.main --workflow workflows/test_scenarios.json --vision
```

### 2. Natural Language Task Execution

Give the AI a task in plain English:

```bash
# Login task
python -m python_agent.main --task "Login with bob@example.com and password 10203040"

# Shopping task
python -m python_agent.main --task "Add the first product to cart and proceed to checkout"

# Navigation task
python -m python_agent.main --task "Go to the WebView section from the menu"
```

### 3. Autonomous Exploration

Let the AI explore and find bugs:

```bash
# Default exploration (30 steps)
python -m python_agent.main --explore

# Extended exploration
python -m python_agent.main --explore --max-steps 50
```

### 4. Interactive Mode

Chat with the AI agent:

```bash
python -m python_agent.main --interactive
```

In interactive mode, you can type commands like:
- "Click on the login button"
- "Add a product to cart"
- "Go back to the home screen"
- Type `quit` or `exit` to stop

### 5. Auto-Generate Tests

Let the AI analyze the app and generate test scenarios:

```bash
python -m python_agent.main --generate-tests
```

## Command Reference

| Option | Description |
|--------|-------------|
| `--workflow <file>` | Run a static workflow JSON file |
| `--task "<text>"` | Execute a natural language task |
| `--explore` | Autonomous bug-finding exploration |
| `--interactive` | Interactive chat mode |
| `--generate-tests` | Generate test scenarios automatically |
| `--vision` | Enable visual checks (for --workflow) |
| `--max-steps <n>` | Max steps for AI modes (default: 30) |
| `--out <path>` | Custom output report path |

## Workflow JSON Format

```json
{
  "version": 1,
  "data": {
    "username": "bob@example.com",
    "password": "10203040"
  },
  "workflows": [
    {
      "name": "Login Flow",
      "priority": "critical",
      "steps": [
        {
          "action": "click",
          "locator_strategy": "accessibility_id",
          "locator_value": "Login button",
          "note": "Tap login"
        },
        {
          "action": "input",
          "locator_strategy": "accessibility_id",
          "locator_value": "Username input field",
          "text": "${username}"
        },
        {
          "action": "scroll",
          "direction": "down"
        },
        {
          "action": "visual_check",
          "note": "Check for UI bugs"
        },
        {
          "action": "assert_contains",
          "assert_contains": "Welcome"
        },
        {
          "action": "reset"
        }
      ]
    }
  ]
}
```

### Supported Actions

| Action | Description | Parameters |
|--------|-------------|------------|
| `click` | Tap an element | `locator_strategy`, `locator_value` |
| `input` | Type text | `locator_strategy`, `locator_value`, `text` |
| `scroll` | Scroll/swipe | `direction` (up/down/left/right) |
| `wait` | Wait seconds | `seconds` |
| `visual_check` | AI visual bug check | `note` |
| `assert_contains` | Assert text visible | `assert_contains` |
| `reset` | Reset app state | - |

### Locator Strategies

- `accessibility_id` - Accessibility ID (recommended)
- `id` - Resource ID
- `xpath` - XPath selector
- `text` - Exact text match

## Reports

Test reports are saved to `python_agent/artifacts/reports/` as JSON files.

## Architecture

```
python_agent/
├── main.py              # CLI entry point
├── ai_tester.py         # AI-powered testing agent
├── workflow_runner.py   # Static workflow executor
├── appium_controller.py # Appium driver wrapper
├── vlm.py               # Google Gemini VLM integration
├── config.py            # Configuration
├── memory.py            # State tracking
├── workflows/           # Test scenario files
└── artifacts/           # Screenshots and reports
```

## Requirements

- Python 3.10+
- Appium Server
- Android device/emulator with USB debugging
- Google API Key (for AI features)
