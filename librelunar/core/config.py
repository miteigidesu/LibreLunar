"""
Configuration manager for LibreLunar.
Handles persistence of settings, selected versions, custom data directories,
and backward-compatible schema adaptation/migration across updates.
"""
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .i18n import (
    DEFAULT_LANGUAGE,
    detect_system_language,
    get_supported_languages,
    normalize_lang_code,
)
from .paths import get_config_file_path, get_default_data_dir
from .utils import get_default_resolution

CONFIG_VERSION = 1

# Known legacy/alias keys mapped to current canonical field names
KEY_ALIASES: dict[str, str] = {
    "offline_name": "username",
    "player_name": "username",
    "player": "username",
    "ram": "memory",
    "ram_mb": "memory",
    "lang": "language",
    "locale": "language",
    "auto_update": "check_updates",
    "update_check": "check_updates",
    "update_checker": "check_updates",
    "res_width": "width",
    "res_height": "height",
    "keepopen": "keep_open",
}


def _safe_int(val: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    try:
        n = int(val)
        if min_val is not None:
            n = max(min_val, n)
        if max_val is not None:
            n = min(max_val, n)
        return n
    except (ValueError, TypeError):
        return default


def _safe_bool(val: Any, default: bool) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("true", "1", "yes", "y", "on"):
            return True
        if v in ("false", "0", "no", "n", "off"):
            return False
    return default


def _safe_str(val: Any, default: str) -> str:
    if val is None:
        return default
    s = str(val).strip()
    return s if s else default


@dataclass
class LauncherConfig:
    data_dir: str = ""
    first_run_completed: bool = False
    language: str = DEFAULT_LANGUAGE
    check_updates: bool = True
    version: str = ""
    module: str = ""
    username: str = "Player"
    uuid: str = ""
    xuid: str = "0000000000000000"
    memory: int = 3072  # 3 GB RAM default
    width: int = 1280
    height: int = 720
    fullscreen: bool = False
    verbose: bool = False
    keep_open: bool = False
    config_version: int = CONFIG_VERSION
    extra_fields: dict[str, Any] = field(default_factory=dict)

    @property
    def resolved_data_dir(self) -> Path:
        """Return Path object for the configured data directory or default AppData."""
        if self.data_dir and isinstance(self.data_dir, str):
            return Path(self.data_dir).expanduser().resolve()
        return get_default_data_dir()

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dict, merging extra fields so unknown/future options are preserved."""
        data = asdict(self)
        extra = data.pop("extra_fields", {})
        # Known fields overwrite any stale extra fields with same key
        return {**extra, **data}

    @classmethod
    def load(cls) -> "LauncherConfig":
        """Load and adapt configuration from disk."""
        default_w, default_h = get_default_resolution()
        default_lang = detect_system_language()
        config = cls(width=default_w, height=default_h, language=default_lang)

        cfg_file = get_config_file_path()
        if not cfg_file.is_file():
            return config

        try:
            raw_text = cfg_file.read_text(encoding="utf-8")
            raw_data = json.loads(raw_text)
            if not isinstance(raw_data, dict):
                return config

            adapted, needs_resave = cls.adapt_and_migrate(raw_data, default_w, default_h, default_lang)
            config = cls(**adapted)
            if needs_resave:
                config.save()
        except Exception:
            pass

        return config

    @classmethod
    def from_dict(cls, raw_data: dict[str, Any]) -> "LauncherConfig":
        """Construct and adapt a LauncherConfig instance from an arbitrary dictionary."""
        default_w, default_h = get_default_resolution()
        default_lang = detect_system_language()
        adapted, _ = cls.adapt_and_migrate(raw_data, default_w, default_h, default_lang)
        return cls(**adapted)

    @classmethod
    def adapt_and_migrate(
        cls,
        raw_data: dict[str, Any],
        default_w: int,
        default_h: int,
        default_lang: str,
    ) -> tuple[dict[str, Any], bool]:
        """
        Adapt old, changed, or legacy configuration data to current schema.
        Returns (adapted_kwargs_dict, needs_resave).
        """
        data = dict(raw_data)
        needs_resave = False

        # 1. Map legacy aliases to canonical keys
        for alias_key, canonical_key in KEY_ALIASES.items():
            if alias_key in data:
                if canonical_key not in data or not data[canonical_key]:
                    data[canonical_key] = data[alias_key]
                del data[alias_key]
                needs_resave = True

        # 2. Extract and validate known fields
        known_keys = {
            "data_dir",
            "first_run_completed",
            "language",
            "check_updates",
            "version",
            "module",
            "username",
            "uuid",
            "xuid",
            "memory",
            "width",
            "height",
            "fullscreen",
            "verbose",
            "keep_open",
            "config_version",
        }

        # Any key not recognized is stored in extra_fields to prevent data loss across updates
        extra_fields = {k: v for k, v in data.items() if k not in known_keys}

        data_dir = str(data.get("data_dir", ""))
        first_run_completed = _safe_bool(data.get("first_run_completed"), False)

        raw_lang = data.get("language")
        supported = get_supported_languages()
        if raw_lang:
            norm = normalize_lang_code(raw_lang)
            if norm in supported:
                language = norm
                if str(raw_lang) != norm:
                    needs_resave = True
            else:
                language = default_lang if default_lang in supported else DEFAULT_LANGUAGE
                needs_resave = True
        else:
            language = default_lang if default_lang in supported else DEFAULT_LANGUAGE

        check_updates = _safe_bool(data.get("check_updates"), True)
        if "check_updates" not in data:
            needs_resave = True

        version = str(data.get("version", ""))
        module = str(data.get("module", ""))
        username = _safe_str(data.get("username"), "Player")
        uuid_str = str(data.get("uuid", ""))
        xuid_str = str(data.get("xuid", "0000000000000000"))

        memory = _safe_int(data.get("memory"), 3072, min_val=512, max_val=131072)
        width = _safe_int(data.get("width"), default_w, min_val=640, max_val=7680)
        height = _safe_int(data.get("height"), default_h, min_val=360, max_val=4320)

        fullscreen = _safe_bool(data.get("fullscreen"), False)
        verbose = _safe_bool(data.get("verbose"), False)
        keep_open = _safe_bool(data.get("keep_open"), False)
        cfg_version = _safe_int(data.get("config_version"), CONFIG_VERSION)

        adapted: dict[str, Any] = {
            "data_dir": data_dir,
            "first_run_completed": first_run_completed,
            "language": language,
            "check_updates": check_updates,
            "version": version,
            "module": module,
            "username": username,
            "uuid": uuid_str,
            "xuid": xuid_str,
            "memory": memory,
            "width": width,
            "height": height,
            "fullscreen": fullscreen,
            "verbose": verbose,
            "keep_open": keep_open,
            "config_version": cfg_version,
            "extra_fields": extra_fields,
        }

        return adapted, needs_resave

    def save(self):
        """Save current configuration to the config JSON file."""
        cfg_file = get_config_file_path()
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(self.to_dict(), indent=2)
        cfg_file.write_text(content, encoding="utf-8")

        # Also store copy inside data_dir if it's custom and exists
        target_dir = self.resolved_data_dir
        if target_dir.is_dir() and target_dir != cfg_file.parent:
            try:
                (target_dir / "config.json").write_text(content, encoding="utf-8")
            except OSError:
                pass
