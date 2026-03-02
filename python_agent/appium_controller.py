from __future__ import annotations

import time

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.actions import interaction

from . import config
from .logging_config import get_logger

logger = get_logger("appium_controller")

class AppiumController:
    def __init__(self):
        self.driver = None
        self.app_is_open = False

    def start_driver(self):
        config.SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)

        options = UiAutomator2Options().load_capabilities(config.ANDROID_CAPABILITIES)
        
        try:
            self.driver = webdriver.Remote(command_executor=config.APPIUM_SERVER_URL, options=options)
            self.app_is_open = True
            logger.info("Appium driver started successfully.")
        except Exception as e:
            logger.error("Error starting Appium driver: %s", e, exc_info=True)
            self.app_is_open = False

    # ── Sentinel string emitted by UiAutomator2 when instrumentation dies ──
    _DEAD_SESSION_MARKERS = (
        "instrumentation process is not running",
        "cannot be proxied to UiAutomator2 server",
        "session is either terminated or not started",
    )

    def is_session_alive(self) -> bool:
        """Quick health-check: try to fetch page source to confirm the session is usable."""
        if not self.driver:
            return False
        try:
            self.driver.page_source
            return True
        except Exception as e:
            msg = str(e).lower()
            if any(m in msg for m in self._DEAD_SESSION_MARKERS):
                logger.warning("Session is dead (instrumentation crashed).")
                return False
            # Some transient error  --  still probably alive
            return True

    def restart_driver(self) -> bool:
        """Tear down the current (dead) session and create a fresh one."""
        logger.warning("Restarting Appium driver session...")
        # 1. Kill any leftover session
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        self.driver = None
        self.app_is_open = False

        # 2. Small pause so Appium/UiAutomator2 can clean up
        import time
        time.sleep(2)

        # 3. Create a new session
        self.start_driver()
        if self.app_is_open:
            logger.info("Driver session restarted successfully.")
        else:
            logger.error("Driver restart FAILED.")
        return self.app_is_open

    def stop_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            self.app_is_open = False
            logger.info("Appium driver stopped.")

    def get_page_source(self):
        if not self.driver:
            return None
        try:
            return self.driver.page_source
        except WebDriverException as e:
            logger.error("Error getting page source: %s", e)
            return None

    def take_screenshot(self, filename="screenshot.png"):
        if not self.driver:
            return None
        path = config.SCREENSHOTS_DIR / filename
        try:
            self.driver.save_screenshot(str(path))
            return str(path)
        except WebDriverException as e:
            logger.error("Error taking screenshot: %s", e)
            return None

    def find_element(self, by, value):
        if not self.driver:
            return None
        try:
            return self.driver.find_element(by, value)
        except NoSuchElementException:
            return None

    def find_by_accessibility_id(self, accessibility_id: str):
        return self.find_element(AppiumBy.ACCESSIBILITY_ID, accessibility_id)

    def find_by_id(self, resource_id: str):
        return self.find_element(AppiumBy.ID, resource_id)

    def find_by_android_uiautomator(self, uiautomator: str):
        return self.find_element(AppiumBy.ANDROID_UIAUTOMATOR, uiautomator)


    def click_element(self, element):
        if element:
            element.click()

    def input_text(self, element, text):
        if element:
            element.send_keys(text)

    def hide_keyboard(self):
        """Hides the on-screen keyboard if it's visible."""
        if not self.driver:
            return False
        try:
            if self.driver.is_keyboard_shown():
                self.driver.hide_keyboard()
                return True
            return False
        except WebDriverException:
            # Fallback: tap on empty space at top of screen
            try:
                size = self.driver.get_window_size()
                self.driver.tap([(size["width"] // 2, 50)], 100)
                return True
            except:
                return False

    def press_keycode(self, keycode: int):
        """Press an Android keycode (e.g., 66 for Enter/Next)."""
        if not self.driver:
            return False
        try:
            self.driver.press_keycode(keycode)
            return True
        except WebDriverException as e:
            logger.error("Error pressing keycode %d: %s", keycode, e)
            return False

    def press_enter(self):
        """Press Enter/Next key to move to next field or submit."""
        return self.press_keycode(66)  # KEYCODE_ENTER

    def press_back(self):
        """Press the Android back button."""
        return self.press_keycode(4)  # KEYCODE_BACK

    def is_keyboard_shown(self) -> bool:
        """Check if the keyboard is currently visible."""
        if not self.driver:
            return False
        try:
            return self.driver.is_keyboard_shown()
        except:
            return False

    def scroll(self, direction: str):
        """Performs a scroll action using W3C Actions (compatible with Appium 2+)."""
        if not self.driver:
            return False

        try:
            size = self.driver.get_window_size()
            width = size["width"]
            height = size["height"]

            # Use conservative range to avoid edge gestures
            if direction == "down":
                sx, sy = width // 2, int(height * 0.70)
                ex, ey = width // 2, int(height * 0.30)
            elif direction == "up":
                sx, sy = width // 2, int(height * 0.30)
                ex, ey = width // 2, int(height * 0.70)
            elif direction == "left":
                sx, sy = int(width * 0.75), height // 2
                ex, ey = int(width * 0.25), height // 2
            elif direction == "right":
                sx, sy = int(width * 0.25), height // 2
                ex, ey = int(width * 0.75), height // 2
            else:
                logger.warning("Unknown scroll direction: %s", direction)
                return False

            return self.swipe(sx, sy, ex, ey)
        except Exception as e:
            logger.error("Error scrolling %s: %s", direction, e)
            return False

    def swipe(self, start_x, start_y, end_x, end_y, duration=600):
        """Perform a swipe using W3C Actions (Appium 2 compatible)."""
        if not self.driver:
            return False
        try:
            finger = PointerInput(interaction.POINTER_TOUCH, "finger")
            actions = ActionChains(self.driver)
            actions.w3c_actions = ActionBuilder(self.driver, mouse=finger)
            actions.w3c_actions.pointer_action.move_to_location(start_x, start_y)
            actions.w3c_actions.pointer_action.pointer_down()
            actions.w3c_actions.pointer_action.pause(0.1)
            actions.w3c_actions.pointer_action.move_to_location(end_x, end_y)
            actions.w3c_actions.pointer_action.pause(0.05)
            actions.w3c_actions.pointer_action.release()
            actions.perform()
            logger.debug("Swipe (%d,%d)->(%d,%d)", start_x, start_y, end_x, end_y)
            return True
        except Exception as e:
            # Fallback to legacy swipe
            try:
                self.driver.swipe(start_x, start_y, end_x, end_y, duration)
                return True
            except WebDriverException as e2:
                logger.error("Error performing swipe: %s", e2)
                return False

    def long_press(self, element=None, x=None, y=None, duration_ms=1500):
        """Perform a long press on an element or coordinates using W3C Actions."""
        if not self.driver:
            return False
        try:
            finger = PointerInput(interaction.POINTER_TOUCH, "finger")
            actions = ActionChains(self.driver)
            actions.w3c_actions = ActionBuilder(self.driver, mouse=finger)
            if element:
                loc = element.location
                sz = element.size
                cx = loc['x'] + sz['width'] // 2
                cy = loc['y'] + sz['height'] // 2
                actions.w3c_actions.pointer_action.move_to_location(cx, cy)
            elif x is not None and y is not None:
                actions.w3c_actions.pointer_action.move_to_location(x, y)
            else:
                return False
            actions.w3c_actions.pointer_action.pointer_down()
            actions.w3c_actions.pointer_action.pause(duration_ms / 1000)
            actions.w3c_actions.pointer_action.release()
            actions.perform()
            logger.debug("Long press at element=%s / (%s,%s)", element, x, y)
            return True
        except Exception as e:
            logger.error("Error performing long press: %s", e)
            return False

    def scroll_to_text(self, text: str):
        """Use UiAutomator2 scrollIntoView to scroll until text is visible."""
        if not self.driver:
            return None
        try:
            safe = text.replace('"', '\\"')
            el = self.driver.find_element(
                AppiumBy.ANDROID_UIAUTOMATOR,
                f'new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView(new UiSelector().textContains("{safe}"))'
            )
            return el
        except Exception as e:
            logger.debug("scroll_to_text('%s') failed: %s", text, e)
            return None

    def find_elements(self, by, value):
        """Find multiple elements matching the locator."""
        if not self.driver:
            return []
        try:
            return self.driver.find_elements(by, value)
        except Exception:
            return []

    def reset_app(self):
        if not self.driver:
            return
        try:
            # Newer Appium versions don't have reset(), use terminate + activate
            from . import config
            self.driver.terminate_app(config.APP_PACKAGE)
            self.driver.activate_app(config.APP_PACKAGE)
        except Exception as e:
            logger.error("Error resetting app: %s", e)

    # ── Coordinate-based interactions ────────────────────────────────

    def tap_at(self, x: int, y: int):
        """Tap at absolute screen coordinates using W3C Actions."""
        if not self.driver:
            return False
        try:
            finger = PointerInput(interaction.POINTER_TOUCH, "finger")
            actions = ActionChains(self.driver)
            actions.w3c_actions = ActionBuilder(self.driver, mouse=finger)
            actions.w3c_actions.pointer_action.move_to_location(x, y)
            actions.w3c_actions.pointer_action.pointer_down()
            actions.w3c_actions.pointer_action.pause(0.05)
            actions.w3c_actions.pointer_action.release()
            actions.perform()
            logger.debug("Tap at (%d, %d)", x, y)
            return True
        except Exception as e:
            logger.error("Error tapping at (%d, %d): %s", x, y, e)
            return False

    def type_at_coordinates(self, x: int, y: int, text: str) -> bool:
        """Tap at coordinates to focus the field, then type text via keyboard."""
        if not self.driver:
            return False
        try:
            # Tap to focus
            if not self.tap_at(x, y):
                return False
            time.sleep(0.4)

            # Try send_keys on the active/focused element
            try:
                active = self.driver.switch_to.active_element
                if active:
                    active.clear()
                    active.send_keys(text)
                    self.hide_keyboard()
                    return True
            except Exception:
                pass

            # Fallback: use press_keycode for each character via ADB keyboard
            # This always works regardless of context
            from appium.webdriver.extensions.android.nativekey import AndroidKey
            self.driver.press_keycode(67)  # KEYCODE_DEL to clear first
            time.sleep(0.1)
            for ch in text:
                code = ord(ch)
                if 97 <= code <= 122:  # a-z
                    self.driver.press_keycode(code - 68)
                elif 65 <= code <= 90:  # A-Z
                    self.driver.press_keycode(code - 36, 1)  # with SHIFT
                elif 48 <= code <= 57:  # 0-9
                    self.driver.press_keycode(code - 41)
                elif ch == '@':
                    self.driver.press_keycode(77, 1)  # SHIFT + @
                elif ch == '.':
                    self.driver.press_keycode(56)
                elif ch == ' ':
                    self.driver.press_keycode(62)
                elif ch == '-':
                    self.driver.press_keycode(69)
                elif ch == '_':
                    self.driver.press_keycode(69, 1)
                elif ch == '+':
                    self.driver.press_keycode(81)
                else:
                    # Skip unsupported chars
                    continue
                time.sleep(0.05)
            self.hide_keyboard()
            return True
        except Exception as e:
            logger.error("Error typing at (%d, %d): %s", x, y, e)
            return False

