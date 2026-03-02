[CmdletBinding(DefaultParameterSetName='task')]
param(
    [Parameter(ParameterSetName='task', Position=0)]
    [string]$task = "Log in with valid credentials and then log out.",

    [Parameter(ParameterSetName='explore')]
    [switch]$explore,

    [Parameter(ParameterSetName='interactive')]
    [switch]$interactive,

    [Parameter(ParameterSetName='generate')]
    [switch]$generateTests,

    [Parameter(ParameterSetName='workflow', Mandatory=$true)]
    [string]$workflow,

    [Parameter(ParameterSetName='workflow')]
    [switch]$vision
)

$ErrorActionPreference = 'Stop'

Write-Host "=== WDIO Demo App Test Runner ===" -ForegroundColor Cyan

# Set paths
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$apkPath = Join-Path $repoRoot "appium-wdio-react-native-ios-android\app\android\Android-MyDemoAppRN.1.3.0.build-244.apk"

if (-not (Test-Path $apkPath)) {
  Write-Host "APK not found at: $apkPath" -ForegroundColor Red
  exit 1
}

# Configure environment for the WDIO demo app
$env:APK_PATH = $apkPath
$env:APP_PACKAGE = "com.saucelabs.mydemoapp.rn"
$env:APP_ACTIVITY = ".MainActivity"
$env:APPIUM_HOST = '127.0.0.1'
$env:APPIUM_PORT = '4723'
$env:APPIUM_BASE_PATH = '/wd/hub'
$env:AVD_NAME = 'Pixel_2_API_30'

Write-Host "APK: $apkPath" -ForegroundColor Green
Write-Host "Package: $env:APP_PACKAGE" -ForegroundColor Green
Write-Host ""

# Kill any stuck emulator/adb
Write-Host "Restarting ADB..." -ForegroundColor Yellow
adb kill-server | Out-Null
Start-Sleep -Seconds 1
adb start-server | Out-Null

Write-Host "Running AI agent to test the WDIO demo app..." -ForegroundColor Cyan
Write-Host ""

try {
  # Run the agent based on the selected mode
  if ($PSCmdlet.ParameterSetName -eq 'task') {
    python -m python_agent.main --task "$task" --max-steps 20
  } elseif ($PSCmdlet.ParameterSetName -eq 'explore') {
    python -m python_agent.main --explore --max-steps 30
  } elseif ($PSCmdlet.ParameterSetName -eq 'interactive') {
    python -m python_agent.main --interactive
  } elseif ($PSCmdlet.ParameterSetName -eq 'generate') {
    python -m python_agent.main --generate-tests
  } elseif ($PSCmdlet.ParameterSetName -eq 'workflow') {
    if ($vision) {
      python -m python_agent.main --workflow "$workflow" --vision
    } else {
      python -m python_agent.main --workflow "$workflow"
    }
  } else {
    # Default to task mode
    python -m python_agent.main --task "$task" --max-steps 20
  }
} finally {
  Write-Host "Test run finished." -ForegroundColor Green
}

# --- Other execution modes (for reference) ---
# You can comment out the line above and uncomment one of the lines below to use a different mode.

# 2. Exploration Mode
# python -m python_agent.main --explore --max-steps 30

# 3. Workflow Mode
# python -m python_agent.main --workflow "python_agent/workflows/sample_login_logout.json"
