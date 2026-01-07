# Python Implementation Guide for Mobile Automation

This guide provides a step-by-step approach to implementing the functionality of the Appium + WebDriver.IO framework in Python using the Appium-Python-Client.

---

## Prerequisites

### Install Python
Ensure Python 3.8+ is installed on your system. You can download it from [python.org](https://www.python.org/).

### Install Required Libraries
Install the following Python libraries:
```bash
pip install appium
pip install pytest
pip install pytest-html
```

---

## Project Structure

### Suggested Directory Layout
```
python_project/
│
├── tests/
│   ├── android/
│   │   └── test_login.py
│   ├── ios/
│   │   └── test_login.py
│
├── screen_objects/
│   ├── android/
│   │   └── login_screen.py
│   ├── ios/
│       └── login_screen.py
│
├── config/
│   ├── android_config.py
│   └── ios_config.py
│
└── requirements.txt
```

---

## Configuration

### Android Configuration
Create `config/android_config.py`:
```python
ANDROID_CAPABILITIES = {
    "platformName": "Android",
    "deviceName": "emulator-5554",
    "automationName": "UIAutomator2",
    "app": "path/to/your/android/app.apk",
    "noReset": True
}
```

### iOS Configuration
Create `config/ios_config.py`:
```python
IOS_CAPABILITIES = {
    "platformName": "iOS",
    "deviceName": "iPhone 14 Plus",
    "automationName": "XCUITest",
    "app": "path/to/your/ios/app.app",
    "noReset": True
}
```

---

## Writing Tests

### Example Test for Android
Create `tests/android/test_login.py`:
```python
import pytest
from appium import webdriver
from screen_objects.android.login_screen import LoginScreen
from config.android_config import ANDROID_CAPABILITIES

@pytest.fixture(scope="module")
def driver():
    driver = webdriver.Remote("http://localhost:4723/wd/hub", ANDROID_CAPABILITIES)
    yield driver
    driver.quit()

def test_login(driver):
    login_screen = LoginScreen(driver)
    login_screen.login("username", "password")
    assert login_screen.is_logged_in()
```

### Example Test for iOS
Create `tests/ios/test_login.py`:
```python
import pytest
from appium import webdriver
from screen_objects.ios.login_screen import LoginScreen
from config.ios_config import IOS_CAPABILITIES

@pytest.fixture(scope="module")
def driver():
    driver = webdriver.Remote("http://localhost:4723/wd/hub", IOS_CAPABILITIES)
    yield driver
    driver.quit()

def test_login(driver):
    login_screen = LoginScreen(driver)
    login_screen.login("username", "password")
    assert login_screen.is_logged_in()
```

---

## Screen Objects

### Android Login Screen
Create `screen_objects/android/login_screen.py`:
```python
from appium.webdriver.common.appiumby import AppiumBy

class LoginScreen:
    def __init__(self, driver):
        self.driver = driver
        self.username_field = (AppiumBy.ACCESSIBILITY_ID, "username")
        self.password_field = (AppiumBy.ACCESSIBILITY_ID, "password")
        self.login_button = (AppiumBy.ACCESSIBILITY_ID, "login")

    def login(self, username, password):
        self.driver.find_element(*self.username_field).send_keys(username)
        self.driver.find_element(*self.password_field).send_keys(password)
        self.driver.find_element(*self.login_button).click()

    def is_logged_in(self):
        return self.driver.find_element(AppiumBy.ACCESSIBILITY_ID, "logout").is_displayed()
```

### iOS Login Screen
Create `screen_objects/ios/login_screen.py`:
```python
from appium.webdriver.common.appiumby import AppiumBy

class LoginScreen:
    def __init__(self, driver):
        self.driver = driver
        self.username_field = (AppiumBy.ACCESSIBILITY_ID, "username")
        self.password_field = (AppiumBy.ACCESSIBILITY_ID, "password")
        self.login_button = (AppiumBy.ACCESSIBILITY_ID, "login")

    def login(self, username, password):
        self.driver.find_element(*self.username_field).send_keys(username)
        self.driver.find_element(*self.password_field).send_keys(password)
        self.driver.find_element(*self.login_button).click()

    def is_logged_in(self):
        return self.driver.find_element(AppiumBy.ACCESSIBILITY_ID, "logout").is_displayed()
```

---

## Running Tests

### Android Tests
Run the following command:
```bash
pytest tests/android --html=report.html
```

### iOS Tests
Run the following command:
```bash
pytest tests/ios --html=report.html
```

---

## Conclusion
This guide provides the foundation for implementing mobile automation in Python. You can extend this framework by adding more screen objects, test cases, and configurations.