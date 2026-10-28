"""
Main launcher window for LibreLunar.
"""
import os
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.config import LauncherConfig
from ..core.i18n import get_i18n, get_language, set_language, t
from ..core.launch_worker import LaunchWorker
from ..core.metadata import fetch_version_metadata, find_major_for_version
from ..core.paths import is_first_run
from ..core.updater import UpdateCheckWorker, is_frozen
from ..core.utils import get_app_title, parse_version_key
from .options_dialog import OptionsDialog
from .setup_dialog import SetupDialog
from .styles import LAUNCHER_STYLE
from .update_dialog import UpdateProgressDialog


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(LAUNCHER_STYLE)

        icon_path = Path(__file__).resolve().parent.parent / "resources" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.config = LauncherConfig.load()
        set_language(self.config.language)

        if is_first_run() or not self.config.first_run_completed:
            setup = SetupDialog(self)
            if setup.exec() != QDialog.Accepted:
                # If closed without completing, proceed with appdata defaults
                self.config.first_run_completed = True
                self.config.language = get_language()
                self.config.save()
            self.config = LauncherConfig.load()
            set_language(self.config.language)

        self.metadata = {}
        self.worker: LaunchWorker | None = None
        self.update_worker: UpdateCheckWorker | None = None
        self._status_state = "ready"
        self._last_error = ""
        self._stage_info: tuple[int, int, str] | None = None

        self._init_ui()
        get_i18n().language_changed.connect(self._retranslate_ui)
        self._retranslate_ui()
        self._load_metadata_and_populate()
        self._start_update_check()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSizeConstraint(QLayout.SetFixedSize)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(10)

        # 1. Major Version
        self.lbl_major = QLabel()
        main_layout.addWidget(self.lbl_major)

        self.combo_major = QComboBox()
        self.combo_major.currentIndexChanged.connect(self._on_major_changed)
        main_layout.addWidget(self.combo_major)

        # 2. Minor Version
        self.lbl_minor = QLabel()
        main_layout.addWidget(self.lbl_minor)

        self.combo_minor = QComboBox()
        self.combo_minor.currentIndexChanged.connect(self._on_minor_changed)
        main_layout.addWidget(self.combo_minor)

        # 3. Flavor
        self.lbl_flavor = QLabel()
        main_layout.addWidget(self.lbl_flavor)

        self.combo_flavor = QComboBox()
        main_layout.addWidget(self.combo_flavor)

        # 4. Offline Username
        self.lbl_user = QLabel()
        main_layout.addWidget(self.lbl_user)

        self.edit_username = QLineEdit()
        self.edit_username.setText(self.config.username or "Player")
        main_layout.addWidget(self.edit_username)

        main_layout.addSpacing(4)

        # 5. Buttons Row: [Options] [Open data folder] ... [Launch]
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_options = QPushButton()
        self.btn_options.clicked.connect(self._open_options)
        btn_row.addWidget(self.btn_options)

        self.btn_open_folder = QPushButton()
        self.btn_open_folder.clicked.connect(self._open_data_folder)
        btn_row.addWidget(self.btn_open_folder)

        btn_row.addStretch()

        self.btn_launch = QPushButton()
        self.btn_launch.setObjectName("launchButton")
        self.btn_launch.clicked.connect(self._start_launch)
        btn_row.addWidget(self.btn_launch)

        main_layout.addLayout(btn_row)

        main_layout.addSpacing(6)

        # 6. Status Text 1 & 2
        self.lbl_status1 = QLabel()
        self.lbl_status1.setObjectName("statusText1")
        self.lbl_status1.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.lbl_status1)

        self.lbl_status2 = QLabel()
        self.lbl_status2.setObjectName("statusText2")
        self.lbl_status2.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.lbl_status2)

        # 7. Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        main_layout.addWidget(self.progress_bar)

        self.setFixedWidth(440)

    def _retranslate_ui(self):
        """Update all user-visible strings in real time."""
        self.setWindowTitle(get_app_title())
        self.lbl_major.setText(t("main_select_major"))
        self.lbl_minor.setText(t("main_select_minor"))
        self.lbl_flavor.setText(t("main_select_flavor"))
        self.lbl_user.setText(t("main_enter_username"))
        self.edit_username.setPlaceholderText(t("main_username_placeholder"))
        self.btn_options.setText(t("main_options"))
        self.btn_open_folder.setText(t("main_open_folder"))
        self.btn_launch.setText(t("main_launch"))

        if self._status_state == "ready":
            self.lbl_status1.setText(t("main_ready"))
            self.lbl_status2.setText(t("main_select_version_hint"))
        elif self._status_state == "preparing":
            self.lbl_status1.setText(t("main_preparing_launch"))
            self.lbl_status2.setText(t("main_init_env"))
        elif self._status_state == "staging" and self._stage_info:
            cur, tot, tit = self._stage_info
            self.lbl_status1.setText(t("main_stage_format", current=cur, total=tot, title=tit))
        elif self._status_state == "running":
            self.lbl_status1.setText(t("main_game_running"))
            self.lbl_status2.setText(t("main_enjoy_game"))
        elif self._status_state == "failed":
            self.lbl_status1.setText(t("main_launch_failed"))
            self.lbl_status2.setText(self._last_error[:60] if self._last_error else t("main_launch_failed_desc"))

    def _load_metadata_and_populate(self):
        data_dir = self.config.resolved_data_dir
        try:
            self.metadata = fetch_version_metadata(offline=True, data_dir=data_dir)
        except Exception:
            try:
                self.metadata = fetch_version_metadata(data_dir=data_dir)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    t("main_catalog_error_title"),
                    t("main_catalog_error_msg", error=e),
                )
                return

        versions = self.metadata.get("versions", [])
        if not versions:
            return

        # Sort major versions by actual version hierarchy descending (e.g. 26 > 1.21 > 1.20 > ... > 1.7)
        versions = sorted(versions, key=lambda m: parse_version_key(m.get("id", "")), reverse=True)

        # Check if saved version from last-options.json is valid in metadata
        preferred_major = find_major_for_version(self.metadata, self.config.version) if self.config.version else None

        if preferred_major:
            target_major_id = preferred_major.get("id")
            target_sub_id = self.config.version
            target_mod_id = self.config.module
        else:
            # Respect the default boolean value in metadata for first run or intentionally changed/invalid config
            default_major = next((m for m in versions if m.get("default")), versions[0])
            target_major_id = default_major.get("id")
            target_sub_id = None
            target_mod_id = None

        self.combo_major.blockSignals(True)
        self.combo_major.clear()

        selected_major_idx = 0
        for idx, major in enumerate(versions):
            name = major.get("name", "").strip()
            label = f"{major['id']} - {name}" if name else str(major["id"])
            self.combo_major.addItem(label, major)
            if major.get("id") == target_major_id:
                selected_major_idx = idx

        self.combo_major.setCurrentIndex(selected_major_idx)
        self.combo_major.blockSignals(False)

        self._populate_subversions(target_sub_id=target_sub_id, target_mod_id=target_mod_id)

    def _populate_subversions(self, target_sub_id: str | None = None, target_mod_id: str | None = None):
        major = self.combo_major.currentData()
        if not major:
            return

        subversions = major.get("subversions", [])
        # Sort subversions by actual version hierarchy descending (e.g. 1.21.11 > 1.21.10 > 1.21.9)
        subversions = sorted(subversions, key=lambda s: parse_version_key(s.get("id", "")), reverse=True)

        self.combo_minor.blockSignals(True)
        self.combo_minor.clear()

        selected_sub_idx = 0
        matched_target = False

        if target_sub_id:
            for idx, sub in enumerate(subversions):
                if sub.get("id") == target_sub_id:
                    selected_sub_idx = idx
                    matched_target = True
                    break

        # If no target or target not in this major (e.g. user changed major intentionally):
        # Respect the default boolean value in Lunar Client metadata
        if not matched_target:
            for idx, sub in enumerate(subversions):
                if sub.get("default"):
                    selected_sub_idx = idx
                    break

        for sub in subversions:
            self.combo_minor.addItem(str(sub["id"]), sub)

        self.combo_minor.setCurrentIndex(selected_sub_idx)
        self.combo_minor.blockSignals(False)

        self._populate_flavors(target_mod_id=target_mod_id if matched_target else None)

    def _populate_flavors(self, target_mod_id: str | None = None):
        subversion = self.combo_minor.currentData()
        if not subversion:
            return

        modules = subversion.get("modules", [])
        self.combo_flavor.blockSignals(True)
        self.combo_flavor.clear()

        selected_flavor_idx = 0
        matched_target = False

        if target_mod_id:
            for idx, mod in enumerate(modules):
                if mod.get("id") == target_mod_id:
                    selected_flavor_idx = idx
                    matched_target = True
                    break

        # If no target or target not in this subversion (e.g. user changed subversion intentionally):
        # Respect the default boolean value in Lunar Client metadata
        if not matched_target:
            for idx, mod in enumerate(modules):
                if mod.get("default"):
                    selected_flavor_idx = idx
                    break

        for mod in modules:
            label = f"{mod.get('name', mod['id'])}"
            self.combo_flavor.addItem(label, mod)

        self.combo_flavor.setCurrentIndex(selected_flavor_idx)
        self.combo_flavor.blockSignals(False)

    def _on_major_changed(self):
        # User intentionally changed major version: select default subversion and default flavor
        self._populate_subversions(target_sub_id=None, target_mod_id=None)

    def _on_minor_changed(self):
        # User intentionally changed minor version: select default flavor
        self._populate_flavors(target_mod_id=None)

    def _open_options(self):
        dlg = OptionsDialog(self.config, self)
        if dlg.exec() == QDialog.Accepted:
            self.config = LauncherConfig.load()
            set_language(self.config.language)

    def _open_data_folder(self):
        data_dir = self.config.resolved_data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(data_dir)
        except Exception as e:
            QMessageBox.warning(
                self,
                t("main_open_folder_error_title"),
                t("main_open_folder_error_msg", error=e),
            )

    def _set_inputs_enabled(self, enabled: bool):
        self.combo_major.setEnabled(enabled)
        self.combo_minor.setEnabled(enabled)
        self.combo_flavor.setEnabled(enabled)
        self.edit_username.setEnabled(enabled)
        self.btn_options.setEnabled(enabled)
        self.btn_open_folder.setEnabled(enabled)
        self.btn_launch.setEnabled(enabled)

    def _start_launch(self):
        username = self.edit_username.text().strip()
        if not username:
            QMessageBox.warning(
                self,
                t("main_missing_username_title"),
                t("main_missing_username_msg"),
            )
            self.edit_username.setFocus()
            return

        subversion = self.combo_minor.currentData()
        module = self.combo_flavor.currentData()
        if not subversion or not module:
            QMessageBox.warning(
                self,
                t("main_invalid_selection_title"),
                t("main_invalid_selection_msg"),
            )
            return

        # Update and save configuration
        self.config.version = subversion["id"]
        self.config.module = module["id"]
        self.config.username = username
        self.config.save()

        # Disable interactive controls during launch
        self._set_inputs_enabled(False)
        self._status_state = "preparing"
        self.lbl_status1.setText(t("main_preparing_launch"))
        self.lbl_status2.setText(t("main_init_env"))
        self.progress_bar.setRange(0, 0)  # indeterminate pulse

        # Start Launch Worker
        self.worker = LaunchWorker(self.config, subversion, self)
        self.worker.sig_stage.connect(self._on_stage)
        self.worker.sig_detail.connect(self._on_detail)
        self.worker.sig_progress.connect(self._on_progress)
        self.worker.sig_process_spawned.connect(self._on_process_spawned)
        self.worker.sig_game_exited.connect(self._on_game_exited)
        self.worker.sig_finished.connect(self._on_finished)
        self.worker.start()

    def _on_stage(self, current: int, total: int, title: str):
        self._status_state = "staging"
        self._stage_info = (current, total, title)
        self.lbl_status1.setText(t("main_stage_format", current=current, total=total, title=title))

    def _on_detail(self, detail: str):
        self.lbl_status2.setText(detail)

    def _on_progress(self, pct: int):
        if pct < 0:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)

    def _on_process_spawned(self):
        if not self.config.keep_open:
            self.hide()

    def _on_game_exited(self, returncode: int):
        # Spawns launcher back when game instance is closed
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.raise_()
        self.activateWindow()
        self._set_inputs_enabled(True)
        self._status_state = "ready"
        self.lbl_status1.setText(t("main_ready"))
        self.lbl_status2.setText(t("main_select_version_hint"))
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

    def _on_finished(self, success: bool, error_msg: str):
        if success:
            if self.config.keep_open:
                self._status_state = "running"
                self.lbl_status1.setText(t("main_game_running"))
                self.lbl_status2.setText(t("main_enjoy_game"))
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(100)
        else:
            self.show()
            self._set_inputs_enabled(True)
            self._status_state = "failed"
            self._last_error = error_msg
            self.lbl_status1.setText(t("main_launch_failed"))
            self.lbl_status2.setText(error_msg[:60] if error_msg else t("main_launch_failed_desc"))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            QMessageBox.critical(
                self,
                t("main_launch_error_title"),
                t("main_launch_error_msg", error=error_msg),
            )

    def _start_update_check(self):
        if is_frozen() and self.config.check_updates:
            self.update_worker = UpdateCheckWorker(parent=self)
            self.update_worker.sig_update_available.connect(self._on_update_available)
            self.update_worker.start()

    def _on_update_available(self, info: dict):
        latest_tag = info.get("tag_name", "")
        current_ver = info.get("current_version", "")
        latest_display = latest_tag if latest_tag.startswith("v") else f"v{latest_tag}"
        current_display = current_ver if current_ver.startswith("v") else f"v{current_ver}"
        reply = QMessageBox.question(
            self,
            t("update_dialog_title"),
            t("update_dialog_msg", latest=latest_display, current=current_display),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            dlg = UpdateProgressDialog(info, self)
            dlg.exec()

    def closeEvent(self, event):
        QApplication.quit()
        super().closeEvent(event)
