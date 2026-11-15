"""Install the bundled controller runtime without a development checkout."""
from __future__ import annotations

import shutil
import sys
import tempfile
import zipfile
import fcntl
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .patch import DEFAULT_APP, RECEIPT, contained, copy_app, read_json, write_json


SUPPORT = Path.home() / "Library/Application Support/EndPlayDesktop"


@contextmanager
def storage_lock(support: Path = SUPPORT):
    """Serialize patchers so cleanup cannot remove another install's staging."""
    support.mkdir(parents=True, exist_ok=True)
    with (support / ".storage.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("另一个补丁工具正在操作，请等待其完成后重试。") from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


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

    def install_payload(self, support: Path = SUPPORT) -> Path:
        metadata = self.metadata
        payload = metadata["payload"]
        parent = contained(support, Path("payloads") / self.key)
        destination = contained(parent, payload)
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
                for name in ("mxu", "EndPlayDesktopLauncher"):
                    executable = contained(stage, Path(payload) / name)
                    if executable.is_file():
                        executable.chmod(0o755)
                contained(stage, payload).rename(destination)
        return destination


def restore_backup(app: Path, support: Path = SUPPORT) -> Path:
    receipt = app / RECEIPT
    if receipt.is_file() and read_json(receipt).get("backup"):
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


def backup_directories(support: Path = SUPPORT) -> list[Path]:
    """List only backups made by this tool, without following directory links."""
    parent = support / "backups"
    if parent.is_symlink():
        raise ValueError("备份目录不能是符号链接。")
    if not parent.exists():
        return []
    found = []
    for path in sorted(parent.iterdir()):
        if path.is_symlink() or not path.is_dir():
            continue
        metadata = path / "backup.json"
        original = path / "MaaEnd.app"
        if metadata.is_symlink() or original.is_symlink() or not metadata.is_file():
            continue
        data = read_json(metadata)
        app = data.get("app")
        if data.get("format") == 1 and isinstance(app, str) and Path(app).is_absolute() and original.is_dir():
            found.append(path)
    return found


def known_apps(support: Path, app: Path | None = None) -> set[Path]:
    apps = {DEFAULT_APP.resolve()}
    registry = support / "installations.json"
    if registry.exists():
        data = read_json(registry)
        paths = data.get("apps")
        if data.get("format") != 1 or not isinstance(paths, list) or not all(
                isinstance(path, str) and Path(path).is_absolute() for path in paths):
            raise ValueError("安装记录无法读取，已停止自动清理运行环境。")
        apps.update(Path(path).resolve() for path in paths)
    if app is not None:
        apps.add(app.resolve())
    for backup in backup_directories(support):
        apps.add(Path(read_json(backup / "backup.json")["app"]).resolve())
    return apps


def register_app(app: Path, support: Path = SUPPORT) -> None:
    # Keep non-default installations discoverable even after their backups go.
    apps = known_apps(support, app)
    support.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".installations-", dir=support) as temporary:
        staged = Path(temporary) / "installations.json"
        write_json(staged, {"format": 1, "apps": sorted(str(path) for path in apps)})
        staged.replace(support / "installations.json")


def runtime_references(app: Path) -> set[Path]:
    references = set()
    receipt = app / RECEIPT
    if receipt.is_file():
        runtime = read_json(receipt).get("runtime")
        if runtime:
            references.add(Path(runtime).resolve())
    config = app / "Contents/Resources/EndPlayDesktop/runtime.json"
    if config.is_file():
        settings = read_json(config)
        for key in ("python", "project_dir"):
            if settings.get(key):
                references.add((config.parent / settings[key]).resolve())
    interface = app / "Contents/MacOS/interface.json"
    if interface.is_file():
        for controller in read_json(interface).get("controller", []):
            config = controller.get("endplaydesktop", {})
            for key in ("python", "project_dir"):
                if config.get(key):
                    references.add((interface.parent / config[key]).resolve())
    return references


def cleanup_storage(app: Path, support: Path = SUPPORT) -> dict:
    """Collect unused managed bundles; retained backups pin their own runtime."""
    register_app(app, support)
    references = {Path(__file__).resolve(), Path(sys.executable).resolve()}
    for installed in known_apps(support, app):
        references.update(runtime_references(installed))
    for backup in backup_directories(support):
        references.update(runtime_references(backup / "MaaEnd.app"))
    removed = {"runtimes": 0, "payloads": 0}
    # These are generated caches, never arbitrary user folders. Validate their
    # identifying metadata and keep symlink entries and unknown content intact.
    for folder in removed:
        parent = support / folder
        if parent.is_symlink():
            raise ValueError(f"缓存目录不能是符号链接：{parent}")
        if not parent.exists():
            continue
        for entry in sorted(parent.iterdir()):
            if entry.is_symlink() or not entry.is_dir():
                continue
            if any(path.is_relative_to(entry.resolve()) for path in references):
                continue
            if folder == "runtimes":
                metadata = entry / "EndPlayDesktopPatch.app/Contents/Resources/distribution.json"
                if not metadata.is_file():
                    continue
                data = read_json(metadata)
                if data.get("format") != 2 or entry.name != f"{data.get('version')}-{data.get('build_id')}":
                    continue
            else:
                metadata = entry / "desktop/manifest.json"
                if not metadata.is_file():
                    continue
                data = read_json(metadata)
                expected = {"mxu"} if data.get("format") == 2 else {"controller", "launcher"}
                if data.get("format") not in (2, 3) or set(data.get("files", {})) != expected:
                    continue
            shutil.rmtree(entry)
            removed[folder] += 1
    return removed


def clear_backups(app: Path, support: Path = SUPPORT) -> dict:
    register_app(app, support)
    # A v1 installation may still need its only original Go Agent for migration.
    for installed in known_apps(support, app):
        receipt = installed / RECEIPT
        if receipt.is_file() and read_json(receipt).get("format") == 1:
            raise ValueError("仍有旧版补丁需要备份恢复官方 Agent，请先应用新版补丁或重新安装官方 MaaEnd，再清空备份。")
    backups = backup_directories(support)
    for backup in backups:
        shutil.rmtree(backup)
    return {"status": "backups_cleared", "deleted_backups": len(backups)}
