from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional
import shutil
from urllib.parse import urlparse
from urllib.error import URLError
from urllib.request import Request, urlopen


def _url_ok(url: str, timeout_seconds: float = 2.0) -> bool:
    try:
        req = Request(url, headers={"User-Agent": "python-agent"})
        with urlopen(req, timeout=timeout_seconds) as resp:
            return 200 <= getattr(resp, "status", 200) < 500
    except URLError:
        return False
    except Exception:
        return False


def is_appium_responding(server_url: str) -> bool:
    base = server_url.rstrip("/")
    return _url_ok(f"{base}/status")


def _resolve_appium_cmd() -> list[str]:
    # Prefer a globally-installed `appium` if present.
    appium = shutil.which("appium") or shutil.which("appium.cmd")
    if appium:
        return [appium]

    # Fall back to `npx --yes appium` (works without global install).
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx:
        return [npx, "--yes", "appium"]

    # Last resort: hope CreateProcess can resolve it.
    return ["npx", "--yes", "appium"]


def _pick_working_dir_for_cmd(cmd: list[str], repo_root: Path) -> Path:
    """Prefer running `npx appium` from the attached WDIO folder so it uses its pinned dependency."""

    if not cmd:
        return repo_root

    exe = Path(cmd[0]).name.lower()
    is_npx = exe in {"npx", "npx.cmd", "npx.exe"}
    if not is_npx:
        return repo_root

    wdio_root = repo_root / "appium-wdio-react-native-ios-android"
    if (wdio_root / "package.json").exists() and (wdio_root / "node_modules").exists():
        return wdio_root

    return repo_root


def _server_args_from_url(server_url: str) -> list[str]:
    parsed = urlparse(server_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 4723
    base_path = parsed.path.rstrip("/")
    args: list[str] = ["--address", host, "-p", str(port), "--log-level", "info"]
    if base_path == "/wd/hub":
        args += ["--base-path", "/wd/hub"]
    return args


def start_appium_server(server_url: str, repo_root: Path, log_file: Optional[Path] = None) -> Optional[subprocess.Popen]:
    """Start Appium if needed; return the spawned process or None if already running."""

    if is_appium_responding(server_url):
        print("Appium server already running.")
        return None

    cmd = _resolve_appium_cmd()
    extra_args = _server_args_from_url(server_url)

    stdout = subprocess.DEVNULL
    stderr = subprocess.DEVNULL
    file_handle = None
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handle = open(log_file, "a", encoding="utf-8")
        stdout = file_handle
        stderr = file_handle

    creationflags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    working_dir = _pick_working_dir_for_cmd(cmd, repo_root)
    print(f"Starting Appium server: {' '.join(cmd + extra_args)}")
    proc = subprocess.Popen(
        cmd + extra_args,
        cwd=str(working_dir),
        stdout=stdout,
        stderr=stderr,
        creationflags=creationflags,
    )

    deadline = time.time() + 45.0
    while time.time() < deadline:
        if is_appium_responding(server_url):
            print("Appium server is responding.")
            return proc
        time.sleep(1)

    stop_appium_server(proc)
    if file_handle:
        try:
            file_handle.close()
        except Exception:
            pass
    raise RuntimeError("Appium server did not become ready in time")


def stop_appium_server(proc: Optional[subprocess.Popen]) -> None:
    if not proc:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


