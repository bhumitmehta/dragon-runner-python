from __future__ import annotations

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, WebDriverException

from . import config

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
            print("Appium driver started successfully.")
        except Exception as e:
            print(f"Error starting Appium driver: {e}")
            self.app_is_open = False

    def stop_driver(self):
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.app_is_open = False
            print("Appium driver stopped.")

    def get_page_source(self):
        if not self.driver:
            return None
        try:
            return self.driver.page_source
        except WebDriverException as e:
            print(f"Error getting page source: {e}")
            return None

    def take_screenshot(self, filename="screenshot.png"):
        if not self.driver:
            return None
        path = config.SCREENSHOTS_DIR / filename
        try:
            self.driver.save_screenshot(str(path))
            return str(path)
        except WebDriverException as e:
            print(f"Error taking screenshot: {e}")
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
            print(f"Error pressing keycode {keycode}: {e}")
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
        """Performs a scroll action in the given direction."""
        if not self.driver:
            return

        size = self.driver.get_window_size()
        width = size["width"]
        height = size["height"]

        start_x, start_y, end_x, end_y = 0, 0, 0, 0

        if direction == "down":
            start_x = width // 2
            start_y = int(height * 0.8)
            end_x = width // 2
            end_y = int(height * 0.2)
        elif direction == "up":
            start_x = width // 2
            start_y = int(height * 0.2)
            end_x = width // 2
            end_y = int(height * 0.8)
        elif direction == "left":
            start_x = int(width * 0.8)
            start_y = height // 2
            end_x = int(width * 0.2)
            end_y = height // 2
        elif direction == "right":
            start_x = int(width * 0.2)
            start_y = height // 2
            end_x = int(width * 0.8)
            end_y = height // 2
        
        self.swipe(start_x, start_y, end_x, end_y)

    def swipe(self, start_x, start_y, end_x, end_y, duration=800):
        if not self.driver:
            return
        try:
            self.driver.swipe(start_x, start_y, end_x, end_y, duration)
        except WebDriverException as e:
            print(f"Error performing swipe: {e}")

    def reset_app(self):
        if not self.driver:
            return
        try:
            # Newer Appium versions don't have reset(), use terminate + activate
            from . import config
            self.driver.terminate_app(config.APP_PACKAGE)
            self.driver.activate_app(config.APP_PACKAGE)
        except Exception as e:
            print(f"Error resetting app: {e}")
