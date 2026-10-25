"""Download pinned MLX/GGUF presets, without a Hub cache or model runtime."""

import hashlib
import json
from pathlib import Path
import shutil
import stat
from urllib.request import urlopen

MANIFEST = json.loads((Path(__file__).parent / "data" / "model_manifest.json").read_text())
PRESET = MANIFEST["repo"]
REVISION = MANIFEST["revision"]
GGUF_MANIFEST = json.loads((Path(__file__).parent / "data" / "gguf_manifest.json").read_text())
GGUF_PRESET = GGUF_MANIFEST["repo"]
PRESETS = {PRESET: MANIFEST, GGUF_PRESET: GGUF_MANIFEST}
TOTAL_BYTES = sum(item["size"] for item in MANIFEST["files"])


class DownloadCancelled(Exception):
    pass


def ready(folder, manifest=None):
    manifest = MANIFEST if manifest is None else manifest
    marker = folder / "download-complete.json"
    try:
        return (json.loads(marker.read_text()) == manifest
                and all((folder / item["name"]).stat().st_size == item["size"]
                        for item in manifest["files"]))
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


def download(folder, progress, cancelled, manifest=None):
    manifest = MANIFEST if manifest is None else manifest
    total_bytes = sum(item["size"] for item in manifest["files"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "download-complete.json").unlink(missing_ok=True)
    completed = 0
    for item in manifest["files"]:
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
            url = f"https://huggingface.co/{manifest['repo']}/resolve/{manifest['revision']}/{item['name']}"
            with urlopen(url, timeout=20) as response, partial.open("wb") as output:
                size = 0
                while chunk := response.read(1024 * 1024):
                    check_cancel(cancelled)
                    size += len(chunk)
                    if size > item["size"]:
                        raise ValueError("Unexpected file size")
                    output.write(chunk)
                    progress(f"Downloading {100 * (completed + size) / total_bytes:.1f}%")
            if size != item["size"] or digest_file(partial, item, cancelled) != item["digest"]:
                raise ValueError("File verification failed; retry the download")
            partial.replace(path)
            completed += size
        finally:
            partial.unlink(missing_ok=True)
    check_cancel(cancelled)
    (folder / "download-complete.json").write_text(json.dumps(manifest))


def remove_preset(root, preset):
    """Remove only known app-managed preset files, never custom paths or links."""
    manifest = PRESETS.get(preset)
    if manifest is None:
        raise ValueError('Only built-in downloaded presets can be removed.')
    folder = root / manifest['revision']
    def linked(path):
        if path.is_symlink():
            return True
        return bool(getattr(path.lstat(), 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)) if path.exists() else False
    for path in (root.parent, root, folder):
        if linked(path):
            raise ValueError('Refusing to remove a linked model folder.')
    if not folder.exists():
        return
    allowed = {'download-complete.json'}
    for item in manifest['files']:
        allowed.update((item['name'], item['name'] + '.part'))
    files = list(folder.iterdir())
    for path in files:
        if path.name not in allowed or linked(path) or not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('Preset folder contains unknown files or links; nothing was removed.')
    marker = folder / 'download-complete.json'
    if marker.exists() and json.loads(marker.read_text()) != manifest:
        raise ValueError('The completion record does not identify this preset; nothing was removed.')
    # All checks complete before the first unlink. No recursive deletion.
    for path in files:
        path.unlink()
    folder.rmdir()
