$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$wdioRoot = Join-Path $repoRoot 'appium-wdio-react-native-ios-android'

if (-not (Test-Path $wdioRoot)) {
  throw "Expected folder not found: $wdioRoot"
}

Push-Location $wdioRoot
try {
  # Uses the pinned Appium dependency from appium-wdio-react-native-ios-android/package.json
  npx appium --base-path /wd/hub --address 127.0.0.1 -p 4723 --log-level info
} finally {
  Pop-Location
}
