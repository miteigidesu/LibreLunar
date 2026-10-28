"""
Lunar Client download and launch engine for LibreLunar.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from .config import LauncherConfig
from .constants import (
    ASSET_BASE,
    LAUNCHER_VERSION,
    LUNAR_API,
    LUNAR_UA,
    MOJANG_MANIFEST,
    ZERO_HEX32,
    ZERO_UUID,
)
from .downloader import (
    class_entries,
    download_batch,
    download_single_file,
    http_get,
    parse_index,
    safe_extract,
)
from .i18n import t
from .metadata import ssl_context
from .paths import ProfilePaths, account_file_path
from .utils import fake_timestamp, offline_uuid, safe_name, safe_rel


def write_account(username: str, data_dir: Path | None = None, offline: bool = True) -> tuple[str, str]:
    """Write offline Xbox account to .lunarclient/settings/game/accounts.json."""
    uuid_str = offline_uuid(username)
    profile_id = uuid_str.replace("-", "").lower()
    account = {
        "activeAccountLocalId": profile_id,
        "accounts": {
            profile_id: {
                "accessToken": "thisisafaketoken" if offline else "",
                "accessTokenExpiresAt": fake_timestamp() if offline else "",
                "eligibleForMigration": False,
                "hasMultipleProfiles": False,
                "legacy": False,
                "persistent": True,
                "localId": profile_id,
                "refreshToken": "thisisafakerefreshtoken" if offline else "",
                "minecraftProfile": {
                    "id": profile_id,
                    "name": username,
                },
                "remoteId": "0000000000000000",
                "type": "Xbox",
                "username": username,
            }
        }
    }
    path = account_file_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(account, indent=2), "utf-8")
    return uuid_str, profile_id


def fetch_launch_manifest(
    version: str,
    module: str,
    profile_paths: ProfilePaths | None = None,
    branch: str = "master",
) -> dict:
    if profile_paths is None:
        profile_paths = ProfilePaths(version, module)
    mpath = profile_paths.data_dir / "manifests" / f"{safe_name(version)}-{safe_name(module)}.json"
    body = {
        "installation_id": ZERO_UUID,
        "overwolf_muid": ZERO_UUID,
        "os": "win32",
        "os_release": platform.version(),
        "arch": "x64",
        "launcher_version": LAUNCHER_VERSION,
        "version": version,
        "branch": branch,
        "args": [],
        "module": module,
        "canary_preference": "NEUTRAL",
        "profile": {"id": ZERO_UUID, "name": "LibreLunar"},
    }
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "User-Agent": LUNAR_UA,
        "sentry-trace": ZERO_HEX32,
        "X-Installation-Id": ZERO_UUID,
        "X-Overwolf-Muid": ZERO_UUID,
    }
    req = urllib.request.Request(
        LUNAR_API,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    manifest = None
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as r:
            manifest = json.loads(r.read().decode("utf-8"))
        if manifest.get("success"):
            mpath.parent.mkdir(parents=True, exist_ok=True)
            mpath.write_text(json.dumps(manifest, indent=2), "utf-8")
            return manifest
    except Exception:
        pass

    if mpath.exists():
        return json.loads(mpath.read_text("utf-8"))
    if manifest and manifest.get("success"):
        return manifest
    raise RuntimeError(f"Could not load launch manifest for {version} ({module}). Check internet connection.")


def install_natives_zip(zpath: Path, key: str, natives_dir: Path, exclude: tuple = ()):
    """Extract native dlls into profile's natives folder with completeness verification."""
    natives_dir.mkdir(parents=True, exist_ok=True)
    marker = natives_dir / ".installed.json"
    state = json.loads(marker.read_text("utf-8")) if marker.exists() else {}
    if state.get(str(key)) == key:
        with zipfile.ZipFile(zpath) as z:
            missing = False
            for member in z.namelist():
                if any(member.startswith(ex) for ex in exclude) or member.endswith("/"):
                    continue
                if not (natives_dir / member).exists():
                    missing = True
                    break
            if not missing:
                return

    with zipfile.ZipFile(zpath) as z:
        safe_extract(z, natives_dir, exclude=exclude)
    state[str(key)] = key
    marker.write_text(json.dumps(state, indent=1), "utf-8")


def materialize(src: Path, dest: Path):
    """Link or copy cached artifact to view directory."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            if dest.stat().st_size == src.stat().st_size:
                return
        except OSError:
            pass
        dest.unlink()
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def sync_lunar_artifacts(manifest: dict, profile_paths: ProfilePaths, progress_cb=None):
    """Synchronize Lunar Client core jar files, external jsons, and native binaries."""
    arts = manifest["launchTypeData"]["artifacts"]
    profile_paths.artifact_view.mkdir(parents=True, exist_ok=True)
    jobs = []
    artifacts_cache = profile_paths.data_dir / "artifacts" / "cache"

    for a in arts:
        if not a.get("url") or not a.get("sha1"):
            continue
        cache_dir = artifacts_cache / a["sha1"]
        if a.get("type") == "NATIVES":
            dest = cache_dir / "native.zip"
        else:
            dest = cache_dir / safe_rel(a.get("name", "artifact.jar"))
        jobs.append({
            "url": a["url"],
            "dest": dest,
            "sha1": a["sha1"],
            "size": a.get("size", 0),
            "name": a.get("name", dest.name),
        })

    def on_batch_progress(done, total, name):
        if progress_cb and total > 0:
            pct = int(min(1.0, done / total) * 100)
            progress_cb(pct, f"{name} ({pct}%)")

    download_batch(jobs, max_workers=6, progress_callback=on_batch_progress)

    for a in arts:
        if not a.get("sha1"):
            continue
        cache_dir = artifacts_cache / a["sha1"]
        if a.get("type") == "NATIVES":
            install_natives_zip(cache_dir / "native.zip", a["sha1"], profile_paths.natives)
        else:
            dest = cache_dir / safe_rel(a.get("name", "artifact.jar"))
            materialize(dest, profile_paths.artifact_view / safe_rel(a.get("name", "artifact.jar")))

    classpath = [profile_paths.artifact_view / safe_rel(a["name"]) for a in arts if a.get("type") == "CLASS_PATH"]
    external = [a["name"] for a in arts if a.get("type") == "EXTERNAL_FILE"]
    return classpath, external


def ensure_jre(jre: dict, profile_paths: ProfilePaths, progress_cb=None) -> Path:
    """Download and unpack Java runtime environment if not already present."""
    jre_dir = profile_paths.data_dir / "artifacts" / "jre"
    folder = jre_dir / jre["folderChecksum"]
    exe = folder.joinpath(*jre["executablePathInArchive"])
    if not exe.exists():
        d = jre["download"]
        zpath = jre_dir / f"{jre['folderChecksum']}.zip"

        def on_jre_progress(downloaded, total, name):
            if progress_cb:
                if total > 0:
                    pct = int(min(1.0, downloaded / total) * 100)
                    progress_cb(pct, t("progress_downloading_jre_pct", pct=pct))
                else:
                    progress_cb(-1, t("progress_downloading_jre_mb", mb=downloaded // (1024*1024)))

        download_single_file(
            d["url"],
            zpath,
            fallback=d.get("fallbackUrl"),
            progress_callback=on_jre_progress,
            display_name="Java Runtime",
        )
        if progress_cb:
            progress_cb(-1, t("progress_extracting_jre"))
        with zipfile.ZipFile(zpath) as z:
            safe_extract(z, folder)

    console = exe.with_name("java.exe")
    return console if console.exists() else exe


def sync_ui_and_textures(manifest: dict, profile_paths: ProfilePaths, progress_cb=None) -> Path | None:
    """Sync custom UI html/css bundles and textures."""
    def sync_index_files(label: str, index_url: str, index_sha1: str, base_url: str, dest_root: Path):
        dest_root = Path(dest_root)
        dest_root.mkdir(parents=True, exist_ok=True)
        marker = dest_root / ".synced"
        if marker.exists() and marker.read_text("utf-8") == index_sha1:
            return
        if progress_cb:
            progress_cb(-1, t("progress_fetching_index", label=label))
        raw = http_get(index_url)
        (dest_root / ".index").write_bytes(raw)
        entries = parse_index(raw)
        if not entries:
            return

        jobs = []
        for rel_path, sha1 in entries:
            jobs.append({
                "url": base_url + sha1,
                "dest": dest_root / safe_rel(rel_path),
                "sha1": sha1,
                "size": 0,
                "name": rel_path,
            })

        count = [0]
        total_items = len(jobs)

        def on_batch(done, total, name):
            count[0] += 1
            if progress_cb:
                pct = int(min(1.0, count[0] / total_items) * 100)
                progress_cb(pct, f"{label}: {name}")

        download_batch(jobs, max_workers=8, progress_callback=on_batch)
        marker.write_text(index_sha1, "utf-8")

    textures = manifest.get("textures")
    if textures and textures.get("indexUrl"):
        sync_index_files(
            "Textures",
            textures["indexUrl"],
            textures["indexSha1"],
            textures["baseUrl"],
            profile_paths.lc_home / "textures",
        )

    ui = manifest.get("ui")
    ui_dir = None
    if ui:
        ui_dir = profile_paths.lc_home / "ui" / ui["sourceSha1"]
        if not (ui_dir / ".source_ok").exists():
            zpath = profile_paths.data_dir / "artifacts" / "cache" / f"ui-{ui['sourceSha1']}.zip"
            download_single_file(
                ui["sourceUrl"],
                zpath,
                sha1=ui["sourceSha1"],
                display_name="UI bundle",
                progress_callback=lambda d, t, n: progress_cb(int(d / t * 100) if t else -1, f"UI: {n}") if progress_cb else None,
            )
            with zipfile.ZipFile(zpath) as z:
                safe_extract(z, ui_dir)
            (ui_dir / ".source_ok").write_text("1", "utf-8")
        a = ui.get("assets")
        if a and a.get("indexUrl"):
            sync_index_files("UI assets", a["indexUrl"], a["indexSha1"], a["baseUrl"], ui_dir / "assets")

    return ui_dir


def rules_ok(rules: list | None) -> bool:
    if not rules:
        return True
    allowed = False
    for r in rules:
        action = r.get("action")
        os_info = r.get("os", {})
        os_name = os_info.get("name")
        matches = True
        if os_name and os_name != "windows":
            matches = False
        if matches:
            allowed = (action == "allow")
    return allowed


def get_mojang_version(version: str, profile_paths: ProfilePaths, progress_cb=None) -> dict:
    """Fetch vanilla Minecraft version manifest."""
    jpath = profile_paths.mc_data / "versions" / version / f"{version}.json"
    if jpath.exists():
        try:
            return json.loads(jpath.read_text("utf-8"))
        except Exception:
            pass

    if progress_cb:
        progress_cb(-1, t("progress_fetching_mc_manifest", version=version))
    try:
        raw = http_get(MOJANG_MANIFEST)
        manifest = json.loads(raw.decode("utf-8"))
        entry = next((v for v in manifest["versions"] if v["id"] == version), None)
        if not entry:
            raise ValueError(f"Version {version} not found in Mojang manifest")
        vraw = http_get(entry["url"])
        jpath.parent.mkdir(parents=True, exist_ok=True)
        jpath.write_bytes(vraw)
        return json.loads(vraw.decode("utf-8"))
    except Exception:
        if jpath.exists():
            return json.loads(jpath.read_text("utf-8"))
        raise


def prepare_libraries(vjson: dict, lunar_classes: set, profile_paths: ProfilePaths, progress_cb=None) -> list[str]:
    """Download and resolve Mojang libraries into the unified data/libraries folder."""
    jobs = []
    libraries_dir = profile_paths.libraries
    for lib in vjson.get("libraries", []):
        if not rules_ok(lib.get("rules")):
            continue
        name = lib["name"]
        dl = lib.get("downloads", {})
        if dl.get("artifact"):
            art = dl["artifact"]
            path = libraries_dir / safe_rel(art.get("path") or urlparse(art["url"]).path.lstrip("/"))
            jobs.append({"url": art["url"], "dest": path, "sha1": art.get("sha1"), "size": art.get("size", 0), "name": name, "kind": "cp"})
        nat = lib.get("natives", {}).get("windows")
        if nat:
            art = dl.get("classifiers", {}).get(nat.replace("${arch}", "64"))
            if art:
                path = libraries_dir / safe_rel(art.get("path") or urlparse(art["url"]).path.lstrip("/"))
                jobs.append({"url": art["url"], "dest": path, "sha1": art.get("sha1"), "size": art.get("size", 0), "name": name, "kind": "native"})

    total_bytes = sum(j.get("size", 0) for j in jobs)

    def on_batch(done, total, name):
        if progress_cb and total_bytes > 0:
            pct = int(min(1.0, done / total_bytes) * 100)
            progress_cb(pct, t("progress_libraries", name=name, pct=pct))

    download_batch(jobs, max_workers=8, progress_callback=on_batch)

    classpath = []
    for j in jobs:
        p = Path(j["dest"])
        if j["kind"] == "native":
            install_natives_zip(p, j.get("sha1", ""), profile_paths.natives, exclude=("META-INF/",))
            continue
        cls = class_entries(p)
        inter = cls & lunar_classes
        if cls and inter and (len(inter) / len(cls) >= 0.5):
            continue
        classpath.append(str(p))

    return classpath


def download_client_and_assets(vjson: dict, version: str, asset_index_data, profile_paths: ProfilePaths, progress_cb=None):
    """Download client jar and assets into unified storage."""
    client = vjson.get("downloads", {}).get("client")
    if client:
        client_path = profile_paths.mc_data / "versions" / version / f"{version}.jar"
        download_single_file(
            client["url"],
            client_path,
            sha1=client.get("sha1"),
            size=client.get("size"),
            display_name=f"{version}.jar",
            progress_callback=lambda d, t, n: progress_cb(int(d / t * 100) if t else -1, f"Client: {n}") if progress_cb else None,
        )

    assets = profile_paths.assets
    asset_index = asset_index_data or vjson.get("assetIndex")
    if asset_index and isinstance(asset_index, dict) and asset_index.get("url"):
        asset_id = asset_index["id"]
        idx = assets / "indexes" / f"{asset_id}.json"
        download_single_file(
            asset_index["url"],
            idx,
            sha1=asset_index.get("sha1"),
            display_name=f"asset_index_{asset_id}.json",
            progress_callback=lambda d, t, n: progress_cb(-1, f"Asset index: {n}") if progress_cb else None,
        )
        objects = json.loads(idx.read_text("utf-8"))["objects"]
    elif "objects" in vjson:
        asset_id = asset_index.get("id") if isinstance(asset_index, dict) else (vjson.get("id") or version)
        idx = assets / "indexes" / f"{asset_id}.json"
        idx.parent.mkdir(parents=True, exist_ok=True)
        if not idx.exists():
            idx.write_text(json.dumps(vjson), "utf-8")
        objects = vjson["objects"]
    else:
        raise ValueError(f"Unsupported Mojang asset manifest format for {version}")

    infos = list(objects.values())
    total_bytes = sum(info.get("size", 0) for info in infos)
    jobs = []
    for info in infos:
        h = info["hash"]
        prefix = h[:2]
        dest = assets / "objects" / prefix / h
        jobs.append({
            "url": f"{ASSET_BASE}/{prefix}/{h}",
            "dest": dest,
            "sha1": h,
            "size": info.get("size", 0),
            "name": h[:8],
        })

    def on_asset_batch(done, total, name):
        if progress_cb and total_bytes > 0:
            pct = int(min(1.0, done / total_bytes) * 100)
            progress_cb(pct, t("progress_assets", name=name, pct=pct))

    download_batch(jobs, max_workers=8, progress_callback=on_asset_batch)
    return assets, asset_id


def install_modpack(mp: dict, profile_paths: ProfilePaths, progress_cb=None):
    """Download and extract Modrinth modpack."""
    modpack_dir = profile_paths.data_dir / "artifacts" / "modpack"
    modpack_dir.mkdir(parents=True, exist_ok=True)
    hash_val = mp.get("hash", "")
    pack = modpack_dir / f"{hash_val}.mrpack"
    marker = profile_paths.profile_data / ".modpack_installed"
    if marker.exists() and hash_val and marker.read_text("utf-8") == hash_val:
        return

    mrpack_url = mp.get("mrpackUrl") or mp.get("url")
    if not mrpack_url:
        return

    download_single_file(
        mrpack_url,
        pack,
        sha1=hash_val,
        display_name="Modpack bundle",
        progress_callback=lambda d, t, n: progress_cb(int(d / t * 100) if t else -1, f"Modpack: {n}") if progress_cb else None,
    )
    with zipfile.ZipFile(pack) as z:
        index = json.loads(z.read("modrinth.index.json"))
        files = [f for f in index.get("files", []) if f.get("env", {}).get("client") != "unsupported"]
        jobs = []
        for f in files:
            downloads = f.get("downloads", [])
            if not downloads:
                continue
            jobs.append({
                "url": downloads[0],
                "dest": profile_paths.profile_data / safe_rel(f["path"]),
                "sha1": f.get("hashes", {}).get("sha1"),
                "size": f.get("fileSize", f.get("size", 0)),
                "name": Path(f["path"]).name,
            })
        download_batch(jobs, max_workers=8, progress_callback=lambda d, t, n: progress_cb(int(d / t * 100) if t else -1, f"Modpack: {n}") if progress_cb else None)
        for prefix in ("overrides/", "client-overrides/"):
            safe_extract(z, profile_paths.profile_data, strip=prefix)
    if hash_val:
        marker.write_text(hash_val, "utf-8")


def build_command(
    java: Path,
    manifest: dict,
    config: LauncherConfig,
    lunar_cp: list,
    libs_cp: list,
    external: list,
    assets_dir: Path,
    asset_id: str,
    ui_dir: Path | None,
    profile_paths: ProfilePaths,
) -> list[str]:
    """Construct full java command-line arguments for launching."""
    ltd = manifest["launchTypeData"]
    artifacts = ltd.get("artifacts", [])
    modern = any(a.get("name", "").startswith("modern-") for a in artifacts)
    if not modern and not any(a.get("name", "").startswith("legacy-") for a in artifacts):
        modern = not (config.version.startswith("1.7") or config.version.startswith("1.8") or config.version.startswith("1.12"))
    jvm_classpath = lunar_cp + libs_cp if modern else lunar_cp

    cmd = [str(java)]
    cmd += manifest.get("jre", {}).get("extraArguments", [])
    if modern:
        cmd += [
            "--enable-native-access=ALL-UNNAMED",
            "--add-exports", "java.base/jdk.internal.misc=ALL-UNNAMED",
            "-XX:StackShadowPages=32",
        ]
    mods_dir = profile_paths.mods_dir
    cmd += [
        f"-Xmx{config.memory}m",
        f"-Duser.home={profile_paths.home}",
        f"-Dichor.fabric.localModPath={mods_dir}",
        f"-Dichor.fabric.profileModPath={mods_dir}",
        f"-Dfabric.modsFolder={mods_dir}",
        f"-Djava.library.path={profile_paths.natives}",
    ]
    if config.module == "fabric":
        cmd.append("-Dichor.fabricLoaderVersion=0.19.5")

    cmd += [
        f"-Dichor.logsFile={profile_paths.logs_dir / 'ichor-boot.log'}",
        "-Dichor.usingIsolatedProfiles=true",
        "-XX:+DisableAttachMechanism",
        "-XX:-CreateCoredumpOnCrash",
        "-cp", os.pathsep.join([str(p) for p in jvm_classpath]),
        ltd.get("mainClass", "com.moonsworth.lunar.genesis.Genesis"),
    ]
    cmd += [
        "--version", config.version,
        "--launcherVersion", LAUNCHER_VERSION,
        "--installationId", ZERO_UUID,
        "--overwolfMuid", ZERO_UUID,
        "--sentryTraceId", ZERO_HEX32,
        "--launchId", ZERO_UUID,
        "--canaryToken", manifest.get("canaryToken", "no-canary"),
        "--username", config.username,
        "--uuid", config.uuid,
        "--xuid", config.xuid or "0000000000000000",
        "--accessToken", "0",
        "--userProperties", "{}",
        "--assetIndex", str(asset_id),
        "--gameDir", str(profile_paths.mc_data),
        "--assetsDir", str(assets_dir),
        "--texturesDir", str(profile_paths.lc_home / "textures"),
        "--jitDir", str(profile_paths.lc_home / "jit"),
        "--webosrDir", str(profile_paths.natives),
        "--workingDirectory", ".",
        "--classpathDir", str(profile_paths.artifact_view),
        "--width", str(config.width),
        "--height", str(config.height),
        "--ichorClassPath", ",".join(p.name for p in lunar_cp),
    ]
    if config.fullscreen:
        cmd.append("--fullscreen")
    if ui_dir:
        cmd += ["--uiDir", str(ui_dir)]
    if external:
        cmd += ["--ichorExternalFiles", ",".join(external)]

    return cmd


def find_windows_terminal() -> str | None:
    """Detect Windows Terminal (wt.exe) in PATH or standard WindowsApps location."""
    wt = shutil.which("wt.exe") or shutil.which("wt")
    if wt:
        return wt
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "Microsoft" / "WindowsApps" / "wt.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def spawn_game_process(cmd: list[str], mc_data: Path, bat_path: Path | None = None, verbose: bool = False) -> subprocess.Popen:
    """
    Spawn the game process.
    If verbose is True, spawns in Windows Terminal (or Command Prompt if WT missing) via bat_path.
    Executing via batch file prevents Windows Terminal from misinterpreting classpath semicolons (;)
    as tab delimiters.
    """
    if verbose and bat_path:
        wt_path = find_windows_terminal()
        if wt_path:
            try:
                terminal_cmd = [
                    wt_path,
                    "--title", "LibreLunar - Verbose Console",
                    "-d", str(mc_data),
                    "cmd.exe", "/c", str(bat_path),
                ]
                return subprocess.Popen(terminal_cmd, cwd=str(mc_data))
            except OSError:
                pass

        return subprocess.Popen(
            ["cmd.exe", "/c", str(bat_path)],
            cwd=str(mc_data),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    else:
        actual_cmd = list(cmd)
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            if actual_cmd:
                exe_p = Path(actual_cmd[0])
                javaw = exe_p.with_name("javaw.exe")
                if javaw.exists():
                    actual_cmd[0] = str(javaw)
        return subprocess.Popen(actual_cmd, cwd=str(mc_data), creationflags=creationflags)


