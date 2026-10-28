"""
Resolve Calendar Version (YYYY.MM.DD.run_number) for LibreLunar.
Format: 2026.10.28.1
Where run_number counts the runs on that day.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path


def get_calendar_date() -> tuple[str, str, int, int, int]:
    now = datetime.datetime.now(datetime.timezone.utc)
    date_str = now.strftime("%Y.%m.%d")
    iso_date = now.strftime("%Y-%m-%d")
    return date_str, iso_date, now.year, now.month, now.day


def get_daily_run_number(date_str: str, iso_date: str) -> int:
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    daily_run = 0

    # 1. Query GitHub Actions workflow runs API if running in CI
    if repo and token:
        try:
            url = f"https://api.github.com/repos/{repo}/actions/workflows/build.yml/runs?created={iso_date}&per_page=100"
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "GitHub-Actions-CalVer",
                    "Authorization": f"Bearer {token}",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                runs = data.get("workflow_runs", [])
                today_runs = [r for r in runs if r.get("created_at", "").startswith(iso_date)]
                if today_runs:
                    daily_run = len(today_runs)
        except Exception as e:
            print(f"Notice: GitHub Actions API query ({e})", file=sys.stderr)

    # 2. Query git tags for today to ensure uniqueness and prevent collision
    tag_max = 0
    try:
        subprocess.run(["git", "fetch", "--tags", "--force"], capture_output=True)
        out = subprocess.check_output(
            ["git", "tag", "-l", f"{date_str}.*", f"v{date_str}.*"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            line = line.strip().lstrip("v")
            m = re.match(rf"^{re.escape(date_str)}\.(\d+)$", line)
            if m:
                tag_max = max(tag_max, int(m.group(1)))
    except Exception:
        pass

    # If GitHub API gave a run count, use it unless existing tags already reached or exceeded it
    if daily_run > tag_max:
        return daily_run
    return tag_max + 1


def update_version_info_txt(version: str, y: int, m: int, d: int, run_num: int):
    path = Path("version_info.txt")
    if not path.is_file():
        return
    content = f"""# UTF-8
#
# Version Information for LibreLunar Windows Executable
#
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({y}, {m}, {d}, {run_num}),
    prodvers=({y}, {m}, {d}, {run_num}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'LibreLunar'),
        StringStruct('FileDescription', 'LibreLunar Client Launcher'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'LibreLunar'),
        StringStruct('LegalCopyright', 'Copyright (C) {y} LibreLunar Contributors'),
        StringStruct('OriginalFilename', 'LibreLunar.exe'),
        StringStruct('ProductName', 'LibreLunar'),
        StringStruct('ProductVersion', 'v{version}')])
      ]), 
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    path.write_text(content, encoding="utf-8")


def main():
    date_str, iso_date, y, m, d = get_calendar_date()
    run_num = get_daily_run_number(date_str, iso_date)
    version = f"{date_str}.{run_num}"

    print(f"Resolved Calendar Version: {version}")

    # 1. Bake into librelunar/_version.py
    vfile = Path("librelunar") / "_version.py"
    vfile.parent.mkdir(parents=True, exist_ok=True)
    vfile.write_text(f'__version__ = "{version}"\n', encoding="utf-8")

    # 2. Update version_info.txt
    update_version_info_txt(version, y, m, d, run_num)

    # 3. Export to GITHUB_ENV if running in CI
    gh_env = os.environ.get("GITHUB_ENV")
    if gh_env:
        with open(gh_env, "a", encoding="utf-8") as f:
            f.write(f"APP_VERSION={version}\n")

    return version


if __name__ == "__main__":
    main()

