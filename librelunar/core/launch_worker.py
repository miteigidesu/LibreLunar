"""
QThread worker for running the launch sequence asynchronously without blocking Qt GUI.
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path
from PySide6.QtCore import QObject, QThread, Signal

from .config import LauncherConfig
from .downloader import class_entries
from .i18n import t
from .launcher import (
    build_command,
    download_client_and_assets,
    ensure_jre,
    fetch_launch_manifest,
    get_mojang_version,
    install_modpack,
    prepare_libraries,
    spawn_game_process,
    sync_lunar_artifacts,
    sync_ui_and_textures,
    write_account,
)
from .paths import ProfilePaths
from .utils import is_java_running


class LaunchWorker(QThread):
    sig_stage = Signal(int, int, str)       # current, total, stage_name
    sig_detail = Signal(str)               # detail text (status text 2)
    sig_progress = Signal(int)             # 0 to 100, or -1 for indeterminate
    sig_process_spawned = Signal()         # emitted when game process starts
    sig_game_exited = Signal(int)          # emitted when game instance closes
    sig_finished = Signal(bool, str)       # (success, error_msg)

    def __init__(self, config: LauncherConfig, subversion_info: dict, parent: QObject | None = None):
        super().__init__(parent)
        self.config = config
        self.subversion_info = subversion_info

    def run(self):
        try:
            data_dir = self.config.resolved_data_dir
            profile_paths = ProfilePaths(self.config.version, self.config.module, data_dir=data_dir)
            profile_paths.ensure_directories()

            # Offline account configuration
            uuid_str, _ = write_account(self.config.username, data_dir=data_dir, offline=True)
            self.config.uuid = uuid_str
            self.config.save()

            total_stages = 5

            # Stage 1: Manifest
            self.sig_stage.emit(1, total_stages, t("stage_manifest"))
            self.sig_detail.emit(t("detail_manifest"))
            self.sig_progress.emit(-1)

            manifest = fetch_launch_manifest(self.config.version, self.config.module, profile_paths)
            if not manifest.get("success"):
                raise RuntimeError(f"Lunar API refused request: {manifest.get('error', 'unknown error')}")

            if manifest.get("baseModpack"):
                total_stages = 6
                self.sig_stage.emit(1, total_stages, t("stage_manifest"))

            # Stage 2: Lunar Artifacts
            self.sig_stage.emit(2, total_stages, t("stage_artifacts"))
            self.sig_detail.emit(t("detail_artifacts"))
            self.sig_progress.emit(0)

            def on_art_progress(pct, detail):
                self.sig_progress.emit(pct)
                self.sig_detail.emit(detail)

            lunar_cp, external = sync_lunar_artifacts(manifest, profile_paths, progress_cb=on_art_progress)

            # Stage 3: Java Runtime
            self.sig_stage.emit(3, total_stages, t("stage_jre"))
            self.sig_detail.emit(t("detail_jre"))
            self.sig_progress.emit(-1)

            def on_jre_progress(pct, detail):
                self.sig_progress.emit(pct)
                self.sig_detail.emit(detail)

            java_exe = ensure_jre(manifest["jre"], profile_paths, progress_cb=on_jre_progress)

            # Stage 4: Textures and UI
            self.sig_stage.emit(4, total_stages, t("stage_textures_ui"))
            self.sig_detail.emit(t("detail_textures_ui"))
            self.sig_progress.emit(0)

            def on_ui_progress(pct, detail):
                self.sig_progress.emit(pct)
                self.sig_detail.emit(detail)

            ui_dir = sync_ui_and_textures(manifest, profile_paths, progress_cb=on_ui_progress)

            # Stage 5: Mojang libraries and assets
            self.sig_stage.emit(5, total_stages, t("stage_mojang"))
            self.sig_detail.emit(t("detail_mojang"))
            self.sig_progress.emit(-1)

            def on_mojang_progress(pct, detail):
                self.sig_progress.emit(pct)
                self.sig_detail.emit(detail)

            vjson = get_mojang_version(self.config.version, profile_paths, progress_cb=on_mojang_progress)

            lunar_classes = set()
            for jar in lunar_cp:
                lunar_classes |= class_entries(jar)

            libs_cp = prepare_libraries(vjson, lunar_classes, profile_paths, progress_cb=on_mojang_progress)

            assets_dir, asset_id = download_client_and_assets(
                vjson,
                self.config.version,
                self.subversion_info.get("assets"),
                profile_paths,
                progress_cb=on_mojang_progress,
            )

            # Stage 6: Modpack if present
            if manifest.get("baseModpack"):
                self.sig_stage.emit(6, total_stages, t("stage_modpack"))
                self.sig_detail.emit(t("detail_modpack"))
                self.sig_progress.emit(0)

                def on_mp_progress(pct, detail):
                    self.sig_progress.emit(pct)
                    self.sig_detail.emit(detail)

                install_modpack(manifest["baseModpack"], profile_paths, progress_cb=on_mp_progress)

            # Build command and launch
            self.sig_detail.emit(t("detail_prep_params"))
            self.sig_progress.emit(100)

            cmd = build_command(
                java_exe,
                manifest,
                self.config,
                lunar_cp,
                libs_cp,
                external,
                assets_dir,
                asset_id,
                ui_dir,
                profile_paths,
            )

            if sys.platform == "win32" and cmd:
                exe_p = Path(cmd[0])
                if self.config.verbose:
                    console_exe = exe_p.with_name("java.exe")
                    if console_exe.exists():
                        cmd[0] = str(console_exe)
                else:
                    javaw = exe_p.with_name("javaw.exe")
                    if javaw.exists():
                        cmd[0] = str(javaw)

            # Clean up jfr if present
            shutil.rmtree(profile_paths.mc_data / "jfr", ignore_errors=True)

            lock_file = profile_paths.profile_data / ".game_running"
            lock_file.write_text("running", encoding="utf-8")

            # Create launch.bat in profile directory to ensure clean execution and
            # prevent Windows Terminal from splitting on classpath semicolons
            bat_path = profile_paths.profile_data / "launch.bat"
            cmd_line = subprocess.list2cmdline(cmd)
            bat_content = (
                "@echo off\n"
                f'cd /d "{profile_paths.mc_data}"\n'
                f"{cmd_line}\n"
                f'if exist "{lock_file}" del "{lock_file}"\n'
            )
            bat_path.write_text(bat_content, encoding="utf-8")

            self.sig_detail.emit(t("detail_spawn_game"))
            proc = spawn_game_process(cmd, profile_paths.mc_data, bat_path=bat_path, verbose=self.config.verbose)

            self.sig_process_spawned.emit()
            self.sig_finished.emit(True, "")

            # Wait for game instance to close, then notify launcher to spawn back
            if self.config.verbose:
                # Give java.exe a moment to initialize and launch
                time.sleep(2.0)
                while lock_file.exists():
                    if not is_java_running():
                        break
                    time.sleep(0.5)
                if lock_file.exists():
                    try:
                        lock_file.unlink(missing_ok=True)
                    except OSError:
                        pass
            else:
                proc.wait()
                if lock_file.exists():
                    try:
                        lock_file.unlink(missing_ok=True)
                    except OSError:
                        pass

            self.sig_game_exited.emit(0)

        except Exception as e:
            self.sig_finished.emit(False, str(e))

