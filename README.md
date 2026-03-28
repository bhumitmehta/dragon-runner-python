# Dragon Runner Python 🤖📱

An AI-powered autonomous mobile application testing system that uses a multi-agent architecture to intelligently test Android mobile applications without manual scripting.

## Overview

Dragon Runner combines Vision Language Models (VLM), Appium automation, and a multi-agent system to autonomously explore, test, and validate Android applications. It learns from each test run using persistent memory and can even localize bugs to specific source code files.

## Features

- 🤖 **12 Specialized AI Agents**: Orchestrator, Planner, Navigator, Critic, Explorer, Recovery, Reporter, Accessibility, Security, Doc Ingestion, Script Generator, and Script Executor
- 🧠 **Vision Language Models**: Uses Gemini or Ollama for visual understanding and decision-making
- 🔍 **Autonomous Exploration**: Curiosity-driven exploration to maximize screen coverage and find bugs
- 💾 **Persistent Memory**: Cross-run learning using TinyDB for features, navigation paths, and test results
- 🐛 **Bug Localization**: Maps detected bugs to source code using UniXcoder
- ♿ **Accessibility Auditing**: WCAG compliance checks per screen
- 🔒 **Security Scanning**: Detects data leaks and authentication issues
- 📊 **Visual Dashboard**: React-based frontend for viewing test results and navigation graphs
- 📝 **Multiple Test Modes**: Task-based, explorer, smart-test (documentation-driven), and workflow modes

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER / CLI (main.py)                      │
│  Modes: --task | --explorer | --smart-test | --workflow          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR AGENT                            │
│  Coordinates all agents · Manages lifecycle · Produces reports   │
└────────────────────────────┬────────────────────────────────────┘
                             │
         ┌───────────────────┼──────────────────┐
         ▼                   ▼                   ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────────────┐
│  VLM / LLM     │  │ Appium         │  │ Persistent Memory      │
│  (Gemini/      │  │ Controller     │  │                        │
│   Ollama)      │  │ + UiAutomator2 │  │ KnowledgeBase (TinyDB) │
│                │  │ + ADB          │  │ SessionMemory (in-proc)│
└────────────────┘  └────────────────┘  └────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ANDROID EMULATOR / DEVICE                     │
│              (Runs the React Native Demo App)                    │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- **Python 3.8+**
- **Android Studio** with Android SDK
- **Android Virtual Device (AVD)** - e.g., `Pixel_2_API_30`
- **Node.js/npm** (for Appium and demo app)
- **Java JDK** (for Android builds)

## Installation

### 1. Clone and Setup

```bash
cd python_agent
pip install -r requirements.txt
```

### 2. Set Environment Variables (PowerShell)

```powershell
$env:APPIUM_HOST='127.0.0.1'
$env:APPIUM_PORT='4723'
$env:APPIUM_BASE_PATH='/wd/hub'
$env:AVD_NAME='Pixel_2_API_30'
$env:GOOGLE_API_KEY='your-gemini-api-key'
$env:VLM_MODEL_NAME='gemini-2.5-flash'
```

### 3. Install Appium

```bash
npm install -g appium
appium driver install uiautomator2
```

### 4. Setup Demo App (Optional)

```bash
cd demo-app
npm install
# Build Android APK
npx react-native run-android
```

## Usage

### List Available Apps

```bash
python -m python_agent.main --list-apps
```

### Explorer Mode (Autonomous Testing)

```bash
# Explore the demo app autonomously
python -m python_agent.main --app demo-app --explorer

# With bug localization
python -m python_agent.main --app demo-app --explorer --localize --source-dir ./demo-app
```

### Task Mode (Natural Language)

```bash
python -m python_agent.main --app demo-app --task "Login with demo and password123"
```

### Smart-Test Mode (Documentation-Driven)

```bash
python -m python_agent.main --app demo-app --smart-test --docs ./docs
```

### Workflow Mode (Predefined Tests)

```bash
python -m python_agent.main --app demo-app --workflow ./workflows/test-workflow.json
```

### Start API Server

```bash
python -m python_agent.api
# Or with uvicorn directly
uvicorn python_agent.api:app --reload --port 8000
```

## Project Structure

```
dragon-runner-python/
├── python_agent/              # Core testing engine
│   ├── agents/               # Multi-agent system
│   │   ├── orchestrator.py   # Top-level coordinator
│   │   ├── planner.py        # Task decomposition
│   │   ├── navigator.py      # UI action execution
│   │   ├── critic.py         # Step validation
│   │   ├── explorer.py       # Autonomous exploration
│   │   ├── recovery.py       # Crash handling
│   │   ├── reporter.py       # Report generation
│   │   └── ...
│   ├── main.py               # CLI entry point
│   ├── api.py                # FastAPI REST API
│   ├── config.py             # Configuration & app profiles
│   ├── appium_controller.py  # Appium driver wrapper
│   ├── vlm.py                # Vision Language Model integration
│   ├── knowledge_base.py     # Persistent storage (TinyDB)
│   ├── workflow_runner.py    # Workflow execution
│   └── requirements.txt      # Python dependencies
│
├── demo-app/                 # React Native test app with bugs
│   ├── App.js               # Main app with navigation
│   ├── LoginScreen.js       # Login with bug mode
│   ├── ProductsScreen.js    # Product catalog
│   ├── CartScreen.js        # Cart with calculation bug
│   ├── CalculatorScreen.js  # Calculator
│   └── ContactFormScreen.js # Form validation
│
├── frontend/                 # React dashboard
│   ├── src/
│   └── package.json
│
├── appium-wdio-react-native-ios-android/  # Reference implementation
│
└── ladybug-main/             # Bug localization system
    ├── backend/              # Flask backend
    └── probot/               # GitHub bot integration
```

## Configuration

App profiles are defined in `python_agent/config.py`:

```python
APPS = {
    "saucelabs-demo": {
        "platformName": "Android",
        "appium:automationName": "UiAutomator2",
        "appium:app": "https://github.com/saucelabs/sample-app-mobile/releases/download/2.7.1/Android.SauceLabs.Mobile.Sample.app.2.7.1.apk",
        "appium:appWaitActivity": "com.swaglabsmobileapp.MainActivity"
    },
    "demo-app": {
        "platformName": "Android",
        "appium:automationName": "UiAutomator2",
        "appium:app": "./demo-app/android/app/build/outputs/apk/debug/app-debug.apk",
        "appium:appPackage": "com.demoapp",
        "appium:appActivity": ".MainActivity"
    }
}
```

## Demo App Features

The included React Native demo app has intentional bugs for testing:

- **LoginScreen**: Bug mode accepts any password
- **CartScreen**: Total calculation overcharges by 50%
- **ContactFormScreen**: Broken email validation in bug mode
- **Bug Mode Toggle**: Enable/disable bugs via settings

## Testing

```bash
# Run Python tests
cd python_agent
pytest

# Run specific test files
pytest test_semantic_fingerprint.py
pytest test_action_coverage.py
```

## Troubleshooting

### AVD/Emulator Issues

If `avdmanager` is not recognized:

```powershell
# Use full path to Android SDK tools
& "C:\Users\$env:USERNAME\AppData\Local\Android\Sdk\cmdline-tools\latest\bin\avdmanager.bat" --help

# Or add to PATH permanently
[Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";C:\Users\$env:USERNAME\AppData\Local\Android\Sdk\cmdline-tools\latest\bin", "User")
```

### Appium Connection Issues

1. Ensure emulator is running: `emulator -avd Pixel_2_API_30`
2. Start Appium server: `appium`
3. Check environment variables are set

### VLM Model Issues

- Ensure `GOOGLE_API_KEY` is set for Gemini
- For Ollama, ensure the model is pulled: `ollama pull llama3:8b`

## Documentation

- [Project Documentation](PROJECT_DOCUMENTATION.md)
- [System Architecture](SYSTEM_ARCHITECTURE.md)
- [Python Implementation Guide](PYTHON_IMPLEMENTATION_GUIDE.md)
- [Container Classification Guide](CONTAINER_CLASSIFICATION_GUIDE.md)

## Technologies Used

| Category | Technologies |
|----------|--------------|
| **Mobile Automation** | Appium 2.x, UiAutomator2, WebDriver.IO |
| **AI/ML Models** | Google Gemini, Ollama, UniXcoder |
| **Programming** | Python 3.x, JavaScript/TypeScript, React Native |
| **Database** | TinyDB (JSON-based), NetworkX (graph) |
| **API Framework** | FastAPI, Uvicorn |
| **Frontend** | React 18, Vite, Recharts, react-force-graph-2d |
| **Testing** | Pytest, Jest |

## License

See [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please ensure:

1. Code follows existing style patterns
2. Tests pass: `pytest`
3. Documentation is updated for new features

---

**Note**: This is a sophisticated autonomous testing framework. For production use, ensure proper API key management and review all AI-generated actions before execution in sensitive environments.
