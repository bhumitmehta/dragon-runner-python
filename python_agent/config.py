import os
from pathlib import Path

from dotenv import load_dotenv

# Explicitly load .env from the python_agent directory
_config_dir = Path(__file__).resolve().parent
_env_file = _config_dir / ".env"
load_dotenv(_env_file, override=True)  # override=True ensures new values are loaded

REPO_ROOT = Path(__file__).resolve().parents[1]

# ════════════════════════════════════════════════════════════════════
#  App Profiles — predefined configurations for known apps.
#  Select at runtime with: --app <profile_name>  or  APP_PROFILE env var.
# ════════════════════════════════════════════════════════════════════

APP_PROFILES: dict[str, dict] = {
    "saucelabs-demo": {
        "app_package": "com.saucelabs.mydemoapp.rn",
        "app_activity": ".MainActivity",
        "apk_path": str(
            REPO_ROOT
            / "appium-wdio-react-native-ios-android"
            / "app"
            / "android"
            / "Android-MyDemoAppRN.1.3.0.build-244.apk"
        ),
        "source_code_dir": str(REPO_ROOT / "demo-app"),
        "source_extensions": ".js,.ts,.tsx,.jsx",
        "description": "SauceLabs My Demo App (React Native)",
    },
    "demo-app": {
        "app_package": "com.demoappgenerated",
        "app_activity": ".MainActivity",
        "apk_path": str(
            REPO_ROOT
            / "demo-app"
            / "android"
            / "app"
            / "build"
            / "outputs"
            / "apk"
            / "debug"
            / "app-debug.apk"
        ),
        "source_code_dir": str(REPO_ROOT / "demo-app"),
        "source_extensions": ".js,.ts,.tsx,.jsx",
        "description": "Demo App Generated (React Native)",
    },
    # Add more profiles here, e.g.:
    # "my-native-app": {
    #     "app_package": "com.example.myapp",
    #     "app_activity": ".MainActivity",
    #     "apk_path": "/path/to/myapp.apk",
    #     "source_code_dir": "/path/to/myapp/src",
    #     "source_extensions": ".java,.kt,.xml",
    #     "description": "My Native Android App",
    # },
}

# Which profile to use (CLI --app flag overrides this)
_active_profile_name = os.getenv("APP_PROFILE", "").strip()


def apply_app_profile(profile_name: str) -> None:
    """
    Activate an app profile, overwriting the module-level config variables.

    Called either from ``main.py`` when ``--app <name>`` is passed, or from
    here when ``APP_PROFILE`` env-var is set.
    """
    global APP_PACKAGE, APP_ACTIVITY, APK_PATH, SOURCE_CODE_DIR, SOURCE_CODE_EXTENSIONS
    profile = APP_PROFILES.get(profile_name)
    if not profile:
        avail = ", ".join(APP_PROFILES.keys()) or "(none)"
        raise ValueError(
            f"Unknown app profile '{profile_name}'. Available: {avail}"
        )
    APP_PACKAGE = profile["app_package"]
    APP_ACTIVITY = profile["app_activity"]
    APK_PATH = Path(profile["apk_path"])
    SOURCE_CODE_DIR = Path(profile["source_code_dir"])
    SOURCE_CODE_EXTENSIONS = [
        e.strip() for e in profile.get("source_extensions", "").split(",") if e.strip()
    ] or SOURCE_CODE_EXTENSIONS
    # Re-derive capabilities with the new values
    ANDROID_CAPABILITIES["appium:app"] = str(APK_PATH)
    ANDROID_CAPABILITIES["appium:appPackage"] = APP_PACKAGE
    ANDROID_CAPABILITIES["appium:appActivity"] = APP_ACTIVITY


# App under test (Android) — defaults, may be overridden by profile
APP_PACKAGE = os.getenv("APP_PACKAGE", "com.saucelabs.mydemoapp.rn")
APP_ACTIVITY = os.getenv("APP_ACTIVITY", ".MainActivity")

_default_apk_path = (
    REPO_ROOT
    / "appium-wdio-react-native-ios-android"
    / "app"
    / "android"
    / "Android-MyDemoAppRN.1.3.0.build-244.apk"
)
_apk_path_env = os.getenv("APK_PATH")
APK_PATH = Path(_apk_path_env).expanduser() if _apk_path_env else _default_apk_path

# Device / emulator
EMULATOR_AVD = os.getenv("ANDROID_AVD") or os.getenv("AVD_NAME") or "Pixel_2_API_30"
ADB_TARGET_DEVICE = os.getenv("ANDROID_DEVICE_ID") or os.getenv("ANDROID_SERIAL") or "emulator-5554"

# Appium
_appium_server_url = os.getenv("APPIUM_SERVER_URL")
if not _appium_server_url:
    host = os.getenv("APPIUM_HOST", "127.0.0.1")
    port = os.getenv("APPIUM_PORT", "4723")
    base_path = os.getenv("APPIUM_BASE_PATH", "/wd/hub").rstrip("/")
    if not base_path:
        base_path = "/wd/hub"
    _appium_server_url = f"http://{host}:{port}{base_path}"

APPIUM_SERVER_URL = _appium_server_url
ANDROID_CAPABILITIES = {
    "platformName": "Android",
    "appium:automationName": "UiAutomator2",
    "appium:deviceName": ADB_TARGET_DEVICE,
    "appium:app": str(APK_PATH),
    "appium:appPackage": APP_PACKAGE,
    "appium:appActivity": APP_ACTIVITY,
    "appium:noReset": True,
    "appium:newCommandTimeout": 120,
}

# Google (Gemini)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
# gemini-2.5-flash has separate quota pool from gemini-2.0-flash
VLM_MODEL_NAME = os.getenv("VLM_MODEL_NAME", "gemini-2.5-flash")
VLM_ENABLED = os.getenv("VLM_ENABLED", "1").strip().lower() not in ("0", "false", "no")

# Ollama (local LLM fallback)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3:8b")
# Auto-fallback: use Ollama when Gemini is unavailable (quota exceeded, no API key, etc.)
OLLAMA_FALLBACK = os.getenv("OLLAMA_FALLBACK", "1").strip().lower() not in ("0", "false", "no")

# Agent
MAX_STEPS = int(os.getenv("MAX_STEPS", "30"))
MAX_SAME_STATE = int(os.getenv("MAX_SAME_STATE", "3"))
ACTION_RETRY_BUDGET = int(os.getenv("ACTION_RETRY_BUDGET", "2"))

ARTIFACTS_DIR = REPO_ROOT / "python_agent" / "artifacts"
SCREENSHOTS_DIR = ARTIFACTS_DIR / "screenshots"
LOGS_DIR = ARTIFACTS_DIR / "logs"
REPORTS_DIR = ARTIFACTS_DIR / "reports"
NAVIGATION_MEMORY_FILE = ARTIFACTS_DIR / "navigation_memory.json"
APPIUM_LOG_FILE = LOGS_DIR / "appium.log"

# Bug Localization
BUG_LOCALIZATION_ENABLED = os.getenv("BUG_LOCALIZATION_ENABLED", "0").strip().lower() not in ("0", "false", "no")
# Directory containing the source code of the app under test (for bug-to-source mapping)
_source_dir_env = os.getenv("SOURCE_CODE_DIR")
SOURCE_CODE_DIR: Path | None = Path(_source_dir_env).expanduser() if _source_dir_env else (REPO_ROOT / "demo-app")
SOURCE_CODE_EXTENSIONS = [
    ext.strip()
    for ext in os.getenv("SOURCE_CODE_EXTENSIONS", ".js,.ts,.tsx,.jsx,.java,.kt,.py,.swift,.m").split(",")
    if ext.strip()
]
BUG_LOCALIZATION_TOP_N = int(os.getenv("BUG_LOCALIZATION_TOP_N", "10"))
TRACES_DIR = ARTIFACTS_DIR / "traces"

# ── Auto-apply profile if set via env var ────────────────────────────
if _active_profile_name:
    try:
        apply_app_profile(_active_profile_name)
    except ValueError as exc:
        import warnings
        warnings.warn(str(exc))

