"""
First-time setup dialog for LibreLunar.
Prompts user to select preferred language, data storage location
(AppData vs Custom directory), and choose an offline username.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
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
from ..core.paths import get_default_data_dir, init_data_structure


class SetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(420)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.default_data_dir = get_default_data_dir()
        self.selected_data_dir = self.default_data_dir

        icon_path = Path(__file__).resolve().parent.parent / "resources" / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.init_ui()
        self.retranslate_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        # Welcome Header
        self.lbl_welcome = QLabel()
        self.lbl_welcome.setStyleSheet("font-size: 13pt; font-weight: bold; color: #ffffff; margin-bottom: 4px;")
        layout.addWidget(self.lbl_welcome)

        self.lbl_desc = QLabel()
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("color: #9ba1b0; font-size: 8pt; margin-bottom: 8px;")
        layout.addWidget(self.lbl_desc)

        # Section 0: Preferred Language
        self.lbl_lang = QLabel()
        self.lbl_lang.setStyleSheet("color: #9ba1b0; font-size: 8pt; font-weight: 700; letter-spacing: 0.5px;")
        layout.addWidget(self.lbl_lang)

        self.combo_language = QComboBox()
        for code, name in get_supported_languages().items():
            self.combo_language.addItem(name, code)

        # Select initial language
        cur_lang = normalize_lang_code(get_language())
        for idx in range(self.combo_language.count()):
            if self.combo_language.itemData(idx) == cur_lang:
                self.combo_language.setCurrentIndex(idx)
                break

        self.combo_language.currentIndexChanged.connect(self._on_language_changed)
        layout.addWidget(self.combo_language)

        layout.addSpacing(6)

        # Section 1: Storage Location
        self.lbl_storage = QLabel()
        self.lbl_storage.setStyleSheet("color: #9ba1b0; font-size: 8pt; font-weight: 700; letter-spacing: 0.5px;")
        layout.addWidget(self.lbl_storage)

        self.btn_group = QButtonGroup(self)

        self.rb_appdata = QRadioButton()
        self.rb_appdata.setChecked(True)
        self.btn_group.addButton(self.rb_appdata)
        layout.addWidget(self.rb_appdata)

        self.lbl_appdata_path = QLabel(f"  {self.default_data_dir}")
        self.lbl_appdata_path.setStyleSheet("color: #6b7280; font-size: 8pt; margin-bottom: 4px;")
        layout.addWidget(self.lbl_appdata_path)

        self.rb_custom = QRadioButton()
        self.btn_group.addButton(self.rb_custom)
        layout.addWidget(self.rb_custom)

        custom_row = QHBoxLayout()
        custom_row.setSpacing(6)
        self.txt_custom_path = QLineEdit()
        self.txt_custom_path.setEnabled(False)
        custom_row.addWidget(self.txt_custom_path, stretch=1)

        self.btn_browse = QPushButton()
        self.btn_browse.setEnabled(False)
        self.btn_browse.clicked.connect(self._browse_directory)
        custom_row.addWidget(self.btn_browse)
        layout.addLayout(custom_row)

        self.rb_appdata.toggled.connect(self._on_storage_toggled)

        layout.addSpacing(6)

        # Section 2: Offline Username
        self.lbl_user = QLabel()
        self.lbl_user.setStyleSheet("color: #9ba1b0; font-size: 8pt; font-weight: 700; letter-spacing: 0.5px;")
        layout.addWidget(self.lbl_user)

        self.txt_username = QLineEdit()
        self.txt_username.setText("Player")
        layout.addWidget(self.txt_username)

        layout.addSpacing(6)

        # Section 3: Updates Consent
        self.chk_updates = QCheckBox()
        self.chk_updates.setChecked(True)
        layout.addWidget(self.chk_updates)

        layout.addSpacing(8)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_continue = QPushButton()
        self.btn_continue.setObjectName("launchButton")
        self.btn_continue.clicked.connect(self._on_continue)
        btn_layout.addWidget(self.btn_continue)

        layout.addLayout(btn_layout)

    def retranslate_ui(self):
        """Update all user-visible strings in real time."""
        self.setWindowTitle(t("setup_title"))
        self.lbl_welcome.setText(t("setup_welcome"))
        self.lbl_desc.setText(t("setup_desc"))
        self.lbl_lang.setText(t("setup_language_section"))
        self.lbl_storage.setText(t("setup_storage_section"))
        self.rb_appdata.setText(t("setup_appdata_option"))
        self.rb_custom.setText(t("setup_custom_option"))
        self.txt_custom_path.setPlaceholderText(t("setup_custom_placeholder"))
        self.btn_browse.setText(t("setup_browse_button"))
        self.lbl_user.setText(t("setup_username_section"))
        self.txt_username.setPlaceholderText(t("setup_username_placeholder"))
        self.chk_updates.setText(t("setup_check_updates"))
        self.btn_continue.setText(t("setup_continue_button"))

    def _on_language_changed(self, index: int):
        lang = self.combo_language.currentData()
        if lang:
            set_language(lang)
            self.retranslate_ui()

    def _on_storage_toggled(self, checked: bool):
        is_custom = not checked
        self.txt_custom_path.setEnabled(is_custom)
        self.btn_browse.setEnabled(is_custom)
        if is_custom and not self.txt_custom_path.text().strip():
            # Suggest current directory / Data if portable
            self.txt_custom_path.setText(str(Path.cwd() / "Data"))

    def _browse_directory(self):
        chosen = QFileDialog.getExistingDirectory(
            self,
            t("setup_select_dir"),
            self.txt_custom_path.text() or str(Path.home()),
        )
        if chosen:
            self.txt_custom_path.setText(str(Path(chosen).resolve()))

    def _on_continue(self):
        username = self.txt_username.text().strip()
        if not username:
            username = "Player"

        if self.rb_appdata.isChecked():
            chosen_path = self.default_data_dir
        else:
            custom_str = self.txt_custom_path.text().strip()
            if not custom_str:
                QMessageBox.warning(self, t("setup_invalid_path_title"), t("setup_invalid_path_msg"))
                return
            chosen_path = Path(custom_str).resolve()

        try:
            chosen_path.mkdir(parents=True, exist_ok=True)
            # Test write access
            test_file = chosen_path / ".perm_check"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
        except Exception as e:
            QMessageBox.critical(
                self,
                t("permission_error"),
                t("setup_perm_error", path=chosen_path, error=e),
            )
            return

        # Initialize directory layout
        init_data_structure(chosen_path)

        # Update launcher configuration
        config = LauncherConfig.load()
        config.data_dir = str(chosen_path)
        config.username = username
        config.language = self.combo_language.currentData() or get_language()
        config.check_updates = self.chk_updates.isChecked()
        config.first_run_completed = True
        config.save()
        set_language(config.language)

        self.accept()
