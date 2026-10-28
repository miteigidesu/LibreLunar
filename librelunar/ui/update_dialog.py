"""
Update progress dialog for LibreLunar.
Displays download progress when applying an update.
"""
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..core.i18n import t
from ..core.updater import UpdateDownloadWorker, apply_update
from .styles import LAUNCHER_STYLE


class UpdateProgressDialog(QDialog):
    def __init__(self, update_info: dict, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.worker: UpdateDownloadWorker | None = None
        self.temp_dest: Path | None = None

        self.setWindowTitle(t("update_dialog_title"))
        self.setStyleSheet(LAUNCHER_STYLE)
        self.setFixedWidth(380)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        icon_path = Path(__file__).resolve().parent.parent / "resources" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._init_ui()
        self._start_download()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        self.lbl_status = QLabel(t("update_downloading"))
        self.lbl_status.setStyleSheet("font-weight: bold; color: #f3f4f6; font-size: 9pt;")
        layout.addWidget(self.lbl_status)

        self.lbl_detail = QLabel(self.update_info.get("asset_name", ""))
        self.lbl_detail.setStyleSheet("color: #9ba1b0; font-size: 8pt;")
        layout.addWidget(self.lbl_detail)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_cancel = QPushButton(t("cancel"))
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.btn_cancel)

        layout.addLayout(btn_row)

    def _start_download(self):
        url = self.update_info.get("asset_url")
        if not url:
            QMessageBox.critical(self, t("update_failed"), t("update_failed_msg", error="Missing download URL"))
            self.reject()
            return

        suffix = ".zip" if self.update_info.get("is_zip") else ".exe"
        fd, path_str = tempfile.mkstemp(suffix=suffix, prefix="librelunar_update_")
        import os
        os.close(fd)
        self.temp_dest = Path(path_str)

        self.worker = UpdateDownloadWorker(
            url=url,
            dest=self.temp_dest,
            size=self.update_info.get("asset_size", 0),
            parent=self,
        )
        self.worker.sig_progress.connect(self._on_progress)
        self.worker.sig_finished.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = int(min(1.0, downloaded / total) * 100)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            mb_down = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self.lbl_detail.setText(f"{mb_down:.1f} MB / {mb_total:.1f} MB ({pct}%)")
        else:
            self.progress_bar.setRange(0, 0)
            mb_down = downloaded / (1024 * 1024)
            self.lbl_detail.setText(f"{mb_down:.1f} MB")

    def _on_finished(self, success: bool, error: str, dest_path: Path):
        if success and dest_path.is_file():
            self.lbl_status.setText(t("update_installing"))
            self.lbl_detail.setText("")
            self.progress_bar.setRange(0, 0)
            self.btn_cancel.setEnabled(False)

            # Apply atomic update and restart
            is_zip = self.update_info.get("is_zip", False)
            apply_update(dest_path, is_zip=is_zip)
            QApplication.quit()
            sys.exit(0)
        else:
            QMessageBox.critical(self, t("update_failed"), t("update_failed_msg", error=error or "Download failed"))
            self.reject()

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
        if self.temp_dest and self.temp_dest.exists():
            try:
                self.temp_dest.unlink()
            except OSError:
                pass
        super().reject()

    def _on_cancel(self):
        self.reject()
