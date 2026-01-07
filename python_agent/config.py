import os
from pathlib import Path

from dotenv import load_dotenv

# Explicitly load .env from the python_agent directory
_config_dir = Path(__file__).resolve().parent
_env_file = _config_dir / ".env"
load_dotenv(_env_file, override=True)  # override=True ensures new values are loaded

REPO_ROOT = Path(__file__).resolve().parents[1]

# App under test (Android)
APP_PACKAGE = "com.saucelabs.mydemoapp.rn"
APP_ACTIVITY = ".MainActivity"
APK_PATH = (
    REPO_ROOT
    / "appium-wdio-react-native-ios-android"
    / "app"
    / "android"
    / "Android-MyDemoAppRN.1.3.0.build-244.apk"
)

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

