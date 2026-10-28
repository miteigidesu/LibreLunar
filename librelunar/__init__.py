"""
LibreLunar - A clean, minimal, open-source Lunar Client portable launcher.
"""

__all__ = ["__version__"]

try:
    from .core.utils import get_commit_hash
    __version__ = get_commit_hash()
except Exception:
    __version__ = "Dev"

