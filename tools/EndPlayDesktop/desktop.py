"""Install the bundled controller runtime without a development checkout."""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .patch import RECEIPT, contained, copy_app, read_json


SUPPORT = Path.home() / "Library/Application Support/EndPlayDesktop"


@dataclass(frozen=True)
class Runtime:
    project: Path
    python: Path


@dataclass(frozen=True)
class Distribution:
    app: Path

    @property
    def resources(self) -> Path:
        return self.app / "Contents/Resources"

    @property
    def metadata(self) -> dict:
        return read_json(self.resources / "distribution.json")

    @property
    def key(self) -> str:
        metadata = self.metadata
        return f"{metadata['version']}-{metadata['build_id']}"

    def install_runtime(self, support: Path = SUPPORT) -> Runtime:
        parent = contained(support, Path("runtimes") / self.key)
        destination = parent / "EndPlayDesktopPatch.app"
        if not destination.exists():
            parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".runtime-", dir=parent) as temporary:
                staged = Path(temporary) / destination.name
                copy_app(self.app, staged)
                staged.rename(destination)
        runtime = Runtime(destination / "Contents/Resources/runtime_source",
                          destination / "Contents/MacOS/EndPlayDesktopRuntime")
        if not runtime.python.is_file() or not (runtime.project / "tools/EndPlayDesktop/sidecar.py").is_file():
            raise ValueError("内置运行环境不完整，请重新下载补丁工具。")
        return runtime

    def install_payload(self, target_version: str, support: Path = SUPPORT) -> Path:
        metadata = self.metadata
        version = target_version if target_version in metadata["payloads"] else metadata["default_payload"]
        parent = contained(support, Path("payloads") / self.key)
        destination = contained(parent, version)
        if not destination.exists():
            parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".payload-", dir=parent) as temporary:
                stage = Path(temporary)
                with zipfile.ZipFile(self.resources / "payloads.zip") as archive:
                    for member in archive.infolist():
                        path = contained(stage, member.filename)
                        if member.is_dir():
                            path.mkdir(parents=True, exist_ok=True)
                        else:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(member) as source, path.open("wb") as output:
                                shutil.copyfileobj(source, output)
                for name in ("mxu", "go-service"):
                    contained(stage, Path(version) / name).chmod(0o755)
                contained(stage, version).rename(destination)
        return destination


def restore_backup(app: Path, support: Path = SUPPORT) -> Path:
    receipt = app / RECEIPT
    if receipt.is_file():
        backup = Path(read_json(receipt)["backup"])
        if (backup / "backup.json").is_file() and read_json(backup / "backup.json").get("app") == str(app):
            return backup
    candidates = []
    for metadata in (support / "backups").glob("*/backup.json"):
        try:
            if read_json(metadata).get("app") == str(app):
                candidates.append(metadata.parent)
        except (OSError, ValueError):
            continue
    if not candidates:
        raise ValueError("没有找到这个 MaaEnd 的备份。")
    return max(candidates, key=lambda path: path.name)
