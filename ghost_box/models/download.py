"""Download one pinned preset, without a Hub cache or model runtime."""

import hashlib
import json
from pathlib import Path
import shutil
from urllib.request import urlopen

MANIFEST = json.loads((Path(__file__).parent / "data" / "model_manifest.json").read_text())
PRESET = MANIFEST["repo"]
REVISION = MANIFEST["revision"]
TOTAL_BYTES = sum(item["size"] for item in MANIFEST["files"])


class DownloadCancelled(Exception):
    pass


def ready(folder):
    marker = folder / "download-complete.json"
    try:
        return (json.loads(marker.read_text()) == MANIFEST
                and all((folder / item["name"]).stat().st_size == item["size"]
                        for item in MANIFEST["files"]))
    except (OSError, ValueError):
        return False


def check_cancel(cancelled):
    if cancelled():
        raise DownloadCancelled()


def digest_file(path, item, cancelled):
    digest = hashlib.sha256() if item["algorithm"] == "sha256" else hashlib.sha1()
    if item["algorithm"] == "git-sha1":
        digest.update(f"blob {item['size']}\0".encode())
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            check_cancel(cancelled)
            digest.update(chunk)
    return digest.hexdigest()


def download(folder, progress, cancelled):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "download-complete.json").unlink(missing_ok=True)
    completed = 0
    for item in MANIFEST["files"]:
        check_cancel(cancelled)
        path = folder / item["name"]
        progress(f"Checking {item['name']}…")
        if (path.is_file() and path.stat().st_size == item["size"]
                and digest_file(path, item, cancelled) == item["digest"]):
            completed += item["size"]
            continue
        if shutil.disk_usage(folder).free < item["size"] + 64 * 1024 * 1024:
            raise OSError("Not enough free disk space")
        partial = path.with_name(path.name + ".part")
        try:
            url = f"https://huggingface.co/{PRESET}/resolve/{REVISION}/{item['name']}"
            with urlopen(url, timeout=20) as response, partial.open("wb") as output:
                size = 0
                while chunk := response.read(1024 * 1024):
                    check_cancel(cancelled)
                    size += len(chunk)
                    if size > item["size"]:
                        raise ValueError("Unexpected file size")
                    output.write(chunk)
                    progress(f"Downloading {100 * (completed + size) / TOTAL_BYTES:.1f}%")
            if size != item["size"] or digest_file(partial, item, cancelled) != item["digest"]:
                raise ValueError("File verification failed; retry the download")
            partial.replace(path)
            completed += size
        finally:
            partial.unlink(missing_ok=True)
    check_cancel(cancelled)
    (folder / "download-complete.json").write_text(json.dumps(MANIFEST))
