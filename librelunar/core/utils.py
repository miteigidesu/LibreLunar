"""
Utility functions for LibreLunar.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtGui import QGuiApplication


def get_commit_hash() -> str:
    """
    Resolve version string from:
    1. LIBRELUNAR_VERSION environment variable
    2. Baked _version.py if generated during build
    3. Git CLI or .git directory
    4. Fallback to 'dev'
    """
    env_ver = os.environ.get("LIBRELUNAR_VERSION")
    if env_ver:
        return env_ver.strip()

    try:
        from .._version import __version__
        if __version__:
            return __version__.strip()
    except Exception:
        pass

    # Never spawn external git in compiled/frozen binary
    if getattr(sys, "frozen", False) or "__compiled__" in globals() or hasattr(sys, "__compiled__"):
        return "dev"

    # Try git executable
    git_cmd = shutil.which("git")
    if git_cmd:
        try:
            repo_dir = Path(__file__).resolve().parent.parent.parent
            creationflags = 0x08000000 if sys.platform == "win32" else 0
            out = subprocess.check_output(
                [git_cmd, "rev-parse", "--short", "HEAD"],
                cwd=str(repo_dir),
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=creationflags,
            ).strip()
            if out:
                return out
        except Exception:
            pass

    # Try inspecting .git directly if git executable is missing
    try:
        cur = Path(__file__).resolve().parent
        for _ in range(4):
            git_dir = cur / ".git"
            if git_dir.is_dir():
                head_file = git_dir / "HEAD"
                if head_file.is_file():
                    content = head_file.read_text(encoding="utf-8").strip()
                    if content.startswith("ref: "):
                        ref_path = git_dir / content[5:].strip()
                        if ref_path.is_file():
                            return ref_path.read_text(encoding="utf-8").strip()[:7]
                    elif len(content) >= 7:
                        return content[:7]
            cur = cur.parent
    except Exception:
        pass

    return "dev"


def get_app_title() -> str:
    """Return standard window title: LibreLunar v{version}."""
    ver = get_commit_hash()
    if ver.startswith("v"):
        return f"LibreLunar {ver}"
    return f"LibreLunar v{ver}"


def get_default_resolution() -> tuple[int, int]:
    """
    Returns default resolution:
    1280 x 720 on 1080p or higher screens, else 854 x 480 (default Minecraft size).
    """
    try:
        primary = QGuiApplication.primaryScreen()
        if primary:
            geom = primary.geometry()
            if geom.height() >= 1080 or geom.width() >= 1920:
                return 1280, 720
    except Exception:
        pass
    return 854, 480


def offline_uuid(name: str) -> str:
    """Generate offline Minecraft UUID from player name."""
    h = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(h)))


def fake_timestamp() -> str:
    """Return future expiry timestamp for offline accounts."""
    return (
        (datetime.now(timezone.utc) + timedelta(hours=12))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def parse_version_key(v_str: str) -> tuple:
    """
    Parse a version string (e.g. '1.21.11', '1.8.9', '26', '26.3') into a comparable tuple.
    Orders versions by actual version hierarchy:
      1.21.11 > 1.21.10 > 1.21.9 > 1.21.1 > 1.21
      26 > 1.21 > 1.20 > 1.19 > ... > 1.8 > 1.7
    """
    parts = str(v_str).strip().split(".")
    parsed = []
    for part in parts:
        m = re.match(r"^(\d+)(.*)$", part)
        if m:
            num = int(m.group(1))
            suffix = m.group(2)
            parsed.append((num, suffix))
        else:
            parsed.append((0, part))
    while len(parsed) < 3:
        parsed.append((0, ""))
    return tuple(parsed)


def safe_name(value: str) -> str:
    """Sanitize strings for filesystem safety."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip(".") or "unknown"


def safe_rel(p: str | Path) -> Path:
    """Ensure path is relative and does not escape."""
    rel = Path(str(p).replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"Unsafe path: {p}")
    return rel


def sha1_of(path: str | Path) -> str:
    """Calculate SHA1 hash of a file."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of(path: str | Path) -> str:
    """Calculate SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_file_hash(path: str | Path, expected: str | None) -> bool:
    """
    Verify file against expected hash.
    Automatically detects SHA-256 (64 hex characters) vs SHA-1 (40 hex characters).
    Returns True if hash matches or if expected is None/empty.
    """
    if not expected:
        return True
    exp = expected.strip().lower()
    if len(exp) == 64:
        return sha256_of(path).lower() == exp
    return sha1_of(path).lower() == exp


def is_java_running() -> bool:
    """Check if any java.exe or javaw.exe process is currently active."""
    try:
        import ctypes
        import ctypes.wintypes

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.wintypes.DWORD),
                ("cntUsage", ctypes.wintypes.DWORD),
                ("th32ProcessID", ctypes.wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", ctypes.wintypes.DWORD),
                ("cntThreads", ctypes.wintypes.DWORD),
                ("th32ParentProcessID", ctypes.wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        h = ctypes.windll.kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if h == -1:
            return True
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        found = False
        if ctypes.windll.kernel32.Process32First(h, ctypes.byref(pe)):
            while True:
                name = pe.szExeFile.lower()
                if b"java.exe" in name or b"javaw.exe" in name:
                    found = True
                    break
                if not ctypes.windll.kernel32.Process32Next(h, ctypes.byref(pe)):
                    break
        ctypes.windll.kernel32.CloseHandle(h)
        return found
    except Exception:
        return True

