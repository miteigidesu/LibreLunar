"""
Path configuration and directory management for LibreLunar.
Handles AppData storage, custom directories, and profile isolation.
"""
import os
import json
from pathlib import Path
from .utils import safe_name

CURRENT_FILE = Path(__file__).resolve()
APP_ROOT = CURRENT_FILE.parent.parent.parent


def get_default_data_dir() -> Path:
    """Return canonical system AppData location for LibreLunar."""
    override = os.environ.get("LIBRELUNAR_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "LibreLunar"
    return Path.home() / ".config" / "LibreLunar"


def get_app_config_dir() -> Path:
    """Return the base config directory where the launcher config is stored."""
    override = os.environ.get("LIBRELUNAR_CONFIG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    # If portable marker or config exists in local application root, use local directory
    if (APP_ROOT / "portable.txt").exists() or (APP_ROOT / "config.json").exists():
        return APP_ROOT
    return get_default_data_dir()


def get_config_file_path() -> Path:
    """Return path to the configuration JSON file."""
    return get_app_config_dir() / "config.json"


def get_data_dir() -> Path:
    """
    Resolve the active LibreLunar data directory.
    Checks the configuration file for custom paths; falls back to AppData.
    """
    cfg_file = get_config_file_path()
    if cfg_file.is_file():
        try:
            data = json.loads(cfg_file.read_text("utf-8"))
            custom = data.get("data_dir")
            if custom and isinstance(custom, str):
                p = Path(custom).expanduser().resolve()
                return p
        except Exception:
            pass
    return get_default_data_dir()


def is_first_run() -> bool:
    """Determine whether the first-time setup wizard should be displayed."""
    cfg_file = get_config_file_path()
    if not cfg_file.is_file():
        return True
    try:
        data = json.loads(cfg_file.read_text("utf-8"))
        return not bool(data.get("first_run_completed", False))
    except Exception:
        return True


def init_data_structure(data_dir: Path):
    """Ensure standard LibreLunar directory hierarchy exists."""
    for d in (
        data_dir,
        data_dir / "metadata",
        data_dir / "manifests",
        data_dir / "libraries",
        data_dir / "assets",
        data_dir / "artifacts",
        data_dir / "artifacts" / "views",
        data_dir / "artifacts" / "views" / "cache",
        data_dir / "artifacts" / "cache",
        data_dir / "artifacts" / "jre",
        data_dir / "home",
        data_dir / "home" / ".lunarclient",
        data_dir / "profiles",
    ):
        d.mkdir(parents=True, exist_ok=True)


class ProfilePaths:
    """Paths specific to a chosen Minecraft version and flavor profile."""
    def __init__(self, version: str, module: str, data_dir: Path | None = None):
        self.data_dir = data_dir or get_data_dir()
        self.version = version
        self.module = module
        self.profile_name = f"{safe_name(version)}-{safe_name(module)}"

        # Per-profile isolated game and mod storage
        self.profile_data = self.data_dir / "profiles" / self.profile_name
        self.mc_data = self.profile_data / "minecraft"
        self.mods_dir = self.profile_data / "mods"
        self.logs_dir = self.profile_data / "logs"
        self.natives = self.profile_data / "natives"

        # Shared data directories
        self.artifact_view = self.data_dir / "artifacts" / "views"
        self.libraries = self.data_dir / "libraries"
        self.assets = self.data_dir / "assets"
        self.home = self.data_dir / "home"
        self.lc_home = self.home / ".lunarclient"

    def ensure_directories(self):
        """Create necessary directories for this profile."""
        init_data_structure(self.data_dir)
        for d in (
            self.profile_data,
            self.mc_data,
            self.natives,
            self.mods_dir,
            self.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


def account_file_path(data_dir: Path | None = None) -> Path:
    base = data_dir or get_data_dir()
    return base / "home" / ".lunarclient" / "settings" / "game" / "accounts.json"

