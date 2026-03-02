## Prereqs

- Android Studio / Android SDK installed
- AVD created (example below uses `Pixel_2_API_30`)
- Node/npm installed (for Appium). This repo can run Appium via `npx`.
- Python installed

## (Optional) Verify Appium is available

If you installed Appium globally:

```powershell
appium -v
```

If you did NOT install globally, you can still run via `npx`:

```powershell
npx --yes appium --version
```

If you want to use the pinned Appium dependency from the attached reference project:

```powershell
Push-Location .\appium-wdio-react-native-ios-android
npx appium --version
Pop-Location
```

## Environment variables (PowerShell)

These env vars are understood by the Python agent (it builds the Appium URL and chooses the AVD from them):

```powershell
$env:APPIUM_HOST='127.0.0.1'
$env:APPIUM_PORT='4723'
$env:APPIUM_BASE_PATH='/wd/hub'
$env:AVD_NAME='Pixel_2_API_30'

# Optional: pick a Gemini model that exists for your API key
# (You can list available ones with a small python snippet; default is models/gemini-2.0-flash)
$env:VLM_MODEL_NAME='models/gemini-2.0-flash'
```

## Run the Python agent (auto-starts emulator + Appium)

From the repo root:

```powershell
python -m python_agent.main
```

Notes:
- The agent will try to start the emulator and then start Appium using `appium` or `npx --yes appium`.
- If the folder `appium-wdio-react-native-ios-android` exists and has `node_modules`, the agent will run `npx appium` from there (so it uses the same Appium version as the reference setup).
- Logs go to `python_agent/artifacts/logs/appium.log`.


