"""
Main application bootstrap for LibreLunar.
"""
import sys
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .core.config import LauncherConfig
from .core.constants import APP_NAME
from .core.i18n import set_language
from .core.utils import get_app_title
from .ui.main_window import MainWindow
from .ui.styles import LAUNCHER_STYLE


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 9))
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(get_app_title())
    app.setStyleSheet(LAUNCHER_STYLE)

    config = LauncherConfig.load()
    set_language(config.language)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

