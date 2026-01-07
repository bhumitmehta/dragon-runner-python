# Detailed Documentation: Appium + WebDriver.IO Framework

## Overview
This project demonstrates how to perform mobile testing using Appium and WebDriver.IO for both Android and iOS platforms. It includes configurations, dependencies, and scripts to automate mobile applications.

---

## System Requirements

### General Requirements
1. **Node.js**: Required for downloading Appium and drivers.
2. **Java JDK**: Necessary for Android development.
3. **Android Studio**: For Android emulators and tools.
4. **XCode**: For iOS development.

### Environment Variables
- **JAVA_HOME**: Points to the Java JDK installation.
- **ANDROID_HOME**: Points to the Android SDK installation.

---

## Project Structure

### Key Directories
- `config/`: Contains WebDriver.IO configuration files for Android and iOS.
- `test/`: Contains test specifications and screen object models.
- `app/`: Contains the mobile application files for Android and iOS.

### Key Files
- `package.json`: Defines project dependencies and scripts.
- `android-wdio.conf.js`: WebDriver.IO configuration for Android.
- `ios-wdio.conf.js`: WebDriver.IO configuration for iOS.

---

## Installation and Setup

### Step 1: Install Dependencies
Run the following command to install all dependencies:
```bash
npm install
```

### Step 2: Configure Environment Variables
Set up `JAVA_HOME` and `ANDROID_HOME` as per your operating system.

### Step 3: Install Appium
Install Appium globally:
```bash
npm install -g appium@next
```

### Step 4: Install Appium Drivers
Install the required drivers:
```bash
appium driver install xcuitest
appium driver install uiautomator2
```

---

## Android Configuration

### WebDriver.IO Configuration
The `android-wdio.conf.js` file includes:
- **Capabilities**:
  ```javascript
  capabilities: [{
      platformName: 'Android',
      "appium:deviceName": 'emulator-5554',
      "appium:automationName": "UIAutomator2",
      "appium:app": androidAppPath,
  }]
  ```
- **Services**:
  ```javascript
  services: [
      ['appium', {
          command: 'npx appium',
          logPath: './appium.log',
      }]
  ]
  ```

### Running Tests
Use the following script to run Android tests:
```bash
npm run wdioAndroid
```

---

## iOS Configuration

### WebDriver.IO Configuration
The `ios-wdio.conf.js` file includes:
- **Capabilities**:
  ```javascript
  capabilities: [{
      platformName: 'iOS',
      "appium:deviceName": 'iPhone 14 Plus',
      "appium:automationName": "XCUItest",
      "appium:app": iosAppPath,
  }]
  ```
- **Services**:
  ```javascript
  services: [
      ['appium', {
          args: {
              address: 'localhost',
              port: 4723,
          }
      }]
  ]
  ```

### Running Tests
Use the following script to run iOS tests:
```bash
npm run wdioIos
```

---

## Writing Tests

### Test Structure
- **Screen Objects**: Located in `test/screenObjects/`.
- **Test Specs**: Located in `test/specs/`.

### Example Test
```javascript
describe('Login Test', () => {
    it('should login successfully', () => {
        const loginScreen = require('../screenObjects/Login.screen');
        loginScreen.login('username', 'password');
    });
});
```

---

## Debugging and Troubleshooting

### Appium Doctor
Check system requirements:
```bash
appium-doctor
```

### Logs
- Appium logs: `./appium.log`
- WebDriver.IO logs: Configured in `logLevel`.

---

## Additional Resources
- [WebDriver.IO Documentation](https://webdriver.io/docs/gettingstarted)
- [Appium Documentation](https://appium.io/docs/en/about-appium/)

---

## Conclusion
This framework provides a robust setup for mobile automation testing. By following the configurations and examples, you can extend this project or implement similar functionality in other languages like Python.