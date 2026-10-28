"""
Constants used across LibreLunar.
"""
import re

APP_NAME = "LibreLunar"
LAUNCHER_VERSION = "3.7.25-ow"
LUNAR_API = "https://api.lunarclientprod.com/launcher/launch"
VERSION_METADATA_API = "https://api.lunarclientprod.com/launcher/metadata/versions/lunar"
MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ASSET_BASE = "https://resources.download.minecraft.net"
LUNAR_UA = f"Lunar Client Launcher v{LAUNCHER_VERSION}"
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
ZERO_HEX32 = "0" * 32
HEX40 = re.compile(r"^[0-9a-f]{40}$", re.I)

