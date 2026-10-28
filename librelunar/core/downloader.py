"""
Downloader and asset synchronization utilities with thread-safe progress reporting.
"""
import json
import os
import re
import shutil
import threading
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from .constants import HEX40, LUNAR_UA
from .metadata import ssl_context
from .utils import sha1_of, sha256_of, verify_file_hash


def ua_for(url: str) -> str:
    return LUNAR_UA if "lunarclient" in urlparse(url).netloc else "LibreLunar/1.0"


def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua_for(url)})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:
        return r.read()


def safe_extract(zf: zipfile.ZipFile, dest: Path, exclude: tuple = (), strip: str = ""):
    dest = Path(dest).resolve()
    for m in zf.infolist():
        if m.is_dir():
            continue
        name = m.filename
        if strip:
            if not name.startswith(strip):
                continue
            name = name[len(strip):]
        if not name or any(name.startswith(e) for e in exclude):
            continue
        target = (dest / name).resolve()
        if dest not in target.parents:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zf.open(m) as s, open(target, "wb") as t:
                shutil.copyfileobj(s, t)
        except PermissionError:
            pass


def class_entries(jar: Path) -> set[str]:
    try:
        with zipfile.ZipFile(jar) as z:
            return {
                n for n in z.namelist()
                if n.endswith(".class") and not n.startswith("META-INF/") and not n.endswith("module-info.class")
            }
    except Exception:
        return set()


def parse_index(raw: bytes) -> list[tuple[str, str]]:
    """Parse texture or UI asset index to [(relative_path, sha1)]."""
    out = []
    try:
        obj = json.loads(raw)
    except ValueError:
        for line in raw.decode("utf-8", "replace").splitlines():
            toks = [t for t in re.split(r"[\s,:=]+", line.strip()) if t]
            h = [t for t in toks if HEX40.match(t)]
            p = [t for t in toks if not HEX40.match(t)]
            if h and p:
                out.append((p[0], h[0]))
        return out

    def walk(o, key=None):
        if isinstance(o, dict):
            h = next((o[k] for k in ("hash", "sha1", "sha", "checksum")
                      if isinstance(o.get(k), str) and HEX40.match(o[k])), None)
            p = next((o[k] for k in ("path", "name", "file") if isinstance(o.get(k), str)), None) or key
            if h and p:
                out.append((p, h))
                return
            for k, v in o.items():
                if isinstance(v, str) and HEX40.match(v):
                    out.append((k, v))
                else:
                    walk(v, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, key)

    walk(obj)
    return out


def download_single_file(
    url: str,
    dest: Path,
    sha1: str | None = None,
    size: int | None = None,
    fallback: str | None = None,
    progress_callback=None,
    display_name: str = "",
) -> bool:
    """Download single file with cache verification and chunked progress."""
    dest = Path(dest)
    display_name = display_name or dest.name

    if dest.is_file():
        if sha1:
            if verify_file_hash(dest, sha1):
                if progress_callback and size:
                    progress_callback(size, size, display_name)
                return False
        elif size is not None:
            if dest.stat().st_size == size:
                if progress_callback:
                    progress_callback(size, size, display_name)
                return False
        else:
            return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    urls = [url] + ([fallback] if fallback else [])
    last_err = None

    for u in urls:
        for attempt in range(3):
            tmp = dest.with_name(dest.name + ".part")
            try:
                req = urllib.request.Request(u, headers={"User-Agent": ua_for(u)})
                with urllib.request.urlopen(req, timeout=60, context=ssl_context()) as r, open(tmp, "wb") as f:
                    downloaded = 0
                    total = size or int(r.headers.get("Content-Length", 0))
                    if progress_callback:
                        progress_callback(downloaded, total, display_name)
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total, display_name)

                if sha1 and not verify_file_hash(tmp, sha1):
                    hash_name = "SHA-256" if len(sha1.strip()) == 64 else "SHA-1"
                    raise IOError(f"{hash_name} mismatch")
                os.replace(tmp, dest)
                return True
            except Exception as e:
                last_err = e
                time.sleep(1 + attempt)

    raise RuntimeError(f"Download failed: {url} ({last_err})")


class BatchProgressTracker:
    def __init__(self, total_bytes: int, callback):
        self.total_bytes = total_bytes
        self.done_bytes = 0
        self.callback = callback
        self.lock = threading.Lock()

    def advance(self, amount: int, name: str):
        with self.lock:
            self.done_bytes += amount
            if self.callback:
                self.callback(self.done_bytes, self.total_bytes, name)

    def status(self, name: str):
        with self.lock:
            if self.callback:
                self.callback(self.done_bytes, self.total_bytes, name)


def download_batch(jobs: list[dict], max_workers: int = 8, progress_callback=None):
    """
    Downloads a list of jobs in parallel.
    Each job is a dict: {url, dest, sha1, size, fallback, name}
    """
    total_bytes = sum(j.get("size", 0) for j in jobs)
    tracker = BatchProgressTracker(total_bytes, progress_callback)

    def worker(job: dict):
        dest = Path(job["dest"])
        name = job.get("name") or dest.name
        sha1 = job.get("sha1")
        size = job.get("size")
        url = job["url"]
        fallback = job.get("fallback")

        # Fast cache hit check
        if dest.is_file():
            if sha1:
                if verify_file_hash(dest, sha1):
                    if size:
                        tracker.advance(size, name)
                    return False
            elif size is not None:
                if dest.stat().st_size == size:
                    tracker.advance(size, name)
                    return False

        tracker.status(name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        urls = [url] + ([fallback] if fallback else [])
        last_err = None

        for u in urls:
            for attempt in range(3):
                tmp = dest.with_name(dest.name + f".{threading.get_ident()}.part")
                try:
                    req = urllib.request.Request(u, headers={"User-Agent": ua_for(u)})
                    with urllib.request.urlopen(req, timeout=60, context=ssl_context()) as r, open(tmp, "wb") as f:
                        while True:
                            chunk = r.read(1 << 20)
                            if not chunk:
                                break
                            f.write(chunk)
                            tracker.advance(len(chunk), name)
                    if sha1 and not verify_file_hash(tmp, sha1):
                        hash_name = "SHA-256" if len(sha1.strip()) == 64 else "SHA-1"
                        raise IOError(f"{hash_name} mismatch")
                    os.replace(tmp, dest)
                    return True
                except Exception as e:
                    last_err = e
                    time.sleep(1 + attempt)

        raise RuntimeError(f"Failed to download {name}: {last_err}")

    with ThreadPoolExecutor(max_workers) as executor:
        list(executor.map(worker, jobs))
