"""
Automatic update checker and self-updating engine for LibreLunar.
Supports checking GitHub releases and performing atomic self-updates on Windows.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from PySide6.QtCore import QObject, QThread, Signal

from .metadata import ssl_context
from .utils import get_commit_hash, parse_version_key

GITHUB_REPO = "miteigidesu/LibreLunar"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def is_frozen() -> bool:
    """Check whether application is running as a compiled/packaged binary."""
    return getattr(sys, "frozen", False) or "__compiled__" in globals() or hasattr(sys, "__compiled__")


def is_portable() -> bool:
    """Check whether application is running in portable mode."""
    if not is_frozen():
        return False
    exe_dir = Path(sys.executable).parent
    return (exe_dir / "portable.txt").exists()


def is_version_newer(latest_tag: str, current_ver: str, release_name: str = "") -> bool:
    """
    Determine if latest GitHub release tag/version is newer than current version.
    Handles calendar versions (e.g. '2026.10.28.1'), semantic versions (e.g. 'v1.2.0'),
    commit hashes (e.g. 'build-e9efe18'), and dev builds.
    """
    if not latest_tag or not current_ver:
        return False

    latest_tag = latest_tag.strip()
    current_ver = current_ver.strip()

    # Exact match check
    if latest_tag.lower() == current_ver.lower():
        return False

    # Strip prefixes like 'v' or 'build-'
    clean_latest = re.sub(r"^(v|build-)", "", latest_tag, flags=re.I).strip()
    clean_current = re.sub(r"^(v|build-)", "", current_ver, flags=re.I).strip()

    if clean_latest.lower() == clean_current.lower():
        return False

    # If running local 'dev' build, don't consider remote newer unless explicitly testing
    if clean_current.lower() == "dev":
        return False

    # If release name explicitly references current commit/version, not newer
    if release_name and clean_current.lower() in release_name.lower():
        return False

    # Check calendar / numeric versions (e.g. '2026.10.28.1', '1.2.0')
    is_num_latest = bool(re.match(r"^\d+(\.\d+)+$", clean_latest))
    is_num_current = bool(re.match(r"^\d+(\.\d+)+$", clean_current))

    if is_num_latest and is_num_current:
        t_latest = parse_version_key(clean_latest)
        t_current = parse_version_key(clean_current)
        return t_latest > t_current

    # If latest is a numbered (calver/semver) release, and current is a git hash,
    # the numbered release is newer
    if is_num_latest and not is_num_current:
        return True

    # If current is numbered release and latest is not numbered, don't downgrade
    if not is_num_latest and is_num_current:
        return False

    # For differing commit-hash builds, consider it an update
    return True


def check_for_updates(
    current_version: str | None = None,
    repo: str = GITHUB_REPO,
    timeout: int = 10,
    github_token: str | None = None,
) -> dict | None:
    """
    Query GitHub API for latest release.
    Returns release info dict if a newer release is found, else None.
    Raises Exception on network or API failures.
    """
    curr = current_version or get_commit_hash()
    api_url = f"https://api.github.com/repos/{repo}/releases"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "LibreLunar-Updater",
    }
    token = github_token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(
                f"HTTP 404: Không tìm thấy bản phát hành nào trên {repo}. "
                "(Nếu repository ở chế độ riêng tư, hãy chuyển sang công khai hoặc đặt biến môi trường GITHUB_TOKEN)"
            )
        raise RuntimeError(f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Lỗi kết nối máy chủ cập nhật: {e.reason}")
    except Exception as e:
        raise RuntimeError(f"Lỗi khi kiểm tra cập nhật: {e}")

    # GitHub /releases returns a list of release objects, newest first.
    # If a dict is returned (e.g. /releases/latest mock), wrap in list.
    if isinstance(data, dict):
        releases = [data]
    elif isinstance(data, list):
        releases = data
    else:
        return None

    if not releases:
        return None

    # Pick the latest non-draft release
    selected_release = None
    for r in releases:
        if not r.get("draft", False):
            selected_release = r
            break

    if not selected_release:
        return None

    tag_name = selected_release.get("tag_name", "")
    release_name = selected_release.get("name", tag_name)
    body = selected_release.get("body", "")
    published_at = selected_release.get("published_at", "")
    html_url = selected_release.get("html_url", f"https://github.com/{repo}/releases")

    if not is_version_newer(tag_name, curr, release_name):
        return None

    # Discover release asset (prefer .zip)
    assets = selected_release.get("assets", [])
    selected_asset = None

    for a in assets:
        name = a.get("name", "").lower()
        if name.endswith(".zip"):
            selected_asset = a
            break

    # Fallback to any asset if no zip found
    if not selected_asset and assets:
        selected_asset = assets[0]

    asset_url = selected_asset.get("browser_download_url") if selected_asset else None
    asset_name = selected_asset.get("name", "") if selected_asset else ""
    asset_size = selected_asset.get("size", 0) if selected_asset else 0
    is_zip = asset_name.lower().endswith(".zip")

    return {
        "tag_name": tag_name,
        "name": release_name,
        "body": body,
        "published_at": published_at,
        "html_url": html_url,
        "asset_url": asset_url,
        "asset_name": asset_name,
        "asset_size": asset_size,
        "is_zip": is_zip,
        "current_version": curr,
    }


class UpdateCheckWorker(QThread):
    sig_update_available = Signal(dict)
    sig_no_update = Signal(str)
    sig_error = Signal(str)

    def __init__(self, current_version: str | None = None, repo: str = GITHUB_REPO, parent: QObject | None = None):
        super().__init__(parent)
        self.current_version = current_version or get_commit_hash()
        self.repo = repo

    def run(self):
        try:
            update_info = check_for_updates(current_version=self.current_version, repo=self.repo)
            if update_info:
                self.sig_update_available.emit(update_info)
            else:
                self.sig_no_update.emit(self.current_version)
        except Exception as e:
            self.sig_error.emit(str(e))


class UpdateDownloadWorker(QThread):
    sig_progress = Signal(int, int)        # downloaded, total
    sig_finished = Signal(bool, str, Path) # success, error, dest_path

    def __init__(self, url: str, dest: Path, size: int = 0, parent: QObject | None = None):
        super().__init__(parent)
        self.url = url
        self.dest = dest
        self.size = size

    def run(self):
        try:
            self.dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.dest.with_name(self.dest.name + ".downloading")
            headers = {"User-Agent": "LibreLunar-Updater"}
            token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if token:
                headers["Authorization"] = f"Bearer {token}"
                headers["Accept"] = "application/octet-stream"
            req = urllib.request.Request(self.url, headers=headers)
            with urllib.request.urlopen(req, timeout=60, context=ssl_context()) as r, open(tmp, "wb") as f:
                downloaded = 0
                total = self.size or int(r.headers.get("Content-Length", 0))
                while True:
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    self.sig_progress.emit(downloaded, total)

            if tmp.exists():
                if self.dest.exists():
                    self.dest.unlink()
                os.replace(tmp, self.dest)
            self.sig_finished.emit(True, "", self.dest)
        except Exception as e:
            self.sig_finished.emit(False, str(e), self.dest)


def apply_update(downloaded_file: Path, is_zip: bool = True) -> None:
    """
    Launch detached Windows PowerShell script to replace running binary and restart application.
    Terminates current process.
    """
    pid = os.getpid()
    current_exe = Path(sys.executable).resolve()
    target_dir = current_exe.parent

    # Create temporary updater PowerShell script
    ps_fd, ps_path_str = tempfile.mkstemp(suffix="_updater.ps1", prefix="librelunar_")
    os.close(ps_fd)
    ps_path = Path(ps_path_str)

    ps_content = """param([int]$pidToWait, [string]$targetDir, [string]$sourcePath, [string]$isZipStr)

try {
    $proc = Get-Process -Id $pidToWait -ErrorAction SilentlyContinue
    if ($proc) {
        $proc.WaitForExit(15000)
    }
} catch {}

Start-Sleep -Seconds 1

if ($isZipStr -eq 'True') {
    $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    Expand-Archive -LiteralPath $sourcePath -DestinationPath $tempDir -Force
    Remove-Item -LiteralPath $sourcePath -Force -ErrorAction SilentlyContinue

    # Check if archive has a nested LibreLunar or root directory
    $innerDir = Join-Path $tempDir 'LibreLunar'
    if (-not (Test-Path $innerDir)) {
        $found = Get-ChildItem -Path $tempDir -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'LibreLunar.exe') } | Select-Object -First 1
        if ($found) { $innerDir = $found.FullName } else { $innerDir = $tempDir }
    }

    # Copy files and _internal directory directly into targetDir
    Copy-Item -Path "$innerDir\\*" -Destination $targetDir -Recurse -Force
    Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue

    $exePath = Join-Path $targetDir 'LibreLunar.exe'
    if (Test-Path $exePath) {
        Start-Process -FilePath $exePath
    }
} else {
    Move-Item -LiteralPath $sourcePath -Destination (Join-Path $targetDir 'LibreLunar.exe') -Force
    Start-Process -FilePath (Join-Path $targetDir 'LibreLunar.exe')
}

Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
"""
    ps_path.write_text(ps_content, encoding="utf-8")

    # Launch detached PowerShell process that outlives current Python process
    creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    if sys.platform == "win32":
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-WindowStyle", "Hidden",
            "-ExecutionPolicy", "Bypass",
            "-File", str(ps_path),
            str(pid),
            str(target_dir),
            str(downloaded_file.resolve()),
            "True" if is_zip else "False",
        ],
        creationflags=creationflags,
        close_fds=True,
    )
