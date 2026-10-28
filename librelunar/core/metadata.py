"""
Metadata fetching and caching for Lunar Client versions and modules.
"""
import importlib
import json
import platform
import ssl
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

from .constants import (
    LAUNCHER_VERSION,
    LUNAR_UA,
    VERSION_METADATA_API,
    ZERO_HEX32,
    ZERO_UUID,
)
from .paths import get_data_dir

try:
    certifi = importlib.import_module("certifi")
except ImportError:
    certifi = None


def ssl_context():
    if certifi:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def metadata_query(branch: str = "master") -> str:
    return urlencode({
        "installation_id": ZERO_UUID,
        "overwolf_muid": ZERO_UUID,
        "os": "win32",
        "os_release": platform.version(),
        "arch": "x64",
        "launcher_version": LAUNCHER_VERSION,
        "branch": branch,
    })


def get_metadata_cache_file(data_dir: Path | None = None) -> Path:
    base = data_dir or get_data_dir()
    return base / "metadata" / "versions.json"


def fetch_version_metadata(offline: bool = False, branch: str = "master", data_dir: Path | None = None) -> dict:
    """
    Fetch version metadata from the Lunar API, or use local cache if offline
    or if network fails.
    """
    cache_path = get_metadata_cache_file(data_dir)

    if offline:
        if cache_path.exists():
            return json.loads(cache_path.read_text("utf-8"))
        raise RuntimeError("No cached version metadata available. Run online at least once.")

    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": LUNAR_UA,
        "sentry-trace": ZERO_HEX32,
        "X-Installation-Id": ZERO_UUID,
        "X-Overwolf-Muid": ZERO_UUID,
    }
    url = f"{VERSION_METADATA_API}?{metadata_query(branch)}"
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as response:
            metadata = json.loads(response.read().decode("utf-8"))
        if metadata.get("versions"):
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(metadata, indent=2), "utf-8")
            return metadata
    except Exception as e:
        if cache_path.exists():
            return json.loads(cache_path.read_text("utf-8"))
        raise RuntimeError(f"Failed to fetch version metadata: {e}")

    if cache_path.exists():
        return json.loads(cache_path.read_text("utf-8"))
    raise RuntimeError("Lunar metadata returned invalid format.")


def find_major_for_version(metadata: dict, version_id: str) -> dict | None:
    """Find the major version entry that matches or contains the given version_id."""
    versions = metadata.get("versions", [])
    for major in versions:
        if major.get("id") == version_id:
            return major
        for sub in major.get("subversions", []):
            if sub.get("id") == version_id:
                return major
    return None

