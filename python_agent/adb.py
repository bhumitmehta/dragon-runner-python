from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Optional


def _run_cmd(args: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def adb_available() -> bool:
    try:
        cp = _run_cmd(["adb", "version"], timeout=10.0)
        return cp.returncode == 0
    except Exception:
        return False


def adb_connected_devices() -> list[str]:
    cp = _run_cmd(["adb", "devices"], timeout=10.0)
    if cp.returncode != 0:
        return []

    devices: list[str] = []
    for line in cp.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def wait_for_adb_device(target: Optional[str], timeout_seconds: float, poll_seconds: float = 2.0) -> list[str]:
    deadline = time.time() + max(0.0, timeout_seconds)
    while True:
        devices = adb_connected_devices()
        if target:
            if target in devices:
                return devices
        else:
            if devices:
                return devices

        if time.time() >= deadline:
            return devices
        time.sleep(max(0.2, poll_seconds))


def _sdk_root_candidates() -> list[Path]:
    candidates: list[Path] = []
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(key)
        if value:
            candidates.append(Path(value))

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Android" / "Sdk")

    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        candidates.append(Path(user_profile) / "AppData" / "Local" / "Android" / "Sdk")

    seen: set[str] = set()
    out: list[Path] = []
    for c in candidates:
        key = str(c).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def find_emulator_exe() -> Optional[Path]:
    try:
        cp = _run_cmd(["where", "emulator"], timeout=5.0)
        if cp.returncode == 0:
            first = cp.stdout.splitlines()[0].strip()
            if first:
                p = Path(first)
                if p.exists():
                    return p
    except Exception:
        pass

    for sdk_root in _sdk_root_candidates():
        p = sdk_root / "emulator" / "emulator.exe"
        if p.exists():
            return p
    return None


def list_avds(emulator_exe: Path) -> list[str]:
    cp = _run_cmd([str(emulator_exe), "-list-avds"], timeout=10.0)
    if cp.returncode != 0:
        return []
    return [line.strip() for line in cp.stdout.splitlines() if line.strip()]


def start_emulator(
    avd: str,
    target_device: Optional[str] = None,
    emulator_exe: Optional[Path] = None,
    timeout_seconds: float = 180.0,
) -> bool:
    exe = emulator_exe or find_emulator_exe()
    if not exe:
        raise RuntimeError("Could not find emulator.exe")

    devices = adb_connected_devices()
    if target_device:
        if target_device in devices:
            print(f"ADB device already connected: {target_device}")
            return True
    else:
        if devices:
            print(f"ADB devices already connected: {devices}")
            return True

    print(f"Starting emulator AVD: {avd}...")
    subprocess.Popen([str(exe), "-avd", avd])

    try:
        wait_for_adb_device(target=target_device, timeout_seconds=timeout_seconds)
        return True
    except Exception as e:
        print(f"Emulator {avd} did not start in time: {e}")
        return False

