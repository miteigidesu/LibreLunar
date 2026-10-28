"""
Options dialog for adjusting RAM, resolution, fullscreen, verbose mode, language, and window retention.
"""
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core.config import LauncherConfig
from ..core.i18n import (
    get_language,
    get_supported_languages,
    normalize_lang_code,
    set_language,
    t,
)
from ..core.paths import init_data_structure
from ..core.updater import UpdateCheckWorker, is_frozen
from .styles import LAUNCHER_STYLE
from .update_dialog import UpdateProgressDialog


class OptionsDialog(QDialog):
    PRESETS = [
        ("1280 x 720 (16:9 HD)", 1280, 720),
        ("854 x 480 (Minecraft Default)", 854, 480),
        ("1920 x 1080 (16:9 Full HD)", 1920, 1080),
        ("1600 x 900 (16:9 HD+)", 1600, 900),
        ("2560 x 1440 (16:9 QHD)", 2560, 1440),
        ("Custom", None, None),
    ]

    def __init__(self, config: LauncherConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._initial_language = self.config.language or get_language()
        self.setStyleSheet(LAUNCHER_STYLE)
        self.setModal(True)
        self.setFixedWidth(400)

        icon_path = Path(__file__).resolve().parent.parent / "resources" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._updating_res = False
        self._update_worker = None
        self._init_ui()
        self._load_values()
        self._retranslate_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        # 0. Language Group
        self.lbl_language = QLabel()
        self.lbl_language.setStyleSheet("font-weight: bold; color: #f3f4f6; font-size: 9pt;")
        layout.addWidget(self.lbl_language)

        self.combo_language = QComboBox()
        for code, name in get_supported_languages().items():
            self.combo_language.addItem(name, code)
        self.combo_language.currentIndexChanged.connect(self._on_language_changed)
        layout.addWidget(self.combo_language)

        # Separator
        line0 = QFrame()
        line0.setFrameShape(QFrame.HLine)
        line0.setStyleSheet("color: #363944;")
        layout.addWidget(line0)

        # 1. Allocated RAM Group
        self.ram_label = QLabel()
        self.ram_label.setStyleSheet("font-weight: bold; color: #f3f4f6; font-size: 9pt;")
        layout.addWidget(self.ram_label)

        ram_row = QHBoxLayout()
        self.spin_ram = QSpinBox()
        self.spin_ram.setRange(1024, 65536)
        self.spin_ram.setSingleStep(512)
        self.spin_ram.setSuffix(" MB")
        self.spin_ram.valueChanged.connect(self._on_ram_changed)
        ram_row.addWidget(self.spin_ram)

        self.lbl_ram_gb = QLabel("3.0 GB")
        self.lbl_ram_gb.setStyleSheet("color: #e2e4ea; font-weight: 600; min-width: 50px;")
        ram_row.addWidget(self.lbl_ram_gb)
        layout.addLayout(ram_row)

        # Quick RAM preset buttons
        quick_ram_layout = QHBoxLayout()
        quick_ram_layout.setSpacing(6)
        for mb in (2048, 3072, 4096, 6144, 8192):
            btn = QPushButton(f"{mb // 1024} GB")
            btn.setStyleSheet("padding: 3px 6px; font-size: 8pt;")
            btn.clicked.connect(lambda _, val=mb: self.spin_ram.setValue(val))
            quick_ram_layout.addWidget(btn)
        layout.addLayout(quick_ram_layout)

        # Separator
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setStyleSheet("color: #363944;")
        layout.addWidget(line1)

        # 2. Resolution Group
        self.res_label = QLabel()
        self.res_label.setStyleSheet("font-weight: bold; color: #f3f4f6; font-size: 9pt;")
        layout.addWidget(self.res_label)

        self.combo_presets = QComboBox()
        self._populate_presets()
        self.combo_presets.currentIndexChanged.connect(self._on_preset_changed)
        layout.addWidget(self.combo_presets)

        res_row = QHBoxLayout()
        self.lbl_width = QLabel()
        res_row.addWidget(self.lbl_width)
        self.spin_width = QSpinBox()
        self.spin_width.setRange(640, 7680)
        self.spin_width.setSingleStep(10)
        self.spin_width.valueChanged.connect(self._on_custom_res_changed)
        res_row.addWidget(self.spin_width)

        self.lbl_height = QLabel()
        res_row.addWidget(self.lbl_height)
        self.spin_height = QSpinBox()
        self.spin_height.setRange(360, 4320)
        self.spin_height.setSingleStep(10)
        self.spin_height.valueChanged.connect(self._on_custom_res_changed)
        res_row.addWidget(self.spin_height)
        layout.addLayout(res_row)

        # Separator
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setStyleSheet("color: #363944;")
        layout.addWidget(line2)

        # 3. Switches / Checkboxes
        switches_layout = QVBoxLayout()
        switches_layout.setSpacing(8)

        self.chk_fullscreen = QCheckBox()
        switches_layout.addWidget(self.chk_fullscreen)

        self.chk_verbose = QCheckBox()
        switches_layout.addWidget(self.chk_verbose)

        self.chk_keep_open = QCheckBox()
        switches_layout.addWidget(self.chk_keep_open)

        update_row = QHBoxLayout()
        self.chk_updates = QCheckBox()
        update_row.addWidget(self.chk_updates, stretch=1)

        self.btn_check_updates = QPushButton()
        self.btn_check_updates.clicked.connect(self._manual_check_updates)
        update_row.addWidget(self.btn_check_updates)
        switches_layout.addLayout(update_row)

        layout.addLayout(switches_layout)

        # Separator
        line3 = QFrame()
        line3.setFrameShape(QFrame.HLine)
        line3.setStyleSheet("color: #363944;")
        layout.addWidget(line3)

        # 4. Storage Location Info
        self.storage_label = QLabel()
        self.storage_label.setStyleSheet("font-weight: bold; color: #f3f4f6; font-size: 9pt;")
        layout.addWidget(self.storage_label)

        dir_row = QHBoxLayout()
        self.txt_data_dir = QLineEdit()
        self.txt_data_dir.setReadOnly(True)
        dir_row.addWidget(self.txt_data_dir, stretch=1)

        self.btn_change_dir = QPushButton()
        self.btn_change_dir.clicked.connect(self._change_data_dir)
        dir_row.addWidget(self.btn_change_dir)
        layout.addLayout(dir_row)

        # 5. Dialog Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton()
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_save = QPushButton()
        self.btn_save.setObjectName("launchButton")
        self.btn_save.clicked.connect(self._save_and_close)
        btn_layout.addWidget(self.btn_save)

        layout.addLayout(btn_layout)

    def _populate_presets(self):
        cur_idx = self.combo_presets.currentIndex() if self.combo_presets.count() > 0 else 0
        self.combo_presets.blockSignals(True)
        self.combo_presets.clear()
        for name, w, h in self.PRESETS:
            if w == 854 and h == 480:
                self.combo_presets.addItem(f"854 x 480 ({t('options_preset_default')})")
            elif w is None and h is None:
                self.combo_presets.addItem(t("options_preset_custom"))
            else:
                self.combo_presets.addItem(name)
        if cur_idx >= 0 and cur_idx < self.combo_presets.count():
            self.combo_presets.setCurrentIndex(cur_idx)
        self.combo_presets.blockSignals(False)

    def _retranslate_ui(self):
        """Update all user-visible strings in real time."""
        self.setWindowTitle(t("options_title"))
        self.lbl_language.setText(t("options_language"))
        self.ram_label.setText(t("options_ram"))
        self.res_label.setText(t("options_resolution"))
        self.lbl_width.setText(t("options_width"))
        self.lbl_height.setText(t("options_height"))
        self.chk_fullscreen.setText(t("options_fullscreen"))
        self.chk_verbose.setText(t("options_verbose"))
        self.chk_verbose.setToolTip(t("options_verbose_tooltip"))
        self.chk_keep_open.setText(t("options_keep_open"))
        self.chk_updates.setText(t("options_check_updates"))
        self.btn_check_updates.setText(t("options_btn_check_updates"))
        self.storage_label.setText(t("options_storage"))
        self.btn_change_dir.setText(t("options_change"))
        self.btn_cancel.setText(t("cancel"))
        self.btn_save.setText(t("save"))

        self._populate_presets()

    def _load_values(self):
        # Language selection
        cur_lang = normalize_lang_code(self.config.language or get_language())
        for idx in range(self.combo_language.count()):
            if self.combo_language.itemData(idx) == cur_lang:
                self.combo_language.blockSignals(True)
                self.combo_language.setCurrentIndex(idx)
                self.combo_language.blockSignals(False)
                break

        self.spin_ram.setValue(self.config.memory)
        self._on_ram_changed(self.config.memory)

        self._updating_res = True
        self.spin_width.setValue(self.config.width)
        self.spin_height.setValue(self.config.height)
        self._match_preset(self.config.width, self.config.height)
        self._updating_res = False

        self.chk_fullscreen.setChecked(self.config.fullscreen)
        self.chk_verbose.setChecked(self.config.verbose)
        self.chk_keep_open.setChecked(self.config.keep_open)
        self.chk_updates.setChecked(self.config.check_updates)
        self.txt_data_dir.setText(str(self.config.resolved_data_dir))

    def _on_language_changed(self, index: int):
        lang = self.combo_language.currentData()
        if lang:
            set_language(lang)
            self._retranslate_ui()

    def _change_data_dir(self):
        chosen = QFileDialog.getExistingDirectory(
            self,
            t("options_select_dir"),
            str(self.config.resolved_data_dir),
        )
        if chosen:
            p = Path(chosen).resolve()
            try:
                p.mkdir(parents=True, exist_ok=True)
                test_file = p / ".perm_check"
                test_file.write_text("ok", encoding="utf-8")
                test_file.unlink()
                self.txt_data_dir.setText(str(p))
            except Exception as e:
                QMessageBox.critical(
                    self,
                    t("permission_error"),
                    t("options_perm_error", path=p, error=e),
                )

    def _on_ram_changed(self, mb: int):
        gb = mb / 1024.0
        self.lbl_ram_gb.setText(f"{gb:.1f} GB")

    def _match_preset(self, w: int, h: int):
        for idx, (_, pw, ph) in enumerate(self.PRESETS):
            if pw == w and ph == h:
                self.combo_presets.setCurrentIndex(idx)
                return
        # Custom index is last
        self.combo_presets.setCurrentIndex(len(self.PRESETS) - 1)

    def _on_preset_changed(self, idx: int):
        if self._updating_res:
            return
        _, w, h = self.PRESETS[idx]
        if w is not None and h is not None:
            self._updating_res = True
            self.spin_width.setValue(w)
            self.spin_height.setValue(h)
            self._updating_res = False

    def _on_custom_res_changed(self):
        if self._updating_res:
            return
        w = self.spin_width.value()
        h = self.spin_height.value()
        self._updating_res = True
        self._match_preset(w, h)
        self._updating_res = False

    def reject(self):
        # Revert language if changed without saving
        if get_language() != self._initial_language:
            set_language(self._initial_language)
        super().reject()

    def _save_and_close(self):
        self.config.language = self.combo_language.currentData() or get_language()
        self.config.memory = self.spin_ram.value()
        self.config.width = self.spin_width.value()
        self.config.height = self.spin_height.value()
        self.config.fullscreen = self.chk_fullscreen.isChecked()
        self.config.verbose = self.chk_verbose.isChecked()
        self.config.keep_open = self.chk_keep_open.isChecked()
        self.config.check_updates = self.chk_updates.isChecked()

        new_dir = Path(self.txt_data_dir.text().strip()).resolve()
        if new_dir != self.config.resolved_data_dir:
            init_data_structure(new_dir)
            self.config.data_dir = str(new_dir)

        self.config.save()
        set_language(self.config.language)
        self.accept()

    def _manual_check_updates(self):
        if not is_frozen():
            QMessageBox.information(
                self,
                t("update_dialog_title"),
                t("update_dev_mode"),
            )
            return

        self.btn_check_updates.setEnabled(False)
        self.btn_check_updates.setText(t("update_checking"))

        self._update_worker = UpdateCheckWorker(parent=self)
        self._update_worker.sig_update_available.connect(self._on_update_available)
        self._update_worker.sig_no_update.connect(self._on_no_update)
        self._update_worker.sig_error.connect(self._on_update_error)
        self._update_worker.start()

    def _on_update_available(self, info: dict):
        self.btn_check_updates.setEnabled(True)
        self.btn_check_updates.setText(t("options_btn_check_updates"))
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

    def _on_no_update(self, current: str):
        self.btn_check_updates.setEnabled(True)
        self.btn_check_updates.setText(t("options_btn_check_updates"))
        ver_str = current if current.startswith("v") else f"v{current}"
        QMessageBox.information(
            self,
            t("update_latest_title"),
            t("update_latest_msg", version=ver_str),
        )

    def _on_update_error(self, err: str):
        self.btn_check_updates.setEnabled(True)
        self.btn_check_updates.setText(t("options_btn_check_updates"))
        QMessageBox.warning(
            self,
            t("update_failed"),
            t("update_failed_msg", error=err),
        )
