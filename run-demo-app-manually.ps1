$ErrorActionPreference = 'Stop'

Write-Host "=== Manual Demo App Runner ===" -ForegroundColor Cyan

# --- FIX: Set JDK 17 for this script session ---
$jdk17Path = "C:\Program Files\Eclipse Adoptium\jdk-17.0.17.10-hotspot"
if (-not (Test-Path $jdk17Path)) {
  Write-Host "JDK 17 not found at $jdk17Path. Please install it." -ForegroundColor Red
  exit 1
}
$env:JAVA_HOME = $jdk17Path
$env:Path = "$($jdk17Path)\bin;" + $env:Path
Write-Host "Temporarily switched to Java 17 for this build." -ForegroundColor Green
java -version
# --- End of FIX ---

# Set paths
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$demoAppPath = Join-Path $repoRoot "demo-app"

# 1. Restart ADB and set up port forwarding for Metro
Write-Host "Restarting ADB and setting up Metro port forwarding..." -ForegroundColor Yellow
adb kill-server | Out-Null
Start-Sleep -Seconds 1
adb start-server | Out-Null
adb reverse tcp:8081 tcp:8081
Write-Host "ADB is ready." -ForegroundColor Green
Write-Host ""

# 2. Start Metro bundler in a new window
Write-Host "Starting Metro bundler in a new terminal window..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$demoAppPath'; npx react-native start"
Write-Host "Waiting for Metro to initialize (15 seconds)..."
Start-Sleep -Seconds 15
Write-Host ""

# 3. Build and run the app on the emulator
Write-Host "Building and launching the app on the emulator..." -ForegroundColor Yellow
Write-Host "(This may take a few minutes)"
cd $demoAppPath
npx react-native run-android

Write-Host "App should be running on your emulator." -ForegroundColor Green
