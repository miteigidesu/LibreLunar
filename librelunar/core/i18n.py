"""
Localization (i18n) support for LibreLunar.
Loads translation strings from JSON files in the i18n directory (e.g. en_us.json, vi_vn.json).
"""
import json
import os
import sys
from pathlib import Path
from PySide6.QtCore import QLocale, QObject, Signal

DEFAULT_LANGUAGE = "en_us"

DEFAULT_LANGUAGE_NAMES: dict[str, str] = {
    "en_us": "English",
    "vi_vn": "Tiếng Việt",
}

ALIASES: dict[str, str] = {
    "en": "en_us",
    "vi": "vi_vn",
}


def normalize_lang_code(code: str) -> str:
    """Normalize language codes like 'en', 'vi', 'en-US' into canonical 'en_us', 'vi_vn'."""
    cleaned = str(code).lower().replace("-", "_").strip()
    return ALIASES.get(cleaned, cleaned)


def get_i18n_dirs() -> list[Path]:
    """Find directories where i18n JSON files are stored."""
    candidates = []

    # 1. PyInstaller MEIPASS
    if hasattr(sys, "_MEIPASS"):
        for sub in ("librelunar/i18n", "i18n"):
            p = Path(sys._MEIPASS) / sub
            if p.is_dir() and p not in candidates:
                candidates.append(p)

    # 2. Inside package: librelunar/i18n
    pkg_i18n = Path(__file__).resolve().parent.parent / "i18n"
    if pkg_i18n.is_dir() and pkg_i18n not in candidates:
        candidates.append(pkg_i18n)

    # 3. Project root: ./i18n
    root_i18n = Path(__file__).resolve().parent.parent.parent / "i18n"
    if root_i18n.is_dir() and root_i18n not in candidates:
        candidates.append(root_i18n)

    # 4. Next to sys.executable (_internal or direct distribution)
    exe_dir = Path(sys.executable).resolve().parent
    for sub in ("_internal/librelunar/i18n", "_internal/i18n", "librelunar/i18n", "i18n"):
        p = exe_dir / sub
        if p.is_dir() and p not in candidates:
            candidates.append(p)

    return candidates


class I18nManager(QObject):
    language_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._current_language = DEFAULT_LANGUAGE
        self._translations: dict[str, dict[str, str]] = {}
        self._language_names: dict[str, str] = {}
        self.load_translations()

    def load_translations(self):
        """Scan i18n directories and load all .json translation files."""
        self._translations.clear()
        self._language_names.clear()

        for d in get_i18n_dirs():
            for json_file in sorted(d.glob("*.json")):
                lang_code = normalize_lang_code(json_file.stem)
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        lang_name = data.get("__language_name__") or DEFAULT_LANGUAGE_NAMES.get(lang_code, lang_code)
                        if lang_code not in self._translations:
                            self._translations[lang_code] = {}
                            self._language_names[lang_code] = lang_name

                        # Filter out internal metadata keys
                        filtered = {k: v for k, v in data.items() if not k.startswith("__")}
                        self._translations[lang_code].update(filtered)
                except Exception:
                    pass

    @property
    def current_language(self) -> str:
        return self._current_language

    def get_supported_languages(self) -> dict[str, str]:
        """Return dict of {lang_code: display_name}."""
        if not self._language_names:
            return dict(DEFAULT_LANGUAGE_NAMES)
        return dict(self._language_names)

    def set_language(self, lang: str):
        normalized = normalize_lang_code(lang)
        supported = self.get_supported_languages()
        if normalized not in supported:
            normalized = DEFAULT_LANGUAGE

        if self._current_language != normalized:
            self._current_language = normalized
            self.language_changed.emit(normalized)

    def t(self, key: str, **kwargs) -> str:
        lang_dict = self._translations.get(self._current_language, {})
        text = lang_dict.get(key)
        if text is None:
            # Fallback to English (en_us)
            fallback_dict = self._translations.get(DEFAULT_LANGUAGE, {})
            text = fallback_dict.get(key, key)

        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    def detect_system_language(self) -> str:
        """Detect system language or fallback to default."""
        try:
            env_lang = os.environ.get("LIBRELUNAR_LANG")
            if env_lang:
                normalized = normalize_lang_code(env_lang)
                if normalized in self.get_supported_languages():
                    return normalized

            name = QLocale.system().name().lower()
            if name.startswith("vi"):
                return "vi_vn"
        except Exception:
            pass
        return DEFAULT_LANGUAGE


_manager = I18nManager()


def get_i18n() -> I18nManager:
    return _manager


def t(key: str, **kwargs) -> str:
    return _manager.t(key, **kwargs)


def tr(key: str, **kwargs) -> str:
    return _manager.t(key, **kwargs)


def set_language(lang: str):
    _manager.set_language(lang)


def get_language() -> str:
    return _manager.current_language


def get_supported_languages() -> dict[str, str]:
    return _manager.get_supported_languages()


def detect_system_language() -> str:
    return _manager.detect_system_language()
