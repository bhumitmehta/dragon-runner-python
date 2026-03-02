[CmdletBinding(DefaultParameterSetName='task')]
param(
    [Parameter(ParameterSetName='task', Position=0)]
    [string]$task = "Toggle the bug mode switch on and off, then test the login feature to see if bugs appear when bug mode is on",

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

Write-Host "=== Demo App Test Runner ===" -ForegroundColor Cyan

# Set paths
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$apkPath = Join-Path $repoRoot "demo-app\android\app\build\outputs\apk\debug\app-debug.apk"

if (-not (Test-Path $apkPath)) {
  Write-Host "APK not found at: $apkPath" -ForegroundColor Red
  Write-Host "Build it first: cd demo-app\android; .\gradlew assembleDebug" -ForegroundColor Yellow
  exit 1
}

# Configure environment for demo-app
$env:APK_PATH = $apkPath
$env:APP_PACKAGE = "com.demoappgenerated"
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

# Start Metro bundler in background
Write-Host "Starting Metro bundler..." -ForegroundColor Yellow
Push-Location (Join-Path $repoRoot "demo-app")
$metroJob = Start-Job -ScriptBlock {
  param($demoAppPath)
  Set-Location $demoAppPath
  npx react-native start
} -ArgumentList (Join-Path $repoRoot "demo-app")
Pop-Location

Write-Host "Waiting for Metro to start (15 seconds)..." -ForegroundColor Yellow
Start-Sleep -Seconds 15

Write-Host "Running AI agent to test demo-app with bug toggle..." -ForegroundColor Cyan
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
  # Stop Metro
  Write-Host "Stopping Metro bundler..." -ForegroundColor Yellow
  Stop-Job -Job $metroJob -ErrorAction SilentlyContinue
  Remove-Job -Job $metroJob -ErrorAction SilentlyContinue
}
