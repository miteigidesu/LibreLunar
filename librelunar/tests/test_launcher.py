"""
Unit tests for LibreLunar launcher.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Create a temporary directory for tests to isolate from user AppData
_TEST_TEMP_DIR = tempfile.TemporaryDirectory()
_TEMP_PATH = Path(_TEST_TEMP_DIR.name)
os.environ["LIBRELUNAR_CONFIG_DIR"] = str(_TEMP_PATH)
os.environ["LIBRELUNAR_DATA_DIR"] = str(_TEMP_PATH / "LibreLunar")

# Sample offline metadata for testing
MOCK_METADATA = {
    "versions": [
        {
            "id": "26",
            "name": "Minecraft 26",
            "default": False,
            "subversions": [
                {
                    "id": "26.3",
                    "default": True,
                    "modules": [{"id": "lunar", "name": "Lunar", "default": True}],
                }
            ],
        },
        {
            "id": "1.21",
            "name": "Tricky Trials",
            "default": True,
            "subversions": [
                {
                    "id": "1.21.11",
                    "default": True,
                    "modules": [
                        {"id": "fabric", "name": "Lunar + Fabric", "default": True},
                        {"id": "lunar", "name": "Lunar", "default": False},
                    ],
                },
                {
                    "id": "1.21.10",
                    "default": False,
                    "modules": [{"id": "fabric", "name": "Lunar + Fabric", "default": True}],
                },
                {
                    "id": "1.21.9",
                    "default": False,
                    "modules": [{"id": "fabric", "name": "Lunar + Fabric", "default": True}],
                },
            ],
        },
        {
            "id": "1.20",
            "name": "Trails & Tales",
            "default": False,
            "subversions": [
                {
                    "id": "1.20.4",
                    "default": True,
                    "modules": [{"id": "fabric", "name": "Lunar + Fabric", "default": True}],
                }
            ],
        },
        {
            "id": "1.8",
            "name": "The Bountiful Update",
            "default": False,
            "subversions": [
                {
                    "id": "1.8.9",
                    "default": True,
                    "modules": [
                        {"id": "lunar", "name": "Lunar + OptiFine", "default": True}
                    ],
                }
            ],
        },
        {
            "id": "1.7",
            "name": "The Update that Changed the World",
            "default": False,
            "subversions": [
                {
                    "id": "1.7.10",
                    "default": True,
                    "modules": [
                        {"id": "lunar", "name": "Lunar + OptiFine", "default": True}
                    ],
                }
            ],
        },
    ]
}

# Cache metadata in test directory
_meta_file = _TEMP_PATH / "LibreLunar" / "metadata" / "versions.json"
_meta_file.parent.mkdir(parents=True, exist_ok=True)
_meta_file.write_text(json.dumps(MOCK_METADATA), encoding="utf-8")

from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for GUI tests
app = QApplication.instance() or QApplication([])

from librelunar.core.config import LauncherConfig
from librelunar.core.i18n import (
    get_i18n_dirs,
    get_language,
    get_supported_languages,
    set_language,
    t,
)
from librelunar.core.launcher import (
    build_command,
    fetch_launch_manifest,
    install_modpack,
    spawn_game_process,
)
from librelunar.core.metadata import fetch_version_metadata, find_major_for_version
from librelunar.core.paths import ProfilePaths
from librelunar.core.updater import (
    check_for_updates,
    is_frozen,
    is_version_newer,
)
from librelunar.core.utils import (
    get_app_title,
    offline_uuid,
    parse_version_key,
    sha1_of,
    sha256_of,
    verify_file_hash,
)
from librelunar.ui.main_window import MainWindow
from librelunar.ui.options_dialog import OptionsDialog
from librelunar.ui.setup_dialog import SetupDialog


class TestLibreLunar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = LauncherConfig.load()
        cfg.first_run_completed = True
        cfg.save()

    def test_utils(self):
        title = get_app_title()
        self.assertTrue(title.startswith("LibreLunar v"), f"Unexpected title: {title}")

        uuid1 = offline_uuid("Player")
        uuid2 = offline_uuid("Player")
        self.assertEqual(uuid1, uuid2)
        self.assertEqual(len(uuid1), 36)

    def test_config_defaults(self):
        cfg = LauncherConfig.load()
        self.assertGreaterEqual(cfg.memory, 1024)
        self.assertGreaterEqual(cfg.width, 640)
        self.assertGreaterEqual(cfg.height, 360)
        self.assertIsInstance(cfg.fullscreen, bool)
        self.assertIsInstance(cfg.verbose, bool)
        self.assertIsInstance(cfg.keep_open, bool)
        self.assertIsInstance(cfg.resolved_data_dir, Path)

    def test_setup_dialog_init(self):
        dlg = SetupDialog()
        self.assertTrue(dlg.rb_appdata.isChecked())
        self.assertFalse(dlg.txt_custom_path.isEnabled())
        self.assertEqual(dlg.txt_username.text(), "Player")

    def test_metadata_cached(self):
        cfg = LauncherConfig.load()
        meta = fetch_version_metadata(offline=True, data_dir=cfg.resolved_data_dir)
        self.assertIn("versions", meta)
        versions = meta["versions"]
        self.assertGreater(len(versions), 0)

        # Find major for 26.3
        major_26 = find_major_for_version(meta, "26.3")
        self.assertIsNotNone(major_26)
        self.assertEqual(major_26["id"], "26")

        # Find major for 1.8.9
        major_18 = find_major_for_version(meta, "1.8.9")
        self.assertIsNotNone(major_18)
        self.assertEqual(major_18["id"], "1.8")

    def test_options_dialog(self):
        cfg = LauncherConfig.load()
        dlg = OptionsDialog(cfg)
        self.assertEqual(dlg.spin_ram.value(), cfg.memory)
        self.assertEqual(dlg.spin_width.value(), cfg.width)
        self.assertEqual(dlg.spin_height.value(), cfg.height)
        self.assertEqual(dlg.chk_fullscreen.isChecked(), cfg.fullscreen)
        self.assertEqual(dlg.chk_verbose.isChecked(), cfg.verbose)
        self.assertEqual(dlg.chk_keep_open.isChecked(), cfg.keep_open)

    def test_main_window_prefill(self):
        win = MainWindow()
        self.assertTrue(win.combo_major.count() > 0)
        self.assertTrue(win.combo_minor.count() > 0)
        self.assertTrue(win.combo_flavor.count() > 0)

        if win.config.username:
            self.assertEqual(win.edit_username.text(), win.config.username)

        win.combo_major.setCurrentIndex(win.combo_major.count() - 1)
        self.assertTrue(win.combo_minor.count() > 0)

    def test_build_command_fullscreen(self):
        cfg = LauncherConfig(
            version="1.8.9",
            module="lunar",
            username="TestPlayer",
            memory=2048,
            width=1920,
            height=1080,
            fullscreen=True,
        )
        profile_paths = ProfilePaths("1.8.9", "lunar", data_dir=cfg.resolved_data_dir)
        manifest = {
            "launchTypeData": {"artifacts": []},
            "jre": {"extraArguments": []},
        }
        cmd = build_command(
            java=Path("java.exe"),
            manifest=manifest,
            config=cfg,
            lunar_cp=[],
            libs_cp=[],
            external=[],
            assets_dir=Path("assets"),
            asset_id="1.8",
            ui_dir=None,
            profile_paths=profile_paths,
        )
        self.assertIn("-Xmx2048m", cmd)
        self.assertIn("--width", cmd)
        self.assertIn("1920", cmd)
        self.assertIn("--height", cmd)
        self.assertIn("1080", cmd)
        self.assertIn("--fullscreen", cmd)
        self.assertIn("--username", cmd)
        self.assertIn("TestPlayer", cmd)

    def test_fetch_launch_manifest_signature(self):
        # Verify fetch_launch_manifest accepts both with and without profile_paths without TypeError
        cfg = LauncherConfig.load()
        pp = ProfilePaths("1.8.9", "lunar", data_dir=cfg.resolved_data_dir)
        # Should not raise TypeError: missing 1 required positional argument: 'profile_paths'
        try:
            fetch_launch_manifest("1.8.9", "lunar")
        except TypeError as e:
            self.fail(f"fetch_launch_manifest raised TypeError when called without profile_paths: {e}")
        except Exception:
            # Expected network error in offline test environment
            pass

        try:
            fetch_launch_manifest("1.8.9", "lunar", pp)
        except TypeError as e:
            self.fail(f"fetch_launch_manifest raised TypeError when called with profile_paths: {e}")
        except Exception:
            pass

    def test_install_modpack_mrpack_url(self):
        cfg = LauncherConfig.load()
        pp = ProfilePaths("1.21.11", "fabric", data_dir=cfg.resolved_data_dir)
        # Mock modpack with hash already marked as installed
        marker = pp.profile_data / ".modpack_installed"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("test_hash_123", encoding="utf-8")

        # Must not raise KeyError: 'url' when 'mrpackUrl' is used
        try:
            install_modpack({"hash": "test_hash_123", "mrpackUrl": "https://example.com/test.mrpack"}, pp)
        except KeyError as e:
            self.fail(f"install_modpack raised KeyError: {e}")

    def test_hash_verification(self):
        # Create temp file
        test_file = _TEMP_PATH / "hash_test.bin"
        test_file.write_bytes(b"hello world")

        expected_sha1 = "2aae6c35c94fcfb415dbe95f408b9ce91ee846ed"
        expected_sha256 = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

        self.assertEqual(sha1_of(test_file), expected_sha1)
        self.assertEqual(sha256_of(test_file), expected_sha256)

        # verify_file_hash automatically handles both 40-char SHA-1 and 64-char SHA-256
        self.assertTrue(verify_file_hash(test_file, expected_sha1))
        self.assertTrue(verify_file_hash(test_file, expected_sha256))
        self.assertFalse(verify_file_hash(test_file, "0" * 40))
        self.assertFalse(verify_file_hash(test_file, "0" * 64))

    def test_game_spawn_and_respawn_lifecycle(self):
        win = MainWindow()
        win.show()
        win.config.keep_open = False
        win._on_process_spawned()
        self.assertFalse(win.isVisible())

        win._on_game_exited(0)
        self.assertTrue(win.isVisible())
        self.assertEqual(win.lbl_status1.text(), "Ready to launch")
        self.assertEqual(win.progress_bar.value(), 0)
        self.assertTrue(win.btn_launch.isEnabled())

    def test_version_ordering(self):
        # 1.21.11 must be higher than 1.21.10, and 1.21.10 must be higher than 1.21.9
        self.assertGreater(parse_version_key("1.21.11"), parse_version_key("1.21.10"))
        self.assertGreater(parse_version_key("1.21.10"), parse_version_key("1.21.9"))
        self.assertGreater(parse_version_key("1.21.9"), parse_version_key("1.21.1"))
        self.assertGreater(parse_version_key("1.21.1"), parse_version_key("1.21"))

        # Major version order
        self.assertGreater(parse_version_key("26"), parse_version_key("1.21"))
        self.assertGreater(parse_version_key("1.21"), parse_version_key("1.20"))
        self.assertGreater(parse_version_key("1.20"), parse_version_key("1.8"))
        self.assertGreater(parse_version_key("1.8"), parse_version_key("1.7"))

    def test_version_defaults_on_intentional_change(self):
        win = MainWindow()
        major_ids = [win.combo_major.itemData(i)["id"] for i in range(win.combo_major.count())]
        idx_121 = major_ids.index("1.21")
        win.combo_major.setCurrentIndex(idx_121)

        # 1.21.11 is the default in 1.21 metadata
        self.assertEqual(win.combo_minor.currentData()["id"], "1.21.11")
        # fabric is the default flavor in 1.21.11
        self.assertEqual(win.combo_flavor.currentData()["id"], "fabric")

        # Subversions order must place 1.21.11 before 1.21.10 and 1.21.9
        sub_ids = [win.combo_minor.itemData(i)["id"] for i in range(win.combo_minor.count())]
        self.assertLess(sub_ids.index("1.21.11"), sub_ids.index("1.21.10"))
        self.assertLess(sub_ids.index("1.21.10"), sub_ids.index("1.21.9"))

        # Switch to 1.8
        idx_18 = major_ids.index("1.8")
        win.combo_major.setCurrentIndex(idx_18)
        self.assertEqual(win.combo_minor.currentData()["id"], "1.8.9")
        self.assertEqual(win.combo_flavor.currentData()["id"], "lunar")

    def test_unified_paths(self):
        cfg = LauncherConfig.load()
        base = cfg.resolved_data_dir
        pp = ProfilePaths("1.8.9", "lunar", data_dir=base)
        # Artifact view should be unified in artifacts / views
        self.assertEqual(pp.artifact_view, base / "artifacts" / "views")
        # Libraries should be unified in data_dir / libraries
        self.assertEqual(pp.libraries, base / "libraries")
        # Natives must remain per-profile to avoid DLL collisions (e.g. lwjgl.dll)
        self.assertEqual(pp.natives, pp.profile_data / "natives")

    def test_i18n_translations(self):
        # Verify JSON files exist on disk
        i18n_dirs = get_i18n_dirs()
        self.assertGreater(len(i18n_dirs), 0)
        found_en = any((d / "en_us.json").is_file() for d in i18n_dirs)
        found_vi = any((d / "vi_vn.json").is_file() for d in i18n_dirs)
        self.assertTrue(found_en, "en_us.json was not found in i18n directories")
        self.assertTrue(found_vi, "vi_vn.json was not found in i18n directories")

        # Supported languages from JSON files
        langs = get_supported_languages()
        self.assertIn("en_us", langs)
        self.assertIn("vi_vn", langs)
        self.assertEqual(langs["en_us"], "English")
        self.assertEqual(langs["vi_vn"], "Tiếng Việt")

        # Test EN
        set_language("en")
        self.assertEqual(get_language(), "en_us")
        self.assertEqual(t("main_launch"), "Launch")
        self.assertEqual(t("setup_title"), "LibreLunar Setup")
        self.assertEqual(t("setup_continue_button"), "Get Started")
        self.assertEqual(t("main_stage_format", current=1, total=5, title="Test"), "Stage 1/5: Test")

        # Test VI
        set_language("vi")
        self.assertEqual(get_language(), "vi_vn")
        self.assertEqual(t("main_launch"), "Khởi chạy")
        self.assertEqual(t("setup_title"), "Cài đặt LibreLunar")
        self.assertEqual(t("setup_continue_button"), "Bắt đầu")
        self.assertEqual(t("main_stage_format", current=1, total=5, title="Thử nghiệm"), "Giai đoạn 1/5: Thử nghiệm")

        # Fallback to English on unknown key or invalid lang
        set_language("unknown")
        self.assertEqual(get_language(), "en_us")
        self.assertEqual(t("some_nonexistent_key"), "some_nonexistent_key")

        # Reset to EN for other tests
        set_language("en_us")

    def test_setup_dialog_realtime_localization(self):
        set_language("en_us")
        dlg = SetupDialog()

        # Check English initial state
        self.assertEqual(dlg.windowTitle(), "LibreLunar Setup")
        self.assertEqual(dlg.lbl_welcome.text(), "Welcome to LibreLunar")
        self.assertEqual(dlg.btn_continue.text(), "Get Started")
        self.assertEqual(dlg.lbl_storage.text(), "DATA STORAGE LOCATION")
        self.assertEqual(dlg.rb_appdata.text(), "Application Data (Recommended)")
        self.assertEqual(dlg.rb_custom.text(), "Custom Folder (Portable / External Drive)")
        self.assertEqual(dlg.lbl_user.text(), "OFFLINE USERNAME")

        # Switch to Vietnamese in real-time
        vi_idx = dlg.combo_language.findData("vi_vn")
        self.assertGreaterEqual(vi_idx, 0)
        dlg.combo_language.setCurrentIndex(vi_idx)

        # Dialog texts must update in real time in this window!
        self.assertEqual(get_language(), "vi_vn")
        self.assertEqual(dlg.windowTitle(), "Cài đặt LibreLunar")
        self.assertEqual(dlg.lbl_welcome.text(), "Chào mừng đến với LibreLunar")
        self.assertEqual(dlg.btn_continue.text(), "Bắt đầu")
        self.assertEqual(dlg.lbl_storage.text(), "VỊ TRÍ LƯU TRỮ DỮ LIỆU")
        self.assertEqual(dlg.rb_appdata.text(), "Dữ liệu ứng dụng (Khuyến nghị)")
        self.assertEqual(dlg.rb_custom.text(), "Thư mục tùy chỉnh (Di động / Ổ đĩa ngoài)")
        self.assertEqual(dlg.lbl_user.text(), "TÊN NGƯỜI CHƠI (OFFLINE)")

        # Switch back to English in real-time
        en_idx = dlg.combo_language.findData("en_us")
        dlg.combo_language.setCurrentIndex(en_idx)
        self.assertEqual(get_language(), "en_us")
        self.assertEqual(dlg.windowTitle(), "LibreLunar Setup")
        self.assertEqual(dlg.lbl_welcome.text(), "Welcome to LibreLunar")
        self.assertEqual(dlg.btn_continue.text(), "Get Started")

    def test_options_dialog_localization(self):
        set_language("en_us")
        cfg = LauncherConfig.load()
        cfg.language = "en_us"
        dlg = OptionsDialog(cfg)

        self.assertEqual(dlg.windowTitle(), "Options")
        self.assertEqual(dlg.lbl_language.text(), "Language")
        self.assertEqual(dlg.ram_label.text(), "Allocated RAM")
        self.assertEqual(dlg.res_label.text(), "Game Resolution")
        self.assertEqual(dlg.btn_cancel.text(), "Cancel")
        self.assertEqual(dlg.btn_save.text(), "Save")

        # Switch to Vietnamese
        vi_idx = dlg.combo_language.findData("vi_vn")
        dlg.combo_language.setCurrentIndex(vi_idx)

        self.assertEqual(dlg.windowTitle(), "Tùy chọn")
        self.assertEqual(dlg.lbl_language.text(), "Ngôn ngữ")
        self.assertEqual(dlg.ram_label.text(), "RAM phân bổ")
        self.assertEqual(dlg.res_label.text(), "Độ phân giải trò chơi")
        self.assertEqual(dlg.btn_cancel.text(), "Hủy")
        self.assertEqual(dlg.btn_save.text(), "Lưu")

        # Cancel should revert language
        dlg.reject()
        self.assertEqual(get_language(), "en_us")

    def test_main_window_localization(self):
        set_language("en_us")
        win = MainWindow()
        self.assertEqual(win.btn_launch.text(), "Launch")
        self.assertEqual(win.btn_options.text(), "Options")
        self.assertEqual(win.btn_open_folder.text(), "Open data folder")
        self.assertEqual(win.lbl_status1.text(), "Ready to launch")

        # Change language globally
        set_language("vi_vn")
        self.assertEqual(win.btn_launch.text(), "Khởi chạy")
        self.assertEqual(win.btn_options.text(), "Tùy chọn")
        self.assertEqual(win.btn_open_folder.text(), "Mở thư mục dữ liệu")
        self.assertEqual(win.lbl_status1.text(), "Sẵn sàng khởi chạy")

        # Reset back to EN
        set_language("en_us")
        self.assertEqual(win.btn_launch.text(), "Launch")

    def test_config_adaptation_and_migration(self):
        # 1. Test legacy alias mapping
        legacy_data = {
            "offline_name": "OldPlayer",
            "ram": 6144,
            "lang": "vi",
            "auto_update": False,
            "res_width": 1600,
            "res_height": 900,
            "keepopen": True,
            "new_future_option": "retained_value",
        }
        cfg = LauncherConfig.from_dict(legacy_data)
        self.assertEqual(cfg.username, "OldPlayer")
        self.assertEqual(cfg.memory, 6144)
        self.assertEqual(cfg.language, "vi_vn")
        self.assertFalse(cfg.check_updates)
        self.assertEqual(cfg.width, 1600)
        self.assertEqual(cfg.height, 900)
        self.assertTrue(cfg.keep_open)
        self.assertEqual(cfg.extra_fields.get("new_future_option"), "retained_value")

        # Serialized dict must preserve extra_fields without data loss
        saved_dict = cfg.to_dict()
        self.assertEqual(saved_dict["username"], "OldPlayer")
        self.assertEqual(saved_dict["check_updates"], False)
        self.assertEqual(saved_dict["new_future_option"], "retained_value")

        # 2. Test bounds clamping & type coercion
        dirty_data = {
            "memory": "99999999",  # should clamp to 131072
            "width": 10,           # should clamp to 640
            "height": 99999,       # should clamp to 4320
            "fullscreen": "yes",   # coerced to bool True
            "username": "   ",     # stripped empty -> fallback to Player
            "language": "invalid_lang_code", # fallback to en_us
        }
        cfg_clamped = LauncherConfig.from_dict(dirty_data)
        self.assertEqual(cfg_clamped.memory, 131072)
        self.assertEqual(cfg_clamped.width, 640)
        self.assertEqual(cfg_clamped.height, 4320)
        self.assertTrue(cfg_clamped.fullscreen)
        self.assertEqual(cfg_clamped.username, "Player")
        self.assertEqual(cfg_clamped.language, "en_us")

    def test_updater_version_check(self):
        # Semantic versions
        self.assertTrue(is_version_newer("v1.2.0", "1.1.0"))
        self.assertFalse(is_version_newer("1.1.0", "v1.2.0"))
        self.assertFalse(is_version_newer("v1.0.0", "1.0.0"))
        self.assertFalse(is_version_newer("1.0.0", "1.0.0"))

        # Calendar versioning (YYYY.MM.DD.run_number)
        self.assertTrue(is_version_newer("2026.10.28.2", "2026.10.28.1"))
        self.assertFalse(is_version_newer("2026.10.28.1", "2026.10.28.2"))
        self.assertFalse(is_version_newer("2026.10.28.1", "2026.10.28.1"))
        self.assertTrue(is_version_newer("2026.10.28.10", "2026.10.28.2"))
        self.assertTrue(is_version_newer("2026.10.29.1", "2026.10.28.5"))
        # CalVer is newer than legacy commit hash
        self.assertTrue(is_version_newer("2026.10.28.1", "bc7ba8e"))
        self.assertTrue(is_version_newer("2026.10.28.1", "4b48ec9"))

        # Commit hash prefixes and matching
        self.assertFalse(is_version_newer("build-e9efe18", "e9efe18"))
        self.assertFalse(is_version_newer("v1.0.0", "e9efe18", release_name="LibreLunar (e9efe18)"))

        # Dev mode builds should not trigger updates
        self.assertFalse(is_version_newer("v2.0.0", "dev"))

        # Newer commit
        self.assertTrue(is_version_newer("build-a1b2c3d", "build-e9efe18"))

    @patch("urllib.request.urlopen")
    def test_updater_check_for_updates_mock(self, mock_urlopen):
        # Mock GitHub release response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "tag_name": "v2.0.0",
            "name": "LibreLunar 2.0.0",
            "body": "Release notes",
            "published_at": "2026-10-27T00:00:00Z",
            "html_url": "https://github.com/miteigidesu/LibreLunar/releases/tag/v2.0.0",
            "assets": [
                {
                    "name": "LibreLunar-v2.0.0.zip",
                    "browser_download_url": "https://github.com/.../LibreLunar-v2.0.0.zip",
                    "size": 35000000,
                }
            ],
        }).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        # Check when current is older (1.0.0) -> returns dict
        info = check_for_updates(current_version="1.0.0")
        self.assertIsNotNone(info)
        self.assertEqual(info["tag_name"], "v2.0.0")
        self.assertEqual(info["asset_name"], "LibreLunar-v2.0.0.zip")
        self.assertTrue(info["is_zip"])

        # Check when current is same or newer (2.0.0) -> returns None
        info_none = check_for_updates(current_version="v2.0.0")
        self.assertIsNone(info_none)

    def test_setup_dialog_update_consent(self):
        dlg = SetupDialog()
        self.assertTrue(hasattr(dlg, "chk_updates"))
        self.assertTrue(dlg.chk_updates.isChecked())

        # Check localization
        set_language("en_us")
        dlg.retranslate_ui()
        self.assertEqual(dlg.chk_updates.text(), "Automatically check for updates on startup")

        set_language("vi_vn")
        dlg.retranslate_ui()
        self.assertEqual(dlg.chk_updates.text(), "Tự động kiểm tra bản cập nhật khi khởi động")

        set_language("en_us")

    def test_options_dialog_update_controls(self):
        cfg = LauncherConfig.load()
        cfg.check_updates = False
        dlg = OptionsDialog(cfg)

        self.assertTrue(hasattr(dlg, "chk_updates"))
        self.assertTrue(hasattr(dlg, "btn_check_updates"))
        self.assertFalse(dlg.chk_updates.isChecked())

        # Check localization
        set_language("en_us")
        dlg._retranslate_ui()
        self.assertEqual(dlg.chk_updates.text(), "Check for updates on startup")
        self.assertEqual(dlg.btn_check_updates.text(), "Check for Updates")

        set_language("vi_vn")
        dlg._retranslate_ui()
        self.assertEqual(dlg.chk_updates.text(), "Kiểm tra bản cập nhật khi khởi động")
        self.assertEqual(dlg.btn_check_updates.text(), "Kiểm tra cập nhật")

        set_language("en_us")

        # In dev mode (not frozen), clicking manual update check informs user
        with patch("librelunar.ui.options_dialog.is_frozen", return_value=False), \
             patch("librelunar.ui.options_dialog.QMessageBox.information") as mock_info:
            dlg._manual_check_updates()
            mock_info.assert_called_once()

    def test_spawn_game_process_verbose_toggle(self):
        mc_data = _TEMP_PATH / "mock_mc"
        mc_data.mkdir(parents=True, exist_ok=True)
        bat_path = mc_data / "launch.bat"
        bin_dir = _TEMP_PATH / "mock_jre" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "java.exe").touch()
        (bin_dir / "javaw.exe").touch()
        cmd = [str(bin_dir / "java.exe"), "-jar", "game.jar"]

        # 1. Non-verbose on Windows: should switch to javaw.exe if it exists and pass CREATE_NO_WINDOW
        with patch("librelunar.core.launcher.sys.platform", "win32"), \
             patch("librelunar.core.launcher.subprocess.Popen") as mock_popen:
            spawn_game_process(cmd, mc_data, bat_path=bat_path, verbose=False)
            mock_popen.assert_called_once()
            called_cmd = mock_popen.call_args[0][0]
            called_kwargs = mock_popen.call_args[1]
            self.assertTrue(called_cmd[0].endswith("javaw.exe"))
            self.assertEqual(called_kwargs.get("creationflags"), 0x08000000)
            self.assertEqual(called_kwargs.get("cwd"), str(mc_data))

        # 2. Verbose with Windows Terminal available
        with patch("librelunar.core.launcher.find_windows_terminal", return_value="C:/wt/wt.exe"), \
             patch("librelunar.core.launcher.subprocess.Popen") as mock_popen:
            spawn_game_process(cmd, mc_data, bat_path=bat_path, verbose=True)
            mock_popen.assert_called_once()
            called_cmd = mock_popen.call_args[0][0]
            self.assertEqual(called_cmd[0], "C:/wt/wt.exe")
            self.assertIn("cmd.exe", called_cmd)
            self.assertIn(str(bat_path), called_cmd)

        # 3. Verbose without Windows Terminal: should fall back to cmd.exe with CREATE_NEW_CONSOLE
        with patch("librelunar.core.launcher.find_windows_terminal", return_value=None), \
             patch("librelunar.core.launcher.subprocess.Popen") as mock_popen:
            spawn_game_process(cmd, mc_data, bat_path=bat_path, verbose=True)
            mock_popen.assert_called_once()
            called_cmd = mock_popen.call_args[0][0]
            called_kwargs = mock_popen.call_args[1]
            self.assertEqual(called_cmd, ["cmd.exe", "/c", str(bat_path)])
            self.assertEqual(called_kwargs.get("creationflags"), 0x00000010)  # CREATE_NEW_CONSOLE



def tearDownModule():
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.closeAllWindows()
            app.quit()
    except Exception:
        pass


if __name__ == "__main__":
    unittest.main()

